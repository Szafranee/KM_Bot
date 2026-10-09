"""Built-in step-by-step tutorial ("Samouczek"), so new users do not need a manual explanation.

Pages are edited in place (``H:<page>``). Pages with a demo have a "Wypróbuj" button (``HX:<demo>``) that sends
a real result as a new message, leaving the tutorial where it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from km_bot import stations as station_search
from km_bot.bot import callbacks as cb
from km_bot.bot import views
from km_bot.bot.services import Services
from km_bot.bot.views import View, button

DEMO_STATION = "Śródmieście"
DEMO_ROUTE = ("Zachodnia", "Wschodnia")


@dataclass(frozen=True)
class Page:
    title: str
    text: str
    demo: str | None = None
    demo_label: str = ""


PAGES: tuple[Page, ...] = (
    Page(
        "🚉 Odjazdy ze stacji",
        "Napisz po prostu <b>nazwę stacji</b> – bez komend. Działają skróty i potoczne nazwy:\n"
        "• <i>Śródmieście</i>, <i>Koło</i>, <i>Wschodnia</i> → stacje warszawskie\n"
        "• <i>zach</i>, <i>wwa centralna</i>, <i>lotnisko</i>, <i>Okęcie</i>\n"
        "• <i>Otwock</i>, <i>Mińsk</i>, <i>Grodzisk</i> → stacje podmiejskie\n\n"
        "Chcesz zobaczyć pociągi na później? Dopisz godzinę: <i>Śródmieście 17:30</i>.\n\n"
        "Na tablicy widać 5 najbliższych pociągów KM i SKM: godzinę, opóźnienie, kierunek, peron i typ taboru.\n"
        "Przyciski pod tablicą:\n"
        "• <b>1.–5.</b> – szczegóły pociągu,\n"
        "• <b>◀ / ▶</b> – wcześniejsze i późniejsze odjazdy, <b>🔄</b> – odświeżenie,\n"
        "• <b>⭐</b> – dodanie stacji do ulubionych, <b>🧭 Trasa stąd</b> – wybór stacji docelowej.\n\n"
        "Gdy nazwa pasuje do kilku stacji, bot pokaże listę do wyboru.",
        demo="departures",
        demo_label=f"▶ Wypróbuj: {DEMO_STATION}",
    ),
    Page(
        "🔢 Pociąg po numerze",
        "Napisz <b>numer pociągu</b>, np. <i>91450</i> albo <i>91450/1</i>. Numer znajdziesz na tablicy odjazdów "
        "w bocie, na wyświetlaczu w pociągu albo w rozkładzie KM.\n\n"
        "Karta pociągu pokazuje:\n"
        "• <b>tabor</b> – np. <i>2× Flirt 3</i> albo <i>EU47 + 6 wagonów piętrowych</i>, ze zdjęciem,\n"
        "• <b>status</b> – czy wyjechał, gdzie jest i jakie ma opóźnienie,\n"
        "• <b>całą trasę</b>: ✓ stacje już minięte, ▶ następna stacja, 📍 Twoja stacja, "
        "przy stacjach opóźnienie i peron.\n\n"
        "Przyciski <b>◀ Dzień wcześniej / Dzień później ▶</b> pokazują ten sam pociąg w inne dni – tabor potrafi "
        "się zmieniać, np. w weekendy.",
        demo="number",
        demo_label="▶ Wypróbuj: pociąg, który zaraz odjeżdża",
    ),
    Page(
        "🧭 Trasy z punktu A do B",
        "Napisz dwie stacje rozdzielone znakiem <b>&gt;</b> albo myślnikiem ze spacjami:\n"
        "• <i>Nowa Iwiczna &gt; Służewiec</i>\n"
        "• <i>Koło - Wschodnia 17:30</i> (z godziną)\n\n"
        "Bot pokaże tylko pociągi <b>bez przesiadki</b>, które naprawdę dojeżdżają do celu – z godziną odjazdu "
        "i przyjazdu, czasem jazdy, taborem i opóźnieniem. Na dużych stacjach, takich jak Śródmieście czy "
        "Zachodnia, nie trzeba się zastanawiać, który pociąg gdzie jedzie.\n\n"
        "• <b>⭐ Zapisz trasę</b> – trasa trafia do „🧭 Moje trasy” w menu,\n"
        "• <b>⇄ Odwrotnie</b> – powrót tą samą trasą.\n\n"
        "Nową trasę możesz też dodać w „🧭 Moje trasy” → „➕ Nowa trasa”.",
        demo="route",
        demo_label=f"▶ Wypróbuj: {DEMO_ROUTE[0]} > {DEMO_ROUTE[1]}",
    ),
    Page(
        "⭐ Ulubione i 📍 lokalizacja",
        "<b>Ulubione stacje</b> – na tablicy odjazdów kliknij „⭐ Do ulubionych”. Potem przycisk "
        "„⭐ Ulubione” w menu otwiera tablicę jednym kliknięciem. Znak ✖ obok stacji ją usuwa.\n\n"
        "<b>Najbliższa stacja</b> – kliknij „📍 Najbliższa stacja” w menu (na telefonie). Telegram zapyta "
        "o udostępnienie lokalizacji, a bot pokaże 3 najbliższe stacje KM i SKM z odległością.\n"
        "Lokalizacja przydaje się też przy dodawaniu trasy – zamiast wpisywać stację początkową.",
    ),
    Page(
        "🔔 Obserwowanie pociągu",
        "Na karcie pociągu kliknij <b>🔔 Obserwuj</b>. Bot sam napisze, gdy:\n"
        "• opóźnienie zmieni się o 3 minuty lub więcej (i gdy pociąg wróci do rozkładu),\n"
        "• pociąg zostanie <b>odwołany</b>,\n"
        "• zostanie ok. <b>10 minut do odjazdu</b> z Twojej stacji – z aktualnym peronem i opóźnieniem.\n\n"
        "Przypomnienie działa, gdy kartę otworzysz z tablicy odjazdów albo z trasy, bo wtedy bot wie, "
        "z której stacji jedziesz. Obserwowanie wyłącza się samo po dojeździe pociągu. Listę obserwowanych "
        "pociągów znajdziesz w menu „🔔 Obserwowane”.",
    ),
    Page(
        "🔤 Co oznaczają symbole",
        "<b>Opóźnienia</b>\n"
        "🟢 planowo · 🟡 +1–4 min · 🟠 +5–14 min · 🔴 15 min i więcej · ❌ odwołany\n\n"
        "<b>Trasa pociągu</b>\n"
        "✓ stacja minięta · ▶ następna stacja · 📍 Twoja stacja · <i>p. 2</i> peron\n\n"
        "<b>Oznaczenia pociągów</b>\n"
        "KM R1, RE1… – Koleje Mazowieckie (RE – przyspieszony), SKM S1… – Szybka Kolej Miejska, "
        "🚌 ZKA – autobus zastępczy.\n\n"
        "<b>Skąd są dane</b>\n"
        "• Rozkład i opóźnienia: PKP PLK. Opóźnienia odświeżają się co kilka minut, więc mogą być lekko spóźnione.\n"
        "• Tabor: zestawienia publikowane przez KM na kilka tygodni naprzód. Na dni, na które nie ma jeszcze "
        "zestawienia, bot napisze „tabor nieznany”. Dla SKM danych o taborze nie ma.",
    ),
    Page(
        "✅ To wszystko!",
        "Najważniejsze w skrócie:\n"
        "• <i>nazwa stacji</i> → odjazdy,\n"
        "• <i>numer pociągu</i> → tabor i trasa,\n"
        "• <i>stacja &gt; stacja</i> → pociągi bezpośrednie,\n"
        "• menu na dole ekranu → ulubione, trasy, lokalizacja, obserwowane.\n\n"
        "Samouczek możesz otworzyć ponownie komendą /samouczek albo przyciskiem „❓ Pomoc” w menu. "
        "Wpisanie /anuluj przerywa dodawanie trasy.",
    ),
)

TUTORIAL_INTRO = (
    "📖 <b>Samouczek</b>\n\n"
    "Krótki przewodnik po bocie – ok. 2 minuty. Możesz iść po kolei (▶) albo wybrać temat. "
    "Przyciski „▶ Wypróbuj” pokazują prawdziwy przykład w osobnej wiadomości."
)


def contents_view() -> View:
    rows = [[button(page.title, cb.TUTORIAL, index + 1)] for index, page in enumerate(PAGES)]
    rows.insert(0, [button("▶ Zacznij od początku", cb.TUTORIAL, 1)])
    return View(TUTORIAL_INTRO, rows)


def page_view(number: int) -> View:
    """Page ``number`` (1-based); 0 or out of range shows the table of contents."""
    if not 1 <= number <= len(PAGES):
        return contents_view()
    page = PAGES[number - 1]
    text = f"<b>{page.title}</b>  <i>(samouczek {number}/{len(PAGES)})</i>\n\n{page.text}"
    rows = []
    if page.demo:
        rows.append([button(page.demo_label, cb.TUTORIAL_DEMO, page.demo)])
    nav = []
    if number > 1:
        nav.append(button("◀ Wstecz", cb.TUTORIAL, number - 1))
    nav.append(button("📋 Spis", cb.TUTORIAL, 0))
    if number < len(PAGES):
        nav.append(button("Dalej ▶", cb.TUTORIAL, number + 1))
    rows.append(nav)
    return View(text, rows)


def offer_view() -> View:
    """Short invitation shown after /start."""
    return View(
        "Pierwszy raz tutaj? Zajrzyj do krótkiego samouczka – pokaże wszystko na przykładach.",
        [[button("📖 Samouczek (2 min)", cb.TUTORIAL, 0)]],
    )


def _station(svc: Services, query: str):
    matches = station_search.search(query, svc.timetable.stations().values())
    return matches[0].station if station_search.is_confident(matches) else None


def demo_view(svc: Services, demo: str, user_id: int, chat_id: int, now: datetime) -> View:
    """Real example results for the "Wypróbuj" buttons."""
    if not svc.timetable.available():
        return View(views.NO_TIMETABLE)
    if demo == "departures":
        station = _station(svc, DEMO_STATION)
        if station:
            return views.departures_view(svc, user_id, station.id, 0, now)
    elif demo == "number":
        station = _station(svc, DEMO_STATION)
        departures = svc.timetable.departures(station.id, now, limit=15) if station else []
        departure = next((d for d in departures if d.trip.agency == "KM" and not d.trip.is_bus), None)
        departure = departure or (departures[0] if departures else None)
        if departure:
            # Opened "from" the demo station, so the card shows 📍 and tracking can remind before departure.
            return views.trip_view(
                svc, chat_id, departure.trip.trip_id, departure.service_date, station.id, None, now, number_mode=True
            )
    elif demo == "route":
        origin, target = (_station(svc, name) for name in DEMO_ROUTE)
        if origin and target:
            return views.connections_view(svc, user_id, origin.id, target.id, 0, now)
    return View("Ten przykład jest teraz niedostępny – spróbuj wpisać zapytanie samodzielnie.")
