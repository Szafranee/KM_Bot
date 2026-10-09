"""Command line interface: ``python -m km_bot <command>``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from pathlib import Path

from km_bot.config import Settings, get_settings, now
from km_bot.logging_setup import setup_logging

log = logging.getLogger("km_bot")

TRACKER_INTERVAL = 120


def refresh_gtfs(settings: Settings, force: bool = False) -> None:
    from km_bot import db
    from km_bot.timetable.gtfs_import import download_feed, import_feed

    downloaded = download_feed(settings.gtfs_path, force=force)
    if downloaded or force or not db.exists(settings.timetable_db):
        import_feed(settings.gtfs_path, settings.timetable_db)


def refresh_rolling_stock(settings: Settings, download: bool = True) -> None:
    from km_bot.rolling_stock.gemini_fallback import GeminiDateConverter
    from km_bot.rolling_stock.importer import build_database
    from km_bot.rolling_stock.scraper import archive_expired_pdfs, download_current_pdfs

    today = now().date()
    if download:
        try:
            download_current_pdfs(settings.pdf_dir, settings.old_pdf_dir, today)
        except Exception:
            log.exception("Downloading rolling stock PDFs failed - using the files already on disk")
    archive_expired_pdfs(settings.pdf_dir, settings.old_pdf_dir, today)
    pdfs = sorted(settings.pdf_dir.glob("*.pdf"))
    gemini = GeminiDateConverter(
        settings.gemini_api_key, settings.gemini_model, settings.data_dir / "gemini_dates_cache.json"
    )
    report = build_database(pdfs, settings.rolling_stock_db, gemini)
    for failure in report.failed:
        log.warning("Dates not converted: %s", failure)


def cmd_refresh(args: argparse.Namespace, settings: Settings) -> int:
    status = 0
    if not args.rolling_stock_only:
        try:
            refresh_gtfs(settings, force=args.force)
        except Exception:
            log.exception("Timetable refresh failed")
            status = 1
    if not args.gtfs_only:
        try:
            refresh_rolling_stock(settings, download=not args.no_download)
        except Exception:
            log.exception("Rolling stock refresh failed")
            status = 1
    return status


def cmd_import_pdf(args: argparse.Namespace, settings: Settings) -> int:
    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    for name in args.paths:
        source = Path(name)
        shutil.copy2(source, settings.pdf_dir / source.name)
        log.info("Copied %s", source.name)
    refresh_rolling_stock(settings, download=False)
    return 0


def _services(settings: Settings):
    from km_bot.bot.services import Services

    return Services.from_settings(settings)


def cmd_poll(args: argparse.Namespace, settings: Settings) -> int:
    from telegram import Update

    from km_bot.bot.app import build_application, configure_bot, default_builder
    from km_bot.bot.tracking import check_watches

    svc = _services(settings)

    async def tracker_loop(app) -> None:
        while True:
            try:
                await check_watches(svc, app.bot, now())
            except Exception:
                log.exception("Tracked trains check failed")
            await asyncio.sleep(TRACKER_INTERVAL)

    tasks: list[asyncio.Task] = []

    async def post_init(app) -> None:
        await configure_bot(app)
        tasks.append(asyncio.get_running_loop().create_task(tracker_loop(app)))

    async def post_stop(app) -> None:
        for task in tasks:
            task.cancel()

    builder = default_builder(settings.telegram_token).post_init(post_init).post_stop(post_stop)
    app = build_application(svc, builder=builder)
    log.warning("Polling mode - this removes the webhook of this bot token until `set-webhook` is run again.")
    app.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])
    return 0


async def _with_bot(settings: Settings, func):
    from telegram import Bot

    async with Bot(settings.telegram_token) as bot:
        return await func(bot)


def cmd_check_tracked(args: argparse.Namespace, settings: Settings) -> int:
    from km_bot.bot.tracking import check_watches

    svc = _services(settings)
    sent = asyncio.run(_with_bot(settings, lambda bot: check_watches(svc, bot, now())))
    log.info("Tracked trains checked, %d notifications sent", sent)
    return 0


def cmd_set_webhook(args: argparse.Namespace, settings: Settings) -> int:
    from telegram import Update

    from km_bot.bot.app import COMMANDS

    if not settings.webhook_url or not settings.webhook_secret:
        log.error("WEBHOOK_URL and WEBHOOK_SECRET must be set")
        return 1

    async def run(bot):
        await bot.set_webhook(
            settings.webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
            max_connections=4,
        )
        await bot.set_my_commands(COMMANDS)
        return await bot.get_webhook_info()

    info = asyncio.run(_with_bot(settings, run))
    log.info("Webhook set: %s (pending updates: %s)", info.url, info.pending_update_count)
    return 0


def cmd_delete_webhook(args: argparse.Namespace, settings: Settings) -> int:
    asyncio.run(_with_bot(settings, lambda bot: bot.delete_webhook()))
    log.info("Webhook deleted")
    return 0


def cmd_webhook_info(args: argparse.Namespace, settings: Settings) -> int:
    info = asyncio.run(_with_bot(settings, lambda bot: bot.get_webhook_info()))
    print(f"url: {info.url or '-'}")
    print(f"pending updates: {info.pending_update_count}")
    print(f"last error: {info.last_error_message or '-'} ({info.last_error_date or '-'})")
    return 0


def cmd_plk_check(args: argparse.Namespace, settings: Settings) -> int:
    from km_bot.realtime.plk import PlkProvider
    from km_bot.storage import Storage

    if not settings.plk_api_key:
        log.error("PLK_API_KEY is not set")
        return 1
    print(PlkProvider(Storage(settings.app_db), settings.plk_api_key, max_age=0).check())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="km_bot", description="Koleje Mazowieckie Telegram bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("poll", help="run the bot with long polling (local development)").set_defaults(func=cmd_poll)

    refresh = sub.add_parser("refresh-data", help="download and import the timetable and rolling stock lists")
    group = refresh.add_mutually_exclusive_group()
    group.add_argument("--gtfs-only", action="store_true", help="only the GTFS timetable")
    group.add_argument("--rolling-stock-only", action="store_true", help="only the rolling stock PDFs")
    refresh.add_argument("--force", action="store_true", help="re-download and re-import the timetable")
    refresh.add_argument("--no-download", action="store_true", help="use PDFs already in data/pdf")
    refresh.set_defaults(func=cmd_refresh)

    import_pdf = sub.add_parser("import-pdf", help="add rolling stock PDF files manually and rebuild")
    import_pdf.add_argument("paths", nargs="+")
    import_pdf.set_defaults(func=cmd_import_pdf)

    sub.add_parser("check-tracked", help="send notifications for tracked trains (cron)").set_defaults(
        func=cmd_check_tracked
    )
    sub.add_parser("set-webhook", help="register WEBHOOK_URL with Telegram").set_defaults(func=cmd_set_webhook)
    sub.add_parser("delete-webhook", help="remove the webhook").set_defaults(func=cmd_delete_webhook)
    sub.add_parser("webhook-info", help="show webhook status").set_defaults(func=cmd_webhook_info)
    sub.add_parser("plk-check", help="verify the PKP PLK API key").set_defaults(func=cmd_plk_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    settings = get_settings()
    needs_token = args.command in {"poll", "check-tracked", "set-webhook", "delete-webhook", "webhook-info"}
    if needs_token and not settings.telegram_token:
        log.error("TELEGRAM_API_TOKEN is not set")
        return 1
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
