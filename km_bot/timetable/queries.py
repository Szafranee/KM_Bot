"""Timetable queries on ``timetable.sqlite``."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from km_bot import db
from km_bot.config import TZ


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    lat: float | None
    lon: float | None
    departures: int


@dataclass(frozen=True)
class TripInfo:
    pk: int
    trip_id: str
    number: str
    name: str | None
    agency: str
    route: str
    is_bus: bool
    headsign: str
    first_station: str
    last_station: str
    first_departure: int | None

    @property
    def carrier(self) -> str:
        return "SKM" if self.agency == "SKM" else "KM"


@dataclass(frozen=True)
class StopTime:
    seq: int
    plk_seq: int | None
    station_id: str
    station_name: str
    arrival: datetime | None
    departure: datetime | None
    platform: str | None
    track: str | None
    pickup: int
    dropoff: int

    @property
    def time(self) -> datetime:
        return self.departure or self.arrival  # type: ignore[return-value]


@dataclass(frozen=True)
class Departure:
    trip: TripInfo
    service_date: date
    stop: StopTime
    destination_name: str


@dataclass(frozen=True)
class Connection:
    trip: TripInfo
    service_date: date
    origin: StopTime
    target: StopTime
    destination_name: str


@dataclass(frozen=True)
class TripDetails:
    trip: TripInfo
    service_date: date
    stops: list[StopTime]


def service_day_start(day: date) -> datetime:
    """GTFS times are measured from "noon minus 12 h" of the service day (correct across DST changes)."""
    return datetime.combine(day, time(12), TZ) - timedelta(hours=12)


def to_datetime(day: date, seconds: int | None) -> datetime | None:
    if seconds is None:
        return None
    return (service_day_start(day) + timedelta(seconds=seconds)).astimezone(TZ)


_TRIP_COLUMNS = """
    t.pk, t.trip_id, t.number, t.name, t.headsign, t.first_station, t.last_station, t.first_departure,
    r.agency, r.short_name AS route, r.is_bus
"""


def _trip(row: sqlite3.Row) -> TripInfo:
    return TripInfo(
        pk=row["pk"],
        trip_id=row["trip_id"],
        number=row["number"],
        name=row["name"],
        agency=row["agency"],
        route=row["route"],
        is_bus=bool(row["is_bus"]),
        headsign=row["headsign"] or "",
        first_station=row["first_station"],
        last_station=row["last_station"],
        first_departure=row["first_departure"],
    )


def _stop(row: sqlite3.Row, day: date, prefix: str = "") -> StopTime:
    return StopTime(
        seq=row[f"{prefix}seq"],
        plk_seq=row[f"{prefix}plk_seq"],
        station_id=row[f"{prefix}station_id"],
        station_name=row[f"{prefix}station_name"],
        arrival=to_datetime(day, row[f"{prefix}arr"]),
        departure=to_datetime(day, row[f"{prefix}dep"]),
        platform=row[f"{prefix}platform"],
        track=row[f"{prefix}track"],
        pickup=row[f"{prefix}pickup"],
        dropoff=row[f"{prefix}dropoff"],
    )


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


class TimetableRepository:
    def __init__(self, path: Path):
        self.path = path
        self._stations_cache: tuple[float, dict[str, Station]] | None = None

    def available(self) -> bool:
        return db.exists(self.path)

    def _conn(self):
        return db.open_db(self.path, readonly=True)

    # --- stations -------------------------------------------------------------------------------

    def stations(self) -> dict[str, Station]:
        if not self.available():
            return {}
        mtime = self.path.stat().st_mtime
        if self._stations_cache and self._stations_cache[0] == mtime:
            return self._stations_cache[1]
        with self._conn() as conn:
            stations = {
                r["id"]: Station(r["id"], r["name"], r["lat"], r["lon"], r["departures"])
                for r in conn.execute("SELECT * FROM stations")
            }
        self._stations_cache = (mtime, stations)
        return stations

    def station(self, station_id: str) -> Station | None:
        return self.stations().get(station_id)

    def station_group(self, station_id: str) -> list[str]:
        """Ids of a station and its secondary parts ('Warszawa Zachodnia (Peron 9)')."""
        from km_bot.stations import group_name

        stations = self.stations()
        main = stations.get(station_id)
        if main is None:
            return [station_id]
        key = group_name(main.name)
        return [station_id] + [s.id for s in stations.values() if s.id != station_id and group_name(s.name) == key]

    def meta(self) -> dict[str, str]:
        if not self.available():
            return {}
        with self._conn() as conn:
            return {r["key"]: r["value"] for r in conn.execute("SELECT * FROM meta")}

    # --- departures -----------------------------------------------------------------------------

    def departures(self, station_id: str, after: datetime, limit: int = 5, offset: int = 0) -> list[Departure]:
        """Next departures from a station, counting trips of the previous service day (after midnight)."""
        if not self.available():
            return []
        after = after.astimezone(TZ)
        wanted = offset + limit
        found: list[Departure] = []
        ids = {f"s{i}": sid for i, sid in enumerate(self.station_group(station_id))}
        placeholders = ", ".join(f":{key}" for key in ids)
        with self._conn() as conn:
            for day in (after.date() - timedelta(days=1), after.date(), after.date() + timedelta(days=1)):
                min_seconds = int((after - service_day_start(day)).total_seconds())
                rows = conn.execute(
                    f"""
                    SELECT {_TRIP_COLUMNS}, st.*, s.name AS station_name, ls.name AS destination_name
                    FROM stop_times st
                    JOIN trips t ON t.pk = st.trip_pk
                    JOIN routes r ON r.id = t.route_id
                    JOIN service_dates sd ON sd.service_id = t.service_id AND sd.date = :day
                    JOIN stations s ON s.id = st.station_id
                    JOIN stations ls ON ls.id = t.last_station
                    WHERE st.station_id IN ({placeholders}) AND st.is_last = 0 AND st.pickup != 1
                      AND st.dep >= :min_seconds
                    ORDER BY st.dep LIMIT :limit
                    """,
                    {"day": _ymd(day), "min_seconds": min_seconds, "limit": wanted, **ids},
                ).fetchall()
                found.extend(Departure(_trip(r), day, _stop(r, day), r["destination_name"]) for r in rows)
        found.sort(key=lambda d: (d.stop.time, d.trip.number))
        return found[offset:wanted]

    def connections(
        self, from_id: str, to_id: str, after: datetime, limit: int = 5, offset: int = 0
    ) -> list[Connection]:
        """Direct trains from one station to another."""
        if not self.available():
            return []
        after = after.astimezone(TZ)
        wanted = offset + limit
        found: list[Connection] = []
        origin_ids = {f"o{i}": sid for i, sid in enumerate(self.station_group(from_id))}
        target_ids = {f"t{i}": sid for i, sid in enumerate(self.station_group(to_id))}
        ids = origin_ids | target_ids
        origins = ", ".join(f":{key}" for key in origin_ids)
        targets = ", ".join(f":{key}" for key in target_ids)
        with self._conn() as conn:
            for day in (after.date() - timedelta(days=1), after.date(), after.date() + timedelta(days=1)):
                min_seconds = int((after - service_day_start(day)).total_seconds())
                rows = conn.execute(
                    f"""
                    SELECT {_TRIP_COLUMNS},
                        a.seq, a.plk_seq, a.station_id, sa.name AS station_name, a.arr, a.dep, a.platform,
                        a.track, a.pickup, a.dropoff,
                        b.seq AS b_seq, b.plk_seq AS b_plk_seq, b.station_id AS b_station_id,
                        sb.name AS b_station_name, b.arr AS b_arr, b.dep AS b_dep, b.platform AS b_platform,
                        b.track AS b_track, b.pickup AS b_pickup, b.dropoff AS b_dropoff,
                        ls.name AS destination_name
                    FROM stop_times a
                    JOIN stop_times b ON b.trip_pk = a.trip_pk AND b.seq > a.seq
                    JOIN trips t ON t.pk = a.trip_pk
                    JOIN routes r ON r.id = t.route_id
                    JOIN service_dates sd ON sd.service_id = t.service_id AND sd.date = :day
                    JOIN stations sa ON sa.id = a.station_id
                    JOIN stations sb ON sb.id = b.station_id
                    JOIN stations ls ON ls.id = t.last_station
                    WHERE a.station_id IN ({origins}) AND b.station_id IN ({targets})
                      AND a.pickup != 1 AND b.dropoff != 1 AND a.dep >= :min_seconds
                    ORDER BY a.dep LIMIT :limit
                    """,
                    {"day": _ymd(day), "min_seconds": min_seconds, "limit": wanted, **ids},
                ).fetchall()
                found.extend(
                    Connection(_trip(r), day, _stop(r, day), _stop(r, day, "b_"), r["destination_name"]) for r in rows
                )
        found.sort(key=lambda c: (c.origin.time, c.trip.number))
        return found[offset:wanted]

    # --- trips ----------------------------------------------------------------------------------

    def trip_details(self, trip_id: str, service_date: date) -> TripDetails | None:
        if not self.available():
            return None
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_TRIP_COLUMNS} FROM trips t JOIN routes r ON r.id = t.route_id WHERE t.trip_id = ?",
                (trip_id,),
            ).fetchone()
            if row is None:
                return None
            stops = conn.execute(
                """
                SELECT st.*, s.name AS station_name FROM stop_times st
                JOIN stations s ON s.id = st.station_id
                WHERE st.trip_pk = ? ORDER BY st.seq
                """,
                (row["pk"],),
            ).fetchall()
        return TripDetails(_trip(row), service_date, [_stop(s, service_date) for s in stops])

    def trips_by_number(self, number: str, service_date: date) -> list[TripInfo]:
        if not self.available():
            return []
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT {_TRIP_COLUMNS} FROM trip_numbers n
                JOIN trips t ON t.pk = n.trip_pk
                JOIN routes r ON r.id = t.route_id
                JOIN service_dates sd ON sd.service_id = t.service_id AND sd.date = ?
                WHERE n.number = ? OR t.number = ?
                ORDER BY t.first_departure
                """,
                (_ymd(service_date), number, number),
            ).fetchall()
        return [_trip(r) for r in rows]

    def next_run_date(self, number: str, after: date, days: int = 14) -> date | None:
        """First date (from ``after``) on which a train with this number runs."""
        if not self.available():
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT MIN(sd.date) AS d FROM trip_numbers n
                JOIN trips t ON t.pk = n.trip_pk
                JOIN service_dates sd ON sd.service_id = t.service_id
                WHERE (n.number = ? OR t.number = ?) AND sd.date >= ? AND sd.date <= ?
                """,
                (number, number, _ymd(after), _ymd(after + timedelta(days=days))),
            ).fetchone()
        value = row["d"] if row else None
        return datetime.strptime(value, "%Y%m%d").date() if value else None
