"""DVDs.

A Raspberry Pi with a USB drive in it is a DVD player, and a shelf of children's
DVDs is the most likely thing already in the house. VLC plays them directly —
there is nothing to rip — so all this has to do is notice the drive, notice
whether there is a disc in it, and hand libVLC the right MRL.

No decryption happens here and none is bundled. Most commercial DVDs are CSS
scrambled and need libdvdcss, which Debian ships as a source package you build
yourself (`libdvd-pkg`) for licensing reasons. install.sh says so rather than
pretending; a disc that will not play says which package is missing instead of
showing a black screen.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Where an optical drive turns up. /dev/sr0 is what the kernel calls it; the
# others are the udev symlinks, kept because a second drive lands on sr1 and
# because some images only create one of them.
CANDIDATES = ("/dev/sr0", "/dev/sr1", "/dev/dvd", "/dev/cdrom")

DVD_KIND = "dvd"
DVD_REL = "\x00dvd"


@dataclass(frozen=True)
class Disc:
    device: str
    title: str = "DVD"
    has_disc: bool = False

    @property
    def mrl(self) -> str:
        """What libVLC is handed. `dvd://` gets the menus and the title
        structure; pointing it at the raw device would play one track."""
        return f"dvd://{self.device}"


def _readable(device: str) -> bool:
    """Is there a disc in there?

    Opening the device succeeds with an empty drive on some kernels and fails
    with ENOMEDIUM on others, so the read is what settles it: no medium, no
    bytes. Non-blocking, because opening an optical device that is still
    spinning up otherwise waits, and this runs on the drawing thread.
    """
    try:
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        return bool(os.read(fd, 2048))
    except OSError:
        return False
    finally:
        os.close(fd)


class Watcher:
    """Looks at the drive on its OWN thread, and answers instantly from a cache.

    Probing an optical drive means opening the device and reading from it, and a
    drive that is spinning up blocks that read for SECONDS. O_NONBLOCK does not
    help; the kernel waits for the disc. Called from the drawing code — which is
    where the tile list is built, four times a second and on every keypress —
    that stalls the whole interface the instant a disc starts spinning. Which is
    to say: the instant you press Play on a DVD, the television locks up with a
    black screen and no buttons, and never comes back.

    So the probe runs in a daemon thread and `snapshot()` returns whatever it
    last found. Being a second out of date about a disc drive costs nothing.
    """

    def __init__(self, candidates=CANDIDATES, every: float = 3.0):
        self._candidates = candidates
        self._every = every
        self._discs: list[Disc] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # One pass up front so the first screen is not empty, on this thread but
        # once rather than forever.
        self._refresh()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="ozzytv-discs")
        self._thread.start()

    def _loop(self) -> None:
        while True:
            time.sleep(self._every)
            try:
                self._refresh()
            except Exception:
                log.debug("disc scan failed", exc_info=True)

    def _refresh(self) -> None:
        found = find(self._candidates)
        with self._lock:
            self._discs = found

    def snapshot(self) -> list[Disc]:
        with self._lock:
            return list(self._discs)


def find(candidates=CANDIDATES) -> list[Disc]:
    """Every optical drive on the machine, with whether it has a disc in it.

    Drives are reported even when empty — a DVD tile that appears and vanishes
    depending on what is loaded is worse than one that says "no disc". Symlinks
    are resolved so /dev/dvd and /dev/sr0 do not become two tiles for one drive.
    """
    out: list[Disc] = []
    seen: set[str] = set()
    for dev in candidates:
        p = Path(dev)
        if not p.exists():
            continue
        real = str(p.resolve())
        if real in seen:
            continue
        seen.add(real)
        out.append(Disc(device=real, has_disc=_readable(real)))
    for i, d in enumerate(out):
        if len(out) > 1:
            out[i] = Disc(d.device, f"DVD {i + 1}", d.has_disc)
    return out
