from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models.enums import ChangeKind, DataSource, SlotStatus
from app.timeutil import utcnow


class CourtSlot(Base):
    """코트·날짜·시간대 단위의 예약 상태.

    서울시 사이트는 이 단위의 데이터를 자동 수집할 수 없어 auto_status는 UNKNOWN으로 남는다.
    사용자가 직접 확인해 넣은 값은 manual_* 열에 따로 둔다.
    """

    __tablename__ = "court_slots"
    __table_args__ = (
        UniqueConstraint("facility_id", "court_id", "use_date", "start_time", "end_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"))
    court_id: Mapped[int | None] = mapped_column(ForeignKey("courts.id", ondelete="CASCADE"))
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("reservation_notices.id", ondelete="SET NULL"))
    use_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    auto_status: Mapped[SlotStatus] = mapped_column(String(16), default=SlotStatus.UNKNOWN)
    auto_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    manual_status: Mapped[SlotStatus | None] = mapped_column(String(16))
    manual_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    manual_note: Mapped[str | None] = mapped_column(Text)

    history: Mapped[list["SlotHistory"]] = relationship(
        back_populates="slot", cascade="all, delete-orphan", order_by="SlotHistory.id"
    )

    @property
    def has_conflict(self) -> bool:
        """자동 확인값과 수동 입력값이 모두 있고 서로 다르다."""
        return (
            self.manual_status is not None
            and self.auto_status != SlotStatus.UNKNOWN
            and self.manual_status != self.auto_status
        )


class SlotHistory(Base):
    __tablename__ = "slot_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("court_slots.id", ondelete="CASCADE"))
    source: Mapped[DataSource] = mapped_column(String(10))
    old_status: Mapped[SlotStatus | None] = mapped_column(String(16))
    new_status: Mapped[SlotStatus] = mapped_column(String(16))
    kind: Mapped[ChangeKind] = mapped_column(String(10), default=ChangeKind.OTHER)
    notifiable: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    slot: Mapped[CourtSlot] = relationship(back_populates="history")
