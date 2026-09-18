"""The television's own remote, over HDMI-CEC.

Only the translation is testable without a television in the room, so that is
what is tested — and it is the part that would silently do nothing if the output
format were misread.
"""
import pytest

from ozzytv.app import Action
from ozzytv.cec import translate


@pytest.mark.parametrize("line,expected", [
    ("TRAFFIC: [123] key pressed: up (1)", (Action.UP, "")),
    ("TRAFFIC: [123] key pressed: select (0)", (Action.SELECT, "")),
    ("key pressed: exit (13)", (Action.BACK, "")),
    ("key pressed: play (44)", (Action.PLAY_PAUSE, "")),
    ("key pressed: volume up (65)", (Action.VOLUME_UP, "")),
    ("key pressed: root menu (9)", (Action.PARENT, "")),
    ("key pressed: number3 (23)", (Action.DIGIT, "3")),
])
def test_a_press_becomes_an_action(line, expected):
    assert translate(line) == expected


@pytest.mark.parametrize("line", [
    "key released: up (1)",             # releases must not double every press
    "DEBUG: [1] << e0:8c",
    "",
    "key pressed: channel up (48)",     # real, but nothing here for it to do
])
def test_everything_else_is_ignored(line):
    assert translate(line) is None
