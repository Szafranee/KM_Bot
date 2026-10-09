"""Builds ``rolling_stock.sqlite`` from the downloaded PDFs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from km_bot import db
from km_bot.rolling_stock.dates import DateParseError, Period, parse_schedule
from km_bot.rolling_stock.gemini_fallback import GeminiDateConverter
from km_bot.rolling_stock.pdf_parser import ParsedPdf, PdfRow, parse_pdf

log = logging.getLogger(__name__)

PARSER_VERSION = 2

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE pdfs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    priority INTEGER NOT NULL
);
CREATE TABLE entries (
    number TEXT NOT NULL,          -- single train number, e.g. 91471
    raw_number TEXT NOT NULL,      -- as printed, e.g. 91470/1
    run_date TEXT NOT NULL,        -- YYYY-MM-DD
    pdf_id INTEGER NOT NULL REFERENCES pdfs(id),
    origin TEXT NOT NULL,
    departure TEXT NOT NULL,
    destination TEXT NOT NULL,
    arrival TEXT NOT NULL,
    stock TEXT NOT NULL,
    units TEXT NOT NULL,
    explicit INTEGER NOT NULL      -- 0 when the PDF left the dates cell empty (whole period assumed)
);
CREATE INDEX entries_lookup ON entries (number, run_date);
"""


def expand_train_number(raw: str) -> list[str]:
    """'91470/1' -> ['91470', '91471']; '21308/9' -> ['21308', '21309']; '10780' -> ['10780']."""
    raw = raw.strip()
    if "/" not in raw:
        return [raw]
    base, suffix = raw.split("/", 1)
    if not (base.isdigit() and suffix.isdigit()):
        return [base]
    second = base[: len(base) - len(suffix)] + suffix
    return [base] if second == base else [base, second]


@dataclass
class ImportReport:
    pdfs: int = 0
    rows: int = 0
    entries: int = 0
    gemini: int = 0
    failed: list[str] = field(default_factory=list)


def _cache_path(pdf: Path) -> Path:
    return pdf.parent / ".cache" / f"{pdf.name}.json"


def load_or_parse(pdf: Path) -> ParsedPdf:
    """Parsing a PDF takes ~10 s, so results are cached next to it."""
    cache = _cache_path(pdf)
    stat = pdf.stat()
    signature = {"version": PARSER_VERSION, "size": stat.st_size, "mtime": int(stat.st_mtime)}
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("signature") == signature:
            period = (
                Period(date.fromisoformat(data["period"][0]), date.fromisoformat(data["period"][1]))
                if data.get("period")
                else None
            )
            return ParsedPdf(pdf.name, period, [PdfRow(**row) for row in data["rows"]])
    except OSError, ValueError, KeyError, TypeError:
        pass
    parsed = parse_pdf(pdf)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "signature": signature,
                "period": [parsed.period.start.isoformat(), parsed.period.end.isoformat()] if parsed.period else None,
                "rows": [row.to_dict() for row in parsed.rows],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return parsed


def resolve_dates(parsed: ParsedPdf, gemini: GeminiDateConverter | None, report: ImportReport) -> dict[str, set[date]]:
    """Maps every distinct dates cell of a PDF to concrete dates (deterministic parser, then Gemini)."""
    resolved: dict[str, set[date]] = {}
    unknown: list[str] = []
    for text in {row.schedule for row in parsed.rows}:
        try:
            resolved[text] = parse_schedule(text, parsed.period)
        except DateParseError as exc:
            log.warning("Unparsed date expression in %s: %r (%s)", parsed.name, text, exc)
            unknown.append(text)
    if unknown and gemini and parsed.period:
        converted = gemini.convert(unknown, parsed.period)
        resolved.update(converted)
        report.gemini += len(converted)
    report.failed.extend(f"{parsed.name}: {text}" for text in unknown if text not in resolved)
    return resolved


def build_database(pdfs: list[Path], db_path: Path, gemini: GeminiDateConverter | None) -> ImportReport:
    report = ImportReport()
    parsed_pdfs = [(pdf, load_or_parse(pdf)) for pdf in pdfs]
    # Newer/more specific lists win when periods overlap: higher priority = later start, then newer file.
    parsed_pdfs.sort(key=lambda item: (item[1].period.start if item[1].period else date.min, item[0].stat().st_mtime))

    with db.rebuild_db(db_path) as conn:
        conn.executescript(SCHEMA)
        for priority, (_pdf, parsed) in enumerate(parsed_pdfs):
            report.pdfs += 1
            report.rows += len(parsed.rows)
            cursor = conn.execute(
                "INSERT INTO pdfs (name, period_start, period_end, priority) VALUES (?, ?, ?, ?)",
                (
                    parsed.name,
                    parsed.period.start.isoformat() if parsed.period else None,
                    parsed.period.end.isoformat() if parsed.period else None,
                    priority,
                ),
            )
            pdf_id = cursor.lastrowid
            dates_by_text = resolve_dates(parsed, gemini, report)
            batch = []
            for row in parsed.rows:
                for run_date in sorted(dates_by_text.get(row.schedule, ())):
                    for number in expand_train_number(row.number):
                        batch.append(
                            (
                                number,
                                row.number,
                                run_date.isoformat(),
                                pdf_id,
                                row.origin,
                                row.departure,
                                row.destination,
                                row.arrival,
                                row.stock,
                                row.units,
                                int(bool(row.schedule)),
                            )
                        )
            conn.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
            report.entries += len(batch)
        conn.execute("INSERT INTO meta VALUES ('imported_at', datetime('now'))")
    log.info(
        "Rolling stock import: %d PDFs, %d rows, %d entries, %d via Gemini, %d failed",
        report.pdfs,
        report.rows,
        report.entries,
        report.gemini,
        len(report.failed),
    )
    return report
