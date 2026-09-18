"""The parent's PIN, and the reason a child cannot guess their way past it.

A four-digit PIN has ten thousand combinations, and a bored eight-year-old with a
remote has all afternoon. So the PIN is stored as a slow hash (never in the
clear, not even on a device only the family touches — the SD card leaves the
house in a laptop bag eventually), and wrong guesses cost increasing amounts of
time. The delay is PERSISTED: pulling the plug is the obvious way to clear a
lockout and it is the first thing anyone tries.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

# scrypt parameters. n=16384 is roughly a fifth of a second on a Pi 3's A53 —
# unnoticeable when a parent types a PIN once, and ruinous at ten thousand tries.
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32

MIN_PIN_LEN = 4
MAX_PIN_LEN = 12

# Wrong guesses before the keypad starts making you wait, and how long for.
FREE_ATTEMPTS = 3
BACKOFF_SECONDS = (5, 15, 60, 300, 900)     # then the last value, for ever


@dataclass(frozen=True)
class PinHash:
    salt: bytes
    key: bytes

    def encode(self) -> str:
        return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${self.salt.hex()}${self.key.hex()}"

    @staticmethod
    def decode(s: str) -> "PinHash | None":
        try:
            scheme, n, r, p, salt, key = s.split("$")
            if scheme != "scrypt":
                return None
            return PinHash(salt=bytes.fromhex(salt), key=bytes.fromhex(key))
        except (ValueError, AttributeError):
            return None


class WeakPin(ValueError):
    pass


def _derive(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                          p=SCRYPT_P, dklen=KEY_LEN)


def hash_pin(pin: str) -> PinHash:
    check_pin_strength(pin)
    salt = os.urandom(16)
    return PinHash(salt=salt, key=_derive(pin, salt))


def verify_pin(pin: str, stored: PinHash) -> bool:
    # compare_digest, not ==: the timing of a failing comparison leaks how much of
    # the PIN was right, which turns 10,000 guesses into about 40.
    return hmac.compare_digest(_derive(pin, stored.salt), stored.key)


def check_pin_strength(pin: str) -> None:
    """Refuse the PINs that are not really PINs. Raises WeakPin with a sentence a
    parent can act on, because 'invalid' tells them nothing."""
    if not pin.isdigit():
        raise WeakPin("A PIN is digits only.")
    if not (MIN_PIN_LEN <= len(pin) <= MAX_PIN_LEN):
        raise WeakPin(f"A PIN needs {MIN_PIN_LEN} to {MAX_PIN_LEN} digits.")
    if len(set(pin)) == 1:
        raise WeakPin("Pick a PIN that is not the same digit over and over.")
    runs = all(int(pin[i + 1]) - int(pin[i]) == 1 for i in range(len(pin) - 1))
    backwards = all(int(pin[i]) - int(pin[i + 1]) == 1 for i in range(len(pin) - 1))
    if runs or backwards:
        raise WeakPin("Pick a PIN that is not a simple run like 1234.")


@dataclass
class Lockout:
    """How long the keypad is refusing to try, and why."""
    failures: int = 0
    locked_until: float = 0.0

    def seconds_left(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return max(0, int(round(self.locked_until - now)))

    def locked(self, now: float | None = None) -> bool:
        return self.seconds_left(now) > 0

    def record_failure(self, now: float | None = None) -> "Lockout":
        now = time.time() if now is None else now
        failures = self.failures + 1
        over = failures - FREE_ATTEMPTS
        if over <= 0:
            return Lockout(failures=failures, locked_until=self.locked_until)
        wait = BACKOFF_SECONDS[min(over - 1, len(BACKOFF_SECONDS) - 1)]
        return Lockout(failures=failures, locked_until=now + wait)

    def record_success(self) -> "Lockout":
        return Lockout()


class PinGate:
    """The PIN, its lockout, and the fact that both outlive a reboot.

    Reads and writes through the Store's meta table so there is one file to back
    up and nothing to keep in sync.
    """

    KEY_HASH = "pin_hash"
    KEY_FAILURES = "pin_failures"
    KEY_UNTIL = "pin_locked_until"

    def __init__(self, store):
        self._store = store

    # ---- the PIN itself --------------------------------------------------
    def is_set(self) -> bool:
        return PinHash.decode(self._store.get_meta(self.KEY_HASH, "") or "") is not None

    def set_pin(self, pin: str) -> None:
        self._store.set_meta(self.KEY_HASH, hash_pin(pin).encode())
        self._save(Lockout())

    def change_pin(self, current: str, new: str) -> bool:
        """Changing the PIN needs the old one. Without this, a child who gets past
        the keypad once owns the device."""
        if self.is_set() and not self.check(current):
            return False
        self.set_pin(new)
        return True

    # ---- trying it -------------------------------------------------------
    def lockout(self) -> Lockout:
        return Lockout(
            failures=int(self._store.get_meta(self.KEY_FAILURES, "0") or 0),
            locked_until=float(self._store.get_meta(self.KEY_UNTIL, "0") or 0.0))

    def _save(self, lo: Lockout) -> None:
        self._store.set_meta(self.KEY_FAILURES, str(lo.failures))
        self._store.set_meta(self.KEY_UNTIL, repr(lo.locked_until))

    def check(self, pin: str, now: float | None = None) -> bool:
        """True when `pin` is right AND the keypad is not currently waiting out a
        lockout. A correct PIN during a lockout is still refused — otherwise the
        lockout only delays someone who is guessing wrong, which is nobody."""
        lo = self.lockout()
        if lo.locked(now):
            return False
        stored = PinHash.decode(self._store.get_meta(self.KEY_HASH, "") or "")
        if stored is None:
            return False
        if verify_pin(pin, stored):
            self._save(lo.record_success())
            return True
        self._save(lo.record_failure(now))
        return False
