"""The whole of Ozzy TV's behaviour, with nothing drawn.

Every screen, every keypress and every rule about what happens next lives here,
as a state machine over plain data. The drawing layer (tkview.py) does two
things: hand keypresses in as Actions, and render `view()`. Nothing else.

That split is not tidiness. A television for a child is exactly the kind of
software nobody tests, because testing it appears to need a television — and the
consequences of not testing it land on someone who cannot report a bug. With the
behaviour separated out, the navigation, the PIN gate and the parent screen are
all driven headlessly, and what is left unverified is confined to widget
plumbing.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import library, picks
from .library import Kind, Node
from .picks import Mark, Rules
from .playback import PlaybackSession, PlayState, SEEK_BIG_MS, SEEK_SMALL_MS
from .security import PinGate, WeakPin, check_pin_strength

# How often to look for programmes that arrived over the network. Long enough
# that it is not a drip of I/O, short enough that somebody who has just copied a
# film over does not conclude it did not work.
LOOK_FOR_NEW_EVERY = 5.0

log = logging.getLogger(__name__)


class Action(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    SELECT = "select"
    BACK = "back"
    PLAY_PAUSE = "play_pause"
    PARENT = "parent"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    DIGIT = "digit"          # carries a value
    CLEAR = "clear"
    QUIT = "quit"


class Pane(str, Enum):
    """Which half of the browse screen the remote is driving.

    Roku's home screen is two panes — a list of places down the left, what is in
    the highlighted place across the right — and it suits a child better than a
    single grid does: you can always see where you are without remembering how
    you got there, and getting out is one press of Left rather than a guess.
    """
    RAIL = "rail"
    GRID = "grid"


class Screen(str, Enum):
    BROWSE = "browse"
    PLAYING = "playing"
    PIN = "pin"
    PARENT = "parent"
    MESSAGE = "message"


@dataclass
class RailItem:
    title: str
    rel: str
    root_index: int
    count: int = 0
    # The synthetic first entry for files sitting loose in the current folder,
    # so they have somewhere to be listed without inventing a folder for them.
    is_here: bool = False


@dataclass
class Tile:
    title: str
    kind: str
    rel: str
    root_index: int
    badge: str = ""          # 'resume' | 'may not play' — shown as a corner mark


@dataclass
class ParentRow:
    title: str
    rel: str
    root_index: int
    depth: int
    kind: str
    mark: str                # 'allow' | 'block' | ''  (this row's OWN mark)
    effective: bool          # what the child actually gets
    inherited_from: str      # the rule that decided, '' when this row decides
    note: str = ""


@dataclass
class View:
    screen: str
    heading: str = ""
    subheading: str = ""
    tiles: list[Tile] = field(default_factory=list)
    cursor: int = 0
    rail: list[RailItem] = field(default_factory=list)
    rail_cursor: int = 0
    focus: str = Pane.RAIL.value
    can_go_back: bool = False
    message: str = ""
    # playing
    now_title: str = ""
    position_ms: int = 0
    duration_ms: int = 0
    paused: bool = False
    volume: int = 0
    resumed_from_ms: int = 0
    # pin
    pin_digits: int = 0
    pin_error: str = ""
    lock_seconds: int = 0
    pin_prompt: str = ""
    # parent
    rows: list[ParentRow] = field(default_factory=list)
    parent_hint: str = ""
    # the first-boot menu: (title, explanation) for each thing left to do
    welcome: list[tuple[str, str]] = field(default_factory=list)


# What a child sees when a parent has not chosen anything yet. Deliberately not
# an error: nothing is broken, an adult just has not finished setting up.
# Rail entries that are not folders.
RECENT_KEY = "\x00recent"
LOOSE_KEY = "\x00loose"
RECENT_LIMIT = 12

WELCOME_KEY = "\x00welcome"

NOTHING_ALLOWED = ("Nothing to watch yet.\n\n"
                   "Ask a grown-up to choose some programmes for you.")
NO_MEDIA = ("No films or programmes found.\n\n"
            "Ask a grown-up to plug in the drive with the videos on it.")


def welcome_steps(settings, allowed: bool) -> list[tuple[str, str]]:
    """What to do next, on the screen, in order.

    A first boot is the one time this television has something to say to the
    grown-up rather than to the child, and the grown-up is standing in front of
    it rather than reading a README.
    """
    where = str(settings.roots[0]) if settings.roots else "/media/ozzy"
    steps = [("Copy programmes in",
              f"Put films and episodes in {where} — over the network, or on a "
              f"memory stick."),
             ("Choose what Ozzy can watch",
              "Press P, type the PIN, and allow the ones you are happy with.")]
    if allowed:
        # The drive is not the problem, so lead with the step that is.
        steps.reverse()
    steps.append(("Nothing is visible until you allow it",
                  "That is deliberate. A stick someone plugs in later shows up "
                  "to you, not to your child."))
    return steps


class OzzyApp:
    def __init__(self, settings, store, player, clock=None):
        self.settings = settings
        self.store = store
        self.player = player
        self.pin = PinGate(store)
        self.playback = PlaybackSession(player, store, settings)
        self._clock = clock or (lambda: __import__("time").time())

        self.screen = Screen.BROWSE
        self.roots: list[Node] = []
        self.rules: list[Rules] = []
        self._stack: list[tuple[int, str]] = []   # (root index, rel) breadcrumbs
        self.focus = Pane.RAIL
        self.rail_cursor = 0
        # WHICH shelf is highlighted, not merely where it sits. "Watch again"
        # appears the moment anything is played, pushing every other shelf down
        # one — and an index-only cursor then silently highlights a different
        # shelf than the one the child was looking at.
        self._rail_rel = ""
        self.cursor = 0                           # position in the tile grid
        self.message = ""
        self._pin_buffer = ""
        self._pin_error = ""
        self._pin_purpose = "parent"              # 'parent' | 'set' | 'confirm'
        self._new_pin = ""
        self._parent_rows: list[ParentRow] = []
        self._parent_cursor = 0
        self.should_quit = False
        self._library_seen: tuple = ()
        self._looked_at = 0.0
        self.rescan()
        self._library_seen = self._fingerprint()

    # ------------------------------------------------------------------ scan
    def _fingerprint(self) -> tuple:
        """A cheap signal that the library on disk has changed.

        Directory mtimes only — one per folder, not per file. Adding, removing
        or renaming anything changes the mtime of the folder it happened in, so
        this notices a new episode three levels down without walking the files,
        and costs a stat per folder rather than a scan of the drive. That
        distinction is the whole point: this runs on an SD card, a few times a
        minute, forever.
        """
        out = []
        seen = set()
        folders = [r for r in self.settings.roots]
        folders += [n.path for root in self.roots for n in root.walk()
                    if not n.is_playable]
        for d in folders:
            if d in seen:
                continue
            seen.add(d)
            try:
                out.append((str(d), os.stat(d).st_mtime_ns))
            except OSError:
                out.append((str(d), -1))       # gone counts as a change
        return tuple(sorted(out))

    def look_for_new_programmes(self) -> bool:
        """Rescan if the drive changed, WITHOUT losing where somebody is.

        Films arrive over the network now, which means the library changes while
        the television is switched on and pointed at it. rescan() empties the
        stack and sends the cursor home — fine at startup, but as a background
        refresh it would snatch the screen away mid-choice.
        """
        now = self._fingerprint()
        if now == self._library_seen:
            return False
        where, rail, cursor, focus = (list(self._stack), self._rail_rel,
                                      self.cursor, self.focus)
        self.rescan()
        self._library_seen = self._fingerprint()
        # Walk back to where they were, as far as it still exists. A folder that
        # was deleted out from under them stops the descent there rather than
        # erroring — which is exactly what it should do.
        for ri, rel in where:
            if self._node_at(ri, rel) is None:
                break
            self._stack.append((ri, rel))
        self._rail_rel, self.cursor, self.focus = rail, cursor, focus
        return True

    def rescan(self) -> None:
        self.roots = [library.prune_empty_folders(n)
                      for n in library.scan(self.settings.roots)]
        self.rules = [self.store.rules_for(n.root) for n in self.roots]
        self._stack = []
        self.focus = Pane.RAIL
        self.rail_cursor = 0
        self.cursor = 0

    # -------------------------------------------------------------- browsing
    def _node_at(self, root_index: int, rel: str) -> Node | None:
        if not (0 <= root_index < len(self.roots)):
            return None
        node = self.roots[root_index]
        if rel == picks.ROOT_KEY:
            return node
        for n in node.walk():
            if n.rel == rel:
                return n
        return None

    def _current(self) -> tuple[int, Node] | None:
        if not self._stack:
            return None
        ri, rel = self._stack[-1]
        node = self._node_at(ri, rel)
        return (ri, node) if node else None

    def _visible_children(self, root_index: int, node: Node) -> list[Node]:
        """What the child may see in this folder.

        A folder survives only if something under it is visible — an openable
        shelf that turns out to be empty is indistinguishable, to a child, from
        having pressed the wrong button.
        """
        rules = self.rules[root_index]
        out = []
        for c in node.children:
            if c.is_playable:
                if picks.decide_rel(rules, c.rel).visible:
                    out.append(c)
            elif picks.folder_has_anything_visible(rules, c.rel, c.descendant_rels()):
                out.append(c)
        return out

    def _top_level(self) -> list[tuple[int, Node]]:
        """The first screen. One root drops you straight into it — making a child
        open 'USB Drive' before they can reach anything is a step for nobody."""
        present = [(i, r) for i, r in enumerate(self.roots)]
        if len(present) == 1:
            i, root = present[0]
            return [(i, c) for c in self._visible_children(i, root)]
        out = []
        for i, root in present:
            if self._visible_children(i, root):
                out.append((i, root))
        return out

    def _browse_items(self) -> list[tuple[int, Node]]:
        cur = self._current()
        if cur is None:
            return self._top_level()
        ri, node = cur
        return [(ri, c) for c in self._visible_children(ri, node)]

    def _here_title(self) -> str:
        cur = self._current()
        return cur[1].title if cur else "Ozzy TV"

    def _playable_under(self, root_index: int, node: Node) -> list[tuple[int, Node]]:
        """Everything watchable anywhere below `node`, flattened.

        Used for the shelf COUNTS and for "Watch again" — not for the tiles. The
        grid shows what is actually in a folder, sub-folders included, because the
        person holding the remote is a grown-up who filed it that way on purpose.
        """
        rules = self.rules[root_index]
        out = []
        for n in node.walk():
            if n is node or not n.is_playable:
                continue
            if picks.decide_rel(rules, n.rel).visible:
                out.append((root_index, n))
        return out

    def _shelves(self) -> list[tuple[int, Node]]:
        """The folders down the left: the ones at wherever we currently are."""
        cur = self._current()
        if cur is None:
            return [(ri, c) for ri, root in enumerate(self.roots)
                    for c in self._visible_children(ri, root) if not c.is_playable]
        ri, node = cur
        return [(ri, c) for c in self._visible_children(ri, node) if not c.is_playable]

    def _rail(self) -> list[RailItem]:
        """The shelves down the left — the only list a child ever chooses from.

        "Watch again" comes first because it is what a toddler actually wants:
        the thing they had yesterday, whose name they cannot read.
        """
        rail: list[RailItem] = []
        if self._current() is None and self._recent():
            rail.append(RailItem(title="Watch again", rel=RECENT_KEY, root_index=-1,
                                 count=len(self._recent()), is_here=True))
        cur = self._current()
        if cur is None:
            loose = [(ri, n) for ri, root in enumerate(self.roots)
                     for n in self._visible_children(ri, root) if n.is_playable]
        else:
            loose = [(cur[0], n) for n in self._visible_children(*cur) if n.is_playable]
        if loose:
            rail.append(RailItem(title=self._here_title() if cur else "Everything else",
                                 rel=LOOSE_KEY, root_index=loose[0][0],
                                 count=len(loose), is_here=True))
        for ri, node in self._shelves():
            items = self._playable_under(ri, node)
            if items:
                rail.append(RailItem(title=node.title, rel=node.rel, root_index=ri,
                                     count=len(items)))
        return rail

    def _recent(self) -> list[tuple[int, Node]]:
        """Recently watched, newest first, dropping anything since hidden or
        deleted — a rule changed in the parent screen must take effect here too,
        or "Watch again" becomes a way round it."""
        by_path = {str(n.path): (ri, n) for ri, root in enumerate(self.roots)
                   for n in root.walk() if n.is_playable}
        out = []
        for path, _title, _root, _rel in self.store.recent(RECENT_LIMIT):
            hit = by_path.get(path)
            if hit is None:
                continue
            ri, node = hit
            if picks.decide_rel(self.rules[ri], node.rel).visible:
                out.append(hit)
        return out

    def _grid(self) -> list[tuple[int, Node]]:
        """What is on the highlighted shelf. Only things that play."""
        rail = self._rail()
        if not rail:
            return []
        sel = rail[min(self.rail_cursor, len(rail) - 1)]
        if sel.rel == RECENT_KEY:
            return self._recent()
        if sel.rel == LOOSE_KEY:
            cur = self._current()
            if cur is None:
                return [(ri, n) for ri, root in enumerate(self.roots)
                        for n in self._visible_children(ri, root) if n.is_playable]
            return [(cur[0], n) for n in self._visible_children(*cur) if n.is_playable]
        node = self._node_at(sel.root_index, sel.rel)
        if node is None:
            return []
        return [(sel.root_index, c)
                for c in self._visible_children(sel.root_index, node)]

    # ---------------------------------------------------------------- input
    def handle(self, action: Action, value: str = "") -> None:
        """One keypress. Never raises: a television that shows a traceback to a
        four-year-old has failed at its only job."""
        try:
            self._handle(action, value)
        except Exception:
            log.exception("action %s failed", action)
            self.screen = Screen.MESSAGE
            self.message = "Something went wrong.\n\nAsk a grown-up."

    def _handle(self, action: Action, value: str) -> None:
        if action is Action.PARENT and self.screen in (Screen.BROWSE, Screen.MESSAGE):
            self._open_pin("parent")
            return
        handler = {
            Screen.BROWSE: self._browse_key,
            Screen.PLAYING: self._playing_key,
            Screen.PIN: self._pin_key,
            Screen.PARENT: self._parent_key,
            Screen.MESSAGE: self._message_key,
        }[self.screen]
        handler(action, value)

    # -- kid: the two panes --
    def _browse_key(self, action: Action, value: str) -> None:
        rail = self._sync_rail(self._rail())
        grid = self._grid()
        cols = max(1, self.settings.columns)
        if self.focus is Pane.RAIL:
            if action is Action.UP:
                self.rail_cursor = max(0, self.rail_cursor - 1)
                self.cursor = 0
            elif action is Action.DOWN:
                self.rail_cursor = min(len(rail) - 1, self.rail_cursor + 1) if rail else 0
                self.cursor = 0
            if action in (Action.UP, Action.DOWN) and rail:
                self._rail_rel = rail[self.rail_cursor].rel
            elif action in (Action.RIGHT, Action.SELECT):
                if grid:
                    self.focus = Pane.GRID
                    self.cursor = 0
            elif action is Action.BACK:
                # Out of a folder. At the top there is nowhere to go, and that is
                # NOT an exit: holding Back is how a child looks for a way out of
                # an app, and there must not be one.
                if self._stack:
                    _, rel = self._stack.pop()
                    self._rail_rel = rel
                    self.rail_cursor = 0
                    self.cursor = 0
            return

        # focus is the grid
        if action is Action.UP:
            if self.cursor < cols:
                self.focus = Pane.RAIL      # off the top of the tiles, back to the list
            else:
                self.cursor -= cols
        elif action is Action.DOWN:
            self.cursor = min(len(grid) - 1, self.cursor + cols) if grid else 0
        elif action is Action.LEFT:
            if self.cursor % cols == 0:
                self.focus = Pane.RAIL      # off the left edge, back to the list
            else:
                self.cursor -= 1
        elif action is Action.RIGHT:
            self.cursor = min(len(grid) - 1, self.cursor + 1) if grid else 0
        elif action is Action.SELECT:
            self._open(grid)
        elif action is Action.BACK:
            self.focus = Pane.RAIL

    # ------------------------------------------------------------- pointing
    def click(self, target: str) -> None:
        """Press a thing by name — "rail:2", "tile:5".

        A pointer is not how a child drives this, and the screen is still laid
        out for a remote. But the grown-up setting it up has a mouse in their
        hand, and a tile that does nothing when clicked reads as broken rather
        than as deliberate. The decision lives here, not in the drawing layer,
        for the same reason every other decision does: it can be tested.
        """
        kind, _, n = target.partition(":")
        if not n.isdigit():
            return
        i = int(n)
        if kind == "rail":
            rail = self._sync_rail(self._rail())
            if 0 <= i < len(rail):
                self.focus = Pane.RAIL
                self.rail_cursor = i
                self._rail_rel = rail[i].rel
                self.cursor = 0
        elif kind == "tile":
            grid = self._grid()
            if 0 <= i < len(grid):
                # Move to it AND open it. One click, because a click that only
                # moved a highlight would need a second one nobody would guess.
                self.focus = Pane.GRID
                self.cursor = i
                self._open(grid)
        elif kind == "row":
            # The parent screen. Move to the row; do NOT toggle it. Allowing or
            # blocking something a child can watch is a decision, and a stray
            # click is not one — OK still does that, deliberately.
            if 0 <= i < len(self._parent_rows):
                self._parent_cursor = i
        elif kind == "digit":
            self.handle(Action.DIGIT, n)

    def _sync_rail(self, rail: list[RailItem]) -> list[RailItem]:
        """Keep the highlight on the SHELF it was on, whatever moved around it."""
        if not rail:
            self.rail_cursor = 0
            return rail
        if self._rail_rel:
            for i, item in enumerate(rail):
                if item.rel == self._rail_rel:
                    self.rail_cursor = i
                    return rail
        self.rail_cursor = min(self.rail_cursor, len(rail) - 1)
        self._rail_rel = rail[self.rail_cursor].rel
        return rail

    def _open(self, items: list[tuple[int, Node]]) -> None:
        if not (0 <= self.cursor < len(items)):
            return
        ri, node = items[self.cursor]
        if node.is_playable:
            self._play(ri, node)
        else:
            self._stack.append((ri, node.rel))
            self.focus = Pane.RAIL
            self.rail_cursor = 0
            self._rail_rel = ""
            self.cursor = 0

    def _play(self, root_index: int, node: Node) -> None:
        # Re-check at the moment of playing, not only when the grid was drawn.
        # The rules could have changed in the parent screen since, and this is the
        # last point before something actually appears on the television.
        #
        # The root index is passed in rather than searched for: looking the node's
        # root up again by value raises StopIteration if a rescan has replaced the
        # tree in between, and that exception on this path would be a traceback in
        # front of a child.
        ri = root_index
        if not picks.decide(self.rules[ri], node.root, node.path).visible:
            self.screen = Screen.MESSAGE
            self.message = NOTHING_ALLOWED
            return
        self.store.record_play(node.path, node.title, node.root, node.rel)
        self.playback.start(node.path, node.title)
        self.screen = Screen.PLAYING

    # -- kid: watching --
    def _playing_key(self, action: Action, value: str) -> None:
        if action in (Action.SELECT, Action.PLAY_PAUSE):
            self.playback.toggle_pause()
        elif action is Action.BACK:
            self.playback.stop()
            self.screen = Screen.BROWSE
        elif action is Action.RIGHT:
            self.playback.seek(SEEK_SMALL_MS)
        elif action is Action.LEFT:
            self.playback.seek(-SEEK_SMALL_MS)
        elif action is Action.UP:
            self.playback.seek(SEEK_BIG_MS)
        elif action is Action.DOWN:
            self.playback.seek(-SEEK_BIG_MS)
        elif action is Action.VOLUME_UP:
            self.playback.change_volume(5)
        elif action is Action.VOLUME_DOWN:
            self.playback.change_volume(-5)

    def tick(self) -> None:
        """Called a few times a second by the drawing layer."""
        if self.screen is not Screen.PLAYING:
            # Not while something is playing: the drive is busy feeding VLC, and
            # a stat storm on an SD card is a stutter in the picture.
            now = self._clock()
            if now - self._looked_at >= LOOK_FOR_NEW_EVERY:
                self._looked_at = now
                self.look_for_new_programmes()
            return
        state = self.playback.tick()
        if state in (PlayState.ENDED, PlayState.ERROR):
            failed = state is PlayState.ERROR
            self.playback.stop()
            self.screen = Screen.BROWSE
            if failed:
                self.screen = Screen.MESSAGE
                self.message = ("That one would not play.\n\n"
                                "Ask a grown-up to check it.")

    # -- the keypad --
    def _open_pin(self, purpose: str) -> None:
        self._pin_buffer = ""
        self._pin_error = ""
        self._pin_purpose = purpose
        if purpose == "parent" and not self.pin.is_set():
            # No PIN yet — a fresh install. Let the first person through and make
            # them set one, rather than locking the parent out of their own box.
            self.screen = Screen.PARENT
            self._build_parent_rows()
            self.message = "Set a PIN from this screen before anyone else does."
            return
        self.screen = Screen.PIN

    def _pin_key(self, action: Action, value: str) -> None:
        if action is Action.BACK:
            self.screen = Screen.BROWSE
            self._pin_buffer = ""
            return
        if action is Action.CLEAR:
            self._pin_buffer = ""
            return
        if action is Action.DIGIT and value.isdigit():
            self._pin_buffer += value
            self._pin_error = ""
            return
        if action is Action.SELECT:
            self._pin_submit()

    def _pin_submit(self) -> None:
        entered, self._pin_buffer = self._pin_buffer, ""
        if self._pin_purpose == "parent":
            lo = self.pin.lockout()
            if lo.locked(self._clock()):
                self._pin_error = f"Too many tries. Wait {lo.seconds_left(self._clock())}s."
                return
            if self.pin.check(entered, self._clock()):
                self.screen = Screen.PARENT
                self._build_parent_rows()
                self.message = ""
                return
            lo = self.pin.lockout()
            self._pin_error = ("Wrong PIN." if not lo.locked(self._clock())
                               else f"Wrong PIN. Wait {lo.seconds_left(self._clock())}s.")
            return
        if self._pin_purpose == "set":
            try:
                check_pin_strength(entered)
            except WeakPin as e:
                self._pin_error = str(e)
                return
            self._new_pin = entered
            self._pin_purpose = "confirm"
            return
        if self._pin_purpose == "confirm":
            if entered != self._new_pin:
                self._pin_error = "Those did not match. Start again."
                self._pin_purpose = "set"
                self._new_pin = ""
                return
            self.pin.set_pin(entered)
            self._new_pin = ""
            self.screen = Screen.PARENT
            self._build_parent_rows()
            self.message = "PIN saved."

    # -- the parent screen --
    def _build_parent_rows(self) -> None:
        rows: list[ParentRow] = []
        for ri, root in enumerate(self.roots):
            rules = self.rules[ri]
            def add(node: Node, depth: int):
                d = picks.decide_rel(rules, node.rel)
                own = rules.marks.get(node.rel)
                note = ""
                if own is Mark.ALLOW and node.kind is Kind.FOLDER:
                    note = "whole folder — new files here show up too"
                elif d.visible and d.inherited:
                    note = f"from “{d.by}”"
                elif not d.visible and d.by:
                    note = f"blocked by “{d.by}”"
                elif not d.visible:
                    note = "not chosen yet"
                rows.append(ParentRow(
                    title=node.title, rel=node.rel, root_index=ri, depth=depth,
                    kind=node.kind.value, mark=own.value if own else "",
                    effective=d.visible, inherited_from=d.by if d.inherited else "",
                    note=note))
                for c in node.children:
                    add(c, depth + 1)
            add(root, 0)
        self._parent_rows = rows
        self._parent_cursor = min(self._parent_cursor, max(0, len(rows) - 1))

    def _parent_key(self, action: Action, value: str) -> None:
        rows = self._parent_rows
        if action is Action.UP:
            self._parent_cursor = max(0, self._parent_cursor - 1)
        elif action is Action.DOWN:
            self._parent_cursor = min(len(rows) - 1, self._parent_cursor + 1) if rows else 0
        elif action is Action.SELECT:
            self._cycle_mark()
        elif action is Action.BACK:
            self.screen = Screen.BROWSE
            self.focus = Pane.RAIL
            self.rail_cursor = 0
            self.cursor = 0
            self._stack = []
            self.message = ""
        elif action is Action.PARENT:
            self._pin_purpose = "set"
            self._pin_buffer = ""
            self._pin_error = ""
            self.screen = Screen.PIN
        elif action is Action.QUIT:
            self.should_quit = True

    def _cycle_mark(self) -> None:
        """One button, three states — a remote has no modifier keys.

        The FIRST press always changes what the child sees. Cycling in a fixed
        allow → block → inherit order reads as a broken button on half the rows:
        pressing OK on something already visible and watching it stay visible is
        indistinguishable from nothing happening. So the first press is whichever
        mark flips the current outcome, the second is the other one, and the third
        clears the row back to inheriting from its folder.
        """
        if not (0 <= self._parent_cursor < len(self._parent_rows)):
            return
        row = self._parent_rows[self._parent_cursor]
        rules = self.rules[row.root_index]
        current = rules.marks.get(row.rel)
        # The cycle's ORDER is fixed by what this row would be with no mark of its
        # own — a value that does not change as we cycle, so pressing OK three
        # times always lands back where it started. Deriving it from the row's
        # CURRENT outcome instead collapses into a two-state flip, because after
        # the first press the outcome is the thing that changed.
        inherited_visible = picks.decide_rel(
            rules.with_mark(row.rel, None), row.rel).visible
        cycle = ([None, Mark.BLOCK, Mark.ALLOW] if inherited_visible
                 else [None, Mark.ALLOW, Mark.BLOCK])
        nxt = cycle[(cycle.index(current) + 1) % len(cycle)]
        root = self.roots[row.root_index].root
        self.store.set_mark(root, row.rel, nxt)
        self.rules[row.root_index] = self.store.rules_for(root)
        self._build_parent_rows()

    def _message_key(self, action: Action, value: str) -> None:
        if action in (Action.BACK, Action.SELECT):
            self.screen = Screen.BROWSE
            self.message = ""

    # ----------------------------------------------------------------- view
    def view(self) -> View:
        if self.screen is Screen.PLAYING and self.playback.now:
            n = self.playback.now
            return View(screen=Screen.PLAYING.value, now_title=n.title,
                        position_ms=n.position_ms, duration_ms=n.duration_ms,
                        paused=self.player.state() is PlayState.PAUSED,
                        volume=self.playback.volume,
                        resumed_from_ms=n.resumed_from_ms)
        if self.screen is Screen.PIN:
            lo = self.pin.lockout()
            prompt = {"parent": "Grown-ups only", "set": "Choose a new PIN",
                      "confirm": "Type it once more"}[self._pin_purpose]
            return View(screen=Screen.PIN.value, heading=prompt,
                        pin_digits=len(self._pin_buffer), pin_error=self._pin_error,
                        lock_seconds=lo.seconds_left(self._clock()),
                        pin_prompt=self._pin_purpose)
        if self.screen is Screen.PARENT:
            return View(screen=Screen.PARENT.value, heading="Choose what Ozzy can watch",
                        rows=self._parent_rows, cursor=self._parent_cursor,
                        message=self.message,
                        parent_hint="OK cycles allow / block / inherit · "
                                    "P sets the PIN · Back returns to Ozzy")
        if self.screen is Screen.MESSAGE:
            return View(screen=Screen.MESSAGE.value, message=self.message)

        rail = self._sync_rail(self._rail())
        if not rail:
            # A MENU with nothing on it, not a message INSTEAD of the menu.
            # Throwing the whole screen away for a line of text meant a fresh
            # install looked broken rather than empty: no logo, no shelves, and
            # no sign that pressing P is how a grown-up fixes it. The layout is
            # the thing that says "this is working, it is just waiting for you".
            any_media = any(r.children for r in self.roots)
            return View(screen=Screen.BROWSE.value,
                        heading="Nothing to watch yet",
                        subheading="Ozzy TV",
                        rail=[RailItem("Getting started", WELCOME_KEY, -1, 0, True)],
                        rail_cursor=0, focus=Pane.RAIL.value,
                        message=NOTHING_ALLOWED if any_media else NO_MEDIA,
                        welcome=welcome_steps(self.settings, allowed=any_media))
        items = self._grid()
        tiles = []
        for ri, n in items:
            badge = ""
            if n.is_playable:
                if self.store.get_resume(n.path):
                    badge = "resume"
                else:
                    pl = self.store.get_playability(n.path)
                    if pl and pl[0] == "no":
                        badge = "may not play"
            tiles.append(Tile(title=n.title, kind=n.kind.value, rel=n.rel,
                              root_index=ri, badge=badge))
        # The breadcrumb is built from the PATH, not from the navigation stack.
        # A shelf is entered from the rail, so the stack holds one entry —
        # "Bluey/Series 1" — and reading titles off the stack produced
        # "Ozzy TV › Series 1", quietly losing the folder it is inside.
        trail: list[str] = []
        if self._stack:
            ri, rel = self._stack[-1]
            parts = rel.split("/")
            for i in range(len(parts)):
                node = self._node_at(ri, "/".join(parts[:i + 1]))
                if node:
                    trail.append(node.title)
        return View(screen=Screen.BROWSE.value,
                    heading=rail[self.rail_cursor].title,
                    subheading=" › ".join(["Ozzy TV"] + trail),
                    tiles=tiles, cursor=min(self.cursor, max(0, len(tiles) - 1)),
                    rail=rail, rail_cursor=self.rail_cursor,
                    focus=self.focus.value, can_go_back=bool(self._stack))
