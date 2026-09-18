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
