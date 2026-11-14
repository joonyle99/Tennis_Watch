from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy.orm import Session

from app.adapters.base import AdapterError, BlockedError
from app.models import (
    DataSource,
    Facility,
    NotificationEvent,
    NotificationStatus,
    OpeningRule,
    ReservationNotice,
    RuleType,
    Site,
    VerificationStatus,
    WatchRule,
)
from app.services import collector, notifier, opening_rules
from app.services.settings import set_setting
from app.services.telegram import TelegramError
from tests.helpers import T0, FakeAdapter, detail, notice

MIN = timedelta(minutes=1)
SEC = timedelta(seconds=1)


class FakeTelegram:
    """보낸 메시지를 기록한다. outcomes에 예외를 넣으면 그 순서의 전송이 실패한다."""

    def __init__(self, configured=True):
        self.configured = configured
        self.sent: list[str] = []
        self.outcomes: list[Exception | None] = []
        self.calls = 0

    def send_message(self, text):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome
        self.sent.append(text)


@pytest.fixture
def site(session):
    return session.query(Site).one()


@pytest.fixture
def adapter():
    return FakeAdapter()


@pytest.fixture
def telegram():
    return FakeTelegram()


def events(session, **filters):
    session.expire_all()
    return session.query(NotificationEvent).filter_by(**filters).order_by(NotificationEvent.id).all()


def run(session, telegram, now):
    return notifier.run_notifications(session, telegram, now)


def reopened(session, adapter, site, at=T0 + 5 * MIN):
    adapter.listing = [notice("S1", "예약마감")]
    collector.run_list_sync(session, adapter, site, T0)
    adapter.listing = [notice("S1", "접수중")]
    collector.run_list_sync(session, adapter, site, at)


# ---------------------------------------------------------------- 접수 재개·오픈 확인


def test_reopening_sends_one_message_with_the_booking_link(session, adapter, site, telegram):
    reopened(session, adapter, site)
    counts = run(session, telegram, T0 + 5 * MIN)

    assert counts == {"changes": 1, "openings": 0, "system": 0, "sent": 1}
    message = telegram.sent[0]
    assert message.startswith("[Tennis Watch] 접수 재개 (빈 코트 가능)")
    assert "시설: 동부도로사업소 테니스장" in message
    assert "공고: 동부 도로사업소 테니스장 A코트 주말 및 공휴일 11월16일~30일" in message
    assert "코트: A코트 (공고명에서 추출)" in message
    assert "이용기간: 2026-11-16 ~ 2026-11-30" in message
    assert "상태: 예약마감 → 접수중" in message
    assert "확인시각: 2026-11-14 12:05" in message  # 한국시간
    assert "예약 바로가기: https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=S1" in message

    [event] = events(session)
    assert (event.type, event.status, event.attempts, event.sent_at) == ("REOPENED", "SENT", 1, T0 + 5 * MIN)


def test_the_same_change_is_never_sent_twice(session, adapter, site, telegram):
    reopened(session, adapter, site)
    for i in range(5):
        run(session, telegram, T0 + 5 * MIN + i * 30 * SEC)
    collector.run_list_sync(session, adapter, site, T0 + 10 * MIN)  # 상태 그대로인 수집
    run(session, telegram, T0 + 10 * MIN)

    assert len(telegram.sent) == 1 and len(events(session)) == 1


def test_each_new_reopening_gets_its_own_message(session, adapter, site, telegram):
    for i, raw in enumerate(["예약마감", "접수중", "예약마감", "접수중"]):
        adapter.listing = [notice("S1", raw)]
        collector.run_list_sync(session, adapter, site, T0 + i * 5 * MIN)
        run(session, telegram, T0 + i * 5 * MIN)

    assert len(telegram.sent) == 2


def test_actual_opening_message(session, adapter, site, telegram):
    adapter.listing = [notice("S1", "안내중", reception_start_at=T0 + 5 * MIN)]
    collector.run_list_sync(session, adapter, site, T0 - timedelta(days=3))
    adapter.listing = [notice("S1", "접수중", reception_start_at=T0 + 5 * MIN)]
    collector.run_list_sync(session, adapter, site, T0 + 5 * MIN)
    run(session, telegram, T0 + 5 * MIN)

    [message] = telegram.sent
    assert message.startswith("[Tennis Watch] 예약 오픈 확인")
    assert "상태: 안내중 → 접수중" in message and "어느 날짜" not in message


def test_non_notifiable_changes_create_no_event(session, adapter, site, telegram):
    adapter.listing = [notice("S1", "접수중"), notice("S9", "예약마감", place="홍은테니스장", area="서대문구")]
    collector.run_list_sync(session, adapter, site, T0)  # 최초 수집
    adapter.listing = [notice("S1", "예약마감"), notice("S9", "접수중", place="홍은테니스장", area="서대문구")]
    collector.run_list_sync(session, adapter, site, T0 + 5 * MIN)  # 마감 + 비관심 시설의 재개
    run(session, telegram, T0 + 5 * MIN)

    assert telegram.sent == [] and events(session) == []


def test_stale_change_is_not_sent_late(session, adapter, site, telegram):
    """서버가 한동안 알림을 못 보냈다면, 뒤늦은 접수 재개 알림은 보내지 않는다."""
    reopened(session, adapter, site)
    run(session, telegram, T0 + 5 * MIN + timedelta(minutes=31))

    assert telegram.sent == []
    [event] = events(session)
    assert event.status == "SKIPPED" and "지남" in event.last_error


# ---------------------------------------------------------------- 재시도


def test_failed_send_is_retried_with_growing_delay_until_it_succeeds(session, adapter, site, telegram):
    reopened(session, adapter, site)
    start = T0 + 5 * MIN
    telegram.outcomes = [TelegramError("Telegram 오류 502"), TelegramError("Telegram 요청 실패 (ConnectTimeout)"), None]

    run(session, telegram, start)
    [event] = events(session)
    assert (event.status, event.attempts, event.next_attempt_at) == ("PENDING", 1, start + 30 * SEC)
    assert event.last_error == "Telegram 오류 502"

    run(session, telegram, start + 20 * SEC)  # 아직 기다리는 중
    assert telegram.calls == 1

    run(session, telegram, start + 30 * SEC)
    [event] = events(session)
    assert (event.attempts, event.next_attempt_at) == (2, start + 30 * SEC + 60 * SEC)

    run(session, telegram, start + 90 * SEC)
    [event] = events(session)
    assert (event.status, event.attempts, event.last_error) == ("SENT", 3, None)
    assert len(telegram.sent) == 1


def test_send_gives_up_after_max_attempts(session, adapter, site, telegram):
    reopened(session, adapter, site)
    telegram.outcomes = [TelegramError("오류")] * 10
    now = T0 + 5 * MIN
    for _ in range(8):
        run(session, telegram, now)
        now += 3 * MIN  # 대기 시간보다 길게, 만료(30분)보다는 짧게

    [event] = events(session)
    assert (event.status, event.attempts) == ("FAILED", notifier.MAX_ATTEMPTS)
    assert telegram.calls == notifier.MAX_ATTEMPTS


def test_permanent_error_fails_immediately(session, adapter, site, telegram):
    reopened(session, adapter, site)
    telegram.outcomes = [TelegramError("Telegram 오류 400: chat not found", permanent=True)]
    run(session, telegram, T0 + 5 * MIN)
    run(session, telegram, T0 + 6 * MIN)

    [event] = events(session)
    assert (event.status, event.attempts, telegram.calls) == ("FAILED", 1, 1)
    assert "chat not found" in event.last_error


def test_rate_limit_waits_as_told_and_pauses_the_rest_of_the_batch(session, adapter, site, telegram):
    adapter.listing = [notice("S1", "예약마감"), notice("S2", "예약마감")]
    collector.run_list_sync(session, adapter, site, T0)
    adapter.listing = [notice("S1", "접수중"), notice("S2", "접수중")]
    collector.run_list_sync(session, adapter, site, T0 + 5 * MIN)
    start = T0 + 5 * MIN
    telegram.outcomes = [TelegramError("전송 제한", retry_after=17)]

    run(session, telegram, start)
    first, second = events(session)
    assert (first.status, first.attempts, first.next_attempt_at) == ("PENDING", 0, start + 17 * SEC)
    assert telegram.calls == 1 and second.attempts == 0  # 두 번째는 시도하지 않았다

    run(session, telegram, start + 10 * SEC)
    assert len(telegram.sent) == 1  # 제한에 걸리지 않은 알림은 다음 차례에 나간다
    run(session, telegram, start + 17 * SEC)
    assert [e.status for e in events(session)] == ["SENT", "SENT"]


def test_pending_notifications_survive_restart(db_url, adapter):
    from app.db import init_db, make_engine

    first = make_engine(db_url)
    init_db(first)
    down = FakeTelegram()
    down.outcomes = [TelegramError("오류")]
    with Session(first, expire_on_commit=False) as session:
        reopened(session, adapter, session.query(Site).one())
        run(session, down, T0 + 5 * MIN)
    first.dispose()

    second = make_engine(db_url)
    init_db(second)
    up = FakeTelegram()
    with Session(second, expire_on_commit=False) as session:
        run(session, up, T0 + 6 * MIN)
        assert [e.status for e in events(session)] == ["SENT"]
    second.dispose()
    assert len(up.sent) == 1


# ---------------------------------------------------------------- 켜기/끄기, 미설정


def test_disabled_notifications_are_recorded_but_never_sent(session, adapter, site, telegram):
    set_setting(session, "notifications_enabled", False)
    session.commit()
    reopened(session, adapter, site)
    run(session, telegram, T0 + 5 * MIN)

    [event] = events(session)
    assert (event.status, event.last_error) == ("SKIPPED", "알림이 꺼져 있음")

    # 다시 켜도 꺼져 있던 동안의 알림이 몰려 나가지 않는다.
    set_setting(session, "notifications_enabled", True)
    session.commit()
    run(session, telegram, T0 + 6 * MIN)
    assert telegram.sent == []


def test_unconfigured_telegram_records_skipped_events(session, adapter, site):
    telegram = FakeTelegram(configured=False)
    reopened(session, adapter, site)
    counts = run(session, telegram, T0 + 5 * MIN)

    assert counts["sent"] == 0 and telegram.calls == 0
    assert [(e.status, e.last_error) for e in events(session)] == [("SKIPPED", "Telegram 미설정")]


# ---------------------------------------------------------------- 오픈 예정


OPENS = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)  # 2026-11-25 00:00 KST


def upcoming_notice(session, adapter, site):
    adapter.listing = [
        notice("S5", "안내중", title="동부 도로사업소 테니스장 A코트 평일 야간 12월1일~15일", reception_start_at=OPENS),
        notice("S6", "안내중", title="동부 도로사업소 테니스장 A코트 주말 및 공휴일 12월1일~15일", reception_start_at=OPENS),
    ]
    collector.run_list_sync(session, adapter, site, T0)


def test_opening_alerts_fire_at_each_offset_exactly_once(session, adapter, site, telegram):
    upcoming_notice(session, adapter, site)

    run(session, telegram, OPENS - timedelta(days=1, minutes=1))
    assert telegram.sent == []

    moments = [OPENS - timedelta(days=1), OPENS - timedelta(hours=1), OPENS - 10 * MIN]
    for moment in moments:
        run(session, telegram, moment)
        run(session, telegram, moment + 30 * SEC)  # 다음 주기에 중복으로 나가지 않는다

    assert [m.splitlines()[0] for m in telegram.sent] == [
        "[Tennis Watch] 예약 오픈 예정 (1일 전)",
        "[Tennis Watch] 예약 오픈 예정 (1시간 전)",
        "[Tennis Watch] 예약 오픈 예정 (10분 전)",
    ]
    message = telegram.sent[0]
    assert "시설: 동부도로사업소 테니스장" in message
    assert "오픈: 2026-11-25 00:00 (수)" in message
    # 같은 시각에 열리는 공고 두 개가 한 메시지로 묶인다.
    assert " - 동부 도로사업소 테니스장 A코트 평일 야간 12월1일~15일" in message
    assert " - 동부 도로사업소 테니스장 A코트 주말 및 공휴일 12월1일~15일" in message

    run(session, telegram, OPENS)  # 열린 뒤에는 예고를 보내지 않는다
    assert len(telegram.sent) == 3


def test_only_the_latest_due_offset_is_sent_after_downtime(session, adapter, site, telegram):
    upcoming_notice(session, adapter, site)
    run(session, telegram, OPENS - 5 * MIN)  # 그동안 꺼져 있다가 오픈 5분 전에 켜짐

    assert [m.splitlines()[0] for m in telegram.sent] == ["[Tennis Watch] 예약 오픈 예정 (10분 전)"]
    statuses = {e.dedupe_key.rsplit(":", 1)[1]: e.status for e in events(session)}
    assert statuses == {"1440": "SKIPPED", "60": "SKIPPED", "10": "SENT"}


def test_opening_alert_offsets_follow_settings(session, adapter, site, telegram):
    upcoming_notice(session, adapter, site)
    set_setting(session, "opening_alert_offsets_minutes", [30])
    session.commit()

    run(session, telegram, OPENS - timedelta(hours=1))
    assert telegram.sent == []
    run(session, telegram, OPENS - 30 * MIN)
    assert [m.splitlines()[0] for m in telegram.sent] == ["[Tennis Watch] 예약 오픈 예정 (30분 전)"]


def test_changed_opening_time_is_announced_again(session, adapter, site, telegram):
    upcoming_notice(session, adapter, site)
    run(session, telegram, OPENS - timedelta(hours=1))
    moved = OPENS + timedelta(hours=9)
    adapter.listing = [replace_start(n, moved) for n in adapter.listing]
    collector.run_list_sync(session, adapter, site, OPENS - 50 * MIN)
    run(session, telegram, moved - timedelta(hours=1))

    assert len(telegram.sent) == 2 and "오픈: 2026-11-25 09:00 (수)" in telegram.sent[1]


def replace_start(item, start):
    from dataclasses import replace

    return replace(item, reception_start_at=start)


def test_opening_alert_respects_watch_rules(session, adapter, site, telegram):
    upcoming_notice(session, adapter, site)
    facility = session.query(Facility).one()
    session.add(WatchRule(facility_id=facility.id, weekdays=[5, 6]))  # 주말만
    session.commit()

    run(session, telegram, OPENS - 10 * MIN)

    [message] = telegram.sent
    assert "주말 및 공휴일" in message and "평일 야간" not in message


def test_no_opening_alert_for_unwatched_facility(session, adapter, site, telegram):
    adapter.listing = [notice("S5", "안내중", place="홍은테니스장", area="서대문구", reception_start_at=OPENS)]
    collector.run_list_sync(session, adapter, site, T0)
    facility = session.query(Facility).one()
    opening_rules.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.ONE_TIME, opens_at=OPENS
    )
    session.commit()
    run(session, telegram, OPENS - 10 * MIN)

    assert telegram.sent == []


def maru(session, adapter, site, count=6):
    names = ["1면", "2면", "3면", "1면 (조명)", "2면 (조명)", "3면 (조명)"][:count]
    adapter.listing = [notice(f"M{i}", title=f"마루공원 테니스장 {n}", place="마루공원") for i, n in enumerate(names)]
    collector.run_list_sync(session, adapter, site, T0)
    for i, n in enumerate(names):
        adapter.details[f"M{i}"] = detail(f"M{i}", title=f"마루공원 테니스장 {n}")
    collector.run_detail_sync(session, adapter, site, T0)


def test_rolling_openings_are_grouped_and_sent_every_day_without_the_day_before_alert(
    session, adapter, site, telegram
):
    maru(session, adapter, site)
    today_open = datetime(2026, 11, 14, 5, 0, tzinfo=UTC)  # 11/14 14:00 KST

    # 전날 14시: "1일 전" 알림은 보내지 않는다(그 시각은 전날분 오픈 시각이다).
    run(session, telegram, today_open - timedelta(days=1))
    assert not [m for m in telegram.sent if "11-14 14:00" in m]
    telegram.sent.clear()

    run(session, telegram, today_open - timedelta(hours=1))
    run(session, telegram, today_open - 10 * MIN)
    assert [m.splitlines()[0] for m in telegram.sent] == [
        "[Tennis Watch] 예약 오픈 예정 (1시간 전)",
        "[Tennis Watch] 예약 오픈 예정 (10분 전)",
    ]
    message = telegram.sent[0]
    assert "오픈: 2026-11-14 14:00 (토)" in message
    assert "이용일: 2026-11-28 (토)" in message
    assert message.count(" - 마루공원 테니스장") == 6  # 공고 6개가 한 메시지에

    # 다음 날도 같은 방식으로 온다.
    telegram.sent.clear()
    run(session, telegram, today_open + timedelta(days=1) - 10 * MIN)
    assert len(telegram.sent) == 1 and "이용일: 2026-11-29 (일)" in telegram.sent[0]


def test_inferred_rule_is_labelled_in_the_message(session, adapter, site, telegram):
    adapter.listing = [notice("S1")]
    collector.run_list_sync(session, adapter, site, T0)
    facility = session.query(Facility).one()
    facility.booking_url = "https://example.test/booking"
    opening_rules.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=25, open_time=time(0, 0),
        target_description="다음 달 1~15일분", verification_status=VerificationStatus.INFERRED,
    )  # fmt: skip
    session.commit()

    run(session, telegram, OPENS - 10 * MIN)

    [message] = telegram.sent
    assert "오픈: 2026-11-25 00:00 (수)" in message and " - 다음 달 1~15일분" in message
    assert "※ 추정 규칙입니다" in message
    assert "예약 바로가기: https://example.test/booking" in message


# ---------------------------------------------------------------- 시스템 오류


def test_persistent_failure_alerts_once_per_outage(session, adapter, site, telegram):
    adapter.listing = [notice("S1")]
    collector.run_list_sync(session, adapter, site, T0)
    adapter.listing = adapter.html = AdapterError("HTTP 503: 점검 중")

    now = T0
    for _ in range(2):
        now += 5 * MIN
        collector.run_list_sync(session, adapter, site, now)
        run(session, telegram, now)
    assert telegram.sent == []  # 기준(3회) 전

    for _ in range(3):
        now += 5 * MIN
        collector.run_list_sync(session, adapter, site, now)
        run(session, telegram, now)
    assert len(telegram.sent) == 1
    message = telegram.sent[0]
    assert message.startswith("[Tennis Watch] 수집 오류")
    assert "연속 실패: 3회" in message
    assert "마지막 정상 수집: 2026-11-14 12:00" in message
    assert "AdapterError: HTTP 503: 점검 중" in message

    # 복구 후 새 장애가 나면 다시 알린다.
    adapter.listing = [notice("S1")]
    now += 5 * MIN
    collector.run_list_sync(session, adapter, site, now)
    adapter.listing = adapter.html = AdapterError("timeout")
    for _ in range(3):
        now += 5 * MIN
        collector.run_list_sync(session, adapter, site, now)
        run(session, telegram, now)
    assert len(telegram.sent) == 2


def test_block_sends_a_collection_stopped_alert_once(session, adapter, site, telegram):
    adapter.listing = BlockedError("차단")
    collector.run_list_sync(session, adapter, site, T0)
    run(session, telegram, T0)
    run(session, telegram, T0 + MIN)

    assert len(telegram.sent) == 1 and telegram.sent[0].startswith("[Tennis Watch] 수집 중지")


def test_system_alerts_are_sent_even_long_after_they_were_created(session, adapter, site, telegram):
    adapter.listing = BlockedError("차단")
    collector.run_list_sync(session, adapter, site, T0)
    telegram.outcomes = [TelegramError("오류")]
    run(session, telegram, T0)
    run(session, telegram, T0 + timedelta(hours=5))

    assert len(telegram.sent) == 1  # 오류 알림에는 만료가 없다
