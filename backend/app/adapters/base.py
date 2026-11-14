"""사이트 어댑터의 공통 인터페이스.

사이트마다 데이터 형식이 달라도 수집 엔진은 여기 정의된 자료형만 다룬다.
새 사이트를 붙일 때는 SiteAdapter를 구현하고 registry에 등록한다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time

from app.models.enums import DayType, SlotStatus, TimeBand


class AdapterError(Exception):
    """수집 실패. 수집 엔진은 이 예외를 받으면 상태를 UNKNOWN으로 다룬다."""


class AuthError(AdapterError):
    """인증키가 없거나 유효하지 않다."""


class BlockedError(AdapterError):
    """사이트가 접근을 차단했다. 재시도하지 말고 수집을 멈춰야 한다."""


class ParseError(AdapterError):
    """응답 구조가 예상과 다르다. 사이트 개편 가능성이 있다."""


@dataclass(frozen=True)
class TitleInfo:
    """공고명에서 추출한 정보. 자유 텍스트라 확실하지 않다."""

    court_label: str | None = None
    day_type: DayType = DayType.UNKNOWN
    time_band: TimeBand = TimeBand.UNKNOWN
    lighting: bool = False


@dataclass(frozen=True)
class NoticeData:
    """목록 수집으로 얻는 공고 한 건."""

    external_id: str
    title: str
    status: SlotStatus
    raw_status: str | None
    place_name: str | None
    area: str | None
    detail_url: str
    # 시각까지 아는 경우에만 채운다. HTML 목록은 날짜만 주므로 None이다.
    reception_start_at: datetime | None = None
    reception_end_at: datetime | None = None
    reception_start_date: date | None = None
    reception_end_date: date | None = None
    use_start_date: date | None = None
    use_end_date: date | None = None
    daily_open_time: time | None = None
    daily_close_time: time | None = None
    selection_method: str | None = None
    fee_type: str | None = None
    target: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class NoticeDetail:
    """상세 페이지에서 얻는 공고 정보."""

    external_id: str
    title: str
    status: SlotStatus
    raw_status: str | None
    place_name: str | None
    reception_start_at: datetime | None
    reception_end_at: datetime | None
    use_start_date: date | None
    use_end_date: date | None
    selection_method: str | None
    fee_type: str | None
    # 이용일 기준 롤링 접수 규칙. 회차별 공고에서는 None이다.
    open_days_before: int | None
    open_hour: int | None
    close_days_before: int | None
    close_hour: int | None
    min_use_hours: int | None
    max_use_hours: int | None
    latitude: float | None
    longitude: float | None


class SiteAdapter(ABC):
    code: str

    @abstractmethod
    def fetch_notices(self, area: str | None = None) -> list[NoticeData]:
        """테니스장 예약 공고 목록. area를 주면 그 지역만 돌려준다."""

    @abstractmethod
    def fetch_notice_detail(self, external_id: str) -> NoticeDetail:
        """공고 한 건의 상세 정보."""

    @abstractmethod
    def notice_url(self, external_id: str) -> str:
        """사용자가 직접 예약하러 갈 상세 페이지 주소."""

    @abstractmethod
    def parse_title(self, title: str) -> TitleInfo:
        """공고명에서 코트·요일 구분·시간대 구분 후보를 추출한다."""
