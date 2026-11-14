"""대시보드 접근 제한.

DASHBOARD_PASSWORD가 설정되어 있으면 로그인한 브라우저만 API를 쓸 수 있다.
개인용이라 계정은 없고 비밀번호 하나다. 설정하지 않으면 제한이 없으므로 외부에 열지 않는다.
"""

import hashlib
import hmac
import time

COOKIE_NAME = "tw_session"
SESSION_SECONDS = 30 * 24 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 300


def _key(password: str) -> bytes:
    return hashlib.sha256(f"tennis-watch-session:{password}".encode()).digest()


def make_token(password: str, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + SESSION_SECONDS)
    signature = hmac.new(_key(password), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def token_valid(password: str, token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, signature = token.split(".", 1)
    if not expires.isdigit() or int(expires) < (now if now is not None else time.time()):
        return False
    expected = hmac.new(_key(password), expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def password_matches(expected: str, given: str) -> bool:
    return hmac.compare_digest(expected.encode(), given.encode())


class LoginThrottle:
    """비밀번호를 연속으로 틀리면 잠시 로그인 시도를 막는다."""

    def __init__(self):
        self.failures = 0
        self.locked_until = 0.0

    def locked_for(self, now: float | None = None) -> int:
        remaining = self.locked_until - (now if now is not None else time.time())
        return max(0, int(remaining + 0.999))

    def record(self, success: bool, now: float | None = None) -> None:
        if success:
            self.failures = 0
            return
        self.failures += 1
        if self.failures >= MAX_FAILURES:
            self.locked_until = (now if now is not None else time.time()) + LOCK_SECONDS
            self.failures = 0
