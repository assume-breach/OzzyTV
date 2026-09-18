"""Render Ozzy TV's screens to PNG, without a Raspberry Pi or a television.

    python3 tools/mockup.py [--out docs/mockups] [--size 1280x720]

This draws the SAME Scene that tkview.py paints on the telly, so these are not
impressions of the design — they are the screen. If a tile is in the wrong place
here it is in the wrong place on the Pi.

Everything is drawn at twice the size and scaled down at the end: PIL does not
antialias, and a room-scale UI made of circles looks like a jigsaw without it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont            # noqa: E402

from ozzytv import scene as S                          # noqa: E402
from ozzytv import skin                                # noqa: E402

SS = 2                                                  # supersampling factor

FONT_FILES = {
    "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}
# Font role -> (file, size as a fraction of the screen height)
FONTS = {
    S.LOGO:  ("bold", 0.058),
    S.H1:    ("bold", 0.044),
    S.H2:    ("bold", 0.029),
    S.TILE:  ("bold", 0.025),
    S.BODY:  ("regular", 0.024),
    S.SMALL: ("regular", 0.019),
    S.GLYPH: ("bold", 0.040),
}
ANCHORS = {"nw": "la", "n": "ma", "ne": "ra", "w": "lm", "center": "mm",
           "e": "rm", "sw": "ld", "s": "md", "se": "rd"}


def _font(role: str, h: int, size: float = 0):
    name, frac = FONTS.get(role, FONTS[S.BODY])
    px = size * SS if size else h * frac
    return ImageFont.truetype(FONT_FILES[name], max(8, int(px)))


def _wrap(draw, text: str, font, width: float, max_lines: int) -> str:
    if not width:
        return text
    lines, words = [], text.split()
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return "\n".join(lines)


def render(sc: S.Scene) -> Image.Image:
    w, h = sc.w * SS, sc.h * SS
    img = Image.new("RGB", (w, h), sc.bg)
    d = ImageDraw.Draw(img)
    for item in sc.items:
        if isinstance(item, S.Gradient):
            _gradient(d, item)
        elif isinstance(item, S.RoundRect):
            d.rounded_rectangle(
                [item.x * SS, item.y * SS, (item.x + item.w) * SS, (item.y + item.h) * SS],
                radius=max(0, item.r * SS), fill=item.fill, outline=item.outline,
                width=max(1, int(item.width * SS)) if item.width else 0)
        elif isinstance(item, S.Oval):
            d.ellipse([(item.cx - item.rx) * SS, (item.cy - item.ry) * SS,
                       (item.cx + item.rx) * SS, (item.cy + item.ry) * SS],
                      fill=item.fill, outline=item.outline,
                      width=max(1, int(item.width * SS)) if item.width else 1)
        elif isinstance(item, S.Poly):
            pts = [(x * SS, y * SS) for x, y in item.points]
            if len(pts) == 2 or (item.outline and not item.fill):
                d.line(pts, fill=item.outline or item.fill,
                       width=max(1, int((item.width or 1) * SS)), joint="curve")
            else:
                d.polygon(pts, fill=item.fill, outline=item.outline)
        elif isinstance(item, S.Text):
            f = _font(item.font, h, item.size)
            text = _wrap(d, item.text, f, item.wrap * SS, item.max_lines)
            d.multiline_text((item.x * SS, item.y * SS), text, font=f, fill=item.fill,
                             anchor=ANCHORS.get(item.anchor, "la"),
                             align="center" if item.anchor in ("n", "center", "s") else "left",
                             spacing=int(h * 0.006))
    return img.resize((sc.w, sc.h), Image.LANCZOS)


def _gradient(d, g: S.Gradient) -> None:
    top = tuple(int(g.top[i:i + 2], 16) for i in (1, 3, 5))
    bot = tuple(int(g.bottom[i:i + 2], 16) for i in (1, 3, 5))
    for i in range(g.bands):
        t = i / max(1, g.bands - 1)
        c = tuple(int(top[j] + (bot[j] - top[j]) * t) for j in range(3))
        y0 = (g.y + g.h * i / g.bands) * SS
        y1 = (g.y + g.h * (i + 1) / g.bands) * SS + 1
        d.rectangle([g.x * SS, y0, (g.x + g.w) * SS, y1], fill=c)


# ---------------------------------------------------------------- the demos
def demo_views():
    """Realistic screens, built from the app's own View objects."""
    from ozzytv.app import ParentRow, RailItem, Tile, View

    rail = [RailItem("Watch again", "\x00recent", -1, 4, True),
            RailItem("Bluey", "Bluey", 0, 52),
            RailItem("PAW Patrol", "PAW Patrol", 0, 26),
            RailItem("Hey Duggee", "Hey Duggee", 0, 18),
            RailItem("Films", "Films", 0, 6),
            RailItem("Nursery Rhymes", "Nursery Rhymes", 0, 31)]
    tiles = [Tile("The Magic Xylophone · S1 E1", "video", "a", 0, "resume"),
             Tile("Hospital · S1 E2", "video", "b", 0),
             Tile("Shadowlands · S1 E10", "video", "c", 0),
             Tile("Sleepytime · S2 E14", "video", "d", 0),
             Tile("Series 3", "folder", "e", 0),
             Tile("Bin Night · S3 E1", "video", "f", 0, "may not play")]

    yield "01-home", View(screen="browse", heading="Bluey", subheading="Ozzy TV",
                          tiles=tiles, cursor=0, rail=rail, rail_cursor=1, focus="rail")
    yield "02-choosing", View(screen="browse", heading="Bluey", subheading="Ozzy TV",
                              tiles=tiles, cursor=3, rail=rail, rail_cursor=1, focus="grid")
    yield "03-paused", View(screen="playing", now_title="Bluey · The Magic Xylophone",
                            position_ms=7 * 60_000 + 12_000, duration_ms=11 * 60_000,
                            paused=True, volume=80)
    yield "04-pin", View(screen="pin", heading="Grown-ups only", pin_digits=2,
                         pin_prompt="parent")
    yield "05-parent", View(screen="parent", heading="Choose what Ozzy can watch",
                            cursor=2, message="PIN saved.", rows=[
        ParentRow("Videos", ".", 0, 0, "folder", "", True, "", "whole folder — new files here show up too"),
        ParentRow("Bluey", "Bluey", 0, 1, "folder", "allow", True, "", "whole folder — new files here show up too"),
        ParentRow("Series 1", "Bluey/S1", 0, 2, "folder", "", True, "Bluey", "from “Bluey”"),
        ParentRow("The Magic Xylophone", "Bluey/S1/a", 0, 3, "video", "", True, "Bluey", "from “Bluey”"),
        ParentRow("Films", "Films", 0, 1, "folder", "block", False, "", "blocked by “Films”"),
        ParentRow("Alien", "Films/alien", 0, 2, "video", "", False, "Films", "blocked by “Films”"),
        ParentRow("Paddington", "Films/padd", 0, 2, "video", "allow", True, "", ""),
    ])
    # A fresh install. Built from the app's own helper, so this really is the
    # first screen somebody sees rather than a guess at it.
    from ozzytv.app import HOME_KEY, welcome_steps
    from ozzytv.config import Settings
    yield "06-nothing-yet", View(
        screen="browse", heading="Home", subheading="Ozzy TV",
        rail=[RailItem("Home", HOME_KEY, -1, 0, True)],
        rail_cursor=0, focus="grid", cursor=0,
        tiles=[Tile("DVD", "dvd", "\x00dvd:0", -1, "no disc"),
               Tile("Grown-ups", "parent", "\x00parent", -1)],
        welcome=welcome_steps(Settings(media_roots=["/media/ozzy"]), allowed=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/mockups")
    ap.add_argument("--size", default="1280x720")
    args = ap.parse_args()
    w, h = (int(v) for v in args.size.lower().split("x"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, view in demo_views():
        sc = skin.build(view, w, h, columns=3, rows=2)
        if view.screen == "playing":
            # Nothing draws the sky here — on the Pi the programme itself is
            # behind this strip. Stand something in for it so the mockup reads as
            # a paused picture rather than as a bug.
            sc.items.insert(0, S.Text(w / 2, h * 0.32, "( the programme is playing here )",
                                      font=S.BODY, fill="#39344f", anchor="center"))
        render(sc).save(out / f"{name}.png")
        print(f"  {out / name}.png")
    # a sheet of every creature, for choosing
    sheet = S.Scene(w=w, h=int(h * 0.62), bg=skin.SKY_TOP)
    skin.backdrop(sheet, w, int(h * 0.62))
    sheet.add(S.Text(w / 2, h * 0.055, "the Ozzy TV animals", font=S.H1,
                     fill=skin.INK, anchor="center"))
    for i, kind in enumerate(skin.CREATURES):
        col, row = i % 6, i // 6
        cx = w * (0.115 + col * 0.155)
        cy = h * (0.22 + row * 0.20)
        sheet.add(S.Circle(cx, cy, h * 0.072, fill="#ffffff"))
        skin.creature(sheet, kind, cx, cy, h * 0.058, skin.CREATURE_COLOURS[i % 10])
        sheet.add(S.Text(cx, cy + h * 0.105, kind, font=S.BODY, fill=skin.INK, anchor="center"))
    render(sheet).save(out / "00-animals.png")
    print(f"  {out}/00-animals.png")

    # The logo on its own, for the README and anywhere else it is wanted.
    lw, lh = int(h * 0.62), int(h * 0.22)
    mark = S.Scene(w=lw, h=lh, bg=skin.PANEL)
    skin.logo(mark, lh * 0.18, lh * 0.16, lh * 0.66)
    render(mark).save(out / "logo.png")
    print(f"  {out}/logo.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
