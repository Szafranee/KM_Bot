"""Shared fixtures: a tiny GTFS feed, a rolling stock database and a ``Services`` container."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from pathlib import Path

import pytest

from km_bot.bot.services import Services
from km_bot.config import TZ, Settings
from km_bot.realtime.base import TripKey, TripRequest, TripStatus
from km_bot.realtime.service import RealtimeService
from km_bot.rolling_stock import importer
from km_bot.rolling_stock.dates import Period
from km_bot.rolling_stock.pdf_parser import ParsedPdf, PdfRow
from km_bot.rolling_stock.repository import RollingStockRepository
from km_bot.storage import Storage
from km_bot.timetable.gtfs_import import import_feed
from km_bot.timetable.queries import TimetableRepository

DAY = date(2026, 10, 9)  # Friday
SATURDAY = date(2026, 10, 10)


def at(hour: int, minute: int, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def _csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


STATIONS = {
    "100": ("Warszawa Zachodnia", 52.2200, 20.9652),
    "101": ("Warszawa Zachodnia (Peron 9)", 52.2214, 20.9613),
    "102": ("Warszawa Śródmieście", 52.2293, 21.0075),
    "103": ("Warszawa Wschodnia", 52.2514, 21.0522),
    "104": ("Pruszków", 52.1693, 20.8121),
    "105": ("Warszawa Koło", 52.2461, 20.9590),
    "106": ("Zajezierze koło Dęblina", 51.5421, 21.8172),
    "107": ("Radom Główny", 51.3988, 21.1529),
}


def _stop_time(trip: str, seq: int, station: str, time: str, platform: str = "1") -> dict[str, str]:
    return {
        "trip_id": trip,
        "stop_sequence": str(seq),
        "stop_id": f"{station}_RAIL_{platform}_1",
        "arrival_time": time,
        "departure_time": time,
        "pickup_type": "0",
        "drop_off_type": "0",
        "platform": platform,
        "track": "1",
        "plk_sequence": str(seq + 1),
    }


def build_gtfs(path: Path) -> Path:
    trips = [
        ("PLK_KM_2026_1", "KM_R1", "DAILY", "91450/1", "", "Warszawa Wschodnia"),
        ("PLK_SKM_2026_2", "SKM_S1", "DAILY", "99310/1", "", "Pruszków"),
        ("PLK_KM_2026_3", "KM_R9", "DAILY", "51136 Ciechan", "CIECHAN", "Warszawa Śródmieście"),
        ("PLK_IC_2026_4", "IC_EC", "DAILY", "1234", "", "Kraków"),
        ("PLK_KM_2026_5", "KM_R1", "WEEKEND", "91452", "", "Warszawa Wschodnia"),
        ("PLK_KM_2026_6", "KM_R8", "DAILY", "29404", "", "Radom Główny"),
    ]
    stop_times = [
        _stop_time("PLK_KM_2026_1", 0, "104", "08:00:00"),
        _stop_time("PLK_KM_2026_1", 1, "100", "08:10:00", "2"),
        _stop_time("PLK_KM_2026_1", 2, "102", "08:15:00", "1"),
        _stop_time("PLK_KM_2026_1", 3, "103", "08:20:00", "4"),
        _stop_time("PLK_SKM_2026_2", 0, "103", "08:05:00"),
        _stop_time("PLK_SKM_2026_2", 1, "102", "08:10:00", "3"),
        _stop_time("PLK_SKM_2026_2", 2, "100", "08:15:00", "3"),
        _stop_time("PLK_SKM_2026_2", 3, "104", "08:25:00"),
        _stop_time("PLK_KM_2026_3", 0, "105", "23:50:00"),
        _stop_time("PLK_KM_2026_3", 1, "101", "24:05:00", "9"),
        _stop_time("PLK_KM_2026_3", 2, "102", "24:10:00"),
        _stop_time("PLK_IC_2026_4", 0, "103", "08:30:00"),
        _stop_time("PLK_IC_2026_4", 1, "100", "08:40:00"),
        _stop_time("PLK_KM_2026_5", 0, "104", "09:00:00"),
        _stop_time("PLK_KM_2026_5", 1, "103", "09:20:00"),
        _stop_time("PLK_KM_2026_6", 0, "106", "10:00:00"),
        _stop_time("PLK_KM_2026_6", 1, "107", "11:00:00"),
    ]
    stops = []
    for sid, (name, lat, lon) in STATIONS.items():
        stops.append(
            {
                "stop_id": sid,
                "stop_name": name,
                "stop_lat": str(lat),
                "stop_lon": str(lon),
                "location_type": "1",
                "parent_station": "",
            }
        )
        for platform in ("1", "2", "3", "4", "9"):
            stops.append(
                {
                    "stop_id": f"{sid}_RAIL_{platform}_1",
                    "stop_name": name,
                    "stop_lat": str(lat),
                    "stop_lon": str(lon),
                    "location_type": "0",
                    "parent_station": sid,
                }
            )
    dates = [(f"202610{d:02d}", "DAILY") for d in range(8, 12)] + [("20261010", "WEEKEND")]
    files = {
        "agency.txt": _csv([{"agency_id": a, "agency_name": a} for a in ("KM", "SKM", "IC")]),
        "routes.txt": _csv(
            [
                {
                    "route_id": "KM_R1",
                    "agency_id": "KM",
                    "route_short_name": "R1",
                    "route_long_name": "",
                    "route_type": "2",
                },
                {
                    "route_id": "KM_R8",
                    "agency_id": "KM",
                    "route_short_name": "R8",
                    "route_long_name": "",
                    "route_type": "2",
                },
                {
                    "route_id": "KM_R9",
                    "agency_id": "KM",
                    "route_short_name": "RE9",
                    "route_long_name": "",
                    "route_type": "2",
                },
                {
                    "route_id": "SKM_S1",
                    "agency_id": "SKM",
                    "route_short_name": "S1",
                    "route_long_name": "",
                    "route_type": "2",
                },
                {
                    "route_id": "IC_EC",
                    "agency_id": "IC",
                    "route_short_name": "EC",
                    "route_long_name": "",
                    "route_type": "2",
                },
            ]
        ),
        "trips.txt": _csv(
            [
                {
                    "trip_id": t,
                    "route_id": r,
                    "service_id": s,
                    "trip_short_name": n,
                    "trip_headsign": h,
                    "plk_train_number": n.split()[0],
                    "plk_train_name": name,
                }
                for t, r, s, n, name, h in trips
            ]
        ),
        "stops.txt": _csv(stops),
        "stop_times.txt": _csv(stop_times),
        "calendar_dates.txt": _csv([{"date": d, "service_id": s, "exception_type": "1"} for d, s in dates]),
        "feed_info.txt": _csv([{"feed_version": "test", "feed_start_date": "20261008", "feed_end_date": "20261011"}]),
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


PDF_ROWS = [
    PdfRow("91450/1", "PRUSZKÓW", "08:00", "WARSZAWA WSCHODNIA", "08:20", "ER160", "2", "5-23 X (D)"),
    PdfRow("91450/1", "PRUSZKÓW", "08:00", "WARSZAWA WSCHODNIA", "08:20", "45WEkm", "1", "4-24 X (C)"),
    PdfRow("51136", "WARSZAWA KOŁO", "23:50", "WARSZAWA ŚRÓDMIEŚCIE", "00:10", "EU47, B, Bs", "1, 4, 1", "4-24 X"),
    PdfRow("29404", "ZAJEZIERZE", "10:00", "RADOM GŁÓWNY", "11:00", "SA135", "1", "4-24 X (Q)"),
]


def build_rolling_stock(tmp_path: Path, monkeypatch) -> Path:
    pdf = tmp_path / "pdf" / "Zestawienie pociągów KM kursujących w dniach 4-24 X 2026r..pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-fake")
    parsed = ParsedPdf(pdf.name, Period(date(2026, 10, 4), date(2026, 10, 24)), PDF_ROWS)
    monkeypatch.setattr(importer, "load_or_parse", lambda path: parsed)
    db_path = tmp_path / "rolling_stock.sqlite"
    importer.build_database([pdf], db_path, gemini=None)
    return db_path


class FakeRealtime:
    name = "fake"

    def __init__(self) -> None:
        self.statuses_by_key: dict[TripKey, TripStatus] = {}
        self.calls: list[list[TripRequest]] = []

    def statuses(self, requests: list[TripRequest]) -> dict[TripKey, TripStatus]:
        self.calls.append(requests)
        return {r.key: self.statuses_by_key[r.key] for r in requests if r.key in self.statuses_by_key}


@pytest.fixture
def gtfs_db(tmp_path: Path) -> Path:
    feed = build_gtfs(tmp_path / "feed.zip")
    db_path = tmp_path / "timetable.sqlite"
    import_feed(feed, db_path)
    return db_path


@pytest.fixture
def timetable(gtfs_db: Path) -> TimetableRepository:
    return TimetableRepository(gtfs_db)


@pytest.fixture
def fake_realtime() -> FakeRealtime:
    return FakeRealtime()


@pytest.fixture
def services(tmp_path: Path, gtfs_db: Path, monkeypatch, fake_realtime: FakeRealtime) -> Services:
    settings = Settings(
        telegram_token="123456:TEST",
        webhook_url="https://kmbot.test/telegram",
        webhook_secret="s3cret",
        public_base_url="https://kmbot.test",
        data_dir=tmp_path,
    )
    return Services(
        settings=settings,
        timetable=TimetableRepository(gtfs_db),
        rolling_stock=RollingStockRepository(build_rolling_stock(tmp_path, monkeypatch)),
        storage=Storage(tmp_path / "app.sqlite"),
        realtime=RealtimeService([fake_realtime]),
    )
