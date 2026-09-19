"""How Ozzy TV looks: a Roku-shaped menu painted for a two-year-old.

Two briefs that pull in different directions, and both are real. The person
holding the remote is a grown-up, so the SHAPE is Roku's — a list of places down
the left, what is in the highlighted place across the right, a big obvious
selection that never leaves you wondering where you are. What the toddler on the
sofa gets is the LOOK: a sky with clouds and hills, bright sweet colors, and an
animal on everything.

The animals are not decoration. A toddler cannot read "Bluey" or "Series 1", so
every shelf and every show is given a creature and a color, picked by
hashing its name — which means they are stable. The same show is the orange
cat today, tomorrow, and after the library is rescanned. That is something a
child who cannot read can actually use to point at what they want.

Everything here is drawn as vectors into a Scene rather than loaded from image
files: nothing to install, nothing to lose when an SD card is re-flashed, it
scales to whatever the television turns out to be, and tools/mockup.py can render
exactly what the Pi will draw.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .scene import (BODY, GLYPH, H1, H2, LOGO, SMALL, TILE, Circle, Gradient,
                    Oval, Poly, RoundRect, Scene, Text)

# ---------------------------------------------------------------- the palette
SKY_TOP = "#3a2a8c"          # deep blueberry, so white text carries at 3 metres
SKY_BOTTOM = "#5f5bd6"
HILL_FAR = "#4a8f6b"
HILL_NEAR = "#3c7a58"
CLOUD = "#8f8ae8"
SUN = "#ffd449"
SUN_GLOW = "#ffe9a3"
PANEL = "#241a5e"
PANEL_EDGE = "#5b4bd0"
INK = "#ffffff"
INK_DIM = "#c9c2ff"
PILL = "#33268a"
PILL_ON = "#ffd449"
PILL_ON_INK = "#2a1d6b"
# Line weights as fractions of screen height, not pixels. Every other measure in
# this file already scales; these were literals, so on a 4K panel they stayed two
# and three physical pixels — hairlines that shimmer and read as a soft, grainy
# picture next to shapes that grew with the screen.
HAIRLINE = 2 / 720
RULE = 3 / 720

TILE_BG = "#2d2276"
FOCUS = "#ffffff"
SHADOW = "#1b1350"

# Sweet-shop colors for the creatures. Bright, distinct at a glance, and all
# legible against the tile behind them.
CREATURE_COLOURS = [
    "#ff8a5c", "#ffd449", "#6fe3a0", "#66d9ff", "#ff9ecd",
    "#c39bff", "#ffb347", "#7ef0d6", "#ff7a7a", "#a6e34d",
]
CREATURES = ["cat", "dog", "bear", "rabbit", "owl", "frog", "fish", "duck",
             "panda", "lion", "pig", "monkey"]


def _digest(name: str) -> bytes:
    """Stable across runs, machines and Python versions — hash() is not: it is
    randomised per process, so the cat would be a different color every boot."""
    return hashlib.sha256(name.encode("utf-8")).digest()


@dataclass(frozen=True)
class Badge:
    creature: str
    color: str


def badge_for(name: str) -> Badge:
    """The creature and color this name prefers, from its hash alone.

    SEPARATE bytes for the two: deriving both from one 32-bit slice (`h % 12`
    and `h // 12 % 10`) made them correlate badly — five of the first six shelf
    names came out the same, which for a child navigating by animal is the same
    as having no animals.
    """
    d = _digest(name)
    return Badge(creature=CREATURES[int.from_bytes(d[0:4], "big") % len(CREATURES)],
                 color=CREATURE_COLOURS[int.from_bytes(d[4:8], "big") % len(CREATURE_COLOURS)])


def assign_badges(names: list[str]) -> dict[str, Badge]:
    """Badges for everything on one screen, guaranteed different from each other.

    A hash alone cannot do this. Twelve creatures and six tiles collide about
    three times in four — the first render of this screen put four pandas on it —
    and two identical pandas are worse than no animals, because the child has
    been taught the animal is what tells them apart.

    So each name still ASKS for its hashed creature and gets it whenever it is
    free; otherwise it takes the next one along. Deterministic for a given set,
    which is what matters: the same shelf looks the same every time it is drawn,
    every boot, on any machine. Adding a show can shuffle the animals on
    that one shelf, and that is the price of them being distinct at all.
    """
    out: dict[str, Badge] = {}
    used_creature: set[str] = set()
    used_color: set[str] = set()
    for name in names:
        want = badge_for(name)
        creature_i = CREATURES.index(want.creature)
        for step in range(len(CREATURES)):
            c = CREATURES[(creature_i + step) % len(CREATURES)]
            if c not in used_creature:
                break
        else:                       # more items than creatures: start reusing
            c = want.creature
        color_i = CREATURE_COLOURS.index(want.color)
        for step in range(len(CREATURE_COLOURS)):
            k = CREATURE_COLOURS[(color_i + step) % len(CREATURE_COLOURS)]
            if k not in used_color:
                break
        else:
            k = want.color
        if len(used_creature) >= len(CREATURES):
            used_creature.clear()
        if len(used_color) >= len(CREATURE_COLOURS):
            used_color.clear()
        used_creature.add(c)
        used_color.add(k)
        out[name] = Badge(creature=c, color=k)
    return out


# ------------------------------------------------------------- the creatures
def creature(sc: Scene, kind: str, cx: float, cy: float, s: float,
             color: str, ink: str = "#2a1d6b") -> None:
    """One animal, built from circles and triangles.

    Vectors rather than emoji: a Raspberry Pi does not reliably have a color
    emoji font, and a row of blank boxes is worse than no animals at all.
    """
    dark = ink
    if kind == "cat":
        sc.add(Poly([(cx - s * .62, cy - s * .35), (cx - s * .30, cy - s * .95), (cx - s * .12, cy - s * .45)], fill=color),
               Poly([(cx + s * .62, cy - s * .35), (cx + s * .30, cy - s * .95), (cx + s * .12, cy - s * .45)], fill=color),
               Circle(cx, cy, s * .72, fill=color))
        _face(sc, cx, cy, s, dark, whiskers=True)
    elif kind == "dog":
        sc.add(Oval(cx - s * .72, cy - s * .1, s * .26, s * .5, fill=_shade(color)),
               Oval(cx + s * .72, cy - s * .1, s * .26, s * .5, fill=_shade(color)),
               Circle(cx, cy, s * .72, fill=color),
               Oval(cx, cy + s * .3, s * .34, s * .26, fill="#ffffff"))
        _face(sc, cx, cy, s, dark, snout=True)
    elif kind == "bear":
        sc.add(Circle(cx - s * .6, cy - s * .58, s * .27, fill=color),
               Circle(cx + s * .6, cy - s * .58, s * .27, fill=color),
               Circle(cx, cy, s * .72, fill=color),
               Oval(cx, cy + s * .28, s * .32, s * .24, fill="#ffffff"))
        _face(sc, cx, cy, s, dark, snout=True)
    elif kind == "rabbit":
        sc.add(Oval(cx - s * .30, cy - s * .95, s * .17, s * .52, fill=color),
               Oval(cx + s * .30, cy - s * .95, s * .17, s * .52, fill=color),
               Oval(cx - s * .30, cy - s * .95, s * .08, s * .36, fill="#ffd8ef"),
               Oval(cx + s * .30, cy - s * .95, s * .08, s * .36, fill="#ffd8ef"),
               Circle(cx, cy, s * .70, fill=color))
        _face(sc, cx, cy, s, dark, whiskers=True)
    elif kind == "owl":
        sc.add(Oval(cx, cy, s * .70, s * .78, fill=color),
               Circle(cx - s * .30, cy - s * .12, s * .26, fill="#ffffff"),
               Circle(cx + s * .30, cy - s * .12, s * .26, fill="#ffffff"),
               Circle(cx - s * .30, cy - s * .12, s * .12, fill=dark),
               Circle(cx + s * .30, cy - s * .12, s * .12, fill=dark),
               Poly([(cx, cy + s * .04), (cx - s * .13, cy + s * .26), (cx + s * .13, cy + s * .26)], fill="#ff8a5c"))
    elif kind == "frog":
        # Body FIRST. Drawn after the eyes it covered them, and a frog whose eyes
        # are behind its head is a green blob with a line on it.
        sc.add(Oval(cx, cy + s * .10, s * .72, s * .56, fill=color),
               Circle(cx - s * .36, cy - s * .46, s * .27, fill=color),
               Circle(cx + s * .36, cy - s * .46, s * .27, fill=color),
               Circle(cx - s * .36, cy - s * .46, s * .17, fill="#ffffff"),
               Circle(cx + s * .36, cy - s * .46, s * .17, fill="#ffffff"),
               Circle(cx - s * .36, cy - s * .44, s * .09, fill=dark),
               Circle(cx + s * .36, cy - s * .44, s * .09, fill=dark),
               Poly([(cx - s * .30, cy + s * .24), (cx - s * .10, cy + s * .34),
                     (cx + s * .10, cy + s * .34), (cx + s * .30, cy + s * .24)],
                    outline=dark, width=max(2, s * .09)))
    elif kind == "fish":
        sc.add(Poly([(cx + s * .30, cy), (cx + s * .90, cy - s * .45), (cx + s * .90, cy + s * .45)], fill=_shade(color)),
               Oval(cx - s * .10, cy, s * .62, s * .48, fill=color),
               Circle(cx - s * .38, cy - s * .10, s * .11, fill="#ffffff"),
               Circle(cx - s * .38, cy - s * .10, s * .06, fill=dark))
    elif kind == "duck":
        # A smaller beak and a proper eye. The old one was a big triangle cut out
        # of a plain circle, which reads as Pac-Man rather than as a duck.
        sc.add(Poly([(cx - s * .10, cy - s * .62), (cx + s * .04, cy - s * .98),
                     (cx + s * .20, cy - s * .60)], fill=_shade(color)),
               Circle(cx, cy, s * .70, fill=color),
               Poly([(cx + s * .58, cy + s * .06), (cx + s * .96, cy + s * .17),
                     (cx + s * .58, cy + s * .28)], fill="#ff8a5c"),
               Circle(cx + s * .26, cy - s * .18, s * .15, fill="#ffffff"),
               Circle(cx + s * .28, cy - s * .18, s * .08, fill=dark))
    elif kind == "panda":
        sc.add(Circle(cx - s * .58, cy - s * .56, s * .25, fill=dark),
               Circle(cx + s * .58, cy - s * .56, s * .25, fill=dark),
               Circle(cx, cy, s * .72, fill="#ffffff"),
               Oval(cx - s * .30, cy - s * .08, s * .19, s * .23, fill=dark),
               Oval(cx + s * .30, cy - s * .08, s * .19, s * .23, fill=dark),
               Circle(cx - s * .30, cy - s * .08, s * .07, fill="#ffffff"),
               Circle(cx + s * .30, cy - s * .08, s * .07, fill="#ffffff"),
               Oval(cx, cy + s * .30, s * .14, s * .10, fill=dark))
    elif kind == "lion":
        # A fixed amber mane rather than a darker shade of the body: on a tile the
        # body is white, so a "shade of white" mane is gray on white and the whole
        # animal collapses into a gray flower.
        for i in range(12):
            import math
            a = i * math.pi / 6
            sc.add(Circle(cx + math.cos(a) * s * .80, cy + math.sin(a) * s * .80, s * .26,
                          fill="#ffb347"))
        sc.add(Circle(cx, cy, s * .66, fill=color))
        _face(sc, cx, cy, s, dark, snout=True)
    elif kind == "pig":
        sc.add(Poly([(cx - s * .66, cy - s * .40), (cx - s * .34, cy - s * .86), (cx - s * .18, cy - s * .44)], fill=color),
               Poly([(cx + s * .66, cy - s * .40), (cx + s * .34, cy - s * .86), (cx + s * .18, cy - s * .44)], fill=color),
               Circle(cx, cy, s * .72, fill=color),
               Oval(cx, cy + s * .26, s * .30, s * .22, fill=_shade(color)),
               Circle(cx - s * .11, cy + s * .26, s * .06, fill=dark),
               Circle(cx + s * .11, cy + s * .26, s * .06, fill=dark))
        _eyes(sc, cx, cy, s, dark)
    else:  # monkey
        sc.add(Circle(cx - s * .68, cy - s * .10, s * .24, fill=color),
               Circle(cx + s * .68, cy - s * .10, s * .24, fill=color),
               Circle(cx, cy, s * .72, fill=color),
               Oval(cx, cy + s * .18, s * .46, s * .36, fill="#ffe3c4"))
        _face(sc, cx, cy, s, dark, snout=False)


def _shade(color: str) -> str:
    """A slightly deeper version, for ears and tails."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * .78), int(g * .78), int(b * .78))


def _eyes(sc: Scene, cx: float, cy: float, s: float, dark: str) -> None:
    sc.add(Circle(cx - s * .24, cy - s * .12, s * .09, fill=dark),
           Circle(cx + s * .24, cy - s * .12, s * .09, fill=dark))


def _face(sc: Scene, cx: float, cy: float, s: float, dark: str,
          whiskers: bool = False, snout: bool = False) -> None:
    _eyes(sc, cx, cy, s, dark)
    nose_y = cy + (s * .22 if snout else s * .14)
    sc.add(Poly([(cx - s * .09, nose_y - s * .05), (cx + s * .09, nose_y - s * .05),
                 (cx, nose_y + s * .08)], fill=dark))
    if whiskers:
        for side in (-1, 1):
            for dy in (-s * .08, s * .06):
                sc.add(Poly([(cx + side * s * .18, nose_y + dy),
                             (cx + side * s * .62, nose_y + dy - s * .06)],
                            outline=dark, width=max(1.5, s * .05)))


# ------------------------------------------------------------------ the logo
def logo(sc: Scene, x: float, y: float, h: float) -> None:
    """The mark: a little television with cat ears, and the wordmark beside it.

    A television that is also an animal — which is what the whole box is meant to
    be. It is drawn rather than loaded so it is sharp at any size and there is no
    image file to go missing.
    """
    u = h / 64.0                      # one design unit
    bw, bh = 62 * u, 50 * u
    bx, by = x, y + 8 * u
    # ears
    sc.add(Poly([(bx + 9 * u, by + 4 * u), (bx + 16 * u, by - 15 * u), (bx + 27 * u, by + 4 * u)], fill="#ff8a5c"),
           Poly([(bx + 53 * u, by + 4 * u), (bx + 46 * u, by - 15 * u), (bx + 35 * u, by + 4 * u)], fill="#ff8a5c"),
           # body
           RoundRect(bx, by, bw, bh, r=14 * u, fill="#ff8a5c"),
           RoundRect(bx + 6 * u, by + 6 * u, bw - 12 * u, bh - 12 * u, r=9 * u, fill="#2a1d6b"),
           # screen glint
           Poly([(bx + 10 * u, by + 34 * u), (bx + 10 * u, by + 12 * u), (bx + 20 * u, by + 12 * u)],
                fill="#3a2a8c"),
           # play button
           Poly([(bx + 26 * u, by + 15 * u), (bx + 44 * u, by + 25 * u), (bx + 26 * u, by + 35 * u)],
                fill=SUN),
           # feet
           RoundRect(bx + 8 * u, by + bh - 2 * u, 12 * u, 7 * u, r=3 * u, fill="#e06a3e"),
           RoundRect(bx + 42 * u, by + bh - 2 * u, 12 * u, 7 * u, r=3 * u, fill="#e06a3e"))
    # Wordmark. The size is stated rather than taken from the font role, because
    # the "TV" pill has to sit just after the word and therefore has to know how
    # wide it is — sized by role, the pill landed on top of the last two letters.
    word_px = h * 0.46
    sc.add(Text(x + 74 * u, y + 21 * u, "ozzy", font=LOGO, size=word_px,
                fill=INK, anchor="w"))
    word_w = len("ozzy") * word_px * 0.60          # DejaVu Bold advance, near enough
    pill_x = x + 74 * u + word_w + 8 * u
    pill_w, pill_h = word_px * 1.15, word_px * 0.78
    sc.add(RoundRect(pill_x, y + 21 * u - pill_h / 2, pill_w, pill_h,
                     r=pill_h * 0.34, fill=SUN),
           Text(pill_x + pill_w / 2, y + 21 * u, "TV", font=H2, size=word_px * 0.52,
                fill=PILL_ON_INK, anchor="center"))


# ------------------------------------------------------------ the background
def backdrop(sc: Scene, w: int, h: int) -> None:
    """Sky, sun, clouds, hills, and somebody watching from the grass.

    Deep enough that white text carries across a room — a pale nursery blue looks
    lovely on a laptop and turns a dark living room into a lamp — but every hue in
    it is a bright one.
    """
    sc.add(Gradient(0, 0, w, h, SKY_TOP, SKY_BOTTOM))
    for i, (fx, fy, fr) in enumerate([(0.08, 0.10, 2.0), (0.19, 0.05, 1.4), (0.31, 0.14, 1.7),
                                      (0.62, 0.07, 1.5), (0.74, 0.16, 2.2), (0.88, 0.09, 1.3),
                                      (0.45, 0.04, 1.6), (0.97, 0.22, 1.8)]):
        sc.add(Circle(w * fx, h * fy, fr * h / 220, fill="#ffffff"))
    # Sun, tucked into the very top corner: further in it sat behind the top row
    # of tiles, which is where the eye needs to go.
    sun_x, sun_y, sun_r = w * 0.930, h * 0.105, h * 0.042
    sc.add(Circle(sun_x, sun_y, sun_r, fill=SUN))
    for i in range(12):
        import math
        a = i * math.pi / 6
        sc.add(Poly([(sun_x + math.cos(a) * sun_r * 1.30, sun_y + math.sin(a) * sun_r * 1.30),
                     (sun_x + math.cos(a) * sun_r * 1.62, sun_y + math.sin(a) * sun_r * 1.62)],
                    outline=SUN, width=max(2, h * 0.007)))
    _cloud(sc, w * 0.44, h * 0.075, h * 0.042)
    _cloud(sc, w * 0.72, h * 0.115, h * 0.030)
    _cloud(sc, w * 0.90, h * 0.30, h * 0.026)
    # hills
    sc.add(Oval(w * 0.18, h * 1.22, w * 0.55, h * 0.36, fill=HILL_FAR),
           Oval(w * 0.82, h * 1.24, w * 0.52, h * 0.32, fill=HILL_FAR),
           Oval(w * 0.50, h * 1.33, w * 0.80, h * 0.36, fill=HILL_NEAR))
    # Three friends in the grass along the bottom, below the tiles and clear of
    # the button hints on the left.
    creature(sc, "rabbit", w * 0.640, h * 0.952, h * 0.040, "#ff9ecd")
    creature(sc, "bear", w * 0.760, h * 0.958, h * 0.044, "#ffb347")
    creature(sc, "duck", w * 0.880, h * 0.955, h * 0.038, "#ffd449")


def _cloud(sc: Scene, cx: float, cy: float, r: float) -> None:
    for dx, dy, rr in ((-1.0, 0.15, 0.72), (0.0, -0.22, 1.0), (1.0, 0.12, 0.78), (0.15, 0.30, 0.70)):
        sc.add(Oval(cx + dx * r, cy + dy * r, rr * r * 1.25, rr * r, fill=CLOUD))


# --------------------------------------------------------------- the screens
def build(view, w: int, h: int, columns: int = 3, rows: int = 2) -> Scene:
    """One View, as something to draw. Pure — which is what lets the layout be
    tested ("the focused tile is bigger than its neighbors") and what lets
    tools/mockup.py render exactly what the television will show."""
    sc = Scene(w=w, h=h, bg=SKY_TOP)
    # No sky while something is playing: the picture IS the screen, and on the
    # television this scene is drawn into a strip across the bottom, so a
    # backdrop here would be a skyful of clouds squashed into that strip.
    if view.screen != "playing":
        backdrop(sc, w, h)
    else:
        sc.bg = "#000000"
    {
        "browse": _browse,
        "playing": _playing,
        "pin": _pin,
        "parent": _parent,
        "message": _message,
    }.get(view.screen, _message)(sc, view, w, h, columns, rows)
    return sc


def _hints(sc: Scene, w: int, h: int, pairs: list[tuple[str, str]]) -> None:
    """The bottom strip of buttons. Drawn as key caps, because "OK" in a sentence
    is not something a two-year-old can match to the thing in their hand."""
    x = w * 0.031
    y = h - h * 0.072
    # ...and they are BUTTONS, not a legend. With a mouse there was no way back
    # at all: the bar said "Back  out" and nothing happened when you pressed it,
    # which is worse than not drawing it.
    presses = {"OK": "key:select", "Back": "key:back", "P": "key:parent",
               "+ -": "", "0-9": ""}
    for cap, what in pairs:
        cw = max(h * 0.052, h * 0.021 * len(cap) + h * 0.033)
        sc.add(RoundRect(x, y, cw, h * 0.048, r=h * 0.014, fill=PILL,
                         outline=PANEL_EDGE, width=HAIRLINE * h,
                         hit=presses.get(cap) or None),
               Text(x + cw / 2, y + h * 0.024, cap, font=SMALL, fill=INK, anchor="center"))
        sc.add(Text(x + cw + h * 0.014, y + h * 0.024, what, font=SMALL, fill=INK_DIM, anchor="w"))
        x += cw + h * 0.021 + h * 0.011 * len(what) + h * 0.028


def _browse(sc: Scene, v, w: int, h: int, columns: int, rows: int) -> None:
    rail_w = w * 0.30
    # ---- the rail
    sc.add(RoundRect(-h * 0.04, -h * 0.04, rail_w + h * 0.04, h + h * 0.08,
                     r=h * 0.05, fill=PANEL))
    logo(sc, w * 0.035, h * 0.045, h * 0.085)

    rail_badges = assign_badges([i.title for i in v.rail])
    top = h * 0.215
    row_h = h * 0.105
    gap = h * 0.018
    fits = max(1, int((h * 0.70) // (row_h + gap)))
    first = max(0, min(v.rail_cursor - fits // 2, len(v.rail) - fits))
    for i, item in enumerate(v.rail[first:first + fits]):
        idx = first + i
        y = top + i * (row_h + gap)
        on = idx == v.rail_cursor
        b = rail_badges[item.title]
        sc.add(RoundRect(w * 0.022, y, rail_w - w * 0.044, row_h, r=row_h / 2,
                         hit=f"rail:{idx}",
                         fill=PILL_ON if on else PILL,
                         outline=FOCUS if on and v.focus == "rail" else None,
                         width=h * 0.006 if on and v.focus == "rail" else 0))
        cx = w * 0.022 + row_h * 0.52
        sc.add(Circle(cx, y + row_h / 2, row_h * 0.36, fill="#ffffff"))
        creature(sc, b.creature, cx, y + row_h / 2, row_h * 0.30, b.color)
        sc.add(Text(cx + row_h * 0.52, y + row_h / 2, item.title, font=H2,
                    fill=PILL_ON_INK if on else INK, anchor="w",
                    wrap=rail_w - row_h - w * 0.09, max_lines=2))
        if item.count:
            sc.add(Text(rail_w - w * 0.052, y + row_h / 2, str(item.count), font=SMALL,
                        fill=PILL_ON_INK if on else INK_DIM, anchor="e"))

    # ---- the tiles
    mx = rail_w + w * 0.030
    mw = w - mx - w * 0.030
    sc.add(Text(mx, h * 0.072, v.heading, font=H1, fill=INK, anchor="w"))
    if v.welcome:
        # The home screen with an empty library. It is a home SCREEN, not a page
        # of instructions — so what to do next takes the subheading's line
        # rather than a row of its own, which had nowhere to go but into the
        # tiles.
        sc.add(Text(mx, h * 0.125, v.welcome[0][1], font=SMALL, fill=SUN,
                    anchor="w", wrap=mw, max_lines=1))
    elif v.subheading:
        sc.add(Text(mx, h * 0.125, v.subheading, font=SMALL, fill=INK_DIM, anchor="w"))

    if not v.tiles and v.welcome:
        _welcome(sc, v, mx, mw, w, h)
        _hints(sc, w, h, [("OK", "Open"), ("P", "Settings")])
        return

    if not v.tiles:
        sc.add(Text(mx + mw / 2, h * 0.45, "Nothing on this shelf yet", font=H2,
                    fill=INK_DIM, anchor="center"))
        _hints(sc, w, h, [("OK", "Open"), ("Back", "Go back")])
        return

    # A LIST, not a grid of tiles. Big artwork is the right shape for six
    # things a child recognizes by their pictures; it is the wrong shape for a
    # folder with forty episodes in it, where the only thing that tells them
    # apart is the words. A list fits twice as many, sorts the way a season
    # does, and reads down rather than snaking.
    badges = assign_badges([t.title for t in v.tiles])
    row_h = h * 0.088
    gap = h * 0.014
    top = h * 0.185
    per_page = max(1, int((h * 0.70) // (row_h + gap)))
    page = v.cursor // per_page
    for i, tile in enumerate(v.tiles[page * per_page:(page + 1) * per_page]):
        idx = page * per_page + i
        y = top + i * (row_h + gap)
        on = idx == v.cursor and v.focus == "grid"
        if on:
            sc.add(RoundRect(mx - h * 0.008, y - h * 0.008, mw + h * 0.016,
                             row_h + h * 0.016, r=h * 0.026, fill=SUN))
        sc.add(RoundRect(mx, y, mw, row_h, r=h * 0.020, fill=TILE_BG,
                         hit=f"tile:{idx}",
                         outline=FOCUS if on else PANEL_EDGE,
                         width=h * 0.004 if on else HAIRLINE * h))
        b = badges[tile.title]
        # A small round creature on the left, so a list still looks like this
        # television and not like a file manager.
        disc_r = row_h * 0.34
        cx = mx + row_h * 0.52
        sc.add(Circle(cx, y + row_h / 2, disc_r, fill=b.color))
        creature(sc, b.creature, cx, y + row_h / 2, disc_r * 0.78, "#ffffff", "#2a1d6b")
        if tile.kind == "folder":
            sc.add(Text(mx + row_h * 1.02, y + row_h / 2, "▸", font=H2, fill=SUN,
                        anchor="w"))
        tx = mx + row_h * (1.28 if tile.kind == "folder" else 1.02)
        badge_w = mw * 0.22 if tile.badge else 0
        sc.add(Text(tx, y + row_h / 2, tile.title, font=TILE, fill=INK, anchor="w",
                    wrap=mw - (tx - mx) - badge_w - mw * 0.03, max_lines=1))
        if tile.badge:
            bw = mw * 0.19
            sc.add(RoundRect(mx + mw - bw - mw * 0.02, y + row_h / 2 - h * 0.021,
                             bw, h * 0.042, r=h * 0.014, fill=SHADOW),
                   Text(mx + mw - bw / 2 - mw * 0.02, y + row_h / 2, tile.badge,
                        font=SMALL, fill=SUN, anchor="center"))

    pages = max(1, (len(v.tiles) + per_page - 1) // per_page)
    if pages > 1:
        for p in range(pages):
            cxp = mx + mw / 2 + (p - (pages - 1) / 2) * h * 0.030
            sc.add(Circle(cxp, h * 0.905, h * 0.0075,
                          fill=SUN if p == page else PANEL_EDGE))
    _hints(sc, w, h, [("OK", "Play"), ("Back", "Go back"), ("P", "Settings")])


def _playing(sc: Scene, v, w: int, h: int, columns: int, rows: int) -> None:
    """Only ever drawn paused — while something is playing the picture is the
    screen, and a progress bar across it is something to look at instead."""
    # The strip is deep enough to hold the title, the bar AND the buttons without
    # them landing on each other — at 0.22 of the screen the progress bar ran
    # straight through the "OK / Back" caps.
    bar_h = h * 0.30
    y = h - bar_h
    sc.add(RoundRect(-h * 0.04, y, w + h * 0.08, bar_h + h * 0.08, r=h * 0.05, fill=PANEL))
    b = badge_for(v.now_title)
    sc.add(Circle(w * 0.055, y + bar_h * 0.26, bar_h * 0.17, fill="#ffffff"))
    creature(sc, b.creature, w * 0.055, y + bar_h * 0.26, bar_h * 0.14, b.color)
    sc.add(Text(w * 0.105, y + bar_h * 0.24, v.now_title, font=H1, fill=INK, anchor="w"),
           Text(w - w * 0.035, y + bar_h * 0.24,
                f"{_clock(v.position_ms)} / {_clock(v.duration_ms)}",
                font=BODY, fill=INK_DIM, anchor="e"))
    frac = (v.position_ms / v.duration_ms) if v.duration_ms else 0
    bx, bw2, by = w * 0.035, w * 0.93, y + bar_h * 0.50
    sc.add(RoundRect(bx, by, bw2, h * 0.020, r=h * 0.010, fill=PILL),
           RoundRect(bx, by, max(h * 0.020, bw2 * frac), h * 0.020, r=h * 0.010, fill=SUN),
           Circle(bx + bw2 * frac, by + h * 0.010, h * 0.019, fill=FOCUS))
    sc.add(Text(w / 2, y + bar_h * 0.68, "Paused", font=BODY, fill=INK_DIM, anchor="center"))
    _hints(sc, w, h, [("OK", "Resume"), ("Back", "Stop"), ("+ -", "Volume")])


def _welcome(sc: Scene, v, mx: float, mw: float, w: int, h: int) -> None:
    """The first-boot screen: what to do next, in order, on the television.

    Numbered cards rather than a paragraph, because this is read from across a
    room by somebody holding a memory stick, and because a list of three things
    with one of them done is a different feeling from a wall of text.
    """
    card_h = h * 0.155
    gap = h * 0.030
    top = h * 0.185
    for i, (title, body) in enumerate(v.welcome[:3]):
        y = top + i * (card_h + gap)
        # Clickable. This is the ONE screen where a grown-up is certain to be
        # the one standing there, most likely with a mouse, and until now it was
        # the one screen with nothing on it a pointer could press.
        sc.add(RoundRect(mx, y, mw, card_h, r=h * 0.028, fill=TILE_BG,
                         outline=PANEL_EDGE, width=HAIRLINE * h, hit="grownups"))
        # A numbered disc, in the same sunny yellow as the focus ring, so the
        # order reads before any of the words do.
        cx, cy, rr = mx + card_h * 0.42, y + card_h / 2, card_h * 0.24
        sc.add(Circle(cx, cy, rr, fill=SUN))
        sc.add(Text(cx, cy, str(i + 1), font=H2, fill="#2a1d6b", anchor="center"))
        tx = mx + card_h * 0.82
        sc.add(Text(tx, y + card_h * 0.34, title, font=TILE, fill=INK, anchor="w",
                    wrap=mw - card_h - w * 0.02, max_lines=1))
        sc.add(Text(tx, y + card_h * 0.66, body, font=SMALL, fill=INK_DIM, anchor="w",
                    wrap=mw - card_h - w * 0.02, max_lines=2))


def _pin(sc: Scene, v, w: int, h: int, columns: int, rows: int) -> None:
    cw, ch = w * 0.44, h * 0.46
    x, y = (w - cw) / 2, (h - ch) / 2
    sc.add(RoundRect(x + h * 0.010, y + h * 0.014, cw, ch, r=h * 0.045, fill=SHADOW),
           RoundRect(x, y, cw, ch, r=h * 0.045, fill=PANEL, outline=PANEL_EDGE, width=RULE * h))
    creature(sc, "owl", x + cw / 2, y + ch * 0.22, h * 0.055, "#c39bff")
    sc.add(Text(x + cw / 2, y + ch * 0.44, v.heading, font=H1, fill=INK, anchor="center"))
    n = max(v.pin_digits, 0)
    for i in range(max(4, n)):
        dx = x + cw / 2 + (i - (max(4, n) - 1) / 2) * h * 0.055
        sc.add(Circle(dx, y + ch * 0.62, h * 0.018,
                      fill=SUN if i < n else PANEL, outline=PANEL_EDGE, width=HAIRLINE * h))
    msg = (f"Too many tries — wait {v.lock_seconds} seconds" if v.lock_seconds
           else v.pin_error or "Type the PIN, then press OK")
    sc.add(Text(x + cw / 2, y + ch * 0.82, msg, font=BODY,
                fill="#ff9ecd" if (v.pin_error or v.lock_seconds) else INK_DIM,
                anchor="center", wrap=cw * 0.86, max_lines=2))
    _hints(sc, w, h, [("0-9", "type"), ("OK", "enter"), ("Back", "cancel")])


def _parent(sc: Scene, v, w: int, h: int, columns: int, rows: int) -> None:
    sc.add(RoundRect(w * 0.020, h * 0.030, w - w * 0.040, h - h * 0.150,
                     r=h * 0.035, fill=PANEL, outline=PANEL_EDGE, width=RULE * h))
    sc.add(Text(w * 0.045, h * 0.082, v.heading, font=H1, fill=INK, anchor="w"))
    if v.message:
        sc.add(Text(w * 0.045, h * 0.135, v.message, font=SMALL, fill=SUN, anchor="w"))
    top, row_h = h * 0.185, h * 0.058
    fits = max(1, int((h * 0.63) // row_h))
    first = max(0, min(v.cursor - fits // 2, len(v.rows) - fits))
    for i, row in enumerate(v.rows[first:first + fits]):
        idx = first + i
        y = top + i * row_h
        # An invisible rectangle over the whole row, purely so a pointer has
        # something to land on. No fill and no outline, so both renderers draw
        # nothing — it exists to be hit-tested.
        sc.add(RoundRect(w * 0.035, y - h * 0.008, w - w * 0.070, row_h - h * 0.006,
                         r=0, fill=None, outline=None, hit=f"row:{idx}"))
        if idx == v.cursor:
            sc.add(RoundRect(w * 0.035, y - h * 0.008, w - w * 0.070, row_h - h * 0.006,
                             r=h * 0.014, fill=PILL, outline=SUN, width=HAIRLINE * h))
        state = {"allow": "✔ allowed", "block": "✖ blocked"}.get(
            row.mark, "· " + ("shown" if row.effective else "hidden"))
        sc.add(Text(w * 0.055 + row.depth * w * 0.018, y + row_h * 0.30,
                    ("▸ " if row.kind == "folder" else "• ") + row.title, font=BODY,
                    fill=INK if row.effective else INK_DIM, anchor="w",
                    wrap=w * 0.46, max_lines=1),
               Text(w * 0.605, y + row_h * 0.30, state, font=SMALL,
                    fill="#6fe3a0" if row.effective else "#ff9ecd", anchor="w"),
               Text(w - w * 0.055, y + row_h * 0.30, row.note, font=SMALL,
                    fill=INK_DIM, anchor="e", wrap=w * 0.26, max_lines=1))
    _hints(sc, w, h, [("OK", "Show / hide"), ("Back", "Done")])


def _message(sc: Scene, v, w: int, h: int, columns: int, rows: int) -> None:
    cw, ch = w * 0.62, h * 0.48
    x, y = (w - cw) / 2, (h - ch) / 2
    sc.add(RoundRect(x + h * 0.010, y + h * 0.014, cw, ch, r=h * 0.045, fill=SHADOW),
           RoundRect(x, y, cw, ch, r=h * 0.045, fill=PANEL, outline=PANEL_EDGE, width=RULE * h))
    creature(sc, "cat", x + cw * 0.30, y + ch * 0.30, h * 0.070, "#ff8a5c")
    creature(sc, "dog", x + cw * 0.70, y + ch * 0.31, h * 0.062, "#ffd449")
    sc.add(Text(x + cw / 2, y + ch * 0.68, v.message, font=H2, fill=INK,
                anchor="center", wrap=cw * 0.82, max_lines=5))
    _hints(sc, w, h, [("P", "Settings")])


def _clock(ms: int) -> str:
    s = max(0, ms // 1000)
    return (f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600
            else f"{s // 60}:{s % 60:02d}")
