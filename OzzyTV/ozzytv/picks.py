"""What the child is allowed to see.

This is the one module in Ozzy TV where a bug shows a child something a parent
did not approve, so it is deliberately small, pure, and has no I/O: it decides
over two sets of rules that store.py loads and saves. Everything here is a
function of its arguments, which is what makes the adversarial tests possible.

THE MODEL
    A parent marks a file or a folder ALLOWED or BLOCKED. A folder's mark covers
    everything beneath it, and the NEAREST mark wins — so "allow Bluey, block
    Bluey/S02E14" means exactly what it reads like.

    Anything with no mark above it at all is HIDDEN. Not "hidden until we get
    round to it" — hidden, by design. A new folder appearing on a USB stick, a
    file dropped in by someone else, a rule that was deleted: all of them land on
    "no" without anyone having to think about it. The cost is that a parent has
    to say yes once per shelf; the alternative is a default that fails towards
    showing a four-year-old whatever turned up.

    Allowing a FOLDER is a standing yes: things added to it later are visible
    too. That is usually what a parent means ("she can watch anything in here"),
    and the parent screen says so on the row rather than leaving it to be
    discovered.

CONFINEMENT
    Rules are keyed by the path RELATIVE TO ITS ROOT, and a path only gets a
    decision once it has been resolved and found to still be inside that root.
    A symlink in an allowed folder pointing at /etc resolves out of the root and
    is refused — being reachable through an allowed folder is not the same as
    being in one.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

# The root itself, as a rule key. Allowing this is "everything on this drive",
# which blocks below it then carve into.
ROOT_KEY = "."


class Mark(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True)
class Decision:
    visible: bool
    # Which rule decided, as a relative path ('.' = the whole root), or None when
    # nothing did. The parent screen shows this: "hidden — nothing here is
    # allowed yet" reads very differently from "hidden — you blocked Scary Films".
    by: str | None
    # True when the deciding rule was on an ANCESTOR rather than this item, i.e.
    # the item inherits. The parent screen greys inherited rows so it is obvious
    # which one to change.
    inherited: bool = False
    # Set when the path could not be placed inside its root at all.
    escaped: bool = False


@dataclass(frozen=True)
class Rules:
    """Every mark for one root, as {relative path: Mark}."""
    marks: dict[str, Mark]

    @staticmethod
    def empty() -> "Rules":
        return Rules(marks={})

    def with_mark(self, rel: str, mark: Mark | None) -> "Rules":
        m = dict(self.marks)
        if mark is None:
            m.pop(rel, None)
        else:
            m[rel] = mark
        return Rules(marks=m)


def relkey(root: Path, path: Path) -> str | None:
    """`path` as a rule key under `root`, or None if it is not really in there.

    BOTH sides are resolved first. That is the whole confinement check: a
    symlink, a `..`, a bind mount or a hard-won relative path all collapse to
    where they actually point, and anything that lands outside the root comes
    back None — which every caller treats as "not visible".
    """
    try:
        r = root.resolve(strict=False)
        p = path.resolve(strict=False)
    except (OSError, RuntimeError):     # broken link loop, permission, ELOOP
        return None
    try:
        rel = p.relative_to(r)
    except ValueError:
        return None
    s = PurePosixPath(rel).as_posix()
    return ROOT_KEY if s in ("", ".") else s


def _chain(rel: str) -> list[str]:
    """`rel` and every folder above it, NEAREST FIRST, ending at the root."""
    if rel == ROOT_KEY:
        return [ROOT_KEY]
    p = PurePosixPath(rel)
    out = [p.as_posix()]
    for parent in p.parents:
        out.append(ROOT_KEY if parent.as_posix() == "." else parent.as_posix())
    return out


def decide(rules: Rules, root: Path, path: Path) -> Decision:
    """Whether the child may see `path`. Fails closed on every unclear case."""
    rel = relkey(root, path)
    if rel is None:
        return Decision(visible=False, by=None, escaped=True)
    return decide_rel(rules, rel)


def decide_rel(rules: Rules, rel: str) -> Decision:
    """The same decision, for a key that is already known to be inside the root.
    Split out so the scanner can decide a whole tree without re-resolving every
    path it just walked."""
    for i, key in enumerate(_chain(rel)):
        mark = rules.marks.get(key)
        if mark is Mark.BLOCK:
            return Decision(visible=False, by=key, inherited=i > 0)
        if mark is Mark.ALLOW:
            return Decision(visible=True, by=key, inherited=i > 0)
    return Decision(visible=False, by=None)


def is_visible(rules: Rules, root: Path, path: Path) -> bool:
    return decide(rules, root, path).visible


def folder_has_anything_visible(rules: Rules, rel: str, descendants: list[str]) -> bool:
    """Whether a folder is worth showing the child at all.

    A shelf you can open to find nothing is worse than no shelf: the child does
    not know whether they did something wrong. A folder is shown only if at least
    one thing under it resolves to visible — which is not the same as the folder
    being allowed, because a block underneath can empty it out.
    """
    return any(decide_rel(rules, d).visible for d in descendants)
