"""Playing something, and remembering where we got to.

VLC does the hard part. What is here is the part VLC has no opinion about: where
to resume from, how loud a child is allowed to make it, and making sure the
position is written down often enough that pulling the power out of a Raspberry
Pi loses seconds rather than an afternoon.

The engine sits behind a small protocol so all of that is testable without a
display, a sound card or libVLC — and so `--fake-player` can drive the whole app
on a laptop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

# How often the position is written down while something is playing. Ten seconds
# is the most a child loses when the plug comes out, and it is a handful of tiny
# writes a minute to an SD card that has to last years.
RESUME_SAVE_EVERY_MS = 10_000

# Jumping about with the arrow keys.
SEEK_SMALL_MS = 10_000
SEEK_BIG_MS = 60_000


class PlayState(str, Enum):
    IDLE = "idle"
    OPENING = "opening"
    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"
    ERROR = "error"


class Player(Protocol):
    """Everything the app needs an engine to do."""
    def attach(self, window_id: int) -> None: ...
    def open(self, path: Path, start_ms: int = 0) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def seek_to(self, ms: int) -> None: ...
    def set_volume(self, percent: int) -> None: ...
    def position_ms(self) -> int: ...
    def duration_ms(self) -> int: ...
    def state(self) -> PlayState: ...
    def release(self) -> None: ...


class VlcUnavailable(RuntimeError):
    pass


class VlcPlayer:
    """libVLC, through the official python-vlc bindings.

    Imported lazily and with a message worth reading: 'No module named vlc' on a
    television tells a parent nothing, and this is the single most likely thing
    to be missing on a fresh Raspberry Pi.
    """

    def __init__(self, vlc_args: list[str] | None = None):
        try:
            import vlc                                      # noqa: PLC0415
        except (ImportError, OSError) as e:                 # OSError: libvlc missing
            raise VlcUnavailable(
                "VLC is not available. On Raspberry Pi OS:\n"
                "    sudo apt install vlc python3-vlc\n"
                f"(the import said: {e})") from e
        self._vlc = vlc
        # An empty args list is the right default: VLC picks a working video
        # output on its own, and a stale hardware flag copied from a forum is the
        # usual cause of 'sound plays, screen stays black'.
        self._instance = vlc.Instance(list(vlc_args or []))
        if self._instance is None:
            raise VlcUnavailable(
                "libVLC refused to start with these arguments: "
                f"{vlc_args!r}. Clear 'vlc_args' in settings.json and try again.")
        self._mp = self._instance.media_player_new()
        self._duration_hint = 0

    def attach(self, window_id: int) -> None:
        """Draw into someone else's window instead of opening one of our own, so
        video appears inside the app rather than as a second window a child can
        get behind."""
        self._mp.set_xwindow(window_id)

    def open(self, path: Path, start_ms: int = 0) -> None:
        media = self._instance.media_new_path(str(path))
        self._mp.set_media(media)
        self._duration_hint = 0
        self._mp.play()
        if start_ms > 0:
            # The position can only be set once VLC has the media open; doing it
            # here is a request, and PlaybackSession re-applies it on the first
            # tick that reports a real duration.
            self._mp.set_time(int(start_ms))

    def play(self) -> None:
        self._mp.set_pause(0)

    def pause(self) -> None:
        self._mp.set_pause(1)

    def stop(self) -> None:
        self._mp.stop()

    def seek_to(self, ms: int) -> None:
        self._mp.set_time(int(max(0, ms)))

    def set_volume(self, percent: int) -> None:
        self._mp.audio_set_volume(int(percent))

    def position_ms(self) -> int:
        return max(0, int(self._mp.get_time() or 0))

    def duration_ms(self) -> int:
        d = int(self._mp.get_length() or 0)
        if d > 0:
            self._duration_hint = d
        return max(0, self._duration_hint)

    def state(self) -> PlayState:
        s = self._mp.get_state()
        v = self._vlc.State
        return {
            v.NothingSpecial: PlayState.IDLE,
            v.Opening: PlayState.OPENING,
            v.Buffering: PlayState.OPENING,
            v.Playing: PlayState.PLAYING,
            v.Paused: PlayState.PAUSED,
            v.Stopped: PlayState.IDLE,
            v.Ended: PlayState.ENDED,
            v.Error: PlayState.ERROR,
        }.get(s, PlayState.IDLE)

    def release(self) -> None:
        try:
            self._mp.stop()
            self._mp.release()
            self._instance.release()
        except Exception:               # nothing useful to do while shutting down
            log.debug("VLC release failed", exc_info=True)


class FakePlayer:
    """An engine that plays nothing, for tests and for `--fake-player`.

    It advances only when `tick_ms` is called, which is what makes the resume and
    end-of-file behaviour testable without waiting in real time.
    """

    def __init__(self, duration_ms: int = 600_000):
        self.window_id: int | None = None
        self.path: Path | None = None
        self._pos = 0
        self._duration = duration_ms
        self._state = PlayState.IDLE
        self.volume = 100
        self.released = False
        self.seeks: list[int] = []

    def attach(self, window_id: int) -> None:
        self.window_id = window_id

    def open(self, path: Path, start_ms: int = 0) -> None:
        self.path = path
        self._pos = max(0, int(start_ms))
        self._state = PlayState.PLAYING

    def play(self) -> None:
        if self._state in (PlayState.PAUSED, PlayState.IDLE):
            self._state = PlayState.PLAYING

    def pause(self) -> None:
        if self._state is PlayState.PLAYING:
            self._state = PlayState.PAUSED

    def stop(self) -> None:
        self._state = PlayState.IDLE
        self._pos = 0

    def seek_to(self, ms: int) -> None:
        self._pos = max(0, min(int(ms), self._duration))
        self.seeks.append(self._pos)

    def set_volume(self, percent: int) -> None:
        self.volume = int(percent)

    def position_ms(self) -> int:
        return self._pos

    def duration_ms(self) -> int:
        return self._duration

    def state(self) -> PlayState:
        return self._state

    def release(self) -> None:
        self.released = True

    # -- test driving --
    def tick_ms(self, ms: int) -> None:
        if self._state is not PlayState.PLAYING:
            return
        self._pos = min(self._pos + ms, self._duration)
        if self._pos >= self._duration:
            self._state = PlayState.ENDED


@dataclass
class NowPlaying:
    path: Path
    title: str
    position_ms: int = 0
    duration_ms: int = 0
    resumed_from_ms: int = 0


class PlaybackSession:
    """One thing playing, with the decisions VLC does not make.

    Deliberately holds no reference to the UI: the screen asks it what is going
    on, rather than it reaching out to draw.
    """

    def __init__(self, player: Player, store, settings):
        self.player = player
        self.store = store
        self.settings = settings
        self.now: NowPlaying | None = None
        self._last_saved_ms = 0
        self._pending_seek_ms = 0
        self.volume = self._clamp_volume(settings.volume)

    # ---- starting and stopping ------------------------------------------
    def start(self, path: Path, title: str) -> NowPlaying:
        resume_ms = self._resume_point(path)
        self.player.open(path, start_ms=resume_ms)
        self.player.set_volume(self.volume)
        self.now = NowPlaying(path=path, title=title, resumed_from_ms=resume_ms)
        self._last_saved_ms = resume_ms
        # VLC cannot honour a seek until the media is really open, so the request
        # is kept and re-applied on the first tick that knows the duration.
        self._pending_seek_ms = resume_ms
        return self.now

    def _resume_point(self, path: Path) -> int:
        if not self.settings.resume:
            return 0
        saved = self.store.get_resume(path)
        if not saved:
            return 0
        if saved < self.settings.resume_min_seconds * 1000:
            return 0                    # barely started; just start again
        return saved

    def stop(self) -> None:
        self._save_position(force=True)
        self.player.stop()
        self.now = None
        self._pending_seek_ms = 0

    # ---- the heartbeat ---------------------------------------------------
    def tick(self) -> PlayState:
        """Called by the UI a few times a second. Returns the state so the screen
        can react to something ending without watching for it itself."""
        if self.now is None:
            return PlayState.IDLE
        state = self.player.state()
        duration = self.player.duration_ms()
        self.now.duration_ms = duration
        self.now.position_ms = self.player.position_ms()

        if self._pending_seek_ms and duration > 0:
            # Now that VLC knows how long the file is, the resume can actually
            # land. Do not ask for a point past the end of a file that turned out
            # to be shorter than the one we remembered.
            target = min(self._pending_seek_ms, max(0, duration - 5_000))
            if target > 0 and abs(self.now.position_ms - target) > 3_000:
                self.player.seek_to(target)
            self._pending_seek_ms = 0

        if state is PlayState.ENDED:
            self.store.clear_resume(self.now.path)
            return state
        if state is PlayState.PLAYING:
            self._save_position()
        return state

    def _save_position(self, force: bool = False) -> None:
        if self.now is None:
            return
        pos, dur = self.now.position_ms, self.now.duration_ms
        if dur <= 0:
            return
        if not force and abs(pos - self._last_saved_ms) < RESUME_SAVE_EVERY_MS:
            return
        self._last_saved_ms = pos
        # Near the end is 'finished', not 'resume here' — otherwise the last
        # ninety seconds of a film replay for ever.
        if pos >= dur - self.settings.resume_tail_seconds * 1000:
            self.store.clear_resume(self.now.path)
            return
        if pos < self.settings.resume_min_seconds * 1000:
            return
        self.store.save_resume(self.now.path, pos, dur)

    # ---- what the remote does -------------------------------------------
    def toggle_pause(self) -> PlayState:
        if self.player.state() is PlayState.PLAYING:
            self.player.pause()
            self._save_position(force=True)
        else:
            self.player.play()
        return self.player.state()

    def seek(self, delta_ms: int) -> int:
        dur = self.player.duration_ms()
        target = self.player.position_ms() + delta_ms
        target = max(0, min(target, max(0, dur - 3_000)) if dur else max(0, target))
        self.player.seek_to(target)
        return target

    def _clamp_volume(self, v: int) -> int:
        return max(self.settings.volume_min, min(int(v), self.settings.volume_max))

    def change_volume(self, delta: int) -> int:
        """Bounded at BOTH ends on purpose. A child who drags the volume to zero
        decides the television is broken; one who drags it to 200% wakes the
        house."""
        self.volume = self._clamp_volume(self.volume + delta)
        self.player.set_volume(self.volume)
        return self.volume
