"""Interpretation of free-text messages: train number, route "A > B [time]" or station "[time]"."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

NUMBER_RE = re.compile(r"^\s*(?:nr\.?\s*|poci[aą]g\s*)?(\d{4,6})(?:\s*/\s*\d{1,2})?\s*$", re.IGNORECASE)
TIME_RE = re.compile(r"(?:^|\s+)(?:o\s+|od\s+|godz\.?\s*)?(\d{1,2})[:.](\d{2})\s*$", re.IGNORECASE)
# " - " needs spaces around it: station names such as "Skarżysko-Kamienna" contain hyphens.
ROUTE_SEPARATOR_RE = re.compile(r"\s*(?:->|=>|→|>|–|—|,|;|\n)\s*|\s+-\s+|\s+do\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Query:
    kind: str  # "number", "route" or "station"
    number: str | None = None
    origin: str | None = None
    target: str | None = None
    at: datetime | None = None


def _split_time(text: str, now: datetime) -> tuple[str, datetime | None]:
    match = TIME_RE.search(text)
    if not match:
        return text, None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return text, None
    moment = datetime.combine(now.date(), time(hours, minutes), now.tzinfo)
    if moment < now - timedelta(hours=2):
        moment += timedelta(days=1)  # "Koło 6:30" asked late in the evening means tomorrow morning
    return text[: match.start()].strip(), moment


def parse_query(text: str, now: datetime) -> Query | None:
    text = text.strip()
    if not text:
        return None
    if match := NUMBER_RE.match(text):
        return Query("number", number=match.group(1))
    body, at = _split_time(text, now)
    parts = [part.strip() for part in ROUTE_SEPARATOR_RE.split(body) if part and part.strip()]
    if len(parts) == 2:
        return Query("route", origin=parts[0], target=parts[1], at=at)
    if len(parts) == 3 and at is None:
        # Legacy format: "start, end, HH:MM" (already handled above when the time is last).
        body3, at3 = _split_time(parts[2], now)
        if at3 and not body3:
            return Query("route", origin=parts[0], target=parts[1], at=at3)
    if not body:
        return None
    return Query("station", origin=body, at=at)
