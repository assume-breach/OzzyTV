"""What a screen looks like, as data.

A Scene is a flat list of shapes and words with no Tk in sight. Two things draw
it: tkview.py on the television, and tools/mockup.py into a PNG.

That second renderer is the point. This UI runs on a Raspberry Pi wired to a
telly, so the person who asked for it cannot see it while it is being built, and
a picture drawn separately to show them would be a drawing of the intention
rather than of the thing. Both renderers consume the same Scene, so a mockup is
the actual screen — if the tile is in the wrong place in the PNG, it is in the
wrong place on the television.

It also means the layout is testable: "the focused tile is bigger than its
neighbors" is an assertion about a Scene, not about pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

# Font roles rather than sizes, so each renderer picks something real and the
# layout code never mentions a typeface.
LOGO, H1, H2, TILE, BODY, SMALL, GLYPH = "logo", "h1", "h2", "tile", "body", "small", "glyph"


@dataclass
class RoundRect:
    x: float
    y: float
    w: float
    h: float
    r: float = 16
    fill: str | None = None
    outline: str | None = None
    width: float = 0
    # What this rectangle IS, if it is something you can press: "rail:2",
    # "tile:5", "digit:7". Purely a label — both renderers ignore it — but it
    # means a pointer can be hit-tested against the same layout that was drawn,
    # rather than against a second copy of the geometry that would drift.
    hit: str | None = None


@dataclass
class Text:
    x: float
    y: float
    text: str
    font: str = BODY
    fill: str = "#ffffff"
    anchor: str = "nw"          # nw | n | ne | w | center | e | sw | s | se
    wrap: float = 0             # px width to wrap at; 0 = never
    max_lines: int = 0
    # Exact pixel size, overriding the role's default. For the few places that
    # need to put something NEXT to text and therefore need to know how wide it
    # will be — the logo's "TV" pill, mostly.
    size: float = 0


@dataclass
class Poly:
    points: list[tuple[float, float]]
    fill: str | None = None
    outline: str | None = None
    width: float = 0


@dataclass
class Oval:
    cx: float
    cy: float
    rx: float
    ry: float
    fill: str | None = None
    outline: str | None = None
    width: float = 0


def Circle(cx: float, cy: float, r: float, **kw) -> Oval:      # noqa: N802
    return Oval(cx, cy, r, r, **kw)


@dataclass
class Gradient:
    """A vertical wash. Tk has no gradients, so both renderers paint it as a
    stack of bands — one place to decide how many, rather than fifty rectangles
    cluttering the layout code."""
    x: float
    y: float
    w: float
    h: float
    top: str
    bottom: str
    bands: int = 48


# typing.Union, not `A | B`. This one is a real expression evaluated at import,
# not an annotation that `from __future__ import annotations` defers — and
# Raspberry Pi OS Bullseye ships Python 3.9, where `A | B` between classes raises
# TypeError. The whole app would have failed to start on it, with a message about
# unsupported operand types.
Item = Union[RoundRect, Text, Poly, Oval, Gradient]


@dataclass
class Scene:
    w: int
    h: int
    bg: str
    items: list[Item] = field(default_factory=list)

    def add(self, *items: Item) -> None:
        self.items.extend(items)

    def texts(self) -> list[str]:
        return [i.text for i in self.items if isinstance(i, Text)]

    def rects(self) -> list[RoundRect]:
        return [i for i in self.items if isinstance(i, RoundRect)]
