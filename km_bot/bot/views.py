"""Message views (text + inline keyboard). Pure, synchronous and Telegram-transport agnostic, so they are
easy to test; handlers run them in a worker thread because they touch SQLite and the network."""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from km_bot import stations as station_search
from km_bot.bot import callbacks as cb
from km_bot.bot.services import Services
from km_bot.config import TZ
from km_bot.realtime.base import StopStatus, TripRequest, TripStatus
from km_bot.realtime.service import RealtimeResult
from km_bot.rolling_stock.repository import StockEntry
from km_bot.timetable.queries import Connection, Departure, StopTime, TripDetails, TripInfo

PAGE_SIZE = 5
WEEKDAYS = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")
NO_TIMETABLE = "⏳ Rozkład jazdy nie jest jeszcze załadowany. Spróbuj ponownie za kilka minut."


@dataclass
class View:
    text: str
    buttons: list[list[InlineKeyboardButton]] = field(default_factory=list)
    preview_url: str | None = None
    alert: str | None = None
    """Short text for answer_callback_query (toast)."""

    @property
    def markup(self) -> InlineKeyboardMarkup | None:
        return InlineKeyboardMarkup(self.buttons) if self.buttons else None


def button(text: str, *data: object) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cb.make(*data))


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def hhmm(moment: datetime | None) -> str:
    return moment.astimezone(TZ).strftime("%H:%M") if moment else "--:--"


def day_label(day: date, today: date) -> str:
    if day == today:
        prefix = "dziś"
    elif day == today + timedelta(days=1):
        prefix = "jutro"
    else:
        prefix = WEEKDAYS[day.weekday()]
    return f"{prefix} {day.day}.{day.month:02d}"


def title_case(name: str) -> str:
    return " ".join(part.capitalize() if part.isupper() else part for part in name.split())


def trip_label(trip: TripInfo) -> str:
    kind = "🚌 ZKA" if trip.is_bus else trip.carrier
    name = f" „{title_case(trip.name)}”" if trip.name else ""
    return f"{kind} {trip.route} · {trip.number}{name}"


def delay_text(
    status: StopStatus | None, trip_status: TripStatus | None, scheduled: datetime | None, now: datetime
) -> str:
    """'+3 min', 'planowo', 'odwołany' or '' when nothing useful is known."""
    if (trip_status is not None and trip_status.cancelled) or (status is not None and status.cancelled):
        return "❌ odwołany"
    if status is None or status.delay is None:
        return ""
    if status.delay >= 1:
        icon = "🔴" if status.delay >= 15 else "🟠" if status.delay >= 5 else "🟡"
        return f"{icon} +{status.delay} min"
    started = trip_status is not None and trip_status.started
    soon = scheduled is not None and scheduled - now < timedelta(minutes=45)
    return "🟢 planowo" if started or soon else ""


def platform_text(stop: StopTime) -> str:
    if not stop.platform:
        return ""
    return f"<b>peron {esc(stop.platform)}" + (f", tor {esc(stop.track)}" if stop.track else "") + "</b>"


def board_entry(
    index: int, times: str, delay: str, trip: TripInfo, stop: StopTime, destination: str, stock: str, note: str = ""
) -> list[str]:
    """One train on a board: times + delay / train + platform / direction / rolling stock.

    The platform sits right next to the train (it is what you need at the station) and the direction gets
    its own line, so the lines stay short enough not to wrap on a phone.
    """
    lines = [f"<b>{index}. {times}</b>" + (f"  <b>{delay}</b>" if delay else "")]
    train = [esc(trip_label(trip))]
    if platform := platform_text(stop):
        train.append(platform)
    elif note:
        train.append(note)
    lines.append("    " + " · ".join(train))
    lines.append(f"    → {esc(destination)}")
    if stock:
        lines.append(f"    🚆 {stock}")
    lines.append("")
    return lines


def stock_text(entries: Sequence[StockEntry]) -> str:
    if not entries:
        return ""
    labels = list(dict.fromkeys(entry.description.label for entry in entries))
    return " / ".join(esc(label) for label in labels)


def realtime_footer(result: RealtimeResult) -> str:
    if result.source_label:
        updated = ""
        statuses = list(result.statuses.values())
        if statuses and statuses[0].updated_at:
            updated = f", {hhmm(statuses[0].updated_at)}"
        return f"Opóźnienia: {esc(result.source_label)}{updated}"
    if result.error:
        return "⚠️ Opóźnienia chwilowo niedostępne"
    return "Opóźnienia: brak danych na żywo"


# --- static views --------------------------------------------------------------------------------

START_TEXT = (
    "Cześć! 👋 Jestem botem <b>Kolei Mazowieckich</b>.\n\n"
    "• Napisz <b>nazwę stacji</b> (np. <i>Śródmieście</i>, <i>Koło</i>, <i>Zachodnia</i>), a pokażę najbliższe "
    "odjazdy KM i SKM z opóźnieniami i typem taboru.\n"
    "• Napisz <b>numer pociągu</b> (np. <i>91450</i>), a powiem, jaki to skład i gdzie jest.\n"
    "• Napisz <b>trasę</b> (np. <i>Nowa Iwiczna &gt; Służewiec</i> lub <i>Koło - Wschodnia 17:30</i>), a pokażę "
    "pociągi bezpośrednie.\n"
    "• Wyślij <b>lokalizację</b>, a znajdę najbliższe stacje.\n\n"
    "Menu na dole ekranu prowadzi do ulubionych stacji, zapisanych tras i obserwowanych pociągów, "
    "a „❓ Pomoc” – do samouczka."
)

HELP_TEXT = (
    "<b>Jak korzystać z bota</b>\n\n"
    "🚉 <b>Odjazdy</b> – wpisz nazwę stacji. Skróty działają: <i>Śródmieście</i>, <i>zach</i>, <i>wwa centralna</i>, "
    "<i>lotnisko</i>. Przyciski 1–5 pokazują szczegóły kursu, ◀ ▶ przewijają listę.\n"
    "🔢 <b>Numer pociągu</b> – np. <i>91450</i> lub <i>91450/1</i>: typ taboru wg zestawienia KM, trasa i opóźnienie.\n"
    "🧭 <b>Trasy</b> – <i>Nowa Iwiczna &gt; Służewiec</i>, <i>Koło - Wschodnia 17:30</i>. Zapisz trasę ⭐, by mieć ją "
    "pod ręką w „Moje trasy”.\n"
    "⭐ <b>Ulubione</b> – stacje dodane przyciskiem ⭐ na tablicy odjazdów.\n"
    "📍 <b>Najbliższa stacja</b> – wyślij lokalizację.\n"
    "🔔 <b>Obserwowanie</b> – przycisk „Obserwuj” na karcie pociągu: dam znać o zmianie opóźnienia, odwołaniu "
    "i przypomnę ~10 min przed odjazdem.\n\n"
    "Komendy: /odjazdy &lt;stacja&gt;, /pociag &lt;numer&gt;, /trasy, /ulubione, /obserwowane, /samouczek, "
    "/info.\n\n"
    "<i>Dane: rozkład i opóźnienia PKP PLK (Otwarte Dane Kolejowe, GTFS mkuran.pl, CC BY 4.0), "
    "typ taboru z zestawień Kolei Mazowieckich.</i>"
)


def help_view() -> View:
    return View(HELP_TEXT, [[button("📖 Samouczek krok po kroku", cb.TUTORIAL, 0)]])


# --- station search ------------------------------------------------------------------------------


def search_stations(svc: Services, query: str) -> list[station_search.Match]:
    return station_search.search(query, svc.timetable.stations().values())


def station_choice_view(matches: list[station_search.Match], mode: str, query: str) -> View:
    if not matches:
        return View(
            f"🤷 Nie znalazłem stacji „{esc(query)}” obsługiwanej przez KM lub SKM.\n"
            "Spróbuj innej nazwy, np. <i>Śródmieście</i>, <i>Wschodnia</i>, <i>Otwock</i>."
        )
    prompt = {"d": "Którą stację masz na myśli?", "f": "Skąd jedziesz?", "t": "Dokąd jedziesz?"}.get(mode, "")
    return View(
        f"🔎 {prompt}",
        [[button(m.station.name, cb.PICK, m.station.id, mode)] for m in matches],
    )


def nearest_view(svc: Services, lat: float, lon: float, mode: str = "d") -> View:
    found = station_search.nearest(lat, lon, svc.timetable.stations().values(), limit=4)
    found = [(s, d) for s, d in found if not station_search.is_secondary(s.name)][:3]
    if not found:
        return View(NO_TIMETABLE)
    if found[0][1] > 30:
        return View("📍 W pobliżu nie ma stacji Kolei Mazowieckich ani SKM.")
    rows = [[button(f"📍 {s.name} ({d:.1f} km)", cb.PICK, s.id, mode)] for s, d in found]
    return View("📍 Najbliższe stacje:", rows)


# --- departures board ----------------------------------------------------------------------------


def _board_requests(items: Sequence[Departure | Connection], station_ids: tuple[str, ...]) -> list[TripRequest]:
    requests = []
    for item in items:
        stops = (item.stop,) if isinstance(item, Departure) else (item.origin, item.target)
        requests.append(TripRequest(item.trip.trip_id, item.service_date, stops, station_ids))
    return requests


def departures_view(
    svc: Services, user_id: int, station_id: str, offset: int, now: datetime, at: datetime | None = None
) -> View:
    station = svc.timetable.station(station_id)
    if station is None:
        return View(NO_TIMETABLE if not svc.timetable.available() else "Ta stacja nie jest już dostępna.")
    offset = max(offset, 0)
    departures = svc.timetable.departures(station_id, at or now, limit=PAGE_SIZE, offset=offset)
    at_arg = cb.encode_at(at)
    group = tuple(svc.timetable.station_group(station_id))
    realtime = svc.realtime.statuses(_board_requests(departures, group))

    lines = [f"🚉 <b>{esc(station.name)}</b>", f"<i>Odjazdy KM i SKM{_since(at, now)} · stan na {hhmm(now)}</i>", ""]
    if not departures:
        lines.append("Brak odjazdów w najbliższym czasie.")
    for index, dep in enumerate(departures, start=1):
        status = realtime.get((dep.trip.trip_id, dep.service_date))
        stop_status = status.at(dep.stop.seq) if status else None
        delay = delay_text(stop_status, status, dep.stop.departure, now)
        day = "" if dep.stop.time.date() == now.date() else f" ({day_label(dep.stop.time.date(), now.date())})"
        note = esc(dep.stop.station_name) if dep.stop.station_id != station_id else ""
        lines += board_entry(
            index,
            f"{hhmm(dep.stop.departure)}{day}",
            delay,
            dep.trip,
            dep.stop,
            dep.destination_name,
            stock_text(svc.stock_for_trip(dep.trip, dep.service_date)),
            note,
        )
    lines.append(f"<i>{realtime_footer(realtime)}</i>")

    back = cb.back_departures(station_id, offset, at_arg)
    rows = _number_buttons(
        [(dep.trip.trip_id, dep.service_date, hhmm(dep.stop.departure)) for dep in departures],
        station_id,
        back,
    )
    nav = []
    if offset > 0:
        nav.append(button("◀ Wcześniej", cb.DEPARTURES, station_id, max(offset - PAGE_SIZE, 0), at_arg))
    nav.append(button("🔄 Odśwież", cb.DEPARTURES, station_id, offset, at_arg))
    if departures:
        nav.append(button("Później ▶", cb.DEPARTURES, station_id, offset + PAGE_SIZE, at_arg))
    rows.append(nav)
    favorite = svc.storage.is_favorite_station(user_id, station_id)
    rows.append(
        [
            button("★ Usuń z ulubionych", cb.FAV_DEL, station_id, "b")
            if favorite
            else button("⭐ Do ulubionych", cb.FAV_ADD, station_id),
            button("🧭 Trasa stąd", cb.ROUTE_FROM_HERE, station_id),
        ]
    )
    return View("\n".join(lines), rows)


def _since(at: datetime | None, now: datetime) -> str:
    return f" od {day_label(at.date(), now.date())} {hhmm(at)}" if at else ""


def _number_buttons(items: list[tuple[str, date, str]], station_id: str | None, back: str):
    buttons = [
        InlineKeyboardButton(
            f"{index}. {label}",
            callback_data=cb.make_lenient(cb.TRIP, cb.encode_trip(trip_id), cb.encode_date(day), station_id, back),
        )
        for index, (trip_id, day, label) in enumerate(items, start=1)
    ]
    return [buttons[:3], buttons[3:]] if len(buttons) > 3 else [buttons] if buttons else []


# --- connections (A -> B) ------------------------------------------------------------------------


def connections_view(
    svc: Services,
    user_id: int,
    from_id: str,
    to_id: str,
    offset: int,
    now: datetime,
    route_id: int | None = None,
    at: datetime | None = None,
) -> View:
    origin, target = svc.timetable.station(from_id), svc.timetable.station(to_id)
    if origin is None or target is None:
        return View(NO_TIMETABLE if not svc.timetable.available() else "Ta trasa nie jest już dostępna.")
    offset = max(offset, 0)
    connections = svc.timetable.connections(from_id, to_id, at or now, limit=PAGE_SIZE, offset=offset)
    at_arg = cb.encode_at(at)
    realtime = svc.realtime.statuses(_board_requests(connections, tuple(svc.timetable.station_group(from_id))))

    lines = [
        f"🧭 <b>{esc(origin.name)} → {esc(target.name)}</b>",
        f"<i>Pociągi bezpośrednie KM i SKM{_since(at, now)} · stan na {hhmm(now)}</i>",
        "",
    ]
    if not connections:
        lines.append("Brak bezpośrednich połączeń w najbliższym czasie.")
    for index, con in enumerate(connections, start=1):
        status = realtime.get((con.trip.trip_id, con.service_date))
        delay = delay_text(status.at(con.origin.seq) if status else None, status, con.origin.departure, now)
        day = "" if con.origin.time.date() == now.date() else f" ({day_label(con.origin.time.date(), now.date())})"
        minutes = int((con.target.time - con.origin.time).total_seconds() // 60)
        times = f"{hhmm(con.origin.departure)} → {hhmm(con.target.arrival or con.target.departure)}{day}"
        lines += board_entry(
            index,
            f"{times} ({minutes} min)",
            delay,
            con.trip,
            con.origin,
            con.destination_name,
            stock_text(svc.stock_for_trip(con.trip, con.service_date)),
        )
    lines.append(f"<i>{realtime_footer(realtime)}</i>")

    if route_id is not None:
        back = cb.back_route(route_id, offset)

        def page(new_offset: int) -> tuple:
            return (cb.ROUTE, route_id, new_offset)
    else:
        back = cb.back_connections(from_id, to_id, offset, at_arg)

        def page(new_offset: int) -> tuple:
            return (cb.CONNECTIONS, from_id, to_id, new_offset, at_arg)

    rows = _number_buttons(
        [(c.trip.trip_id, c.service_date, hhmm(c.origin.departure)) for c in connections], from_id, back
    )
    nav = []
    if offset > 0:
        nav.append(button("◀ Wcześniej", *page(max(offset - PAGE_SIZE, 0))))
    nav.append(button("🔄 Odśwież", *page(offset)))
    if connections:
        nav.append(button("Później ▶", *page(offset + PAGE_SIZE)))
    rows.append(nav)
    saved = svc.storage.find_favorite_route(user_id, from_id, to_id)
    reverse = svc.storage.find_favorite_route(user_id, to_id, from_id)
    rows.append(
        [
            button("⇄ Odwrotnie", cb.ROUTE, reverse.id, 0)
            if reverse
            else button("⇄ Odwrotnie", cb.CONNECTIONS, to_id, from_id, 0),
            button("🗑 Usuń trasę", cb.ROUTE_DEL, saved.id)
            if saved
            else button("⭐ Zapisz trasę", cb.ROUTE_SAVE, from_id, to_id),
        ]
    )
    return View("\n".join(lines), rows)


def route_view(svc: Services, user_id: int, route_id: int, offset: int, now: datetime) -> View:
    route = svc.storage.favorite_route(user_id, route_id)
    if route is None:
        return View("Ta trasa została usunięta.", alert="Trasa nie istnieje")
    return connections_view(svc, user_id, route.from_id, route.to_id, offset, now, route_id=route.id)


# --- trip card -----------------------------------------------------------------------------------


def _trip_status(svc: Services, details: TripDetails) -> RealtimeResult:
    return svc.realtime.statuses([TripRequest(details.trip.trip_id, details.service_date, tuple(details.stops))])


def trip_view(
    svc: Services,
    chat_id: int,
    trip_id: str,
    service_date: date,
    station_id: str | None,
    back: str | None,
    now: datetime,
    *,
    number_mode: bool = False,
) -> View:
    details = svc.timetable.trip_details(trip_id, service_date)
    if details is None:
        return View("Ten kurs nie jest już dostępny w rozkładzie – odśwież listę.", alert="Kurs nieaktualny")
    trip = details.trip
    realtime = _trip_status(svc, details)
    status = realtime.get((trip_id, service_date))
    stops = details.stops
    first, last = stops[0], stops[-1]

    lines = [
        f"🚆 <b>{esc(trip_label(trip))}</b>",
        f"{esc(first.station_name)} → {esc(last.station_name)}",
        f"📅 {day_label(service_date, now.date())} · {hhmm(first.departure)}–{hhmm(last.arrival)}",
        "",
    ]

    stock_entries = svc.stock_for_trip(trip, service_date)
    preview = None
    if stock_entries:
        description = stock_entries[0].description
        lines.append(f"<b>Tabor:</b> {stock_text(stock_entries)}")
        if description.details:
            lines.append(f"<i>{esc(description.details)}</i>")
        preview = svc.image_url(description.image)
    elif trip.agency == "KM" and not trip.is_bus:
        coverage = svc.rolling_stock.coverage_end()
        reason = (
            "brak zestawienia KM na ten dzień"
            if coverage is None or service_date > coverage
            else "pociągu nie ma w zestawieniu KM"
        )
        lines.append(f"<b>Tabor:</b> nieznany ({reason})")

    lines.append(f"<b>Status:</b> {_status_text(status, details, now)}")
    lines.append("")

    next_seq = _next_stop_seq(status, details, now)
    highlighted = set(svc.timetable.station_group(station_id)) if station_id else set()
    for stop in stops:
        stop_status = status.at(stop.seq) if status else None
        moment = stop.departure if stop is not last else stop.arrival
        passed = stop_status.passed if stop_status else (moment is not None and moment < now - timedelta(minutes=2))
        marker = "✓" if passed else "▶" if stop.seq == next_seq else "·"
        name = esc(stop.station_name)
        if stop.station_id in highlighted:
            name = f"📍<b>{name}</b>"
        elif stop.seq == next_seq:
            name = f"<b>{name}</b>"
        extra = []
        if stop_status and stop_status.cancelled:
            extra.append("❌")
        elif stop_status and stop_status.delay:
            extra.append(f"{'+' if stop_status.delay > 0 else ''}{stop_status.delay}′")
        if stop.platform and not passed:
            extra.append(f"p. {esc(stop.platform)}")
        suffix = f"  <i>{' '.join(extra)}</i>" if extra else ""
        lines.append(f"{marker} <code>{hhmm(moment)}</code> {name}{suffix}")

    lines.append("")
    footer = [realtime_footer(realtime)]
    if stock_entries:
        entry = stock_entries[0]
        footer.append(f"tabor: zestawienie KM {_period(entry)}")
    lines.append("<i>" + " · ".join(footer) + "</i>")

    watch = svc.storage.find_watch(chat_id, trip_id, service_date)
    trip_arg, date_arg = cb.encode_trip(trip_id), cb.encode_date(service_date)
    rows = [
        [
            button("🔕 Nie obserwuj", cb.UNWATCH, watch.id, "c")
            if watch
            else InlineKeyboardButton(
                "🔔 Obserwuj", callback_data=cb.make_lenient(cb.WATCH, trip_arg, date_arg, station_id, back)
            ),
            InlineKeyboardButton(
                "🔄 Odśwież", callback_data=cb.make_lenient(cb.TRIP, trip_arg, date_arg, station_id, back)
            ),
        ]
    ]
    if number_mode:
        number = trip.number.split("/")[0]
        today = now.date()
        rows.append(
            [
                button("◀ Dzień wcześniej", cb.NUMBER, number, cb.encode_date(service_date - timedelta(days=1))),
                button("Dzień później ▶", cb.NUMBER, number, cb.encode_date(service_date + timedelta(days=1))),
            ]
        )
        if service_date != today:
            rows.append([button("📅 Dziś", cb.NUMBER, number, cb.encode_date(today))])
    if back_data := cb.back_to_callback(back):
        rows.append([InlineKeyboardButton("◀ Wróć do listy", callback_data=back_data)])
    return View("\n".join(lines), rows, preview_url=preview)


def _period(entry: StockEntry) -> str:
    start, end = entry.period_start, entry.period_end
    if start and end:
        return f"{start.day}.{start.month:02d}–{end.day}.{end.month:02d}"
    return entry.pdf_name


def _next_stop_seq(status: TripStatus | None, details: TripDetails, now: datetime) -> int | None:
    if status and status.started:
        upcoming = [s.seq for s in details.stops if not (status.at(s.seq) and status.at(s.seq).passed)]
        return upcoming[0] if upcoming else None
    first = details.stops[0]
    if first.departure and first.departure <= now <= (details.stops[-1].arrival or now):
        upcoming = [s.seq for s in details.stops if (s.departure or s.arrival) and (s.departure or s.arrival) >= now]
        return upcoming[0] if upcoming else None
    return None


def _status_text(status: TripStatus | None, details: TripDetails, now: datetime) -> str:
    first, last = details.stops[0], details.stops[-1]
    if status and status.cancelled:
        return "❌ odwołany"
    delay = status.current_delay() if status else None
    delay_part = ""
    if delay is not None:
        delay_part = f"opóźnienie <b>+{delay} min</b>" if delay > 0 else "planowo"
    last_status = status.at(last.seq) if status else None
    if last_status and last_status.passed:
        return "✅ dojechał" + (f" · {delay_part}" if delay else "")
    if status and status.started:
        return "🚆 w drodze" + (f" · {delay_part}" if delay_part else "")
    if first.departure and first.departure > now:
        minutes = int((first.departure - now).total_seconds() // 60)
        when = f"za {minutes} min" if minutes < 120 else f"o {hhmm(first.departure)}"
        return f"🕐 odjazd ze stacji początkowej {when}" + (f" · {delay_part}" if delay and delay > 0 else "")
    if last.arrival and now > last.arrival + timedelta(minutes=max(delay or 0, 0) + 5):
        return "✅ dojechał (wg rozkładu)"
    return "🚆 w drodze (wg rozkładu)" + (f" · {delay_part}" if delay_part else "")


# --- train by number ----------------------------------------------------------------------------


def number_view(svc: Services, chat_id: int, number: str, day: date, now: datetime) -> View:
    trips = svc.timetable.trips_by_number(number, day)
    if len(trips) == 1:
        return trip_view(svc, chat_id, trips[0].trip_id, day, None, None, now, number_mode=True)
    if len(trips) > 1:
        rows = [
            [
                InlineKeyboardButton(
                    f"{trip_label(t)} · {_seconds_label(t.first_departure)}",
                    callback_data=cb.make_lenient(cb.TRIP, cb.encode_trip(t.trip_id), cb.encode_date(day), None, ""),
                )
            ]
            for t in trips
        ]
        return View(f"🔢 Pociąg nr <b>{esc(number)}</b> – {day_label(day, now.date())} kursuje kilka razy:", rows)

    # Not in the GTFS timetable on that day - fall back to the PDF list (original bot behaviour).
    entries = svc.rolling_stock.lookup(number, day)
    nav = [
        [
            button("◀ Dzień wcześniej", cb.NUMBER, number, cb.encode_date(day - timedelta(days=1))),
            button("Dzień później ▶", cb.NUMBER, number, cb.encode_date(day + timedelta(days=1))),
        ]
    ]
    if entries:
        entry = entries[0]
        description = entry.description
        lines = [
            f"🚆 <b>Pociąg {esc(entry.raw_number)}</b> – {day_label(day, now.date())}",
            f"{esc(title_case(entry.origin))} {entry.departure} → {esc(title_case(entry.destination))} {entry.arrival}",
            "",
            f"<b>Tabor:</b> {stock_text(entries)}",
        ]
        if description.details:
            lines.append(f"<i>{esc(description.details)}</i>")
        lines.append(f"\n<i>Wg zestawienia KM {_period(entry)}; brak kursu w rozkładzie PLK.</i>")
        return View("\n".join(lines), nav, preview_url=svc.image_url(description.image))

    text = f"🤷 Nie znalazłem pociągu nr <b>{esc(number)}</b> kursującego {day_label(day, now.date())}."
    next_day = svc.timetable.next_run_date(number, day + timedelta(days=1))
    if next_day:
        text += f"\nNajbliższy kurs: <b>{day_label(next_day, now.date())}</b>."
        nav.insert(
            0,
            [button(f"Pokaż {day_label(next_day, now.date())}", cb.NUMBER, number, cb.encode_date(next_day))],
        )
    return View(text, nav)


def _seconds_label(seconds: int | None) -> str:
    if seconds is None:
        return ""
    hours, rest = divmod(seconds, 3600)
    return f"{hours % 24:02d}:{rest // 60:02d}"


# --- favourites, routes, watches ----------------------------------------------------------------


def favorites_view(svc: Services, user_id: int) -> View:
    favorites = svc.storage.favorite_stations(user_id)
    if not favorites:
        return View(
            "⭐ Nie masz jeszcze ulubionych stacji.\n"
            "Wpisz nazwę stacji i na tablicy odjazdów kliknij „⭐ Do ulubionych”."
        )
    rows = [[button(f"🚉 {name}", cb.DEPARTURES, sid, 0), button("✖", cb.FAV_DEL, sid, "l")] for sid, name in favorites]
    return View("⭐ <b>Ulubione stacje</b> – kliknij, aby zobaczyć odjazdy:", rows)


def routes_view(svc: Services, user_id: int) -> View:
    routes = svc.storage.favorite_routes(user_id)
    rows = [[button(f"🧭 {r.from_name} → {r.to_name}", cb.ROUTE, r.id, 0)] for r in routes]
    rows.append([button("➕ Nowa trasa", cb.MENU, "newroute")])
    if not routes:
        return View(
            "🧭 <b>Moje trasy</b>\n\nZapisz trasę, którą często jeździsz (np. <i>Nowa Iwiczna → Służewiec</i>), "
            "a zobaczysz tylko pociągi, które naprawdę tam jadą – razem z typem taboru i opóźnieniem.",
            rows,
        )
    return View("🧭 <b>Moje trasy</b>", rows)


def watches_view(svc: Services, chat_id: int, now: datetime) -> View:
    watches = svc.storage.watches(chat_id)
    if not watches:
        return View("🔔 Nie obserwujesz żadnego pociągu.\nKliknij „🔔 Obserwuj” na karcie pociągu.")
    rows = []
    for watch in watches:
        rows.append(
            [
                InlineKeyboardButton(
                    f"{day_label(watch.service_date, now.date())} · {watch.label}"[:60],
                    callback_data=cb.make_lenient(
                        cb.TRIP,
                        cb.encode_trip(watch.trip_id),
                        cb.encode_date(watch.service_date),
                        watch.station_id,
                        "",
                    ),
                ),
                button("✖", cb.UNWATCH, watch.id, "l"),
            ]
        )
    return View("🔔 <b>Obserwowane pociągi</b>", rows)


def info_view(svc: Services, now: datetime) -> View:
    meta = svc.timetable.meta()
    lines = ["ℹ️ <b>Stan danych</b>", ""]
    if meta:
        start, end = meta.get("feed_start_date", ""), meta.get("feed_end_date", "")
        lines.append(
            f"Rozkład (GTFS): {start[6:8]}.{start[4:6]}–{end[6:8]}.{end[4:6]}.{end[:4]}, "
            f"import {esc(meta.get('imported_at', '?'))} UTC"
        )
    else:
        lines.append("Rozkład: brak")
    pdfs = svc.rolling_stock.pdfs()
    if pdfs:
        lines.append("Zestawienia taboru KM:")
        lines.extend(f"• {esc(p.name)}" for p in pdfs)
    else:
        lines.append("Zestawienia taboru: brak")
    providers = ", ".join(p.name for p in svc.realtime.providers)
    lines.append(f"Źródła opóźnień: {esc(providers)}")
    lines.append(f"\n<i>{hhmm(now)}</i>")
    return View("\n".join(lines))
