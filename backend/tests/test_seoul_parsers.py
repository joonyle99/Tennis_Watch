from datetime import UTC, date, datetime, time

import pytest

from app.adapters.base import AdapterError, AuthError, ParseError
from app.adapters.seoul import (
    map_status,
    parse_detail_html,
    parse_list_html,
    parse_openapi_response,
    parse_title,
)
from app.models.enums import DayType, SlotStatus, TimeBand

# ---------------------------------------------------------------- Open API


def test_openapi_rows_are_parsed(fixture_text):
    notices, total = parse_openapi_response(fixture_text("seoul_openapi_ok.json"))

    assert total == 313
    assert [n.external_id for n in notices] == [
        "S251121100349891778",
        "S251121102355938084",
        "S250114090501006336",
    ]
    first = notices[0]
    assert first.title == "테니스장1(평일)-2026년 응봉공원(대현산배수지)"
    assert first.place_name == "응봉공원"
    assert first.area == "성동구"
    assert (first.raw_status, first.status) == ("예약마감", SlotStatus.UNAVAILABLE)
    assert first.detail_url == (
        "https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=S251121100349891778"
    )
    assert first.target == "제한없음"  # 원문 앞 공백 제거
    assert (first.daily_open_time, first.daily_close_time) == (time(7, 0), time(19, 0))
    assert first.longitude == pytest.approx(127.0218, abs=1e-4)
    assert first.latitude == pytest.approx(37.5569, abs=1e-4)


def test_openapi_reception_time_is_converted_from_kst_to_utc(fixture_text):
    notices, _ = parse_openapi_response(fixture_text("seoul_openapi_ok.json"))
    first = notices[0]
    # 2025-12-02 09:00 KST
    assert first.reception_start_at == datetime(2025, 12, 2, 0, 0, tzinfo=UTC)
    # 2026-12-31 17:00 KST
    assert first.reception_end_at == datetime(2026, 12, 31, 8, 0, tzinfo=UTC)
    # 이용 기간은 한국 기준 날짜 그대로
    assert (first.use_start_date, first.use_end_date) == (date(2025, 12, 1), date(2026, 12, 31))


def test_openapi_invalid_key_error_arrives_as_xml(fixture_text):
    with pytest.raises(AuthError, match="INFO-100"):
        parse_openapi_response(fixture_text("seoul_openapi_invalid_key.xml"))


def test_openapi_no_data_is_an_empty_list():
    xml = "<RESULT><CODE>INFO-200</CODE><MESSAGE>해당하는 데이터가 없습니다.</MESSAGE></RESULT>"
    assert parse_openapi_response(xml) == ([], 0)


def test_openapi_other_errors_and_garbage_are_reported():
    with pytest.raises(AdapterError, match="ERROR-500"):
        parse_openapi_response("<RESULT><CODE>ERROR-500</CODE><MESSAGE>서버 오류</MESSAGE></RESULT>")
    with pytest.raises(ParseError):
        parse_openapi_response("not json")
    with pytest.raises(ParseError):
        parse_openapi_response('{"unexpected": {}}')


# ---------------------------------------------------------------- HTML 목록


def test_list_html_is_parsed(fixture_text):
    notices, total, last_page = parse_list_html(fixture_text("seoul_list_gangnam.html"))

    assert (total, last_page, len(notices)) == (16, 3, 6)
    maru = next(n for n in notices if n.external_id == "S210216131232290211")
    assert maru.title == "마루공원 테니스장 3면"
    assert (maru.place_name, maru.area) == ("마루공원", "강남구")
    assert (maru.raw_status, maru.status) == ("접수중", SlotStatus.AVAILABLE)
    assert (maru.selection_method, maru.fee_type) == ("선착순", "무료")
    assert (maru.reception_start_date, maru.reception_end_date) == (date(2026, 10, 8), date(2026, 12, 31))
    assert (maru.use_start_date, maru.use_end_date) == (date(2025, 6, 1), date(2026, 12, 31))
    # 목록에는 접수 시각이 없으므로 추측해서 채우지 않는다.
    assert maru.reception_start_at is None


def test_empty_list_html(fixture_text):
    assert parse_list_html(fixture_text("seoul_list_empty.html")) == ([], 0, 1)


def test_list_html_with_changed_structure_fails_loudly():
    with pytest.raises(ParseError):
        parse_list_html("<html><body><p>점검 중입니다</p></body></html>")
    with pytest.raises(ParseError, match="목록 항목"):
        parse_list_html('<div class="title_dep1">총 <span class="text_red">5</span> 건</div>')


# ---------------------------------------------------------------- HTML 상세


def test_detail_with_rolling_open_rule(fixture_text):
    detail = parse_detail_html(fixture_text("seoul_detail_rolling.html"), "S210216131232290211")

    assert detail.title == "마루공원 테니스장 3면"
    assert detail.place_name == "마루공원"
    assert detail.status == SlotStatus.AVAILABLE
    # 이용일 14일 전 14시부터, 이용 1일 전 23시까지
    assert (detail.open_days_before, detail.open_hour) == (14, 14)
    assert (detail.close_days_before, detail.close_hour) == (1, 23)
    assert (detail.min_use_hours, detail.max_use_hours) == (1, 2)
    # 2026.10.08 14:00 KST
    assert detail.reception_start_at == datetime(2026, 10, 8, 5, 0, tzinfo=UTC)
    assert (detail.use_start_date, detail.use_end_date) == (date(2025, 6, 1), date(2026, 12, 31))


def test_detail_of_per_period_notice_has_no_rolling_rule(fixture_text):
    detail = parse_detail_html(fixture_text("seoul_detail_notice.html"), "S261109114800279845")

    assert detail.title == "동부 도로사업소 테니스장 A코트 주말 및 공휴일 11월16일~30일"
    assert detail.place_name == "동부도로사업소 테니스장"
    assert detail.open_days_before is None and detail.open_hour is None
    # 2026.11.10 00:00 KST 접수 시작
    assert detail.reception_start_at == datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    assert (detail.use_start_date, detail.use_end_date) == (date(2026, 11, 16), date(2026, 11, 30))
    assert (detail.selection_method, detail.fee_type) == ("선착순", "유료")


def test_detail_for_a_different_notice_is_rejected(fixture_text):
    with pytest.raises(ParseError, match="다른 공고"):
        parse_detail_html(fixture_text("seoul_detail_notice.html"), "S000000000000000000")


def test_detail_with_changed_structure_fails_loudly():
    with pytest.raises(ParseError):
        parse_detail_html("<html><body>오류</body></html>", "S1")


# ---------------------------------------------------------------- 상태·공고명


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("접수중", SlotStatus.AVAILABLE),
        ("예약마감", SlotStatus.UNAVAILABLE),
        ("접수종료", SlotStatus.UNAVAILABLE),
        ("안내중", SlotStatus.NOT_OPEN),
        ("예약일시중지", SlotStatus.CLOSED),
        ("예약 일시정지", SlotStatus.CLOSED),
        ("처음 보는 상태", SlotStatus.UNKNOWN),
        (None, SlotStatus.UNKNOWN),
    ],
)
def test_status_mapping(raw, expected):
    assert map_status(raw) == expected


@pytest.mark.parametrize(
    ("title", "court", "day_type", "time_band"),
    [
        ("동부 도로사업소 테니스장 A코트 평일 야간 11월16일~30일", "A코트", DayType.WEEKDAY, TimeBand.NIGHT),
        ("동부 도로사업소 테니스장 A코트 주말 및 공휴일 11월16일~30일", "A코트", DayType.WEEKEND, TimeBand.UNKNOWN),
        ("동부 도로사업소 테니스장 A코트 평일주간 11월1일~15일", "A코트", DayType.WEEKDAY, TimeBand.DAY),
        ("마루공원 테니스장 3면", "3면", DayType.UNKNOWN, TimeBand.UNKNOWN),
        ("11/16~11/30 장충테니스장 4번코트(평일주간)", "4번코트", DayType.WEEKDAY, TimeBand.DAY),
        ("잠원 한강공원 테니스장 2번 코트 평일", "2번코트", DayType.WEEKDAY, TimeBand.UNKNOWN),
        ("테니스장1(토/일/공휴일)-2026년 응봉공원(대현산배수지)", "1번코트", DayType.WEEKEND, TimeBand.UNKNOWN),
        ("홍은테니스장 평일 주간 11월16일~30일", None, DayType.WEEKDAY, TimeBand.DAY),
        # 평일과 주말이 섞인 공고는 어느 쪽인지 단정하지 않는다.
        ("한남테니스장 6번코트 평일 야간 및 주말", "6번코트", DayType.UNKNOWN, TimeBand.UNKNOWN),
    ],
)
def test_title_parsing(title, court, day_type, time_band):
    info = parse_title(title)
    assert (info.court_label, info.day_type, info.time_band) == (court, day_type, time_band)


def test_title_lighting_flag():
    assert parse_title("마루공원 테니스장 1면 (조명)").lighting is True
    assert parse_title("마루공원 테니스장 1면").lighting is False
