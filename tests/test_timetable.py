from datetime import date

from km_bot.timetable.gtfs_import import split_train_name
from km_bot.timetable.queries import TimetableRepository
from tests.conftest import DAY, SATURDAY, at


def test_only_km_and_skm_are_imported(timetable: TimetableRepository):
    assert timetable.trips_by_number("1234", DAY) == []
    assert timetable.meta()["feed_version"] == "test"
    assert set(timetable.stations()) == {"100", "101", "102", "103", "104", "105", "106", "107"}


def test_split_train_name():
    assert split_train_name("51136 Ciechan") == ("51136", "Ciechan")
    assert split_train_name("91162/3") == ("91162/3", "")


def test_departures_are_sorted_and_exclude_terminating_trains(timetable):
    departures = timetable.departures("102", at(8, 0), limit=2)
    assert [(d.trip.number, d.stop.departure.strftime("%H:%M")) for d in departures] == [
        ("99310/1", "08:10"),
        ("91450/1", "08:15"),
    ]
    # The Ciechan train terminates at Śródmieście, so it is not a departure there.
    assert all(d.trip.number != "51136" for d in timetable.departures("102", at(23, 0)))


def test_departures_paging(timetable):
    first = timetable.departures("102", at(7, 0), limit=1)
    second = timetable.departures("102", at(7, 0), limit=1, offset=1)
    assert first[0].trip.number == "99310/1"
    assert second[0].trip.number == "91450/1"


def test_after_midnight_trip_belongs_to_previous_service_day(timetable):
    departures = timetable.departures("100", at(0, 0, date(2026, 10, 10)))
    ciechan = next(d for d in departures if d.trip.number == "51136")
    assert ciechan.service_date == DAY
    assert ciechan.stop.departure == at(0, 5, SATURDAY)
    assert ciechan.trip.name == "CIECHAN"


def test_station_group_includes_secondary_platform_station(timetable):
    assert timetable.station_group("100") == ["100", "101"]
    numbers = {d.trip.number for d in timetable.departures("100", at(23, 0))}
    assert "51136" in numbers  # departs from "Warszawa Zachodnia (Peron 9)"


def test_weekend_only_trip(timetable):
    assert timetable.trips_by_number("91452", DAY) == []
    assert len(timetable.trips_by_number("91452", SATURDAY)) == 1
    assert timetable.next_run_date("91452", DAY) == SATURDAY


def test_number_lookup_matches_both_halves(timetable):
    assert timetable.trips_by_number("91451", DAY)[0].number == "91450/1"
    assert timetable.trips_by_number("91450/1", DAY)[0].number == "91450/1"


def test_connections(timetable):
    connections = timetable.connections("104", "103", at(7, 0), limit=1)
    assert [c.trip.number for c in connections] == ["91450/1"]
    con = connections[0]
    assert (con.origin.departure.strftime("%H:%M"), con.target.arrival.strftime("%H:%M")) == ("08:00", "08:20")
    # Opposite direction is served by the SKM train only.
    assert [c.trip.number for c in timetable.connections("103", "104", at(7, 0), limit=1)] == ["99310/1"]


def test_trip_details(timetable):
    trip = timetable.trips_by_number("91450", DAY)[0]
    details = timetable.trip_details(trip.trip_id, DAY)
    assert [s.station_name for s in details.stops] == [
        "Pruszków",
        "Warszawa Zachodnia",
        "Warszawa Śródmieście",
        "Warszawa Wschodnia",
    ]
    assert details.stops[1].platform == "2"
    assert details.stops[0].plk_seq == 1
    assert timetable.trip_details("missing", DAY) is None


def test_missing_database(tmp_path):
    repo = TimetableRepository(tmp_path / "none.sqlite")
    assert repo.available() is False
    assert repo.departures("1", at(8, 0)) == []
    assert repo.stations() == {}


def test_board_continues_into_the_next_day(timetable):
    numbers = [(d.trip.number, d.service_date) for d in timetable.departures("104", at(8, 30), limit=3)]
    # Friday is over at Pruszków, so Saturday's trains follow (including the weekend-only one).
    assert numbers == [("91450/1", SATURDAY), ("91452", SATURDAY)]
