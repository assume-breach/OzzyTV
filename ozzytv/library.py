"""Reading the media roots into something a child can look at.

Two jobs beyond walking directories. First, names: a shelf that reads
`Bluey.S01E01.1080p.WEB-DL.x264-GRP.mkv` is no use to someone who cannot read
well yet, so filenames are cleaned into titles. Second, order: plain sorting puts
Episode 10 before Episode 2, which is maddening for anyone and impossible for a
child to reason about — so sorting is natural.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .config import AUDIO_EXTS, IGNORED_LOWER, VIDEO_EXTS

# How deep to walk before deciding something is wrong with the drive rather than
# with us. Nobody files their children's television 40 folders down.
MAX_DEPTH = 40


class Kind(str, Enum):
    FOLDER = "folder"
    VIDEO = "video"
    AUDIO = "audio"


def episode_of(name: str) -> tuple[int, int] | None:
    """(season, episode) from a filename, or None."""
    m = _EPISODE.search(name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def sort_key(title: str, source_name: str) -> tuple:
    """How things line up on a shelf.

    Episodes go in EPISODE order. Sorting them by their cleaned title looks right
    until a series names its episodes — then 'Hospital', 'Shadowlands', 'The
    Magic Xylophone' is alphabetical order, which is nobody's idea of how to watch
    a show, and is impossible to explain to a child.
    """
    ep = episode_of(source_name)
    if ep:
        return (0, ep[0], ep[1], ())
    return (1, 0, 0, natural_key(title))


@dataclass
class Node:
    kind: Kind
    path: Path
    rel: str                  # the picks key: path relative to its root
    root: Path
    title: str
    order: tuple = ()         # how it sorts on a shelf; see sort_key()
    children: list["Node"] = field(default_factory=list)

    @property
    def is_playable(self) -> bool:
        return self.kind in (Kind.VIDEO, Kind.AUDIO)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def descendant_rels(self) -> list[str]:
        return [n.rel for n in self.walk() if n is not self]


# Tokens that are about the FILE, not about the show. Dropped from titles.
_JUNK = re.compile(
    r"\b("
    r"\d{3,4}[pi]|4k|uhd|hdr|sdr|10bit|8bit|"
    r"x26[45]|h\.?26[45]|hevc|avc|xvid|divx|av1|vp9|"
    r"web-?dl|web-?rip|bluray|blu-ray|bdrip|brrip|dvdrip|hdtv|hdrip|remux|"
    r"aac\d?|ac3|dts(-hd)?|truehd|atmos|ddp?5[\. ]1|mp3|flac|opus|"
    r"proper|repack|extended|uncut|remastered|internal|limited|multi|dual"
    r")\b", re.I)
_RELEASE_GROUP = re.compile(r"-[A-Za-z0-9]{2,}$")
_YEAR = re.compile(r"[\(\[]?(19|20)\d{2}[\)\]]?")
_EPISODE = re.compile(r"\bS(\d{1,2})[ ._-]?E(\d{1,3})\b", re.I)
_DIGITS = re.compile(r"(\d+)")


def clean_title(name: str) -> str:
    """A filename as something worth putting on a tile.

    Conservative on purpose: separators are normalised and known file-about-the-
    file tokens are dropped, but the words themselves are left exactly as the
    parent named them. Re-capitalising would turn 'PAW Patrol' into 'Paw Patrol'
    and 'Ozzy's birthday' into something worse.
    """
    # A dot is a SEPARATOR when nothing follows it but more title, and
    # PUNCTUATION when a space follows: 'Mr. Men' keeps its full stop,
    # 'Bluey.S01E01.The Magic Xylophone.1080p' loses all of its. Keying on the
    # whole name having no spaces (the obvious first rule) fails on exactly the
    # common case — a dotted release name whose episode title contains spaces —
    # and left 'Bluey. .The Magic Xylophone' on the tile.
    stem = re.sub(r"\.(?!\s)", " ", name)
    stem = stem.replace("_", " ")
    ep = _EPISODE.search(stem)
    stem = _RELEASE_GROUP.sub("", stem)
    stem = _JUNK.sub(" ", stem)
    stem = _YEAR.sub(" ", stem)
    stem = _EPISODE.sub(" ", stem)
    # Brackets whose contents were the junk: '[HDTV]' loses HDTV and would
    # otherwise leave '[ ]' sitting on the tile.
    stem = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", stem)
    stem = re.sub(r"[\s\-–—]+", " ", stem).strip(" -–—.([{)]}")
    if ep:
        season, episode = int(ep.group(1)), int(ep.group(2))
        label = f"S{season} E{episode}"
        stem = f"{stem} · {label}" if stem else label
    return stem or name


def natural_key(text: str) -> tuple:
    """Sort 'Episode 2' before 'Episode 10'.

    Each run becomes a (kind, number, text) triple rather than a bare int or str:
    a list that mixes the two raises TypeError the moment two names differ in
    shape ('Episode 2' against 'Extras'), and the crash would be inside a sort of
    whatever happened to be on the drive.
    """
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower())
                 for p in _DIGITS.split(text))


def _is_media(p: Path) -> Kind | None:
    ext = p.suffix.lower()
    if ext in VIDEO_EXTS:
        return Kind.VIDEO
    if ext in AUDIO_EXTS:
        return Kind.AUDIO
    return None


def _skip(name: str) -> bool:
    return name.startswith(".") or name.lower() in IGNORED_LOWER


def scan_root(root: Path) -> Node | None:
    """One media root as a tree, or None when it is not there.

    A root that is missing is the normal case, not an error: it is a USB stick
    that has not been plugged in. The caller shows the others.
    """
    try:
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            return None
    except (OSError, RuntimeError):
        return None

    # Every directory we have already been inside, by resolved path. A symlink
    # pointing back up the tree is otherwise an infinite library.
    seen: set[str] = set()

    def build(path: Path, rel: str, depth: int) -> Node:
        title = clean_title(path.name) if rel != "." else _root_title(root)
        node = Node(kind=Kind.FOLDER, path=path, rel=rel, root=root, title=title,
                    order=sort_key(title, path.name))
        if depth >= MAX_DEPTH:
            return node
        try:
            key = str(path.resolve(strict=False))
        except (OSError, RuntimeError):
            return node
        if key in seen:
            return node                 # already walked; a link points back here
        seen.add(key)
        try:
            entries = list(path.iterdir())
        except (OSError, PermissionError):
            return node                 # an unreadable folder is an empty one
        folders, files = [], []
        for e in entries:
            if _skip(e.name):
                continue
            child_rel = e.name if rel == "." else f"{rel}/{e.name}"
            try:
                is_dir = e.is_dir()
            except OSError:
                continue
            if is_dir:
                folders.append(build(e, child_rel, depth + 1))
            else:
                kind = _is_media(e)
                if kind is None:
                    continue
                title = clean_title(e.stem)
                files.append(Node(kind=kind, path=e, rel=child_rel, root=root,
                                  title=title, order=sort_key(title, e.stem)))
        folders.sort(key=lambda n: n.order)
        files.sort(key=lambda n: n.order)
        node.children = folders + files
        return node

    return build(root, ".", 0)


def _root_title(root: Path) -> str:
    name = root.name or str(root)
    return clean_title(name)


def scan(roots: list[Path]) -> list[Node]:
    """Every root that is actually present, in the order the parent listed them."""
    out = []
    for r in roots:
        n = scan_root(r)
        if n is not None:
            out.append(n)
    return out


def prune_empty_folders(node: Node) -> Node:
    """Keep the shape of the drive, empty folders and all.

    This used to drop any folder with no media beneath it, on the grounds that a
    shelf you open to find nothing teaches a child the remote is broken. That is
    true — and it also meant a folder you had just made over the network share
    vanished, which teaches a GROWN-UP that the share is broken, and they are the
    one who can do something about it. The sidecar folders that motivated the
    rule (subs, sample, artwork) are filtered by name instead, in config.py.
    """
    if node.is_playable:
        return node
    node.children = [prune_empty_folders(c) for c in node.children]
    return node
