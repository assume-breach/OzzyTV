"""Playing something, and remembering where we got to.

VLC does the playing. What is tested here is everything VLC has no opinion
about — and every one of these is a thing a child notices: a programme that
starts again from the beginning, a film that replays its last minute for ever,
a television that has gone silent.
"""
import pytest

from ozzytv.playback import (RESUME_SAVE_EVERY_MS, FakePlayer, PlaybackSession,
                             PlayState)


@pytest.fixture()
def video(tmp_path):
    f = tmp_path / "film.mp4"
    f.write_bytes(b"v" * 2048)
    return f


@pytest.fixture()
def session(store, settings, player):
    return PlaybackSession(player, store, settings)


class TestPickingUpWhereWeLeftOff:
    def test_the_position_is_written_down_as_it_goes(self, session, player, video, store):
        """Not at the end — a Raspberry Pi is turned off by pulling the plug, so
        whatever has not been written down by then is lost."""
        session.start(video, "Film")
        player.tick_ms(90_000)
        session.tick()
        first = store.get_resume(video)
        assert first is not None and first >= 90_000

        player.tick_ms(RESUME_SAVE_EVERY_MS * 3)
        session.tick()
        assert store.get_resume(video) > first, "it stopped writing after the first time"

    def test_but_not_on_every_single_tick(self, session, player, video, store):
        """Four writes a second to an SD card that has to last years."""
        session.start(video, "Film")
        player.tick_ms(90_000)
        session.tick()
        at_90s = store.get_resume(video)
        player.tick_ms(1_000)
        session.tick()
        assert store.get_resume(video) == at_90s

    def test_and_is_used_next_time(self, session, player, video):
        session.start(video, "Film")
        player.tick_ms(200_000)
        session.tick()
        session.stop()
        now = session.start(video, "Film")
        assert now.resumed_from_ms >= 190_000

    def test_the_first_minute_does_not_count_as_a_place(self, session, player, video, store):
        """Stopping ten seconds in is a mis-press."""
        session.start(video, "Film")
        player.tick_ms(20_000)
        session.tick()
        session.stop()
        assert store.get_resume(video) is None

    def test_nor_does_the_last_minute(self, session, player, video, store):
        """Otherwise the end of a film replays every time it is chosen."""
        session.start(video, "Film")
        player.tick_ms(player.duration_ms() - 10_000)
        session.tick()
        assert store.get_resume(video) is None

    def test_finishing_clears_it(self, session, player, video, store):
        session.start(video, "Film")
        player.tick_ms(300_000)
        session.tick()
        player.tick_ms(600_000)
        assert session.tick() is PlayState.ENDED
        assert store.get_resume(video) is None

    def test_a_replaced_file_starts_again(self, session, player, video, store):
        """Same name, different programme. Resuming twenty minutes in would drop a
        child into the middle of something nobody chose."""
        session.start(video, "Film")
        player.tick_ms(300_000)
        session.tick()
        session.stop()
        video.write_bytes(b"different content entirely")
        assert session.start(video, "Film").resumed_from_ms == 0

    def test_a_resume_past_the_end_of_a_shorter_file_is_clamped(self, store, settings,
                                                                video):
        """The remembered position can outlive the file it belonged to."""
        store.save_resume(video, 500_000, 600_000)
        short = FakePlayer(duration_ms=120_000)
        s = PlaybackSession(short, store, settings)
        s.start(video, "Film")
        s.tick()
        assert short.position_ms() <= 120_000

    def test_resume_can_be_switched_off(self, store, settings, player, video):
        settings.resume = False
        s = PlaybackSession(player, store, settings)
        store.save_resume(video, 300_000, 600_000)
        assert s.start(video, "Film").resumed_from_ms == 0


class TestTheVolume:
    def test_it_cannot_be_driven_to_silence(self, session, settings):
        """A child who mutes the television concludes it is broken."""
        for _ in range(100):
            session.change_volume(-10)
        assert session.volume == settings.volume_min

    def test_nor_through_the_ceiling(self, session, settings):
        for _ in range(100):
            session.change_volume(10)
        assert session.volume == settings.volume_max

    def test_a_silly_stored_volume_is_clamped_on_startup(self, store, settings, player):
        settings.volume = 5000
        assert PlaybackSession(player, store, settings).volume == settings.volume_max


class TestSeeking:
    def test_it_does_not_run_off_the_start(self, session, player, video):
        session.start(video, "Film")
        assert session.seek(-999_999) == 0

    def test_nor_off_the_end(self, session, player, video):
        session.start(video, "Film")
        assert session.seek(999_999) <= player.duration_ms()

    def test_pause_writes_the_position_down_immediately(self, session, player, video, store):
        """A paused programme is one somebody walked away from."""
        session.start(video, "Film")
        player.tick_ms(120_000)
        session.tick()
        store.clear_resume(video)
        session.toggle_pause()
        assert store.get_resume(video) is not None


class TestTheFakeEngine:
    """It stands in for VLC in every other test, so it has to behave."""

    def test_it_reaches_the_end_and_stops(self):
        p = FakePlayer(duration_ms=1000)
        p.open("x")
        p.tick_ms(5000)
        assert p.state() is PlayState.ENDED and p.position_ms() == 1000

    def test_a_paused_engine_does_not_advance(self):
        p = FakePlayer()
        p.open("x")
        p.pause()
        p.tick_ms(10_000)
        assert p.position_ms() == 0
