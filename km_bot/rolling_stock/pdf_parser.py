"""Extraction of rows from "Zestawienie pociągów KM kursujących w dniach ..." PDFs.

Each row has 8 columns: train number, origin, departure, destination, arrival, rolling stock type,
unit count and the operating dates ("termin kursowania"). The primary strategy uses PyMuPDF's table
detection, which keeps multi-line cells together. A text-based fallback (the heuristics of the original
parser) is used when no tables are detected, e.g. after a layout change.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf

from km_bot.rolling_stock.dates import DateParseError, Period, parse_date_list, parse_period

log = logging.getLogger(__name__)

TRAIN_NUMBER_RE = re.compile(r"^\d{3,6}(?:/\d{1,2})?$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_HEADER_KEYWORDS = re.compile(
    r"\b(okres|nr poc|relacja|handlowa|zestawienie|termin|kursowania|odj\.?|przyj\.?|typ|taboru|ilość|legenda)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PdfRow:
    number: str
    origin: str
    departure: str
    destination: str
    arrival: str
    stock: str
    units: str
    schedule: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ParsedPdf:
    name: str
    period: Period | None
    rows: list[PdfRow]


def _clean(cell: str | None) -> str:
    return re.sub(r"\s+", " ", (cell or "").replace("\n", " ")).strip()


def _clean_schedule(cell: str | None) -> str:
    # Line breaks inside the dates cell split tokens like "10-\n24 V" - joining with a space is safe
    # because the date tokenizer ignores whitespace.
    return _clean(cell)


def period_from_filename(name: str) -> Period | None:
    """'Zestawienie ... w dniach 09 III-29 V 2025r..pdf' -> Period(2025-03-09, 2025-05-29)."""
    match = re.search(r"w dniach (.+?)\s*(\d{4})\s*r", name)
    if not match:
        return None
    try:
        days = parse_date_list(match.group(1), None, int(match.group(2)))
    except DateParseError:
        return None
    return Period(min(days), max(days)) if days else None


def _row_from_cells(cells: list[str | None]) -> PdfRow | None:
    if len(cells) < 8:
        return None
    number = _clean(cells[0])
    if not TRAIN_NUMBER_RE.match(number):
        return None
    departure, arrival = _clean(cells[2]), _clean(cells[4])
    if not (_TIME_RE.match(departure) and _TIME_RE.match(arrival)):
        return None
    return PdfRow(
        number=number,
        origin=_clean(cells[1]),
        departure=departure.zfill(5),
        destination=_clean(cells[3]),
        arrival=arrival.zfill(5),
        stock=_clean(cells[5]),
        units=_clean(cells[6]),
        schedule=_clean_schedule(cells[7]),
    )


def _parse_with_tables(doc: pymupdf.Document) -> tuple[list[PdfRow], Period | None]:
    rows: list[PdfRow] = []
    period = None
    for page in doc:
        for table in page.find_tables().tables:
            for cells in table.extract():
                first = _clean(cells[0]) if cells else ""
                if period is None and "okres" in first.lower():
                    period = parse_period(first)
                row = _row_from_cells(cells)
                if row:
                    rows.append(row)
    return rows, period


def _parse_with_text(doc: pymupdf.Document) -> list[PdfRow]:
    """Fallback: rebuilds rows from one-cell-per-line page text (original parser heuristics)."""
    rows: list[PdfRow] = []
    for page in doc:
        lines = [line.strip() for line in page.get_text("text").splitlines()]
        lines = [line for line in lines if line and not _HEADER_KEYWORDS.search(line)]
        i = 0
        while i < len(lines):
            if not TRAIN_NUMBER_RE.match(lines[i]):
                i += 1
                continue
            cells = [lines[i]]
            i += 1
            while len(cells) < 7 and i < len(lines):
                line = lines[i]
                # Station names such as "WARSZAWA ZACHODNIA PERON" + "9" are split over two lines.
                if line.endswith(("PERON", "LOTNISKO")) and i + 1 < len(lines):
                    line = f"{line} {lines[i + 1]}"
                    i += 1
                cells.append(line)
                i += 1
            schedule_parts = []
            while i < len(lines) and not TRAIN_NUMBER_RE.match(lines[i]):
                schedule_parts.append(lines[i])
                i += 1
            row = _row_from_cells([*cells, " ".join(schedule_parts)])
            if row:
                rows.append(row)
    return rows


def parse_pdf(path: Path) -> ParsedPdf:
    with pymupdf.open(path) as doc:
        rows, period = _parse_with_tables(doc)
        if not rows:
            log.warning("No tables detected in %s, falling back to text parsing", path.name)
            rows = _parse_with_text(doc)
            if period is None:
                period = parse_period(doc[0].get_text("text")) if len(doc) else None
    period = period or period_from_filename(path.name)
    log.info("Parsed %s: %d rows, period %s", path.name, len(rows), period)
    return ParsedPdf(name=path.name, period=period, rows=rows)
