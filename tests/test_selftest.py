"""The check that would have caught the bug that shipped twice.

`ozzytv --selftest` draws every screen with no display, so a Pi can prove its
own UI paints before anybody is standing in front of a television. These tests
are about the self-test being worth trusting: one that passes on broken code is
worse than none, because it is what the installer now relies on.
"""
import io

from ozzytv import selftest


class TestItActuallyDraws:
    def test_every_screen_paints(self):
        results = selftest.run()
        assert results, "it checked nothing"
        assert all(r.ok for r in results), [(r.screen, r.error) for r in results]

    def test_it_covers_the_screens_that_matter(self):
        names = {r.screen for r in selftest.run()}
        for expected in ("the menu", "a folder", "the grown-up keypad",
                         "playing", "paused", "ask a grown-up"):
            assert expected in names

    def test_it_needs_no_media_of_its_own(self):
        """It builds its library in a temp directory and takes it away again —
        a check that depends on what is plugged into the Pi is not a check."""
        import tempfile
        before = set(__import__("os").listdir(tempfile.gettempdir()))
        selftest.run()
        left = {n for n in __import__("os").listdir(tempfile.gettempdir())
                if n.startswith("ozzytv-selftest-")}
        assert not left - before, f"it left {left} behind"


class TestItFailsOnBrokenCode:
    """The whole value is here. A permissive stand-in Tk accepts anything and
    reports success, which is exactly how 330 passing tests sat on top of an app
    that could not start."""

    def test_the_canvas_models_every_alias_not_just_the_first_one_to_bite(self):
        """tkinter's Canvas ends `lift = tkraise = tag_raise`, so BOTH names act
        on a canvas ITEM and with none named Tcl refuses. Modelling only `lift`
        is how the same bug shipped twice: the fix switched to `tkraise()`, this
        stand-in accepted it, and the television showed the identical error."""
        import pytest
        c = selftest._Canvas()
        assert selftest._Canvas.lift is selftest._Canvas.tag_raise
        assert selftest._Canvas.tkraise is selftest._Canvas.tag_raise
        for name in ("lift", "tkraise"):
            with pytest.raises(selftest._TclError) as e:
                getattr(c, name)()
            assert "raise tagOrId" in str(e.value)
        c.tag_raise("some-item")          # naming an item is fine

    def test_and_offers_the_way_that_actually_raises_the_widget(self):
        """Tcl's own `raise`, reached through the interpreter handle, where
        there is no Python-level alias to land on."""
        c = selftest._Canvas()
        c.tk.call("raise", str(c))
        assert any("raise" in call for call in c.calls)

    def test_a_frame_is_not_a_canvas(self):
        """Frames have no such alias, which is why the video frame was fine and
        the menus were not — and why one stand-in for both hid it."""
        selftest._Widget().lift()         # must not raise

    def test_a_broken_render_is_reported_not_swallowed(self, monkeypatch):
        import ozzytv.skin as skin
        monkeypatch.setattr(skin, "build",
                            lambda *a, **kw: (_ for _ in ()).throw(ValueError("nope")))
        results = selftest.run()
        assert any(not r.ok for r in results)
        assert "nope" in " ".join(r.error for r in results)


class TestTheReport:
    def test_a_failure_is_a_non_zero_exit(self):
        out = io.StringIO()
        rc = selftest.report([selftest.Result("the menu", "TclError: boom")], out=out)
        assert rc == 1
        assert "the menu" in out.getvalue() and "boom" in out.getvalue()
        assert "black screen" in out.getvalue()

    def test_all_clear_is_zero(self):
        out = io.StringIO()
        assert selftest.report([selftest.Result("the menu")], out=out) == 0
        assert "Every screen draws." in out.getvalue()
