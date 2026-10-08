"""Common types of the realtime (delay) providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from km_bot.timetable.queries import StopTime

TripKey = tuple[str, date]


@dataclass(frozen=True)
class StopStatus:
    arrival_delay: int | None = None
    departure_delay: int | None = None
    cancelled: bool = False
    passed: bool = False
    """The train confirmed passing this stop."""

    @property
    def delay(self) -> int | None:
        return self.departure_delay if self.departure_delay is not None else self.arrival_delay


@dataclass
class TripStatus:
    source: str
    cancelled: bool = False
    stops: dict[int, StopStatus] = field(default_factory=dict)
    """Statuses by GTFS stop sequence."""
    updated_at: datetime | None = None

    @property
    def started(self) -> bool:
        return any(s.passed for s in self.stops.values())

    def at(self, seq: int) -> StopStatus | None:
        return self.stops.get(seq)

    def current_delay(self) -> int | None:
        """Delay at the last confirmed stop, or the first known prediction when the train has not started."""
        passed = [seq for seq, s in self.stops.items() if s.passed and s.delay is not None]
        if passed:
            return self.stops[max(passed)].delay
        known = [seq for seq, s in self.stops.items() if s.delay is not None]
        return self.stops[min(known)].delay if known else None


@dataclass(frozen=True)
class TripRequest:
    trip_id: str
    service_date: date
    stops: tuple[StopTime, ...]
    """Scheduled stops of interest (one stop for a departure board, all stops for a trip card)."""
    station_ids: tuple[str, ...] = ()
    """Board station(s) - lets providers fetch a whole station at once."""

    @property
    def key(self) -> TripKey:
        return (self.trip_id, self.service_date)


class RealtimeProvider(Protocol):
    name: str

    def statuses(self, requests: list[TripRequest]) -> dict[TripKey, TripStatus]:
        """Returns statuses for the trips the provider knows about. Raises on provider failure."""
        ...


def delay_minutes(predicted: datetime | None, scheduled: datetime | None) -> int | None:
    if predicted is None or scheduled is None:
        return None
    return round((predicted - scheduled).total_seconds() / 60)
