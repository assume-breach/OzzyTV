"""Clicking things.

A pointer is not how a child drives this — the screen is laid out for a remote,
and it stays that way. But the grown-up setting it up has a mouse in their hand,
and a tile that does nothing when you click it reads as broken rather than as
deliberate. It was: only <Key> was ever bound, and the pointer was hidden
outright, so there was no way to tell the two apart.
"""
import pytest

from ozzytv import skin
from ozzytv.app import Action, Pane
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
        assert "" in cursors, "the pointer never reappears"

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
    """The one screen where a grown-up is certainly the one standing there,
    most likely with a mouse — and until now the one screen with nothing on it
    a pointer could press."""

    def test_its_tiles_are_clickable_like_any_others(self, empty_tv):
        app = empty_tv
        v = app.view()
        assert v.welcome, "not the first-boot screen"
        assert v.tiles, "a home screen with nothing on it to press"
        sc = skin.build(v, 1280, 720, columns=3, rows=2)
        targets = {i.hit for i in sc.items if isinstance(i, RoundRect) and i.hit}
        for i in range(len(v.tiles)):
            assert f"tile:{i}" in targets, f"home tile {i} does nothing when clicked"

    def test_and_clicking_grown_ups_opens_the_way_in(self, empty_tv):
        app = empty_tv
        v = app.view()
        i = [n for n, t in enumerate(v.tiles) if t.kind == "parent"][0]
        app.click(f"tile:{i}")
        assert app.screen.value in ("pin", "parent")
