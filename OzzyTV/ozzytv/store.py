"""Everything Ozzy TV remembers: one SQLite file, no server, no daemon.

SQLite because it is in the standard library, survives the power being pulled out
of a Raspberry Pi mid-write (which is how these machines are usually turned off),
and gives us one file a parent can copy to a new SD card and keep their choices.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import app_home
from .picks import Mark, Rules

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- What the child may see. Keyed by the RESOLVED root plus the path relative to
-- it, so a library that moves with its drive keeps its rules, and two roots that
-- both contain a 'Films' folder do not share one.
CREATE TABLE IF NOT EXISTS marks (
    root TEXT NOT NULL,
    rel  TEXT NOT NULL,
    mark TEXT NOT NULL CHECK (mark IN ('allow','block')),
    set_at REAL NOT NULL,
    PRIMARY KEY (root, rel)
);

-- Where we got to. size+mtime are part of the row on purpose: a file replaced by
-- a different one of the same name must not resume into the middle of it.
CREATE TABLE IF NOT EXISTS resume (
    path        TEXT PRIMARY KEY,
    position_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    size        INTEGER NOT NULL,
    mtime       REAL    NOT NULL,
    updated     REAL    NOT NULL
);

-- What was watched, most recent first. Toddlers do not browse; they want the
-- thing they had yesterday, and they cannot read the name of it. "Watch again"
-- is the top shelf for that reason.
CREATE TABLE IF NOT EXISTS history (
    path      TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    root      TEXT NOT NULL,
    rel       TEXT NOT NULL,
    played_at REAL NOT NULL
);

-- Whether this hardware can actually play a file (see probe.py). Cached because
-- the answer only changes when the file does, and asking costs a subprocess.
CREATE TABLE IF NOT EXISTS playability (
    path    TEXT PRIMARY KEY,
    size    INTEGER NOT NULL,
    mtime   REAL    NOT NULL,
    verdict TEXT    NOT NULL,
    detail  TEXT    NOT NULL DEFAULT '',
    checked REAL    NOT NULL
);
"""


def db_path() -> Path:
    return app_home() / "ozzytv.db"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None,
                                     check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL: the player thread reads while the UI writes a resume position, and
        # the default journal makes them wait on each other.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self):
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ---- meta ------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ---- what the child may see -----------------------------------------
    @staticmethod
    def _rootkey(root: Path) -> str:
        return str(root.resolve(strict=False))

    def rules_for(self, root: Path) -> Rules:
        rows = self._conn.execute("SELECT rel, mark FROM marks WHERE root=?",
                                  (self._rootkey(root),)).fetchall()
        return Rules(marks={r["rel"]: Mark(r["mark"]) for r in rows})

    def set_mark(self, root: Path, rel: str, mark: Mark | None) -> None:
        rk = self._rootkey(root)
        if mark is None:
            self._conn.execute("DELETE FROM marks WHERE root=? AND rel=?", (rk, rel))
            return
        self._conn.execute(
            "INSERT INTO marks(root,rel,mark,set_at) VALUES(?,?,?,?) "
            "ON CONFLICT(root,rel) DO UPDATE SET mark=excluded.mark, set_at=excluded.set_at",
            (rk, rel, mark.value, time.time()))

    def clear_marks(self, root: Path) -> None:
        self._conn.execute("DELETE FROM marks WHERE root=?", (self._rootkey(root),))

    def all_marks(self) -> list[tuple[str, str, Mark]]:
        return [(r["root"], r["rel"], Mark(r["mark"])) for r in
                self._conn.execute("SELECT root, rel, mark FROM marks ORDER BY root, rel")]

    # ---- where we got to -------------------------------------------------
    def save_resume(self, path: Path, position_ms: int, duration_ms: int) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        self._conn.execute(
            "INSERT INTO resume(path,position_ms,duration_ms,size,mtime,updated) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
            "position_ms=excluded.position_ms, duration_ms=excluded.duration_ms, "
            "size=excluded.size, mtime=excluded.mtime, updated=excluded.updated",
            (str(path), int(position_ms), int(duration_ms), st.st_size, st.st_mtime,
             time.time()))

    def get_resume(self, path: Path) -> int | None:
        """The stored position, or None — including when the file has CHANGED
        since. A same-named replacement resuming 20 minutes in is worse than
        simply starting again."""
        row = self._conn.execute(
            "SELECT position_ms, size, mtime FROM resume WHERE path=?", (str(path),)
        ).fetchone()
        if not row:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        if st.st_size != row["size"] or abs(st.st_mtime - row["mtime"]) > 1.0:
            self._conn.execute("DELETE FROM resume WHERE path=?", (str(path),))
            return None
        return int(row["position_ms"])

    def clear_resume(self, path: Path) -> None:
        self._conn.execute("DELETE FROM resume WHERE path=?", (str(path),))

    # ---- what was watched -------------------------------------------------
    def record_play(self, path: Path, title: str, root: Path, rel: str) -> None:
        self._conn.execute(
            "INSERT INTO history(path,title,root,rel,played_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET played_at=excluded.played_at, "
            "title=excluded.title",
            (str(path), title, self._rootkey(root), rel, time.time()))

    def recent(self, limit: int = 12) -> list[tuple[str, str, str, str]]:
        """(path, title, root, rel), newest first."""
        return [(r["path"], r["title"], r["root"], r["rel"]) for r in self._conn.execute(
            "SELECT path,title,root,rel FROM history ORDER BY played_at DESC LIMIT ?",
            (int(limit),))]

    def forget_history(self) -> None:
        self._conn.execute("DELETE FROM history")

    # ---- can this hardware play it? --------------------------------------
    def get_playability(self, path: Path) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT size, mtime, verdict, detail FROM playability WHERE path=?",
            (str(path),)).fetchone()
        if not row:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        if st.st_size != row["size"] or abs(st.st_mtime - row["mtime"]) > 1.0:
            return None                 # the file changed; the old answer is void
        return row["verdict"], row["detail"]

    def save_playability(self, path: Path, verdict: str, detail: str = "") -> None:
        try:
            st = path.stat()
        except OSError:
            return
        self._conn.execute(
            "INSERT INTO playability(path,size,mtime,verdict,detail,checked) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
            "size=excluded.size, mtime=excluded.mtime, verdict=excluded.verdict, "
            "detail=excluded.detail, checked=excluded.checked",
            (str(path), st.st_size, st.st_mtime, verdict, detail, time.time()))
