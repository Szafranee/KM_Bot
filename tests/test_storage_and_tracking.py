import time
from datetime import timedelta

from km_bot.bot.tracking import boarding_stop, evaluate
from km_bot.realtime.base import StopStatus, TripStatus
from km_bot.storage import Storage, Watch
from tests.conftest import DAY, at


def test_favorites_and_routes(tmp_path):
    storage = Storage(tmp_path / "app.sqlite")
    storage.add_favorite_station(1, "102", "Warszawa Śródmieście")
    storage.add_favorite_station(1, "102", "Warszawa Śródmieście")
    assert storage.favorite_stations(1) == [("102", "Warszawa Śródmieście")]
    assert storage.is_favorite_station(1, "102") and not storage.is_favorite_station(2, "102")
    storage.remove_favorite_station(1, "102")
    assert storage.favorite_stations(1) == []

    route_id = storage.add_favorite_route(1, "104", "Pruszków", "103", "Warszawa Wschodnia")
    assert storage.add_favorite_route(1, "104", "Pruszków", "103", "Warszawa Wschodnia") == route_id
    assert storage.find_favorite_route(1, "104", "103").id == route_id
    assert storage.favorite_route(2, route_id) is None
    storage.remove_favorite_route(1, route_id)
    assert storage.favorite_routes(1) == []


def test_state_expires(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "app.sqlite")
    storage.set_state(1, "route_to", {"from": "104"})
    assert storage.get_state(1) == ("route_to", {"from": "104"})
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 3600)
    assert storage.get_state(1) is None


def test_watches(tmp_path):
    storage = Storage(tmp_path / "app.sqlite")
    watch_id = storage.add_watch(10, 1, "PLK_KM_2026_1", DAY, "102", "KM R1", time.time() + 60, 0)
    assert storage.add_watch(10, 1, "PLK_KM_2026_1", DAY, "100", "KM R1", time.time() + 60, 0) == watch_id
    watch = storage.find_watch(10, "PLK_KM_2026_1", DAY)
    assert watch.station_id == "100"
    storage.update_watch(watch_id, last_delay=7, reminded=1, chat_id=999)  # unknown fields are ignored
    watch = storage.watches(10)[0]
    assert (watch.last_delay, watch.reminded, watch.chat_id) == (7, True, 10)
    storage.remove_watch(watch_id, chat_id=11)
    assert storage.watches()
    storage.remove_watch(watch_id, chat_id=10)
    assert storage.watches() == []


def test_cache(tmp_path):
    storage = Storage(tmp_path / "app.sqlite")
    storage.cache_put("k", {"a": 1})
    assert storage.cache_get("k", 60) == {"a": 1}
    assert storage.cache_get("k", -1) is None


def _watch(**overrides) -> Watch:
    values = dict(
        id=1,
        chat_id=10,
        user_id=1,
        trip_id="PLK_KM_2026_1",
        service_date=DAY,
        station_id="102",
        label="KM R1 · 91450/1",
        last_delay=0,
        last_cancelled=False,
        reminded=False,
        expires_at=time.time() + 3600,
    )
    values.update(overrides)
    return Watch(**values)


def _trip(timetable):
    trip = timetable.trips_by_number("91450", DAY)[0]
    details = timetable.trip_details(trip.trip_id, DAY)
    return details, boarding_stop(details, {"102"})


def test_delay_change_is_reported_once(timetable):
    details, boarding = _trip(timetable)
    status = TripStatus("fake", stops={0: StopStatus(departure_delay=6, passed=True), 2: StopStatus(departure_delay=6)})
    result = evaluate(_watch(), details, status, boarding, at(7, 0))
    assert len(result.messages) == 1 and "+6 min" in result.messages[0]
    assert result.updates == {"last_delay": 6}
    again = evaluate(_watch(last_delay=6), details, status, boarding, at(7, 0))
    assert again.messages == []


def test_back_on_time_message(timetable):
    details, boarding = _trip(timetable)
    status = TripStatus("fake", stops={2: StopStatus(departure_delay=0)})
    result = evaluate(_watch(last_delay=8), details, status, boarding, at(7, 0))
    assert "planowo" in result.messages[0]


def test_reminder_before_departure_includes_delay_and_platform(timetable):
    details, boarding = _trip(timetable)
    status = TripStatus("fake", stops={2: StopStatus(departure_delay=2)})
    result = evaluate(_watch(), details, status, boarding, at(8, 8))
    assert any("Za ok. 9 min" in m and "peron 1" in m and "+2 min" in m for m in result.messages)
    assert result.updates["reminded"] == 1
    early = evaluate(_watch(), details, status, boarding, at(7, 30))
    assert "reminded" not in early.updates


def test_cancellation_and_finish(timetable):
    details, boarding = _trip(timetable)
    cancelled = evaluate(_watch(), details, TripStatus("fake", cancelled=True), boarding, at(7, 0))
    assert "odwołany" in cancelled.messages[0] and cancelled.updates == {"last_cancelled": 1}
    assert (
        evaluate(_watch(last_cancelled=True), details, TripStatus("fake", cancelled=True), boarding, at(7, 0)).messages
        == []
    )
    finished = evaluate(
        _watch(), details, TripStatus("fake", stops={3: StopStatus(arrival_delay=0, passed=True)}), boarding, at(8, 30)
    )
    assert finished.finished


def test_no_realtime_still_reminds(timetable):
    details, boarding = _trip(timetable)
    result = evaluate(_watch(), details, None, boarding, at(8, 15) - timedelta(minutes=5))
    assert any("Za ok. 5 min" in m for m in result.messages)
