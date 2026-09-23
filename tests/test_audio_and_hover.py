"""Sound on more than the first film, and a pointer that can look without opening.
"""
import types

import pytest

from ozzytv.app import Action, OzzyApp, Pane, Screen
from tests.conftest import into_tiles, pick_shelf
from tests.test_tkview import tkview  # noqa: F401


class TestEachFilmGetsTheSoundDeviceBack:
    """Handing libVLC new media while the old one is still playing leaves the
    audio output open on the previous stream — and an ALSA device opened for one
    sample rate does not re-open for another. Sound on the first film, silence on
    every one after it."""

    def test_the_player_is_stopped_before_new_media_is_opened(self):
        import inspect

        from ozzytv import playback
        src = inspect.getsource(playback.VlcPlayer.open)
        before = src.index("stop()")
        after = src.index("set_media")
        assert before < after, "it hands over new media without letting go first"

    def test_playing_a_second_thing_starts_it_from_the_beginning(self,
                                                                 allow_everything):
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        into_tiles(app)
        app.click("tile:0")
        assert app.screen is Screen.PLAYING
        first = app.playback.now.path
        app.handle(Action.BACK)
        app.click("tile:1")
        assert app.playback.now.path != first
        assert app.playback.now.position_ms == 0


class TestTheAlsaDefaultIsShared:
    """A raw hardware device is opened exclusively and at one fixed rate."""

    def test_the_installer_goes_through_plug_and_dmix(self):
        from pathlib import Path
        body = (Path(__file__).resolve().parents[1]
                / "install" / "install.sh").read_text()
        assert "type plug" in body, "no resampling: a second rate gets silence"
        assert "type dmix" in body, "exclusive device: a second open gets silence"
        assert "defaults.pcm.card" not in body, "that is the raw card again"


class TestLookingWithoutOpening:
    """There was no way to look at a show with a mouse: the only thing a pointer
    could do was open whatever was under it."""

    def test_pointing_at_a_shelf_moves_the_highlight(self, allow_everything):
        app = allow_everything
        names = [r.title for r in app.view().rail]
        target = names.index("PAW Patrol")
        assert app.point_at(f"rail:{target}") is True
        v = app.view()
        assert v.rail[v.rail_cursor].title == "PAW Patrol"
        assert app.screen is Screen.BROWSE, "it opened something"

    def test_pointing_at_a_show_does_not_play_it(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        into_tiles(app)
        assert app.point_at("tile:1") is True
        assert app.view().cursor == 1
        assert app.screen is Screen.BROWSE, "hovering started a film"

    def test_and_the_click_still_opens_it(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        into_tiles(app)
        app.point_at("tile:1")
        app.click("tile:1")
        assert app.screen is Screen.PLAYING

    def test_pointing_at_where_it_already_is_changes_nothing(self, allow_everything):
        """Otherwise a pointer sitting still redraws the screen four times a
        second."""
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        into_tiles(app)
        app.point_at("tile:1")
        assert app.point_at("tile:1") is False

    def test_nonsense_is_ignored(self, allow_everything):
        for junk in ("", "tile:", "rail:x", "wat:1", "tile:999", "rail:999"):
            assert allow_everything.point_at(junk) is False


def paints(widget):
    """How many times it was DRAWN on — not how many times it was spoken to.
    Showing the pointer touches every widget's cursor, which is not a repaint."""
    return len([c for c in widget.calls if c[0] in ("delete", "create_text",
                                                    "create_rectangle")])


class TestTheScreenFollowsThePointer:
    def test_moving_over_a_shelf_redraws(self, tkview):
        tkview.render()
        # A shelf that is NOT the one already highlighted — pointing at where
        # the highlight already is correctly does nothing.
        here = tkview.app.view().rail_cursor
        target = next((h for h in tkview._hits
                       if h[4].startswith("rail:") and h[4] != f"rail:{here}"), None)
        assert target, "no other shelf to point at"
        x0, y0, x1, y1, _ = target
        before = paints(tkview.canvas)
        tkview._on_motion(types.SimpleNamespace(x=(x0 + x1) / 2, y=(y0 + y1) / 2))
        assert paints(tkview.canvas) > before, "the highlight never moved"

    def test_but_not_while_a_film_is_playing(self, tkview):
        for _ in range(6):
            tkview.app.handle(Action.SELECT)
            if tkview.app.screen is Screen.PLAYING:
                break
        tkview.render()
        before = paints(tkview.canvas)
        tkview._on_motion(types.SimpleNamespace(x=5, y=5))
        assert paints(tkview.canvas) == before, "it repainted over the film"
