"""Realtime provider for Warszawska Kolej Dojazdowa (WKD).

WKD is not part of the PKP PLK network, so neither the PLK API nor the PLK-based mkuran feed know it. Mikołaj
Kuranowski's WKDGTFS scrapes the live map on wkd.com.pl into a GTFS-Realtime feed (``trip_updates`` only,
https://mkuran.pl/gtfs/wkd.pb, ~3 KB). The feed lists *predicted* departure times of the stops still ahead
of each train that is on the line; the delay is the prediction minus the scheduled time.

GTFS-Realtime is a protocol buffer. The few fields needed here are decoded by hand (see ``decode``) instead of
adding the protobuf runtime as a dependency of the hosting environment.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime

import httpx

from km_bot.config import TZ
from km_bot.realtime.base import StopStatus, TripKey, TripRequest, TripStatus, delay_minutes
from km_bot.storage import Storage
from km_bot.timetable.gtfs_import import WKD_PREFIX

log = logging.getLogger(__name__)

FEED_URL = "https://mkuran.pl/gtfs/wkd.pb"
CACHE_KEY = "wkd:trip_updates"
MAX_PLAUSIBLE_DELAY = 240  # minutes; larger values mean the prediction belongs to a different day's run

# GTFS-Realtime schedule_relationship values
SKIPPED, CANCELED = 1, 3


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int | bytes]]:
    """Yields (field number, value) of one protobuf message; fixed-width fields are skipped."""
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
            yield number, value
        elif wire == 2:
            length, pos = _varint(buf, pos)
            yield number, buf[pos : pos + length]
            pos += length
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")


def _time_of(event: bytes) -> int | None:
    """StopTimeEvent.time (field 2); the feed carries absolute times, not delays."""
    return next((v for n, v in _fields(event) if n == 2 and isinstance(v, int)), None)


def decode(data: bytes) -> dict:
    """FeedMessage -> {"timestamp": int, "trips": {trip_id: {"cancelled": bool, "stops": {stop_id: {...}}}}}."""
    timestamp = 0
    trips: dict[str, dict] = {}
    for number, value in _fields(data):
        if number == 1 and isinstance(value, bytes):  # FeedHeader
            timestamp = next((v for n, v in _fields(value) if n == 3 and isinstance(v, int)), 0)
        elif number == 2 and isinstance(value, bytes):  # FeedEntity
            for n, update in _fields(value):
                if n != 3 or not isinstance(update, bytes):  # TripUpdate
                    continue
                trip_id, cancelled, stops = "", False, {}
                for un, uv in _fields(update):
                    if un == 1 and isinstance(uv, bytes):  # TripDescriptor
                        for tn, tv in _fields(uv):
                            if tn == 1 and isinstance(tv, bytes):
                                trip_id = tv.decode()
                            elif tn == 4 and tv == CANCELED:
                                cancelled = True
                    elif un == 2 and isinstance(uv, bytes):  # StopTimeUpdate
                        stop = {"arr": None, "dep": None, "skipped": False}
                        stop_id = ""
                        for sn, sv in _fields(uv):
                            if sn == 2 and isinstance(sv, bytes):
                                stop["arr"] = _time_of(sv)
                            elif sn == 3 and isinstance(sv, bytes):
                                stop["dep"] = _time_of(sv)
                            elif sn == 4 and isinstance(sv, bytes):
                                stop_id = sv.decode()
                            elif sn == 5 and sv == SKIPPED:
                                stop["skipped"] = True
                        if stop_id:
                            stops[stop_id] = stop
                if trip_id:
                    trips[trip_id] = {"cancelled": cancelled, "stops": stops}
    return {"timestamp": timestamp, "trips": trips}


def _moment(timestamp: int | None) -> datetime | None:
    return datetime.fromtimestamp(timestamp, TZ) if timestamp else None


class WkdProvider:
    name = "wkd"

    def __init__(
        self,
        storage: Storage,
        url: str = FEED_URL,
        max_age: float = 30,
        timeout: float = 15,
        transport: httpx.BaseTransport | None = None,
    ):
        self.storage = storage
        self.url = url
        self.max_age = max_age
        self.timeout = timeout
        self.transport = transport

    def _feed(self) -> dict:
        cached = self.storage.cache_get(CACHE_KEY, self.max_age)
        if cached is not None:
            return cached
        with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
            response = client.get(self.url, headers={"User-Agent": "KM_Bot/2.0"})
        response.raise_for_status()
        feed = decode(response.content)
        self.storage.cache_put(CACHE_KEY, feed)
        return feed

    def statuses(self, requests: list[TripRequest]) -> dict[TripKey, TripStatus]:
        wanted = [r for r in requests if r.trip_id.startswith(WKD_PREFIX)]
        if not wanted:
            return {}
        feed = self._feed()
        updated_at = _moment(feed.get("timestamp"))
        result: dict[TripKey, TripStatus] = {}
        for request in wanted:
            trip = feed["trips"].get(request.trip_id.removeprefix(WKD_PREFIX))
            if trip is None:
                continue
            status = TripStatus(source=self.name, cancelled=trip["cancelled"], updated_at=updated_at)
            for stop in request.stops:
                update = trip["stops"].get(stop.station_id.removeprefix(WKD_PREFIX))
                if update is None:
                    continue
                arrival = delay_minutes(_moment(update["arr"]), stop.arrival)
                departure = delay_minutes(_moment(update["dep"]), stop.departure)
                delays = [d for d in (arrival, departure) if d is not None]
                if any(abs(d) > MAX_PLAUSIBLE_DELAY for d in delays):
                    continue
                status.stops[stop.seq] = StopStatus(
                    arrival_delay=arrival, departure_delay=departure, cancelled=update["skipped"]
                )
            if status.stops or status.cancelled:
                result[request.key] = status
        return result
