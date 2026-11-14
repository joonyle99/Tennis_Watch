from datetime import date, time

import pytest

from app.models import ChangeKind, CourtSlot, Facility, Site, SlotStatus
from app.services.availability import apply_auto_slot_status, classify_change, set_manual_slot_status
from tests.helpers import T0

A, U, N, C, X = (
    SlotStatus.AVAILABLE,
    SlotStatus.UNAVAILABLE,
    SlotStatus.NOT_OPEN,
    SlotStatus.CLOSED,
    SlotStatus.UNKNOWN,
)


@pytest.mark.parametrize(
    ("old", "new", "after_failure", "kind", "notifiable"),
    [
        (None, A, False, ChangeKind.INITIAL, False),  # 최초 수집
        (U, A, False, ChangeKind.REOPENED, True),  # 예약 불가 → 가능
        (U, A, True, ChangeKind.REOPENED, False),  # 수집 실패 뒤 복구
        (X, A, False, ChangeKind.OTHER, False),  # UNKNOWN → 가능
        (C, A, False, ChangeKind.OTHER, False),  # 휴장 → 가능
        (N, A, False, ChangeKind.OPENED, True),  # 실제 오픈
        (N, A, True, ChangeKind.OPENED, True),
        (A, U, False, ChangeKind.OTHER, False),
        (A, X, False, ChangeKind.OTHER, False),
        (N, U, False, ChangeKind.OTHER, False),
    ],
)
def test_classify_change(old, new, after_failure, kind, notifiable):
    assert classify_change(old, new, after_failure=after_failure) == (kind, notifiable)


@pytest.fixture
def slot(session):
    site = session.query(Site).one()
    facility = Facility(site_id=site.id, name="f", external_name="f")
    session.add(facility)
    session.flush()
    slot = CourtSlot(
        facility_id=facility.id, use_date=date(2026, 11, 21), start_time=time(18), end_time=time(20)
    )
    session.add(slot)
    session.commit()
    return slot


def test_first_slot_observation_is_not_a_vacancy(slot):
    entry = apply_auto_slot_status(slot, A, T0, first_seen=True)
    assert (entry.kind, entry.notifiable) == (ChangeKind.INITIAL, False)
    assert slot.auto_checked_at == T0


def test_slot_reopening_is_detected_every_time(slot):
    """불가 → 가능 → 불가 → 가능: 가능해질 때마다 새 알림 대상이 된다."""
    apply_auto_slot_status(slot, U, T0, first_seen=True)
    first = apply_auto_slot_status(slot, A, T0)
    apply_auto_slot_status(slot, U, T0)
    second = apply_auto_slot_status(slot, A, T0)

    assert first.notifiable and second.notifiable and first is not second
    assert [h.new_status for h in slot.history] == [U, A, U, A]


def test_unchanged_slot_records_only_the_check_time(slot, session):
    apply_auto_slot_status(slot, U, T0, first_seen=True)
    later = T0.replace(hour=4)
    assert apply_auto_slot_status(slot, U, later) is None
    assert slot.auto_checked_at == later and len(slot.history) == 1


def test_uncertain_court_suppresses_vacancy_alert(slot):
    apply_auto_slot_status(slot, U, T0, first_seen=True)
    entry = apply_auto_slot_status(slot, A, T0, court_uncertain=True)
    assert (entry.kind, entry.notifiable) == (ChangeKind.REOPENED, False)


def test_manual_status_is_kept_apart_from_auto_status(slot):
    apply_auto_slot_status(slot, U, T0, first_seen=True)
    set_manual_slot_status(slot, A, T0, note="직접 확인")

    assert (slot.auto_status, slot.manual_status) == (U, A)
    assert slot.has_conflict is True
    assert slot.history[-1].source == "MANUAL" and slot.history[-1].notifiable is False

    # 이후 자동 수집이 와도 수동값은 그대로다.
    apply_auto_slot_status(slot, U, T0)
    assert slot.manual_status == A and slot.manual_note == "직접 확인"
