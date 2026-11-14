import threading
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.adapters.base import AdapterError, AuthError, BlockedError
from app.models import (
    ChangeKind,
    Court,
    CrawlLog,
    DataSource,
    Facility,
    NoticeStatusHistory,
    OpeningRule,
    ReservationNotice,
    RuleType,
    Site,
    SlotStatus,
    VerificationStatus,
    WatchRule,
)
from app.scheduler.jobs import Collector
from app.services import collector, opening_rules
from app.services.settings import get_setting, set_setting
from tests.helpers import T0, FakeAdapter, detail, notice

MIN = timedelta(minutes=1)


@pytest.fixture
def site(session):
    return session.query(Site).one()


@pytest.fixture
def adapter():
    return FakeAdapter()


def sync(session, adapter, site, now=T0):
    return collector.run_list_sync(session, adapter, site, now)


def the_notice(session, external_id="S1"):
    session.expire_all()
    return session.query(ReservationNotice).filter_by(external_id=external_id).one()


def history(session, external_id="S1"):
    return [(h.kind, h.notifiable) for h in the_notice(session, external_id).status_history]


# ---------------------------------------------------------------- 최초 수집


def test_first_sync_creates_facilities_courts_and_notices(session, adapter, site):
    adapter.listing = [
        notice("S1"),
        notice("S2", title="동부 도로사업소 테니스장 A코트 평일 야간 11월16일~30일"),
        notice("S3", title="마루공원 테니스장 3면", place="마루공원"),
        notice("S4", title="홍은테니스장 평일 주간 11월16일~30일", place="홍은테니스장", area="서대문구"),
    ]

    result = sync(session, adapter, site)

    assert (result.ok, result.source, result.seen, result.created, result.changed) == (True, "openapi", 4, 4, 0)
    facilities = {f.name: f for f in session.query(Facility).all()}
    assert set(facilities) == {"동부도로사업소 테니스장", "마루공원", "홍은테니스장"}
    # 기본 관심 시설만 관심으로 표시된다.
    assert {n for n, f in facilities.items() if f.is_watched} == {"동부도로사업소 테니스장", "마루공원"}
    assert facilities["마루공원"].area == "강남구" and facilities["마루공원"].source == DataSource.AUTO

    # 같은 코트의 공고 두 개는 코트 하나로 묶이고, 추출한 코트는 미확인 상태다.
    dongbu = facilities["동부도로사업소 테니스장"]
    assert [(c.name, c.verified, c.source) for c in dongbu.courts] == [("A코트", False, "AUTO")]
    assert the_notice(session, "S1").court_id == the_notice(session, "S2").court_id == dongbu.courts[0].id
    assert the_notice(session, "S2").time_band == "NIGHT"
    assert the_notice(session, "S4").court_id is None  # 공고명에 코트가 없으면 추측하지 않는다


def test_first_sync_never_notifies(session, adapter, site):
    adapter.listing = [notice("S1", "접수중"), notice("S2", "예약마감")]
    result = sync(session, adapter, site)

    assert result.notifiable == 0
    assert history(session, "S1") == [(ChangeKind.INITIAL, False)]
    assert the_notice(session, "S1").last_checked_at == T0


def test_notice_first_seen_later_as_available_is_not_a_reopening(session, adapter, site):
    adapter.listing = [notice("S1", "예약마감")]
    sync(session, adapter, site)
    adapter.listing = [notice("S1", "예약마감"), notice("S2", "접수중")]
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert (result.created, result.notifiable) == (1, 0)


# ---------------------------------------------------------------- 접수 재개 감지


def test_unavailable_to_available_is_a_notifiable_reopening(session, adapter, site):
    adapter.listing = [notice("S1", "예약마감")]
    sync(session, adapter, site)
    adapter.listing = [notice("S1", "접수중")]
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert (result.changed, result.notifiable) == (1, 1)
    change = session.get(NoticeStatusHistory, result.changes[0])
    assert (change.old_raw_status, change.new_raw_status) == ("예약마감", "접수중")
    assert (change.kind, change.notifiable, change.changed_at) == (ChangeKind.REOPENED, True, T0 + 5 * MIN)
    current = the_notice(session)
    assert (current.status, current.status_changed_at) == (SlotStatus.AVAILABLE, T0 + 5 * MIN)


def test_reopening_is_detected_again_after_closing_again(session, adapter, site):
    """불가 → 가능 → 불가 → 가능: 두 번 모두 알림 대상이다."""
    for i, raw in enumerate(["예약마감", "접수중", "예약마감", "접수중"]):
        adapter.listing = [notice("S1", raw)]
        sync(session, adapter, site, T0 + i * 5 * MIN)

    assert history(session) == [
        (ChangeKind.INITIAL, False),
        (ChangeKind.REOPENED, True),
        (ChangeKind.OTHER, False),
        (ChangeKind.REOPENED, True),
    ]


def test_unchanged_status_adds_no_history(session, adapter, site):
    adapter.listing = [notice("S1", "접수중")]
    sync(session, adapter, site)
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert result.changed == 0 and len(history(session)) == 1
    assert the_notice(session).last_checked_at == T0 + 5 * MIN  # 확인 시각은 갱신된다


def test_edited_notice_without_status_change_is_not_a_change(session, adapter, site):
    """공고명이나 기간만 고쳐진 것은 알림 대상이 아니다."""
    adapter.listing = [notice("S1", "접수중")]
    sync(session, adapter, site)
    adapter.listing = [
        notice("S1", "접수중", title="동부 도로사업소 테니스장 B코트 주말 11월16일~30일",
               reception_start_at=datetime(2026, 11, 10, 0, 0, tzinfo=UTC))
    ]  # fmt: skip
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert (result.changed, result.notifiable) == (0, 0)
    current = the_notice(session)
    assert current.title.startswith("동부 도로사업소 테니스장 B코트")
    assert current.court.name == "B코트"  # 공고명이 바뀌면 코트도 다시 추출한다
    assert current.reception_start_at == datetime(2026, 11, 10, 0, 0, tzinfo=UTC)


def test_actual_opening_is_notifiable(session, adapter, site):
    adapter.listing = [notice("S1", "안내중")]
    sync(session, adapter, site)
    adapter.listing = [notice("S1", "접수중")]
    sync(session, adapter, site, T0 + 5 * MIN)

    assert history(session)[-1] == (ChangeKind.OPENED, True)


def test_unknown_to_available_is_not_notifiable(session, adapter, site):
    adapter.listing = [notice("S1", "처음 보는 상태")]
    sync(session, adapter, site)
    assert the_notice(session).status == SlotStatus.UNKNOWN
    adapter.listing = [notice("S1", "접수중")]
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert (result.changed, result.notifiable) == (1, 0)
    assert history(session)[-1] == (ChangeKind.OTHER, False)


# ---------------------------------------------------------------- 관심 조건


def test_unwatched_facility_changes_are_recorded_but_not_notifiable(session, adapter, site):
    adapter.listing = [notice("S1", "예약마감", place="홍은테니스장", area="서대문구")]
    sync(session, adapter, site)
    adapter.listing = [notice("S1", "접수중", place="홍은테니스장", area="서대문구")]
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert (result.changed, result.notifiable) == (1, 0)
    assert history(session)[-1] == (ChangeKind.REOPENED, False)


def reopen(session, adapter, site, **notice_kwargs):
    adapter.listing = [notice("S1", "예약마감", **notice_kwargs)]
    sync(session, adapter, site)
    yield
    adapter.listing = [notice("S1", "접수중", **notice_kwargs)]
    yield sync(session, adapter, site, T0 + 5 * MIN)


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({}, True),
        ({"notify_vacancy": False}, False),
        ({"enabled": False}, True),  # 꺼진 조건만 있으면 조건이 없는 것과 같다
        ({"weekdays": [5, 6]}, True),  # 주말 공고
        ({"weekdays": [0, 1, 2]}, False),
        ({"date_from": date(2026, 11, 20), "date_to": date(2026, 11, 22)}, True),
        ({"date_from": date(2026, 12, 1)}, False),
        ({"date_to": date(2026, 11, 15)}, False),
        ({"time_from": time(18, 0), "time_to": time(22, 0)}, True),  # 운영 09~21시
        ({"time_from": time(21, 0)}, False),
        ({"time_to": time(9, 0)}, False),
    ],
)
def test_watch_rules_filter_notifications(session, adapter, site, rule, expected):
    steps = reopen(session, adapter, site, daily_open_time=time(9, 0), daily_close_time=time(21, 0))
    next(steps)
    facility = session.query(Facility).one()
    session.add(WatchRule(facility_id=facility.id, **rule))
    session.commit()

    assert bool(next(steps).notifiable) is expected


def test_watch_rule_for_another_court_does_not_match(session, adapter, site):
    steps = reopen(session, adapter, site)
    next(steps)
    facility = session.query(Facility).one()
    other = Court(facility_id=facility.id, name="B코트")
    session.add(other)
    session.flush()
    session.add(WatchRule(facility_id=facility.id, court_id=other.id))
    session.commit()

    assert next(steps).notifiable == 0


def test_any_matching_watch_rule_is_enough(session, adapter, site):
    steps = reopen(session, adapter, site)
    next(steps)
    facility = session.query(Facility).one()
    session.add_all(
        [WatchRule(facility_id=facility.id, weekdays=[0]), WatchRule(facility_id=facility.id, weekdays=[6])]
    )
    session.commit()

    assert next(steps).notifiable == 1


# ---------------------------------------------------------------- 수집 실패와 복구


def test_single_failure_keeps_stored_status_and_logs_the_error(session, adapter, site):
    adapter.listing = [notice("S1", "예약마감")]
    sync(session, adapter, site)
    adapter.listing = AdapterError("HTTP 500")
    adapter.html = AdapterError("HTTP 500")
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert (result.ok, result.error_type) == (False, "AdapterError")
    assert the_notice(session).status == SlotStatus.UNAVAILABLE  # 값을 추측해 바꾸지 않는다
    assert the_notice(session).last_checked_at == T0  # 마지막으로 실제 확인한 시각
    assert collector.consecutive_failures(session, site.id) == 1
    assert collector.last_success_at(session, site.id) == T0
    log = session.query(CrawlLog).order_by(CrawlLog.id.desc()).first()
    assert (log.success, log.error_type, log.error_message) == (False, "AdapterError", "HTTP 500")


def test_reopening_found_right_after_a_failure_is_not_notified(session, adapter, site):
    adapter.listing = [notice("S1", "예약마감")]
    sync(session, adapter, site)
    adapter.listing = adapter.html = AdapterError("timeout")
    sync(session, adapter, site, T0 + 5 * MIN)
    adapter.listing = [notice("S1", "접수중")]
    result = sync(session, adapter, site, T0 + 10 * MIN)

    assert (result.ok, result.changed, result.notifiable) == (True, 1, 0)
    assert history(session)[-1] == (ChangeKind.REOPENED, False)
    assert collector.consecutive_failures(session, site.id) == 0


def test_repeated_failures_turn_status_unknown_and_recovery_is_silent(session, adapter, site):
    adapter.listing = [notice("S1", "예약마감")]
    sync(session, adapter, site)

    adapter.listing = adapter.html = AdapterError("timeout")
    sync(session, adapter, site, T0 + 5 * MIN)
    sync(session, adapter, site, T0 + 10 * MIN)
    assert the_notice(session).status == SlotStatus.UNAVAILABLE  # 기준(3회) 전
    sync(session, adapter, site, T0 + 15 * MIN)
    assert the_notice(session).status == SlotStatus.UNKNOWN
    assert collector.consecutive_failures(session, site.id) == 3

    adapter.listing = [notice("S1", "접수중")]
    recovered = sync(session, adapter, site, T0 + 20 * MIN)
    assert (recovered.changed, recovered.notifiable) == (1, 0)
    assert the_notice(session).status == SlotStatus.AVAILABLE

    # 복구 뒤의 새 변화는 다시 정상적으로 알린다.
    adapter.listing = [notice("S1", "예약마감")]
    sync(session, adapter, site, T0 + 25 * MIN)
    adapter.listing = [notice("S1", "접수중")]
    assert sync(session, adapter, site, T0 + 30 * MIN).notifiable == 1


def test_opening_is_notified_even_after_a_failure(session, adapter, site):
    adapter.listing = [notice("S1", "안내중")]
    sync(session, adapter, site)
    adapter.listing = adapter.html = AdapterError("timeout")
    sync(session, adapter, site, T0 + 5 * MIN)
    adapter.listing = [notice("S1", "접수중")]

    assert sync(session, adapter, site, T0 + 10 * MIN).notifiable == 1


def test_backoff_doubles_with_each_failure_and_clears_on_success(session, adapter, site):
    assert collector.backoff_until(session, site.id, 5) is None
    adapter.listing = adapter.html = AdapterError("timeout")
    waits = []
    now = T0
    for _ in range(6):
        sync(session, adapter, site, now)
        waits.append((collector.backoff_until(session, site.id, 5) - now) // MIN)
        now += 5 * MIN
    assert waits == [5, 10, 20, 40, 60, 60]  # 최대 1시간

    adapter.listing = []
    sync(session, adapter, site, now)
    assert collector.backoff_until(session, site.id, 5) is None


def test_block_pauses_collection_until_resumed(session, engine, adapter, site):
    adapter.listing = BlockedError("차단")
    runner = Collector(sessionmaker(bind=engine, expire_on_commit=False), lambda code: adapter)

    first = runner.run(now=T0)
    assert first[0].error_type == "BlockedError"
    assert "차단" in get_setting(session, "collection_paused_reason")

    calls = len(adapter.calls)
    skipped = runner.run(force=True, now=T0 + 5 * MIN)  # 수동 실행으로도 요청하지 않는다
    assert "수집 중지됨" in skipped[0].skipped and len(adapter.calls) == calls

    set_setting(session, "collection_paused_reason", None)
    session.commit()
    adapter.listing = [notice("S1")]
    assert runner.run(force=True, now=T0 + 10 * MIN)[0].ok


def test_block_does_not_fall_back_to_html(session, adapter, site):
    adapter.listing = BlockedError("차단")
    sync(session, adapter, site)
    assert [c[0] for c in adapter.calls] == ["openapi"]


# ---------------------------------------------------------------- 수집 경로


def test_openapi_failure_falls_back_to_html_for_watched_areas(session, adapter, site):
    adapter.listing = [notice("S1"), notice("S9", place="홍은테니스장", area="서대문구")]
    sync(session, adapter, site)

    adapter.listing = AuthError("인증키가 유효하지 않습니다")
    html_item = replace(notice("S1", "예약마감"), reception_start_at=None)
    adapter.html = {"강남구": [html_item]}
    result = sync(session, adapter, site, T0 + 5 * MIN)

    assert (result.ok, result.source, result.changed) == (True, "html", 1)
    assert ("html", "강남구") in adapter.calls and ("html", "서대문구") not in adapter.calls
    # HTML 목록에 없는 접수 시각은 지우지 않는다.
    assert the_notice(session).reception_start_at == datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    # 수집하지 않은 지역의 공고는 그대로 둔다.
    assert the_notice(session, "S9").is_active is True


def test_without_a_key_html_starts_from_the_default_area(session, site):
    adapter = FakeAdapter(api_key="")
    adapter.html = {"강남구": [notice("S1")]}
    result = sync(session, adapter, site)

    assert (result.ok, result.source, result.created) == (True, "html", 1)
    assert adapter.calls == [("html", "강남구")]


def test_notice_missing_from_a_full_list_becomes_inactive(session, adapter, site):
    adapter.listing = [notice("S1"), notice("S2")]
    sync(session, adapter, site)
    adapter.listing = [notice("S2")]
    sync(session, adapter, site, T0 + 5 * MIN)

    assert the_notice(session, "S1").is_active is False
    assert the_notice(session, "S1").status == SlotStatus.AVAILABLE  # 상태 이력은 건드리지 않는다
    adapter.listing = [notice("S1"), notice("S2")]
    sync(session, adapter, site, T0 + 10 * MIN)
    assert the_notice(session, "S1").is_active is True


def test_new_notice_joins_the_existing_facility_by_place_name_or_alias(session, adapter, site):
    adapter.listing = [notice("S1")]
    sync(session, adapter, site)
    facility = session.query(Facility).one()
    facility.aliases = ["동부도로사업소"]
    session.commit()

    adapter.listing = [notice("S1"), notice("S2", place="동부도로사업소"), notice("S3")]
    sync(session, adapter, site, T0 + 5 * MIN)

    assert session.query(Facility).count() == 1
    assert {n.facility_id for n in session.query(ReservationNotice).all()} == {facility.id}


# ---------------------------------------------------------------- 수동 값 보호


def test_user_edited_facility_fields_are_not_overwritten(session, adapter, site):
    adapter.listing = [notice("S1", phone="02-111-1111")]
    sync(session, adapter, site)
    facility = session.query(Facility).one()
    facility.phone, facility.name, facility.is_watched = "02-999-9999", "동부", False
    facility.locked_fields = ["name", "phone"]
    session.commit()

    adapter.listing = [notice("S1", phone="02-222-2222")]
    sync(session, adapter, site, T0 + 5 * MIN)

    session.expire_all()
    facility = session.query(Facility).one()
    assert (facility.phone, facility.name, facility.is_watched) == ("02-999-9999", "동부", False)


def test_user_corrected_notice_fields_are_not_overwritten(session, adapter, site):
    adapter.listing = [notice("S1")]
    sync(session, adapter, site)
    current = the_notice(session)
    manual_court = Court(facility_id=current.facility_id, name="1번코트", source=DataSource.MANUAL, verified=True)
    session.add(manual_court)
    session.flush()
    current.court_id, current.day_type = manual_court.id, "WEEKDAY"
    current.locked_fields = ["court_id", "day_type"]
    session.commit()

    adapter.listing = [notice("S1", title="동부 도로사업소 테니스장 B코트 주말 11월16일~30일")]
    sync(session, adapter, site, T0 + 5 * MIN)

    current = the_notice(session)
    assert (current.court.name, current.day_type) == ("1번코트", "WEEKDAY")
    assert current.title.startswith("동부 도로사업소 테니스장 B코트")  # 잠그지 않은 값은 갱신된다


# ---------------------------------------------------------------- 오픈 규칙 자동 기록


def rules(session, **filters):
    session.expire_all()
    return session.query(OpeningRule).filter_by(**filters).order_by(OpeningRule.id).all()


def test_watched_notice_reception_start_becomes_an_opening_rule(session, adapter, site):
    adapter.listing = [notice("S1"), notice("S9", place="홍은테니스장", area="서대문구")]
    sync(session, adapter, site)
    sync(session, adapter, site, T0 + 5 * MIN)  # 다시 수집해도 중복으로 만들지 않는다

    [rule] = rules(session)
    assert (rule.rule_type, rule.source, rule.verification_status) == ("NOTICE", "AUTO", "VERIFIED")
    assert rule.opens_at == datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    assert (rule.target_use_start, rule.target_use_end) == (date(2026, 11, 16), date(2026, 11, 30))
    assert rule.notice_id == the_notice(session).id and rule.last_verified_at == T0 + 5 * MIN


def test_changed_reception_start_updates_the_notice_rule(session, adapter, site):
    adapter.listing = [notice("S1")]
    sync(session, adapter, site)
    moved = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    adapter.listing = [notice("S1", reception_start_at=moved)]
    sync(session, adapter, site, T0 + 5 * MIN)

    [rule] = rules(session)
    assert rule.opens_at == moved


def maru_synced(session, adapter, site):
    adapter.listing = [notice("S1", title="마루공원 테니스장 3면", place="마루공원")]
    sync(session, adapter, site)
    adapter.details["S1"] = detail("S1")


def test_detail_sync_records_the_rolling_rule(session, adapter, site):
    maru_synced(session, adapter, site)
    result = collector.run_detail_sync(session, adapter, site, T0)

    assert (result.ok, result.seen) == (True, 1)
    current = the_notice(session)
    assert (current.open_days_before, current.open_hour, current.max_use_hours) == (14, 14, 2)
    assert current.detail_checked_at == T0

    [rolling] = rules(session, is_active=True)
    assert (rolling.rule_type, rolling.days_before, rolling.open_time) == ("DAYS_BEFORE_USE", 14, time(14, 0))
    assert (rolling.source, rolling.verification_status) == ("AUTO", "VERIFIED")
    assert rolling.court.name == "3면" if hasattr(rolling, "court") else rolling.court_id == current.court_id
    # 롤링 오픈 공고의 접수 시작 일시는 오픈 시각이 아니므로 그 규칙은 닫힌다.
    assert [r.rule_type for r in rules(session, is_active=False)] == ["NOTICE"]

    # 다음 목록 수집에서 닫힌 규칙이 되살아나지 않는다.
    sync(session, adapter, site, T0 + 5 * MIN)
    assert [r.rule_type for r in rules(session, is_active=True)] == ["DAYS_BEFORE_USE"]


def test_changed_rolling_rule_keeps_the_old_one_as_history(session, adapter, site):
    maru_synced(session, adapter, site)
    collector.run_detail_sync(session, adapter, site, T0)
    adapter.details["S1"] = detail("S1", open_days_before=7, open_hour=9)
    later = T0 + timedelta(days=2)
    collector.run_detail_sync(session, adapter, site, later)

    old, new = rules(session, rule_type=RuleType.DAYS_BEFORE_USE)
    assert (old.days_before, old.is_active, old.valid_to) == (14, False, later)
    assert (new.days_before, new.open_time, new.is_active, new.replaces_id) == (7, time(9, 0), True, old.id)


def test_manual_rule_conflicting_with_collected_rule_is_flagged_and_both_kept(session, adapter, site):
    """수동 데이터와 자동 데이터가 충돌하면 양쪽을 보존하고 충돌로 표시한다."""
    maru_synced(session, adapter, site)
    facility = session.query(Facility).one()
    manual = opening_rules.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.DAYS_BEFORE_USE, days_before=7, open_time=time(9, 0)
    )
    session.commit()
    assert manual.verification_status == VerificationStatus.UNVERIFIED  # 아직 비교할 자동 규칙이 없다

    collector.run_detail_sync(session, adapter, site, T0)

    by_source = {r.source: r for r in rules(session, rule_type=RuleType.DAYS_BEFORE_USE, is_active=True)}
    assert (by_source["MANUAL"].days_before, by_source["MANUAL"].verification_status) == (7, "CONFLICT")
    assert (by_source["AUTO"].days_before, by_source["AUTO"].verification_status) == (14, "VERIFIED")


def test_new_notice_checks_inferred_monthly_rules(session, adapter, site):
    adapter.listing = [notice("S1")]
    sync(session, adapter, site)
    facility = session.query(Facility).one()
    rule = opening_rules.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=25,
        open_time=time(0, 0), verification_status=VerificationStatus.INFERRED,
    )  # fmt: skip
    session.commit()

    # 12월 1~15일분 공고가 11월 25일 00:00 KST 접수 시작으로 올라왔다.
    adapter.listing = [notice("S1"), notice("S2", "안내중", reception_start_at=datetime(2026, 11, 24, 15, 0, tzinfo=UTC))]
    sync(session, adapter, site, T0 + 5 * MIN)

    session.refresh(rule)
    assert rule.verification_status == VerificationStatus.VERIFIED


# ---------------------------------------------------------------- 상세 수집 대상


def test_detail_sync_only_covers_watched_active_notices_and_respects_refresh(session, adapter, site):
    adapter.listing = [
        notice("S1", title="마루공원 테니스장 3면", place="마루공원"),
        notice("S9", place="홍은테니스장", area="서대문구"),
    ]
    sync(session, adapter, site)
    adapter.details["S1"] = detail("S1")

    collector.run_detail_sync(session, adapter, site, T0)
    assert [c for c in adapter.calls if c[0] == "detail"] == [("detail", "S1")]

    # 24시간 안에는 다시 확인하지 않는다.
    again = collector.run_detail_sync(session, adapter, site, T0 + timedelta(hours=23))
    assert again.skipped and len([c for c in adapter.calls if c[0] == "detail"]) == 1
    collector.run_detail_sync(session, adapter, site, T0 + timedelta(hours=24))
    assert len([c for c in adapter.calls if c[0] == "detail"]) == 2


def test_detail_batch_size_limits_requests_per_run(session, adapter, site):
    adapter.listing = [notice(f"S{i}", title=f"마루공원 테니스장 {i}면", place="마루공원") for i in range(1, 6)]
    sync(session, adapter, site)
    for i in range(1, 6):
        adapter.details[f"S{i}"] = detail(f"S{i}")
    set_setting(session, "detail_batch_size", 2)
    session.commit()

    collector.run_detail_sync(session, adapter, site, T0)
    collector.run_detail_sync(session, adapter, site, T0 + MIN)

    checked = [c[1] for c in adapter.calls if c[0] == "detail"]
    assert checked == ["S1", "S2", "S3", "S4"]  # 아직 확인 안 한 공고부터


def test_hot_window_polls_only_notices_about_to_open(session, adapter, site):
    opens = T0 + 8 * MIN
    adapter.listing = [
        notice("S1", "안내중", reception_start_at=opens),
        notice("S2", "안내중", reception_start_at=T0 + timedelta(hours=3)),
    ]
    sync(session, adapter, site)
    for n in session.query(ReservationNotice).all():
        n.detail_checked_at = T0  # 일반 갱신 대상이 아니게 한다
    session.commit()

    def hot(now):
        return [n.external_id for n in collector.notices_needing_detail(session, now, hot_only=True)]

    assert hot(T0 - 3 * MIN) == []  # 오픈 11분 전
    assert hot(T0) == ["S1"]  # 오픈 8분 전
    assert hot(opens + 5 * MIN) == ["S1"]
    assert hot(opens + 6 * MIN) == []  # 오픈 5분이 지나면 일반 주기로 돌아간다

    # 실제 오픈이 확인되면 자주 확인하기를 멈추고, 오픈 알림 대상으로 기록된다.
    adapter.details["S1"] = detail(
        "S1", "접수중", title=notice().title, reception_start_at=opens,
        open_days_before=None, open_hour=None, close_days_before=None, close_hour=None,
    )  # fmt: skip
    result = collector.run_detail_sync(session, adapter, site, opens + MIN, hot_only=True)
    assert (result.changed, result.notifiable) == (1, 1)
    assert history(session)[-1] == (ChangeKind.OPENED, True)
    assert hot(opens + 2 * MIN) == []


def test_one_failed_detail_does_not_stop_the_others_or_change_values(session, adapter, site):
    adapter.listing = [
        notice("S1", "예약마감", title="마루공원 테니스장 1면", place="마루공원"),
        notice("S2", title="마루공원 테니스장 2면", place="마루공원"),
    ]
    sync(session, adapter, site)
    adapter.details = {"S1": AdapterError("HTTP 500"), "S2": detail("S2")}

    result = collector.run_detail_sync(session, adapter, site, T0)

    assert (result.ok, result.seen) == (False, 1) and "S1" in result.error
    assert the_notice(session, "S1").status == SlotStatus.UNAVAILABLE
    assert the_notice(session, "S1").detail_checked_at is None
    assert the_notice(session, "S2").open_days_before == 14


# ---------------------------------------------------------------- 실행기


def make_runner(engine, adapter):
    return Collector(sessionmaker(bind=engine, expire_on_commit=False), lambda code: adapter)


def test_runner_does_list_then_detail(engine, adapter, session, site):
    adapter.listing = [notice("S1", title="마루공원 테니스장 3면", place="마루공원")]
    adapter.details["S1"] = detail("S1")

    results = make_runner(engine, adapter).run(now=T0)

    assert [(r.job, r.ok) for r in results] == [("list", True), ("detail", True)]
    assert the_notice(session).open_days_before == 14


def test_runner_waits_out_backoff_unless_forced(engine, adapter, session, site):
    adapter.listing = adapter.html = AdapterError("timeout")
    runner = make_runner(engine, adapter)
    runner.run(now=T0)
    calls = len(adapter.calls)

    waiting = runner.run(now=T0 + 2 * MIN)
    assert "대기" in waiting[0].skipped and len(adapter.calls) == calls

    assert runner.run(now=T0 + 5 * MIN)[0].error_type == "AdapterError"  # 대기 시간이 지나면 다시 시도
    assert runner.run(force=True, now=T0 + 6 * MIN)[0].skipped is None  # 수동 실행은 기다리지 않는다


def test_runner_refuses_overlapping_runs(engine, session, site):
    started, release = threading.Event(), threading.Event()

    class SlowAdapter(FakeAdapter):
        def fetch_notices(self, area=None):
            started.set()
            release.wait(timeout=5)
            return []

    runner = make_runner(engine, SlowAdapter())
    first: list = []
    thread = threading.Thread(target=lambda: first.extend(runner.run(now=T0)))
    thread.start()
    assert started.wait(timeout=5)

    overlapping = runner.run(now=T0)
    release.set()
    thread.join(timeout=5)

    assert overlapping[0].skipped == "이미 수집 중입니다"
    assert first[0].ok
    assert session.query(CrawlLog).filter_by(job="list").count() == 1


def test_state_survives_restart_and_detection_continues(db_url, adapter):
    """재시작해도 직전 상태와 비교해 접수 재개를 감지한다."""
    from app.db import init_db, make_engine

    first = make_engine(db_url)
    init_db(first)
    adapter.listing = [notice("S1", "예약마감")]
    make_runner(first, adapter).run(now=T0)
    first.dispose()

    second = make_engine(db_url)
    init_db(second)
    adapter.listing = [notice("S1", "접수중")]
    results = make_runner(second, adapter).run(now=T0 + 5 * MIN)
    second.dispose()

    assert (results[0].created, results[0].changed, results[0].notifiable) == (0, 1, 1)


def test_crawl_log_records_how_long_the_run_took(session, site, monkeypatch):
    ticks = iter([100.0, 124.4])
    monkeypatch.setattr(collector.time_module, "monotonic", lambda: next(ticks))
    adapter = FakeAdapter()
    adapter.listing = [notice("S1")]

    collector.run_list_sync(session, adapter, site, T0)

    log = session.query(CrawlLog).one()
    assert (log.started_at, log.finished_at) == (T0, T0 + timedelta(seconds=24))
