import json

import httpx
import pytest

from app.services.telegram import TelegramClient, TelegramError

TOKEN = "123456:SECRET-TOKEN"


def make_client(handler, token=TOKEN, chat_id="42"):
    return TelegramClient(token, chat_id, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_send_message_posts_to_the_bot_api():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    make_client(handler).send_message("안녕하세요")

    request = requests[0]
    assert str(request.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = json.loads(request.content)
    assert (body["chat_id"], body["text"]) == ("42", "안녕하세요")
    assert body["link_preview_options"] == {"is_disabled": True}


def test_long_messages_are_cut_to_the_telegram_limit():
    sent = []
    client = make_client(lambda r: sent.append(json.loads(r.content)) or httpx.Response(200, json={"ok": True}))
    client.send_message("가" * 5000)
    assert len(sent[0]["text"]) == 4096


def test_rate_limit_reports_retry_after():
    body = {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 17}}
    with pytest.raises(TelegramError) as exc:
        make_client(lambda r: httpx.Response(429, json=body)).send_message("x")
    assert (exc.value.retry_after, exc.value.permanent) == (17, False)


def test_rate_limit_without_body_uses_header_or_default():
    with pytest.raises(TelegramError) as exc:
        make_client(lambda r: httpx.Response(429, headers={"retry-after": "5"})).send_message("x")
    assert exc.value.retry_after == 5
    with pytest.raises(TelegramError) as exc:
        make_client(lambda r: httpx.Response(429)).send_message("x")
    assert exc.value.retry_after == 30


@pytest.mark.parametrize(
    ("status", "description", "permanent"),
    [
        (401, "Unauthorized", True),  # 토큰 오류
        (400, "Bad Request: chat not found", True),  # 채팅 ID 오류
        (403, "Forbidden: bot was blocked by the user", True),
        (500, "Internal Server Error", False),
        (502, None, False),
    ],
)
def test_client_errors_are_permanent_and_server_errors_are_retryable(status, description, permanent):
    body = {"ok": False, "description": description} if description else None
    response = httpx.Response(status, json=body) if body else httpx.Response(status)
    with pytest.raises(TelegramError) as exc:
        make_client(lambda r: response).send_message("x")
    assert exc.value.permanent is permanent and exc.value.retry_after is None


def test_errors_never_contain_the_token():
    def boom(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)

    for handler in (boom, lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})):
        with pytest.raises(TelegramError) as exc:
            make_client(handler).send_message("x")
        assert TOKEN not in str(exc.value) and "SECRET" not in repr(exc.value)
        assert exc.value.__cause__ is None


def test_missing_configuration_is_a_permanent_error_without_any_request():
    def fail(request):
        raise AssertionError("요청하면 안 된다")

    with pytest.raises(TelegramError, match="TELEGRAM_BOT_TOKEN") as exc:
        make_client(fail, token="").send_message("x")
    assert exc.value.permanent
    with pytest.raises(TelegramError, match="TELEGRAM_CHAT_ID"):
        make_client(fail, chat_id="").send_message("x")
    assert make_client(fail, chat_id="").configured is False
    assert make_client(fail).configured is True


def test_bot_name_and_recent_chats():
    def handler(request):
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"username": "my_tennis_bot"}})
        updates = [
            {"update_id": 1, "message": {"chat": {"id": 777, "type": "private", "first_name": "준"}}},
            {"update_id": 2, "message": {"chat": {"id": 777, "type": "private", "first_name": "준"}}},
            {"update_id": 3, "message": {"chat": {"id": -100123, "type": "group", "title": "테니스"}}},
            {"update_id": 4, "edited_message": {}},
        ]
        return httpx.Response(200, json={"ok": True, "result": updates})

    client = make_client(handler)
    assert client.bot_name() == "my_tennis_bot"
    assert client.recent_chats() == [
        {"chat_id": "777", "type": "private", "name": "준"},
        {"chat_id": "-100123", "type": "group", "name": "테니스"},
    ]
