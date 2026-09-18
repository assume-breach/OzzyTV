"""Where Ozzy TV keeps things, and what an operator can change.

Settings live in one JSON file so a parent can edit them over SSH without the app
running. Everything has a working default: a fresh Raspberry Pi with a USB stick
plugged in should show something useful without anyone opening an editor.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "ozzytv"

# Containers VLC handles happily. The list is deliberately generous — VLC is the
# playback engine precisely so we do not have to be clever about formats — and a
# file that turns out to be beyond this hardware is caught by probe.py and shown
# to the PARENT, not discovered by a child watching a slideshow.
VIDEO_EXTS = frozenset({
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".mpg", ".mpeg", ".m2v",
    ".ts", ".m2ts", ".mts", ".wmv", ".asf", ".flv", ".ogv", ".3gp", ".divx", ".vob",
})
AUDIO_EXTS = frozenset({
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav", ".wma",
})

# Files that are never media, whatever their extension suggests.
IGNORED_NAMES = frozenset({
    "@eaDir", "lost+found", "System Volume Information", ".Trash-1000", "#recycle",
})


def app_home() -> Path:
    """Everything this app owns, in one directory. One env var moves the lot,
    which is what the tests use and what a second child profile would use."""
    env = os.environ.get("OZZYTV_HOME")
    if env:
        return Path(env).expanduser()
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


@dataclass
class Settings:
    # Where the media is. A list, not a single path: a plugged-in USB stick is the
    # normal way a film reaches a Pi, and it is not in the same place as the
    # library on the SD card.
    media_roots: list[str] = field(default_factory=lambda: [str(Path.home() / "Videos")])

    # Extra arguments handed to libVLC at startup. EMPTY BY DEFAULT and that is
    # deliberate: VLC picks a working output on its own, and a stale hardware flag
    # copied from a forum post is the usual reason a Pi plays sound with a black
    # screen. See README ("If video stutters") before putting anything here.
    vlc_args: list[str] = field(default_factory=list)

    # Kid screen shape. 3x2 tiles fill a 1080p TV at a size a four-year-old can
    # aim at from the sofa; a Pi 3 draws that without breaking a sweat.
    columns: int = 3
    rows: int = 2

    # Pick up where we left off. Stored per file, and invalidated if the file
    # changes underneath us (see store.py) so a re-download never resumes into
    # the middle of something else.
    resume: bool = True
    resume_min_seconds: int = 60        # below this, just start again
    resume_tail_seconds: int = 90       # this close to the end, start again

    # How the parent gets in. The KEY is not the secret — the PIN is — so this can
    # be anything a remote can send.
    parent_keys: list[str] = field(default_factory=lambda: ["p", "Menu", "F1"])

    # A child holding the remote should not be able to drag the volume to zero and
    # then think the telly is broken.
    volume: int = 80
    volume_min: int = 20
    volume_max: int = 100

    # Optional: drive the app from the TV's own remote over HDMI-CEC. Off until
    # asked for — it needs cec-client, and a Pi that cannot find it should not
    # print errors at a child.
    cec: bool = False

    @property
    def roots(self) -> list[Path]:
        return [Path(p).expanduser() for p in self.media_roots]


def settings_path() -> Path:
    return app_home() / "settings.json"


def load_settings() -> Settings:
    """Never raises. A settings file someone has broken with a stray comma must
    not stop a child's television from working — fall back to defaults, keep the
    broken file for them to look at, and carry on."""
    p = settings_path()
    try:
        raw = json.loads(p.read_text())
    except FileNotFoundError:
        return Settings()
    except Exception:
        try:
            p.replace(p.with_suffix(".json.broken"))
        except OSError:
            pass
        return Settings()
    known = {f for f in Settings().__dataclass_fields__}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save_settings(s: Settings) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2, sort_keys=True) + "\n")
    tmp.replace(p)                      # atomic: never a half-written settings file
