from datetime import date
from pathlib import Path

import pymupdf
import pytest

from km_bot.rolling_stock import importer
from km_bot.rolling_stock.catalog import describe
from km_bot.rolling_stock.dates import Period
from km_bot.rolling_stock.gemini_fallback import GeminiDateConverter
from km_bot.rolling_stock.importer import expand_train_number
from km_bot.rolling_stock.pdf_parser import ParsedPdf, PdfRow, _parse_with_text, _row_from_cells, parse_pdf
from km_bot.rolling_stock.repository import RollingStockRepository
from km_bot.rolling_stock.scraper import is_expired
from tests.conftest import build_rolling_stock

PROJECT = Path(__file__).resolve().parent.parent


class TestCatalog:
    def test_multiple_units(self):
        info = describe("ER160", "2")
        assert info.label == "2× Flirt 3"
        assert info.image == "flirt_3.jpg"
        assert "269 miejsc" in info.details

    def test_locomotive_hauled_set(self):
        assert describe("EU47, Bs, P, B", "1, 1, 3, 2").label == "EU47 + 6 wagonów piętrowych"
        assert describe("EU47, B, Bs", "1, 1, 3").label == "EU47 + 4 wagony piętrowe"
        assert describe("111Eb, P, Ps", "1, 4, 1").label == "Gama 111Eb + 5 wagonów"

    def test_mixed_and_unknown(self):
        assert describe("EW60, EN57AKMw1", "1, 1").label == "EW60 + Kibel AKM"
        assert describe("XYZ9", "1").label == "XYZ9"
        assert describe("", "").label == "brak danych"

    def test_zero_count_is_ignored(self):
        assert describe("ER160", "0").label == "Flirt 3"


def test_expand_train_number():
    assert expand_train_number("91470/1") == ["91470", "91471"]
    assert expand_train_number("21308/9") == ["21308", "21309"]
    assert expand_train_number("19488/90") == ["19488", "19490"]
    assert expand_train_number("10780") == ["10780"]


def test_row_from_cells_skips_headers():
    assert _row_from_cells(["nr poc", "relacja handlowa", None, None, None, "zestawienie", None, "termin"]) is None
    row = _row_from_cells(
        ["51136", "CIECHANÓW", "8:44", "WARSZAWA ZACHODNIA PERON\n9", "10:01", "EU47, Bs, B", "1, 1, 3", "5-23 X\n(D)"]
    )
    assert row == PdfRow(
        "51136", "CIECHANÓW", "08:44", "WARSZAWA ZACHODNIA PERON 9", "10:01", "EU47, Bs, B", "1, 1, 3", "5-23 X (D)"
    )


def test_text_fallback_parser(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "okres obowiązywania 2026-10-04 - 2026-10-24",
        "nr poc",
        "relacja handlowa",
        "91470/1",
        "BŁONIE",
        "08:10",
        "WARSZAWA WSCHODNIA",
        "08:53",
        "ER160",
        "2",
        "4-24 X (C)",
        "51600",
        "CIECHANÓW",
        "05:35",
        "WARSZAWA ZACHODNIA PERON",
        "9",
        "07:08",
        "ER160",
        "2",
        "5-24 X",
        "(1-6)",
    ]
    page.insert_text((40, 40), "\n".join(lines), fontname="helv", fontsize=8)
    rows = _parse_with_text(doc)
    assert [r.number for r in rows] == ["91470/1", "51600"]
    assert rows[1].destination == "WARSZAWA ZACHODNIA PERON 9"
    assert rows[1].schedule == "5-24 X (1-6)"


@pytest.mark.skipif(not list((PROJECT / "data" / "pdf").glob("*.pdf")), reason="no downloaded PDF")
def test_real_pdf_parses_completely():
    pdf = sorted((PROJECT / "data" / "pdf").glob("*.pdf"))[-1]
    parsed = parse_pdf(pdf)
    assert parsed.period is not None
    assert len(parsed.rows) > 1000
    assert all(row.stock and row.units for row in parsed.rows)


def test_build_database_and_lookup(tmp_path, monkeypatch):
    repo = RollingStockRepository(build_rolling_stock(tmp_path, monkeypatch))
    friday, saturday = date(2026, 10, 9), date(2026, 10, 10)

    [weekday] = repo.lookup("91451", friday)
    assert weekday.stock == "ER160" and weekday.description.label == "2× Flirt 3"
    [weekend] = repo.lookup("91450", saturday)
    assert weekend.stock == "45WEkm"
    assert repo.lookup("51136", friday)[0].description.label == "EU47 + 5 wagonów piętrowych"
    assert repo.lookup("29404", friday) == []  # its dates could not be parsed
    assert repo.lookup("91450", date(2026, 10, 25)) == []  # outside the period
    assert repo.coverage_end() == date(2026, 10, 24)


def test_newer_pdf_wins(tmp_path, monkeypatch):
    old_pdf, new_pdf = tmp_path / "a.pdf", tmp_path / "b.pdf"
    old_pdf.write_bytes(b"x")
    new_pdf.write_bytes(b"x")
    parsed = {
        old_pdf: ParsedPdf(
            "a.pdf",
            Period(date(2026, 9, 26), date(2026, 10, 24)),
            [PdfRow("1001", "A", "08:00", "B", "09:00", "ER75", "1", "")],
        ),
        new_pdf: ParsedPdf(
            "b.pdf",
            Period(date(2026, 10, 4), date(2026, 10, 24)),
            [PdfRow("1001", "A", "08:00", "B", "09:00", "EN76", "1", "")],
        ),
    }
    monkeypatch.setattr(importer, "load_or_parse", lambda path: parsed[path])
    db_path = tmp_path / "rs.sqlite"
    importer.build_database([new_pdf, old_pdf], db_path, gemini=None)
    repo = RollingStockRepository(db_path)
    assert repo.lookup("1001", date(2026, 10, 10))[0].stock == "EN76"
    assert repo.lookup("1001", date(2026, 9, 30))[0].stock == "ER75"


def test_gemini_fallback_is_used_and_validated(tmp_path, monkeypatch):
    period = Period(date(2026, 10, 4), date(2026, 10, 24))
    converter = GeminiDateConverter("key", "model", tmp_path / "cache.json")
    answers = {
        "results": [
            {"input": "co drugi dzień", "dates": ["2026-10-04", "2026-10-06"]},
            {"input": "poza okresem", "dates": ["2026-11-04"]},
        ]
    }
    monkeypatch.setattr(converter, "_ask", lambda expressions, p: answers)
    result = converter.convert(["co drugi dzień", "poza okresem"], period)
    assert result == {"co drugi dzień": {date(2026, 10, 4), date(2026, 10, 6)}}
    # The valid answer is cached and no request is needed the second time.
    monkeypatch.setattr(converter, "_ask", lambda expressions, p: pytest.fail("should use cache"))
    again = GeminiDateConverter("key", "model", tmp_path / "cache.json").convert(["co drugi dzień"], period)
    assert again == {"co drugi dzień": {date(2026, 10, 4), date(2026, 10, 6)}}


def test_gemini_without_key_is_skipped(tmp_path):
    converter = GeminiDateConverter("", "model", tmp_path / "cache.json")
    assert converter.convert(["x"], Period(date(2026, 10, 4), date(2026, 10, 24))) == {}


def test_expired_pdf_names():
    today = date(2026, 10, 9)
    assert is_expired("Zestawienie pociągów KM kursujących w dniach 09 III-29 V 2025r._0.pdf", today)
    assert not is_expired("Zestawienie pociągów KM kursujących w dniach 4-24 X 2026r..pdf", today)
    assert not is_expired("Zestawienie bez dat.pdf", today)
