"""Look-back rules of live boards: a train that just left, or is late, must not vanish too early."""

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from km_bot.bot import views
from km_bot.bot.board import select_visible
from km_bot.realtime.base import StopStatus, TripStatus
from km_bot.realtime.service import RealtimeResult
from km_bot.timetable.queries import StopTime
from tests.conftest import DAY, at

NOW = at(8, 12)


@dataclass
class Item:
    name: str
    stop: StopTime
    trip_id: str = "t"
    service_date: date = DAY


def item(name: str, hour: int, minute: int, seq: int = 0) -> Item:
    when = at(hour, minute)
    stop = StopTime(seq, None, "s", "Stacja", when, when, "1", "1", 0, 0)
    return Item(name, stop, trip_id=name)


def visible(items, statuses=None, now=NOW, ref=None):
    realtime = RealtimeResult(statuses or {})
    result = select_visible(items, lambda i: i.stop, lambda i: (i.trip_id, i.service_date), realtime, ref or now, now)
    return [(i.name, left) for i, left in result]


def status(delay=None, passed=False, cancelled=False, trip_cancelled=False) -> TripStatus:
    stop = StopStatus(departure_delay=delay, passed=passed, cancelled=cancelled)
    return TripStatus("fake", cancelled=trip_cancelled, stops={0: stop})


def test_just_departed_train_stays_for_a_few_minutes_and_is_flagged():
    items = [item("a", 8, 10), item("b", 8, 15)]
    assert visible(items) == [("a", True), ("b", False)]  # 2 min ago: kept, flagged as left by schedule


def test_older_than_the_buffer_is_dropped():
    items = [item("old", 8, 8), item("next", 8, 15)]
    assert visible(items) == [("next", False)]  # 4 min ago with a train due in 3 min: buffer is 3 min


def test_buffer_grows_when_the_next_train_is_far_away():
    items = [item("a", 8, 10), item("far", 9, 0)]
    assert visible(items, now=at(8, 14)) == [("a", True), ("far", False)]  # 4 min ago, next in 46 min
    assert visible(items, now=at(8, 16)) == [("far", False)]  # 6 min ago is too long even then


def test_delayed_train_is_kept_until_its_expected_departure():
    items = [item("late", 8, 6), item("next", 8, 20)]
    delayed = {("late", DAY): status(delay=6)}
    assert visible(items, delayed, now=at(8, 12)) == [("late", False), ("next", False)]  # expected 08:12
    assert visible(items, delayed, now=at(8, 14)) == [("late", True), ("next", False)]  # delays are imprecise: buffer
    assert visible(items, delayed, now=at(8, 16)) == [("next", False)]


def test_buffer_is_measured_from_a_custom_start_time():
    items = [item("a", 17, 28), item("b", 17, 40)]
    assert visible(items, now=at(8, 0), ref=at(17, 30)) == [("a", False), ("b", False)]
    assert visible(items, now=at(8, 0), ref=at(17, 33)) == [("b", False)]


def test_reported_zero_delay_is_not_trusted_blindly():
    items = [item("a", 8, 10), item("next", 8, 20)]
    on_time = {("a", DAY): status(delay=0)}
    assert visible(items, on_time) == [("a", True), ("next", False)]  # the portal also misses some delays


def test_train_confirmed_as_gone_is_dropped_at_once():
    items = [item("a", 8, 10), item("next", 8, 20)]
    gone = {("a", DAY): status(delay=1, passed=True)}  # expected departure 08:11, now 08:12
    assert visible(items, gone) == [("next", False)]


def test_cancelled_trains_are_not_kept_by_the_buffer():
    items = [item("a", 8, 10), item("b", 8, 14)]
    cancelled = {("a", DAY): status(cancelled=True), ("b", DAY): status(trip_cancelled=True)}
    assert visible(items, cancelled) == [("b", False)]  # b is still in the future, a is past and cancelled


@pytest.mark.parametrize("minutes_ago", [0, 2, 3])
def test_trains_due_now_are_never_flagged(minutes_ago):
    now = NOW
    when = now - timedelta(minutes=minutes_ago)
    items = [item("x", when.hour, when.minute)]
    flagged = dict(visible(items, now=now))["x"]
    assert flagged == (minutes_ago > 0)


# --- through the views --------------------------------------------------------------------------


def test_board_shows_the_train_that_just_left(services):
    text = views.departures_view(services, 1, "102", 0, at(8, 12)).text
    assert "08:10" in text and views.LEFT_TEXT in text  # SKM S1 99310/1 left Śródmieście at 08:10
    assert "08:15" in text


def test_board_drops_it_after_the_buffer(services):
    text = views.departures_view(services, 1, "102", 0, at(8, 14)).text
    assert "1. 08:15" in text and views.LEFT_TEXT not in text  # the next 08:10 is tomorrow's


def test_reported_delay_replaces_the_left_note(services, fake_realtime):
    trip = services.timetable.trips_by_number("99310", DAY)[0]
    fake_realtime.statuses_by_key[(trip.trip_id, DAY)] = TripStatus("fake", stops={1: StopStatus(departure_delay=5)})
    text = views.departures_view(services, 1, "102", 0, at(8, 14)).text
    assert "08:10" in text and "+5 min" in text and views.LEFT_TEXT not in text  # expected 08:15


def test_custom_start_time_has_the_buffer_too(services):
    text = views.departures_view(services, 1, "102", 0, at(8, 12), at(8, 12)).text
    assert "08:10" in text and "08:15" in text


def test_paging_is_consistent_with_the_look_back(services):
    first = views.departures_view(services, 1, "102", 0, at(8, 12)).text
    second = views.departures_view(services, 1, "102", views.PAGE_SIZE, at(8, 12)).text
    assert "1. 08:10" in first
    assert "08:10" not in second


def test_connections_use_the_same_look_back(services):
    text = views.connections_view(services, 1, "104", "103", 0, at(8, 3)).text
    assert "08:00" in text and views.LEFT_TEXT in text  # Pruszków 08:00 -> Wschodnia, 3 min ago
