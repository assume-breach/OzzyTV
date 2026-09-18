"""The PIN, and the bored child with a whole afternoon.

Four digits is ten thousand combinations. A remote can send one every second.
Without a cost per guess that is under three hours of pressing buttons, and the
child in question has nothing else to do.
"""
import time

import pytest

from ozzytv.security import (BACKOFF_SECONDS, FREE_ATTEMPTS, Lockout, PinGate,
                             PinHash, WeakPin, check_pin_strength, hash_pin,
                             verify_pin)


class TestStoringIt:
    def test_the_pin_is_not_in_the_stored_value(self):
        """The SD card leaves the house in a laptop bag eventually.

        A LONG pin on purpose. The stored form is 104 hex characters, and every
        digit of a PIN is also a hex digit, so a four-digit PIN turns up in it by
        coincidence about once in every 630 runs — a test that fails that often
        for no reason is a test people learn to re-run. Ten digits puts the
        coincidence at about one in ten billion while asserting the same thing.
        """
        stored = hash_pin("1379024687").encode()
        assert "1379024687" not in stored

    def test_the_same_pin_stores_differently_every_time(self):
        """Salted: two Ozzy TVs with the same PIN must not look alike, and a
        matching stored value must not be evidence of a matching PIN."""
        assert hash_pin("1379").encode() != hash_pin("1379").encode()

    def test_the_right_pin_verifies(self):
        h = hash_pin("1379")
        assert verify_pin("1379", h) is True

    def test_a_wrong_one_does_not(self):
        h = hash_pin("1379")
        for wrong in ("1378", "379", "13790", "", "abcd"):
            assert verify_pin(wrong, h) is False

    def test_two_identical_pins_hash_differently(self):
        """Salted, so a matching pair of stored values does not reveal that two
        boxes share a PIN."""
        assert hash_pin("1379").encode() != hash_pin("1379").encode()

    def test_a_stored_value_survives_a_round_trip(self):
        h = hash_pin("1379")
        assert verify_pin("1379", PinHash.decode(h.encode())) is True

    def test_a_corrupt_stored_value_is_not_a_crash(self):
        for junk in ("", "nonsense", "scrypt$1$2$3", "md5$1$1$aa$bb"):
            assert PinHash.decode(junk) is None


class TestRefusingSillyPins:
    @pytest.mark.parametrize("pin,because", [
        ("1111", "same digit"), ("1234", "simple run"), ("4321", "simple run"),
        ("123", "digits"), ("abcd", "digits only"), ("", "digits"),
    ])
    def test_it_is_refused(self, pin, because):
        with pytest.raises(WeakPin):
            check_pin_strength(pin)

    def test_the_reason_is_something_a_parent_can_act_on(self):
        with pytest.raises(WeakPin, match="simple run"):
            check_pin_strength("2345")

    @pytest.mark.parametrize("pin", ["1379", "9042", "271828"])
    def test_a_reasonable_pin_is_accepted(self, pin):
        check_pin_strength(pin)


class TestMakingGuessesCost:
    def test_the_first_few_tries_are_free(self):
        lo = Lockout()
        for _ in range(FREE_ATTEMPTS):
            lo = lo.record_failure(now=0)
        assert lo.locked(now=0) is False

    def test_then_it_starts_waiting(self):
        lo = Lockout()
        for _ in range(FREE_ATTEMPTS + 1):
            lo = lo.record_failure(now=0)
        assert lo.seconds_left(now=0) == BACKOFF_SECONDS[0]

    def test_and_waits_longer_each_time(self):
        lo, waits = Lockout(), []
        for _ in range(FREE_ATTEMPTS + len(BACKOFF_SECONDS)):
            lo = lo.record_failure(now=0)
            waits.append(lo.seconds_left(now=0))
        assert waits[FREE_ATTEMPTS:] == list(BACKOFF_SECONDS)

    def test_it_never_stops_costing(self):
        lo = Lockout()
        for _ in range(50):
            lo = lo.record_failure(now=0)
        assert lo.seconds_left(now=0) == BACKOFF_SECONDS[-1]

    def test_getting_it_right_clears_the_slate(self):
        lo = Lockout(failures=9, locked_until=100)
        assert lo.record_success().locked(now=0) is False


class TestTheGate:
    def test_a_correct_pin_during_a_lockout_is_still_refused(self, store):
        """Otherwise the delay only inconveniences someone guessing wrong — which,
        by definition, is not the person who knows the PIN."""
        gate = PinGate(store)
        gate.set_pin("1379")
        now = 1000.0
        for _ in range(FREE_ATTEMPTS + 1):
            gate.check("0000", now)
        assert gate.check("1379", now) is False
        assert gate.check("1379", now + 3600) is True

    def test_the_lockout_survives_pulling_the_plug(self, store):
        """The first thing anyone tries."""
        gate = PinGate(store)
        gate.set_pin("1379")
        for _ in range(FREE_ATTEMPTS + 1):
            gate.check("0000", 1000.0)
        assert PinGate(store).lockout().locked(1000.0) is True

    def test_changing_the_pin_needs_the_old_one(self, store):
        """A child who gets past the keypad once must not be able to own the box."""
        gate = PinGate(store)
        gate.set_pin("1379")
        assert gate.change_pin("0000", "2468") is False
        assert gate.check("1379", 1e9) is True
        assert gate.change_pin("1379", "2468") is True
        assert gate.check("2468", 1e9) is True

    def test_a_box_with_no_pin_refuses_every_pin(self, store):
        assert PinGate(store).is_set() is False
        assert PinGate(store).check("1379") is False
