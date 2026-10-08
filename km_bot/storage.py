"""User data and caches kept in ``app.sqlite`` (favourites, saved routes, tracked trains, realtime cache)."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from km_bot import db

MIGRATIONS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS favorite_stations (
        user_id INTEGER NOT NULL,
        station_id TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (user_id, station_id)
    );
    CREATE TABLE IF NOT EXISTS favorite_routes (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        from_id TEXT NOT NULL,
        from_name TEXT NOT NULL,
        to_id TEXT NOT NULL,
        to_name TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE (user_id, from_id, to_id)
    );
    CREATE TABLE IF NOT EXISTS user_state (
        user_id INTEGER PRIMARY KEY,
        state TEXT NOT NULL,
        data TEXT NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS watches (
        id INTEGER PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        trip_id TEXT NOT NULL,
        service_date TEXT NOT NULL,
        station_id TEXT,
        label TEXT NOT NULL,
        last_delay INTEGER,
        last_cancelled INTEGER NOT NULL DEFAULT 0,
        reminded INTEGER NOT NULL DEFAULT 0,
        expires_at REAL NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE (chat_id, trip_id, service_date)
    );
    CREATE TABLE IF NOT EXISTS rt_cache (
        key TEXT PRIMARY KEY,
        fetched_at REAL NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rt_trips (
        trip_id TEXT NOT NULL,
        start_date TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (trip_id, start_date)
    );
    """,
]

STATE_TTL = 30 * 60


@dataclass(frozen=True)
class FavoriteRoute:
    id: int
    from_id: str
    from_name: str
    to_id: str
    to_name: str


@dataclass(frozen=True)
class Watch:
    id: int
    chat_id: int
    user_id: int
    trip_id: str
    service_date: date
    station_id: str | None
    label: str
    last_delay: int | None
    last_cancelled: bool
    reminded: bool
    expires_at: float


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self._migrated = False

    def _db(self):
        if not self._migrated:
            self.migrate()
        return db.open_db(self.path)

    def migrate(self) -> None:
        # Statements are idempotent (IF NOT EXISTS): several Passenger processes may start at once.
        with db.open_db(self.path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
                conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {index}; COMMIT;")
        self._migrated = True

    # --- favourite stations ---------------------------------------------------------------------

    def favorite_stations(self, user_id: int) -> list[tuple[str, str]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT station_id, name FROM favorite_stations WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return [(r["station_id"], r["name"]) for r in rows]

    def is_favorite_station(self, user_id: int, station_id: str) -> bool:
        with self._db() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM favorite_stations WHERE user_id = ? AND station_id = ?",
                    (user_id, station_id),
                ).fetchone()
                is not None
            )

    def add_favorite_station(self, user_id: int, station_id: str, name: str) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO favorite_stations VALUES (?, ?, ?, ?)",
                (user_id, station_id, name, time.time()),
            )

    def remove_favorite_station(self, user_id: int, station_id: str) -> None:
        with self._db() as conn:
            conn.execute("DELETE FROM favorite_stations WHERE user_id = ? AND station_id = ?", (user_id, station_id))

    # --- favourite routes -----------------------------------------------------------------------

    def favorite_routes(self, user_id: int) -> list[FavoriteRoute]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM favorite_routes WHERE user_id = ? ORDER BY created_at", (user_id,)
            ).fetchall()
        return [FavoriteRoute(r["id"], r["from_id"], r["from_name"], r["to_id"], r["to_name"]) for r in rows]

    def favorite_route(self, user_id: int, route_id: int) -> FavoriteRoute | None:
        return next((r for r in self.favorite_routes(user_id) if r.id == route_id), None)

    def find_favorite_route(self, user_id: int, from_id: str, to_id: str) -> FavoriteRoute | None:
        return next((r for r in self.favorite_routes(user_id) if (r.from_id, r.to_id) == (from_id, to_id)), None)

    def add_favorite_route(self, user_id: int, from_id: str, from_name: str, to_id: str, to_name: str) -> int:
        with self._db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO favorite_routes (user_id, from_id, from_name, to_id, to_name, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, from_id, from_name, to_id, to_name, time.time()),
            )
            row = conn.execute(
                "SELECT id FROM favorite_routes WHERE user_id = ? AND from_id = ? AND to_id = ?",
                (user_id, from_id, to_id),
            ).fetchone()
        return row["id"]

    def remove_favorite_route(self, user_id: int, route_id: int) -> None:
        with self._db() as conn:
            conn.execute("DELETE FROM favorite_routes WHERE user_id = ? AND id = ?", (user_id, route_id))

    # --- conversation state ---------------------------------------------------------------------

    def set_state(self, user_id: int, state: str, data: dict[str, Any] | None = None) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_state VALUES (?, ?, ?, ?)",
                (user_id, state, json.dumps(data or {}, ensure_ascii=False), time.time()),
            )

    def get_state(self, user_id: int) -> tuple[str, dict[str, Any]] | None:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM user_state WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or time.time() - row["updated_at"] > STATE_TTL:
            return None
        return row["state"], json.loads(row["data"])

    def clear_state(self, user_id: int) -> None:
        with self._db() as conn:
            conn.execute("DELETE FROM user_state WHERE user_id = ?", (user_id,))

    # --- tracked trains -------------------------------------------------------------------------

    @staticmethod
    def _watch(row: sqlite3.Row) -> Watch:
        return Watch(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            trip_id=row["trip_id"],
            service_date=date.fromisoformat(row["service_date"]),
            station_id=row["station_id"],
            label=row["label"],
            last_delay=row["last_delay"],
            last_cancelled=bool(row["last_cancelled"]),
            reminded=bool(row["reminded"]),
            expires_at=row["expires_at"],
        )

    def add_watch(
        self,
        chat_id: int,
        user_id: int,
        trip_id: str,
        service_date: date,
        station_id: str | None,
        label: str,
        expires_at: float,
        last_delay: int | None,
    ) -> int:
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO watches (chat_id, user_id, trip_id, service_date, station_id, label, last_delay,
                                     expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (chat_id, trip_id, service_date) DO UPDATE SET
                    station_id = excluded.station_id, label = excluded.label, expires_at = excluded.expires_at
                """,
                (
                    chat_id,
                    user_id,
                    trip_id,
                    service_date.isoformat(),
                    station_id,
                    label,
                    last_delay,
                    expires_at,
                    time.time(),
                ),
            )
            row = conn.execute(
                "SELECT id FROM watches WHERE chat_id = ? AND trip_id = ? AND service_date = ?",
                (chat_id, trip_id, service_date.isoformat()),
            ).fetchone()
        return row["id"]

    def watches(self, chat_id: int | None = None) -> list[Watch]:
        with self._db() as conn:
            if chat_id is None:
                rows = conn.execute("SELECT * FROM watches ORDER BY id").fetchall()
            else:
                rows = conn.execute("SELECT * FROM watches WHERE chat_id = ? ORDER BY id", (chat_id,)).fetchall()
        return [self._watch(r) for r in rows]

    def find_watch(self, chat_id: int, trip_id: str, service_date: date) -> Watch | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM watches WHERE chat_id = ? AND trip_id = ? AND service_date = ?",
                (chat_id, trip_id, service_date.isoformat()),
            ).fetchone()
        return self._watch(row) if row else None

    def update_watch(self, watch_id: int, **fields: Any) -> None:
        allowed = {"last_delay", "last_cancelled", "reminded"}
        assignments = {k: v for k, v in fields.items() if k in allowed}
        if not assignments:
            return
        sql = ", ".join(f"{k} = ?" for k in assignments)
        with self._db() as conn:
            conn.execute(f"UPDATE watches SET {sql} WHERE id = ?", (*assignments.values(), watch_id))

    def remove_watch(self, watch_id: int, chat_id: int | None = None) -> None:
        with self._db() as conn:
            if chat_id is None:
                conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
            else:
                conn.execute("DELETE FROM watches WHERE id = ? AND chat_id = ?", (watch_id, chat_id))

    # --- generic realtime cache -----------------------------------------------------------------

    def cache_get(self, key: str, max_age: float) -> Any | None:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM rt_cache WHERE key = ?", (key,)).fetchone()
        if row is None or time.time() - row["fetched_at"] > max_age:
            return None
        return json.loads(row["payload"])

    def cache_put(self, key: str, payload: Any) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO rt_cache VALUES (?, ?, ?)",
                (key, time.time(), json.dumps(payload, ensure_ascii=False)),
            )
            conn.execute("DELETE FROM rt_cache WHERE fetched_at < ?", (time.time() - 86400,))
