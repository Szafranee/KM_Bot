"""Read access to ``rolling_stock.sqlite``."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from km_bot import db
from km_bot.rolling_stock.catalog import StockDescription, describe


@dataclass(frozen=True)
class StockEntry:
    raw_number: str
    run_date: date
    origin: str
    departure: str
    destination: str
    arrival: str
    stock: str
    units: str
    pdf_name: str
    period_start: date | None
    period_end: date | None

    @property
    def description(self) -> StockDescription:
        return describe(self.stock, self.units)


@dataclass(frozen=True)
class PdfInfo:
    name: str
    period_start: date | None
    period_end: date | None


def _to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class RollingStockRepository:
    def __init__(self, path: Path):
        self.path = path

    def available(self) -> bool:
        return db.exists(self.path)

    def lookup(self, number: str, run_date: date, departure: str | None = None) -> list[StockEntry]:
        """Rolling stock of train ``number`` on ``run_date``.

        Only rows from the highest-priority (newest) PDF covering that day are used. ``departure``
        (HH:MM at the train's origin) disambiguates trains with several variants.
        """
        if not self.available():
            return []
        with db.open_db(self.path, readonly=True) as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT e.*, p.name AS pdf_name, p.period_start, p.period_end, p.priority
                    FROM entries e JOIN pdfs p ON p.id = e.pdf_id
                    WHERE e.number = ? AND e.run_date = ?
                    ORDER BY p.priority DESC, e.explicit DESC, e.departure
                    """,
                    (number.strip(), run_date.isoformat()),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        if not rows:
            return []
        top = rows[0]["priority"]
        rows = [r for r in rows if r["priority"] == top]
        if any(r["explicit"] for r in rows):
            rows = [r for r in rows if r["explicit"]]
        if departure:
            matching = [r for r in rows if r["departure"] == departure]
            rows = matching or rows
        seen: set[tuple] = set()
        result: list[StockEntry] = []
        for r in rows:
            key = (r["origin"], r["departure"], r["destination"], r["stock"], r["units"])
            if key in seen:
                continue
            seen.add(key)
            result.append(
                StockEntry(
                    raw_number=r["raw_number"],
                    run_date=run_date,
                    origin=r["origin"],
                    departure=r["departure"],
                    destination=r["destination"],
                    arrival=r["arrival"],
                    stock=r["stock"],
                    units=r["units"],
                    pdf_name=r["pdf_name"],
                    period_start=_to_date(r["period_start"]),
                    period_end=_to_date(r["period_end"]),
                )
            )
        return result

    def pdfs(self) -> list[PdfInfo]:
        if not self.available():
            return []
        with db.open_db(self.path, readonly=True) as conn:
            try:
                rows = conn.execute("SELECT * FROM pdfs ORDER BY priority DESC").fetchall()
            except sqlite3.OperationalError:
                return []
        return [PdfInfo(r["name"], _to_date(r["period_start"]), _to_date(r["period_end"])) for r in rows]

    def coverage_end(self) -> date | None:
        ends = [p.period_end for p in self.pdfs() if p.period_end]
        return max(ends) if ends else None
