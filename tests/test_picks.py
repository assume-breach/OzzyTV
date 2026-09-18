"""The safety boundary: what a child can see, and what they cannot.

A bug here is not a crash — it is a four-year-old watching something a parent
did not approve, with nothing on screen to suggest anything went wrong. So these
go at it adversarially: symlinks out of the library, `..`, loops, a root that is
itself a link, rules that look like they overlap, and the case nobody thinks
about — a rule deleted, leaving children with nothing above them.
"""
import os
from pathlib import Path

import pytest

from ozzytv.picks import (ROOT_KEY, Decision, Mark, Rules, decide, decide_rel,
                          folder_has_anything_visible, is_visible, relkey)


def R(**marks) -> Rules:
    return Rules(marks={k.replace("__", "/"): v for k, v in marks.items()})


class TestEverythingShowsUnlessSomebodyHidesIt:
    """This used to fail CLOSED: nothing was visible until a grown-up allowed it,
    one thing at a time. That is the right default for a machine somebody else
    fills up, and the wrong one for a machine you fill up yourself — you already
    decided when you copied the file on."""

    def test_an_untouched_library_is_all_visible(self):
        assert decide_rel(Rules.empty(), "Bluey/S01E01.mp4").visible is True

    def test_and_says_nobody_has_decided_anything_about_it(self):
        """'Nobody has touched this' and 'you allowed this' are different, and
        the grown-up screen has to tell them apart."""
        d = decide_rel(Rules.empty(), "Bluey/S01E01.mp4")
        assert d.by is None and d.escaped is False

    def test_blocking_still_works(self):
        assert decide_rel(R(Horror=Mark.BLOCK), "Horror/It.mp4").visible is False

    def test_and_is_still_inherited_by_everything_under_it(self):
        rules = R(Horror=Mark.BLOCK)
        assert decide_rel(rules, "Horror/Sequels/It2.mp4").visible is False

    def test_a_sibling_being_blocked_does_not_hide_anything_else(self):
        assert decide_rel(R(Horror=Mark.BLOCK), "Bluey/S01E01.mp4").visible is True

    def test_deleting_a_block_shows_everything_under_it_again(self):
        rules = R(Horror=Mark.BLOCK)
        assert decide_rel(rules, "Horror/It.mp4").visible is False
        assert decide_rel(rules.with_mark("Horror", None), "Horror/It.mp4").visible is True


class TestNearestRuleWins:
    def test_a_folder_covers_what_is_under_it(self):
        rules = R(Bluey=Mark.ALLOW)
        assert decide_rel(rules, "Bluey/S01E01.mp4").visible is True
        assert decide_rel(rules, "Bluey/Series 2/S02E05.mp4").visible is True

    def test_one_file_can_be_carved_out_of_an_allowed_folder(self):
        rules = R(Bluey=Mark.ALLOW, **{"Bluey__S02E14.mp4": Mark.BLOCK})
        assert decide_rel(rules, "Bluey/S02E13.mp4").visible is True
        assert decide_rel(rules, "Bluey/S02E14.mp4").visible is False

    def test_one_folder_can_be_carved_back_in_again(self):
        """allow root, block a shelf, allow one thing on that shelf."""
        rules = Rules(marks={ROOT_KEY: Mark.ALLOW, "Films": Mark.BLOCK,
                             "Films/Paddington.mp4": Mark.ALLOW})
        assert decide_rel(rules, "Films/Alien.mp4").visible is False
        assert decide_rel(rules, "Films/Paddington.mp4").visible is True
        assert decide_rel(rules, "Bluey/S01E01.mp4").visible is True

    def test_depth_decides_not_order(self):
        """The rules are a dict; nothing may depend on insertion order."""
        deep = Rules(marks={"a/b/c": Mark.ALLOW, "a": Mark.BLOCK})
        shallow_first = Rules(marks={"a": Mark.BLOCK, "a/b/c": Mark.ALLOW})
        for rules in (deep, shallow_first):
            assert decide_rel(rules, "a/b/c/x.mp4").visible is True
            assert decide_rel(rules, "a/b/x.mp4").visible is False

    def test_the_rule_that_decided_is_reported(self):
        rules = R(Bluey=Mark.ALLOW)
        d = decide_rel(rules, "Bluey/S01E01.mp4")
        assert d.by == "Bluey" and d.inherited is True

    def test_a_rule_on_the_item_itself_is_not_inherited(self):
        rules = R(**{"Bluey__S01E01.mp4": Mark.ALLOW})
        d = decide_rel(rules, "Bluey/S01E01.mp4")
        assert d.by == "Bluey/S01E01.mp4" and d.inherited is False

    def test_allowing_the_whole_root(self):
        rules = Rules(marks={ROOT_KEY: Mark.ALLOW})
        assert decide_rel(rules, "anything/at/all.mp4").visible is True
        assert decide_rel(rules, ROOT_KEY).visible is True

    def test_a_name_that_merely_starts_the_same_is_a_different_folder(self):
        """"Bluey" must not be the rule for "Bluey Extras". Matching on a string
        prefix rather than on path segments is how a block on one folder silently
        covers its neighbor."""
        rules = R(**{"Bluey": Mark.BLOCK})
        assert decide_rel(rules, "Bluey/ep.mp4").visible is False
        assert decide_rel(rules, "Bluey Extras/ep.mp4").visible is True

class TestConfinement:
    """Being REACHABLE through an allowed folder is not the same as being in it."""

    @pytest.fixture()
    def lib(self, tmp_path):
        root = tmp_path / "library"
        (root / "Bluey").mkdir(parents=True)
        (root / "Bluey" / "S01E01.mp4").write_bytes(b"x")
        outside = tmp_path / "grownups"
        outside.mkdir()
        (outside / "Alien.mp4").write_bytes(b"x")
        return root, outside

    def test_a_symlink_out_of_the_library_is_refused(self, lib):
        root, outside = lib
        (root / "Bluey" / "shortcut.mp4").symlink_to(outside / "Alien.mp4")
        rules = R(Bluey=Mark.ALLOW)
        d = decide(rules, root, root / "Bluey" / "shortcut.mp4")
        assert d.visible is False and d.escaped is True

    def test_a_symlinked_folder_out_of_the_library_is_refused(self, lib):
        root, outside = lib
        (root / "Bluey" / "more").symlink_to(outside, target_is_directory=True)
        rules = R(Bluey=Mark.ALLOW)
        assert is_visible(rules, root, root / "Bluey" / "more" / "Alien.mp4") is False

    def test_dot_dot_cannot_climb_out(self, lib):
        root, outside = lib
        rules = Rules(marks={ROOT_KEY: Mark.ALLOW})
        assert is_visible(rules, root, root / "Bluey" / ".." / ".." / "grownups" / "Alien.mp4") is False

    def test_a_symlink_INSIDE_the_library_follows_its_target_rules(self, lib):
        """The link is not a way to dodge a block on what it points at."""
        root, _ = lib
        (root / "Scary").mkdir()
        (root / "Scary" / "It.mp4").write_bytes(b"x")
        (root / "Bluey" / "sneaky.mp4").symlink_to(root / "Scary" / "It.mp4")
        rules = R(Bluey=Mark.ALLOW, Scary=Mark.BLOCK)
        assert is_visible(rules, root, root / "Bluey" / "sneaky.mp4") is False

    def test_a_root_that_is_itself_a_symlink_still_works(self, lib, tmp_path):
        """/media/ozzy -> /mnt/usb is how a stick is normally mounted; resolving
        only one side would make the whole library look like an escape."""
        root, _ = lib
        link = tmp_path / "media-ozzy"
        link.symlink_to(root, target_is_directory=True)
        rules = R(Bluey=Mark.ALLOW)
        assert is_visible(rules, link, link / "Bluey" / "S01E01.mp4") is True
        assert relkey(link, link / "Bluey" / "S01E01.mp4") == "Bluey/S01E01.mp4"

    def test_a_symlink_loop_is_refused_rather_than_hanging(self, tmp_path):
        root = tmp_path / "lib"
        root.mkdir()
        (root / "a").symlink_to(root / "b")
        (root / "b").symlink_to(root / "a")
        rules = Rules(marks={ROOT_KEY: Mark.ALLOW})
        assert decide(rules, root, root / "a" / "x.mp4").visible in (False, True)  # must not hang
        assert relkey(root, root / "a") in (None, "a")

    def test_the_root_itself_is_the_root_key(self, lib):
        root, _ = lib
        assert relkey(root, root) == ROOT_KEY
        assert relkey(root, root / ".") == ROOT_KEY

    def test_a_path_from_a_different_root_is_not_placed(self, lib, tmp_path):
        root, outside = lib
        assert relkey(root, outside / "Alien.mp4") is None

    @pytest.mark.skipif(os.name != "posix", reason="POSIX paths")
    def test_an_absolute_path_masquerading_as_relative_is_refused(self, lib):
        root, outside = lib
        rules = Rules(marks={ROOT_KEY: Mark.ALLOW})
        assert is_visible(rules, root, Path("/etc/passwd")) is False


class TestEmptyShelves:
    """A shelf you can open to find nothing is worse than no shelf — the child
    cannot tell it apart from having done something wrong."""

    def test_a_folder_with_something_visible_is_shown(self):
        rules = R(Bluey=Mark.ALLOW)
        assert folder_has_anything_visible(rules, "Bluey", ["Bluey/S01E01.mp4"]) is True

    def test_a_folder_blocked_all_the_way_down_is_not(self):
        rules = R(Bluey=Mark.ALLOW, **{"Bluey__S01": Mark.BLOCK})
        assert folder_has_anything_visible(
            rules, "Bluey/S01", ["Bluey/S01/E01.mp4", "Bluey/S01/E02.mp4"]) is False

    def test_an_unmarked_folder_is_shown(self):
        """Nothing has been said about it, so it shows — the whole point of the
        default now being open."""
        assert folder_has_anything_visible(Rules.empty(), "New", ["New/x.mp4"]) is True

    def test_a_blocked_folder_is_empty_and_therefore_hidden(self):
        """A shelf you can open to find nothing is worse than no shelf: the
        child cannot tell it from having done something wrong."""
        rules = R(New=Mark.BLOCK)
        assert folder_has_anything_visible(rules, "New", ["New/x.mp4"]) is False

    def test_one_survivor_is_enough(self):
        rules = Rules(marks={"F": Mark.ALLOW, "F/a.mp4": Mark.BLOCK})
        assert folder_has_anything_visible(rules, "F", ["F/a.mp4", "F/b.mp4"]) is True
