"""예약 가능 상태의 변경을 해석한다.

알림 대상은 두 가지 전이뿐이다.
- 접수 시작 전 → 예약 가능: 실제 예약 오픈
- 예약 불가 → 예약 가능: 접수 재개(빈 코트)

같은 전이가 다시 일어나면(불가 → 가능 → 불가 → 가능) 그때마다 새 변경으로 기록된다.
"""

from datetime import datetime

from app.models import (
    ChangeKind,
    CourtSlot,
    DataSource,
    SlotHistory,
    SlotStatus,
)


def classify_change(
    old: SlotStatus | None, new: SlotStatus, *, after_failure: bool = False
) -> tuple[ChangeKind, bool]:
    """(변경 종류, 알림 가능 여부)를 돌려준다.

    after_failure: 수집 실패 뒤 처음 성공한 수집에서 발견된 변경. 그 사이 무슨 일이
    있었는지 알 수 없으므로 접수 재개 알림을 보내지 않는다.
    """
    if old is None:
        return ChangeKind.INITIAL, False
    if new != SlotStatus.AVAILABLE:
        return ChangeKind.OTHER, False
    if old == SlotStatus.NOT_OPEN:
        # 예정된 오픈이 실제로 열린 것은 수집 공백과 무관하게 확실한 사실이다.
        return ChangeKind.OPENED, True
    if old == SlotStatus.UNAVAILABLE:
        return ChangeKind.REOPENED, not after_failure
    # UNKNOWN, CLOSED에서 가능으로 바뀐 것은 취소표로 볼 근거가 없다.
    return ChangeKind.OTHER, False


def apply_auto_slot_status(
    slot: CourtSlot,
    new_status: SlotStatus,
    now: datetime,
    *,
    first_seen: bool = False,
    after_failure: bool = False,
    court_uncertain: bool = False,
) -> SlotHistory | None:
    """사이트에서 자동 확인한 슬롯 상태를 반영한다. 수동 입력값은 건드리지 않는다.

    서울시 사이트는 슬롯 단위 데이터를 주지 않아 지금은 호출하는 수집기가 없다.
    슬롯을 제공하는 사이트의 어댑터가 쓴다.
    """
    old = None if first_seen else slot.auto_status
    slot.auto_checked_at = now
    if not first_seen and old == new_status:
        return None
    slot.auto_status = new_status
    kind, notifiable = classify_change(old, new_status, after_failure=after_failure)
    if court_uncertain and kind == ChangeKind.REOPENED:
        notifiable = False
    entry = SlotHistory(
        source=DataSource.AUTO,
        old_status=old,
        new_status=new_status,
        kind=kind,
        notifiable=notifiable,
        changed_at=now,
    )
    slot.history.append(entry)
    return entry


def set_manual_slot_status(
    slot: CourtSlot, status: SlotStatus | None, now: datetime, note: str | None = None
) -> None:
    """사용자가 직접 확인한 상태를 기록한다. 자동 확인값과 별도로 저장되며 알림 대상이 아니다."""
    old = slot.manual_status
    slot.manual_status = status
    slot.manual_updated_at = now
    slot.manual_note = note
    if status is not None and status != old:
        slot.history.append(
            SlotHistory(
                source=DataSource.MANUAL,
                old_status=old,
                new_status=status,
                kind=ChangeKind.OTHER,
                notifiable=False,
                changed_at=now,
            )
        )
