"""서울시 공공서비스예약 어댑터.

수집 경로와 구조는 docs/SITE_RESEARCH.md에 근거한다.
- 목록: 서울 열린데이터광장 Open API(OA-2266). 인증키가 없으면 HTML 목록으로 대체.
- 상세: 예약 사이트 상세 페이지 HTML.
- 날짜·시간대별 잔여(달력)는 사이트가 자동화 접근을 차단하므로 수집하지 않는다.
"""

import json
import re
import time as time_module
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date, datetime, time
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import (
    AdapterError,
    AuthError,
    BlockedError,
    NoticeData,
    NoticeDetail,
    ParseError,
    SiteAdapter,
    TitleInfo,
)
from app.models.enums import DayType, SlotStatus, TimeBand
from app.timeutil import kst_to_utc

SITE_BASE = "https://yeyak.seoul.go.kr"
OPENAPI_BASE = "http://openapi.seoul.go.kr:8088"
OPENAPI_SERVICE = "ListPublicReservationSport"
OPENAPI_PAGE_SIZE = 1000  # 한 번에 요청할 수 있는 최대 건수
LIST_PATH = "/web/search/selectPageListDetailSearchImg.do"
DETAIL_PATH = "/web/reservation/selectReservView.do"
BLOCK_PATH = "/management/ipRedirect.do"
TENNIS_PARAMS = {"code": "T100", "dCode": "T108"}

# 목록 HTML의 자치구 필터 코드(sch_pl)
AREA_CODES = {
    "강남구": "SE01", "강동구": "SE02", "강북구": "SE03", "강서구": "SE04", "관악구": "SE05",
    "광진구": "SE06", "구로구": "SE07", "금천구": "SE08", "노원구": "SE09", "도봉구": "SE10",
    "동대문구": "SE11", "동작구": "SE12", "마포구": "SE13", "서대문구": "SE14", "서초구": "SE15",
    "성동구": "SE16", "성북구": "SE17", "송파구": "SE18", "양천구": "SE19", "영등포구": "SE20",
    "용산구": "SE21", "은평구": "SE22", "종로구": "SE23", "중구": "SE24", "중랑구": "SE25",
}  # fmt: skip

_STATUS_MAP = {
    "접수중": SlotStatus.AVAILABLE,
    "예약마감": SlotStatus.UNAVAILABLE,
    "접수종료": SlotStatus.UNAVAILABLE,
    "안내중": SlotStatus.NOT_OPEN,
    # Open API는 "예약일시중지", 사이트 화면은 "예약 일시정지"로 표기한다.
    "예약일시중지": SlotStatus.CLOSED,
    "예약일시정지": SlotStatus.CLOSED,
}


def map_status(raw: str | None) -> SlotStatus:
    if not raw:
        return SlotStatus.UNKNOWN
    return _STATUS_MAP.get(re.sub(r"\s+", "", raw), SlotStatus.UNKNOWN)


def notice_url(external_id: str) -> str:
    return f"{SITE_BASE}{DETAIL_PATH}?rsv_svc_id={external_id}"


# ---------------------------------------------------------------- 공고명 해석

_COURT_PATTERNS = [
    (re.compile(r"([A-Za-z])\s*코트"), lambda m: f"{m.group(1).upper()}코트"),
    (re.compile(r"(\d+)\s*번\s*코트"), lambda m: f"{m.group(1)}번코트"),
    (re.compile(r"(\d+)\s*면"), lambda m: f"{m.group(1)}면"),
    (re.compile(r"테니스장\s*(\d+)(?!\s*[월일년\d])"), lambda m: f"{m.group(1)}번코트"),
]


def parse_title(title: str) -> TitleInfo:
    court = None
    for pattern, label in _COURT_PATTERNS:
        if m := pattern.search(title):
            court = label(m)
            break

    weekday = "평일" in title
    weekend = bool(re.search(r"주말|공휴일|토\s*/\s*일|토요일|일요일", title))
    if weekday and not weekend:
        day_type = DayType.WEEKDAY
    elif weekend and not weekday:
        day_type = DayType.WEEKEND
    else:
        day_type = DayType.UNKNOWN

    day = "주간" in title
    night = bool(re.search(r"야간|저녁", title))
    if weekday and weekend:
        # "평일 야간 및 주말"처럼 섞인 공고는 시간대 구분이 어느 쪽에 걸리는지 알 수 없다.
        time_band = TimeBand.UNKNOWN
    elif day and not night:
        time_band = TimeBand.DAY
    elif night and not day:
        time_band = TimeBand.NIGHT
    else:
        time_band = TimeBand.UNKNOWN

    return TitleInfo(court, day_type, time_band, lighting="조명" in title)


# ---------------------------------------------------------------- 값 변환


def _clean(value) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if text and text.lower() != "null" else None


def _parse_api_datetime(value) -> datetime | None:
    """'2025-12-02 09:00:00.0' 형식의 한국시간 값을 UTC로 바꾼다."""
    text = _clean(value)
    if not text:
        return None
    try:
        return kst_to_utc(datetime.strptime(text.split(".")[0], "%Y-%m-%d %H:%M:%S"))
    except ValueError as exc:
        raise ParseError(f"일시 형식을 해석할 수 없습니다: {text!r}") from exc


def _parse_hhmm(value) -> time | None:
    text = _clean(value)
    if not text:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    # 24:00은 time으로 표현할 수 없어 23:59로 둔다.
    return time(23, 59) if hour >= 24 else time(hour, minute)


def _parse_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value) -> int | None:
    text = _clean(value)
    return int(text) if text and text.isdigit() else None


def _parse_dot_date(text: str) -> date:
    return datetime.strptime(text, "%Y.%m.%d").date()


# ---------------------------------------------------------------- Open API


def _raise_api_error(code: str | None, message: str | None):
    message = _clean(message) or ""
    if code == "INFO-100":
        raise AuthError(f"Open API 인증키가 유효하지 않습니다 ({code})")
    raise AdapterError(f"Open API 오류 {code}: {message}")


def parse_openapi_response(text: str) -> tuple[list[NoticeData], int]:
    """Open API 응답을 (공고 목록, 전체 건수)로 바꾼다.

    오류 응답은 json으로 요청해도 XML로 온다.
    """
    stripped = text.lstrip()
    if stripped.startswith("<"):
        try:
            root = ET.fromstring(stripped)
        except ET.ParseError as exc:
            raise ParseError("Open API 응답을 해석할 수 없습니다") from exc
        code = root.findtext("CODE") or root.findtext(".//CODE")
        if code == "INFO-200":  # 해당하는 데이터가 없음
            return [], 0
        _raise_api_error(code, root.findtext("MESSAGE") or root.findtext(".//MESSAGE"))

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ParseError("Open API 응답이 JSON이 아닙니다") from exc

    body = payload.get(OPENAPI_SERVICE)
    if body is None:
        result = payload.get("RESULT") or {}
        if result.get("CODE") == "INFO-200":
            return [], 0
        if result:
            _raise_api_error(result.get("CODE"), result.get("MESSAGE"))
        raise ParseError(f"Open API 응답에 {OPENAPI_SERVICE} 항목이 없습니다")

    result = body.get("RESULT") or {}
    if result.get("CODE") != "INFO-000":
        if result.get("CODE") == "INFO-200":
            return [], 0
        _raise_api_error(result.get("CODE"), result.get("MESSAGE"))

    notices = [_notice_from_api_row(row) for row in body.get("row", [])]
    return notices, int(body.get("list_total_count", len(notices)))


def _notice_from_api_row(row: dict) -> NoticeData:
    external_id = _clean(row.get("SVCID"))
    if not external_id:
        raise ParseError("Open API 행에 SVCID가 없습니다")
    raw_status = _clean(row.get("SVCSTATNM"))
    use_start = _parse_api_datetime(row.get("SVCOPNBGNDT"))
    use_end = _parse_api_datetime(row.get("SVCOPNENDDT"))
    reception_start = _parse_api_datetime(row.get("RCPTBGNDT"))
    reception_end = _parse_api_datetime(row.get("RCPTENDDT"))
    return NoticeData(
        external_id=external_id,
        title=_clean(row.get("SVCNM")) or "",
        status=map_status(raw_status),
        raw_status=raw_status,
        place_name=_clean(row.get("PLACENM")),
        area=_clean(row.get("AREANM")),
        detail_url=notice_url(external_id),
        reception_start_at=reception_start,
        reception_end_at=reception_end,
        # 이용 기간은 한국 기준 날짜다. 원문에서 날짜 부분만 쓴다.
        use_start_date=_api_date(row.get("SVCOPNBGNDT")),
        use_end_date=_api_date(row.get("SVCOPNENDDT")),
        reception_start_date=_api_date(row.get("RCPTBGNDT")),
        reception_end_date=_api_date(row.get("RCPTENDDT")),
        daily_open_time=_parse_hhmm(row.get("V_MIN")),
        daily_close_time=_parse_hhmm(row.get("V_MAX")),
        fee_type=_clean(row.get("PAYATNM")),
        target=_clean(row.get("USETGTINFO")),
        phone=_clean(row.get("TELNO")),
        # X가 경도, Y가 위도다.
        longitude=_parse_float(row.get("X")),
        latitude=_parse_float(row.get("Y")),
    )


def _api_date(value) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------- HTML 목록

_DETAIL_ID = re.compile(r"fnDetailPage\('([^']+)'")
_PLACE_AREA = re.compile(r"^(.*?)\s*\(([^()]+)\)$")
_DATE_RANGE = re.compile(r"(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})")
_DATETIME_RANGE = re.compile(
    r"(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2})"
)


def parse_list_html(html: str) -> tuple[list[NoticeData], int, int]:
    """목록 페이지를 (공고 목록, 전체 건수, 마지막 페이지 번호)로 바꾼다."""
    soup = BeautifulSoup(html, "html.parser")

    total_el = soup.select_one(".title_dep1 .text_red")
    if total_el is None or not total_el.get_text(strip=True).replace(",", "").isdigit():
        raise ParseError("목록 페이지에서 총 건수를 찾지 못했습니다")
    total = int(total_el.get_text(strip=True).replace(",", ""))

    notices = []
    for anchor in soup.select("ul.img_board a[onclick*=fnDetailPage]"):
        m = _DETAIL_ID.search(anchor.get("onclick", ""))
        title_el = anchor.select_one(".tit1")
        if not m or title_el is None:
            raise ParseError("목록 항목의 구조가 예상과 다릅니다")
        external_id = m.group(1)

        place = area = None
        if place_el := anchor.select_one(".ib_attr .sch-rslt"):
            place = _clean(place_el.get_text())
            if place and (pm := _PLACE_AREA.match(place)):
                place, area = pm.group(1), pm.group(2)

        def date_range(marker: str):
            label = anchor.select_one(f".ib_attr b.{marker}")
            rng = _DATE_RANGE.search(label.parent.get_text(" ")) if label else None
            return (_parse_dot_date(rng.group(1)), _parse_dot_date(rng.group(2))) if rng else (None, None)

        reception = date_range("date1")
        use = date_range("date2")
        status_el = anchor.select_one(".bd_label[class*=status]")
        fee_el = anchor.select_one(".bd_label[class*=type]")
        method_el = anchor.select_one(".ib_num")
        raw_status = _clean(status_el.get_text()) if status_el else None

        notices.append(
            NoticeData(
                external_id=external_id,
                title=_clean(title_el.get_text()) or "",
                status=map_status(raw_status),
                raw_status=raw_status,
                place_name=place,
                area=area,
                detail_url=notice_url(external_id),
                reception_start_date=reception[0],
                reception_end_date=reception[1],
                use_start_date=use[0],
                use_end_date=use[1],
                selection_method=_clean(method_el.get_text()) if method_el else None,
                fee_type=_clean(fee_el.get_text()) if fee_el else None,
            )
        )

    if total > 0 and not notices:
        raise ParseError("총 건수는 있는데 목록 항목을 찾지 못했습니다")

    pages = [int(n) for n in re.findall(r"fnGoPage\('(\d+)'\)", str(soup.select_one(".paging") or ""))]
    return notices, total, max(pages, default=1)


# ---------------------------------------------------------------- HTML 상세


def parse_detail_html(html: str, external_id: str) -> NoticeDetail:
    soup = BeautifulSoup(html, "html.parser")
    top = soup.select_one(".dt_top_box")
    title_el = top.select_one(".tit") if top else None
    if top is None or title_el is None:
        raise ParseError("상세 페이지 구조가 예상과 다릅니다")

    rows = {}
    for li in top.select(".dt_top_list li"):
        if (label := li.select_one("b.tit1")) is None:
            continue
        key = _clean(label.get_text())
        label.extract()
        rows[key] = _clean(li.get_text(" ")) or ""

    form = {
        el.get("name"): el.get("value")
        for el in soup.select("#aform input[name]")
    }
    page_id = _clean(form.get("rsv_svc_id"))
    if page_id and page_id != external_id:
        raise ParseError(f"요청한 공고({external_id})와 다른 공고({page_id})의 페이지입니다")

    reception = _DATETIME_RANGE.search(rows.get("접수기간", ""))
    use = _DATE_RANGE.search(rows.get("이용기간", ""))
    if reception is None or use is None:
        raise ParseError("상세 페이지에서 접수기간 또는 이용기간을 찾지 못했습니다")

    def kst(text: str) -> datetime:
        return kst_to_utc(datetime.strptime(text, "%Y.%m.%d %H:%M"))

    status_el = top.select_one(".bd_label[class*=status]")
    raw_status = _clean(status_el.get_text()) if status_el else None
    place = rows.get("장소")
    if place:
        place = _clean(re.sub(r"\(면적\s*:.*?\)|지도보기", "", place))

    return NoticeDetail(
        external_id=external_id,
        title=_clean(title_el.get_text()) or "",
        status=map_status(raw_status),
        raw_status=raw_status,
        place_name=place,
        reception_start_at=kst(reception.group(1)),
        reception_end_at=kst(reception.group(2)),
        use_start_date=_parse_dot_date(use.group(1)),
        use_end_date=_parse_dot_date(use.group(2)),
        selection_method=rows.get("선정방법") or None,
        fee_type=rows.get("이용요금") or None,
        open_days_before=_parse_int(form.get("use_stdr_rcept_daycnt")),
        open_hour=_parse_int(form.get("use_stdr_rcept_time")),
        close_days_before=_parse_int(form.get("rsvde_stdr_rcept_daycnt")),
        close_hour=_parse_int(form.get("rsvde_stdr_rcept_time")),
        min_use_hours=_parse_int(form.get("mumm_use_posbl_time")),
        max_use_hours=_parse_int(form.get("mxmm_use_posbl_time")),
        longitude=_parse_float(form.get("x")),
        latitude=_parse_float(form.get("y")),
    )


# ---------------------------------------------------------------- 어댑터


class SeoulAdapter(SiteAdapter):
    code = "seoul"

    def __init__(
        self,
        api_key: str = "",
        client: httpx.Client | None = None,
        *,
        timeout: float = 15.0,
        min_interval: float = 2.0,
        user_agent: str = "TennisWatch/0.1",
        max_list_pages: int = 10,
        sleep: Callable[[float], None] = time_module.sleep,
        clock: Callable[[], float] = time_module.monotonic,
    ):
        self.api_key = api_key
        self.client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": user_agent}, follow_redirects=False
        )
        self.min_interval = min_interval
        self.max_list_pages = max_list_pages
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    def notice_url(self, external_id: str) -> str:
        return notice_url(external_id)

    def parse_title(self, title: str) -> TitleInfo:
        return parse_title(title)

    def fetch_notices(self, area: str | None = None) -> list[NoticeData]:
        if self.api_key:
            notices = self.fetch_notices_openapi()
            return [n for n in notices if area is None or n.area == area]
        return self.fetch_notices_html(area)

    def fetch_notices_openapi(self) -> list[NoticeData]:
        if not self.api_key:
            raise AuthError("SEOUL_OPENAPI_KEY가 설정되지 않았습니다")
        notices: list[NoticeData] = []
        start = 1
        while True:
            end = start + OPENAPI_PAGE_SIZE - 1
            url = (
                f"{OPENAPI_BASE}/{self.api_key}/json/{OPENAPI_SERVICE}"
                f"/{start}/{end}/{quote('테니스장')}"
            )
            page, total = parse_openapi_response(self._get(url, safe_url=url.replace(self.api_key, "***")))
            notices.extend(page)
            # 요청한 것보다 적게 왔으면 마지막 페이지다. 전체 건수만 믿고 계속 요청하지 않는다.
            if len(page) < OPENAPI_PAGE_SIZE or len(notices) >= total:
                return notices
            start = end + 1

    def fetch_notices_html(self, area: str | None = None) -> list[NoticeData]:
        """목록 HTML 수집. 페이지당 6건이라 요청이 많으므로 지역을 좁혀 쓴다."""
        params = dict(TENNIS_PARAMS)
        if area is not None:
            if area not in AREA_CODES:
                raise AdapterError(f"알 수 없는 지역입니다: {area}")
            params["sch_pl"] = AREA_CODES[area]

        notices: list[NoticeData] = []
        page = 1
        while True:
            html = self._get(f"{SITE_BASE}{LIST_PATH}", params={**params, "currentPage": page})
            items, _total, last_page = parse_list_html(html)
            notices.extend(items)
            if page >= last_page or not items:
                return notices
            if page >= self.max_list_pages:
                raise AdapterError(
                    f"목록이 {last_page}페이지로 한도({self.max_list_pages})를 넘습니다. 지역을 좁히세요."
                )
            page += 1

    def fetch_notice_detail(self, external_id: str) -> NoticeDetail:
        html = self._get(f"{SITE_BASE}{DETAIL_PATH}", params={"rsv_svc_id": external_id})
        return parse_detail_html(html, external_id)

    def _get(self, url: str, params: dict | None = None, safe_url: str | None = None) -> str:
        """요청 간격을 지키며 GET. 오류 메시지에는 인증키가 들어가지 않게 한다."""
        shown = safe_url or url
        if self._last_request_at is not None:
            wait = self.min_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        try:
            response = self.client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise AdapterError(f"요청 실패: {shown} ({type(exc).__name__})") from None
        finally:
            self._last_request_at = self._clock()

        location = response.headers.get("location", "")
        if BLOCK_PATH in location or BLOCK_PATH in str(response.url):
            raise BlockedError("사이트가 비정상 접근으로 판단해 차단했습니다")
        if response.status_code != 200:
            raise AdapterError(f"HTTP {response.status_code}: {shown}")
        return response.text
