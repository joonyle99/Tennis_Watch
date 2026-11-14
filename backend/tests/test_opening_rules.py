from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.models import (
    DataSource,
    Facility,
    OpeningRule,
    ReservationNotice,
    RuleType,
    Site,
    VerificationStatus,
    WatchRule,
)
from app.services import opening_rules as svc
from app.timeutil import to_kst
from tests.helpers import T0


def kst(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC) - timedelta(hours=9)


@pytest.fixture
def facility(session):
    site = session.query(Site).one()
    facility = Facility(site_id=site.id, name="마루공원", external_name="마루공원", is_watched=True)
    session.add(facility)
    session.commit()
    return facility


def test_rolling_open_time_matches_the_site_example():
    """사이트 안내: 11.28일 예약신청은 14일전(11.14) 14시부터 개시."""
    assert svc.rolling_open_at(date(2026, 11, 28), 14, time(14, 0)) == kst(2026, 11, 14, 14)


def test_rolling_open_time_crosses_month_and_year():
    assert svc.rolling_open_at(date(2027, 1, 5), 14, time(14, 0)) == kst(2026, 12, 22, 14)


def test_monthly_occurrences_use_korean_calendar():
    # 매월 10일 00:00 KST는 UTC로 9일 15:00이다.
    got = list(svc.monthly_occurrences(10, time(0, 0), kst(2026, 11, 1), kst(2027, 1, 31)))
    assert got == [kst(2026, 11, 10), kst(2026, 12, 10), kst(2027, 1, 10)]
    assert got[0] == datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def test_monthly_occurrences_respect_window_edges():
    start = kst(2026, 11, 10, 0, 1)  # 이번 달 오픈은 1분 전에 지남
    assert list(svc.monthly_occurrences(10, time(0, 0), start, kst(2026, 12, 10))) == [kst(2026, 12, 10)]


def test_monthly_occurrences_skip_months_without_that_day():
    got = list(svc.monthly_occurrences(30, time(9, 0), kst(2027, 1, 1), kst(2027, 3, 31)))
    assert [to_kst(d).month for d in got] == [1, 3]  # 2월 30일은 없다


def test_upcoming_openings_combine_rule_types_in_time_order(session, facility):
    session.add_all(
        [
            OpeningRule(
                facility_id=facility.id, rule_type=RuleType.MONTHLY, source=DataSource.MANUAL,
                day_of_month=25, open_time=time(0, 0), target_description="다음 달 1~15일",
                verification_status=VerificationStatus.INFERRED,
            ),
            OpeningRule(
                facility_id=facility.id, rule_type=RuleType.NOTICE, source=DataSource.AUTO,
                opens_at=kst(2026, 11, 20, 9), target_use_start=date(2026, 12, 1),
                target_use_end=date(2026, 12, 15),
            ),
            OpeningRule(  # 이미 지난 오픈
                facility_id=facility.id, rule_type=RuleType.ONE_TIME, source=DataSource.MANUAL,
                opens_at=kst(2026, 11, 1),
            ),
            OpeningRule(  # 닫힌 규칙
                facility_id=facility.id, rule_type=RuleType.ONE_TIME, source=DataSource.MANUAL,
                opens_at=kst(2026, 11, 21), is_active=False,
            ),
        ]
    )  # fmt: skip
    session.commit()

    openings = svc.upcoming_openings(session, T0, horizon_days=14)

    assert [(o.rule_type, o.opens_at) for o in openings] == [
        (RuleType.NOTICE, kst(2026, 11, 20, 9)),
        (RuleType.MONTHLY, kst(2026, 11, 25)),
    ]
    assert openings[0].use_start == date(2026, 12, 1)
    assert openings[1].verification_status == VerificationStatus.INFERRED


def rolling_rule(facility):
    return OpeningRule(
        facility_id=facility.id, rule_type=RuleType.DAYS_BEFORE_USE, source=DataSource.AUTO,
        days_before=14, open_time=time(14, 0),
    )  # fmt: skip


def test_rolling_rule_opens_every_day_without_watch_rules(session, facility):
    session.add(rolling_rule(facility))
    session.commit()

    # T0는 11/14 12:00 KST. 오늘 14시 오픈(11/28 이용분)부터 3일 뒤까지.
    openings = svc.upcoming_openings(session, T0, horizon_days=3)

    assert [(to_kst(o.opens_at).day, o.use_start) for o in openings] == [
        (14, date(2026, 11, 28)),
        (15, date(2026, 11, 29)),
        (16, date(2026, 11, 30)),
    ]
    assert all(to_kst(o.opens_at).hour == 14 for o in openings)


def test_rolling_rule_is_narrowed_to_watched_use_dates(session, facility):
    """관심 조건이 토요일이면, 토요일 이용분이 열리는 날의 오픈만 남는다."""
    session.add(rolling_rule(facility))
    session.add(WatchRule(facility_id=facility.id, weekdays=[5]))
    session.commit()

    openings = svc.upcoming_openings(session, T0, horizon_days=14)

    assert [o.use_start for o in openings] == [date(2026, 11, 28), date(2026, 12, 5)]
    assert all(o.use_start.weekday() == 5 for o in openings)
    assert openings[0].opens_at == kst(2026, 11, 14, 14)


def test_rolling_rule_ignores_watch_rules_that_do_not_want_opening_alerts(session, facility):
    session.add(rolling_rule(facility))
    session.add(WatchRule(facility_id=facility.id, weekdays=[5], notify_opening=False))
    session.commit()
    assert len(svc.upcoming_openings(session, T0, horizon_days=3)) == 3


def test_manual_rule_edit_keeps_history(session, facility):
    rule = svc.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=10, open_time=time(9, 0)
    )
    later = T0 + timedelta(days=1)
    new_rule = svc.replace_manual_rule(session, rule, later, open_time=time(0, 0))
    session.commit()

    assert (rule.is_active, rule.valid_to, rule.open_time) == (False, later, time(9, 0))
    assert (new_rule.is_active, new_rule.replaces_id, new_rule.open_time) == (True, rule.id, time(0, 0))
    assert new_rule.day_of_month == 10 and new_rule.source == DataSource.MANUAL

    with pytest.raises(ValueError, match="닫힌"):
        svc.replace_manual_rule(session, rule, later, open_time=time(1, 0))


def test_manual_rule_requires_the_values_for_its_type(session, facility):
    with pytest.raises(ValueError):
        svc.create_manual_rule(session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=10)
    with pytest.raises(ValueError):
        svc.create_manual_rule(session, T0, facility_id=facility.id, rule_type=RuleType.ONE_TIME)


def test_auto_rules_cannot_be_edited(session, facility):
    rule = rolling_rule(facility)
    session.add(rule)
    session.commit()
    with pytest.raises(ValueError, match="자동 수집"):
        svc.replace_manual_rule(session, rule, T0, days_before=7)


def test_manual_rolling_rule_is_checked_against_the_collected_rule(session, facility):
    session.add(rolling_rule(facility))
    session.commit()

    same = svc.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.DAYS_BEFORE_USE, days_before=14, open_time=time(14, 0)
    )
    different = svc.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.DAYS_BEFORE_USE, days_before=7, open_time=time(9, 0)
    )
    session.commit()

    assert same.verification_status == VerificationStatus.VERIFIED
    assert different.verification_status == VerificationStatus.CONFLICT
    # 충돌해도 양쪽 값은 그대로 남는다.
    assert different.days_before == 7
    auto = session.query(OpeningRule).filter_by(source=DataSource.AUTO).one()
    assert (auto.days_before, auto.is_active) == (14, True)


def _notice(session, facility, opened_at, external_id="S9"):
    notice = ReservationNotice(
        site_id=facility.site_id, facility_id=facility.id, external_id=external_id, title="t",
        reception_start_at=opened_at,
    )  # fmt: skip
    session.add(notice)
    session.flush()
    return notice


def test_new_notice_verifies_the_matching_monthly_rule(session, facility):
    tenth = svc.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=10,
        open_time=time(0, 0), verification_status=VerificationStatus.INFERRED,
    )  # fmt: skip
    twenty_fifth = svc.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=25,
        open_time=time(0, 0), verification_status=VerificationStatus.INFERRED,
    )  # fmt: skip

    svc.verify_monthly_rules(session, _notice(session, facility, kst(2026, 11, 25)), T0)

    assert twenty_fifth.verification_status == VerificationStatus.VERIFIED
    assert twenty_fifth.last_verified_at == T0
    assert tenth.verification_status == VerificationStatus.INFERRED  # 이번 공고와 무관


def test_new_notice_that_contradicts_the_rules_flags_the_nearest_one(session, facility):
    tenth = svc.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=10, open_time=time(0, 0)
    )
    twenty_fifth = svc.create_manual_rule(
        session, T0, facility_id=facility.id, rule_type=RuleType.MONTHLY, day_of_month=25, open_time=time(0, 0)
    )

    # 25일이 아니라 26일 09:00에 열렸다.
    svc.verify_monthly_rules(session, _notice(session, facility, kst(2026, 11, 26, 9)), T0)

    assert twenty_fifth.verification_status == VerificationStatus.CONFLICT
    assert "2026-11-26 09:00" in twenty_fifth.note
    assert (twenty_fifth.day_of_month, twenty_fifth.open_time) == (25, time(0, 0))  # 값은 그대로
    assert tenth.verification_status == VerificationStatus.UNVERIFIED
