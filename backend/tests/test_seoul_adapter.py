import httpx
import pytest

from app.adapters.base import AdapterError, AuthError, BlockedError
from app.adapters.registry import build_adapter
from app.adapters.seoul import SeoulAdapter
from app.config import Settings

API_KEY = "test-key-123"


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_adapter(handler, api_key="", **kwargs):
    fake = FakeClock()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SeoulAdapter(
        api_key=api_key, client=client, sleep=fake.sleep, clock=fake.clock, **kwargs
    )
    return adapter, fake


def test_openapi_is_used_when_a_key_is_set(fixture_text):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=fixture_text("seoul_openapi_ok.json"))

    adapter, _ = make_adapter(handler, api_key=API_KEY)
    # fixture는 3건만 담고 전체 313건이라고 답한다. 한 페이지에 1000건이므로 요청은 1회여야 한다.
    notices = adapter.fetch_notices_openapi()

    assert len(notices) == 3
    assert len(requests) == 1
    url = requests[0].url
    assert url.host == "openapi.seoul.go.kr" and url.port == 8088
    assert url.path == f"/{API_KEY}/json/ListPublicReservationSport/1/1000/테니스장"


def test_openapi_pages_until_total_is_reached():
    def row(i):
        return {"SVCID": f"S{i}", "SVCNM": f"공고 {i}", "SVCSTATNM": "접수중"}

    def handler(request):
        start, end = (int(x) for x in request.url.path.split("/")[4:6])
        rows = [row(i) for i in range(start, min(end, 1500) + 1)]
        body = {"list_total_count": 1500, "RESULT": {"CODE": "INFO-000"}, "row": rows}
        return httpx.Response(200, json={"ListPublicReservationSport": body})

    adapter, fake = make_adapter(handler, api_key=API_KEY)
    notices = adapter.fetch_notices_openapi()

    assert len(notices) == 1500
    assert notices[-1].external_id == "S1500"
    assert len(fake.sleeps) == 1  # 두 번째 요청 전에 간격을 둔다


def test_fetch_notices_filters_by_area(fixture_text):
    adapter, _ = make_adapter(
        lambda r: httpx.Response(200, text=fixture_text("seoul_openapi_ok.json")), api_key=API_KEY
    )
    assert {n.area for n in adapter.fetch_notices(area="성동구")} == {"성동구"}
    assert adapter.fetch_notices(area="강남구") == []


def test_invalid_key_raises_auth_error_without_leaking_the_key(fixture_text):
    adapter, _ = make_adapter(
        lambda r: httpx.Response(200, text=fixture_text("seoul_openapi_invalid_key.xml")),
        api_key=API_KEY,
    )
    with pytest.raises(AuthError) as exc:
        adapter.fetch_notices_openapi()
    assert API_KEY not in str(exc.value)


def test_http_and_network_errors_do_not_leak_the_key():
    adapter, _ = make_adapter(lambda r: httpx.Response(500), api_key=API_KEY)
    with pytest.raises(AdapterError) as exc:
        adapter.fetch_notices_openapi()
    assert "HTTP 500" in str(exc.value) and API_KEY not in str(exc.value)

    def boom(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    adapter, _ = make_adapter(boom, api_key=API_KEY)
    with pytest.raises(AdapterError) as exc:
        adapter.fetch_notices_openapi()
    assert "ConnectTimeout" in str(exc.value) and API_KEY not in str(exc.value)
    assert exc.value.__cause__ is None  # 원래 예외 메시지에 주소(키 포함)가 들어 있다


def test_html_list_is_used_without_a_key_and_walks_pages(fixture_text):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=fixture_text("seoul_list_gangnam.html"))

    adapter, fake = make_adapter(handler)
    notices = adapter.fetch_notices(area="강남구")

    # fixture는 마지막 페이지가 3이라고 답한다.
    assert [r.url.params["currentPage"] for r in requests] == ["1", "2", "3"]
    assert all(r.url.params["sch_pl"] == "SE01" for r in requests)
    assert all(r.url.params["dCode"] == "T108" for r in requests)
    assert len(notices) == 18
    assert fake.sleeps == [2.0, 2.0]


def test_html_list_refuses_to_crawl_too_many_pages(fixture_text):
    adapter, _ = make_adapter(
        lambda r: httpx.Response(200, text=fixture_text("seoul_list_gangnam.html")),
        max_list_pages=2,
    )
    with pytest.raises(AdapterError, match="한도"):
        adapter.fetch_notices_html()


def test_unknown_area_is_rejected():
    adapter, _ = make_adapter(lambda r: httpx.Response(200, text=""))
    with pytest.raises(AdapterError, match="알 수 없는 지역"):
        adapter.fetch_notices_html("없는구")


def test_detail_page_is_fetched_by_notice_id(fixture_text):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=fixture_text("seoul_detail_rolling.html"))

    adapter, _ = make_adapter(handler)
    detail = adapter.fetch_notice_detail("S210216131232290211")

    assert detail.open_days_before == 14
    assert requests[0].url.path == "/web/reservation/selectReservView.do"
    assert requests[0].url.params["rsv_svc_id"] == "S210216131232290211"


def test_block_redirect_raises_blocked_error():
    """사이트가 차단 페이지로 돌려보내면 재시도 대상이 아닌 별도 오류로 알린다."""
    location = "https://yeyak.seoul.go.kr/management/ipRedirect.do?threatGb=DNP"
    adapter, _ = make_adapter(lambda r: httpx.Response(302, headers={"location": location}))
    with pytest.raises(BlockedError):
        adapter.fetch_notice_detail("S1")


def test_requests_are_spaced_by_min_interval(fixture_text):
    adapter, fake = make_adapter(
        lambda r: httpx.Response(200, text=fixture_text("seoul_detail_rolling.html")),
        min_interval=2.0,
    )
    adapter.fetch_notice_detail("S210216131232290211")
    assert fake.sleeps == []  # 첫 요청은 기다리지 않는다

    fake.now += 0.5
    adapter.fetch_notice_detail("S210216131232290211")
    assert fake.sleeps == [pytest.approx(1.5)]

    fake.now += 10
    adapter.fetch_notice_detail("S210216131232290211")
    assert len(fake.sleeps) == 1  # 이미 충분히 지났으면 기다리지 않는다


def test_registry_builds_seoul_adapter_from_settings():
    adapter = build_adapter("seoul", Settings(seoul_openapi_key="k", _env_file=None))
    assert isinstance(adapter, SeoulAdapter) and adapter.api_key == "k"
    with pytest.raises(ValueError):
        build_adapter("songpa", Settings(_env_file=None))
