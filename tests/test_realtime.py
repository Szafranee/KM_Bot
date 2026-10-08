import httpx

from km_bot.realtime.base import StopStatus, TripRequest, TripStatus
from km_bot.realtime.mkuran import MkuranProvider
from km_bot.realtime.plk import PlkProvider, plk_ids
from km_bot.realtime.service import RealtimeService
from km_bot.storage import Storage
from tests.conftest import DAY


def _details(timetable, number="91450"):
    trip = timetable.trips_by_number(number, DAY)[0]
    return timetable.trip_details(trip.trip_id, DAY)


MKURAN_FEED = {
    "timestamp": "2026-10-09T08:12:00+02:00",
    "trip_updates": [
        {
            "id": "U1",
            "trip_id": "PLK_KM_2026_1",
            "start_date": "2026-10-09",
            "agency_id": "KM",
            "numbers": ["91450", "91451"],
            "stop_times": [
                {"stop_sequence": 0, "departure": "2026-10-09T08:02:00+02:00", "confirmed": True},
                {"stop_sequence": 1, "arrival": "2026-10-09T08:13:00+02:00", "departure": "2026-10-09T08:14:00+02:00"},
                {"stop_sequence": 2, "arrival": "2026-10-09T08:19:00+02:00", "departure": "2026-10-09T08:19:30+02:00"},
                {"stop_sequence": 3, "arrival": "2026-10-09T08:24:00+02:00", "cancelled": True},
            ],
        },
        {"id": "U2", "trip_id": "PLK_IC_2026_4", "start_date": "2026-10-09", "agency_id": "IC", "numbers": ["1"]},
        {
            "id": "U3",
            "trip_id": "PLK_SKM_2026_2",
            "start_date": "2026-10-09",
            "agency_id": "SKM",
            "numbers": ["99310"],
            "cancelled": True,
            "stop_times": [],
        },
    ],
}


def mkuran(tmp_path, feed=MKURAN_FEED, counter=None) -> MkuranProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.append(request.url)
        return httpx.Response(200, json=feed, headers={"Last-Modified": "Fri, 09 Oct 2026 06:12:00 GMT"})

    return MkuranProvider(Storage(tmp_path / "app.sqlite"), transport=httpx.MockTransport(handler))


def test_mkuran_delays_are_computed_from_schedule(tmp_path, timetable):
    details = _details(timetable)
    provider = mkuran(tmp_path)
    status = provider.statuses([TripRequest(details.trip.trip_id, DAY, tuple(details.stops))])[
        (details.trip.trip_id, DAY)
    ]
    assert status.source == "mkuran" and status.started
    assert status.at(0) == StopStatus(arrival_delay=None, departure_delay=2, passed=True)
    assert status.at(1).delay == 4 and status.at(1).arrival_delay == 3
    assert status.at(3).cancelled
    assert status.current_delay() == 2  # last confirmed stop


def test_mkuran_keeps_only_km_and_skm_and_caches(tmp_path, timetable):
    calls: list = []
    provider = mkuran(tmp_path, counter=calls)
    skm = _details(timetable, "99310")
    request = TripRequest(skm.trip.trip_id, DAY, tuple(skm.stops))
    first = provider.statuses([request])
    second = provider.statuses([request])
    assert first[request.key].cancelled and second[request.key].cancelled
    assert len(calls) == 1  # second call served from the snapshot in app.sqlite
    assert provider.statuses([TripRequest("PLK_IC_2026_4", DAY, ())]) == {}
    assert provider.feed_age() is not None


PLK_TRAIN = {
    "scheduleId": 2026,
    "orderId": 1,
    "operatingDate": "2026-10-09",
    "trainStatus": "P",
    "stations": [
        {
            "stationId": 104,
            "plannedSequenceNumber": 1,
            "isConfirmed": True,
            "departureDelayMinutes": 5,
            "actualDeparture": "2026-10-09T08:05:00",
            "plannedDeparture": "2026-10-09T08:00:00",
        },
        {"stationId": 100, "plannedSequenceNumber": 2, "isConfirmed": False},
        {"stationId": 102, "plannedSequenceNumber": 3, "isConfirmed": False, "isCancelled": True},
    ],
}


def test_plk_ids():
    assert plk_ids("PLK_KM_2026_114929865") == (2026, 114929865)
    assert plk_ids("KM_900_1") is None


def test_plk_status_propagates_current_delay(tmp_path, timetable):
    details = _details(timetable)
    provider = PlkProvider(Storage(tmp_path / "app.sqlite"), "key")
    status = provider.to_status(PLK_TRAIN, TripRequest(details.trip.trip_id, DAY, tuple(details.stops)))
    assert status.at(0).passed and status.at(0).delay == 5
    assert status.at(1).delay == 5 and not status.at(1).passed  # predicted from the last confirmed station
    assert status.at(2).cancelled
    assert 3 not in status.stops  # Warszawa Wschodnia missing in the response


def test_plk_board_request_uses_station_query(tmp_path, timetable):
    details = _details(timetable)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["X-API-Key"] == "key"
        return httpx.Response(200, json={"trains": [PLK_TRAIN]})

    provider = PlkProvider(Storage(tmp_path / "app.sqlite"), "key", transport=httpx.MockTransport(handler))
    request = TripRequest(details.trip.trip_id, DAY, (details.stops[1],), ("100", "101"))
    statuses = provider.statuses([request])
    assert statuses[request.key].at(1).delay == 5
    assert seen[0].url.path == "/api/v1/operations"
    assert seen[0].url.params["stations"] == "100,101"
    provider.statuses([request])
    assert len(seen) == 1  # cached


class Failing:
    name = "failing"

    def statuses(self, requests):
        raise httpx.ConnectError("down")


class Static:
    name = "static"

    def __init__(self, result):
        self.result = result

    def statuses(self, requests):
        return self.result


def test_service_falls_back_to_next_provider():
    request = TripRequest("PLK_KM_2026_1", DAY, ())
    status = TripStatus(source="static")
    result = RealtimeService([Failing(), Static({request.key: status})]).statuses([request])
    assert result.source == "static" and result.get(request.key) is status


def test_service_reports_errors_when_everything_fails():
    result = RealtimeService([Failing()]).statuses([TripRequest("x", DAY, ())])
    assert result.error and result.source is None and result.statuses == {}


def test_service_without_requests_does_not_call_providers():
    assert RealtimeService([Failing()]).statuses([]).error is False
