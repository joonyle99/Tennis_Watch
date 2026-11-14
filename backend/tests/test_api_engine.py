from datetime import time

import pytest
from sqlalchemy.orm import sessionmaker

from app.adapters.base import BlockedError
from app.api.routes import get_collector
from app.main import app
from app.models import DataSource, Facility, OpeningRule, RuleType, Site
from app.scheduler.jobs import Collector
from tests.helpers import FakeAdapter, detail, notice


@pytest.fixture
def adapter():
    return FakeAdapter()


@pytest.fixture
def api(client, engine, adapter):
    runner = Collector(sessionmaker(bind=engine, expire_on_commit=False), lambda code: adapter)
    app.dependency_overrides[get_collector] = lambda: runner
    return client


@pytest.fixture
def facility_id(session):
    site = session.query(Site).one()
    facility = Facility(site_id=site.id, name="마루공원", external_name="마루공원", is_watched=True)
    session.add(facility)
    session.commit()
    return facility.id


def test_manual_sync_collects_and_reports(api, adapter):
    adapter.listing = [notice("S1", title="마루공원 테니스장 3면", place="마루공원")]
    adapter.details["S1"] = detail("S1")

    results = api.post("/api/sync").json()

    assert [(r["job"], r["ok"], r["created"]) for r in results] == [("list", True, 1), ("detail", True, 0)]
    notices = api.get("/api/notices", params={"watched": True}).json()
    assert [(n["external_id"], n["open_days_before"], n["open_hour"]) for n in notices] == [("S1", 14, 14)]

    status = api.get("/api/status").json()
    assert status["paused_reason"] is None
    assert status["sites"][0]["consecutive_failures"] == 0
    assert status["sites"][0]["last_success_at"] is not None
    assert {log["job"] for log in status["recent_logs"]} == {"list", "detail"}


def test_block_is_visible_in_status_and_can_be_resumed(api, adapter):
    adapter.listing = BlockedError("사이트가 비정상 접근으로 판단해 차단했습니다")
    assert api.post("/api/sync").json()[0]["error_type"] == "BlockedError"

    status = api.get("/api/status").json()
    assert "차단" in status["paused_reason"]
    assert status["sites"][0]["consecutive_failures"] == 1
    assert "수집 중지됨" in api.post("/api/sync").json()[0]["skipped"]

    assert api.post("/api/sync/resume").status_code == 204
    adapter.listing = []
    assert api.post("/api/sync").json()[0]["ok"] is True


def test_changes_endpoint_lists_reopenings(api, adapter):
    adapter.listing = [notice("S1", "예약마감")]
    api.post("/api/sync")
    adapter.listing = [notice("S1", "접수중")]
    api.post("/api/sync")

    changes = api.get("/api/changes").json()
    assert [(c["kind"], c["notifiable"], c["old_raw_status"], c["new_raw_status"]) for c in changes] == [
        ("REOPENED", True, "예약마감", "접수중")
    ]
    notice_id = changes[0]["notice_id"]
    history = api.get(f"/api/notices/{notice_id}/history").json()
    assert [h["kind"] for h in history] == ["INITIAL", "REOPENED"]
    assert api.get("/api/changes", params={"notifiable": False}).json() == []


def test_notice_correction_is_locked_against_later_syncs(api, adapter):
    adapter.listing = [notice("S1")]
    api.post("/api/sync")
    current = api.get("/api/notices").json()[0]
    court = api.post(f"/api/facilities/{current['facility_id']}/courts", json={"name": "1번코트"}).json()

    patched = api.patch(f"/api/notices/{current['id']}", json={"court_id": court["id"], "time_band": "NIGHT"})
    assert patched.status_code == 200

    adapter.listing = [notice("S1", title="동부 도로사업소 테니스장 B코트 평일주간 11월16일~30일")]
    api.post("/api/sync")
    after = api.get("/api/notices").json()[0]
    assert (after["court_id"], after["time_band"], after["day_type"]) == (court["id"], "NIGHT", "WEEKDAY")


def test_notice_correction_rejects_a_court_of_another_facility(api, adapter, facility_id):
    adapter.listing = [notice("S1")]
    api.post("/api/sync")
    current = api.get("/api/notices").json()[0]
    other_court = api.post(f"/api/facilities/{facility_id}/courts", json={"name": "3면"}).json()

    response = api.patch(f"/api/notices/{current['id']}", json={"court_id": other_court["id"]})
    assert response.status_code == 400


def test_settings_defaults_update_and_validation(api):
    settings = api.get("/api/settings").json()
    assert settings["sync_interval_minutes"] == 5
    assert settings["opening_alert_offsets_minutes"] == [1440, 60, 10]

    updated = api.put(
        "/api/settings", json={"values": {"sync_interval_minutes": 10, "opening_alert_offsets_minutes": [60]}}
    )
    assert updated.status_code == 200 and updated.json()["sync_interval_minutes"] == 10
    assert api.get("/api/settings").json()["opening_alert_offsets_minutes"] == [60]

    assert api.put("/api/settings", json={"values": {"sync_interval_minutes": 0}}).status_code == 422
    assert api.put("/api/settings", json={"values": {"sync_interval_minutes": True}}).status_code == 422
    assert api.put("/api/settings", json={"values": {"nope": 1}}).status_code == 400
    assert api.get("/api/settings").json()["sync_interval_minutes"] == 10  # 실패한 요청은 반영되지 않는다


def test_opening_rule_lifecycle(api, facility_id):
    created = api.post(
        "/api/opening-rules",
        json={
            "facility_id": facility_id, "rule_type": "MONTHLY", "day_of_month": 10, "open_time": "00:00:00",
            "target_description": "16일~말일", "verification_status": "INFERRED",
        },
    )  # fmt: skip
    assert created.status_code == 201
    rule = created.json()
    assert (rule["source"], rule["verification_status"], rule["is_active"]) == ("MANUAL", "INFERRED", True)

    edited = api.patch(f"/api/opening-rules/{rule['id']}", json={"day_of_month": 11}).json()
    assert (edited["day_of_month"], edited["replaces_id"], edited["target_description"]) == (11, rule["id"], "16일~말일")

    active = api.get("/api/opening-rules", params={"facility_id": facility_id}).json()
    assert [r["id"] for r in active] == [edited["id"]]
    everything = api.get("/api/opening-rules", params={"facility_id": facility_id, "include_inactive": True}).json()
    assert len(everything) == 2  # 고치기 전 규칙이 이력으로 남는다

    assert api.delete(f"/api/opening-rules/{edited['id']}").status_code == 204
    assert api.get("/api/opening-rules").json() == []


def test_opening_rule_validation(api, facility_id, session):
    base = {"facility_id": facility_id, "rule_type": "MONTHLY"}
    assert api.post("/api/opening-rules", json={**base, "day_of_month": 10}).status_code == 422  # 시각 없음
    assert api.post("/api/opening-rules", json={**base, "day_of_month": 32, "open_time": "00:00"}).status_code == 422
    naive = {"facility_id": facility_id, "rule_type": "ONE_TIME", "opens_at": "2026-11-25T00:00:00"}
    assert api.post("/api/opening-rules", json=naive).status_code == 422  # 시간대 없는 일시
    assert api.post("/api/opening-rules", json={**base, "facility_id": 999}).status_code == 404

    auto = OpeningRule(
        facility_id=facility_id, rule_type=RuleType.DAYS_BEFORE_USE, source=DataSource.AUTO,
        days_before=14, open_time=time(14, 0),
    )  # fmt: skip
    session.add(auto)
    session.commit()
    assert api.patch(f"/api/opening-rules/{auto.id}", json={"days_before": 7}).status_code == 409
    assert api.delete(f"/api/opening-rules/{auto.id}").status_code == 409


def test_one_time_rule_is_stored_in_utc_and_listed_as_upcoming(api, facility_id):
    response = api.post(
        "/api/opening-rules",
        json={"facility_id": facility_id, "rule_type": "ONE_TIME", "opens_at": "2099-01-01T09:00:00+09:00"},
    )
    assert response.json()["opens_at"] == "2099-01-01T00:00:00Z"
    listed = api.get("/api/opening-rules").json()[0]
    assert listed["opens_at"] == "2099-01-01T00:00:00Z"
    assert api.get("/api/openings", params={"days": 500}).status_code == 422


def test_upcoming_openings_from_a_rolling_rule(api, facility_id):
    api.post(
        "/api/opening-rules",
        json={"facility_id": facility_id, "rule_type": "DAYS_BEFORE_USE", "days_before": 14, "open_time": "14:00"},
    )
    openings = api.get("/api/openings", params={"days": 7}).json()

    assert 7 <= len(openings) <= 8
    assert all(o["rule_type"] == "DAYS_BEFORE_USE" and o["use_start"] == o["use_end"] for o in openings)
    assert all(o["opens_at"].endswith("T05:00:00Z") for o in openings)  # 14:00 KST


def test_watch_rule_crud_and_validation(api, facility_id):
    created = api.post(
        "/api/watch-rules",
        json={"facility_id": facility_id, "name": "토요일 저녁", "weekdays": [5], "time_from": "18:00", "time_to": "22:00"},
    )
    assert created.status_code == 201
    rule = created.json()
    assert (rule["notify_opening"], rule["notify_vacancy"], rule["enabled"]) == (True, True, True)

    replaced = api.put(f"/api/watch-rules/{rule['id']}", json={"weekdays": [5, 6], "notify_vacancy": False}).json()
    assert (replaced["weekdays"], replaced["notify_vacancy"], replaced["time_from"]) == ([5, 6], False, None)
    assert len(api.get("/api/watch-rules", params={"facility_id": facility_id}).json()) == 1

    bad = {"facility_id": facility_id}
    assert api.post("/api/watch-rules", json={**bad, "weekdays": [7]}).status_code == 422
    assert api.post("/api/watch-rules", json={**bad, "time_from": "20:00", "time_to": "18:00"}).status_code == 422
    assert api.post("/api/watch-rules", json={**bad, "date_from": "2026-12-02", "date_to": "2026-12-01"}).status_code == 422

    assert api.delete(f"/api/watch-rules/{rule['id']}").status_code == 204
    assert api.get("/api/watch-rules").json() == []


def test_manual_slot_status_is_upserted_and_can_be_cleared(api, facility_id):
    body = {
        "facility_id": facility_id, "use_date": "2026-11-28", "start_time": "18:00", "end_time": "20:00",
        "status": "AVAILABLE", "note": "사이트에서 직접 확인",
    }  # fmt: skip
    first = api.put("/api/slots/manual", json=body).json()
    assert (first["manual_status"], first["auto_status"], first["has_conflict"]) == ("AVAILABLE", "UNKNOWN", False)
    assert first["manual_updated_at"] is not None

    second = api.put("/api/slots/manual", json={**body, "status": "UNAVAILABLE"}).json()
    assert second["id"] == first["id"] and second["manual_status"] == "UNAVAILABLE"

    listed = api.get("/api/slots", params={"facility_id": facility_id, "date_from": "2026-11-28"}).json()
    assert len(listed) == 1
    assert api.get("/api/slots", params={"date_to": "2026-11-27"}).json() == []

    cleared = api.put("/api/slots/manual", json={**body, "status": None, "note": None}).json()
    assert cleared["manual_status"] is None

    assert api.put("/api/slots/manual", json={**body, "start_time": "20:00"}).status_code == 422


def test_sync_endpoint_needs_a_collector(client):
    app.dependency_overrides.pop(get_collector, None)
    if hasattr(app.state, "collector"):
        del app.state.collector
    assert client.post("/api/sync").status_code == 503
