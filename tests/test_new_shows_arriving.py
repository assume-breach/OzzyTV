"""Films arrive over the network now, while the television is switched on.

Before the share existed the library was scanned once, at startup, and that was
defensible: the only way to add a show was to walk over with a memory
stick, which means a reboot anyway. A network share breaks that assumption — you
copy a series over from a laptop, look at the television, and nothing has
changed. There is no error and nothing to search for.
"""
import os
import time

import pytest

from ozzytv.app import Action, OzzyApp, Pane
from ozzytv.picks import ROOT_KEY, Mark
from tests.conftest import press, shelves, titles


@pytest.fixture()
def tv(settings, store, player, clock, library_dir):
    app = OzzyApp(settings, store, player, clock=clock)
    store.set_mark(app.roots[0].root, ROOT_KEY, Mark.ALLOW)
    app.rescan()
    app._library_seen = app._fingerprint()
    return app


def play_something(app) -> None:
    """Press OK until a show is on. How many presses that takes depends on
    how deep the first thing in the library happens to be."""
    for _ in range(6):
        app.handle(Action.SELECT)
        if app.screen.value == "playing":
            return
    raise AssertionError(f"nothing played; stuck on {app.screen.value}")


def arrive(library_dir, rel: str) -> None:
    """A file landing the way Samba lands one."""
    p = library_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"a new show")
    # Directory mtimes have coarse resolution on some filesystems; make the
    # change unambiguous rather than depending on the clock ticking over.
    os.utime(p.parent, (time.time() + 1, time.time() + 1))


class TestItNoticesOnItsOwn:
    def test_a_new_series_appears_without_a_restart(self, tv, library_dir, clock):
        assert "Hey Duggee" not in shelves(tv.view())
        arrive(library_dir, "Hey Duggee/Episode 1.mp4")
        clock.advance(10)
        tv.tick()
        assert "Hey Duggee" in shelves(tv.view())

    def test_an_episode_added_deep_inside_a_folder_is_found(self, tv, library_dir, clock):
        """The case a one-level check would miss, and the commonest one: a new
        episode dropped into a series folder that already exists."""
        arrive(library_dir, "Bluey/Series 1/Bluey.S01E03.Keepy Uppy.mkv")
        clock.advance(10)
        tv.tick()
        from tests.conftest import into_tiles, pick_shelf
        pick_shelf(tv, "Bluey")
        into_tiles(tv)
        press(tv, Action.SELECT)                      # into Series 1
        assert any("Keepy Uppy" in t for t in titles(tv.view()))

    def test_it_does_not_scan_on_every_tick(self, tv, clock, monkeypatch):
        """Four times a second against an SD card is a steady drip of I/O for a
        library that is not changing."""
        looks = []
        real = tv.look_for_new_shows
        monkeypatch.setattr(tv, "look_for_new_shows",
                            lambda: looks.append(1) or real())
        for _ in range(20):                       # five seconds of ticks
            tv.tick()
        assert len(looks) == 1, f"it looked at the drive {len(looks)} times"
        clock.advance(10)
        tv.tick()
        assert len(looks) == 2, "and never looked again"

    def test_it_does_not_scan_while_something_is_playing(self, tv, clock):
        """The drive is busy feeding VLC; a stat storm is a stutter."""
        play_something(tv)
        looked = []
        tv._fingerprint = lambda: looked.append(1) or ()
        clock.advance(60)
        tv.tick()
        assert not looked

    def test_nothing_changing_means_no_rescan(self, tv, clock, monkeypatch):
        rescans = []
        real = tv.rescan
        monkeypatch.setattr(tv, "rescan", lambda: rescans.append(1) or real())
        clock.advance(10)
        tv.tick()
        clock.advance(10)
        tv.tick()
        assert not rescans, "it rescanned a library that had not changed"


class TestItDoesNotSnatchTheScreenAway:
    """rescan() empties the stack and sends the cursor home. Fine at startup;
    as a background refresh it would take the screen away mid-choice."""

    def test_you_keep_your_place_in_a_folder(self, tv, library_dir, clock):
        from tests.conftest import into_tiles, pick_shelf
        pick_shelf(tv, "Bluey")
        into_tiles(tv)
        press(tv, Action.SELECT)                      # into Series 1
        before = tv.view().heading
        arrive(library_dir, "Hey Duggee/Episode 1.mp4")
        clock.advance(10)
        tv.tick()
        assert tv.view().heading == before, "it threw them back to the top"

    def test_you_keep_the_shelf_you_were_on(self, tv, library_dir, clock):
        from tests.conftest import pick_shelf
        pick_shelf(tv, "PAW Patrol")
        arrive(library_dir, "Hey Duggee/Episode 1.mp4")
        clock.advance(10)
        tv.tick()
        v = tv.view()
        assert v.rail[v.rail_cursor].title == "PAW Patrol"

    def test_a_folder_deleted_underneath_you_stops_the_descent(self, tv, library_dir,
                                                               clock):
        """Rather than erroring, which on this screen is a traceback in front of
        a child."""
        import shutil
        from tests.conftest import into_tiles, pick_shelf
        pick_shelf(tv, "Bluey")
        into_tiles(tv)
        press(tv, Action.SELECT)
        shutil.rmtree(library_dir / "Bluey")
        os.utime(library_dir, (time.time() + 1, time.time() + 1))
        clock.advance(10)
        tv.tick()                                     # must not raise
        tv.view()

    def test_the_refresh_reports_whether_anything_changed(self, tv, library_dir):
        assert tv.look_for_new_shows() is False
        arrive(library_dir, "Hey Duggee/Episode 1.mp4")
        assert tv.look_for_new_shows() is True
        assert tv.look_for_new_shows() is False
