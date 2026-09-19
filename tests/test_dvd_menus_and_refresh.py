"""Three things that were each invisible from inside the code.

A DVD menu belongs to the DISC. New files appear while nobody is pressing
anything. And the mouse pointer sits on top of the one window this program does
not own. All three went wrong in the same way: the code was right about its own
state and wrong about something outside it.
"""
import tempfile
from pathlib import Path

import pytest

from tests.test_tkview import tkview  # noqa: F401

from ozzytv import discs
from ozzytv.app import Action, OzzyApp, Screen
from ozzytv.playback import FakePlayer  # noqa: F401


class FakeWatcher:
    def __init__(self, found):
        self._found = list(found)

    def snapshot(self):
        return list(self._found)

    def start(self):
        pass


@pytest.fixture()
def disc_tv(settings, store, player, clock, tmp_path):
    settings.media_roots = [str(tmp_path / "empty")]
    app = OzzyApp(settings, store, player, clock=clock)
    app.discs = FakeWatcher([discs.Disc("/dev/sr0", "DVD", True)])
    i = [n for n, t in enumerate(app.view().tiles) if t.kind == "dvd"][0]
    app.click(f"tile:{i}")
    assert app.screen is Screen.PLAYING
    app.player.menu = True          # the disc's own menu is up
    return app


class TestOnceTheFilmStartsTheControlsAreOurs:
    """Routing everything to the disc is how playback ended up with no controls
    at all: past the menu, Up seeked nowhere and OK did nothing."""

    def test_ok_pauses_the_film(self, disc_tv):
        disc_tv.player.menu = False
        disc_tv.handle(Action.SELECT)
        assert disc_tv.player.state().value == "paused"
        assert disc_tv.player.navigated == [], "it sent OK to a disc that is playing"

    def test_the_arrows_seek(self, disc_tv):
        disc_tv.player.menu = False
        disc_tv.playback.now.duration_ms = 600_000
        disc_tv.handle(Action.RIGHT)
        assert disc_tv.player.navigated == []

    def test_pause_always_works_even_if_the_disc_says_it_is_in_a_menu(self, disc_tv):
        """Nothing important is allowed to depend on the menu heuristic."""
        disc_tv.player.menu = True
        disc_tv.handle(Action.PLAY_PAUSE)
        assert disc_tv.player.state().value == "paused"
        assert disc_tv.player.navigated == []

    def test_and_so_does_back(self, disc_tv):
        disc_tv.player.menu = True
        disc_tv.handle(Action.BACK)
        assert disc_tv.screen is Screen.BROWSE


class TestADiscMenuBelongsToTheDisc:
    """libVLC draws it and only libVLC can move its highlight. Handled as
    ordinary playback keys, Up seeks forward a minute and OK pauses — which is
    how you end up unable to start the film, and able to pause a menu."""

    def test_ok_works_the_menu_instead_of_pausing(self, disc_tv):
        disc_tv.handle(Action.SELECT)
        assert disc_tv.player.navigated == ["activate"]
        assert disc_tv.player.state().value != "paused", "it paused a menu"

    def test_the_arrows_move_the_highlight_instead_of_seeking(self, disc_tv):
        for a in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
            disc_tv.handle(a)
        assert disc_tv.player.navigated == ["up", "down", "left", "right"]
        assert disc_tv.playback.now.position_ms == 0, "it seeked inside a menu"

    def test_back_is_still_ours(self, disc_tv):
        """The only way off the disc. A menu with no way out is a television
        that needs unplugging."""
        disc_tv.handle(Action.BACK)
        assert disc_tv.screen is Screen.BROWSE
        assert "back" not in disc_tv.player.navigated

    def test_volume_is_still_ours(self, disc_tv):
        before = disc_tv.playback.volume
        disc_tv.handle(Action.VOLUME_UP)
        assert disc_tv.playback.volume != before

    def test_a_FILE_is_not_a_disc_and_still_pauses(self, allow_everything):
        app = allow_everything
        for _ in range(6):
            app.handle(Action.SELECT)
            if app.screen is Screen.PLAYING:
                break
        app.handle(Action.SELECT)
        assert app.player.state().value == "paused"
        assert app.player.navigated == [], "it sent menu keys to an mp4"


class TestTheScreenFindsOutAboutNewShows:
    """The library refreshed on its own and the television went on showing the
    old picture: the drawing layer redraws on a keypress and when the SCREEN
    changes, and a folder appearing on the drive is neither."""

    def test_a_folder_arriving_asks_for_a_redraw(self, settings, store, player,
                                                 clock, tmp_path):
        media = tmp_path / "ozzy"
        media.mkdir()
        settings.media_roots = [str(media)]
        app = OzzyApp(settings, store, player, clock=clock)
        assert app.needs_redraw is False
        (media / "Paw Patrol").mkdir()
        (media / "Paw Patrol" / "S01E01.mp4").write_bytes(b"v")
        clock.advance(10)
        app.tick()
        assert app.needs_redraw is True, "the screen is never told"
        assert any(r.title == "Paw Patrol" for r in app.view().rail)

    def test_nothing_changing_asks_for_nothing(self, allow_everything, clock):
        allow_everything.needs_redraw = False
        clock.advance(10)
        allow_everything.tick()
        assert allow_everything.needs_redraw is False

    def test_a_disc_going_in_asks_for_a_redraw_too(self, settings, store, player,
                                                   clock, tmp_path):
        settings.media_roots = [str(tmp_path / "empty")]
        app = OzzyApp(settings, store, player, clock=clock)
        app.discs = FakeWatcher([discs.Disc("/dev/sr0", "DVD", False)])
        app.tick()
        app.needs_redraw = False
        app.discs = FakeWatcher([discs.Disc("/dev/sr0", "DVD", True)])
        clock.advance(10)
        app.tick()
        assert app.needs_redraw is True, "a disc going in never reaches the screen"


class TestTheDrawingLayerActsOnIt:
    def test_the_tick_redraws_when_asked(self, tkview):
        tkview.render()
        # Pin the screen to what it already is, so ONLY the flag can cause a
        # redraw. Left empty, _last_screen differs on the first tick and the
        # tick redraws whatever the flag says — which makes this test pass
        # against the bug it is here to catch.
        tkview._last_screen = tkview.app.screen.value
        before = len(tkview.canvas.calls)
        tkview.app.needs_redraw = True
        tkview._tick()
        assert len(tkview.canvas.calls) > before, "it ignored the request"
        assert tkview.app.needs_redraw is False, "and never cleared it"

    def test_but_not_otherwise(self, tkview):
        tkview.render()
        tkview.app.needs_redraw = False
        tkview._last_screen = tkview.app.screen.value
        before = len(tkview.canvas.calls)
        tkview._tick()
        assert len(tkview.canvas.calls) == before, "it redrew a screen nothing changed on"


class TestThePointerDoesNotStrobeTheFilm:
    """<Motion> fires on every pixel of movement, and reconfiguring the window
    libVLC draws into makes X clear and repaint it."""

    def test_moving_the_mouse_twice_only_configures_once(self, tkview):
        import types
        tkview._on_motion(types.SimpleNamespace(x=10, y=10))
        n = len([c for c in tkview.root.calls if c[0] == "config"])
        for i in range(20):
            tkview._on_motion(types.SimpleNamespace(x=10 + i, y=10))
        after = len([c for c in tkview.root.calls if c[0] == "config"])
        assert after == n, f"it reconfigured the windows {after - n} more times"

    def test_the_video_window_is_left_alone_while_playing(self, tkview):
        import types
        from ozzytv.app import Screen as S
        tkview.app.screen = S.PLAYING
        tkview._cursor_now = None
        before = len([c for c in tkview.video.calls if c[0] == "config"])
        tkview._on_motion(types.SimpleNamespace(x=5, y=5))
        after = len([c for c in tkview.video.calls if c[0] == "config"])
        assert after == before, "it repainted the film to change a cursor"
