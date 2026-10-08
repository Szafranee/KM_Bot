"""Realtime provider based on PKP PLK "Otwarte Dane Kolejowe" API (https://pdp-api.plk-sa.pl, X-API-Key).

GTFS trip ids of the Polish trains feed embed the PLK identifiers: ``PLK_<agency>_<scheduleId>_<orderId>``.
Responses are cached in ``app.sqlite`` for ``max_age`` seconds to stay far below the API rate limits
(Basic tier: 100 requests/hour).
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from km_bot.config import TZ
from km_bot.realtime.base import StopStatus, TripKey, TripRequest, TripStatus, delay_minutes
from km_bot.storage import Storage

log = logging.getLogger(__name__)

API_URL = "https://pdp-api.plk-sa.pl/api/v1"


def plk_ids(trip_id: str) -> tuple[int, int] | None:
    """'PLK_KM_2026_114929865' -> (2026, 114929865)."""
    parts = trip_id.split("_")
    if len(parts) < 4 or parts[0] != "PLK" or not (parts[-2].isdigit() and parts[-1].isdigit()):
        return None
    return int(parts[-2]), int(parts[-1])


def _parse_dt(value: str | None) -> datetime | None:
    """PLK returns local times without an offset; values with an offset are converted to Warsaw time."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)


class PlkProvider:
    name = "plk"

    def __init__(
        self,
        storage: Storage,
        api_key: str,
        max_age: float = 60,
        timeout: float = 15,
        transport: httpx.BaseTransport | None = None,
    ):
        self.storage = storage
        self.api_key = api_key
        self.max_age = max_age
        self.timeout = timeout
        self.transport = transport

    def _get(self, path: str, params: dict | None = None) -> dict:
        key = f"plk:{path}?{sorted((params or {}).items())}"
        cached = self.storage.cache_get(key, self.max_age)
        if cached is not None:
            return cached
        with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
            response = client.get(
                f"{API_URL}{path}",
                params=params,
                headers={"X-API-Key": self.api_key, "User-Agent": "KM_Bot/2.0"},
            )
        response.raise_for_status()
        remaining = response.headers.get("X-RateLimit-Hourly-Remaining")
        if remaining is not None and remaining.isdigit() and int(remaining) < 10:
            log.warning("PLK API hourly limit almost used up (%s left)", remaining)
        payload = response.json()
        self.storage.cache_put(key, payload)
        return payload

    def statuses(self, requests: list[TripRequest]) -> dict[TripKey, TripStatus]:
        result: dict[TripKey, TripStatus] = {}
        trains: dict[tuple[int, int, str], dict] = {}

        board_requests = [r for r in requests if r.station_ids]
        stations = sorted({s for r in board_requests for s in r.station_ids if s.isdigit()})
        if stations:
            payload = self._get(
                "/operations",
                {
                    "stations": ",".join(stations),
                    "withPlanned": "true",
                    "fullRoutes": "true",
                    "pageSize": 2000,
                },
            )
            for train in payload.get("trains") or []:
                trains[(train.get("scheduleId"), train.get("orderId"), str(train.get("operatingDate"))[:10])] = train

        for request in requests:
            ids = plk_ids(request.trip_id)
            if ids is None:
                continue
            key = (*ids, request.service_date.isoformat())
            train = trains.get(key)
            if train is None and not request.station_ids:
                try:
                    train = self._get(f"/operations/train/{ids[0]}/{ids[1]}/{request.service_date.isoformat()}")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        continue
                    raise
            if train:
                result[request.key] = self.to_status(train, request)
        return result

    def to_status(self, train: dict, request: TripRequest) -> TripStatus:
        status = TripStatus(
            source=self.name,
            cancelled=train.get("trainStatus") == "X",
            updated_at=datetime.now(TZ),
        )
        entries = train.get("stations") or []
        by_station: dict[str, list[dict]] = {}
        for entry in entries:
            by_station.setdefault(str(entry.get("stationId")), []).append(entry)

        # Delay at the last confirmed station is propagated to stations the train has not reached yet.
        current_delay = None
        for entry in entries:
            if entry.get("isConfirmed"):
                delay = entry.get("departureDelayMinutes", entry.get("arrivalDelayMinutes"))
                if delay is None:
                    delay = delay_minutes(
                        _parse_dt(entry.get("actualDeparture")), _parse_dt(entry.get("plannedDeparture"))
                    )
                current_delay = delay if delay is not None else current_delay

        for stop in request.stops:
            candidates = by_station.get(stop.station_id, [])
            entry = next((e for e in candidates if e.get("plannedSequenceNumber") == stop.plk_seq), None)
            entry = entry or (candidates[0] if candidates else None)
            if entry is None:
                continue
            passed = bool(entry.get("isConfirmed"))
            arrival_delay = entry.get("arrivalDelayMinutes")
            departure_delay = entry.get("departureDelayMinutes")
            if arrival_delay is None:
                arrival_delay = delay_minutes(_parse_dt(entry.get("actualArrival")), stop.arrival)
            if departure_delay is None:
                departure_delay = delay_minutes(_parse_dt(entry.get("actualDeparture")), stop.departure)
            if not passed and arrival_delay is None and departure_delay is None and current_delay is not None:
                arrival_delay = departure_delay = max(current_delay, 0)
            status.stops[stop.seq] = StopStatus(
                arrival_delay=arrival_delay,
                departure_delay=departure_delay,
                cancelled=bool(entry.get("isCancelled")),
                passed=passed,
            )
        return status

    def check(self) -> dict:
        """Verifies the API key (used by the ``plk-check`` CLI command)."""
        return self._get("/operations/statistics", {"date": date.today().isoformat()})
