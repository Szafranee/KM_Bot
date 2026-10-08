"""WSGI application for Phusion Passenger (webhook mode).

Routes:

* ``POST <webhook path>`` - Telegram updates. The ``X-Telegram-Bot-Api-Secret-Token`` header must match
  ``WEBHOOK_SECRET``. The response is sent after the update has been processed, so Passenger does not
  consider the process idle while the bot is still working.
* ``GET /health`` - liveness and data status (JSON).
* ``GET /img/<file>.jpg`` - rolling stock photos used as link previews in bot messages.

python-telegram-bot is asynchronous while WSGI is not: a single event loop runs in a background thread per
process and requests hand updates over with ``run_coroutine_threadsafe``. The loop is created lazily on the
first request because Passenger may fork the process after importing this module.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import threading
from collections.abc import Callable, Iterable
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import Application

from km_bot.bot.app import build_application
from km_bot.bot.services import Services
from km_bot.config import ASSETS_DIR, Settings, get_settings
from km_bot.logging_setup import setup_logging

log = logging.getLogger(__name__)

MAX_BODY = 1 << 20
PROCESS_TIMEOUT = 50
IMAGE_RE = re.compile(r"^/img/([a-z0-9_]+\.jpg)$")


class BotRunner:
    def __init__(self, services: Services, app_factory: Callable[[Services], Application] | None = None):
        self.services = services
        self.app_factory = app_factory or (lambda svc: build_application(svc, with_updater=False))
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: Application | None = None

    def _ensure_started(self) -> tuple[asyncio.AbstractEventLoop, Application]:
        with self._lock:
            if self._loop is None or self._app is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="telegram-loop", daemon=True).start()
                app = self.app_factory(self.services)
                asyncio.run_coroutine_threadsafe(app.initialize(), loop).result(timeout=30)
                self._loop, self._app = loop, app
                log.info("Telegram application initialised")
            return self._loop, self._app

    def process(self, payload: dict) -> None:
        loop, app = self._ensure_started()
        update = Update.de_json(payload, app.bot)
        future = asyncio.run_coroutine_threadsafe(app.process_update(update), loop)
        try:
            future.result(timeout=PROCESS_TIMEOUT)
        except TimeoutError:
            log.warning("Update %s is still being processed after %ss", update.update_id, PROCESS_TIMEOUT)


def _respond(start_response, status: str, body: bytes, content_type: str = "application/json") -> list[bytes]:
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


def _json(start_response, status: str, payload: dict) -> list[bytes]:
    return _respond(start_response, status, json.dumps(payload, ensure_ascii=False).encode())


def create_app(settings: Settings | None = None, runner: BotRunner | None = None):
    settings = settings or get_settings()
    services = runner.services if runner else Services.from_settings(settings)
    runner = runner or BotRunner(services)
    webhook_path = urlparse(settings.webhook_url).path.rstrip("/") or "/telegram"

    def application(environ: dict, start_response) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/").rstrip("/") or "/"

        if method == "POST" and path == webhook_path:
            token = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
            if not settings.webhook_secret or not hmac.compare_digest(token, settings.webhook_secret):
                return _json(start_response, "403 Forbidden", {"error": "forbidden"})
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY:
                return _json(start_response, "400 Bad Request", {"error": "invalid body"})
            try:
                payload = json.loads(environ["wsgi.input"].read(length))
            except (ValueError, KeyError):
                return _json(start_response, "400 Bad Request", {"error": "invalid json"})
            try:
                runner.process(payload)
            except Exception:
                # Always acknowledge: Telegram would otherwise retry the same update over and over.
                log.exception("Failed to process update")
            return _json(start_response, "200 OK", {"ok": True})

        if method == "GET" and path in ("/", "/health"):
            meta = services.timetable.meta()
            return _json(
                start_response,
                "200 OK",
                {
                    "status": "ok",
                    "timetable": meta.get("feed_version"),
                    "timetable_end": meta.get("feed_end_date"),
                    "rolling_stock_until": str(services.rolling_stock.coverage_end() or ""),
                },
            )

        if method == "GET" and (match := IMAGE_RE.match(path)):
            image = ASSETS_DIR / "trains" / match.group(1)
            if image.is_file():
                body = image.read_bytes()
                start_response(
                    "200 OK",
                    [
                        ("Content-Type", "image/jpeg"),
                        ("Content-Length", str(len(body))),
                        ("Cache-Control", "public, max-age=604800"),
                    ],
                )
                return [body]

        return _json(start_response, "404 Not Found", {"error": "not found"})

    return application


def _lazy_application():
    app = None
    lock = threading.Lock()

    def application(environ, start_response):
        nonlocal app
        if app is None:
            with lock:
                if app is None:
                    setup_logging()
                    app = create_app()
        return app(environ, start_response)

    return application


application = _lazy_application()
