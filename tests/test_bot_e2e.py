"""End-to-end tests: real python-telegram-bot Application with a fake Bot API transport, fed through WSGI."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from telegram.ext import Application
from telegram.request import BaseRequest, RequestData

from km_bot.bot.app import build_application
from km_bot.web import BotRunner, create_app
from tests.conftest import at

CHAT = {"id": 10, "type": "private", "first_name": "Test"}
USER = {"id": 1, "is_bot": False, "first_name": "Test"}


class FakeTelegram(BaseRequest):
    """Records Bot API calls and answers them like Telegram would."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def read_timeout(self) -> float:
        return 5.0

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def do_request(self, url, method, request_data: RequestData | None = None, **kwargs) -> tuple[int, bytes]:
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        self.calls.append((endpoint, params))
        if endpoint == "getMe":
            result: Any = {"id": 999, "is_bot": True, "first_name": "KM", "username": "kmkobot"}
        elif endpoint in ("sendMessage", "editMessageText"):
            result = {"message_id": 5, "date": 0, "chat": CHAT, "text": params.get("text", "")}
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def sent(self, endpoint: str) -> list[dict[str, Any]]:
        return [params for name, params in self.calls if name == endpoint]


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def wsgi(services, telegram, monkeypatch):
    monkeypatch.setattr("km_bot.bot.handlers.now", lambda: at(8, 0))

    def factory(svc) -> Application:
        builder = Application.builder().token(svc.settings.telegram_token).request(telegram)
        return build_application(svc, with_updater=False, builder=builder.get_updates_request(FakeTelegram()))

    return create_app(services.settings, BotRunner(services, factory))


_update_id = 0


def call(app, payload: dict | None, *, path="/telegram", method="POST", secret="s3cret") -> tuple[str, bytes]:
    body = json.dumps(payload).encode() if payload is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": secret,
    }
    status: list[str] = []
    chunks = app(environ, lambda s, headers: status.append(s))
    return status[0], b"".join(chunks)


def message(text: str) -> dict:
    global _update_id
    _update_id += 1
    msg = {"message_id": _update_id, "date": 0, "chat": CHAT, "from": USER, "text": text}
    if text.startswith("/"):  # Telegram marks commands with an entity
        msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return {"update_id": _update_id, "message": msg}


def press(data: str) -> dict:
    global _update_id
    _update_id += 1
    return {
        "update_id": _update_id,
        "callback_query": {
            "id": str(_update_id),
            "from": USER,
            "chat_instance": "x",
            "data": data,
            "message": {
                "message_id": 5,
                "date": 0,
                "chat": CHAT,
                "from": {**USER, "id": 999, "is_bot": True},
                "text": "old",
            },
        },
    }


def last_text(telegram: FakeTelegram, endpoint: str = "sendMessage") -> str:
    return telegram.sent(endpoint)[-1]["text"]


def buttons(params: dict) -> list[str]:
    markup = params.get("reply_markup")
    markup = json.loads(markup) if isinstance(markup, str) else markup
    return [b.get("callback_data") or b.get("text") for row in markup.get("inline_keyboard", []) for b in row]


def test_health_and_images(wsgi):
    status, body = call(wsgi, None, path="/health", method="GET")
    assert status == "200 OK" and json.loads(body)["timetable"] == "test"
    status, body = call(wsgi, None, path="/img/flirt_3.jpg", method="GET")
    assert status == "200 OK" and body[:2] == b"\xff\xd8"
    assert call(wsgi, None, path="/img/../.env", method="GET")[0] == "404 Not Found"
    assert call(wsgi, None, path="/nope", method="GET")[0] == "404 Not Found"


def test_webhook_rejects_wrong_secret_and_bad_bodies(wsgi, telegram):
    assert call(wsgi, message("/start"), secret="wrong")[0] == "403 Forbidden"
    assert call(wsgi, None)[0] == "400 Bad Request"
    assert telegram.calls == []


def test_start_shows_menu_keyboard(wsgi, telegram):
    assert call(wsgi, message("/start"))[0] == "200 OK"
    params = telegram.sent("sendMessage")[-1]
    assert "Kolei Mazowieckich" in params["text"]
    assert "Odjazdy" in json.dumps(params["reply_markup"], ensure_ascii=False)


def test_station_search_and_trip_details(wsgi, telegram):
    call(wsgi, message("Śródmieście"))
    board = telegram.sent("sendMessage")[-1]
    assert "Warszawa Śródmieście" in board["text"] and "91450/1" in board["text"]
    trip_button = next(b for b in buttons(board) if b.startswith("T:PKM_2026_1:"))

    call(wsgi, press(trip_button))
    card = telegram.sent("editMessageText")[-1]
    assert "Pruszków → Warszawa Wschodnia" in card["text"]
    assert telegram.sent("answerCallbackQuery")

    watch_button = next(b for b in buttons(card) if b.startswith("W+:"))
    call(wsgi, press(watch_button))
    assert "Obserwuję" in telegram.sent("answerCallbackQuery")[-1]["text"]
    call(wsgi, message("🔔 Obserwowane"))
    assert "Obserwowane pociągi" in last_text(telegram)


def test_train_number(wsgi, telegram):
    call(wsgi, message("91450"))
    assert "Flirt 3" in last_text(telegram)


def test_route_query_and_saving(wsgi, telegram):
    call(wsgi, message("Pruszków > Wschodnia"))
    view = telegram.sent("sendMessage")[-1]
    assert "Pruszków → Warszawa Wschodnia" in view["text"]
    call(wsgi, press("R+:104:103"))
    assert "Trasa zapisana" in telegram.sent("answerCallbackQuery")[-1]["text"]
    call(wsgi, message("🧭 Moje trasy"))
    assert any(b.startswith("R:") for b in buttons(telegram.sent("sendMessage")[-1]))


def test_route_wizard(wsgi, telegram):
    call(wsgi, press("M:newroute"))
    assert "Skąd jedziesz?" in last_text(telegram)
    call(wsgi, message("Pruszków"))
    assert "Dokąd jedziesz z <b>Pruszków</b>?" in last_text(telegram)
    call(wsgi, message("Wschodnia"))
    assert "Pruszków → Warszawa Wschodnia" in last_text(telegram)
    assert any(b.startswith("R-:") for b in buttons(telegram.sent("sendMessage")[-1]))  # saved automatically


def test_ambiguous_station_offers_choice(wsgi, telegram):
    call(wsgi, message("Warszawa"))
    view = telegram.sent("sendMessage")[-1]
    assert "Którą stację" in view["text"]
    call(wsgi, press(buttons(view)[0]))
    assert "Odjazdy KM i SKM" in last_text(telegram, "editMessageText")


def test_favourites_flow(wsgi, telegram):
    call(wsgi, press("F+:102"))
    assert "Dodano do ulubionych" in telegram.sent("answerCallbackQuery")[-1]["text"]
    call(wsgi, message("⭐ Ulubione"))
    assert "D:102:0" in buttons(telegram.sent("sendMessage")[-1])


def test_location(wsgi, telegram):
    update = message("")
    del update["message"]["text"]
    update["message"]["location"] = {"latitude": 52.2295, "longitude": 21.0080}
    call(wsgi, update)
    assert "Najbliższe stacje" in last_text(telegram)


def test_access_control(services, telegram, monkeypatch):
    from dataclasses import replace

    services.settings = replace(services.settings, allowed_user_ids=frozenset({42}))

    def factory(svc) -> Application:
        builder = Application.builder().token(svc.settings.telegram_token).request(telegram)
        return build_application(svc, with_updater=False, builder=builder.get_updates_request(FakeTelegram()))

    app = create_app(services.settings, BotRunner(services, factory))
    call(app, message("Śródmieście"))
    assert "prywatny" in last_text(telegram)


def test_errors_are_acknowledged(wsgi, telegram, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database exploded")

    monkeypatch.setattr("km_bot.bot.views.departures_view", boom)
    status, _ = call(wsgi, message("Śródmieście"))
    assert status == "200 OK"
    assert "Coś poszło nie tak" in last_text(telegram)


def test_number_typed_during_route_wizard_cancels_it(wsgi, telegram):
    call(wsgi, press("M:newroute"))
    call(wsgi, message("91450"))
    assert "Flirt 3" in last_text(telegram)
    call(wsgi, message("Śródmieście"))
    assert "Odjazdy KM i SKM" in last_text(telegram)
