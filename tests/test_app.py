"""Ozzy TV as a child and as a parent use it — every screen, driven by keypresses.

Nothing here draws anything. The app is a state machine over plain data, so the
whole of what a remote control can do is reachable from a test, which is the only
way software for a four-year-old gets tested at all: they will not be filing
bugs, and the failures that matter to them (a shelf that opens onto nothing, a
Back button that drops them to a Linux desktop) look like normal operation from
the outside.
"""
import pytest

from conftest import into_tiles, pick_shelf, press, shelves, titles
from ozzytv.app import Action, OzzyApp, Screen
from ozzytv.picks import ROOT_KEY, Mark
from ozzytv.playback import PlayState


class TestWhatIsOnTheDriveIsWhatIsOnTheScreen:
    """You already decided when you copied the file on."""

    def test_a_fresh_install_shows_everything(self, app):
        v = app.view()
        assert v.screen == Screen.BROWSE.value
        assert v.rail, "no shelves"
        assert any("Bluey" in s for s in shelves(v))

    def test_an_empty_drive_still_shows_a_home_screen(self, settings, store, player,
                                                      clock, tmp_path):
        """A Roku with nothing installed still shows you a Roku."""
        settings.media_roots = [str(tmp_path / "nothing")]
        a = OzzyApp(settings, store, player, clock=clock)
        v = a.view()
        assert v.screen == Screen.BROWSE.value
        assert v.rail and v.tiles
        assert v.heading == "Home"

    def test_and_says_where_to_put_films(self, settings, store, player, clock,
                                         tmp_path):
        a = OzzyApp(settings, store, player, clock=clock)
        settings.media_roots = [str(tmp_path / "nothing")]
        a = OzzyApp(settings, store, player, clock=clock)
        joined = " ".join(t + " " + b for t, b in a.view().welcome).lower()
        assert any(str(r).lower() in joined for r in a.settings.roots)

    def test_blocking_one_folder_hides_only_that(self, app, store):
        before = set(shelves(app.view()))
        assert "Bluey" in before
        store.set_mark(app.roots[0].root, "Bluey", Mark.BLOCK)
        app.rescan()
        after = set(shelves(app.view()))
        assert "Bluey" not in after
        assert after, "blocking one shelf emptied the whole menu"


class TestTheGrid:
    def test_filenames_become_something_readable(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        press(app, Action.SELECT)                       # open Series 1
        assert titles(app.view()) == ["Bluey The Magic Xylophone · S1 E1",
                                      "Bluey Hospital · S1 E2",
                                      "Bluey Shadowlands · S1 E10"]

    def test_episodes_are_in_episode_order_not_alphabetical(self, allow_everything):
        """Sorting by the cleaned title looks right until a series names its
        episodes — then it is Hospital, Shadowlands, The Magic Xylophone, which is
        nobody's idea of how to watch a show."""
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        press(app, Action.SELECT)                       # open Series 1
        assert [t.split("E")[-1] for t in titles(app.view())] == ["1", "2", "10"]

    def test_episode_10_comes_after_episode_2(self, allow_everything):
        """And where episodes are numbered in the filename, 10 still follows 2."""
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        assert titles(app.view()) == ["Episode 1", "Episode 2"]

    def test_subtitle_and_image_files_are_not_tiles(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        press(app, Action.SELECT)
        assert not any("srt" in t or "en" == t for t in titles(app.view()))

    def test_hidden_and_system_folders_are_not_shelves(self, allow_everything):
        assert not {".hidden", "@eaDir"} & set(shelves(allow_everything.view()))

    def test_a_folder_with_no_media_is_not_a_shelf(self, allow_everything):
        """'subs' holds only .srt files. A shelf that opens onto nothing teaches a
        child that the remote is broken."""
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        press(app, Action.SELECT)
        assert "subs" not in titles(app.view())

    def test_arrows_move_the_cursor_and_stop_at_the_ends(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        assert app.view().cursor == 0
        n = len(app.view().tiles)
        for _ in range(n + 5):
            press(app, Action.RIGHT)
        assert app.view().cursor == n - 1, "must not run off the end"

    def test_down_moves_a_whole_row(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        app.settings.columns = 1
        press(app, Action.DOWN)
        assert app.view().cursor == 1


class TestGoingInAndOut:
    def test_ok_crosses_from_the_shelf_list_to_the_tiles(self, allow_everything):
        app = allow_everything
        assert app.view().focus == "rail"
        into_tiles(app)
        assert app.view().focus == "grid"

    def test_so_does_right(self, allow_everything):
        press(allow_everything, Action.RIGHT)
        assert allow_everything.view().focus == "grid"

    def test_left_at_the_edge_goes_back_to_the_shelf_list(self, allow_everything):
        """Roku's way out, and the one a child finds by mashing Left."""
        app = allow_everything
        into_tiles(app)
        press(app, Action.LEFT)
        assert app.view().focus == "rail"

    def test_up_off_the_top_row_does_too(self, allow_everything):
        app = allow_everything
        into_tiles(app)
        press(app, Action.UP)
        assert app.view().focus == "rail"

    def test_back_from_the_tiles_returns_to_the_shelf_list(self, allow_everything):
        app = allow_everything
        into_tiles(app)
        press(app, Action.BACK)
        assert app.view().focus == "rail"

    def test_opening_a_folder_tile_goes_into_it(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        press(app, Action.SELECT)                       # Series 1
        assert app.view().subheading == "Ozzy TV › Bluey › Series 1"

    def test_back_comes_out_again(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        press(app, Action.SELECT, Action.BACK)
        assert app.view().subheading == "Ozzy TV"

    def test_the_highlighted_shelf_survives_a_shelf_appearing_above_it(self, allow_everything):
        """"Watch again" arrives the moment anything is played and pushes every
        shelf down one. An index-only cursor then silently highlights a different
        shelf than the one that was being looked at."""
        app = allow_everything
        pick_shelf(app, "PAW Patrol")
        into_tiles(app)
        press(app, Action.SELECT)                       # play, which creates the shelf
        press(app, Action.BACK)
        assert "Watch again" in shelves(app.view())
        assert app.view().rail[app.view().rail_cursor].title == "PAW Patrol"

    def test_back_at_the_top_does_NOTHING(self, allow_everything):
        """The single most important key in the app. A child holds Back until
        something happens; what must never happen is a desktop."""
        app = allow_everything
        for _ in range(20):
            press(app, Action.BACK)
        assert app.view().screen == Screen.BROWSE.value
        assert app.should_quit is False

    def test_quit_is_ignored_outside_the_parent_screen(self, allow_everything):
        app = allow_everything
        press(app, Action.QUIT)
        assert app.should_quit is False


class TestWatching:
    def test_selecting_a_video_plays_it(self, allow_everything, player):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        v = app.view()
        assert v.screen == Screen.PLAYING.value
        assert player.path.name.startswith("Bluey.S01E01")
        assert v.now_title == "Bluey The Magic Xylophone · S1 E1"

    def test_back_stops_and_returns_to_the_shelf(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey")
        into_tiles(app)
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT, Action.BACK)
        assert app.view().screen == Screen.BROWSE.value
        assert app.view().heading == "Series 1"

    def test_ok_pauses_and_unpauses(self, allow_everything, player):
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        press(app, Action.SELECT)
        assert player.state() is PlayState.PAUSED
        press(app, Action.SELECT)
        assert player.state() is PlayState.PLAYING

    def test_the_volume_cannot_be_driven_to_silence(self, allow_everything):
        """A child who mutes the television concludes it is broken."""
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        for _ in range(50):
            press(app, Action.VOLUME_DOWN)
        assert app.view().volume == app.settings.volume_min

    def test_nor_up_past_the_ceiling(self, allow_everything):
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        for _ in range(50):
            press(app, Action.VOLUME_UP)
        assert app.view().volume == app.settings.volume_max

    def test_the_end_of_a_show_returns_to_the_shelf(self, allow_everything, player):
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        player.tick_ms(600_000)
        app.tick()
        assert app.view().screen == Screen.BROWSE.value

    def test_a_file_that_will_not_play_says_so_plainly(self, allow_everything, player):
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        player._state = PlayState.ERROR
        app.tick()
        v = app.view()
        assert v.screen == Screen.MESSAGE.value and "would not play" in v.message


class TestPickingUpWhereWeLeftOff:
    def test_it_resumes(self, allow_everything, player, store):
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        player.tick_ms(120_000)
        app.tick()
        press(app, Action.BACK)
        press(app, Action.SELECT)
        assert app.view().resumed_from_ms >= 100_000

    def test_the_tile_says_so(self, allow_everything, player):
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        player.tick_ms(120_000)
        app.tick()
        press(app, Action.BACK)
        assert app.view().tiles[0].badge == "resume"

    def test_the_first_minute_does_not_count(self, allow_everything, player):
        """Stopping ten seconds in is a mis-press, not a place to come back to."""
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        player.tick_ms(10_000)
        app.tick()
        press(app, Action.BACK, Action.SELECT)
        assert app.view().resumed_from_ms == 0

    def test_finishing_clears_it(self, allow_everything, player):
        app = allow_everything
        pick_shelf(app, "Bluey"); into_tiles(app)
        press(app, Action.SELECT, Action.SELECT, Action.SELECT)
        player.tick_ms(600_000)
        app.tick()
        press(app, Action.SELECT)
        assert app.view().resumed_from_ms == 0


class TestTheGrownUpScreenOpensStraightAway:
    """There is no PIN. A lock on the settings screen is worth having when the
    person filling the drive is not the person holding the remote; here they are
    the same person, and a PIN set once and then half-remembered is a tax on the
    only user this machine has."""

    def test_the_parent_key_opens_it(self, allow_everything):
        press(allow_everything, Action.PARENT)
        assert allow_everything.screen is Screen.PARENT

    def test_no_keypad_appears(self, allow_everything):
        press(allow_everything, Action.PARENT)
        assert allow_everything.view().screen != Screen.PIN.value
        assert allow_everything.view().pin_digits == 0

    def test_it_lists_what_is_on_the_drive(self, allow_everything):
        press(allow_everything, Action.PARENT)
        rows = allow_everything.view().rows
        assert rows, "the grown-up screen has nothing on it"
        assert any("Bluey" in r.title for r in rows)

    def test_back_returns_to_the_shows(self, allow_everything):
        press(allow_everything, Action.PARENT, Action.BACK)
        assert allow_everything.screen is Screen.BROWSE


class TestTheParentScreen:
    @pytest.fixture()
    def parent(self, allow_everything):
        """Straight in — there is no PIN any more."""
        app = allow_everything
        press(app, Action.PARENT)
        return app

    def test_it_lists_the_whole_library_not_just_the_allowed_part(self, parent):
        rels = {r.rel for r in parent.view().rows}
        assert "Films" in rels and "Bluey" in rels and ROOT_KEY in rels

    def test_the_first_press_always_changes_what_the_child_sees(self, parent):
        row = next(i for i, r in enumerate(parent.view().rows) if r.rel == "Films")
        parent._parent_cursor = row
        marks = []
        for _ in range(3):
            press(parent, Action.SELECT)
            marks.append(parent.view().rows[row].mark)
        # Films is visible (the root is allowed), so the FIRST press must hide it.
        assert marks == ["block", "allow", ""]

    def test_a_row_shows_by_default_with_nobody_having_said_so(self, parent):
        r = next(r for r in parent.view().rows if r.rel == "Bluey/Series 1")
        assert r.effective is True
        assert r.mark == "", "nothing was marked, so nothing should claim to be"

    def test_a_blocked_folder_is_still_listed_here(self, allow_everything):
        """Built from the pruned tree, blocking a folder made it vanish from the
        very screen you would use to unblock it."""
        app = allow_everything
        app.store.set_mark(app.roots[0].root, "Bluey", Mark.BLOCK)
        app.rescan()
        app.handle(Action.PARENT)
        r = next(r for r in app.view().rows if r.rel == "Bluey")
        assert r.mark == "block" and r.effective is False
        assert "hidden" in r.note.lower() or "stays hidden" in r.note.lower()

    def test_and_is_gone_from_what_the_child_sees(self, allow_everything):
        app = allow_everything
        app.store.set_mark(app.roots[0].root, "Bluey", Mark.BLOCK)
        app.rescan()
        assert "Bluey" not in shelves(app.view())

    def test_an_untouched_row_says_it_is_shown(self, allow_everything):
        allow_everything.handle(Action.PARENT)
        rows = allow_everything.view().rows
        assert rows
        assert all(r.effective for r in rows), "something is hidden that nobody hid"

    def test_a_change_reaches_the_child_immediately(self, parent):
        row = next(i for i, r in enumerate(parent.view().rows) if r.rel == "Films")
        parent._parent_cursor = row
        press(parent, Action.SELECT)                    # -> block
        press(parent, Action.BACK)
        assert "Films" not in titles(parent.view())

    def test_back_returns_to_the_child_at_the_top(self, parent):
        press(parent, Action.BACK)
        v = parent.view()
        assert v.screen == Screen.BROWSE.value and v.subheading == "Ozzy TV"

    def test_quitting_is_possible_only_from_here(self, parent):
        press(parent, Action.QUIT)
        assert parent.should_quit is True



class TestNothingCrashesTheTelevision:
    def test_an_action_that_explodes_becomes_a_friendly_screen(self, allow_everything,
                                                               monkeypatch):
        app = allow_everything
        monkeypatch.setattr(app, "_browse_key",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        press(app, Action.SELECT)
        v = app.view()
        assert v.screen == Screen.MESSAGE.value
        assert "boom" not in v.message and "Ask a grown-up" in v.message

    def test_a_library_that_vanishes_mid_session(self, allow_everything, library_dir):
        """A USB stick pulled out while a child is browsing."""
        import shutil
        app = allow_everything
        shutil.rmtree(library_dir)
        app.rescan()
        v = app.view()
        assert v.screen == Screen.BROWSE.value, "the menu vanished with the drive"
        assert v.welcome, "and left nothing saying what to do about it"
