"""A whole Ozzy TV, headless.

The app is built so that everything except drawing can run without a display, a
sound card or libVLC — so these fixtures assemble the real thing with a fake
engine and drive it by sending the Actions a remote would send.
"""
import os
from pathlib import Path

import pytest

from ozzytv.app import Action, OzzyApp
from ozzytv.config import Settings
from ozzytv.playback import FakePlayer
from ozzytv.store import Store


@pytest.fixture()
def library_dir(tmp_path):
    """A library shaped like a real one: a couple of series, a film, and the
    detritus every media drive collects."""
    root = tmp_path / "Videos"
    tree = {
        "Bluey/Series 1/Bluey.S01E01.The Magic Xylophone.1080p.WEB-DL.x264-GRP.mkv": b"v",
        "Bluey/Series 1/Bluey.S01E02.Hospital.1080p.WEB-DL.x264-GRP.mkv": b"v",
        "Bluey/Series 1/Bluey.S01E10.Shadowlands.1080p.WEB-DL.x264-GRP.mkv": b"v",
        "Bluey/Series 2/Bluey.S02E14.Sleepytime.mkv": b"v",
        "PAW Patrol/Episode 1.mp4": b"v",
        "PAW Patrol/Episode 2.mp4": b"v",
        "Films/Paddington (2014).mp4": b"v",
        "Films/Alien (1979) 1080p BluRay x264.mkv": b"v",
        # things that must never become tiles
        "Bluey/Series 1/subs/en.srt": b"s",
        "Films/poster.jpg": b"i",
        ".hidden/secret.mp4": b"v",
        "@eaDir/thumb.mp4": b"v",
    }
    for rel, data in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


@pytest.fixture()
def settings(library_dir, tmp_path):
    return Settings(media_roots=[str(library_dir)], columns=3, rows=2)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OZZYTV_HOME", str(tmp_path / "home"))
    s = Store(tmp_path / "home" / "ozzytv.db")
    yield s
    s.close()


@pytest.fixture()
def player():
    return FakePlayer(duration_ms=600_000)


@pytest.fixture()
def clock():
    """A clock the tests move, so a lockout can be waited out instantly."""
    class C:
        now = 1_000_000.0
        def __call__(self):
            return self.now
        def advance(self, seconds):
            self.now += seconds
    return C()


@pytest.fixture()
def app(settings, store, player, clock):
    return OzzyApp(settings, store, player, clock=clock)


@pytest.fixture()
def allow_everything(app, store):
    """The shortcut for tests about something other than the rules."""
    from ozzytv.picks import ROOT_KEY, Mark
    store.set_mark(app.roots[0].root, ROOT_KEY, Mark.ALLOW)
    app.rescan()
    return app


def press(app, *actions):
    """Send a sequence of keypresses. A digit is written as 'd7'.

    `not isinstance(a, Action)` is load-bearing: Action is a str enum, so
    Action.DOWN passes `isinstance(a, str)` AND `startswith("d")`. Without this
    guard every Down press in the suite was quietly delivered as the digit
    "own" — the tests still ran, and the ones about moving down a row failed for
    a reason that had nothing to do with the app.
    """
    for a in actions:
        if isinstance(a, str) and not isinstance(a, Action) and a.startswith("d"):
            app.handle(Action.DIGIT, a[1:])
        else:
            app.handle(a)
    return app.view()


def titles(view):
    return [t.title for t in view.tiles]


def shelves(view):
    return [r.title for r in view.rail]


def pick_shelf(app, name):
    """Move the left-hand list onto a named shelf."""
    from ozzytv.app import Action
    for _ in range(40):
        v = app.view()
        if v.rail[v.rail_cursor].title == name:
            return v
        if v.rail_cursor >= len(v.rail) - 1:
            break
        app.handle(Action.DOWN)
    raise AssertionError(f"no shelf named {name!r} in {shelves(app.view())}")


def into_tiles(app):
    """Cross from the shelf list to the tiles beside it."""
    from ozzytv.app import Action
    app.handle(Action.SELECT)
    return app.view()
