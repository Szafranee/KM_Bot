"""SQLite helpers.

The project uses three database files:

* ``timetable.sqlite`` and ``rolling_stock.sqlite`` hold imported, read-only data. They are rebuilt into a
  temporary file and swapped in atomically, so readers never see a half-imported database.
* ``app.sqlite`` holds user data (favourites, routes, tracked trains) and the realtime cache. It is migrated
  in place.

Connections are short-lived (one per operation): Passenger may run several bot processes at once and the
import swaps files underneath them.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=15)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def open_db(path: Path, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    """Yields a connection, commits on success and always closes it."""
    conn = connect(path, readonly=readonly)
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()


@contextmanager
def rebuild_db(path: Path) -> Iterator[sqlite3.Connection]:
    """Builds a fresh database next to ``path`` and atomically replaces ``path`` when the block succeeds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        yield conn
        conn.commit()
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(tmp, path)


def exists(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0
