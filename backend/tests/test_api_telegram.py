import pytest

from app.api.routes import get_telegram
from app.main import app
from app.models import NotificationEvent, NotificationStatus, NotificationType
from app.services.telegram import TelegramError
from tests.helpers import T0


class StubTelegram:
    token = "123:SECRET"
    chat_id = "42"

    def __init__(self):
        self.sent = []
        self.error = None

    def bot_name(self):
        if self.error:
            raise self.error
        return "my_tennis_bot"

    def send_message(self, text):
        self.sent.append(text)

    def recent_chats(self):
        if self.error:
            raise self.error
        return [{"chat_id": "777", "type": "private", "name": "준"}]


@pytest.fixture
def telegram(client):
    stub = StubTelegram()
    app.dependency_overrides[get_telegram] = lambda: stub
    return stub


def test_connection_test_sends_a_message(client, telegram):
    body = client.post("/api/telegram/test").json()

    assert body == {"ok": True, "bot_name": "my_tennis_bot", "error": None}
    assert telegram.sent[0].startswith("[Tennis Watch] 연결 테스트")


def test_connection_test_reports_the_reason_on_failure(client, telegram):
    telegram.error = TelegramError("Telegram 오류 401: Unauthorized", permanent=True)
    body = client.post("/api/telegram/test").json()

    assert body == {"ok": False, "bot_name": None, "error": "Telegram 오류 401: Unauthorized"}
    assert telegram.sent == []


def test_status_never_exposes_secrets(client, telegram):
    response = client.get("/api/telegram")
    assert response.json() == {"token_set": True, "chat_id_set": True, "notifications_enabled": True}
    assert "SECRET" not in response.text

    telegram.chat_id = ""
    client.put("/api/settings", json={"values": {"notifications_enabled": False}})
    assert client.get("/api/telegram").json() == {
        "token_set": True, "chat_id_set": False, "notifications_enabled": False,
    }  # fmt: skip


def test_chats_help_find_the_chat_id(client, telegram):
    assert client.get("/api/telegram/chats").json() == [{"chat_id": "777", "type": "private", "name": "준"}]
    telegram.error = TelegramError("Telegram 오류 401: Unauthorized", permanent=True)
    assert client.get("/api/telegram/chats").status_code == 502


def test_notification_history_with_filters(client, session):
    session.add_all(
        [
            NotificationEvent(
                type=NotificationType.REOPENED, dedupe_key="a", message="재개",
                status=NotificationStatus.SENT, sent_at=T0, attempts=1,
            ),
            NotificationEvent(
                type=NotificationType.SYSTEM_ERROR, dedupe_key="b", message="오류",
                status=NotificationStatus.FAILED, last_error="chat not found", attempts=1,
            ),
        ]
    )  # fmt: skip
    session.commit()

    everything = client.get("/api/notifications").json()
    assert [(n["type"], n["status"]) for n in everything] == [("SYSTEM_ERROR", "FAILED"), ("REOPENED", "SENT")]
    assert everything[1]["sent_at"] == "2026-11-14T03:00:00Z"
    assert [n["message"] for n in client.get("/api/notifications", params={"status": "FAILED"}).json()] == ["오류"]
    assert [n["message"] for n in client.get("/api/notifications", params={"type": "REOPENED"}).json()] == ["재개"]
