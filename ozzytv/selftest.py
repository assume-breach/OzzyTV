"""Draw every screen, with no display, and report what broke.

This exists because of a bug that shipped twice. `Canvas.lift` is aliased to
`tag_raise` in tkinter, so `canvas.lift()` is a TclError rather than a raise —
and the app died on it in TkView.__init__, before drawing a pixel, on every boot
of every Pi. Nothing on the Pi ran the drawing code until somebody was standing
in front of a television, which is the worst possible moment to find out.

So: a stand-in Tk that records calls instead of drawing, and — where real Tk is
SURPRISING rather than merely absent — fails the way real Tk fails. Every screen
is then rendered through the actual TkView. No X, no display, no VLC.

`ozzytv --selftest` runs it, and install.sh refuses to finish if it fails.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass


class _TclError(Exception):
    pass


class _Interp:
    """The `widget.tk` interpreter handle. `tk.call("raise", w)` is how a widget
    is raised without going through a name a Canvas has aliased away."""

    def __init__(self, widget):
        self.widget = widget

    def call(self, *args):
        self.widget.calls.append(" ".join(str(a) for a in args))


class _Widget:
    """Records instead of drawing. Unknown methods are accepted: this is a smoke
    test, not a mock of Tk."""

    _n = 0

    def __init__(self, *a, **kw):
        self.calls: list[str] = []
        _Widget._n += 1
        self._w = f".!{type(self).__name__.lower().lstrip('_')}{_Widget._n}"
        self.tk = _Interp(self)

    def __str__(self):
        return self._w

    def __getattr__(self, name):
        def rec(*a, **kw):
            self.calls.append(name)
            return {"winfo_width": 1280, "winfo_height": 720,
                    "winfo_screenwidth": 1280, "winfo_screenheight": 720,
                    "winfo_id": 4242}.get(name)
        return rec

    def tkraise(self, *a):
        """Misc's version, which a Frame gets and a Canvas does not."""
        self.calls.append("tkraise")

    lift = tkraise

    def after(self, ms, fn=None, *a):
        return "timer"

    def mainloop(self):
        pass


class _Canvas(_Widget):
    """The one difference from a Frame that matters.

    tkinter's Canvas ends with

        lower = tag_lower
        lift = tkraise = tag_raise

    so on a Canvas NONE of those raise the WIDGET — every one of them acts on a
    canvas ITEM, and with no item named Tcl refuses. Modelling that is the whole
    point of this file, and modelling it only HALF is how the same bug shipped
    twice: `lift()` was caught here, `tkraise()` fell through to the permissive
    base class and reported success while the television showed the identical
    TclError. Whatever tkinter aliases, this aliases.
    """

    def tag_raise(self, *a):
        if not a:
            raise _TclError('wrong # args: should be '
                            '".!canvas raise tagOrId ?aboveThis?"')

    lift = tkraise = tag_raise          # exactly as tkinter writes it

    def tag_lower(self, *a):
        if not a:
            raise _TclError('wrong # args: should be '
                            '".!canvas lower tagOrId ?belowThis?"')

    lower = tag_lower


class _Root(_Widget):
    def protocol(self, *a, **kw):
        pass

    def bind(self, *a, **kw):
        pass


def _fake_tkinter():
    tk = types.ModuleType("tkinter")
    tk.Tk, tk.Canvas, tk.Frame, tk.TclError = _Root, _Canvas, _Widget, _TclError
    font = types.ModuleType("tkinter.font")
    font.Font = lambda **kw: types.SimpleNamespace(**kw)
    tk.font = font
    return tk, font


@dataclass
class Result:
    screen: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _library(tmp):
    """A small, known library. Deliberately NOT the child's real one: the point
    is that every screen draws, and that must not depend on what is plugged in.
    """
    for rel in ("Bluey/Series 1/Bluey.S01E01.The Magic Xylophone.mkv",
                "Bluey/Series 1/Bluey.S01E02.Hospital.mkv",
                "PAW Patrol/Episode 1.mp4",
                "Films/Paddington (2014).mp4"):
        f = tmp / "Videos" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"not really a video")
    return tmp / "Videos"


def run() -> list[Result]:
    """Render every screen through the real TkView against a stand-in Tk."""
    import tempfile
    from pathlib import Path

    from .app import Action, OzzyApp
    from .config import Settings
    from .picks import ROOT_KEY, Mark
    from .playback import FakePlayer
    from .store import Store

    tk, font = _fake_tkinter()
    saved = {k: sys.modules.get(k) for k in ("tkinter", "tkinter.font", "ozzytv.tkview")}
    sys.modules["tkinter"], sys.modules["tkinter.font"] = tk, font
    sys.modules.pop("ozzytv.tkview", None)

    with tempfile.TemporaryDirectory(prefix="ozzytv-selftest-") as td:
        tmp = Path(td)
        root = _library(tmp)
        settings = Settings(media_roots=[str(root)])
        store = Store(tmp / "selftest.db")
        try:
            from .tkview import TkView

            # Every screen the app can be on, driven the way a remote drives it.
            # A fresh app per journey: one screen failing must not be reported as
            # four, and a half-navigated app is not a clean starting point.
            journeys = [
                ("the menu", []),
                ("a folder", [Action.SELECT, Action.SELECT]),
                ("the grown-up keypad", [Action.PARENT]),
                ("playing", [Action.SELECT] * 4),
                ("paused", [Action.SELECT] * 5),
                ("ask a grown-up", None),          # nothing allowed: the other path
            ]
            results = []
            for name, keys in journeys:
                r = Result(name)
                try:
                    app = OzzyApp(settings, store, FakePlayer(duration_ms=600_000))
                    if keys is None:
                        store.clear_marks(app.roots[0].root)
                    else:
                        store.set_mark(app.roots[0].root, ROOT_KEY, Mark.ALLOW)
                    app.rescan()
                    view = TkView(app, fullscreen=True)
                    for k in (keys or []):
                        app.handle(k)
                    view.render()
                except Exception as e:
                    r.error = f"{type(e).__name__}: {e}"
                results.append(r)
            return results
        finally:
            store.close()
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v


def report(results: list[Result], out=None) -> int:
    out = out if out is not None else sys.stdout
    bad = [r for r in results if not r.ok]
    for r in results:
        print(f"[{'  ok  ' if r.ok else ' FAIL '}] drawing {r.screen}", file=out)
        if r.error:
            print(f"           {r.error}", file=out)
    if bad:
        print(f"\n{len(bad)} screen(s) will not draw. This is what a black screen "
              f"looks like from here.\n", file=out)
        return 1
    print("\nEvery screen draws.\n", file=out)
    return 0
