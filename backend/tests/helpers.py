from datetime import UTC, date, datetime

from app.adapters.base import AdapterError, NoticeData, NoticeDetail, SiteAdapter
from app.adapters.seoul import map_status, notice_url, parse_title

T0 = datetime(2026, 11, 14, 3, 0, tzinfo=UTC)  # 2026-11-14 12:00 KST


def notice(
    external_id="S1",
    raw_status="접수중",
    title="동부 도로사업소 테니스장 A코트 주말 및 공휴일 11월16일~30일",
    place="동부도로사업소 테니스장",
    area="강남구",
    reception_start_at=datetime(2026, 11, 9, 15, 0, tzinfo=UTC),
    **extra,
) -> NoticeData:
    values = dict(
        external_id=external_id,
        title=title,
        status=map_status(raw_status),
        raw_status=raw_status,
        place_name=place,
        area=area,
        detail_url=notice_url(external_id),
        reception_start_at=reception_start_at,
        use_start_date=date(2026, 11, 16),
        use_end_date=date(2026, 11, 30),
    )
    values.update(extra)
    return NoticeData(**values)


def detail(external_id="S1", raw_status="접수중", title="마루공원 테니스장 3면", **extra) -> NoticeDetail:
    values = dict(
        external_id=external_id,
        title=title,
        status=map_status(raw_status),
        raw_status=raw_status,
        place_name="마루공원",
        reception_start_at=datetime(2026, 10, 8, 5, 0, tzinfo=UTC),
        reception_end_at=datetime(2026, 12, 31, 14, 59, tzinfo=UTC),
        use_start_date=date(2025, 6, 1),
        use_end_date=date(2026, 12, 31),
        selection_method="선착순",
        fee_type="무료",
        open_days_before=14,
        open_hour=14,
        close_days_before=1,
        close_hour=23,
        min_use_hours=1,
        max_use_hours=2,
        latitude=None,
        longitude=None,
    )
    values.update(extra)
    return NoticeDetail(**values)


class FakeAdapter(SiteAdapter):
    """정해 준 응답을 돌려주는 어댑터. 예외를 넣으면 그 호출에서 실패한다."""

    code = "seoul"

    def __init__(self, api_key="key"):
        self.api_key = api_key
        self.listing: list[NoticeData] | Exception = []
        self.html: dict[str, list[NoticeData]] | Exception = {}
        self.details: dict[str, NoticeDetail | Exception] = {}
        self.calls: list[tuple] = []

    def fetch_notices(self, area=None):
        self.calls.append(("openapi", area))
        if isinstance(self.listing, Exception):
            raise self.listing
        return list(self.listing)

    def fetch_notices_html(self, area=None):
        self.calls.append(("html", area))
        if isinstance(self.html, Exception):
            raise self.html
        return list(self.html.get(area, []))

    def fetch_notice_detail(self, external_id):
        self.calls.append(("detail", external_id))
        result = self.details.get(external_id, AdapterError("상세 없음"))
        if isinstance(result, Exception):
            raise result
        return result

    def notice_url(self, external_id):
        return notice_url(external_id)

    def parse_title(self, title):
        return parse_title(title)
