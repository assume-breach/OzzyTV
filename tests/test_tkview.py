"""Running the drawing layer without a display.

tkview.py is the one file the rest of the suite cannot reach: it needs Tk, which
needs a screen. Left at that it would be the only part of a child's television
that nothing ever executes — and it is the part that runs on every keypress.

So Tk is replaced with a stub that records what it was asked to do. This does not
prove anything about how the screen LOOKS; it proves the code runs, that every
screen has a painter, that keys reach the app, and that video and menus are never
on top of each other. Those are the failures that make the app unusable rather
than ugly.
"""
import sys
import types

import pytest

from ozzytv.app import Action, Screen
from ozzytv.picks import ROOT_KEY, Mark


class FakeWidget:
    """Records calls instead of drawing.

    Anything not modelled returns a recorder, so a method this test does not know
    about does not fail here — it fails on a real Tk, which is the honest place
    for it to fail. The exception is anything where real Tk's behavior is
    SURPRISING rather than merely unmodelled: a permissive stub turns those into
    a black screen on a Raspberry Pi and a green suite here. See FakeCanvas."""
    def __init__(self, *a, **kw):
        self.calls = []
        self.placed = True
        self.stack = []

    def __getattr__(self, name):
        def rec(*a, **kw):
            self.calls.append((name, a, kw))
            if name in ("winfo_width",):
                return 1280
            if name in ("winfo_height",):
                return 720
            if name == "winfo_id":
                return 4242
            if name == "winfo_ismapped":
                return 1
            return None
        return rec

    def place(self, **kw):
        self.placed = True

    def place_forget(self):
        self.placed = False

    def tkraise(self, *a):
        self.stack.append("lift")

    lift = tkraise          # what Misc does: on a Frame the two are one method

    def lower(self, *a):
        self.stack.append("lower")

    @property
    def tk(self):
        """`widget.tk.call("raise", w)` — the only way to raise a Canvas widget,
        since a Canvas aliases away every method name that would do it."""
        outer = self

        class Interp:
            def call(self, *args):
                outer.calls.append((" ".join(str(a) for a in args), (), {}))
                if args and args[0] == "raise":
                    outer.stack.append("lift")
        return Interp()

    def __str__(self):
        return f".!{type(self).__name__.lower()}"

    def delete(self, *a):
        self.calls.append(("delete", a, {}))

    def create_text(self, *a, **kw):
        self.calls.append(("create_text", a, kw))

    def create_rectangle(self, *a, **kw):
        self.calls.append(("create_rectangle", a, kw))

    def bind(self, *a, **kw):
        self.calls.append(("bind", a, kw))

    def after(self, ms, fn=None, *a):
        return "timer"

    def mainloop(self):
        pass


class TclError(Exception):
    pass


class FakeCanvas(FakeWidget):
    """A Canvas, with the one difference from a Frame that matters.

    tkinter's Canvas ends with

        lower = tag_lower
        lift = tkraise = tag_raise

    so on a Canvas NONE of those raise the widget — every one acts on a canvas
    item, and with no item named Tcl fails with

        wrong # args: should be ".!canvas raise tagOrId ?aboveThis?"

    This suite first used one permissive FakeWidget for Canvas and Frame alike,
    so `canvas.lift()` was recorded as a raise and every test passed over an app
    that died in TkView.__init__ on every boot. The correction modelled `lift`
    only — and `tkraise`, the name the fix had switched to, fell straight
    through to the permissive base class. The same bug shipped twice off the
    back of a half-modelled alias. Whatever tkinter aliases, this aliases."""

    def tag_raise(self, *a):
        if not a:
            raise TclError('wrong # args: should be '
                           '".!canvas raise tagOrId ?aboveThis?"')
        self.calls.append(("tag_raise", a, {}))

    lift = tkraise = tag_raise          # exactly as tkinter writes it

    def tag_lower(self, *a):
        if not a:
            raise TclError('wrong # args: should be '
                           '".!canvas lower tagOrId ?belowThis?"')
        self.calls.append(("tag_lower", a, {}))

    lower = tag_lower


class FakeRoot(FakeWidget):
    def __init__(self, *a, **kw):
        super().__init__()
        self.bindings = {}

    def bind(self, seq, fn):
        self.bindings[seq] = fn

    def protocol(self, *a, **kw):
        pass


@pytest.fixture()
def tkview(monkeypatch, allow_everything):
    """TkView, wired to a Tk that records rather than draws."""
    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = FakeRoot
    fake_tk.Canvas = FakeCanvas       # NOT the same as a Frame — see FakeCanvas
    fake_tk.Frame = FakeWidget
    fake_tk.TclError = TclError
    fake_font = types.ModuleType("tkinter.font")
    fake_font.Font = lambda **kw: types.SimpleNamespace(**kw)
    fake_tk.font = fake_font
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.font", fake_font)
    monkeypatch.delitem(sys.modules, "ozzytv.tkview", raising=False)
    from ozzytv.tkview import TkView
    return TkView(allow_everything, fullscreen=True)


def texts(widget):
    """Everything the screen was asked to write. create_text puts the string in a
    keyword, not the third positional argument."""
    return [kw["text"] for name, a, kw in widget.calls
            if name == "create_text" and "text" in kw]


class TestEveryScreenPaints:
    def test_the_grid(self, tkview):
        tkview.render()
        drawn = " ".join(str(t) for t in texts(tkview.canvas))
        assert "Bluey" in drawn and "ozzy" in drawn

    def test_a_folder(self, tkview):
        tkview.app.handle(Action.SELECT)          # rail -> tiles
        tkview.app.handle(Action.SELECT)          # open the first folder
        tkview.render()
        assert "Series 1" in " ".join(str(t) for t in texts(tkview.canvas))


    def test_every_kind_of_shape_reaches_the_canvas(self, tkview):
        """The scene is mostly circles and rounded boxes. If a primitive were
        silently skipped the screen would still draw, just wrong — and this is
        the only file that can catch it."""
        tkview.render()
        kinds = {name for name, _a, _kw in tkview.canvas.calls}
        assert {"create_polygon", "create_oval", "create_rectangle",
                "create_text"} <= kinds

    def test_the_parent_list(self, tkview):
        tkview.app.handle(Action.PARENT)          # no PIN set: straight in
        tkview.render()
        drawn = " ".join(str(t) for t in texts(tkview.canvas))
        assert "Choose what Ozzy can watch" in drawn and "Films" in drawn

    def test_an_empty_drive_still_draws_the_television(self, tkview, tmp_path):
        """A Roku with nothing installed still shows you a Roku."""
        tkview.app.settings.media_roots = [str(tmp_path / "nothing")]
        tkview.app.rescan()
        tkview.render()
        drawn = " ".join(str(t) for t in texts(tkview.canvas))
        assert "ozzy" in drawn, "the logo went with the menu"
        assert "Ozzy TV" in drawn or "Home" in drawn

    def test_a_long_title_does_not_stop_the_paint(self, tkview, library_dir):
        # 200, not 300: ext4 caps a filename at 255 bytes, so a longer one tests
        # the filesystem rather than the renderer.
        (library_dir / ("A Very Long Show Name " * 7).strip().replace(" ", "-")[:200]
         ).with_suffix(".mp4").write_bytes(b"v")
        tkview.app.rescan()
        tkview.render()                            # must not raise


class TestVideoAndMenusAreNeverBothOnScreen:
    def _play_something(self, tkview):
        for _ in range(4):                        # rail -> tiles -> folder -> play
            tkview.app.handle(Action.SELECT)
        assert tkview.app.screen is Screen.PLAYING, tkview.app.view()

    def test_playing_raises_the_video_and_hides_the_paused_strip(self, tkview):
        self._play_something(tkview)
        tkview.render()
        assert tkview.video.stack[-1] == "lift"
        assert tkview.overlay.placed is False, "the strip was left over the picture"

    def test_pausing_shows_the_strip(self, tkview):
        self._play_something(tkview)
        tkview.app.handle(Action.SELECT)           # pause
        tkview.render()
        assert tkview.overlay.placed is True
        drawn = " ".join(str(t) for t in texts(tkview.overlay))
        assert "Play" in drawn, "no visible way to resume a paused film"

    def test_the_paused_strip_is_not_the_full_screen_canvas(self, tkview):
        """Tk widgets are opaque: a full-screen canvas lifted over the video does
        not overlay the picture, it replaces it with a rectangle of background."""
        self._play_something(tkview)
        tkview.app.handle(Action.SELECT)
        tkview.render()
        assert tkview.overlay is not tkview.canvas

    def test_no_sky_is_painted_over_the_show(self, tkview):
        """The strip is a slice of the bottom of the screen; a backdrop drawn into
        it is a skyful of clouds squashed into a letterbox."""
        self._play_something(tkview)
        tkview.app.handle(Action.SELECT)
        tkview.render()
        bands = [c for c in tkview.overlay.calls if c[0] == "create_rectangle"]
        assert len(bands) < 20, "that looks like a gradient got in"

    def test_stopping_brings_the_menus_back(self, tkview):
        self._play_something(tkview)
        tkview.app.handle(Action.BACK)
        tkview.render()
        assert tkview.canvas.stack[-1] == "lift"
        assert tkview.overlay.placed is False


class TestKeysReachTheApp:
    def _key(self, tkview, keysym):
        import types as t
        tkview._on_key(t.SimpleNamespace(keysym=keysym))

    def test_right_crosses_into_the_tiles(self, tkview):
        self._key(tkview, "Right")
        assert tkview.app.view().focus == "grid"

    def test_and_left_comes_back(self, tkview):
        self._key(tkview, "Right")
        self._key(tkview, "Left")
        assert tkview.app.view().focus == "rail"

    def test_down_moves_the_shelf_list(self, tkview):
        before = tkview.app.view().rail_cursor
        self._key(tkview, "Down")
        assert tkview.app.view().rail_cursor == before + 1

    def test_a_remotes_media_keys_work_too(self, tkview):
        """Cheap USB remotes send XF86 keysyms, not Return and Escape."""
        for _ in range(4):
            self._key(tkview, "Return")
        assert tkview.app.screen is Screen.PLAYING
        self._key(tkview, "XF86AudioStop")
        assert tkview.app.screen is Screen.BROWSE

    def test_digits_reach_the_keypad(self, tkview):
        tkview.app.pin.set_pin("1379")
        self._key(tkview, "p")
        for d in "1379":
            self._key(tkview, d)
        self._key(tkview, "Return")
        assert tkview.app.screen is Screen.PARENT

    def test_an_unknown_key_is_ignored(self, tkview):
        before = tkview.app.view()
        self._key(tkview, "Super_L")
        assert tkview.app.view() == before

    def test_q_does_not_quit_from_the_childs_screen(self, tkview):
        self._key(tkview, "q")
        assert tkview.app.should_quit is False


class TestStartup:
    def test_vlc_is_given_a_window_to_draw_in(self, tkview):
        tkview._attach_video()
        assert tkview.app.player.window_id == 4242

    def test_a_vlc_that_refuses_the_window_does_not_stop_the_app(self, tkview):
        def boom(_):
            raise RuntimeError("no X window")
        tkview.app.player.attach = boom
        tkview._attach_video()                     # logged, not raised

    def test_the_tick_does_not_redraw_a_still_grid(self, tkview):
        """Building a View stats every tile to decide whether it shows a resume
        mark; four times a second against an SD card is a steady drip of I/O for
        a screen that is not changing."""
        tkview.render()
        tkview._last_screen = tkview.app.screen.value
        before = len(tkview.canvas.calls)
        for _ in range(8):
            tkview._tick()
        assert len(tkview.canvas.calls) == before


class TestARealTkNotJustThisStub:
    """The stub is generous — an unmodelled method records a call and returns.
    That is deliberate, but it means anything where real Tk is SURPRISING has to
    be modelled here, or the suite is green while the Pi shows a black screen.

    These are the surprises found the hard way, one reboot at a time."""

    def test_the_menus_are_raised_without_a_name_a_canvas_has_aliased(self, tkview):
        """`lift = tkraise = tag_raise` on a Canvas: BOTH names raise a canvas
        ITEM, not the widget, and with none named Tcl answers "wrong # args".
        FakeCanvas fails the same way, so this is not a spelling test — put
        either name back and every test in this file errors."""
        tkview.render()
        assert tkview.canvas.stack, "the menu canvas was never raised"
        assert not [c for c in tkview.canvas.calls if c[0] == "tag_raise"], \
            "that raised a canvas item, which is not what was meant"

    def test_both_aliases_are_modelled_not_just_the_one_that_bit_first(self):
        """Modelling `lift` and leaving `tkraise` permissive is how the same bug
        shipped twice. Whatever tkinter aliases, FakeCanvas aliases."""
        import test_tkview as me
        assert me.FakeCanvas.lift is me.FakeCanvas.tag_raise
        assert me.FakeCanvas.tkraise is me.FakeCanvas.tag_raise
        assert me.FakeCanvas.lower is me.FakeCanvas.tag_lower
        for name in ("lift", "tkraise", "lower"):
            with pytest.raises(me.TclError):
                getattr(me.FakeCanvas(), name)()

    def test_real_tkinter_still_aliases_them_that_way(self):
        """The one assertion against the real thing. It runs on the Pi, where
        the suite is also meant to run, and would catch tkinter changing its
        mind about this in some future Python."""
        tkinter = pytest.importorskip("tkinter",
                                      reason="not here; this one runs on the Pi")
        assert tkinter.Canvas.lift is tkinter.Canvas.tag_raise
        assert tkinter.Canvas.tkraise is tkinter.Canvas.tag_raise
        assert tkinter.Frame.tkraise is tkinter.Misc.tkraise

    def test_the_source_never_calls_lift_on_a_canvas(self):
        """Belt and braces, and it reads as the rule it is.

        By AST, not by grep: `sym.lower()` is a perfectly good string method on
        the same line shape, and a check that cannot tell them apart is a check
        somebody deletes."""
        import ast
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[1] / "ozzytv" / "tkview.py"
        widgets = {"canvas", "overlay", "video", "root", "c"}
        for node in ast.walk(ast.parse(src.read_text())):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("lift", "lower", "tkraise")
                    and not node.args):
                continue
            recv = node.func.value
            name = (recv.attr if isinstance(recv, ast.Attribute)
                    else recv.id if isinstance(recv, ast.Name) else "")
            assert name not in widgets, (
                f"{src.name}:{node.lineno} — {name}.{node.func.attr}() resolves "
                f"to tag_raise/tag_lower on a Canvas; use _raise(widget)")


class TestASessionWithNoWindowManager:
    """The kiosk runs bare X: no window manager, no taskbar, nothing for a child
    to reach. Two things a WM normally does then do not happen by themselves."""

    def test_the_window_is_sized_explicitly_as_well_as_asked_to_be_fullscreen(
            self, tkview):
        """`-fullscreen` is a request TO the window manager. With none, the
        window can come up at Tk's default size on a black root — which looks
        exactly like a crash."""
        geoms = [a for name, a, kw in tkview.root.calls if name == "geometry"]
        assert geoms, "nothing set an explicit size"
        assert "x" in str(geoms[0][0]) and "+0+0" in str(geoms[0][0])

    def test_it_takes_the_keyboard_focus_itself(self, tkview):
        """Otherwise X leaves focus at PointerRoot, keys go to whatever the
        pointer is over, and the pointer is hidden on the root window: the menus
        draw perfectly and not one button does anything."""
        tkview._take_the_keyboard()
        assert [c for c in tkview.root.calls if c[0] == "focus_force"]

    def test_a_refused_focus_does_not_stop_the_television(self, tkview, monkeypatch):
        def boom():
            raise RuntimeError("no X for you")
        monkeypatch.setattr(tkview.root, "focus_force", boom, raising=False)
        tkview._take_the_keyboard()               # must not raise
