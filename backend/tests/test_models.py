from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import init_db, make_engine
from app.models import (
    Court,
    CourtSlot,
    DataSource,
    Facility,
    NoticeStatusHistory,
    NotificationEvent,
    NotificationType,
    OpeningRule,
    ReservationNotice,
    RuleType,
    Site,
    SlotStatus,
    VerificationStatus,
)

EXPECTED_TABLES = {
    "sites",
    "facilities",
    "courts",
    "reservation_notices",
    "notice_status_history",
    "opening_rules",
    "court_slots",
    "slot_history",
    "watch_rules",
    "notification_events",
    "crawl_logs",
    "app_settings",
}


def make_facility(session, name="마루공원"):
    site = session.query(Site).one()
    facility = Facility(site_id=site.id, name=name, external_name=name, area="강남구")
    session.add(facility)
    session.flush()
    return facility


def test_all_tables_are_created_and_seoul_site_is_seeded(engine, session):
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    site = session.query(Site).one()
    assert (site.code, site.base_url) == ("seoul", "https://yeyak.seoul.go.kr")


def test_init_db_is_idempotent(engine, session):
    init_db(engine)
    init_db(engine)
    assert session.query(Site).count() == 1


def test_data_survives_restart(db_url):
    """프로세스를 다시 띄워도(엔진을 새로 만들어도) 데이터가 남는다."""
    first = make_engine(db_url)
    init_db(first)
    with Session(first) as session:
        facility = make_facility(session)
        facility.is_watched = True
        session.add(Court(facility_id=facility.id, name="3면"))
        session.commit()
    first.dispose()

    second = make_engine(db_url)
    init_db(second)
    with Session(second) as session:
        facility = session.query(Facility).one()
        assert facility.is_watched is True
        assert [c.name for c in facility.courts] == ["3면"]
        assert session.query(Site).count() == 1
    second.dispose()


def test_facility_and_court_names_are_unique_within_parent(session):
    facility = make_facility(session)
    session.add(Court(facility_id=facility.id, name="1면"))
    session.commit()

    session.add(Court(facility_id=facility.id, name="1면"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(Facility(site_id=facility.site_id, name="다른 이름", external_name="마루공원"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_a_facility_removes_its_courts(session):
    facility = make_facility(session)
    session.add(Court(facility_id=facility.id, name="1면"))
    session.commit()

    session.delete(facility)
    session.commit()
    assert session.query(Court).count() == 0


def test_notice_external_id_is_unique_per_site(session):
    site = session.query(Site).one()
    session.add(ReservationNotice(site_id=site.id, external_id="S1", title="a"))
    session.commit()
    session.add(ReservationNotice(site_id=site.id, external_id="S1", title="b"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_notice_defaults_to_unknown_and_keeps_status_history(session):
    site = session.query(Site).one()
    notice = ReservationNotice(site_id=site.id, external_id="S1", title="a")
    session.add(notice)
    session.commit()
    assert notice.status == SlotStatus.UNKNOWN

    notice.status_history.append(
        NoticeStatusHistory(
            old_status=SlotStatus.UNAVAILABLE,
            new_status=SlotStatus.AVAILABLE,
            old_raw_status="예약마감",
            new_raw_status="접수중",
        )
    )
    session.commit()
    session.expire_all()

    history = session.query(ReservationNotice).one().status_history
    assert [(h.old_raw_status, h.new_raw_status) for h in history] == [("예약마감", "접수중")]
    assert history[0].changed_at.tzinfo is UTC


def test_auto_and_manual_opening_rules_coexist(session):
    """자동 수집 규칙과 수동 규칙은 서로 덮어쓰지 않고 따로 저장된다."""
    facility = make_facility(session)
    session.add_all(
        [
            OpeningRule(
                facility_id=facility.id,
                rule_type=RuleType.DAYS_BEFORE_USE,
                source=DataSource.AUTO,
                days_before=14,
                open_time=time(14, 0),
                verification_status=VerificationStatus.VERIFIED,
            ),
            OpeningRule(
                facility_id=facility.id,
                rule_type=RuleType.DAYS_BEFORE_USE,
                source=DataSource.MANUAL,
                days_before=7,
                open_time=time(9, 0),
                verification_status=VerificationStatus.CONFLICT,
            ),
        ]
    )
    session.commit()

    rules = session.query(OpeningRule).order_by(OpeningRule.id).all()
    assert [(r.source, r.days_before) for r in rules] == [("AUTO", 14), ("MANUAL", 7)]
    assert all(r.is_active for r in rules)


def test_slot_keeps_auto_and_manual_status_separately(session):
    facility = make_facility(session)
    slot = CourtSlot(
        facility_id=facility.id,
        use_date=date(2026, 11, 28),
        start_time=time(18, 0),
        end_time=time(20, 0),
    )
    session.add(slot)
    session.commit()

    # 서울시 사이트는 슬롯을 자동 확인할 수 없으므로 기본값은 UNKNOWN이다.
    assert slot.auto_status == SlotStatus.UNKNOWN
    assert slot.has_conflict is False

    slot.manual_status = SlotStatus.AVAILABLE
    assert slot.has_conflict is False  # 자동값이 UNKNOWN이면 충돌이 아니다

    slot.auto_status = SlotStatus.UNAVAILABLE
    session.commit()
    assert slot.has_conflict is True
    assert (slot.auto_status, slot.manual_status) == ("UNAVAILABLE", "AVAILABLE")


def test_notification_dedupe_key_is_unique(session):
    def event():
        return NotificationEvent(
            type=NotificationType.OPENING_SOON, dedupe_key="opening:S1:60m", message="m"
        )

    session.add(event())
    session.commit()
    session.add(event())
    with pytest.raises(IntegrityError):
        session.commit()


def test_sqlite_foreign_keys_are_enforced(session):
    session.add(Court(facility_id=9999, name="없는 시설의 코트"))
    with pytest.raises(IntegrityError):
        session.commit()
