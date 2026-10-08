"""Deterministic parser for the "termin kursowania" column of KM rolling stock PDFs.

Examples of supported values (all observed in real PDFs)::

    9 III-29 V                       4,11,18 X                 2-5,9-12 VI
    15 III-26 IV, 10- 24 V (6)       30 V,1,6,8,13 VI          5-23 X (D)
    10 III-29 V (1-6) oprócz 21 IV,1,3 V                       9 III-29 V (B) i 3 V
    9 III-25 V (5,7) i 21 IV,1,3 V   4-23 X (2-5,7)            4-24 X (1-4,6-7)

Months are written in Roman numerals and may be omitted when the next item carries them ("1,7 XII").
Arabic ``DD.MM[.YYYY]`` and ISO ``YYYY-MM-DD`` dates are accepted as well, in case KM changes the format.
The year is taken from the PDF validity period. Day rules come from the official KM legend:

    (A) Mon-Fri            (B) Mon-Fri and Sundays      (C) Saturdays, Sundays and holidays
    (D) Mon-Fri except holidays    (E) Mon-Sat except holidays    (+) Sundays and holidays
    (1)...(7) days of the week, e.g. (1-6), (2-5,7)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from km_bot.rolling_stock.holidays import is_holiday

ROMAN_MONTHS = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
    "XI": 11,
    "XII": 12,
}

LETTER_RULES = {
    "A": lambda d: d.weekday() < 5,
    "B": lambda d: d.weekday() < 5 or d.weekday() == 6,
    "C": lambda d: d.weekday() >= 5 or is_holiday(d),
    "D": lambda d: d.weekday() < 5 and not is_holiday(d),
    "E": lambda d: d.weekday() < 6 and not is_holiday(d),
    "+": lambda d: d.weekday() == 6 or is_holiday(d),
}

_TOKEN_RE = re.compile(
    r"(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|(?P<dotted>\d{1,2}\.\d{1,2}(?:\.\d{4})?)"
    r"|(?P<roman>XII|XI|IX|X|VIII|VII|VI|IV|V|III|II|I)(?![A-Z])"
    r"|(?P<day>\d{1,2})"
    r"|(?P<dash>-)"
    r"|(?P<comma>[,;])"
    r"|(?P<space>\s+)"
    r"|(?P<dot>\.)"
)
_EXCEPT_RE = re.compile(r"\b(?:oprócz|oprocz|opr\.|z wyjątkiem|bez)\s*", re.IGNORECASE)
# Case-sensitive on purpose: an uppercase "I" is January.
_ALSO_RE = re.compile(r"(?:^|\s)(?:i|oraz|także|takze)\s+")
_PERIOD_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})\s*[-–]\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})"
)


class DateParseError(ValueError):
    """Raised when a date expression cannot be understood deterministically."""


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)]

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.start <= day <= self.end


@dataclass
class _Point:
    day: int
    month: int | None = None
    year: int | None = None


def normalize(text: str) -> str:
    text = text.replace("\n", " ").replace(" ", " ")
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".").strip()


def parse_period(text: str) -> Period | None:
    """Parses "okres obowiązywania 2026-10-04 - 2026-10-24" or "09.03.2025 - 29.05.2025"."""
    match = _PERIOD_RE.search(text)
    if not match:
        return None
    start, end = (_parse_full_date(part) for part in match.groups())
    return Period(start, end) if start <= end else None


def _parse_full_date(text: str) -> date:
    if "-" in text:
        return date.fromisoformat(text)
    day, month, year = (int(x) for x in text.split("."))
    return date(year, month, day)


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match:
            raise DateParseError(f"Unexpected text {text[pos:]!r} in {text!r}")
        kind = match.lastgroup or ""
        if kind not in ("space", "dot"):
            tokens.append((kind, match.group()))
        pos = match.end()
    return tokens


def _parse_point(tokens: list[tuple[str, str]], i: int, source: str) -> tuple[_Point, int]:
    kind, value = tokens[i]
    if kind == "iso":
        parsed = date.fromisoformat(value)
        return _Point(parsed.day, parsed.month, parsed.year), i + 1
    if kind == "dotted":
        parts = [int(x) for x in value.split(".")]
        return _Point(parts[0], parts[1], parts[2] if len(parts) == 3 else None), i + 1
    if kind != "day":
        raise DateParseError(f"Expected a day number in {source!r}")
    point = _Point(int(value))
    i += 1
    if i < len(tokens) and tokens[i][0] == "roman":
        point.month = ROMAN_MONTHS[tokens[i][1]]
        i += 1
    return point, i


def _parse_items(text: str) -> list[tuple[_Point, _Point]]:
    """Splits "1-2,4-7 XII" into [(1 XII, 2 XII), (4 XII, 7 XII)] with months filled in."""
    tokens = _tokenize(text)
    if not tokens:
        raise DateParseError("Empty date expression")
    items: list[tuple[_Point, _Point]] = []
    i = 0
    while i < len(tokens):
        start, i = _parse_point(tokens, i, text)
        end = start
        if i < len(tokens) and tokens[i][0] == "dash":
            if i + 1 >= len(tokens):
                raise DateParseError(f"Dangling range in {text!r}")
            end, i = _parse_point(tokens, i + 1, text)
        items.append((start, end))
        if i < len(tokens):
            if tokens[i][0] != "comma":
                raise DateParseError(f"Expected a comma in {text!r}")
            i += 1
    # A missing month is inherited from the next point that has one ("16,23 II,2 III" -> 16 II).
    points = [p for item in items for p in item]
    next_month: int | None = None
    next_year: int | None = None
    for point in reversed(points):
        if point.month is None:
            if next_month is None:
                raise DateParseError(f"Cannot determine the month in {text!r}")
            point.month = next_month
            point.year = point.year or next_year
        next_month, next_year = point.month, point.year
    return items


def _resolve(point: _Point, period: Period | None, fallback_year: int) -> date:
    assert point.month is not None
    if point.year is not None:
        years = [point.year]
    elif period is not None:
        years = sorted({period.start.year, period.end.year, period.start.year - 1, period.end.year + 1})
    else:
        years = [fallback_year]
    candidates: list[date] = []
    for year in years:
        try:
            candidates.append(date(year, point.month, point.day))
        except ValueError:
            continue
    if not candidates:
        raise DateParseError(f"Invalid date {point.day}.{point.month}")
    if period is None:
        return candidates[0]

    def distance(day: date) -> int:
        if day < period.start:
            return (period.start - day).days
        if day > period.end:
            return (day - period.end).days
        return 0

    return min(candidates, key=distance)


def parse_date_list(text: str, period: Period | None, fallback_year: int | None = None) -> set[date]:
    """Expands a list of dates/ranges ("15 III-26 IV, 10-24 V") into concrete dates."""
    year = fallback_year or (period.start.year if period else date.today().year)
    result: set[date] = set()
    for start_point, end_point in _parse_items(normalize(text)):
        start = _resolve(start_point, period, year)
        end = _resolve(end_point, period, year)
        if end < start:
            raise DateParseError(f"Range ends before it starts in {text!r}")
        if (end - start).days > 400:
            raise DateParseError(f"Suspiciously long range in {text!r}")
        result.update(start + timedelta(days=i) for i in range((end - start).days + 1))
    return result


def _parse_weekdays(spec: str) -> set[int]:
    """'1-4,6-7' -> {1, 2, 3, 4, 6, 7} (ISO weekdays)."""
    days: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if re.fullmatch(r"[1-7]", part):
            days.add(int(part))
        elif match := re.fullmatch(r"([1-7])\s*-\s*([1-7])", part):
            first, last = int(match.group(1)), int(match.group(2))
            if first > last:
                raise DateParseError(f"Invalid weekday range {spec!r}")
            days.update(range(first, last + 1))
        else:
            raise DateParseError(f"Invalid weekday specification {spec!r}")
    return days


def day_rule(spec: str):
    """Returns a predicate for a legend symbol: 'D', '+', '1-6', '2-5,7'..."""
    spec = normalize(spec).upper()
    if spec in LETTER_RULES:
        return LETTER_RULES[spec]
    weekdays = _parse_weekdays(spec)
    return lambda d: d.isoweekday() in weekdays


def _split_modifiers(text: str) -> tuple[str, str | None, list[str], list[str]]:
    """Splits '9 III-29 V (1-6) oprócz 21 IV,1 V i 3 V' into (dates, rule, excluded, added)."""
    rule = None
    rule_match = re.search(r"\(([^)]*)\)", text)
    if rule_match:
        rule = rule_match.group(1).strip()
        text = (text[: rule_match.start()] + " | " + text[rule_match.end() :]).strip()
    else:
        text = text + " |"
    main, _, rest = text.partition("|")
    excluded: list[str] = []
    added: list[str] = []
    # The rest is a sequence of "oprócz <dates>" / "i <dates>" clauses in any order.
    rest = rest.strip()
    while rest:
        except_match = _EXCEPT_RE.match(rest)
        also_match = _ALSO_RE.match(rest)
        match = except_match or also_match
        if not match:
            raise DateParseError(f"Unexpected modifier {rest!r}")
        body = rest[match.end() :]
        nxt = min([m.start() for m in (_EXCEPT_RE.search(body), _ALSO_RE.search(body)) if m] or [len(body)])
        (excluded if except_match else added).append(body[:nxt].strip(" ,"))
        rest = body[nxt:].strip()
    # Modifiers without a rule in parentheses, e.g. "9 III-29 V oprócz 21 IV".
    for regex, target in ((_EXCEPT_RE, excluded), (_ALSO_RE, added)):
        match = regex.search(main)
        if match:
            target.append(main[match.end() :].strip(" ,"))
            main = main[: match.start()]
    return main.strip(" ,"), rule, excluded, added


def parse_schedule(text: str | None, period: Period | None, fallback_year: int | None = None) -> set[date]:
    """Returns the dates on which a PDF row is valid. An empty value means the whole period."""
    text = normalize(text or "")
    if not text:
        if period is None:
            raise DateParseError("Empty date expression and unknown period")
        return set(period.days())
    main, rule, excluded, added = _split_modifiers(text)
    if main:
        dates = parse_date_list(main, period, fallback_year)
    elif period is not None:
        dates = set(period.days())
    else:
        raise DateParseError(f"No dates in {text!r}")
    if rule:
        predicate = day_rule(rule)
        dates = {d for d in dates if predicate(d)}
    for chunk in excluded:
        dates -= parse_date_list(chunk, period, fallback_year)
    for chunk in added:
        dates |= parse_date_list(chunk, period, fallback_year)
    if period is not None:
        dates = {d for d in dates if d in period}
    return dates
