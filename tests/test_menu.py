"""Menu layout, button styles and the separate Warszawa Zachodnia (Peron 9) station."""

from km_bot.bot import views
from km_bot.bot.handlers import MAIN_KEYBOARD
from tests.conftest import at


def keyboard_texts(markup) -> list[list[str]]:
    rows = markup.keyboard
    return [[getattr(b, "text", b) for b in row] for row in rows]


def test_menu_layout_has_no_help_button_and_routes_before_numbers():
    assert keyboard_texts(MAIN_KEYBOARD) == [
        ["🚉 Odjazdy", "🧭 Moje trasy"],
        ["🔢 Numer pociągu", "⭐ Ulubione"],
        ["📍 Najbliższa stacja", "🔔 Obserwowane"],
    ]


def styles(view):
    return {b.text: b.api_kwargs.get("style") or getattr(b, "style", None) for row in view.buttons for b in row}


def test_favourite_button_names_the_action(services):
    add = views.departures_view(services, 1, "102", 0, at(8, 0))
    assert styles(add)["⭐ Dodaj do ulubionych"] is None
    services.storage.add_favorite_station(1, "102", "Warszawa Śródmieście")
    remove = views.departures_view(services, 1, "102", 0, at(8, 0))
    assert styles(remove)["🗑 Usuń z ulubionych"] == "danger"
    assert styles(views.favorites_view(services, 1))["🗑"] == "danger"


def test_zachodnia_includes_peron_9_marked_and_peron_9_alone_filters(services):
    everything = views.departures_view(services, 1, "100", 0, at(23, 0))
    assert "51136" in everything.text and "🔶 Peron 9" in everything.text and "razem z: Peron 9, WKD" in everything.text
    only = views.departures_view(services, 1, "101", 0, at(23, 0))
    assert "Warszawa Zachodnia (Peron 9)" in only.text and "51136" in only.text
    assert "Tylko peron 9" in str(everything.markup) and "Cała Zachodnia" in str(only.markup)
    assert services.timetable.station_group("101") == ["101"]  # picked alone: only its own trains


def test_peron_9_is_still_found_by_name_but_wkd_station_is_hidden(services):
    assert views.search_stations(services, "zachodnia peron 9")[0].station.id == "101"
    ids = {m.station.id for m in views.search_stations(services, "Śródmieście WKD")}
    assert "WKD_wsrod" not in ids and views.search_stations(services, "Śródmieście WKD")[0].station.id == "102"


def test_merged_station_lists_wkd_trains(services):
    text = views.departures_view(services, 1, "102", 0, at(8, 0)).text
    assert "WKD · 1000" in text and "razem z: WKD" in text
    assert services.timetable.connections("102", "WKD_gmrad", at(8, 0))  # KM/SKM station -> WKD station
