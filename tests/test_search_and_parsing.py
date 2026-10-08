from datetime import date, timedelta

import pytest

from km_bot import stations as search
from km_bot.bot import callbacks as cb
from km_bot.bot.parsing import parse_query
from km_bot.timetable.queries import Station
from tests.conftest import at

STATIONS = [
    Station("1", "Warszawa Śródmieście", 52.2293, 21.0075, 1784),
    Station("2", "Warszawa Koło", 52.2461, 20.9590, 749),
    Station("3", "Zajezierze koło Dęblina", 51.54, 21.81, 63),
    Station("4", "Warszawa Zachodnia", 52.2200, 20.9652, 1970),
    Station("5", "Warszawa Zachodnia (Peron 9)", 52.2214, 20.9613, 643),
    Station("6", "Siedlce Zachodnie", 52.16, 22.26, 100),
    Station("7", "Radom Wschodni", 51.40, 21.18, 300),
    Station("8", "Radom Główny", 51.39, 21.15, 250),
    Station("9", "Radomyśl", 51.90, 22.30, 20),
    Station("10", "Mińsk Mazowiecki", 52.17, 21.56, 500),
    Station("11", "Mińsk Mazowiecki Anielina", 52.17, 21.57, 300),
    Station("12", "Warszawa Lotnisko Chopina", 52.17, 20.97, 400),
    Station("13", "Warszawa Wschodnia", 52.25, 21.05, 1975),
    Station("14", "Otwock", 52.10, 21.26, 600),
    Station("15", "Nowa Iwiczna", 52.09, 20.99, 539),
    Station("16", "Warszawa Centralna", 52.228, 21.003, 900),
]


def best(query: str) -> str | None:
    matches = search.search(query, STATIONS)
    return matches[0].station.name if matches and search.is_confident(matches) else None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Śródmieście", "Warszawa Śródmieście"),
        ("srodmiescie", "Warszawa Śródmieście"),
        ("Koło", "Warszawa Koło"),
        ("zach", "Warszawa Zachodnia"),
        ("Zachodnia", "Warszawa Zachodnia"),
        ("wwa centralna", "Warszawa Centralna"),
        ("lotnisko", "Warszawa Lotnisko Chopina"),
        ("Okęcie", "Warszawa Lotnisko Chopina"),
        ("Radom", "Radom Główny"),
        ("Mińsk", "Mińsk Mazowiecki"),
        ("iwiczna", "Nowa Iwiczna"),
        ("z Wschodniej", None),
        ("Wschodniej", "Warszawa Wschodnia"),
        ("Otwocka", "Otwock"),
    ],
)
def test_station_search(query, expected):
    assert best(query) == expected


def test_secondary_stations_are_hidden():
    assert all("Peron" not in m.station.name for m in search.search("Zachodnia", STATIONS))


def test_ambiguous_query_is_not_confident():
    assert not search.is_confident(search.search("Warszawa", STATIONS))
    assert search.search("Kraków", STATIONS) == []


def test_normalize_and_group():
    assert search.normalize("  Warszawa  Śródmieście-WKD ") == "warszawa srodmiescie wkd"
    assert search.group_name("Warszawa Zachodnia (Peron 9)") == "Warszawa Zachodnia"


def test_nearest():
    nearest = search.nearest(52.2295, 21.0080, STATIONS, limit=2)
    assert nearest[0][0].name == "Warszawa Śródmieście"
    assert nearest[0][1] < 0.1


class TestQueryParsing:
    now = at(16, 0)

    def test_numbers(self):
        for text in ("91450", "91450/1", "nr 91450", "pociąg 91450"):
            query = parse_query(text, self.now)
            assert query.kind == "number" and query.number == "91450"

    def test_routes(self):
        for text in (
            "Koło > Śródmieście",
            "Koło - Śródmieście",
            "Koło → Śródmieście",
            "Koło do Śródmieście",
            "Koło, Śródmieście",
        ):
            query = parse_query(text, self.now)
            assert (query.kind, query.origin, query.target) == ("route", "Koło", "Śródmieście")

    def test_route_with_time(self):
        query = parse_query("Koło - Wschodnia 17:30", self.now)
        assert query.at == at(17, 30)
        assert parse_query("Błonie, Pilawa, 08:01", at(7, 0)).at == at(8, 1)

    def test_time_in_the_past_means_tomorrow(self):
        query = parse_query("Śródmieście 6:30", at(23, 0))
        assert query.kind == "station" and query.at == at(6, 30) + timedelta(days=1)

    def test_hyphenated_station_is_not_a_route(self):
        assert parse_query("Skarżysko-Kamienna", self.now).kind == "station"

    def test_empty(self):
        assert parse_query("   ", self.now) is None


class TestCallbacks:
    def test_trip_roundtrip(self):
        for trip_id in ("PLK_KM_2026_114929865", "KM_900_1"):
            assert cb.decode_trip(cb.encode_trip(trip_id)) == trip_id

    def test_date_and_time_roundtrip(self):
        assert cb.decode_date(cb.encode_date(date(2026, 10, 9))) == date(2026, 10, 9)
        assert cb.decode_at(cb.encode_at(at(17, 30))) == at(17, 30)
        assert cb.decode_at("garbage") is None

    def test_length_limit(self):
        with pytest.raises(ValueError):
            cb.make("T", "x" * 70)
        data = cb.make_lenient(cb.TRIP, "PKM_2026_114929865", "20261009", "33571", "C33910.33563.10.2610091730")
        assert len(data.encode()) <= 64
        assert data.startswith("T:PKM_2026_114929865:20261009:33571")

    def test_parse_and_args(self):
        parsed = cb.parse("D:33571:5:-")
        assert parsed.action == "D" and parsed.arg(0) == "33571" and parsed.int_arg(1) == 5 and parsed.arg(2) is None
        assert cb.parse(None).action == cb.NOOP

    def test_back_targets(self):
        assert cb.back_to_callback(cb.back_departures("1", 5)) == "D:1:5"
        assert cb.back_to_callback(cb.back_connections("1", "2", 0, "2610091730")) == "C:1:2:0:2610091730"
        assert cb.back_to_callback(cb.back_route(3, 10)) == "R:3:10"
        assert cb.back_to_callback("") is None
        assert cb.back_to_callback("Zxx") is None
