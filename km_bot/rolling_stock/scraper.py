"""Downloads the current "Zestawienie pociągów KM ..." PDFs from the Koleje Mazowieckie website."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
from bs4 import BeautifulSoup

from km_bot.rolling_stock.pdf_parser import period_from_filename

log = logging.getLogger(__name__)

BASE_URL = "https://www.mazowieckie.com.pl"
CATEGORY_URL = f"{BASE_URL}/pl/kategoria/tabele-rozkladow-jazdy"
PDF_NAME_PREFIX = "Zestawienie pociągów KM"
USER_AGENT = "KM_Bot/2.0 (Telegram bot; occasional timetable download)"


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def find_pdf_links(client: httpx.Client, category_url: str = CATEGORY_URL) -> dict[str, str]:
    """Returns {file name: absolute URL} of rolling stock PDFs linked from the timetable period pages."""
    response = client.get(category_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    period_pages = sorted(
        {
            urljoin(category_url, a["href"])
            for a in soup.find_all("a", href=True)
            if "rozklad-jazdy" in a["href"] and "/kategoria/" not in a["href"]
        }
    )
    log.info("Found %d timetable period pages", len(period_pages))

    pdfs: dict[str, str] = {}
    for page_url in period_pages:
        try:
            page = client.get(page_url)
            page.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Cannot fetch %s: %s", page_url, exc)
            continue
        for a in BeautifulSoup(page.text, "html.parser").find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue
            name = unquote(href.rsplit("/", 1)[-1])
            if name.startswith(PDF_NAME_PREFIX):
                pdfs[_safe_filename(name)] = urljoin(page_url, href)
    log.info("Found %d rolling stock PDFs", len(pdfs))
    return pdfs


def is_expired(name: str, today: date) -> bool:
    period = period_from_filename(name)
    return period is not None and period.end < today - timedelta(days=1)


def download_current_pdfs(pdf_dir: Path, old_dir: Path, today: date) -> list[Path]:
    """Downloads new PDFs, moves expired ones to ``old_dir`` and returns the current PDF paths."""
    pdf_dir.mkdir(parents=True, exist_ok=True)
    with _client() as client:
        links = find_pdf_links(client)
        for name, url in links.items():
            target = pdf_dir / name
            if target.exists() or (old_dir / name).exists() or is_expired(name, today):
                continue
            log.info("Downloading %s", name)
            response = client.get(url)
            response.raise_for_status()
            tmp = target.with_suffix(".part")
            tmp.write_bytes(response.content)
            tmp.replace(target)
    archive_expired_pdfs(pdf_dir, old_dir, today)
    return sorted(pdf_dir.glob("*.pdf"))


def archive_expired_pdfs(pdf_dir: Path, old_dir: Path, today: date) -> None:
    for path in pdf_dir.glob("*.pdf"):
        if is_expired(path.name, today):
            old_dir.mkdir(parents=True, exist_ok=True)
            log.info("Archiving expired %s", path.name)
            shutil.move(path, old_dir / path.name)
