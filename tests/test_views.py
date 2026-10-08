from km_bot.bot import callbacks as cb
from km_bot.bot import views
from km_bot.realtime.base import StopStatus, TripStatus
from tests.conftest import DAY, SATURDAY, at


def _texts(view) -> list[str]:
    return [button.text for row in view.buttons for button in row]


def _data(view) -> list[str]:
    return [button.callback_data for row in view.buttons for button in row]


def test_departures_board(services, fake_realtime):
    trip = services.timetable.trips_by_number("91450", DAY)[0]
    fake_realtime.statuses_by_key[(trip.trip_id, DAY)] = TripStatus(
        "fake", stops={2: StopStatus(departure_delay=6), 0: StopStatus(departure_delay=6, passed=True)}
    )
    view = views.departures_view(services, 1, "102", 0, at(8, 0))
    assert "Warszawa Śródmieście" in view.text
    assert "SKM S1 · 99310/1" in view.text and "KM R1 · 91450/1" in view.text
    assert "🟠 +6 min" in view.text
    assert "🚆 2× Flirt 3" in view.text  # Friday -> (D) row of the PDF
    assert "peron 1" in view.text
    assert all(len(d.encode()) <= 64 for d in _data(view))
    assert "⭐ Do ulubionych" in _texts(view)
    # The fake provider received one request per departure with the board station group.
    assert {r.station_ids for r in fake_realtime.calls[-1]} == {("102",)}


def test_board_marks_favourite_and_paging(services):
    services.storage.add_favorite_station(1, "102", "Warszawa Śródmieście")
    view = views.departures_view(services, 1, "102", 5, at(8, 0))
    assert "★ Usuń z ulubionych" in _texts(view)
    assert "◀ Wcześniej" in _texts(view)


def test_board_with_custom_time_keeps_it_in_buttons(services):
    view = views.departures_view(services, 1, "102", 0, at(7, 0), at(8, 12))
    assert "od dziś 9.10 08:12" in view.text
    assert "D:102:5:2610090812" in _data(view)


def test_unknown_station(services):
    assert "nie jest już dostępna" in views.departures_view(services, 1, "999", 0, at(8, 0)).text


def test_connections_and_route_saving(services):
    view = views.connections_view(services, 1, "104", "103", 0, at(7, 0))
    assert "Pruszków → Warszawa Wschodnia" in view.text
    assert "08:00 → 08:20" in view.text and "(20 min)" in view.text
    assert cb.make(cb.ROUTE_SAVE, "104", "103") in _data(view)

    route_id = services.storage.add_favorite_route(1, "104", "Pruszków", "103", "Warszawa Wschodnia")
    saved = views.route_view(services, 1, route_id, 0, at(7, 0))
    assert cb.make(cb.ROUTE_DEL, route_id) in _data(saved)
    assert any(d.startswith(f"R:{route_id}:") for d in _data(saved))


def test_trip_card(services, fake_realtime):
    trip = services.timetable.trips_by_number("91450", DAY)[0]
    fake_realtime.statuses_by_key[(trip.trip_id, DAY)] = TripStatus(
        "fake", stops={0: StopStatus(departure_delay=3, passed=True), 1: StopStatus(arrival_delay=4, departure_delay=4)}
    )
    view = views.trip_view(services, 10, trip.trip_id, DAY, "102", cb.back_departures("102", 0), at(8, 5))
    assert "Tabor:</b> 2× Flirt 3" in view.text
    assert "w drodze" in view.text and "+3 min" in view.text
    assert "✓ <code>08:00</code> Pruszków" in view.text
    assert "▶ <code>08:10</code> <b>Warszawa Zachodnia</b>" in view.text
    assert "📍<b>Warszawa Śródmieście</b>" in view.text
    assert view.preview_url == "https://kmbot.test/img/flirt_3.jpg"
    assert "🔔 Obserwuj" in _texts(view) and "◀ Wróć do listy" in _texts(view)


def test_trip_card_shows_watch_state(services):
    trip = services.timetable.trips_by_number("91450", DAY)[0]
    services.storage.add_watch(10, 1, trip.trip_id, DAY, None, "x", 9e9, None)
    view = views.trip_view(services, 10, trip.trip_id, DAY, None, None, at(7, 0))
    assert "🔕 Nie obserwuj" in _texts(view)


def test_number_view(services):
    view = views.number_view(services, 10, "91451", SATURDAY, at(7, 0))
    assert "KM R1 · 91450/1" in view.text and "Impuls" in view.text  # weekend (C) row
    assert "📅 Dziś" in _texts(view)


def test_number_view_named_train(services):
    view = views.number_view(services, 10, "51136", DAY, at(7, 0))
    assert "„Ciechan”" in view.text and "EU47 + 5 wagonów piętrowych" in view.text


def test_number_not_running_suggests_next_day(services):
    view = views.number_view(services, 10, "91452", DAY, at(7, 0))
    assert "Najbliższy kurs: <b>jutro 10.10</b>" in view.text
    assert cb.make(cb.NUMBER, "91452", "20261010") in _data(view)


def test_number_unknown(services):
    assert "Nie znalazłem pociągu nr <b>55555</b>" in views.number_view(services, 10, "55555", DAY, at(7, 0)).text


def test_number_only_in_pdf(services, monkeypatch):
    monkeypatch.setattr(services.timetable, "trips_by_number", lambda number, day: [])
    view = views.number_view(services, 10, "91450", DAY, at(7, 0))
    assert "Pruszków 08:00 → Warszawa Wschodnia 08:20" in view.text
    assert "brak kursu w rozkładzie PLK" in view.text


def test_lists(services):
    assert "Nie masz jeszcze ulubionych" in views.favorites_view(services, 1).text
    services.storage.add_favorite_station(1, "102", "Warszawa Śródmieście")
    assert "🚉 Warszawa Śródmieście" in _texts(views.favorites_view(services, 1))
    assert "➕ Nowa trasa" in _texts(views.routes_view(services, 1))
    assert "Nie obserwujesz" in views.watches_view(services, 10, at(7, 0)).text


def test_station_choice_and_nearest(services):
    matches = views.search_stations(services, "Warszawa")
    choice = views.station_choice_view(matches, "f", "Warszawa")
    assert "Skąd jedziesz?" in choice.text and all(d.endswith(":f") for d in _data(choice))
    assert "Nie znalazłem stacji" in views.station_choice_view([], "d", "Kraków").text
    nearest = views.nearest_view(services, 52.2295, 21.0080)
    assert _texts(nearest)[0].startswith("📍 Warszawa Śródmieście")
    assert "W pobliżu nie ma" in views.nearest_view(services, 54.35, 18.65).text


def test_info(services):
    text = views.info_view(services, at(7, 0)).text
    assert "Zestawienia taboru KM" in text and "fake" in text
