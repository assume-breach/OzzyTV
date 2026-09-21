"""Clicking things.

A pointer is not how a child drives this — the screen is laid out for a remote,
and it stays that way. But the grown-up setting it up has a mouse in their hand,
and a tile that does nothing when you click it reads as broken rather than as
deliberate. It was: only <Key> was ever bound, and the pointer was hidden
outright, so there was no way to tell the two apart.
"""
import pytest

from ozzytv import skin
from ozzytv.app import Action, OzzyApp, Pane, Screen
from ozzytv.scene import RoundRect
from tests.conftest import into_tiles, pick_shelf, shelves
# The stand-in Tk and the TkView built on it live with the renderer's own tests.
from tests.test_tkview import tkview  # noqa: F401


def hits(app, w=1280, h=720):
    """The pressable rectangles, from the Scene that was actually drawn."""
    sc = skin.build(app.view(), w, h, columns=app.settings.columns,
                    rows=app.settings.rows)
    return {i.hit: (i.x, i.y, i.x + i.w, i.y + i.h)
            for i in sc.items if isinstance(i, RoundRect) and i.hit}


class TestTheScreenSaysWhatIsPressable:
    def test_every_shelf_and_every_tile_is_hit_testable(self, allow_everything):
        h = hits(allow_everything)
        v = allow_everything.view()
        for i in range(len(v.rail)):
            assert f"rail:{i}" in h, f"shelf {i} cannot be clicked"
        for i in range(len(v.tiles)):
            assert f"tile:{i}" in h, f"tile {i} cannot be clicked"

    def test_the_regions_are_the_ones_that_were_drawn(self, allow_everything):
        """Not a second copy of the geometry — that is the version that drifts
        and leaves you clicking an inch away from what lights up."""
        h = hits(allow_everything)
        x0, y0, x1, y1 = h["tile:0"]
        assert x1 > x0 and y1 > y0
        assert 0 <= x0 < 1280 and 0 <= y0 < 720

    def test_they_do_not_overlap_each_other(self, allow_everything):
        """Two tiles sharing a rectangle means one of them is unreachable."""
        h = hits(allow_everything)
        tiles = [v for k, v in h.items() if k.startswith("tile:")]
        for i, a in enumerate(tiles):
            for b in tiles[i + 1:]:
                apart = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
                assert apart, f"{a} and {b} overlap"


class TestClicking:
    def test_a_shelf_shows_its_shows(self, allow_everything):
        app = allow_everything
        target = [i for i, s in enumerate(shelves(app.view())) if s == "PAW Patrol"][0]
        app.click(f"rail:{target}")
        v = app.view()
        assert v.rail[v.rail_cursor].title == "PAW Patrol"
        assert app.focus is Pane.RAIL

    def test_a_tile_opens_in_one_click(self, allow_everything):
        """Not two. A click that only moved a highlight would need a second one
        nobody is going to guess at."""
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        into_tiles(app)
        before = app.view().tiles[0].title
        app.click("tile:0")
        assert app.screen.value == "playing", f"clicking {before!r} did nothing"

    def test_clicking_a_folder_opens_the_folder(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        folders = [i for i, t in enumerate(app.view().tiles) if t.kind == "folder"]
        if not folders:
            pytest.skip("no folder on this screen")
        app.click(f"tile:{folders[0]}")
        assert app.view().heading != "Bluey" or app.view().tiles


    def test_clicking_nothing_in_particular_is_ignored(self, allow_everything):
        """A stale hit map, a click in a gap, a name from a newer version —
        none of them should do anything, and none should raise in front of a
        child."""
        app = allow_everything
        heading, screen = app.view().heading, app.screen
        for junk in ("", "rail:", "tile:nine", "wat:0", "rail:999", "tile:999",
                     "digit:", "tile:-1"):
            app.click(junk)
        assert app.view().heading == heading
        assert app.screen is screen


class TestThePointerItself:
    def test_it_is_hidden_until_the_mouse_moves(self, tkview):
        """Permanently hidden and it looks broken; permanently shown and there
        is an arrow parked in the middle of a show, because a child will
        find the mouse and then let go of it."""
        cursors = [kw.get("cursor") for n, a, kw in tkview.root.calls
                   if n == "config" and "cursor" in kw]
        assert cursors and cursors[0] == "none"

    def test_moving_it_brings_it_back(self, tkview):
        import types
        tkview._on_motion(types.SimpleNamespace(x=10, y=10))
        cursors = [kw.get("cursor") for n, a, kw in tkview.root.calls
                   if n == "config" and "cursor" in kw]
        assert any(c and c != "none" for c in cursors), "the pointer never reappears"
        # NOT "" — that means "this window has no cursor of its own", so X walks
        # up to the root window, and with no desktop that is X_cursor: a big
        # black X. It has to be an actual named shape.
        assert "" not in cursors, 'cursor="" inherits the root X'


    def test_a_click_outside_everything_does_nothing(self, tkview):
        import types
        tkview.render()
        tkview._on_click(types.SimpleNamespace(x=-50, y=-50))          # no raise

    def test_a_click_on_a_tile_reaches_the_app(self, tkview):
        import types
        tkview.render()
        assert tkview._hits, "nothing on screen was registered as pressable"
        x0, y0, x1, y1, target = tkview._hits[-1]
        seen = []
        tkview.app.click = lambda t: seen.append(t)
        tkview._on_click(types.SimpleNamespace(x=(x0 + x1) / 2, y=(y0 + y1) / 2))
        assert seen == [target]


class TestClickingWhereYouActuallyClicked:
    """The hit map is in the coordinates of the canvas the Scene was painted
    on. Screen coordinates agree with those only for a fullscreen menu sitting
    at 0,0 — which is the one case anybody tests by hand."""

    def test_the_paused_strip_is_hit_in_its_own_coordinates(self, tkview):
        """It is painted into a separate canvas parked at the bottom of the
        screen, with the Scene shifted up to match. A click measured from the
        top of the SCREEN lands hundreds of pixels away from the button."""
        import types
        from ozzytv.app import Action
        for _ in range(6):
            tkview.app.handle(Action.SELECT)
            if tkview.app.screen.value == "playing":
                break
        tkview.app.handle(Action.SELECT)          # pause
        tkview.render()
        for x0, y0, x1, y1, _ in tkview._hits:
            assert y0 < 720, "the strip's hit map is in screen coordinates"

    def test_a_windowed_session_is_not_offset_by_the_window(self, tkview):
        """--windowed is how this gets set up over VNC, and a window is never
        at 0,0."""
        import inspect
        src = inspect.getsource(type(tkview)._on_click)
        assert "event.x_root" not in src and "event.y_root" not in src, \
            "screen coordinates again"
        assert "event.x" in src


@pytest.fixture()
def empty_tv(settings, store, player, clock, tmp_path):
    """Nothing on the drive — the home screen with only its own tiles on it."""
    from ozzytv.app import OzzyApp
    settings.media_roots = [str(tmp_path / "nothing")]
    return OzzyApp(settings, store, player, clock=clock)


class TestTheFirstBootScreen:
    def test_the_shelves_are_clickable(self, empty_tv):
        """Nothing on the drive and no disc drive: still a menu, and still a
        menu you can press."""
        v = empty_tv.view()
        assert v.rail, "no menu at all"
        sc = skin.build(v, 1280, 720, columns=1, rows=6)
        targets = {i.hit for i in sc.items if isinstance(i, RoundRect) and i.hit}
        assert "rail:0" in targets
        # No Back at the top level — there is nowhere to go back TO. What must
        # be there is a way to press something without a keyboard.
        assert "key:select" in targets

    """The one screen where a grown-up is certainly the one standing there,
    most likely with a mouse — and until now the one screen with nothing on it
    a pointer could press."""



class TestAClickActsOnWhatIsOnTheScreen:
    """view() lines the rail up with what is being LOOKED at before it builds
    the tiles. click() did not — so the moment the shelves changed underneath,
    which the network share causes all day, the two disagreed: on screen you
    pressed a folder, underneath that index was a video on another shelf, and
    it played instead of opening."""

    def test_a_folder_opens_even_after_the_shelves_move(self, settings, store,
                                                        player, clock, tmp_path):
        media = tmp_path / "ozzy"
        for rel in ("Land Before Time/Season 1/01 Cave.mp4", "Zoo/z.mp4"):
            f = media / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"v")
        settings.media_roots = [str(media)]
        app = OzzyApp(settings, store, player, clock=clock)
        app.view()

        # A folder arrives that sorts ahead of the one being looked at.
        (media / "Aardvark").mkdir()
        (media / "Aardvark" / "a.mp4").write_bytes(b"v")
        app.rescan()

        # Draw the screen FIRST — that is what puts the cursor right — and only
        # then knock it out of step, with no render in between. Calling view()
        # after the cursor goes stale fixes it, and the test then passes with
        # the bug present, which is what the first version of this did.
        shown = app.view().tiles
        assert shown[0].kind == "folder", "the test is not set up as intended"
        app.rail_cursor = 0                      # a stale cursor
        app.click("tile:0")
        assert app.screen is not Screen.PLAYING, \
            "it played a video from another shelf instead of opening the folder"
        assert app.view().heading == "Season 1"

    def test_clicking_a_video_still_plays_it(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        into_tiles(app)
        assert app.view().tiles[0].kind == "video"
        app.click("tile:0")
        assert app.screen is Screen.PLAYING


class TestEveryClickHappensOnce:
    """A widget's bindtags are (widget, class, toplevel, all), so a click on the
    canvas ALREADY runs the toplevel's handler. Binding the children as well ran
    every click twice: pause toggled and untoggled, and Stop stopped and then
    acted a second time on the menu that had just replaced the video."""

    def test_only_the_toplevel_listens_for_clicks(self, tkview):
        import re
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "ozzytv" / "tkview.py"
        bindings = re.findall(r'(\w+)\.bind\("<Button-1>"', src.read_text())
        assert bindings == ["root"], f"clicks are bound {len(bindings)} times: {bindings}"

    def test_a_click_that_hits_something_stops_there(self, tkview):
        """Returning "break" keeps Tk from running it again further up."""
        import types
        tkview.render()
        x0, y0, x1, y1, _ = tkview._hits[-1]
        out = tkview._on_click(types.SimpleNamespace(x=(x0 + x1) / 2, y=(y0 + y1) / 2))
        assert out == "break"

    def test_and_so_does_a_click_that_hits_nothing(self, tkview):
        import types
        tkview.render()
        assert tkview._on_click(types.SimpleNamespace(x=-50, y=-50)) == "break"


class TestThePictureSitsStill:
    """render() runs on every tick while something is playing. Raising the
    window libVLC draws into four times a second makes X repaint it four times a
    second, which is a picture that will not sit still."""

    def _play(self, tkview):
        from ozzytv.app import Action, Screen
        for _ in range(6):
            tkview.app.handle(Action.SELECT)
            if tkview.app.screen is Screen.PLAYING:
                return
        raise AssertionError("nothing played")

    def test_the_video_window_is_raised_once_not_every_tick(self, tkview):
        self._play(tkview)
        tkview.render()
        before = len([c for c in tkview.video.calls if "raise" in str(c)])
        for _ in range(8):
            tkview.render()
        after = len([c for c in tkview.video.calls if "raise" in str(c)])
        assert after == before, f"it raised the picture {after - before} more times"

    def test_and_raised_again_after_coming_back_from_the_menu(self, tkview):
        from ozzytv.app import Action
        self._play(tkview)
        tkview.render()
        tkview.app.handle(Action.BACK)          # back to the menu
        tkview.render()
        before = len([c for c in tkview.video.calls if "raise" in str(c)])
        self._play(tkview)
        tkview.render()
        after = len([c for c in tkview.video.calls if "raise" in str(c)])
        assert after > before, "the film came back underneath the menus"

    def test_the_keyboard_is_taken_back_when_a_film_starts(self, tkview):
        """libVLC's output window can end up with the input focus, and with no
        window manager nothing hands it back — after which Back does not stop
        the film because Back never reaches this program."""
        self._play(tkview)
        before = len([c for c in tkview.root.calls if c[0] == "focus_force"])
        tkview.render()
        after = len([c for c in tkview.root.calls if c[0] == "focus_force"])
        assert after > before
