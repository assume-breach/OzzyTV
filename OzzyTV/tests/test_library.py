"""Turning a drive full of files into shelves a child can use.

The two things that go wrong here are not crashes. A tile reading
`Bluey.S01E01.1080p.WEB-DL.x264-GRP.mkv` is no use to someone who cannot read
well yet, and episodes in alphabetical order are no use to anyone.
"""
import os
from pathlib import Path

import pytest

from ozzytv.library import (Kind, clean_title, episode_of, natural_key,
                            prune_empty_folders, scan, scan_root, sort_key)


class TestNamesOnTiles:
    @pytest.mark.parametrize("filename,expected", [
        ("Bluey.S01E01.The Magic Xylophone.1080p.WEB-DL.x264-GRP",
         "Bluey The Magic Xylophone · S1 E1"),
        ("Paddington (2014)", "Paddington"),
        ("Alien (1979) 1080p BluRay x264", "Alien"),
        ("The_Gruffalo_720p", "The Gruffalo"),
        ("Peppa Pig - S03E22 - The Toy Cupboard [HDTV]", "Peppa Pig The Toy Cupboard · S3 E22"),
    ])
    def test_a_release_name_becomes_a_title(self, filename, expected):
        assert clean_title(filename) == expected

    def test_a_dot_before_a_space_is_punctuation_not_a_separator(self):
        """'Mr. Men' keeps its full stop; 'Bluey.S01E01.Something' loses all of
        its. Keying on 'the name has no spaces' is the obvious rule and it fails
        on exactly the common case — a dotted release name whose episode title
        has spaces in it."""
        assert clean_title("Mr. Men") == "Mr. Men"
        assert clean_title("Dr. Seuss - The Lorax") == "Dr. Seuss The Lorax"
        assert "." not in clean_title("Bluey.S01E01.The Magic Xylophone.1080p")

    def test_the_words_a_parent_chose_are_left_alone(self):
        """Re-capitalising turns 'PAW Patrol' into 'Paw Patrol' and is never
        worth it."""
        assert clean_title("PAW Patrol") == "PAW Patrol"
        assert clean_title("ozzys birthday") == "ozzys birthday"

    def test_a_name_that_is_only_junk_keeps_its_filename(self):
        """Better an ugly tile than a blank one."""
        assert clean_title("1080p") == "1080p"

    def test_unicode_survives(self):
        assert clean_title("Les Triplettes de Belleville") == "Les Triplettes de Belleville"
        assert clean_title("となりのトトロ") == "となりのトトロ"


class TestTheOrderOnAShelf:
    def test_ten_comes_after_two(self):
        names = ["Episode 10", "Episode 2", "Episode 1"]
        assert sorted(names, key=natural_key) == ["Episode 1", "Episode 2", "Episode 10"]

    def test_names_of_different_shapes_do_not_raise(self):
        """natural_key used to return a list mixing ints and strs, which raises
        TypeError the moment two names differ in shape — inside a sort of
        whatever happened to be on the drive."""
        names = ["Episode 2", "Extras", "3", "a1b2", "", "Zzz"]
        assert len(sorted(names, key=natural_key)) == len(names)

    def test_episodes_sort_by_number_not_by_episode_title(self):
        files = ["S01E10 Shadowlands", "S01E02 Hospital", "S01E01 The Magic Xylophone"]
        order = sorted(files, key=lambda f: sort_key(clean_title(f), f))
        assert [episode_of(f)[1] for f in order] == [1, 2, 10]

    def test_folders_without_episode_numbers_sort_naturally(self):
        names = ["Series 10", "Series 2", "Series 1"]
        order = sorted(names, key=lambda n: sort_key(n, n))
        assert order == ["Series 1", "Series 2", "Series 10"]


class TestWhatCountsAsMedia:
    def test_only_media_becomes_a_node(self, library_dir):
        root = scan_root(library_dir)
        names = {n.path.name for n in root.walk()}
        assert "en.srt" not in names and "poster.jpg" not in names

    def test_hidden_and_appliance_folders_are_skipped(self, library_dir):
        root = scan_root(library_dir)
        rels = {n.rel for n in root.walk()}
        assert not any(r.startswith(".hidden") or r.startswith("@eaDir") for r in rels)

    def test_a_folder_holding_no_media_is_pruned(self, library_dir):
        """'subs' holds only subtitles. As a shelf it opens onto nothing, which a
        child cannot tell apart from having pressed the wrong button."""
        pruned = prune_empty_folders(scan_root(library_dir))
        assert "Bluey/Series 1/subs" not in {n.rel for n in pruned.walk()}

    def test_a_missing_root_is_not_an_error(self, tmp_path):
        """A USB stick that is not plugged in is the normal case."""
        assert scan_root(tmp_path / "nope") is None
        assert scan([tmp_path / "nope"]) == []

    def test_a_file_given_as_a_root_is_refused(self, tmp_path):
        f = tmp_path / "a.mp4"
        f.write_bytes(b"x")
        assert scan_root(f) is None


class TestAwkwardDrives:
    def test_a_symlink_loop_does_not_hang_the_scan(self, tmp_path):
        root = tmp_path / "lib"
        (root / "a").mkdir(parents=True)
        (root / "a" / "clip.mp4").write_bytes(b"v")
        (root / "a" / "back").symlink_to(root, target_is_directory=True)
        node = scan_root(root)              # must return, not spin
        assert node is not None
        assert len(list(node.walk())) < 50

    def test_an_unreadable_folder_is_empty_rather_than_fatal(self, tmp_path):
        root = tmp_path / "lib"
        (root / "open").mkdir(parents=True)
        (root / "open" / "ok.mp4").write_bytes(b"v")
        shut = root / "shut"
        shut.mkdir()
        (shut / "x.mp4").write_bytes(b"v")
        os.chmod(shut, 0o000)
        try:
            node = scan_root(root)
            assert "open/ok.mp4" in {n.rel for n in node.walk()}
        finally:
            os.chmod(shut, 0o755)

    def test_a_very_deep_tree_stops_rather_than_recursing_for_ever(self, tmp_path):
        root = tmp_path / "lib"
        deep = root
        for i in range(60):
            deep = deep / f"d{i}"
        deep.mkdir(parents=True)
        (deep / "clip.mp4").write_bytes(b"v")
        assert scan_root(root) is not None   # bounded by MAX_DEPTH, no RecursionError

    def test_a_file_with_no_extension_is_not_media(self, tmp_path):
        root = tmp_path / "lib"
        root.mkdir()
        (root / "README").write_text("hello")
        assert not [n for n in scan_root(root).walk() if n.is_playable]
