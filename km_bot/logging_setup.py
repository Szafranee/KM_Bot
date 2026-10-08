"""Logging configuration shared by the WSGI app and CLI commands."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_configured = False


def setup_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = os.getenv("LOG_FILE")
    if log_file:
        handlers.append(RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    logging.basicConfig(
        level=(level or os.getenv("LOG_LEVEL") or "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    # Request logs of httpx (used by python-telegram-bot) are too chatty at INFO level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
