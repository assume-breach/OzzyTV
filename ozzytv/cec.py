"""Optional: drive Ozzy TV with the television's own remote, over HDMI-CEC.

A child already knows where the TV remote lives. A second remote for the box
under the telly is a thing to lose.

This shells out to `cec-client` (libcec) and reads the key presses it prints,
because that is the only interface libcec offers without a C extension to build
on an ARM board. It is OFF by default and every failure is silent by design: a Pi
that cannot find cec-client, or a television with CEC switched off in a menu
nobody remembers, must still work perfectly with the USB remote in the drawer.

NOT VERIFIED ON HARDWARE. It is written from the documented cec-client output
format and is off unless a parent turns it on; the keyboard path is the one the
tests cover and the one the README tells you to use first.
"""
from __future__ import annotations

import logging
import queue
import re
import shutil
import subprocess
import threading

from .app import Action

log = logging.getLogger(__name__)

# cec-client prints e.g. "key pressed: select (0)" / "key released: left (3)".
_KEY_LINE = re.compile(r"key pressed:\s*([a-z0-9 _-]+?)\s*\(", re.I)

# CEC user-control names to what they mean here.
CEC_KEYS = {
    "up": Action.UP, "down": Action.DOWN, "left": Action.LEFT, "right": Action.RIGHT,
    "select": Action.SELECT, "enter": Action.SELECT, "ok": Action.SELECT,
    "exit": Action.BACK, "return": Action.BACK, "back": Action.BACK,
    "play": Action.PLAY_PAUSE, "pause": Action.PLAY_PAUSE,
    "play/pause": Action.PLAY_PAUSE, "stop": Action.BACK,
    "volume up": Action.VOLUME_UP, "volume down": Action.VOLUME_DOWN,
    "root menu": Action.PARENT, "setup menu": Action.PARENT, "contents menu": Action.PARENT,
    **{f"number{n}": (Action.DIGIT, str(n)) for n in range(10)},
    **{str(n): (Action.DIGIT, str(n)) for n in range(10)},
}


def translate(line: str):
    """One line of cec-client output as (Action, value), or None.

    Pure, so the mapping is testable without a television in the room — which is
    the only part of this file that can be.
    """
    m = _KEY_LINE.search(line)
    if not m:
        return None
    name = m.group(1).strip().lower()
    mapped = CEC_KEYS.get(name)
    if mapped is None:
        return None
    if isinstance(mapped, tuple):
        return mapped
    return (mapped, "")


class CecRemote:
    """Runs cec-client in the background and queues what it presses.

    Queued rather than delivered: Tk is not thread-safe, so the UI thread drains
    this on its own tick instead of being called into from a pipe reader.
    """

    def __init__(self, device_name: str = "Ozzy TV"):
        self.device_name = device_name
        self.events: queue.Queue = queue.Queue(maxsize=64)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @staticmethod
    def available() -> bool:
        return shutil.which("cec-client") is not None

    def start(self) -> bool:
        if not self.available():
            log.info("HDMI-CEC asked for but cec-client is not installed — "
                     "using the keyboard/USB remote only")
            return False
        try:
            self._proc = subprocess.Popen(
                ["cec-client", "-d", "1", "-t", "p", "-o", self.device_name],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            log.exception("could not start cec-client")
            return False
        self._thread = threading.Thread(target=self._read, name="cec", daemon=True)
        self._thread.start()
        return True

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                return
            event = translate(line)
            if event is None:
                continue
            try:
                self.events.put_nowait(event)
            except queue.Full:
                pass        # the UI is busy; dropping a keypress beats blocking it

    def drain(self, app) -> bool:
        """Hand everything queued to the app. Returns whether anything happened,
        so the caller can skip a redraw when nothing did."""
        acted = False
        while True:
            try:
                action, value = self.events.get_nowait()
            except queue.Empty:
                return acted
            app.handle(action, value)
            acted = True

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            try:
                self._proc.terminate()
            except OSError:
                pass
