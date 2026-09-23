"""git clone, run the installer, reboot, arrive at the menu.

That is the whole deployment story, and every step of it happens on a machine
nobody is watching. An installer that is only ever run for real is one nobody
finds out is broken until a Raspberry Pi has already been wiped to try it — so
the destinations are overridable and the whole thing runs here against a
temporary root, with apt, systemctl and usermod replaced by recorders.

What this cannot prove is that X starts and VLC decodes. What it can prove is
that the files land, the service is enabled, the app imports from where it was
put, and running it twice is safe.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

STUBS = {
    "apt-get": "#!/bin/sh\nprintf 'apt-get %s\\n' \"$*\" >> \"$FAKE_LOG\"\nexit 0\n",
    "systemctl": """#!/bin/sh
printf 'systemctl %s\\n' "$*" >> "$FAKE_LOG"
# `is-enabled` must answer truthfully, or the installer's own final check is a
# rubber stamp.
if [ "$1" = is-enabled ]; then
    grep -q "systemctl enable $2" "$FAKE_LOG" && exit 0
    exit 1
fi
[ "$1" = get-default ] && { cat "${FAKE_DEFAULT_TARGET:-/dev/null}" 2>/dev/null \
                            || echo multi-user.target; exit 0; }
exit 0
""",
    "usermod": "#!/bin/sh\nprintf 'usermod %s\\n' \"$*\" >> \"$FAKE_LOG\"\nexit 0\n",
    "getent": """#!/bin/sh
printf 'getent %s\\n' "$*" >> "$FAKE_LOG"
[ "$2" = 1000 ] && { echo "pi:x:1000:1000::$FAKE_HOME:/bin/sh"; exit 0; }
echo "$2:x:1000:1000::$FAKE_HOME:/bin/sh"
""",
    "id": "#!/bin/sh\n[ \"$1\" = -u ] && { echo 0; exit 0; }\n[ \"$1\" = -un ] && { echo pi; exit 0; }\necho 0\n",
    "chown": "#!/bin/sh\nexit 0\n",
    # Samba's tools. testparm must actually LOOK at the file: a stub that always
    # says yes turns the installer's own validation into a rubber stamp, which
    # is the mistake this suite already shipped once.
    "testparm": """#!/bin/sh
for a in "$@"; do
    case "$a" in -*) continue ;; esac
    [ -f "$a" ] || { echo "no such file: $a" >&2; exit 1; }
    grep -q '^\\[global\\]' "$a" || { echo "no [global] section" >&2; exit 1; }
    exit 0
done
exit 0
""",
    "pdbedit": "#!/bin/sh\nprintf 'pdbedit %s\\n' \"$*\" >> \"$FAKE_LOG\"\nexit 0\n",
    "smbpasswd": "#!/bin/sh\nprintf 'smbpasswd %s\\n' \"$*\" >> \"$FAKE_LOG\"\nexit 0\n",
    "hostname": """#!/bin/sh
[ "$1" = -s ] && { echo ozzytv; exit 0; }
[ "$1" = -I ] && { echo "192.168.1.50 "; exit 0; }
echo ozzytv
""",
    # A python3 that answers as a Pi would AFTER apt has run. apt is stubbed
    # here, so without this the installer's (correct, and newly fatal) checks for
    # python3-tk and python3-vlc fail on a machine that simply has not got them —
    # which is a fact about this container, not about the installer.
    #
    # Everything else goes to a throwaway VIRTUALENV, not to this container's
    # python3. The installer now proves the import with no PYTHONPATH, so the
    # .pth has to land somewhere python genuinely reads — and a venv is the only
    # way to get a writable, real site-packages directory here. A directory that
    # merely looks like one (~/.local/lib/pythonX.Y/site-packages) is NOT read
    # when the process is root, which is exactly what an installer is.
    "python3": """#!/bin/sh
case "$*" in
  *"import tkinter"*|*"import vlc"*) exit 0 ;;
esac
exec "$FAKE_PYTHON" "$@"
""",
}


@pytest.fixture(scope="session")
def venv(tmp_path_factory):
    """A real Python with a real, writable site-packages.

    Session-scoped because building one costs a couple of seconds and every test
    here wants the same thing: somewhere the installer's .pth can land that the
    interpreter will actually read.
    """
    d = tmp_path_factory.mktemp("venv")
    # No --system-site-packages: a hermetic interpreter, so nothing this
    # container happens to have installed can make an import succeed that would
    # fail on a Pi. tkinter and vlc are answered by the python3 stub instead.
    made = subprocess.run([sys.executable, "-m", "venv", str(d)],
                          capture_output=True, text=True)
    assert made.returncode == 0, made.stdout + made.stderr
    python = d / "bin" / "python3"
    got = subprocess.run([str(python), "-c",
                          "import site; print(site.getsitepackages()[0])"],
                         capture_output=True, text=True)
    assert got.returncode == 0, got.stdout + got.stderr
    return python, Path(got.stdout.strip())


@pytest.fixture()
def install(tmp_path, venv):
    """Run install/install.sh against a throwaway root."""
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        f = bin_dir / name
        f.write_text(body)
        f.chmod(0o755)
    root = tmp_path / "root"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    python, site = venv
    # The venv is shared, so clear any .pth a previous test left behind — one
    # test's install must not be what makes the next one's import succeed.
    (site / "ozzytv.pth").unlink(missing_ok=True)
    log = tmp_path / "calls.log"
    log.write_text("")

    base_env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_LOG": str(log),
        "FAKE_HOME": str(home),
        "HOME": str(home),
        "SUDO_USER": "pi",
        "OZZYTV_APP_DIR": str(root / "opt" / "ozzytv"),
        "OZZYTV_BIN": str(root / "usr" / "local" / "bin"),
        "OZZYTV_UNIT_DIR": str(root / "etc" / "systemd" / "system"),
        "OZZYTV_MEDIA": str(root / "media" / "ozzy"),
        "OZZYTV_XWRAPPER": str(root / "etc" / "X11" / "Xwrapper.config"),
        "FAKE_PYTHON": str(python),
        "OZZYTV_SMB_CONF": str(root / "etc" / "samba" / "smb.conf"),
        # Deliberately NO OZZYTV_SITE: let the installer find site-packages
        # the way it does on a Pi. Overriding it would test the override.
    }

    def run(*args):
        env = dict(base_env)
        # run() builds a clean environment, so anything a test sets with
        # monkeypatch has to be handed through explicitly.
        for passthrough in ("FAKE_DEFAULT_TARGET", "OZZYTV_SITE", "OZZYTV_SHARE_PRIVATE"):
            if passthrough in os.environ:
                env[passthrough] = os.environ[passthrough]
        # From a NEUTRAL directory. Run from the repo root, `python3 -c "import
        # ozzytv"` finds the source tree through '' on sys.path and the .pth
        # check passes whatever the .pth says — which is not how systemd starts
        # it, and hid the very failure this is here to catch.
        return subprocess.run(["/bin/sh", str(REPO / "install" / "install.sh"), *args],
                              capture_output=True, text=True, env=env, timeout=180,
                              cwd=str(tmp_path))

    run.root = root
    run.env = base_env
    run.site = site
    run.home = home
    run.log = log
    return run


class TestAFreshPi:
    def test_it_succeeds(self, install):
        p = install()
        assert p.returncode == 0, p.stdout + p.stderr

    def test_the_app_lands_where_the_service_will_look_for_it(self, install):
        install()
        assert (install.root / "opt" / "ozzytv" / "ozzytv" / "app.py").is_file()
        assert (install.root / "opt" / "ozzytv" / "ozzytv" / "skin.py").is_file()

    def test_and_python_can_import_it_from_there(self, install):
        install()
        pth = install.site / "ozzytv.pth"
        assert pth.is_file()
        assert pth.read_text().strip() == str(install.root / "opt" / "ozzytv")

    def test_the_command_is_on_the_path(self, install):
        install()
        cmd = install.root / "usr" / "local" / "bin" / "ozzytv"
        assert cmd.is_file() and os.access(cmd, os.X_OK)

    def test_the_boot_service_is_installed_and_enabled(self, install):
        """The difference between "installed" and "boots into the menu"."""
        install()
        unit = install.root / "etc" / "systemd" / "system" / "ozzytv@.service"
        assert unit.is_file()
        assert "systemctl enable ozzytv@pi.service" in install.log.read_text()

    def test_the_console_login_gets_out_of_the_way(self, install):
        """Otherwise a getty owns tty1 and X cannot have it."""
        install()
        assert "systemctl disable getty@tty1.service" in install.log.read_text()

    def test_x_is_allowed_to_start_from_the_service(self, install):
        """Debian ships needs_root_rights=auto, which refuses from systemd — the
        failure is a black screen and one line buried in the journal."""
        install()
        cfg = (install.root / "etc" / "X11" / "Xwrapper.config").read_text()
        assert "allowed_users=anybody" in cfg and "needs_root_rights=yes" in cfg

    def test_the_gpu_group_is_granted(self, install):
        """Without `video` the Pi decodes on the CPU and 1080p is a slideshow."""
        install()
        assert re.search(r"usermod -aG video\S* pi", install.log.read_text())

    def test_a_media_folder_and_settings_exist_to_be_edited(self, install):
        install()
        assert (install.root / "media" / "ozzy").is_dir()
        settings = install.home / ".local" / "share" / "ozzytv" / "settings.json"
        assert settings.is_file()
        import json
        assert json.loads(settings.read_text())["media_roots"] == [
            str(install.root / "media" / "ozzy")]

    def test_it_says_what_to_do_next(self, install):
        out = install().stdout
        assert "--scan" in out and "--block" in out
        assert "Reboot" in out

    def test_it_says_that_what_you_copy_in_shows_up(self, install):
        """This asserted the opposite until the gate came out, and then went on
        asserting it — which is how the installer kept printing instructions for
        a version of the program that no longer existed."""
        assert "shows up" in install().stdout

class TestTheCheckThatWasARubberStamp:
    """The installer used to verify the import WITH PYTHONPATH set — which proves
    the files were copied and nothing about whether python3 can find them on its
    own. That is exactly how it starts, so a .pth written into a site-packages
    directory this Python does not read passed the check, printed "done", and the
    Pi booted to a black screen with a white X cursor and nothing to explain it."""

    def test_a_pth_that_python_does_not_read_is_caught(self, install, tmp_path):
        """A real directory that is not on sys.path — the exact shape of the
        failure, without having to break a machine to reproduce it."""
        nowhere = tmp_path / "not-on-sys-path"
        nowhere.mkdir()
        p = install_with(install, OZZYTV_SITE=str(nowhere))
        assert p.returncode != 0, "it claimed success with an unreadable .pth"
        assert "PYTHONPATH" in (p.stdout + p.stderr)
        assert not (install.root / "etc" / "systemd" / "system"
                    / "ozzytv@.service").exists(), \
            "it went on to enable a service that cannot start"

    def test_a_working_install_passes_the_same_check(self, install):
        assert install().returncode == 0


def install_with(install, **extra):
    """Re-run the installer with extra environment."""
    import os as _os
    for k, v in extra.items():
        _os.environ[k] = v
    try:
        return install()
    finally:
        for k in extra:
            _os.environ.pop(k, None)


class TestItProvesTheScreensDraw:
    """Importing proves the files arrived. It says nothing about whether the
    menus PAINT — and the bug that cost two reboots was a TclError on the
    third-to-last line of TkView.__init__, which no import check could see."""

    def test_the_installer_draws_every_screen_before_saying_done(self, install):
        out = install().stdout
        assert "checking that every screen draws" in out
        assert "Every screen draws." in out

    def test_a_ui_that_cannot_draw_stops_the_install(self, install, tmp_path):
        """And stops it BEFORE enabling a boot service that would come up black."""
        install()                                     # get a good tree in place
        tkview = install.root / "opt" / "ozzytv" / "ozzytv" / "tkview.py"
        broken = tkview.read_text().replace("_raise(self.canvas)",
                                            "self.canvas.tkraise()")
        assert broken != tkview.read_text(), "the source no longer matches"
        # Break the SOURCE the installer copies from, via a throwaway copy of it.
        repo = tmp_path / "repo"
        shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".pytest_cache"))
        (repo / "ozzytv" / "tkview.py").write_text(broken)
        p = subprocess.run(["/bin/sh", str(repo / "install" / "install.sh")],
                           capture_output=True, text=True, timeout=180,
                           cwd=str(tmp_path), env=install.env)
        assert p.returncode != 0, "it installed a UI that cannot draw a single screen"
        assert "cannot draw its own screens" in (p.stdout + p.stderr)


class TestItSaysWhatItInstalled:
    """Twice a fix was reported as "still broken" because the installer had been
    re-run against an older checkout — a second copy of the repo, or a
    re-downloaded archive beside the first — and nothing on the Pi could tell
    the two apart."""

    def test_a_build_stamp_is_written(self, install):
        install()
        stamp = (install.root / "opt" / "ozzytv" / "BUILD").read_text()
        assert str(REPO) in stamp, "the stamp does not say where it came from"
        assert "installed" in stamp

    def test_and_printed_where_somebody_will_see_it(self, install):
        """From the SAME run that wrote it. Comparing a stamp against a second
        install's output only worked while both landed in the same minute."""
        out = install().stdout
        assert "Ozzy TV is installed." in out
        stamp = (install.root / "opt" / "ozzytv" / "BUILD").read_text().strip()
        assert stamp in out


class TestRunningItAgain:
    def test_it_is_safe_to_re_run(self, install):
        """Which makes it the upgrade path too."""
        assert install().returncode == 0
        p = install()
        assert p.returncode == 0, p.stdout + p.stderr

    def test_a_second_run_does_not_duplicate_the_x_config(self, install):
        install()
        install()
        cfg = (install.root / "etc" / "X11" / "Xwrapper.config").read_text()
        assert cfg.count("needs_root_rights") == 1

    def test_settings_a_parent_edited_are_not_overwritten(self, install):
        install()
        settings = install.home / ".local" / "share" / "ozzytv" / "settings.json"
        settings.write_text('{"media_roots": ["/mnt/films"], "columns": 4}')
        install()
        assert "/mnt/films" in settings.read_text()

    def test_stale_bytecode_from_an_older_version_is_cleared(self, install):
        install()
        junk = install.root / "opt" / "ozzytv" / "ozzytv" / "__pycache__"
        junk.mkdir(parents=True, exist_ok=True)
        stale = junk / "app.cpython-38.pyc"
        stale.write_bytes(b"stale")
        install()
        # __pycache__ itself comes back — the installer's own import check runs
        # after the sweep and recompiles. What must not survive is the bytecode
        # from the older version, which is the half-updated package that looks
        # exactly like a code bug.
        assert not stale.exists()
        assert not any(f.read_bytes() == b"stale" for f in junk.glob("*.pyc"))


class TestOnTheDesktopImage:
    """Raspberry Pi OS Desktop boots a display manager, which owns the screen and
    the virtual terminal Ozzy TV wants. Left alone the two fight over tty1 and the
    Pi comes up to a desktop, a black screen, or an alternation of the two."""

    @pytest.fixture()
    def desktop(self, install, tmp_path):
        dm = install.root / "etc" / "systemd" / "system" / "display-manager.service"
        dm.parent.mkdir(parents=True, exist_ok=True)
        real = install.root / "lib" / "systemd" / "system" / "lightdm.service"
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text("[Unit]\n")
        return install

    def test_it_says_what_it_is_about_to_do(self, install, monkeypatch, tmp_path):
        target = tmp_path / "target"
        target.write_text("graphical.target\n")
        monkeypatch.setenv("FAKE_DEFAULT_TARGET", str(target))
        p = install()
        assert p.returncode == 0
        assert "multi-user" in (p.stdout + p.stderr)

    def test_a_graphical_boot_target_is_switched_to_console(self, install, monkeypatch,
                                                            tmp_path):
        target = tmp_path / "target"
        target.write_text("graphical.target\n")
        monkeypatch.setenv("FAKE_DEFAULT_TARGET", str(target))
        install()
        assert "systemctl set-default multi-user.target" in install.log.read_text()

    def test_and_uninstall_gives_the_desktop_back(self, install, monkeypatch, tmp_path):
        """A Pi that will not boot to anything recognisable is a worse surprise
        than one that never changed."""
        target = tmp_path / "target"
        target.write_text("graphical.target\n")
        monkeypatch.setenv("FAKE_DEFAULT_TARGET", str(target))
        install()
        install("--uninstall")
        assert "systemctl set-default graphical.target" in install.log.read_text()

    def test_a_console_only_pi_is_left_alone(self, install):
        """Raspberry Pi OS Lite has no display manager and boots to multi-user
        already; nothing should be touched."""
        install()
        log = install.log.read_text()
        assert "set-default" not in log


class TestWithoutTheKiosk:
    def test_no_kiosk_skips_the_boot_service(self, install):
        p = install("--no-kiosk")
        assert p.returncode == 0
        assert not (install.root / "etc" / "systemd" / "system" / "ozzytv@.service").exists()
        assert "systemctl disable getty@tty1.service" not in install.log.read_text()

    def test_but_still_installs_the_app(self, install):
        install("--no-kiosk")
        assert (install.root / "opt" / "ozzytv" / "ozzytv" / "app.py").is_file()


class TestUninstall:
    def test_it_puts_the_console_back(self, install):
        install()
        p = install("--uninstall")
        assert p.returncode == 0
        assert "systemctl enable getty@tty1.service" in install.log.read_text()
        assert not (install.root / "opt" / "ozzytv").exists()

    def test_and_leaves_the_media_and_the_choices_alone(self, install):
        install()
        p = install("--uninstall")
        assert (install.root / "media" / "ozzy").is_dir()
        assert (install.home / ".local" / "share" / "ozzytv").is_dir()
        assert "were left alone" in p.stdout


class TestTheSessionScript:
    def test_it_does_not_respawn_in_a_tight_loop(self, tmp_path):
        """Something that cannot start at all would otherwise respawn twice a
        second for ever, filling the journal and the SD card with one line."""
        body = (REPO / "install" / "ozzytv-session").read_text()
        assert "fails=" in body and "sleep 30" in body

    def test_it_says_where_to_look(self, tmp_path):
        assert "journalctl" in (REPO / "install" / "ozzytv-session").read_text()

    def test_screen_blanking_is_turned_off(self):
        """A show is not idle because nobody has pressed a key for ten
        minutes."""
        body = (REPO / "install" / "ozzytv-session").read_text()
        assert "xset s off" in body and "-dpms" in body


class TestTheBootSessionRunsTheCodeThatWasInstalled:
    """`python3 -m ozzytv` puts the CURRENT DIRECTORY first on sys.path, ahead
    of /opt/ozzytv. A stray copy of the source in whatever directory the service
    happens to start in wins — and the app runs code nobody installed, which
    looks exactly like a fix that did not take."""

    def test_the_service_starts_from_a_directory_with_no_source_in_it(self):
        unit = (REPO / "install" / "ozzytv.service").read_text()
        assert "WorkingDirectory=/" in unit

    def test_and_python_drops_the_implicit_path_entry_too(self):
        unit = (REPO / "install" / "ozzytv.service").read_text()
        assert "PYTHONSAFEPATH=1" in unit

    def test_the_failure_on_screen_says_which_build_it_is(self):
        """A failure on the television and a clean bill of health over ssh were
        indistinguishable. Every obvious explanation — a stale install, a second
        copy winning on sys.path, a .pth pointing elsewhere — needs the same
        three facts, and all three have now actually happened."""
        body = (REPO / "install" / "ozzytv-session").read_text()
        assert "identify()" in body
        for fact in ("BUILD", "sys.path", "tkview", "$(pwd)"):
            assert fact in body, f"the failure report does not say {fact}"
        assert "{ identify; python3 -m ozzytv" in body, \
            "the header is not part of what gets logged and shown"


class TestTheNetworkShare:
    """share.sh is not run against a real Samba here — apt and systemctl are
    stubs. What can be checked is the shape of what it writes, and that is where
    the mistakes that matter live: one wrong line in smb.conf is the difference
    between a folder on the family wifi and a folder on the internet."""

    def test_it_shares_only_the_media_folder(self):
        body = (REPO / "install" / "share.sh").read_text()
        assert "path = $MEDIA" in body
        for never in ("path = /", "path = /home", "path = $HOME", "path = /opt"):
            assert never not in body, f"it shares {never}"

    def test_it_is_open_by_default(self):
        """Dropping a film on a Pi should not involve a credential. What keeps
        that reasonable is everything AROUND it, not a password: one folder, and
        only ever the local network."""
        body = (REPO / "install" / "share.sh").read_text()
        assert "guest ok = yes" in body and "guest only = yes" in body
        assert "map to guest = bad user" in body

    def test_and_a_login_is_still_available(self):
        """For anyone who wants one — and Windows, which refuses guest shares."""
        body = (REPO / "install" / "share.sh").read_text()
        assert "--private" in body
        assert "map to guest = never" in body
        assert "guest ok = no" in body

    def test_smb1_is_off(self):
        """It is how most of the well-known file-sharing worms travel."""
        body = (REPO / "install" / "share.sh").read_text()
        assert "server min protocol = SMB2" in body
        assert "client min protocol = SMB2" in body

    def test_it_is_reachable_from_the_house_and_nowhere_else(self):
        body = (REPO / "install" / "share.sh").read_text()
        assert "hosts allow" in body and "hosts deny = 0.0.0.0/0" in body
        assert "192.168." in body and "10." in body

    def test_files_arrive_owned_by_the_user_the_television_runs_as(self):
        """Otherwise they land as somebody else's and the menu stays empty. With
        an open share the guest account IS that user, which is the whole reason
        it is set rather than left as nobody."""
        body = (REPO / "install" / "share.sh").read_text()
        assert "force user = $OWNER" in body
        assert "guest account = $OWNER" in body

    def test_nobody_can_invent_extra_shares(self):
        body = (REPO / "install" / "share.sh").read_text()
        assert "usershare max shares = 0" in body
        assert "load printers = no" in body

    def test_the_old_smb_conf_is_kept_and_restored(self):
        """A Pi that cannot be put back the way it was is a Pi nobody wants to
        try this on."""
        body = (REPO / "install" / "share.sh").read_text()
        assert "before-ozzytv" in body
        assert "--disable" in body

    def test_the_config_is_checked_before_it_is_trusted(self):
        body = (REPO / "install" / "share.sh").read_text()
        assert "testparm" in body, "it never checks the file it just wrote"

    def test_it_parses(self):
        p = subprocess.run(["/bin/sh", "-n", str(REPO / "install" / "share.sh")],
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr

    def test_it_is_set_up_by_the_ordinary_install(self, install):
        """Getting shows onto the machine is not an optional extra. It is
        the second thing anybody needs after the menu appears, and "now copy
        them onto a memory stick and walk them over" is not an answer."""
        install()
        conf = install.root / "etc" / "samba" / "smb.conf"
        assert conf.is_file(), "the share was never configured"
        body = conf.read_text()
        assert f"path = {install.root / 'media' / 'ozzy'}" in body
        assert "[ozzytv]" in body

    def test_the_written_config_has_the_hardening_in_it(self, install):
        """Grepping the script proves the lines were typed. This proves they
        survive into the file Samba actually reads, with the variables filled
        in — which is where a quoting mistake would have eaten one.

        Open does not mean unguarded. No password is one decision; the local
        network, one folder, SMB2 and no usershares are separate ones, and they
        are what makes the first decision a reasonable one to offer."""
        install()
        body = (install.root / "etc" / "samba" / "smb.conf").read_text()
        for line in ("security = user", "server min protocol = SMB2_10",
                     "hosts deny = 0.0.0.0/0", "usershare max shares = 0",
                     "force user = pi", "guest account = pi",
                     "guest ok = yes", "guest only = yes"):
            assert line in body, f"missing from the real config: {line}"
        assert "192.168." in body and "10." in body

    def test_it_never_asks_for_anything(self, install):
        """No login prompt, and nothing left half-configured waiting for one."""
        p = install()
        assert "smbpasswd" not in install.log.read_text()
        body = (install.root / "etc" / "samba" / "smb.conf").read_text()
        assert "valid users" not in body
        assert "No username, no password" in p.stdout

    def test_it_warns_about_windows(self, install):
        """Windows 10 and 11 refuse guest shares out of the box. Finding that
        out from Explorer's error message is a bad afternoon."""
        assert "Windows" in install().stdout

    def test_a_private_share_can_be_asked_for(self, install):
        p = install_with(install, OZZYTV_SHARE_PRIVATE="1")
        assert p.returncode == 0
        body = (install.root / "etc" / "samba" / "smb.conf").read_text()
        assert "map to guest = never" in body and "valid users = pi" in body

    def test_and_stays_private_when_the_installer_is_re_run(self, install):
        """Re-running the installer must not silently reopen a share somebody
        deliberately locked."""
        install_with(install, OZZYTV_SHARE_PRIVATE="1")
        install()
        body = (install.root / "etc" / "samba" / "smb.conf").read_text()
        assert "guest only = yes" not in body, "a re-run threw the login away"

    def test_no_share_skips_it_entirely(self, install):
        install("--no-share")
        assert not (install.root / "etc" / "samba" / "smb.conf").exists()
        assert (install.root / "opt" / "ozzytv" / "ozzytv" / "app.py").is_file(), \
            "--no-share should skip the share, not the install"

    def test_a_share_that_will_not_set_up_does_not_stop_the_install(self, install,
                                                                    tmp_path):
        """A television that works is worth more than a file server that does.
        If Samba cannot be configured, say so and carry on."""
        broken = tmp_path / "stubs" / "testparm"
        broken.write_text("#!/bin/sh\nexit 1\n")
        broken.chmod(0o755)
        p = install()
        assert p.returncode == 0, "a failed share took the whole install down"
        assert "share" in (p.stdout + p.stderr).lower()
        assert (install.root / "etc" / "systemd" / "system"
                / "ozzytv@.service").is_file()

    def test_uninstall_takes_the_share_down_too(self, install):
        install()
        install("--uninstall")
        conf = install.root / "etc" / "samba" / "smb.conf"
        backup = install.root / "etc" / "samba" / "smb.conf.before-ozzytv"
        assert not backup.exists(), "it left its backup lying around"
        assert not conf.exists() or "Ozzy TV" not in conf.read_text()


class TestWhatItTellsYouIsTrue:
    """The installer went on printing instructions for the version before the
    gate came out — including `ozzytv --set-pin`, which is a flag that no longer
    exists. Somebody following its own closing message would get an error and
    reasonably conclude the install was broken."""

    def test_it_never_names_a_flag_the_program_does_not_have(self, install):
        import re
        out = install().stdout
        src = (REPO / "ozzytv" / "__main__.py").read_text()
        real = set(re.findall(r'add_argument\("(--[a-z-]+)"', src))
        for flag in set(re.findall(r"ozzytv (--[a-z-]+)", out)):
            assert flag in real, f"it tells you to run {flag}, which does not exist"

    def test_it_does_not_promise_a_pin(self, install):
        out = install().stdout
        for gone in ("--set-pin", "enter the PIN", "parent PIN"):
            assert gone not in out, f"still says {gone!r}"

    def test_nor_that_things_must_be_allowed_first(self, install):
        out = install().stdout
        assert "Nothing is visible until you allow it" not in out
        assert "shows up" in out, "it never says what actually happens"

    def test_the_dvd_libraries_are_looked_up_not_guessed(self):
        """libdvdread8t64 on Trixie, libdvdread8 on Bookworm, libdvdread7 on
        Bullseye. Naming one and warning when it is missing means every Trixie
        install reports that discs will not play."""
        body = (REPO / "install" / "install.sh").read_text()
        assert "libdvdread8t64" in body
        assert "apt-cache show" in body, "it still guesses at the package name"
