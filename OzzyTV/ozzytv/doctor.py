"""Why isn't it on the screen?

A black screen with an X cursor means the X server came up and nothing drew on
it — the app died on startup and the session script looped. The reason went to
the journal, which is no help at all while you are standing in front of a
television.

So: one command that walks the chain from "can Python find this package" to "can
VLC open a window", and says which link is broken and what to type. Each check is
a plain function returning (ok, detail, fix), so the whole report is testable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    state: str
    detail: str = ""
    fix: str = ""


def _import(module: str) -> tuple[bool, str]:
    try:
        __import__(module)
        return True, ""
    except BaseException as e:      # libvlc raises OSError, not ImportError
        return False, f"{type(e).__name__}: {e}"


def check_package() -> Check:
    """The one that produced the black screen.

    The launchers run `python3 -m ozzytv` with no PYTHONPATH, so the package has
    to be findable on its own. Installing verified the import WITH PYTHONPATH
    set, which proves nothing about that — and a .pth written into a directory
    this Python does not read fails exactly here, after a clean install.
    """
    r = subprocess.run([sys.executable, "-c", "import ozzytv, sys; print(ozzytv.__file__)"],
                       capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    if r.returncode == 0:
        return Check("the ozzytv package", OK, r.stdout.strip())
    return Check(
        "the ozzytv package", FAIL,
        "python3 cannot import it without PYTHONPATH, which is how it is started",
        "sudo ./install/install.sh   (re-run it; it repairs this)")


def check_tk() -> Check:
    ok, err = _import("tkinter")
    if ok:
        return Check("tkinter (the menus)", OK)
    return Check("tkinter (the menus)", FAIL, err, "sudo apt install python3-tk")


def check_vlc() -> Check:
    ok, err = _import("vlc")
    if not ok:
        return Check("VLC (playback)", FAIL, err,
                     "sudo apt install vlc python3-vlc")
    try:
        import vlc
        inst = vlc.Instance([])
        if inst is None:
            return Check("VLC (playback)", FAIL, "libVLC refused to start",
                         "clear vlc_args in settings.json, then try again")
        inst.release()
    except Exception as e:
        return Check("VLC (playback)", FAIL, f"{type(e).__name__}: {e}",
                     "sudo apt install --reinstall vlc")
    return Check("VLC (playback)", OK)


def check_display() -> Check:
    if not os.environ.get("DISPLAY"):
        return Check("a screen to draw on", WARN,
                     "DISPLAY is not set — expected when run over ssh",
                     "this only matters on the Pi's own screen")
    ok, err = _import("tkinter")
    if not ok:
        return Check("a screen to draw on", FAIL, "tkinter is missing")
    import tkinter as tk
    try:
        root = tk.Tk()
        size = f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}"
        root.destroy()
        return Check("a screen to draw on", OK, f"{os.environ['DISPLAY']} ({size})")
    except Exception as e:
        return Check("a screen to draw on", FAIL, f"{type(e).__name__}: {e}",
                     "check that X is running and this user may open it")


def check_media(settings) -> Check:
    found = [r for r in settings.roots if r.is_dir()]
    if not found:
        return Check("the media folder", FAIL,
                     "none of these exist: " + ", ".join(str(r) for r in settings.roots),
                     "put films in one of them, or edit media_roots in settings.json")
    from . import library
    roots = library.scan(found)
    files = sum(1 for r in roots for n in r.walk() if n.is_playable)
    if not files:
        return Check("the media folder", WARN, f"{found[0]} has nothing playable in it",
                     "copy some films or programmes into it")
    return Check("the media folder", OK, f"{files} playable file(s) under {found[0]}")


def check_allowed(settings, store) -> Check:
    from . import library, picks
    total = 0
    for root in library.scan(settings.roots):
        rules = store.rules_for(root.root)
        total += sum(1 for n in root.walk()
                     if n.is_playable and picks.decide_rel(rules, n.rel).visible)
    if total:
        return Check("what the child can see", OK, f"{total} programme(s) allowed")
    return Check("what the child can see", WARN, "nothing is allowed yet",
                 'ozzytv --allow "/media/ozzy/<folder>"   (this is by design)')


def check_pin(store) -> Check:
    from .security import PinGate
    if PinGate(store).is_set():
        return Check("the grown-up PIN", OK)
    return Check("the grown-up PIN", WARN, "no PIN set — the first person in can set one",
                 "ozzytv --set-pin")


def check_service() -> Check:
    if not shutil.which("systemctl"):
        return Check("start at boot", WARN, "no systemd here")
    user = os.environ.get("SUDO_USER") or os.environ.get("USER") or ""
    unit = f"ozzytv@{user}.service"
    r = subprocess.run(["systemctl", "is-enabled", unit], capture_output=True, text=True)
    if r.stdout.strip() == "enabled":
        return Check("start at boot", OK, unit)
    return Check("start at boot", WARN, f"{unit} is not enabled",
                 "sudo ./install/install.sh")


def check_build() -> Check:
    """Which version is actually on this machine.

    Twice now a fix has been reported as "still broken" because the installer
    was re-run against an older checkout, and nothing on the Pi could tell the
    two apart. `install.sh` stamps what it installed; this reads it back.
    """
    stamp = Path(__file__).resolve().parent.parent / "BUILD"
    if not stamp.is_file():
        return Check("which version is installed", WARN,
                     "no BUILD stamp — installed by hand, or by an older installer",
                     "sudo ./install/install.sh")
    return Check("which version is installed", OK, stamp.read_text().strip())


def check_drawing() -> Check:
    """Does the drawing code RUN? Not whether Tk is importable — whether every
    screen paints. This is the check that was missing when the app died in
    TkView.__init__ on every boot and the only symptom was a black screen."""
    from . import selftest
    bad = [r for r in selftest.run() if not r.ok]
    if not bad:
        return Check("drawing the screens", OK, "every screen paints")
    return Check("drawing the screens", FAIL,
                 f"{bad[0].screen}: {bad[0].error}",
                 "ozzytv --selftest   (for the rest)")


def run(settings, store) -> list[Check]:
    return [check_build(), check_package(), check_tk(), check_vlc(),
            check_drawing(), check_display(),
            check_media(settings), check_allowed(settings, store),
            check_pin(store), check_service()]


def report(checks: list[Check], out=None) -> int:
    """Print it, and return 1 if anything is actually broken.

    `out` is resolved here rather than in the signature: a default of
    `sys.stdout` is bound once at import, which writes past anything that
    replaces stdout later.
    """
    out = out if out is not None else sys.stdout
    mark = {OK: "  ok  ", WARN: " note ", FAIL: " FAIL "}
    print("\nOzzy TV — what is and is not working\n", file=out)
    for c in checks:
        print(f"[{mark[c.state]}] {c.name}", file=out)
        if c.detail:
            print(f"           {c.detail}", file=out)
        if c.fix and c.state != OK:
            print(f"           fix: {c.fix}", file=out)
    broken = [c for c in checks if c.state == FAIL]
    print(file=out)
    if broken:
        print(f"{len(broken)} thing(s) will stop it starting. "
              f"Start with the first FAIL above.\n", file=out)
        return 1
    print("Nothing is broken. If the screen is still black, look at:\n"
          "    journalctl -u ozzytv@$USER -n 50 --no-pager\n", file=out)
    return 0
