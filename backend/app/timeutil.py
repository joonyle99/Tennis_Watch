"""시간 처리 규칙: DB와 내부 로직은 UTC, 사이트 값과 화면 표시는 한국시간."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def utcnow() -> datetime:
    return datetime.now(UTC)


def kst_to_utc(naive_kst: datetime) -> datetime:
    """시간대 표기가 없는 한국시간 값을 UTC로 바꾼다."""
    if naive_kst.tzinfo is not None:
        raise ValueError("시간대가 없는 값이어야 합니다")
    return naive_kst.replace(tzinfo=KST).astimezone(UTC)


def to_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("시간대가 있는 값이어야 합니다")
    return value.astimezone(KST)


def kst_datetime(day: date, at: time) -> datetime:
    """한국 날짜와 시각을 UTC 시각으로 바꾼다."""
    return kst_to_utc(datetime.combine(day, at))


def kst_today(now: datetime | None = None) -> date:
    return to_kst(now or utcnow()).date()
