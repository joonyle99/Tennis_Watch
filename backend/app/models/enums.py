from enum import StrEnum


class SlotStatus(StrEnum):
    """예약 가능 상태. 공고 단위와 슬롯 단위에 같이 쓴다."""

    AVAILABLE = "AVAILABLE"  # 예약 가능
    UNAVAILABLE = "UNAVAILABLE"  # 예약 불가 또는 마감
    NOT_OPEN = "NOT_OPEN"  # 접수 시작 전
    CLOSED = "CLOSED"  # 휴장 또는 운영 중단
    UNKNOWN = "UNKNOWN"  # 상태 확인 불가


class DataSource(StrEnum):
    AUTO = "AUTO"  # 사이트에서 자동 수집
    MANUAL = "MANUAL"  # 사용자가 직접 입력


class RuleType(StrEnum):
    MONTHLY = "MONTHLY"  # 매월 특정 날짜·시각
    DAYS_BEFORE_USE = "DAYS_BEFORE_USE"  # 이용일 기준 N일 전
    ONE_TIME = "ONE_TIME"  # 특정 일시의 일회성 오픈
    NOTICE = "NOTICE"  # 예약 공고에 명시된 접수 시작 일시


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"  # 실제 공고·사이트 값과 일치함을 확인
    INFERRED = "INFERRED"  # 관측값에서 추정, 검증 전
    UNVERIFIED = "UNVERIFIED"  # 확인한 적 없음
    CONFLICT = "CONFLICT"  # 자동 수집값과 수동 입력값이 다름


class DayType(StrEnum):
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"  # 주말 및 공휴일
    UNKNOWN = "UNKNOWN"


class TimeBand(StrEnum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    UNKNOWN = "UNKNOWN"


class ChangeKind(StrEnum):
    """상태 변경의 종류. 알림 여부 판단의 근거다."""

    INITIAL = "INITIAL"  # 최초 수집
    OPENED = "OPENED"  # 접수 시작 전 → 예약 가능
    REOPENED = "REOPENED"  # 예약 불가 → 예약 가능 (접수 재개, 빈 코트)
    OTHER = "OTHER"


class NotificationType(StrEnum):
    OPENING_SOON = "OPENING_SOON"  # 예약 오픈 예정
    OPENED = "OPENED"  # 실제 예약 오픈 확인
    REOPENED = "REOPENED"  # 접수 재개(빈 코트)
    SYSTEM_ERROR = "SYSTEM_ERROR"  # 지속적인 수집 실패


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
