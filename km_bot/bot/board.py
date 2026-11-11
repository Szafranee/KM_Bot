"""Which departures a live board should still show.

A board that hides a train the moment its scheduled time passes is too strict:

* a delayed train has not left yet, although its scheduled time is in the past,
* delays are not always reported - the passenger portal shows none for some trains that do run late.

So the board looks back ``LOOKBACK`` minutes and keeps a train when

1. the live data says it already passed the station (``passed``): only if its expected time is still ahead,
2. a delay is reported: while the *expected* departure (schedule + delay) is at most ``LEAVING`` in the past,
3. otherwise (on time or no data): while the scheduled time is at most ``buffer`` in the past, where the buffer
   is ``BASE_BUFFER`` and grows to ``LONG_BUFFER`` when the next train is more than ``LONG_GAP`` away - missing
   a rare train costs more than a few extra minutes of an already-gone one.

Trains kept only by the buffer are flagged so the board can say that, by schedule, they have left.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from km_bot.realtime.service import RealtimeResult
from km_bot.timetable.queries import StopTime

LOOKBACK = timedelta(minutes=20)
BASE_BUFFER = timedelta(minutes=3)
LONG_BUFFER = timedelta(minutes=5)
LONG_GAP = timedelta(minutes=12)
LEAVING = timedelta(minutes=1)
EXTRA_CANDIDATES = 40
"""Departures within the look-back window that may be filtered out again; fetched on top of the page."""


def select_visible[T](
    items: Sequence[T],
    stop_of: Callable[[T], StopTime],
    key_of: Callable[[T], tuple[str, object]],
    realtime: RealtimeResult,
    now: datetime,
) -> list[tuple[T, bool]]:
    """Filters look-back candidates. Returns (item, left_by_schedule) in the original order."""

    def scheduled(item: T) -> datetime:
        return stop_of(item).time

    upcoming = [scheduled(item) for item in items if scheduled(item) >= now]
    buffer = LONG_BUFFER if not upcoming or min(upcoming) - now > LONG_GAP else BASE_BUFFER

    visible: list[tuple[T, bool]] = []
    for item in items:
        stop = stop_of(item)
        planned = scheduled(item)
        status = realtime.get(key_of(item))
        stop_status = status.at(stop.seq) if status else None
        cancelled = bool(status and status.cancelled) or bool(stop_status and stop_status.cancelled)
        delay = stop_status.delay if stop_status else None
        if cancelled:
            keep = planned >= now
        elif stop_status is not None and stop_status.passed:
            keep = planned + timedelta(minutes=max(delay or 0, 0)) >= now
        elif delay is not None and delay > 0:
            keep = planned + timedelta(minutes=delay) >= now - LEAVING
        else:
            keep = planned >= now - buffer
        if keep:
            delayed = delay is not None and delay > 0
            visible.append((item, planned < now and not delayed and not cancelled))
    return visible
