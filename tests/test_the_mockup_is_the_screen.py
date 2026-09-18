"""The mockups are not impressions of the design — they ARE the screen.

skin.build() produces a Scene: pure data, coordinates and colors, no drawing.
tkview.py paints that Scene on the television and tools/mockup.py paints the
same Scene to a PNG. So a mockup is a picture of the actual layout, and a tile
in the wrong place in one is in the wrong place in the other.

That only holds while both renderers handle everything the skin can emit. A
renderer that quietly ignores an item type does not fail — it draws a screen
with something missing, and the two stop being the same picture. These tests
are what makes "exactly as the mockup" a property rather than an intention.
"""
import sys
from pathlib import Path

import pytest

from ozzytv import scene as S
from ozzytv import skin
from ozzytv.app import Action, ParentRow, RailItem, Tile, View

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

ITEM_TYPES = (S.RoundRect, S.Text, S.Poly, S.Oval, S.Gradient)


def import_tkview():
    """tkview needs tkinter, which this container has not got. selftest already
    carries a stand-in Tk for exactly this, so borrow it rather than skipping:
    the font table is not a thing that should go unchecked off the Pi."""
    import types

    from ozzytv import selftest
    tk, font = selftest._fake_tkinter()
    saved = {k: sys.modules.get(k)
             for k in ("tkinter", "tkinter.font", "ozzytv.tkview")}
    sys.modules["tkinter"], sys.modules["tkinter.font"] = tk, font
    sys.modules.pop("ozzytv.tkview", None)
    try:
        from ozzytv import tkview
        return tkview
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def every_screen(app):
    """A Scene for each screen, built the way the television builds it."""
    scenes = {}
    for name, keys in (("menu", []),
                       ("folder", [Action.SELECT, Action.SELECT]),
                       ("keypad", [Action.PARENT]),
                       ("paused", [Action.SELECT] * 5)):
        for k in keys:
            app.handle(k)
        scenes[name] = skin.build(app.view(), 1280, 720, columns=3, rows=2)
        while app.screen.value != "browse":
            app.handle(Action.BACK)
        app.handle(Action.BACK)
    return scenes


class TestBothRenderersHandleEverythingTheSkinEmits:
    def test_the_skin_emits_nothing_neither_renderer_knows(self, allow_everything):
        """The failure this guards is silent: an unknown item is skipped by an
        if/elif chain, and the screen is merely missing something."""
        seen = set()
        for sc in every_screen(allow_everything).values():
            seen |= {type(i) for i in sc.items}
        assert seen, "no screen produced any items at all"
        assert seen <= set(ITEM_TYPES), f"unknown item type(s): {seen - set(ITEM_TYPES)}"

    def test_the_mockup_draws_every_item_type(self):
        """PIL is here, so this one runs for real rather than by inspection."""
        pytest.importorskip("PIL")
        import mockup
        src = Path(mockup.__file__).read_text()
        for t in ITEM_TYPES:
            assert f"isinstance(item, S.{t.__name__})" in src, \
                f"tools/mockup.py cannot draw {t.__name__}"

    def test_the_television_draws_every_item_type(self):
        src = (Path(__file__).resolve().parents[1] / "ozzytv" / "tkview.py").read_text()
        assert "_draw" in src
        for t in ITEM_TYPES:
            assert f"isinstance(item, S.{t.__name__})" in src, \
                f"tkview.py cannot draw {t.__name__}"


class TestTheyAgreeOnWhatIsOnTheScreen:
    def test_the_same_scene_reaches_both(self, allow_everything):
        """Neither renderer is allowed to build its own layout. Both are handed
        a Scene — so this asserts the Scene is complete enough to be one."""
        sc = skin.build(allow_everything.view(), 1280, 720, columns=3, rows=2)
        assert sc.w == 1280 and sc.h == 720
        assert sc.bg.startswith("#")
        assert len(sc.items) > 10, "a whole screen should be more than a few shapes"
        for item in sc.items:
            assert isinstance(item, ITEM_TYPES)

    def test_the_font_tables_have_not_drifted(self):
        """Both renderers size text as a fraction of screen height, from their
        own copy of the table. If the two drift, the mockup stops being a
        picture of the television — subtly, which is the worst way."""
        pytest.importorskip("PIL")
        import mockup

        tkview = import_tkview()
        assert set(mockup.FONTS) == set(tkview.FONTS)
        for role in mockup.FONTS:
            _, mock_frac = mockup.FONTS[role]
            _, weight, tk_frac = tkview.FONTS[role]
            assert mock_frac == tk_frac, f"{role}: mockup {mock_frac} vs telly {tk_frac}"
            assert (weight == "bold") == (mockup.FONTS[role][0] == "bold"), \
                f"{role}: one renderer draws it bold and the other does not"

    def test_a_mockup_actually_renders_at_the_size_a_television_uses(self, allow_everything):
        pytest.importorskip("PIL")
        import mockup
        sc = skin.build(allow_everything.view(), 1280, 720, columns=3, rows=2)
        img = mockup.render(sc)
        assert img.size == (1280, 720)
        assert len(img.getcolors(maxcolors=1 << 20) or []) > 50, \
            "that is not a screen, that is a flat rectangle"
