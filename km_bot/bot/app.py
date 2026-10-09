"""Construction of the python-telegram-bot ``Application``."""

from __future__ import annotations

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from km_bot.bot import handlers
from km_bot.bot.services import Services

COMMANDS = [
    BotCommand("odjazdy", "Odjazdy ze stacji, np. /odjazdy Śródmieście"),
    BotCommand("pociag", "Pociąg po numerze, np. /pociag 91450"),
    BotCommand("trasy", "Moje zapisane trasy"),
    BotCommand("ulubione", "Ulubione stacje"),
    BotCommand("obserwowane", "Obserwowane pociągi"),
    BotCommand("samouczek", "Samouczek krok po kroku"),
    BotCommand("pomoc", "Jak korzystać z bota"),
    BotCommand("info", "Stan danych rozkładowych"),
]


# python-telegram-bot defaults to a 5 s read timeout; shared hosting occasionally needs longer.
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 15


def default_builder(token: str):
    return (
        Application.builder()
        .token(token)
        .connect_timeout(CONNECT_TIMEOUT)
        .read_timeout(READ_TIMEOUT)
        .write_timeout(READ_TIMEOUT)
        .pool_timeout(CONNECT_TIMEOUT)
    )


def build_application(svc: Services, *, with_updater: bool = True, builder=None) -> Application:
    builder = builder or default_builder(svc.settings.telegram_token)
    if not with_updater:
        builder = builder.updater(None)
    app = builder.build()
    app.bot_data["services"] = svc
    register_handlers(app)
    return app


def register_handlers(app: Application) -> None:
    app.add_handler(TypeHandler(Update, handlers.check_access), group=-1)
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler(["pomoc", "help"], handlers.help_command))
    app.add_handler(CommandHandler(["anuluj", "cancel"], handlers.cancel))
    app.add_handler(CommandHandler(["samouczek", "tutorial"], handlers.tutorial_command))
    app.add_handler(CommandHandler(["odjazdy", "stacja"], handlers.departures_command))
    app.add_handler(CommandHandler(["pociag", "numer"], handlers.number_command))
    app.add_handler(CommandHandler(["trasy", "trasa"], handlers.routes_command))
    app.add_handler(CommandHandler("ulubione", handlers.favorites_command))
    app.add_handler(CommandHandler(["obserwowane", "sledzone"], handlers.watches_command))
    app.add_handler(CommandHandler("info", handlers.info_command))
    app.add_handler(MessageHandler(filters.LOCATION, handlers.location_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))
    app.add_handler(CallbackQueryHandler(handlers.callback_query))
    app.add_error_handler(handlers.error_handler)


async def configure_bot(app: Application) -> None:
    """One-time bot profile setup (command menu)."""
    await app.bot.set_my_commands(COMMANDS)
