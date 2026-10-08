"""Realtime provider based on https://mkuran.pl/gtfs/polish_trains/updates.json (CC BY 4.0).

The feed covers every train in Poland (~47 MB of JSON, ~4 MB gzipped). It is streamed with ``ijson`` and
only KM/SKM trips are stored in ``app.sqlite``, so memory use stays low on shared hosting. The snapshot is
refreshed at most once per ``max_age`` seconds, shared by all bot processes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
import ijson

from km_bot import db
from km_bot.config import TZ
from km_bot.realtime.base import StopStatus, TripKey, TripRequest, TripStatus, delay_minutes
from km_bot.storage import Storage

log = logging.getLogger(__name__)

UPDATES_URL = "https://mkuran.pl/gtfs/polish_trains/updates.json"
META_KEY = "mkuran:meta"


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(TZ) if value else None


class MkuranProvider:
    name = "mkuran"

    def __init__(
        self,
        storage: Storage,
        url: str = UPDATES_URL,
        max_age: float = 60,
        agencies: tuple[str, ...] = ("KM", "SKM"),
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
    ):
        self.storage = storage
        self.url = url
        self.max_age = max_age
        self.agencies = agencies
        self.timeout = timeout
        self.transport = transport

    # --- snapshot management --------------------------------------------------------------------

    def _meta(self, conn: sqlite3.Connection) -> dict | None:
        row = conn.execute("SELECT fetched_at, payload FROM rt_cache WHERE key = ?", (META_KEY,)).fetchone()
        if row is None:
            return None
        return {"fetched_at": row["fetched_at"], **json.loads(row["payload"])}

    def refresh_if_stale(self) -> None:
        self.storage.migrate()
        with db.open_db(self.storage.path) as conn:
            meta = self._meta(conn)
            if meta and time.time() - meta["fetched_at"] < self.max_age:
                return
        conn = db.connect(self.storage.path)
        try:
            conn.execute("BEGIN IMMEDIATE")  # one process downloads, the others wait and reuse the result
            meta = self._meta(conn)
            if meta and time.time() - meta["fetched_at"] < self.max_age:
                conn.rollback()
                return
            trips, last_modified = self._download()
            conn.execute("DELETE FROM rt_trips")
            conn.executemany("INSERT OR REPLACE INTO rt_trips VALUES (?, ?, ?)", trips)
            conn.execute(
                "INSERT OR REPLACE INTO rt_cache VALUES (?, ?, ?)",
                (META_KEY, time.time(), json.dumps({"last_modified": last_modified, "trips": len(trips)})),
            )
            conn.commit()
            log.info("mkuran realtime refreshed: %d trips", len(trips))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _download(self) -> tuple[list[tuple[str, str, str]], float | None]:
        trips: list[tuple[str, str, str]] = []
        items = ijson.sendable_list()
        coro = ijson.items_coro(items, "trip_updates.item", use_float=True)
        headers = {"User-Agent": "KM_Bot/2.0", "Accept-Encoding": "gzip"}
        with (
            httpx.Client(transport=self.transport, timeout=self.timeout) as client,
            client.stream("GET", self.url, headers=headers) as response,
        ):
            response.raise_for_status()
            last_modified = response.headers.get("last-modified")
            for chunk in response.iter_bytes(1 << 16):
                coro.send(chunk)
                for item in items:
                    if item.get("agency_id") in self.agencies:
                        trips.append((item["trip_id"], item["start_date"], json.dumps(item, separators=(",", ":"))))
                del items[:]
        coro.close()
        modified = parsedate_to_datetime(last_modified).timestamp() if last_modified else None
        return trips, modified

    def feed_age(self) -> float | None:
        """Seconds since the upstream feed was last updated (None if unknown)."""
        with db.open_db(self.storage.path) as conn:
            meta = self._meta(conn)
        if not meta or not meta.get("last_modified"):
            return None
        return time.time() - meta["last_modified"]

    # --- statuses -------------------------------------------------------------------------------

    def statuses(self, requests: list[TripRequest]) -> dict[TripKey, TripStatus]:
        if not requests:
            return {}
        self.refresh_if_stale()
        keys = {(r.trip_id, r.service_date.isoformat()) for r in requests}
        payloads: dict[tuple[str, str], dict] = {}
        with db.open_db(self.storage.path) as conn:
            for trip_id, start_date in keys:
                row = conn.execute(
                    "SELECT payload FROM rt_trips WHERE trip_id = ? AND start_date = ?", (trip_id, start_date)
                ).fetchone()
                if row:
                    payloads[(trip_id, start_date)] = json.loads(row["payload"])
            meta = self._meta(conn)
        updated_at = datetime.fromtimestamp(meta["fetched_at"], TZ) if meta else None

        result: dict[TripKey, TripStatus] = {}
        for request in requests:
            payload = payloads.get((request.trip_id, request.service_date.isoformat()))
            if payload is None:
                continue
            result[request.key] = self.to_status(payload, request, updated_at)
        return result

    def to_status(self, payload: dict, request: TripRequest, updated_at: datetime | None) -> TripStatus:
        by_seq = {int(s["stop_sequence"]): s for s in payload.get("stop_times") or []}
        status = TripStatus(source=self.name, cancelled=bool(payload.get("cancelled")), updated_at=updated_at)
        for stop in request.stops:
            live = by_seq.get(stop.seq)
            if live is None:
                continue
            status.stops[stop.seq] = StopStatus(
                arrival_delay=delay_minutes(_parse_dt(live.get("arrival")), stop.arrival),
                departure_delay=delay_minutes(_parse_dt(live.get("departure")), stop.departure),
                cancelled=bool(live.get("cancelled")),
                passed=bool(live.get("confirmed")),
            )
        return status
