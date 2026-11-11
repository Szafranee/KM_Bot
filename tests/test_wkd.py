"""WKD: timetable import, GTFS-Realtime decoding, delays, search and labels."""

from pathlib import Path

import httpx

from km_bot import stations as search
from km_bot.bot import views
from km_bot.realtime.base import StopStatus, TripRequest, TripStatus
from km_bot.realtime.service import RealtimeResult, RealtimeService
from km_bot.realtime.wkd import WkdProvider, decode
from km_bot.storage import Storage
from tests.conftest import DAY, at

FIXTURE = Path(__file__).parent / "fixtures" / "wkd.pb"


# --- timetable ----------------------------------------------------------------------------------


def test_only_rail_trips_and_stops_are_imported(timetable):
    stations = timetable.stations()
    assert stations["WKD_wsrod"].name == "Warszawa Śródmieście WKD"
    assert "WKD_wsrod_bus_d0" not in stations  # ZKA bus stop
    assert timetable.trips_by_number("9000", DAY) == []  # ZKA trip
    [trip] = timetable.trips_by_number("1000", DAY)
    assert (trip.agency, trip.carrier, trip.trip_id, trip.is_bus) == ("WKD", "WKD", "WKD_1000_1", False)
    assert timetable.meta()["wkd_feed_version"].startswith("2026-08-22")


def test_wkd_departures_and_connections(timetable):
    departures = timetable.departures("WKD_wsrod", at(8, 0))
    assert [(d.trip.number, d.destination_name) for d in departures] == [("1000", "Grodzisk Mazowiecki Radońska")]
    [con] = timetable.connections("WKD_wsrod", "WKD_gmrad", at(8, 0))
    assert (con.origin.departure.strftime("%H:%M"), con.target.arrival.strftime("%H:%M")) == ("08:20", "09:00")
    assert timetable.connections("WKD_gmrad", "WKD_wsrod", at(8, 0))[0].trip.number == "1002"


def test_wkd_labels_and_board(services):
    view = views.departures_view(services, 1, "WKD_wsrod", 0, at(8, 0))
    assert "Warszawa Śródmieście WKD" in view.text
    assert "WKD · 1000" in view.text and "WKD WKD" not in view.text
    assert "🚆" not in view.text  # no rolling stock data for WKD
    assert all(len(b.callback_data.encode()) <= 64 for row in view.buttons for b in row)


def test_wkd_trip_card(services):
    [trip] = services.timetable.trips_by_number("1000", DAY)
    view = views.trip_view(services, 1, trip.trip_id, DAY, "WKD_wsrod", None, at(8, 0))
    assert "WKD · 1000" in view.text and "Grodzisk Mazowiecki Radońska" in view.text
    assert "Tabor:" not in view.text  # only KM publishes rolling stock lists


# --- search -------------------------------------------------------------------------------------


def test_search_finds_wkd_when_asked_for(timetable):
    stations = timetable.stations().values()
    assert search.search("Śródmieście", stations)[0].station.id == "102"  # the KM/SKM station stays the default
    wkd = search.search("Śródmieście WKD", stations)
    assert wkd[0].station.id == "WKD_wsrod" and search.is_confident(wkd)
    assert search.search("Radońska", stations)[0].station.id == "WKD_gmrad"


# --- GTFS-Realtime ------------------------------------------------------------------------------


def test_decodes_the_real_feed():
    feed = decode(FIXTURE.read_bytes())  # a snapshot of https://mkuran.pl/gtfs/wkd.pb
    assert feed["timestamp"] == 1794424818 and len(feed["trips"]) == 16
    trip = feed["trips"]["2033_3"]
    assert trip["cancelled"] is False
    assert trip["stops"]["wsrod"] == {"arr": None, "dep": 1794426000, "skipped": False}
    assert list(trip["stops"])[:3] == ["wsrod", "wocho", "wzach"]


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def field(number: int, payload: bytes | int) -> bytes:
    if isinstance(payload, int):
        return varint(number << 3) + varint(payload)
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def feed_bytes(trip_id: str, stops: dict[str, int], cancelled: bool = False) -> bytes:
    descriptor = field(1, trip_id.encode()) + (field(4, 3) if cancelled else b"")
    update = field(1, descriptor)
    for stop_id, departure in stops.items():
        event = field(2, departure)
        update += field(2, field(3, event) + field(4, stop_id.encode()))
    return field(1, field(1, b"2.0") + field(3, 1794424818)) + field(2, field(1, trip_id.encode()) + field(3, update))


def provider(tmp_path, payload: bytes, calls: list | None = None) -> WkdProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url)
        return httpx.Response(200, content=payload)

    return WkdProvider(Storage(tmp_path / "app.sqlite"), transport=httpx.MockTransport(handler))


def wkd_request(timetable, number="1000"):
    [trip] = timetable.trips_by_number(number, DAY)
    details = timetable.trip_details(trip.trip_id, DAY)
    return TripRequest(trip.trip_id, DAY, tuple(details.stops))


def test_delay_is_prediction_minus_schedule(tmp_path, timetable):
    scheduled = at(8, 20)  # wsrod 08:20, wzach 08:25
    payload = feed_bytes(
        "1000_1", {"wsrod": int(scheduled.timestamp()) + 180, "wzach": int(at(8, 25).timestamp()) + 240}
    )
    request = wkd_request(timetable)
    status = provider(tmp_path, payload).statuses([request])[request.key]
    assert status.source == "wkd" and status.updated_at is not None
    assert status.at(0).departure_delay == 3 and status.at(1).departure_delay == 4
    assert status.at(2) is None  # no prediction for Grodzisk
    assert status.current_delay() == 3


def test_prediction_for_another_day_is_ignored(tmp_path, timetable):
    payload = feed_bytes("1000_1", {"wsrod": int(at(8, 20).timestamp()) + 24 * 3600})
    request = wkd_request(timetable)
    assert provider(tmp_path, payload).statuses([request]) == {}


def test_cancelled_trip_and_cache(tmp_path, timetable):
    calls: list = []
    wkd = provider(tmp_path, feed_bytes("1000_1", {}, cancelled=True), calls)
    request = wkd_request(timetable)
    assert wkd.statuses([request])[request.key].cancelled
    wkd.statuses([request])
    assert len(calls) == 1  # served from the cache the second time
    assert wkd.statuses([wkd_request(timetable, "1002")]) == {}  # trip not in the feed


def test_non_wkd_requests_do_not_trigger_a_download(tmp_path):
    calls: list = []
    wkd = provider(tmp_path, b"", calls)
    assert wkd.statuses([TripRequest("PLK_KM_2026_1", DAY, ())]) == {}
    assert calls == []


# --- service routing ----------------------------------------------------------------------------


class Static:
    def __init__(self, name, statuses):
        self.name, self._statuses = name, statuses

    def statuses(self, requests):
        return {r.key: self._statuses[r.key] for r in requests if r.key in self._statuses}


def test_service_sends_wkd_trips_to_the_wkd_provider():
    pkp_key, wkd_key = ("PLK_KM_2026_1", DAY), ("WKD_1000_1", DAY)
    pkp = Static("plk", {pkp_key: TripStatus("plk", stops={0: StopStatus(departure_delay=2)})})
    wkd = Static("wkd", {wkd_key: TripStatus("wkd", stops={0: StopStatus(departure_delay=3)})})
    service = RealtimeService([pkp], wkd)
    result = service.statuses([TripRequest(*pkp_key, ()), TripRequest(*wkd_key, ())])
    assert set(result.statuses) == {pkp_key, wkd_key}
    assert result.source_label == "PKP PLK, WKD"
    only_wkd = service.statuses([TripRequest(*wkd_key, ())])
    assert only_wkd.source_label == "WKD" and not only_wkd.error


def test_wkd_failure_is_reported_but_does_not_break_pkp():
    class Broken:
        name = "wkd"

        def statuses(self, requests):
            raise httpx.ConnectError("down")

    pkp_key = ("PLK_KM_2026_1", DAY)
    pkp = Static("plk", {pkp_key: TripStatus("plk", stops={0: StopStatus(departure_delay=2)})})
    result = RealtimeService([pkp], Broken()).statuses([TripRequest(*pkp_key, ()), TripRequest("WKD_1_1", DAY, ())])
    assert pkp_key in result.statuses and result.error
    assert isinstance(result, RealtimeResult)
