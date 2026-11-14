"""Telegram Bot API 클라이언트.

요청 주소에 봇 토큰이 들어가므로, 예외 메시지와 로그에 주소나 원래 예외를 싣지 않는다.
"""

import httpx

API_BASE = "https://api.telegram.org"
MESSAGE_LIMIT = 4096


class TelegramError(Exception):
    def __init__(self, message: str, *, retry_after: int | None = None, permanent: bool = False):
        super().__init__(message)
        # 429 응답이 알려 준 대기 시간(초)
        self.retry_after = retry_after
        # 다시 보내도 소용없는 오류(토큰·채팅 ID 문제 등)
        self.permanent = permanent


class TelegramClient:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None, timeout: float = 15.0):
        self.token = token
        self.chat_id = chat_id
        self.client = client or httpx.Client(timeout=timeout)

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _call(self, method: str, payload: dict | None = None) -> dict:
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다", permanent=True)
        try:
            response = self.client.post(f"{API_BASE}/bot{self.token}/{method}", json=payload or {})
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram 요청 실패 ({type(exc).__name__})") from None

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200 and body.get("ok"):
            return body.get("result") or {}

        description = str(body.get("description") or f"HTTP {response.status_code}")
        if response.status_code == 429:
            retry_after = (body.get("parameters") or {}).get("retry_after")
            if not isinstance(retry_after, int):
                header = response.headers.get("retry-after", "")
                retry_after = int(header) if header.isdigit() else 30
            raise TelegramError(f"Telegram 전송 제한: {retry_after}초 후 재시도", retry_after=retry_after)
        # 4xx는 요청 자체가 잘못된 것이라 그대로 다시 보내도 실패한다.
        permanent = 400 <= response.status_code < 500
        raise TelegramError(f"Telegram 오류 {response.status_code}: {description}", permanent=permanent)

    def send_message(self, text: str) -> None:
        if not self.chat_id:
            raise TelegramError("TELEGRAM_CHAT_ID가 설정되지 않았습니다", permanent=True)
        self._call(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": text[:MESSAGE_LIMIT],
                "link_preview_options": {"is_disabled": True},
            },
        )

    def bot_name(self) -> str:
        """토큰이 유효한지 확인하고 봇 이름을 돌려준다."""
        me = self._call("getMe")
        return me.get("username") or me.get("first_name") or ""

    def recent_chats(self) -> list[dict]:
        """봇에게 최근 메시지를 보낸 채팅 목록. 채팅 ID를 찾는 데 쓴다."""
        updates = self._call("getUpdates", {"limit": 50, "timeout": 0})
        chats: dict[int, dict] = {}
        for update in updates if isinstance(updates, list) else []:
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            if "id" in chat:
                chats[chat["id"]] = {
                    "chat_id": str(chat["id"]),
                    "type": chat.get("type"),
                    "name": chat.get("title") or chat.get("first_name") or chat.get("username"),
                }
        return list(chats.values())
