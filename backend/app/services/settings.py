"""웹 화면에서 바꿀 수 있는 설정."""

from sqlalchemy.orm import Session

from app.models import AppSetting

DEFAULTS: dict[str, object] = {
    # 일반 수집 주기(분)
    "sync_interval_minutes": 5,
    # 접수 시작 전후로 해당 공고만 1분마다 확인하는 구간(분)
    "hot_window_before_minutes": 10,
    "hot_window_after_minutes": 5,
    # 상세 페이지를 다시 확인하는 주기(시간)와 한 번에 확인할 최대 건수
    "detail_refresh_hours": 24,
    "detail_batch_size": 10,
    # 연속 실패가 이 횟수에 이르면 상태를 UNKNOWN으로 바꾸고 오류 알림 대상이 된다
    "failure_threshold": 3,
    # 예약 오픈 알림 시점(분 전)
    "opening_alert_offsets_minutes": [1440, 60, 10],
    # 알림 전체 켜기/끄기. 끈 동안 생긴 알림은 보내지 않고 이력에만 남긴다
    "notifications_enabled": True,
    # 사이트 차단 등으로 수집을 멈춘 사유. None이면 수집 중
    "collection_paused_reason": None,
}

_VALIDATORS = {
    "sync_interval_minutes": lambda v: isinstance(v, int) and 1 <= v <= 1440,
    "hot_window_before_minutes": lambda v: isinstance(v, int) and 0 <= v <= 120,
    "hot_window_after_minutes": lambda v: isinstance(v, int) and 0 <= v <= 120,
    "detail_refresh_hours": lambda v: isinstance(v, int) and 1 <= v <= 720,
    "detail_batch_size": lambda v: isinstance(v, int) and 1 <= v <= 50,
    "failure_threshold": lambda v: isinstance(v, int) and 1 <= v <= 100,
    "opening_alert_offsets_minutes": lambda v: isinstance(v, list)
    and len(v) <= 10
    and all(isinstance(x, int) and 1 <= x <= 43200 for x in v),
    "notifications_enabled": lambda v: isinstance(v, bool),
    "collection_paused_reason": lambda v: v is None or isinstance(v, str),
}


def get_setting(session: Session, key: str):
    if key not in DEFAULTS:
        raise KeyError(key)
    row = session.get(AppSetting, key)
    return DEFAULTS[key] if row is None else row.value


def get_all(session: Session) -> dict[str, object]:
    stored = {row.key: row.value for row in session.query(AppSetting).all()}
    return {key: stored.get(key, default) for key, default in DEFAULTS.items()}


def set_setting(session: Session, key: str, value) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    wants_bool = isinstance(DEFAULTS[key], bool)
    if (isinstance(value, bool) and not wants_bool) or not _VALIDATORS[key](value):
        raise ValueError(f"{key}에 쓸 수 없는 값입니다: {value!r}")
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
