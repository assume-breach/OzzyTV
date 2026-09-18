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


class TestNothingUntilAGrownUpChooses:
    def test_a_fresh_install_shows_no_programmes(self, app):
        v = app.view()
        assert v.screen == Screen.MESSAGE.value
        assert "Ask a grown-up" in v.message

    def test_it_does_not_look_like_a_fault(self, app):
        """A child cannot tell 'broken' from 'not set up', so it must not read as
        an error at all."""
        m = app.view().message
        assert "error" not in m.lower() and "fail" not in m.lower()

    def test_a_drive_with_no_media_says_something_different(self, settings, store,
                                                            player, tmp_path):
        empty = tmp_path / "Empty"
        empty.mkdir()
        settings.media_roots = [str(empty)]
        v = OzzyApp(settings, store, player).view()
        assert "plug in the drive" in v.message

    def test_allowing_one_folder_shows_only_that(self, app, store):
        store.set_mark(app.roots[0].root, "Bluey", Mark.ALLOW)
        app.rescan()
        assert shelves(app.view()) == ["Bluey"]

    def test_a_blocked_shelf_never_appears(self, app, store):
        root = app.roots[0].root
        store.set_mark(root, ROOT_KEY, Mark.ALLOW)
        store.set_mark(root, "Films", Mark.BLOCK)
        app.rescan()
        assert "Films" not in shelves(app.view())
        assert "Bluey" in shelves(app.view())


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
        nobody's idea of how to watch a programme."""
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

    def test_the_end_of_a_programme_returns_to_the_shelf(self, allow_everything, player):
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


class TestTheGrownUpGate:
    def test_the_parent_key_asks_for_a_pin(self, allow_everything, store):
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT)
        assert app.view().screen == Screen.PIN.value

    def test_the_right_pin_gets_in(self, allow_everything):
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT, "d1", "d3", "d7", "d9", Action.SELECT)
        assert app.view().screen == Screen.PARENT.value

    def test_the_wrong_pin_does_not(self, allow_everything):
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT, "d0", "d0", "d0", "d0", Action.SELECT)
        v = app.view()
        assert v.screen == Screen.PIN.value and "Wrong PIN" in v.pin_error

    def test_guessing_starts_costing_time(self, allow_everything, clock):
        """Ten thousand combinations and a bored child with a whole afternoon."""
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT)
        for _ in range(4):
            press(app, "d0", "d0", "d0", "d0", Action.SELECT)
        assert app.view().lock_seconds > 0

    def test_and_the_right_pin_is_refused_while_it_is_waiting(self, allow_everything):
        """Otherwise the delay only inconveniences someone guessing wrong — which
        is nobody, once they know the PIN."""
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT)
        for _ in range(4):
            press(app, "d0", "d0", "d0", "d0", Action.SELECT)
        press(app, "d1", "d3", "d7", "d9", Action.SELECT)
        assert app.view().screen == Screen.PIN.value

    def test_the_wait_passes(self, allow_everything, clock):
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT)
        for _ in range(4):
            press(app, "d0", "d0", "d0", "d0", Action.SELECT)
        clock.advance(3600)
        press(app, "d1", "d3", "d7", "d9", Action.SELECT)
        assert app.view().screen == Screen.PARENT.value

    def test_a_lockout_survives_pulling_the_plug(self, allow_everything, store,
                                                 settings, player, clock):
        """The first thing anyone tries."""
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT)
        for _ in range(4):
            press(app, "d0", "d0", "d0", "d0", Action.SELECT)
        reborn = OzzyApp(settings, store, player, clock=clock)
        assert reborn.pin.lockout().locked(clock()) is True

    def test_a_box_with_no_pin_yet_lets_the_first_grown_up_in(self, allow_everything):
        """Otherwise the parent is locked out of the device they just set up."""
        app = allow_everything
        press(app, Action.PARENT)
        v = app.view()
        assert v.screen == Screen.PARENT.value and "Set a PIN" in v.message

    def test_the_keypad_never_shows_the_digits(self, allow_everything):
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT, "d1", "d3")
        v = app.view()
        assert v.pin_digits == 2 and "1" not in v.heading


class TestTheParentScreen:
    @pytest.fixture()
    def parent(self, allow_everything):
        app = allow_everything
        app.pin.set_pin("1379")
        press(app, Action.PARENT, "d1", "d3", "d7", "d9", Action.SELECT)
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

    def test_a_row_says_where_its_answer_came_from(self, parent):
        r = next(r for r in parent.view().rows if r.rel == "Bluey/Series 1")
        assert r.effective is True and r.inherited_from == ROOT_KEY

    def test_allowing_a_folder_warns_that_it_is_a_standing_yes(self, parent):
        r = next(r for r in parent.view().rows if r.rel == ROOT_KEY)
        assert "new files here show up too" in r.note

    def test_an_unchosen_row_says_so(self, allow_everything, store):
        store.clear_marks(allow_everything.roots[0].root)
        app = allow_everything
        app.rescan()
        app.pin.set_pin("1379")
        press(app, Action.PARENT, "d1", "d3", "d7", "d9", Action.SELECT)
        r = next(r for r in app.view().rows if r.rel == "Films")
        assert r.note == "not chosen yet"

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

    def test_the_pin_can_be_changed_from_here(self, parent):
        press(parent, Action.PARENT)                    # 'set a new PIN'
        assert parent.view().pin_prompt == "set"
        press(parent, "d2", "d4", "d6", "d8", Action.SELECT)
        assert parent.view().pin_prompt == "confirm"
        press(parent, "d2", "d4", "d6", "d8", Action.SELECT)
        assert parent.view().screen == Screen.PARENT.value
        assert parent.pin.check("2468") is True

    def test_a_mistyped_confirmation_starts_again(self, parent):
        press(parent, Action.PARENT)
        press(parent, "d2", "d4", "d6", "d8", Action.SELECT)
        press(parent, "d1", "d1", "d1", "d1", Action.SELECT)
        v = parent.view()
        assert v.pin_prompt == "set" and "did not match" in v.pin_error
        assert parent.pin.check("1379") is True, "the old PIN must still work"

    def test_an_obvious_pin_is_refused_with_a_reason(self, parent):
        press(parent, Action.PARENT)
        press(parent, "d1", "d2", "d3", "d4", Action.SELECT)
        assert "simple run" in parent.view().pin_error


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
        assert app.view().screen == Screen.MESSAGE.value
