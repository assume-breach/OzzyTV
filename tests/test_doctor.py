"""`ozzytv --doctor` — the answer to "it is just a black screen".

A black screen with a white X cursor means X came up and nothing drew on it: the
app died on startup and the session script looped. The reason went to the
journal, which is no help while you are standing in front of a television. So
the doctor walks the chain and says which link is broken and what to type.

These tests are about the reporting being trustworthy — a doctor that says
"nothing is broken" while the screen is black is worse than no doctor.
"""
import io

import pytest

from ozzytv import doctor
from ozzytv.doctor import FAIL, OK, WARN, Check


class TestTheVerdict:
    def test_a_fail_is_a_non_zero_exit(self):
        rc = doctor.report([Check("x", FAIL, "broken", "do this")], out=io.StringIO())
        assert rc == 1

    def test_warnings_alone_are_not_a_failure(self):
        """"Nothing is allowed yet" is how a fresh install is SUPPOSED to look."""
        rc = doctor.report([Check("x", OK), Check("y", WARN, "not yet")],
                           out=io.StringIO())
        assert rc == 0

    def test_it_prints_the_fix_for_what_is_broken(self):
        out = io.StringIO()
        doctor.report([Check("the ozzytv package", FAIL, "cannot import",
                             "sudo ./install/install.sh")], out=out)
        text = out.getvalue()
        assert "the ozzytv package" in text
        assert "sudo ./install/install.sh" in text

    def test_it_does_not_nag_about_things_that_are_fine(self):
        out = io.StringIO()
        doctor.report([Check("VLC (playback)", OK, "", "sudo apt install vlc")], out=out)
        assert "apt install" not in out.getvalue()

    def test_a_clean_bill_says_where_to_look_next(self):
        """Because "everything is fine" and a black screen is exactly when
        somebody needs the journalctl line."""
        out = io.StringIO()
        doctor.report([Check("x", OK)], out=out)
        assert "journalctl" in out.getvalue()


class TestTheCheckThatMatters:
    """The import is checked in a subprocess with PYTHONPATH REMOVED, because
    that is how systemd starts it. Checking it in-process — or with PYTHONPATH
    left in place — is the rubber stamp that let a broken install report success
    and a Pi boot to nothing."""

    def test_the_package_check_strips_pythonpath(self, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/somewhere/that/would/hide/the/problem")
        seen = {}

        def fake_run(cmd, **kw):
            seen.update(kw.get("env") or {})
            class R:
                returncode = 0
                stdout = "/opt/ozzytv/ozzytv/__init__.py"
            return R()

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)
        assert doctor.check_package().state == OK
        assert "PYTHONPATH" not in seen

    def test_an_unimportable_package_is_a_fail_with_the_repair(self, monkeypatch):
        def fake_run(cmd, **kw):
            class R:
                returncode = 1
                stdout = ""
                stderr = "ModuleNotFoundError: No module named 'ozzytv'"
            return R()

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)
        c = doctor.check_package()
        assert c.state == FAIL
        assert "install.sh" in c.fix


class TestWhatIsOnTheDrive:
    def test_a_library_with_films_in_it_passes(self, settings, store):
        c = doctor.check_media(settings)
        assert c.state == OK and "playable" in c.detail

    def test_a_missing_media_folder_names_the_paths_it_tried(self, settings):
        settings.media_roots = ["/no/such/place", "/nor/this"]
        c = doctor.check_media(settings)
        assert c.state == FAIL
        assert "/no/such/place" in c.detail and "/nor/this" in c.detail

    def test_an_empty_folder_is_a_note_not_a_failure(self, settings, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        settings.media_roots = [str(empty)]
        assert doctor.check_media(settings).state == WARN


class TestWhatTheChildCanSee:
    def test_an_empty_drive_is_reported(self, settings, store, tmp_path):
        settings.media_roots = [str(tmp_path / "nothing")]
        c = doctor.check_allowed(settings, store)
        assert c.state == WARN
        assert "--scan" in c.fix

    def test_what_is_on_the_drive_is_counted(self, settings, store):
        c = doctor.check_allowed(settings, store)
        assert c.state == OK
        assert c.detail.split()[0].isdigit()


class TestTheWholeRun:
    def test_it_checks_everything_and_survives_a_machine_missing_all_of_it(
            self, settings, store):
        """This container has no Tk, no libVLC and no display — which is the
        harshest version of the Pi this exists for, and it must still produce a
        report rather than a traceback."""
        checks = doctor.run(settings, store)
        names = [c.name for c in checks]
        for expected in ("the ozzytv package", "tkinter (the menus)",
                         "VLC (playback)", "the media folder"):
            assert expected in names
        assert all(c.state in (OK, WARN, FAIL) for c in checks)

    def test_the_cli_flag_is_wired_up(self, settings, store, monkeypatch, capsys):
        from ozzytv import __main__ as entry
        monkeypatch.setattr(entry, "load_settings", lambda: settings)
        monkeypatch.setattr(doctor, "run", lambda s, st: [Check("x", OK)])
        rc = entry.main(["--doctor"])
        assert rc == 0
        assert "what is and is not working" in capsys.readouterr().out
