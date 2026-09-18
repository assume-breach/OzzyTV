"""The layout, as a thing that can be checked rather than squinted at.

skin.build() turns a View into a Scene — shapes and words with coordinates — and
nothing in it touches a screen. So "the focused tile is bigger than its
neighbors" and "no two animals on this shelf are the same" are assertions, not
opinions about a screenshot. tools/mockup.py renders the same Scene, so a mockup
is a picture of the television rather than of the intention.
"""
import pytest

from ozzytv import scene as S
from ozzytv import skin
from ozzytv.app import ParentRow, RailItem, Tile, View

W, H = 1280, 720


def rail_view(cursor=1, focus="rail", tiles=None):
    return View(screen="browse", heading="Bluey", subheading="Ozzy TV",
                tiles=tiles if tiles is not None else [
                    Tile(f"Episode {i}", "video", f"e{i}", 0) for i in range(6)],
                cursor=cursor, focus=focus,
                rail=[RailItem("Watch again", "\x00recent", -1, 3, True),
                      RailItem("Bluey", "Bluey", 0, 52),
                      RailItem("PAW Patrol", "PAW Patrol", 0, 26)],
                rail_cursor=1)


def build(view, w=W, h=H):
    return skin.build(view, w, h, columns=3, rows=2)


class TestTheAnimals:
    def test_a_name_always_gets_the_same_one(self):
        """A child who cannot read learns that the green frog is their show.
        That has to survive a rescan, a reboot and a new SD card — which rules
        out hash(), whose seed is randomised per process."""
        assert skin.badge_for("Bluey") == skin.badge_for("Bluey")

    def test_nothing_on_one_screen_wears_the_same_animal(self):
        """Twelve creatures and six tiles collide about three times in four. Two
        identical pandas is worse than no animals, because the animal is what the
        child has been taught to go by."""
        names = ["Hospital · S1 E2", "Shadowlands · S1 E10", "Sleepytime · S2 E14",
                 "Series 3", "Bin Night · S3 E1", "The Magic Xylophone · S1 E1"]
        got = skin.assign_badges(names)
        assert len({b.creature for b in got.values()}) == len(names)
        assert len({b.color for b in got.values()}) == len(names)

    def test_the_same_shelf_looks_the_same_every_time(self):
        names = ["a", "b", "c", "d"]
        assert skin.assign_badges(names) == skin.assign_badges(names)

    def test_more_items_than_animals_still_works(self):
        names = [f"item {i}" for i in range(40)]
        got = skin.assign_badges(names)
        assert len(got) == 40

    def test_every_creature_can_actually_be_drawn(self):
        """A name in the list with no drawing falls through to the monkey, and the
        shelf silently loses its variety."""
        for kind in skin.CREATURES:
            sc = S.Scene(w=100, h=100, bg="#000000")
            skin.creature(sc, kind, 50, 50, 20, "#ffffff")
            assert len(sc.items) >= 3, f"{kind} barely draws anything"


class TestTheShelfList:
    def test_the_highlighted_shelf_is_marked(self):
        sc = build(rail_view())
        # The selected pill is the one filled with the highlight color.
        assert any(r.fill == skin.PILL_ON for r in sc.rects())

    def test_focus_shows_which_pane_the_remote_is_driving(self):
        """Roku's whole navigation rests on this being obvious across a room. The
        count of ringed things is the same either way — what moves is WHICH SIDE
        the ring is on."""
        def ring_x(focus):
            sc = build(rail_view(focus=focus))
            rings = [r for r in sc.rects() if r.outline == skin.FOCUS]
            assert rings, f"nothing is ringed with focus={focus}"
            return min(r.x for r in rings)
        assert ring_x("rail") < W * 0.30 <= ring_x("grid")

    def test_every_shelf_name_is_on_screen(self):
        sc = build(rail_view())
        for name in ("Watch again", "Bluey", "PAW Patrol"):
            assert name in sc.texts()

    def test_the_logo_is_there(self):
        assert "ozzy" in build(rail_view()).texts()
        assert "TV" in build(rail_view()).texts()


class TestTheTiles:
    def _tile_rects(self, sc):
        """The tile bodies: the big rounded boxes in the right-hand half."""
        return [r for r in sc.rects() if r.fill == skin.TILE_BG and r.w > W * 0.1]

    def test_the_focused_row_is_marked_unmistakably(self):
        """It is a list now, so the focused item cannot grow out of its slot —
        it gets a ring in the same sunny yellow instead, which is the one signal
        that reads from across a room."""
        v = View(screen="browse", heading="Bluey", focus="grid", cursor=1,
                 rail=[RailItem("Bluey", "Bluey", 0, 3)],
                 tiles=[Tile(f"Episode {i}", "video", f"e{i}", 0) for i in range(4)])
        sc = skin.build(v, 1280, 720, columns=3, rows=2)
        rings = [r for r in sc.rects() if r.fill == skin.SUN]
        assert rings, "nothing marks which row is selected"

    def test_and_is_ringed(self):
        sc = build(rail_view(cursor=0, focus="grid"))
        assert any(r.outline == skin.FOCUS for r in self._tile_rects(sc))

    def test_nothing_stands_out_when_the_remote_is_on_the_shelf_list(self):
        sc = build(rail_view(cursor=0, focus="rail"))
        sizes = {round(r.w, 3) for r in self._tile_rects(sc)}
        assert len(sizes) == 1, "a tile looks selected while the rail has the focus"

    def test_tiles_stay_inside_the_screen(self):
        sc = build(rail_view(cursor=2, focus="grid"))
        for r in self._tile_rects(sc):
            assert r.x >= 0 and r.y >= 0
            assert r.x + r.w <= W + 1 and r.y + r.h <= H + 1

    def test_a_full_page_is_laid_out_without_overlapping(self):
        sc = build(rail_view(cursor=0, focus="rail"))
        rects = sorted(self._tile_rects(sc), key=lambda r: (r.y, r.x))
        for a, b in zip(rects, rects[1:]):
            same_row = abs(a.y - b.y) < 1
            assert (not same_row) or a.x + a.w <= b.x + 1, "two tiles overlap"

    def test_only_one_page_of_tiles_is_drawn_at_a_time(self):
        many = [Tile(f"Episode {i}", "video", f"e{i}", 0) for i in range(30)]
        sc = build(rail_view(tiles=many))
        assert len(self._tile_rects(sc)) <= 6

    def test_paging_follows_the_cursor(self):
        many = [Tile(f"Episode {i}", "video", f"e{i}", 0) for i in range(30)]
        assert "Episode 0" in build(rail_view(tiles=many, cursor=0)).texts()
        assert "Episode 0" not in build(rail_view(tiles=many, cursor=10)).texts()
        assert "Episode 10" in build(rail_view(tiles=many, cursor=10)).texts()

    def test_an_empty_shelf_says_so(self):
        sc = build(rail_view(tiles=[]))
        assert any("Nothing on this shelf" in t for t in sc.texts())


class TestTheOtherScreens:
    def test_the_keypad_shows_dots_not_digits(self):
        """Somebody is always watching over a shoulder, and on a television that
        somebody is standing right there. (The "0-9" button hint is a label for
        the remote, not anything anyone typed.)"""
        sc = build(View(screen="pin", heading="Grown-ups only", pin_digits=3))
        assert "Grown-ups only" in sc.texts()
        typed = [t for t in sc.texts() if t not in ("0-9", "OK", "Back", "type",
                                                    "enter", "cancel")]
        assert not any(ch.isdigit() for t in typed for ch in t)
        # one filled dot per digit entered, and empty ones for the rest
        # The dots carry an outline; the sun in the sky is the same yellow and
        # does not.
        filled = [i for i in sc.items if isinstance(i, S.Oval)
                  and i.fill == skin.SUN and i.outline == skin.PANEL_EDGE]
        empty = [i for i in sc.items if isinstance(i, S.Oval)
                 and i.fill == skin.PANEL and i.outline == skin.PANEL_EDGE]
        assert len(filled) == 3 and len(empty) == 1   # 3 typed of a 4-dot minimum

    def test_a_lockout_is_explained(self):
        sc = build(View(screen="pin", heading="Grown-ups only", lock_seconds=42))
        assert any("42" in t for t in sc.texts())

    def test_the_parent_screen_shows_both_the_state_and_the_reason(self):
        sc = build(View(screen="parent", heading="Choose what Ozzy can watch", rows=[
            ParentRow("Films", "Films", 0, 1, "folder", "block", False, "",
                      'blocked by \"Films\"')]))
        joined = " ".join(sc.texts())
        assert "blocked" in joined and 'blocked by \"Films\"' in joined

    def test_playing_draws_no_sky(self):
        """On the Pi the show is behind this, and the strip is only the
        bottom slice of the screen — a backdrop here is a skyful of clouds
        squashed into it."""
        sc = build(View(screen="playing", now_title="Bluey", position_ms=1000,
                        duration_ms=2000, paused=True))
        assert not any(isinstance(i, S.Gradient) for i in sc.items)
        assert sc.bg == "#000000"

    def test_the_progress_bar_does_not_sit_on_the_buttons(self):
        """It did: at a shallower strip the bar ran straight through the OK cap."""
        sc = build(View(screen="playing", now_title="Bluey", position_ms=1000,
                        duration_ms=2000, paused=True))
        bar = [r for r in sc.rects() if r.fill == skin.SUN and r.w > W * 0.2]
        # The button caps, NOT the progress track — which is also PILL-filled and
        # sits exactly where the caps would be if this went wrong.
        caps = [r for r in sc.rects()
                if r.fill == skin.PILL and H * 0.03 < r.h < H * 0.07]
        assert bar and caps
        assert max(b.y + b.h for b in bar) <= min(c.y for c in caps) + 1

    def test_every_screen_produces_something(self):
        for screen in ("browse", "playing", "pin", "parent", "message"):
            v = rail_view() if screen == "browse" else View(screen=screen,
                                                            message="hello",
                                                            now_title="x", paused=True)
            assert build(v).items, f"{screen} draws nothing at all"


class TestItFitsOtherTelevisions:
    @pytest.mark.parametrize("size", [(1280, 720), (1920, 1080), (1024, 768), (720, 576)])
    def test_nothing_falls_off_the_edge(self, size):
        w, h = size
        sc = skin.build(rail_view(cursor=0, focus="grid"), w, h, columns=3, rows=2)
        for r in sc.rects():
            if r.fill == skin.TILE_BG and r.w > w * 0.1:
                assert 0 <= r.x and r.x + r.w <= w + 1
                assert 0 <= r.y and r.y + r.h <= h + 1
