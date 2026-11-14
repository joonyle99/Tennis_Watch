from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest

from app.models import ReservationNotice, Site
from app.timeutil import kst_datetime, kst_to_utc, kst_today, to_kst


def test_kst_to_utc_is_nine_hours_behind():
    assert kst_to_utc(datetime(2026, 11, 10, 0, 0)) == datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def test_to_kst_round_trip():
    utc = datetime(2026, 11, 14, 5, 0, tzinfo=UTC)
    kst = to_kst(utc)
    assert (kst.year, kst.month, kst.day, kst.hour) == (2026, 11, 14, 14)
    assert kst == utc


def test_kst_today_changes_at_korean_midnight():
    assert kst_today(datetime(2026, 11, 13, 14, 59, tzinfo=UTC)) == date(2026, 11, 13)
    assert kst_today(datetime(2026, 11, 13, 15, 0, tzinfo=UTC)) == date(2026, 11, 14)


def test_kst_datetime_combines_korean_date_and_time():
    assert kst_datetime(date(2026, 11, 14), time(14, 0)) == datetime(2026, 11, 14, 5, 0, tzinfo=UTC)


def test_naive_and_aware_inputs_are_not_mixed_up():
    with pytest.raises(ValueError):
        kst_to_utc(datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError):
        to_kst(datetime(2026, 1, 1))


def test_database_stores_utc_and_returns_aware_values(session):
    site = session.query(Site).one()
    kst_midnight = datetime(2026, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    session.add(
        ReservationNotice(site_id=site.id, external_id="S1", title="t", reception_start_at=kst_midnight)
    )
    session.commit()
    session.expire_all()

    stored = session.query(ReservationNotice).one().reception_start_at
    assert stored.tzinfo is UTC
    assert stored == datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    raw = session.connection().exec_driver_sql(
        "SELECT reception_start_at FROM reservation_notices"
    ).scalar()
    assert raw.startswith("2026-11-09 15:00:00")


def test_database_rejects_naive_datetime(session):
    site = session.query(Site).one()
    session.add(
        ReservationNotice(
            site_id=site.id, external_id="S1", title="t", reception_start_at=datetime(2026, 11, 10)
        )
    )
    with pytest.raises(Exception, match="시간대 없는"):
        session.commit()
