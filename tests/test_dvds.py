"""DVDs.

A Pi with a USB drive in it is a DVD player, and a shelf of children's DVDs is
the most likely thing already in the house. VLC plays them directly, so the only
work is noticing the drive and handing libVLC the right MRL — which is exactly
where this went wrong the first time, because a DVD is not a file.
"""
import os
from pathlib import Path

import pytest

from ozzytv import discs
from ozzytv.app import Action, OzzyApp, Screen


class FakeWatcher:
    """What the app talks to. The real one probes on its own thread."""
    def __init__(self, found):
        self._found = found

    def snapshot(self):
        return list(self._found)

    def start(self):
        pass


class TestFindingTheDrive:
    def test_no_drive_is_not_an_error(self):
        assert discs.find(candidates=("/dev/definitely-not-here",)) == []

    def test_a_drive_is_reported_even_with_no_disc_in_it(self, tmp_path):
        """A tile that appears and vanishes depending on what is loaded is worse
        than one that says "no disc"."""
        dev = tmp_path / "sr0"
        dev.write_bytes(b"")                      # exists, reads nothing
        found = discs.find(candidates=(str(dev),))
        assert len(found) == 1
        assert found[0].has_disc is False

    def test_a_disc_in_the_drive_is_noticed(self, tmp_path):
        dev = tmp_path / "sr0"
        dev.write_bytes(b"\x00" * 4096)
        found = discs.find(candidates=(str(dev),))
        assert found[0].has_disc is True

    def test_one_drive_behind_two_names_is_one_drive(self, tmp_path):
        """/dev/dvd and /dev/cdrom are symlinks to /dev/sr0. Three tiles for one
        drive is worse than none."""
        real = tmp_path / "sr0"
        real.write_bytes(b"\x00" * 4096)
        for alias in ("dvd", "cdrom"):
            os.symlink(real, tmp_path / alias)
        found = discs.find(candidates=tuple(str(tmp_path / n)
                                            for n in ("sr0", "dvd", "cdrom")))
        assert len(found) == 1

    def test_the_mrl_is_a_dvd_url_not_a_path(self):
        """`dvd://` gets the menus and the title structure. Handing VLC the raw
        device would play one track and ignore the rest of the disc."""
        assert discs.Disc("/dev/sr0").mrl == "dvd:///dev/sr0"


class TestVlcIsHandedSomethingItUnderstands:
    def test_an_mrl_does_not_go_through_media_new_path(self):
        """media_new_path() quotes its argument as a FILE path, so an MRL would
        be looked for as a file of that name and simply not found — a black
        screen with nothing in the log worth reading."""
        import inspect

        from ozzytv import playback
        src = inspect.getsource(playback.VlcPlayer.open)
        assert "://" in src, "it cannot tell an MRL from a path"
        assert "media_new(" in src


class TestOnTheHomeScreen:
    @pytest.fixture()
    def tv(self, settings, store, player, clock, tmp_path, monkeypatch):
        dev = tmp_path / "sr0"
        dev.write_bytes(b"\x00" * 4096)
        settings.media_roots = [str(tmp_path / "empty")]
        app = OzzyApp(settings, store, player, clock=clock)
        app.discs = FakeWatcher([discs.Disc(str(dev), "DVD", True)])
        return app

    def test_a_dvd_tile_is_on_the_home_screen(self, tv):
        titles = [t.title for t in tv.view().tiles]
        assert "DVD" in titles

    def test_pressing_it_plays_the_disc(self, tv):
        i = [n for n, t in enumerate(tv.view().tiles) if t.kind == "dvd"][0]
        tv.click(f"tile:{i}")
        assert tv.screen is Screen.PLAYING
        assert str(tv.playback.now.path).startswith("dvd://")

    def test_an_empty_drive_says_so_instead_of_a_black_screen(self, tv, monkeypatch,
                                                              tmp_path):
        tv.discs = FakeWatcher([discs.Disc(str(tmp_path / "sr0"), "DVD", False)])
        i = [n for n, t in enumerate(tv.view().tiles) if t.kind == "dvd"][0]
        tv.click(f"tile:{i}")
        assert tv.screen is Screen.MESSAGE
        assert "no disc" in tv.view().message.lower()

    def test_a_drive_that_vanishes_does_not_crash_it(self, tv, monkeypatch):
        tiles = tv.view().tiles
        i = [n for n, t in enumerate(tiles) if t.kind == "dvd"][0]
        tv.discs = FakeWatcher([])
        tv.click(f"tile:{i}")                     # must not raise
        # Whatever it does, it must not be a traceback in front of a child. The
        # tile list shrank under it, so index 0 is now something else entirely.
        assert tv.screen in (Screen.MESSAGE, Screen.BROWSE, Screen.PIN,
                             Screen.PARENT)
        tv.view()


class TestTheHomeScreenAlwaysExists:
    """A Roku with nothing installed still shows you a Roku."""

    def test_an_empty_library_still_draws_a_screen(self, settings, store, player,
                                                   clock, tmp_path):
        """No drive and no files: still the television, still saying what to
        do — not a blank."""
        settings.media_roots = [str(tmp_path / "nothing")]
        app = OzzyApp(settings, store, player, clock=clock)
        v = app.view()
        assert v.screen == Screen.BROWSE.value
        assert v.rail, "no menu at all"
        assert v.welcome, "and nothing saying what to do"

    def test_a_drive_puts_a_home_shelf_on_it(self, settings, store, player, clock,
                                             tmp_path):
        settings.media_roots = [str(tmp_path / "nothing")]
        app = OzzyApp(settings, store, player, clock=clock)
        app.discs = FakeWatcher([discs.Disc("/dev/sr0", "DVD", False)])
        assert any(r.title == "Home" for r in app.view().rail)


    def test_arrow_keys_do_not_run_off_the_end(self, settings, store, player, clock,
                                               tmp_path):
        settings.media_roots = [str(tmp_path / "nothing")]
        app = OzzyApp(settings, store, player, clock=clock)
        app.discs = FakeWatcher([discs.Disc("/dev/sr0", "DVD", False)])
        for a in (Action.DOWN, Action.DOWN, Action.UP, Action.UP, Action.RIGHT):
            app.handle(a)
        app.view()                               # must not raise


class TestADiscIsNotAFile:
    def test_the_mrl_survives_the_trip_to_the_player(self, settings, store, player,
                                                     clock, tmp_path, monkeypatch):
        """Path("dvd:///dev/sr0") is PosixPath("dvd:/dev/sr0") — pathlib
        collapses the double slash, and VLC is handed an address pointing
        nowhere. It has to stay a string the whole way."""
        dev = tmp_path / "sr0"
        dev.write_bytes(b"\x00" * 4096)
        settings.media_roots = [str(tmp_path / "empty")]
        app = OzzyApp(settings, store, player, clock=clock)
        app.discs = FakeWatcher([discs.Disc(str(dev), "DVD", True)])
        i = [n for n, t in enumerate(app.view().tiles) if t.kind == "dvd"][0]
        app.click(f"tile:{i}")
        assert str(app.playback.now.path).startswith("dvd://")

    def test_a_disc_has_no_resume_point(self, settings, store, player, clock,
                                        tmp_path, monkeypatch):
        """The resume store is keyed on a file, and a DVD keeps its own place."""
        dev = tmp_path / "sr0"
        dev.write_bytes(b"\x00" * 4096)
        settings.media_roots = [str(tmp_path / "empty")]
        app = OzzyApp(settings, store, player, clock=clock)
        app.discs = FakeWatcher([discs.Disc(str(dev), "DVD", True)])
        i = [n for n, t in enumerate(app.view().tiles) if t.kind == "dvd"][0]
        app.click(f"tile:{i}")
        app.playback.stop()                       # must not try to store a Path
