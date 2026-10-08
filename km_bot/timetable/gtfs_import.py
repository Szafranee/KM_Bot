"""Downloads the Polish trains GTFS feed and imports the Koleje Mazowieckie and SKM Warszawa part of it.

Feed: https://mkuran.pl/gtfs/polish_trains.zip (built by Mikołaj Kuranowski from the PKP PLK open data API).
Only the agencies listed in ``AGENCIES`` are imported, which keeps the database small (~5k trips).
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx

from km_bot import db
from km_bot.rolling_stock.importer import expand_train_number

log = logging.getLogger(__name__)

GTFS_URL = "https://mkuran.pl/gtfs/polish_trains.zip"
AGENCIES = ("KM", "SKM")

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE stations (
    id TEXT PRIMARY KEY,           -- PKP PLK station id (GTFS parent station)
    name TEXT NOT NULL,
    lat REAL,
    lon REAL,
    departures INTEGER NOT NULL DEFAULT 0  -- number of scheduled stops (station importance)
);
CREATE TABLE routes (
    id TEXT PRIMARY KEY,
    agency TEXT NOT NULL,
    short_name TEXT NOT NULL,
    long_name TEXT,
    color TEXT,
    is_bus INTEGER NOT NULL
);
CREATE TABLE trips (
    pk INTEGER PRIMARY KEY,
    trip_id TEXT NOT NULL UNIQUE,
    route_id TEXT NOT NULL REFERENCES routes(id),
    service_id TEXT NOT NULL,
    number TEXT NOT NULL,          -- as published, e.g. 91162/3
    name TEXT,                     -- commercial name of some trains, e.g. "Ciechan"
    headsign TEXT,
    first_station TEXT,
    last_station TEXT,
    first_departure INTEGER
);
CREATE TABLE trip_numbers (number TEXT NOT NULL, trip_pk INTEGER NOT NULL);
CREATE TABLE stop_times (
    trip_pk INTEGER NOT NULL,
    seq INTEGER NOT NULL,          -- GTFS stop_sequence (used by the realtime feed)
    plk_seq INTEGER,
    station_id TEXT NOT NULL,
    arr INTEGER,                   -- seconds since the service day's midnight
    dep INTEGER,
    platform TEXT,
    track TEXT,
    pickup INTEGER NOT NULL DEFAULT 0,
    dropoff INTEGER NOT NULL DEFAULT 0,
    is_first INTEGER NOT NULL DEFAULT 0,
    is_last INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (trip_pk, seq)
);
CREATE TABLE service_dates (service_id TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY (date, service_id));
"""

INDEXES = """
CREATE INDEX stop_times_station ON stop_times (station_id, dep);
CREATE INDEX trip_numbers_number ON trip_numbers (number);
CREATE INDEX trips_service ON trips (service_id);
"""


def download_feed(target: Path, url: str = GTFS_URL, force: bool = False) -> bool:
    """Downloads the feed if it changed on the server. Returns True when a new file was saved."""
    headers = {"User-Agent": "KM_Bot/2.0"}
    if target.exists() and not force:
        modified = datetime.fromtimestamp(target.stat().st_mtime, UTC)
        headers["If-Modified-Since"] = format_datetime(modified, usegmt=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, headers=headers, timeout=120, follow_redirects=True) as response:
        if response.status_code == 304:
            log.info("GTFS feed not modified")
            return False
        response.raise_for_status()
        tmp = target.with_suffix(".part")
        with tmp.open("wb") as f:
            for chunk in response.iter_bytes(1 << 16):
                f.write(chunk)
    tmp.replace(target)
    log.info("Downloaded GTFS feed (%d bytes)", target.stat().st_size)
    return True


def split_train_name(value: str) -> tuple[str, str]:
    """'51136 Ciechan' -> ('51136', 'Ciechan'); '91162/3' -> ('91162/3', '')."""
    match = re.match(r"^\s*(\d+(?:/\d+)?)\s*(.*?)\s*$", value)
    return (match.group(1), match.group(2)) if match else (value.strip(), "")


def _read(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    if name not in zf.namelist():
        return iter(())
    return csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline=""))


def _seconds(value: str) -> int | None:
    if not value:
        return None
    h, m, s = (int(x) for x in value.split(":"))
    return h * 3600 + m * 60 + s


def import_feed(feed: Path, db_path: Path) -> dict[str, int]:
    with zipfile.ZipFile(feed) as zf, db.rebuild_db(db_path) as conn:
        conn.executescript(SCHEMA)

        feed_info = next(_read(zf, "feed_info.txt"), {})
        for key in ("feed_version", "feed_start_date", "feed_end_date"):
            conn.execute("INSERT INTO meta VALUES (?, ?)", (key, feed_info.get(key, "")))

        routes = {r["route_id"]: r for r in _read(zf, "routes.txt") if r["agency_id"] in AGENCIES}
        conn.executemany(
            "INSERT INTO routes VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    rid,
                    r["agency_id"],
                    r["route_short_name"],
                    r["route_long_name"],
                    r.get("route_color"),
                    int(r["route_type"] == "3"),
                )
                for rid, r in routes.items()
            ],
        )

        trips: dict[str, int] = {}
        services: set[str] = set()
        for pk, r in enumerate((r for r in _read(zf, "trips.txt") if r["route_id"] in routes), start=1):
            trips[r["trip_id"]] = pk
            services.add(r["service_id"])
            number, name = split_train_name(r.get("plk_train_number") or r.get("trip_short_name") or "")
            name = r.get("plk_train_name") or name
            conn.execute(
                "INSERT INTO trips (pk, trip_id, route_id, service_id, number, name, headsign)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pk, r["trip_id"], r["route_id"], r["service_id"], number, name or None, r.get("trip_headsign")),
            )
            conn.executemany(
                "INSERT INTO trip_numbers VALUES (?, ?)", [(n, pk) for n in expand_train_number(number) if n]
            )

        parent_of: dict[str, str] = {}
        station_rows: dict[str, dict[str, str]] = {}
        for r in _read(zf, "stops.txt"):
            if r.get("location_type") == "1" or not r.get("parent_station"):
                station_rows[r["stop_id"]] = r
            parent_of[r["stop_id"]] = r.get("parent_station") or r["stop_id"]

        stop_times: dict[int, list[tuple]] = defaultdict(list)
        for r in _read(zf, "stop_times.txt"):
            pk = trips.get(r["trip_id"])
            if pk is None:
                continue
            plk_seq = r.get("plk_sequence")
            stop_times[pk].append(
                (
                    pk,
                    int(r["stop_sequence"]),
                    int(plk_seq) if plk_seq else None,
                    parent_of.get(r["stop_id"], r["stop_id"]),
                    _seconds(r["arrival_time"]),
                    _seconds(r["departure_time"]),
                    r.get("platform") or None,
                    r.get("track") or None,
                    int(r.get("pickup_type") or 0),
                    int(r.get("drop_off_type") or 0),
                )
            )

        used_stations: dict[str, int] = defaultdict(int)
        for pk, rows in stop_times.items():
            rows.sort(key=lambda row: row[1])
            last = len(rows) - 1
            conn.executemany(
                "INSERT INTO stop_times VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(*row, int(i == 0), int(i == last)) for i, row in enumerate(rows)],
            )
            conn.execute(
                "UPDATE trips SET first_station = ?, last_station = ?, first_departure = ? WHERE pk = ?",
                (rows[0][3], rows[-1][3], rows[0][5], pk),
            )
            for row in rows:
                used_stations[row[3]] += 1

        for station_id, count in used_stations.items():
            r = station_rows.get(station_id, {})
            conn.execute(
                "INSERT INTO stations VALUES (?, ?, ?, ?, ?)",
                (
                    station_id,
                    r.get("stop_name") or station_id,
                    _float(r.get("stop_lat")),
                    _float(r.get("stop_lon")),
                    count,
                ),
            )

        dates = [
            (r["service_id"], r["date"])
            for r in _read(zf, "calendar_dates.txt")
            if r["service_id"] in services and r["exception_type"] == "1"
        ]
        removed = {
            (r["service_id"], r["date"])
            for r in _read(zf, "calendar_dates.txt")
            if r["service_id"] in services and r["exception_type"] == "2"
        }
        dates += _calendar_dates(_read(zf, "calendar.txt"), services, removed)
        conn.executemany("INSERT OR IGNORE INTO service_dates VALUES (?, ?)", dates)
        conn.executescript(INDEXES)
        conn.execute("INSERT INTO meta VALUES ('imported_at', datetime('now'))")
        stats = {
            "routes": len(routes),
            "trips": len(trips),
            "stations": len(used_stations),
            "dates": len(dates),
        }
    log.info("GTFS import: %s", stats)
    return stats


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _calendar_dates(rows: Iterator[dict[str, str]], services: set[str], removed: set[tuple[str, str]]):
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    for r in rows:
        if r["service_id"] not in services:
            continue
        day = date(int(r["start_date"][:4]), int(r["start_date"][4:6]), int(r["start_date"][6:]))
        end = date(int(r["end_date"][:4]), int(r["end_date"][4:6]), int(r["end_date"][6:]))
        while day <= end:
            key = (r["service_id"], day.strftime("%Y%m%d"))
            if r[weekdays[day.weekday()]] == "1" and key not in removed:
                yield key
            day += timedelta(days=1)
