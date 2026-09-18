"""Will this actually play on a Raspberry Pi 3?

A Pi 3 has one video decoder worth using and it does H.264 up to 1080p30. Give it
HEVC, VP9, AV1 or anything 4K and VLC falls back to decoding on four 1.2 GHz A53
cores, which produces a slideshow with perfect sound — and a child who concludes
the television is broken.

The point of asking is WHO finds out. Unprobed, the answer arrives as a
four-year-old staring at a stuttering picture. Probed, it arrives in the parent
screen as "may not play on this Pi", next to the file, before it is ever allowed.

Honest about not knowing: with no ffprobe installed the verdict is UNKNOWN, and
nothing is claimed. A guess here is worse than a shrug.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROBE_TIMEOUT = 20

# What the VideoCore IV block decodes. MPEG-2 and VC-1 need paid licence keys and
# are not assumed.
HARDWARE_CODECS = {"h264", "avc1"}
# Decodable on the CPU at standard definition, and not above it.
SOFTWARE_OK_CODECS = {"mpeg4", "msmpeg4v3", "mpeg2video", "mpeg1video", "h263", "wmv3", "vc1"}
# Nothing on this board decodes these; the CPU will not keep up at any useful size.
HOPELESS_CODECS = {"hevc", "h265", "vp9", "av1", "vp8"}

MAX_HW_WIDTH, MAX_HW_HEIGHT = 1920, 1088      # 1088: H.264 pads to macroblocks
MAX_HW_FPS = 32.0
MAX_SW_PIXELS = 720 * 576                     # PAL SD, generously


class Verdict:
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Playability:
    verdict: str
    detail: str = ""

    @property
    def is_problem(self) -> bool:
        return self.verdict == Verdict.NO


def _run_ffprobe(path: Path) -> dict | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        p = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,width,height,avg_frame_rate", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    try:
        streams = json.loads(p.stdout).get("streams") or []
    except (ValueError, TypeError):
        return None
    return streams[0] if streams else None


def _fps(value: str | None) -> float:
    """ffprobe reports frame rate as a fraction, and '0/0' for 'no idea'."""
    if not value or "/" not in str(value):
        return 0.0
    num, _, den = str(value).partition("/")
    try:
        n, d = float(num), float(den)
    except ValueError:
        return 0.0
    return n / d if d else 0.0


def judge(stream: dict | None) -> Playability:
    """The verdict for one video stream. Pure, so the table above is testable."""
    if not stream:
        return Playability(Verdict.UNKNOWN, "could not read this file's video")
    codec = str(stream.get("codec_name") or "").lower()
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    fps = _fps(stream.get("avg_frame_rate"))

    if codec in HOPELESS_CODECS:
        return Playability(Verdict.NO, f"{codec.upper()} — a Pi 3 has no decoder for it")
    if codec in HARDWARE_CODECS:
        if width > MAX_HW_WIDTH or height > MAX_HW_HEIGHT:
            return Playability(Verdict.NO, f"{width}×{height} — beyond 1080p on a Pi 3")
        if fps > MAX_HW_FPS:
            return Playability(Verdict.NO, f"{fps:.0f} fps — beyond 30 fps on a Pi 3")
        return Playability(Verdict.YES, f"H.264 {width}×{height}")
    if codec in SOFTWARE_OK_CODECS:
        if width * height > MAX_SW_PIXELS:
            return Playability(
                Verdict.NO, f"{codec.upper()} at {width}×{height} — too big to decode in software")
        return Playability(Verdict.YES, f"{codec.upper()} {width}×{height} (software)")
    if not codec:
        return Playability(Verdict.UNKNOWN, "no video stream found")
    return Playability(Verdict.UNKNOWN, f"{codec} — untested on this hardware")


def probe(path: Path, store=None) -> Playability:
    """Judge a file, remembering the answer. The cache is keyed on size and mtime
    (see store.py), so a re-encoded file is judged again rather than inheriting
    the old verdict."""
    if store is not None:
        cached = store.get_playability(path)
        if cached:
            return Playability(cached[0], cached[1])
    if shutil.which("ffprobe") is None:
        # Say nothing rather than guess. The parent screen shows no badge, which
        # is the truth: we do not know.
        return Playability(Verdict.UNKNOWN, "install ffmpeg to check files")
    result = judge(_run_ffprobe(path))
    if store is not None and result.verdict != Verdict.UNKNOWN:
        store.save_playability(path, result.verdict, result.detail)
    return result
