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


def test_zachodnia_and_peron_9_are_different_stations(services):
    main = views.departures_view(services, 1, "100", 0, at(23, 0)).text
    peron9 = views.departures_view(services, 1, "101", 0, at(23, 0)).text
    assert "Warszawa Zachodnia (Peron 9)" in peron9 and "51136" in peron9
    assert "51136" not in main
    matches = views.search_stations(services, "zachodnia peron 9")
    assert matches[0].station.id == "101"
