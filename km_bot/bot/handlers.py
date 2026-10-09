"""Telegram update handlers."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from telegram import (
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, NetworkError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from km_bot import stations as station_search
from km_bot.bot import callbacks as cb
from km_bot.bot import tutorial, views
from km_bot.bot.parsing import parse_query
from km_bot.bot.services import Services
from km_bot.bot.views import View
from km_bot.config import now

log = logging.getLogger(__name__)

MENU_DEPARTURES = "🚉 Odjazdy"
MENU_NUMBER = "🔢 Numer pociągu"
MENU_ROUTES = "🧭 Moje trasy"
MENU_FAVORITES = "⭐ Ulubione"
MENU_LOCATION = "📍 Najbliższa stacja"
MENU_WATCHES = "🔔 Obserwowane"
MENU_HELP = "❓ Pomoc"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [MENU_DEPARTURES, MENU_NUMBER],
        [MENU_ROUTES, MENU_FAVORITES],
        [KeyboardButton(MENU_LOCATION, request_location=True), MENU_WATCHES],
        [MENU_HELP],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Stacja, numer pociągu lub trasa A > B",
)

# Conversation states stored in app.sqlite (Passenger may run several processes, so no in-memory state).
STATE_ROUTE_FROM = "route_from"
STATE_ROUTE_TO = "route_to"
STATE_NUMBER = "number"


def services(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.application.bot_data["services"]


async def in_thread(func, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(func, *args, **kwargs)


def _preview(view: View) -> LinkPreviewOptions:
    if view.preview_url:
        return LinkPreviewOptions(url=view.preview_url, prefer_large_media=True, show_above_text=True)
    return LinkPreviewOptions(is_disabled=True)


async def reply(message: Message, view: View, *, keyboard: bool = False) -> None:
    await message.reply_text(
        view.text,
        parse_mode=ParseMode.HTML,
        reply_markup=view.markup or (MAIN_KEYBOARD if keyboard else None),
        link_preview_options=_preview(view),
    )


async def safe_answer(query, text: str | None = None, *, show_alert: bool = False) -> None:
    """Answers a callback query on a best-effort basis.

    The answer only stops the button's loading spinner (and shows an optional toast), so a slow or failed
    request must not abort the action the user asked for.
    """
    try:
        await query.answer(text, show_alert=show_alert)
    except NetworkError as exc:  # includes TimedOut
        log.warning("Could not answer callback query: %s", exc)
    except BadRequest as exc:  # e.g. "query is too old" after a slow response
        log.info("Callback query not answered: %s", exc)


async def edit(update: Update, view: View) -> None:
    query = update.callback_query
    try:
        await query.edit_message_text(
            view.text,
            parse_mode=ParseMode.HTML,
            reply_markup=view.markup,
            link_preview_options=_preview(view),
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


# --- access control ------------------------------------------------------------------------------


async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = services(context).settings.allowed_user_ids
    user = update.effective_user
    if not allowed or (user and user.id in allowed):
        return
    log.info("Rejected update from user %s", user.id if user else None)
    if update.callback_query:
        await safe_answer(update.callback_query, "Ten bot jest prywatny.", show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text("🔒 Ten bot jest prywatny.")
    raise ApplicationHandlerStop


# --- commands ------------------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await in_thread(services(context).storage.clear_state, update.effective_user.id)
    await reply(update.effective_message, View(views.START_TEXT), keyboard=True)
    await reply(update.effective_message, tutorial.offer_view())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(update.effective_message, views.help_view(), keyboard=True)


async def tutorial_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(update.effective_message, tutorial.contents_view())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await in_thread(services(context).storage.clear_state, update.effective_user.id)
    await reply(update.effective_message, View("OK, anulowane."), keyboard=True)


async def departures_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args or [])
    if not text:
        await prompt_departures(update, context)
        return
    await handle_query(update, context, text, force_station=True)


async def number_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args or [])
    if not text:
        await prompt_number(update, context)
        return
    await handle_query(update, context, text)


async def routes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    view = await in_thread(views.routes_view, services(context), update.effective_user.id)
    await reply(update.effective_message, view)


async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    view = await in_thread(views.favorites_view, services(context), update.effective_user.id)
    await reply(update.effective_message, view)


async def watches_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    view = await in_thread(views.watches_view, services(context), update.effective_chat.id, now())
    await reply(update.effective_message, view)


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    view = await in_thread(views.info_view, services(context), now())
    await reply(update.effective_message, view)


async def prompt_departures(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    svc = services(context)
    await in_thread(svc.storage.clear_state, update.effective_user.id)
    favorites = await in_thread(svc.storage.favorite_stations, update.effective_user.id)
    rows = [[views.button(f"⭐ {name}", cb.DEPARTURES, sid, 0)] for sid, name in favorites]
    await reply(
        update.effective_message,
        View("🚉 Wpisz nazwę stacji (np. <i>Śródmieście</i>, <i>Koło</i>) albo wybierz ulubioną:", rows)
        if rows
        else View("🚉 Wpisz nazwę stacji, np. <i>Śródmieście</i>, <i>Koło</i>, <i>Otwock</i>."),
    )


async def prompt_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await in_thread(services(context).storage.set_state, update.effective_user.id, STATE_NUMBER)
    await reply(update.effective_message, View("🔢 Podaj numer pociągu, np. <i>91450</i> lub <i>91450/1</i>."))


async def prompt_route_station(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, *, edit_message=False):
    """Asks for the origin ('f') or destination ('t') of a route, offering favourite stations."""
    svc = services(context)
    favorites = await in_thread(svc.storage.favorite_stations, update.effective_user.id)
    question = "Skąd jedziesz?" if mode == "f" else "Dokąd jedziesz?"
    state = await in_thread(svc.storage.get_state, update.effective_user.id)
    if mode == "t" and state and state[1].get("from_name"):
        question = f"Dokąd jedziesz z <b>{views.esc(state[1]['from_name'])}</b>?"
    rows = [[views.button(f"⭐ {name}", cb.PICK, sid, mode)] for sid, name in favorites]
    view = View(f"🧭 {question} Wpisz nazwę stacji lub wyślij lokalizację 📍.\n<i>/anuluj – przerwij</i>", rows)
    if edit_message and update.callback_query:
        await edit(update, view)
    else:
        await reply(update.effective_message, view)


# --- text and location ---------------------------------------------------------------------------


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = message.text or ""
    if update.effective_chat.type != ChatType.PRIVATE:
        mention = f"@{context.bot.username}"
        if mention.lower() not in text.lower():
            return
        text = text.replace(mention, "").replace(mention.lower(), "").strip()

    menu = {
        MENU_DEPARTURES: prompt_departures,
        MENU_NUMBER: prompt_number,
        MENU_ROUTES: routes_command,
        MENU_FAVORITES: favorites_command,
        MENU_WATCHES: watches_command,
        MENU_HELP: help_command,
    }
    if text in menu:
        await menu[text](update, context)
        return
    if text == MENU_LOCATION:  # clients without location support send the label as text
        await reply(message, View("📍 Wyślij swoją lokalizację (📎 → Lokalizacja), a znajdę najbliższe stacje."))
        return
    await handle_query(update, context, text)


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, force_station=False) -> None:
    svc = services(context)
    message = update.effective_message
    user_id = update.effective_user.id
    current = now()
    state = await in_thread(svc.storage.get_state, user_id)
    query = parse_query(text, current)
    if query is None:
        return

    if state and state[0] in (STATE_ROUTE_FROM, STATE_ROUTE_TO) and query.kind == "station" and not query.at:
        mode = "f" if state[0] == STATE_ROUTE_FROM else "t"
        await resolve_route_station(update, context, text, mode)
        return
    if state:
        # A train number or a complete route typed mid-wizard starts over instead of being a station name.
        await in_thread(svc.storage.clear_state, user_id)
    if query.kind == "number" and not force_station:
        view = await in_thread(views.number_view, svc, update.effective_chat.id, query.number, current.date(), current)
        await reply(message, view)
        return
    if query.kind == "route":
        await start_route(update, context, query.origin, query.target, query.at)
        return

    matches = await in_thread(views.search_stations, svc, query.origin or text)
    if station_search.is_confident(matches):
        view = await in_thread(views.departures_view, svc, user_id, matches[0].station.id, 0, current, query.at)
    else:
        view = views.station_choice_view(matches, "d", query.origin or text)
    await reply(message, view)


async def start_route(update: Update, context: ContextTypes.DEFAULT_TYPE, origin: str, target: str, at) -> None:
    """Resolves both ends of "A > B"; asks the user to pick a station whenever the match is ambiguous."""
    svc = services(context)
    user_id = update.effective_user.id
    origin_matches = await in_thread(views.search_stations, svc, origin)
    if not station_search.is_confident(origin_matches):
        await in_thread(svc.storage.set_state, user_id, STATE_ROUTE_FROM, {"to_query": target, "at": cb.encode_at(at)})
        await reply(update.effective_message, views.station_choice_view(origin_matches, "f", origin))
        return
    await continue_route(update, context, origin_matches[0].station, target, at, save=False)


async def continue_route(update, context, origin, target_query: str | None, at, save: bool, *, editing=False):
    svc = services(context)
    user_id = update.effective_user.id
    data = {"from": origin.id, "from_name": origin.name, "save": save, "at": cb.encode_at(at)}
    if target_query:
        matches = await in_thread(views.search_stations, svc, target_query)
        if station_search.is_confident(matches):
            await finish_route(update, context, origin.id, matches[0].station.id, at, save, editing=editing)
            return
        await in_thread(svc.storage.set_state, user_id, STATE_ROUTE_TO, data)
        view = views.station_choice_view(matches, "t", target_query)
    else:
        await in_thread(svc.storage.set_state, user_id, STATE_ROUTE_TO, data)
        await prompt_route_station(update, context, "t", edit_message=editing)
        return
    if editing:
        await edit(update, view)
    else:
        await reply(update.effective_message, view)


async def finish_route(update, context, from_id: str, to_id: str, at, save: bool, *, editing=False) -> None:
    svc = services(context)
    user_id = update.effective_user.id
    await in_thread(svc.storage.clear_state, user_id)
    if from_id == to_id:
        view = View("🤔 Stacja początkowa i końcowa są takie same.")
    elif save:
        origin, target = svc.timetable.station(from_id), svc.timetable.station(to_id)
        route_id = await in_thread(svc.storage.add_favorite_route, user_id, from_id, origin.name, to_id, target.name)
        view = await in_thread(views.route_view, svc, user_id, route_id, 0, now())
    else:
        view = await in_thread(views.connections_view, svc, user_id, from_id, to_id, 0, now(), None, at)
    if editing:
        await edit(update, view)
    else:
        await reply(update.effective_message, view)


async def resolve_route_station(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, mode: str) -> None:
    svc = services(context)
    matches = await in_thread(views.search_stations, svc, text)
    if station_search.is_confident(matches):
        await route_station_picked(update, context, matches[0].station.id, mode, editing=False)
    else:
        await reply(update.effective_message, views.station_choice_view(matches, mode, text))


async def route_station_picked(update, context, station_id: str, mode: str, *, editing: bool) -> None:
    svc = services(context)
    user_id = update.effective_user.id
    station = svc.timetable.station(station_id)
    state = await in_thread(svc.storage.get_state, user_id)
    data = state[1] if state else {}
    if station is None:
        return
    at = cb.decode_at(data.get("at"))
    if mode == "f":
        await continue_route(
            update, context, station, data.get("to_query"), at, bool(data.get("save")), editing=editing
        )
        return
    if not data.get("from"):
        # The wizard expired - treat the pick as a plain station.
        view = await in_thread(views.departures_view, svc, user_id, station_id, 0, now())
        await (edit(update, view) if editing else reply(update.effective_message, view))
        return
    await finish_route(update, context, data["from"], station_id, at, bool(data.get("save")), editing=editing)


async def location_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    svc = services(context)
    location = update.effective_message.location
    state = await in_thread(svc.storage.get_state, update.effective_user.id)
    mode = "d"
    if state and state[0] == STATE_ROUTE_FROM:
        mode = "f"
    elif state and state[0] == STATE_ROUTE_TO:
        mode = "t"
    view = await in_thread(views.nearest_view, svc, location.latitude, location.longitude, mode)
    await reply(update.effective_message, view)


# --- callback queries ----------------------------------------------------------------------------


async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = cb.parse(query.data)
    svc = services(context)
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    current = now()
    view: View | None = None
    alert: str | None = None

    match data.action:
        case cb.DEPARTURES:
            view = await in_thread(
                views.departures_view, svc, user_id, data.arg(0), data.int_arg(1), current, cb.decode_at(data.arg(2))
            )
        case cb.CONNECTIONS:
            view = await in_thread(
                views.connections_view,
                svc,
                user_id,
                data.arg(0),
                data.arg(1),
                data.int_arg(2),
                current,
                None,
                cb.decode_at(data.arg(3)),
            )
        case cb.ROUTE:
            view = await in_thread(views.route_view, svc, user_id, data.int_arg(0), data.int_arg(1), current)
        case cb.TRIP:
            view = await in_thread(
                views.trip_view,
                svc,
                chat_id,
                cb.decode_trip(data.arg(0)),
                cb.decode_date(data.arg(1)),
                data.arg(2),
                data.arg(3),
                current,
            )
        case cb.NUMBER:
            view = await in_thread(views.number_view, svc, chat_id, data.arg(0), cb.decode_date(data.arg(1)), current)
        case cb.PICK:
            mode = data.arg(1) or "d"
            if mode in ("f", "t"):
                await safe_answer(query)
                await route_station_picked(update, context, data.arg(0), mode, editing=True)
                return
            view = await in_thread(views.departures_view, svc, user_id, data.arg(0), 0, current)
        case cb.FAV_ADD:
            station = svc.timetable.station(data.arg(0))
            if station:
                await in_thread(svc.storage.add_favorite_station, user_id, station.id, station.name)
                alert = "⭐ Dodano do ulubionych"
            view = await in_thread(views.departures_view, svc, user_id, data.arg(0), 0, current)
        case cb.FAV_DEL:
            await in_thread(svc.storage.remove_favorite_station, user_id, data.arg(0))
            alert = "Usunięto z ulubionych"
            if data.arg(1) == "l":
                view = await in_thread(views.favorites_view, svc, user_id)
            else:
                view = await in_thread(views.departures_view, svc, user_id, data.arg(0), 0, current)
        case cb.ROUTE_SAVE:
            origin, target = svc.timetable.station(data.arg(0)), svc.timetable.station(data.arg(1))
            if origin and target:
                route_id = await in_thread(
                    svc.storage.add_favorite_route, user_id, origin.id, origin.name, target.id, target.name
                )
                alert = "⭐ Trasa zapisana w „Moje trasy”"
                view = await in_thread(views.route_view, svc, user_id, route_id, 0, current)
        case cb.ROUTE_DEL:
            route = await in_thread(svc.storage.favorite_route, user_id, data.int_arg(0))
            await in_thread(svc.storage.remove_favorite_route, user_id, data.int_arg(0))
            alert = "Trasa usunięta"
            if route:
                view = await in_thread(views.connections_view, svc, user_id, route.from_id, route.to_id, 0, current)
            else:
                view = await in_thread(views.routes_view, svc, user_id)
        case cb.ROUTE_FROM_HERE:
            station = svc.timetable.station(data.arg(0))
            if station:
                await in_thread(
                    svc.storage.set_state,
                    user_id,
                    STATE_ROUTE_TO,
                    {"from": station.id, "from_name": station.name, "save": False},
                )
                await safe_answer(query)
                await prompt_route_station(update, context, "t")
                return
        case cb.WATCH:
            view, alert = await watch_trip(update, context, data)
        case cb.UNWATCH:
            watch_id = data.int_arg(0)
            watch = next((w for w in await in_thread(svc.storage.watches, chat_id) if w.id == watch_id), None)
            await in_thread(svc.storage.remove_watch, watch_id, chat_id)
            alert = "🔕 Nie obserwuję już tego pociągu"
            if data.arg(1) == "c" and watch:
                view = await in_thread(
                    views.trip_view, svc, chat_id, watch.trip_id, watch.service_date, watch.station_id, None, current
                )
            else:
                view = await in_thread(views.watches_view, svc, chat_id, current)
        case cb.TUTORIAL:
            view = tutorial.page_view(data.int_arg(0))
        case cb.TUTORIAL_DEMO:
            await safe_answer(query)
            demo = await in_thread(tutorial.demo_view, svc, data.arg(0) or "", user_id, chat_id, current)
            await reply(update.effective_message, demo)
            return
        case cb.MENU:
            await safe_answer(query)
            if data.arg(0) == "newroute":
                await in_thread(svc.storage.set_state, user_id, STATE_ROUTE_FROM, {"save": True})
                await prompt_route_station(update, context, "f")
            return
        case _:
            await safe_answer(query)
            return

    await safe_answer(query, alert or (view.alert if view else None))
    if view is not None:
        await edit(update, view)


async def watch_trip(update: Update, context: ContextTypes.DEFAULT_TYPE, data: cb.Callback):
    svc = services(context)
    chat_id = update.effective_chat.id
    trip_id, service_date = cb.decode_trip(data.arg(0)), cb.decode_date(data.arg(1))
    station_id, back = data.arg(2), data.arg(3)
    current = now()
    details = await in_thread(svc.timetable.trip_details, trip_id, service_date)
    if details is None:
        return View("Ten kurs nie jest już dostępny."), "Kurs nieaktualny"
    last_arrival = details.stops[-1].arrival or details.stops[-1].departure
    if last_arrival and last_arrival < current - timedelta(minutes=30):
        return None, "Ten pociąg już dojechał"
    result = await in_thread(views._trip_status, svc, details)
    status = result.get((trip_id, service_date))
    delay = status.current_delay() if status else None
    expires = (last_arrival or current).timestamp() + 3600 + max(delay or 0, 0) * 60
    first, last = details.stops[0], details.stops[-1]
    label = f"{views.trip_label(details.trip)} {first.station_name} → {last.station_name}"
    await in_thread(
        svc.storage.add_watch,
        chat_id,
        update.effective_user.id,
        trip_id,
        service_date,
        station_id,
        label,
        expires,
        delay,
    )
    view = await in_thread(views.trip_view, svc, chat_id, trip_id, service_date, station_id, back, current)
    hint = " i przypomnę przed odjazdem" if station_id else ""
    return view, f"🔔 Obserwuję – dam znać o opóźnieniach{hint}"


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    update_id = getattr(update, "update_id", None)
    if isinstance(context.error, NetworkError):
        # Transient connection problems with the Bot API - one line is enough, no traceback.
        log.warning("Network error while handling update %s: %r", update_id, context.error)
    else:
        log.error("Error while handling update %s", update_id, exc_info=context.error)
    if isinstance(update, Update):
        try:
            if update.callback_query:
                await update.callback_query.answer("😕 Coś poszło nie tak, spróbuj ponownie.", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text("😕 Coś poszło nie tak, spróbuj ponownie za chwilę.")
        except Exception:
            log.debug("Could not notify the user about the error", exc_info=True)
