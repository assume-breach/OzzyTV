"""Folders you made, that you have not filled yet.

These used to vanish. The reasoning was about the CHILD — a shelf you open to
find nothing is indistinguishable, at two, from having pressed the wrong button
— and it is sound as far as it goes. It just ignored the other person: make a
folder over the network share, look at the television, and it is not there. The
grown-up is the one who can do something about it, and what they conclude is
that the share is broken.
"""
import pytest

from ozzytv.app import OzzyApp
from ozzytv.picks import Mark


@pytest.fixture()
def drive(settings, store, player, clock, tmp_path):
    d = tmp_path / "ozzy"
    (d / "Movies").mkdir(parents=True)
    (d / "Movies" / "Dumbo.mp4").write_bytes(b"v")
    (d / "New Folder").mkdir()                      # just made over the share
    (d / "Bluey" / "Series 1" / "subs").mkdir(parents=True)
    (d / "Bluey" / "Series 1" / "subs" / "en.srt").write_text("x")
    (d / "Bluey" / "Series 1" / "S01E01.mp4").write_bytes(b"v")
    settings.media_roots = [str(d)]
    return OzzyApp(settings, store, player, clock=clock), d


def shelf_names(app):
    return [r.title for r in app.view().rail]


class TestAnEmptyFolderIsStillAFolder:
    def test_it_shows_up(self, drive):
        app, _ = drive
        assert "New Folder" in shelf_names(app)

    def test_with_nothing_in_it(self, drive):
        app, _ = drive
        row = next(r for r in app.view().rail if r.title == "New Folder")
        assert row.count == 0, "it claims to have something in it"

    def test_and_opening_it_says_so_rather_than_doing_nothing(self, drive):
        app, _ = drive
        i = shelf_names(app).index("New Folder")
        app.click(f"rail:{i}")
        assert app.view().tiles == []
        app.view()                                  # must not raise

    def test_filling_it_makes_it_count(self, drive, clock):
        app, d = drive
        (d / "New Folder" / "Paddington.mp4").write_bytes(b"v")
        import os, time
        os.utime(d / "New Folder", (time.time() + 1, time.time() + 1))
        clock.advance(10)
        app.tick()
        row = next(r for r in app.view().rail if r.title == "New Folder")
        assert row.count == 1


class TestTheJunkStaysHidden:
    """What actually motivated the old rule was sidecar folders, and those are
    better dealt with by name: they are made BY something else, they sit beside
    every episode, and nobody ever picks one."""

    def test_a_subs_folder_is_not_a_shelf(self, drive):
        app, _ = drive
        i = shelf_names(app).index("Bluey")
        app.click(f"rail:{i}")
        assert "subs" not in [t.title for t in app.view().tiles]

    def test_whatever_it_is_capitalised_as(self, tmp_path, settings, store, player,
                                           clock):
        d = tmp_path / "ozzy" / "Show"
        d.mkdir(parents=True)
        (d / "ep.mp4").write_bytes(b"v")
        for name in ("Subs", "SUBTITLES", "Sample"):
            (d / name).mkdir()
        settings.media_roots = [str(tmp_path / "ozzy")]
        app = OzzyApp(settings, store, player, clock=clock)
        i = shelf_names(app).index("Show")
        app.click(f"rail:{i}")
        assert [t.title for t in app.view().tiles] == ["ep"]

    def test_and_so_does_the_appliance_junk(self, tmp_path, settings, store, player,
                                            clock):
        d = tmp_path / "ozzy"
        (d / "@eaDir").mkdir(parents=True)
        (d / "@eaDir" / "thumb.mp4").write_bytes(b"v")
        (d / ".hidden").mkdir()
        (d / "Real").mkdir()
        (d / "Real" / "a.mp4").write_bytes(b"v")
        settings.media_roots = [str(d)]
        app = OzzyApp(settings, store, player, clock=clock)
        assert shelf_names(app) == ["Real"]


class TestHidingStillWorks:
    def test_a_blocked_folder_is_gone_empty_or_not(self, drive):
        app, _ = drive
        app.store.set_mark(app.roots[0].root, "New Folder", Mark.BLOCK)
        app.rescan()
        assert "New Folder" not in shelf_names(app)

    def test_and_so_is_a_blocked_one_with_films_in_it(self, drive):
        app, _ = drive
        app.store.set_mark(app.roots[0].root, "Movies", Mark.BLOCK)
        app.rescan()
        assert "Movies" not in shelf_names(app)
