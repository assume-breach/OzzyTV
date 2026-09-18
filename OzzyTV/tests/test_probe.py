"""Whether a Pi 3 can really play a file — and who finds out.

Unprobed, the answer arrives as a four-year-old watching a stuttering picture
with perfect sound and deciding the television is broken. Probed, it arrives in
the parent screen, next to the file, before it is ever allowed.
"""
import pytest

from ozzytv.probe import Playability, Verdict, judge, probe


def stream(codec, w=1920, h=1080, fps="25/1"):
    return {"codec_name": codec, "width": w, "height": h, "avg_frame_rate": fps}


class TestWhatThisBoardCanDo:
    def test_1080p_h264_is_what_the_hardware_is_for(self):
        assert judge(stream("h264")).verdict == Verdict.YES

    @pytest.mark.parametrize("codec", ["hevc", "vp9", "av1"])
    def test_the_modern_codecs_are_hopeless_on_it(self, codec):
        v = judge(stream(codec, 1920, 1080))
        assert v.verdict == Verdict.NO and codec.upper() in v.detail

    def test_4k_is_beyond_it_even_in_h264(self):
        v = judge(stream("h264", 3840, 2160))
        assert v.verdict == Verdict.NO and "3840" in v.detail

    def test_so_is_high_frame_rate(self):
        v = judge(stream("h264", 1920, 1080, "60/1"))
        assert v.verdict == Verdict.NO and "60 fps" in v.detail

    def test_1088_is_still_1080p(self):
        """H.264 pads to whole macroblocks, so plenty of real 1080p files report
        1088 and would be refused by a naive height check."""
        assert judge(stream("h264", 1920, 1088)).verdict == Verdict.YES

    def test_an_old_codec_at_sd_is_fine_in_software(self):
        assert judge(stream("mpeg4", 720, 576)).verdict == Verdict.YES

    def test_but_not_at_hd(self):
        v = judge(stream("mpeg4", 1920, 1080))
        assert v.verdict == Verdict.NO and "software" in v.detail

    def test_the_detail_is_worth_reading(self):
        """A parent needs to know what to do — re-encode it, or find another copy."""
        assert "no decoder" in judge(stream("hevc")).detail


class TestSayingSoRatherThanGuessing:
    def test_a_file_we_could_not_read_is_unknown(self):
        assert judge(None).verdict == Verdict.UNKNOWN

    def test_a_codec_nobody_tested_is_unknown_not_no(self):
        """Guessing 'no' would hide a file that plays perfectly well."""
        assert judge(stream("prores")).verdict == Verdict.UNKNOWN

    def test_a_file_with_no_video_stream_is_unknown(self):
        assert judge({"codec_name": "", "width": 0, "height": 0}).verdict == Verdict.UNKNOWN

    def test_a_broken_frame_rate_does_not_raise(self):
        assert judge(stream("h264", fps="0/0")).verdict == Verdict.YES
        assert judge(stream("h264", fps="")).verdict == Verdict.YES
        assert judge(stream("h264", fps="nonsense")).verdict == Verdict.YES

    def test_with_no_ffprobe_it_admits_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ozzytv.probe.shutil.which", lambda _: None)
        f = tmp_path / "a.mkv"
        f.write_bytes(b"x")
        p = probe(f)
        assert p.verdict == Verdict.UNKNOWN and "install ffmpeg" in p.detail


class TestRemembering:
    def test_an_answer_is_cached(self, tmp_path, store, monkeypatch):
        f = tmp_path / "a.mkv"
        f.write_bytes(b"x")
        calls = []
        monkeypatch.setattr("ozzytv.probe.shutil.which", lambda _: "/usr/bin/ffprobe")
        monkeypatch.setattr("ozzytv.probe._run_ffprobe",
                            lambda p: calls.append(p) or stream("h264"))
        assert probe(f, store).verdict == Verdict.YES
        assert probe(f, store).verdict == Verdict.YES
        assert len(calls) == 1

    def test_a_re_encoded_file_is_judged_again(self, tmp_path, store, monkeypatch):
        """The cache is keyed on size and mtime, so a replacement does not inherit
        the old verdict."""
        f = tmp_path / "a.mkv"
        f.write_bytes(b"x")
        monkeypatch.setattr("ozzytv.probe.shutil.which", lambda _: "/usr/bin/ffprobe")
        monkeypatch.setattr("ozzytv.probe._run_ffprobe", lambda p: stream("hevc"))
        assert probe(f, store).verdict == Verdict.NO
        f.write_bytes(b"much longer content now")
        monkeypatch.setattr("ozzytv.probe._run_ffprobe", lambda p: stream("h264"))
        assert probe(f, store).verdict == Verdict.YES

    def test_an_unknown_verdict_is_not_cached(self, tmp_path, store, monkeypatch):
        """ffprobe may have been missing, or busy. Do not remember a shrug."""
        f = tmp_path / "a.mkv"
        f.write_bytes(b"x")
        monkeypatch.setattr("ozzytv.probe.shutil.which", lambda _: "/usr/bin/ffprobe")
        monkeypatch.setattr("ozzytv.probe._run_ffprobe", lambda p: None)
        probe(f, store)
        assert store.get_playability(f) is None
