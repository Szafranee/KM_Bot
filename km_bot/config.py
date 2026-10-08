"""Application settings loaded from environment variables (and an optional `.env` file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
TZ = ZoneInfo("Europe/Warsaw")


def now() -> datetime:
    """Current wall-clock time in Warsaw (all timetable data is local time)."""
    return datetime.now(TZ)


def _int_set(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    return frozenset(int(part) for part in raw.replace(";", ",").split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    telegram_token: str = ""
    plk_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    webhook_url: str = ""
    webhook_secret: str = ""
    public_base_url: str = ""
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    data_dir: Path = PROJECT_DIR / "data"

    @property
    def timetable_db(self) -> Path:
        return self.data_dir / "timetable.sqlite"

    @property
    def rolling_stock_db(self) -> Path:
        return self.data_dir / "rolling_stock.sqlite"

    @property
    def app_db(self) -> Path:
        return self.data_dir / "app.sqlite"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdf"

    @property
    def old_pdf_dir(self) -> Path:
        return self.data_dir / "old"

    @property
    def gtfs_path(self) -> Path:
        return self.data_dir / "polish_trains.zip"

    @property
    def image_base_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/img" if self.public_base_url else ""


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_DIR / ".env")
    data_dir = os.getenv("DATA_DIR")
    return Settings(
        telegram_token=os.getenv("TELEGRAM_API_TOKEN", ""),
        plk_api_key=os.getenv("PLK_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", Settings.gemini_model),
        webhook_url=os.getenv("WEBHOOK_URL", ""),
        webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
        public_base_url=os.getenv("PUBLIC_BASE_URL", ""),
        allowed_user_ids=_int_set(os.getenv("ALLOWED_USER_IDS")),
        data_dir=Path(data_dir) if data_dir else PROJECT_DIR / "data",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
