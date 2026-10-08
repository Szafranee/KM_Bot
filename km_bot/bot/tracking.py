"""Notifications for tracked ("obserwowane") trains. Run every few minutes by cron (``check-tracked``)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError

from km_bot.bot import callbacks as cb
from km_bot.bot import views
from km_bot.bot.services import Services
from km_bot.realtime.base import TripRequest, TripStatus
from km_bot.storage import Watch
from km_bot.timetable.queries import StopTime, TripDetails

log = logging.getLogger(__name__)

REMIND_BEFORE = timedelta(minutes=10)
DELAY_STEP = 3


@dataclass
class Evaluation:
    messages: list[str] = field(default_factory=list)
    updates: dict[str, object] = field(default_factory=dict)
    finished: bool = False


def boarding_stop(details: TripDetails, station_ids: set[str]) -> StopTime | None:
    return next((s for s in details.stops if s.station_id in station_ids and s.departure), None)


def evaluate(
    watch: Watch, details: TripDetails, status: TripStatus | None, boarding: StopTime | None, now: datetime
) -> Evaluation:
    result = Evaluation()
    label = views.esc(watch.label)
    last = details.stops[-1]
    last_status = status.at(last.seq) if status else None
    if last_status and last_status.passed:
        result.finished = True
        return result

    if status and status.cancelled:
        if not watch.last_cancelled:
            result.messages.append(f"❌ <b>{label}</b> został odwołany.")
            result.updates["last_cancelled"] = 1
        return result

    delay = None
    if status:
        stop_status = status.at(boarding.seq) if boarding else None
        delay = stop_status.delay if stop_status and stop_status.delay is not None else status.current_delay()
    if delay is not None:
        previous = watch.last_delay or 0
        if abs(delay - previous) >= DELAY_STEP and max(delay, previous) >= DELAY_STEP:
            if delay >= DELAY_STEP:
                change = f" (było +{previous} min)" if previous >= DELAY_STEP else ""
                result.messages.append(f"⏱ <b>{label}</b>: opóźnienie <b>+{delay} min</b>{change}.")
            else:
                result.messages.append(f"🟢 <b>{label}</b> jedzie już planowo.")
            result.updates["last_delay"] = delay

    if boarding and not watch.reminded and boarding.departure:
        boarding_status = status.at(boarding.seq) if status else None
        if boarding_status and boarding_status.passed:
            result.updates["reminded"] = 1
        else:
            expected = boarding.departure + timedelta(minutes=max(delay or 0, 0))
            if expected - now <= REMIND_BEFORE:
                if expected >= now - timedelta(minutes=1):
                    minutes = max(int((expected - now).total_seconds() // 60), 0)
                    platform = f", peron {views.esc(boarding.platform)}" if boarding.platform else ""
                    delay_part = f", opóźnienie +{delay} min" if delay and delay > 0 else ""
                    result.messages.append(
                        f"🚉 Za ok. {minutes} min odjazd <b>{label}</b> ze stacji "
                        f"<b>{views.esc(boarding.station_name)}</b> (wg rozkładu {views.hhmm(boarding.departure)}"
                        f"{delay_part}{platform})."
                    )
                result.updates["reminded"] = 1
    return result


async def check_watches(svc: Services, bot: Bot, now: datetime) -> int:
    """Checks all tracked trains and sends notifications. Returns the number of messages sent."""
    sent = 0
    watches = await asyncio.to_thread(svc.storage.watches)
    for watch in watches:
        if watch.expires_at < time.time():
            await asyncio.to_thread(svc.storage.remove_watch, watch.id)
            continue
        details = await asyncio.to_thread(svc.timetable.trip_details, watch.trip_id, watch.service_date)
        if details is None:
            await asyncio.to_thread(svc.storage.remove_watch, watch.id)
            continue
        if details.stops[0].departure and details.stops[0].departure - now > timedelta(hours=3):
            continue  # too early to check, saves realtime requests
        realtime = await asyncio.to_thread(
            svc.realtime.statuses, [TripRequest(watch.trip_id, watch.service_date, tuple(details.stops))]
        )
        group = set(svc.timetable.station_group(watch.station_id)) if watch.station_id else set()
        evaluation = evaluate(
            watch, details, realtime.get((watch.trip_id, watch.service_date)), boarding_stop(details, group), now
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🚆 Pokaż pociąg",
                        callback_data=cb.make_lenient(
                            cb.TRIP,
                            cb.encode_trip(watch.trip_id),
                            cb.encode_date(watch.service_date),
                            watch.station_id,
                            "",
                        ),
                    ),
                    InlineKeyboardButton("🔕 Nie obserwuj", callback_data=cb.make(cb.UNWATCH, watch.id, "l")),
                ]
            ]
        )
        for text in evaluation.messages:
            try:
                await bot.send_message(
                    watch.chat_id,
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                sent += 1
            except Forbidden:
                log.info("Chat %s blocked the bot - removing its watches", watch.chat_id)
                await asyncio.to_thread(svc.storage.remove_watch, watch.id)
                break
            except TelegramError:
                log.exception("Cannot notify chat %s", watch.chat_id)
        if evaluation.finished:
            await asyncio.to_thread(svc.storage.remove_watch, watch.id)
        elif evaluation.updates:
            await asyncio.to_thread(svc.storage.update_watch, watch.id, **evaluation.updates)
    return sent
