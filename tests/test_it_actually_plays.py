"""Real libVLC, a real video file, played for real.

Everything else in this suite uses FakePlayer, which is right for testing
decisions and useless for testing whether a show comes on. Twice now something
shipped that passed every test and put a black flash on the television.

Skipped where libVLC is not installed, which is most CI - and NOT skipped on a
Raspberry Pi, where the whole suite is meant to run and where it matters.
"""
import shutil
import subprocess
import time
from pathlib import Path

import pytest

vlc = pytest.importorskip("vlc", reason="libVLC not installed here")

from ozzytv.app import Action, OzzyApp, Screen          # noqa: E402
from ozzytv.config import Settings                      # noqa: E402
from ozzytv.playback import PlayState, VlcPlayer        # noqa: E402
from ozzytv.store import Store                          # noqa: E402

# A video output that needs no screen. The point is the pipeline, not the pixels.
HEADLESS = ["--vout=dummy", "--aout=dummy", "--quiet"]


@pytest.fixture(scope="session")
def clip(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed here")
    out = tmp_path_factory.mktemp("media") / "Show" / "Episode 1.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=size=320x240:rate=10", "-t", "4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out), "-y"],
                   check=True, capture_output=True)
    return out


@pytest.fixture()
def tv(clip, tmp_path):
    app = OzzyApp(Settings(media_roots=[str(clip.parent.parent)], resume=False),
                  Store(tmp_path / "t.db"), VlcPlayer(HEADLESS))
    yield app
    app.player.release()


def run_for(app, seconds, step=0.25):
    """Drive the app the way the drawing layer does."""
    for _ in range(int(seconds / step)):
        time.sleep(step)
        app.tick()
        if app.screen is not Screen.PLAYING:
            return False
    return True


class TestAShowComesOn:
    def test_pressing_ok_starts_it(self, tv):
        for _ in range(6):
            tv.handle(Action.SELECT)
            if tv.screen is Screen.PLAYING:
                break
        assert tv.screen is Screen.PLAYING, "nothing started"
        time.sleep(1.0)
        tv.tick()
        assert tv.player.state() is PlayState.PLAYING
        assert tv.playback.now.duration_ms > 0, "VLC never opened the file"

    def test_and_keeps_playing_rather_than_flashing_back_to_the_menu(self, tv):
        """The exact reported symptom: a black flash and then the menu."""
        for _ in range(6):
            tv.handle(Action.SELECT)
            if tv.screen is Screen.PLAYING:
                break
        assert run_for(tv, 2.0), (
            f"it left the video after under two seconds: "
            f"{tv.view().message!r}")
        assert tv.playback.now.position_ms > 500, "the picture never advanced"

    def test_it_plays_to_the_end_and_goes_back_quietly(self, tv):
        for _ in range(6):
            tv.handle(Action.SELECT)
            if tv.screen is Screen.PLAYING:
                break
        for _ in range(40):
            time.sleep(0.25)
            tv.tick()
            if tv.screen is not Screen.PLAYING:
                break
        assert tv.screen is Screen.BROWSE, "it did not come back to the menu"
        assert tv.view().message == "", \
            "a show that finished normally should not report a problem"


class TestAFailureIsNotSilent:
    """An early end is not a finish. When VLC cannot make a video output the
    decoder stalls and the stream ends short, and that arrived here as an
    ordinary ending — a black flash and the menu, with nothing said."""

    def test_stopping_far_short_of_the_duration_is_reported(self, tv):
        for _ in range(6):
            tv.handle(Action.SELECT)
            if tv.screen is Screen.PLAYING:
                break
        time.sleep(0.6)
        tv.tick()
        assert tv.playback.now.duration_ms > 0
        # Force the shape of the failure: ended, but nowhere near the end.
        tv.playback.now.position_ms = 200
        tv.playback.now.duration_ms = 60_000
        tv.player.stop()
        tv.playback.tick = lambda: PlayState.ENDED
        tv.tick()
        assert tv.screen is Screen.MESSAGE, "it went back to the menu silently"
        assert "would not play" in tv.view().message
        assert "Episode 1" in tv.view().message, "it does not say which file"


class TestTheFileItselfReachesVlc:
    def test_a_path_with_spaces_and_brackets_opens(self, tmp_path, clip):
        """Real libraries are full of these: "Bluey (2018) [1080p]"."""
        awkward = tmp_path / "The Land Before Time (TV) [1080p]"
        awkward.mkdir(parents=True)
        shutil.copy(clip, awkward / "01 The Cave Of Many Voices.mp4")
        app = OzzyApp(Settings(media_roots=[str(tmp_path)], resume=False),
                      Store(tmp_path / "t2.db"), VlcPlayer(HEADLESS))
        try:
            for _ in range(6):
                app.handle(Action.SELECT)
                if app.screen is Screen.PLAYING:
                    break
            assert app.screen is Screen.PLAYING
            time.sleep(1.0)
            app.tick()
            assert app.playback.now.duration_ms > 0, "VLC never opened it"
            assert app.screen is Screen.PLAYING
        finally:
            app.player.release()
