from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models.enums import (
    ChangeKind,
    DataSource,
    DayType,
    RuleType,
    SlotStatus,
    TimeBand,
    VerificationStatus,
)
from app.models.facility import Court, Facility
from app.timeutil import utcnow


class ReservationNotice(Base):
    """예약 공고. 서울시 사이트의 서비스(rsv_svc_id) 하나에 해당한다."""

    __tablename__ = "reservation_notices"
    __table_args__ = (UniqueConstraint("site_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id", ondelete="SET NULL"))
    court_id: Mapped[int | None] = mapped_column(ForeignKey("courts.id", ondelete="SET NULL"))
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    place_name: Mapped[str | None] = mapped_column(String(200))
    area: Mapped[str | None] = mapped_column(String(50))
    detail_url: Mapped[str | None] = mapped_column(String(500))

    status: Mapped[SlotStatus] = mapped_column(String(16), default=SlotStatus.UNKNOWN)
    # 사이트 원문 상태(접수중, 예약마감 등). 예약마감과 접수종료를 구분하는 데 필요하다.
    raw_status: Mapped[str | None] = mapped_column(String(30))

    reception_start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reception_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # 이용 기간과 하루 운영 시각은 한국 기준의 날짜·시각 그대로 저장한다.
    use_start_date: Mapped[date | None] = mapped_column(Date)
    use_end_date: Mapped[date | None] = mapped_column(Date)
    daily_open_time: Mapped[time | None] = mapped_column(Time)
    daily_close_time: Mapped[time | None] = mapped_column(Time)

    # 이용일 기준 롤링 접수 규칙(상세 페이지에서만 수집됨). 예: 14일 전 14시부터
    open_days_before: Mapped[int | None] = mapped_column(Integer)
    open_hour: Mapped[int | None] = mapped_column(Integer)
    close_days_before: Mapped[int | None] = mapped_column(Integer)
    close_hour: Mapped[int | None] = mapped_column(Integer)
    min_use_hours: Mapped[int | None] = mapped_column(Integer)
    max_use_hours: Mapped[int | None] = mapped_column(Integer)

    selection_method: Mapped[str | None] = mapped_column(String(30))
    fee_type: Mapped[str | None] = mapped_column(String(20))
    target: Mapped[str | None] = mapped_column(String(200))
    # 공고명에서 추출한 값. 표기가 시설마다 달라 확실하지 않다.
    day_type: Mapped[DayType] = mapped_column(String(10), default=DayType.UNKNOWN)
    time_band: Mapped[TimeBand] = mapped_column(String(10), default=TimeBand.UNKNOWN)
    lighting: Mapped[bool] = mapped_column(Boolean, default=False)
    # 사용자가 보정한 필드 이름. 자동 수집이 이 필드는 덮어쓰지 않는다.
    locked_fields: Mapped[list[str]] = mapped_column(JSON, default=list)

    # 최근 목록 수집에 포함되었는지. 이용 종료된 공고는 목록에서 빠진다.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    detail_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    facility: Mapped[Facility | None] = relationship()
    court: Mapped[Court | None] = relationship()
    status_history: Mapped[list["NoticeStatusHistory"]] = relationship(
        back_populates="notice", cascade="all, delete-orphan", order_by="NoticeStatusHistory.id"
    )


class NoticeStatusHistory(Base):
    """공고 접수 상태의 변경 이력. 접수 재개 감지의 근거가 된다."""

    __tablename__ = "notice_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("reservation_notices.id", ondelete="CASCADE"))
    old_status: Mapped[SlotStatus | None] = mapped_column(String(16))
    new_status: Mapped[SlotStatus] = mapped_column(String(16))
    old_raw_status: Mapped[str | None] = mapped_column(String(30))
    new_raw_status: Mapped[str | None] = mapped_column(String(30))
    kind: Mapped[ChangeKind] = mapped_column(String(10), default=ChangeKind.OTHER)
    # 알림을 보내도 되는 변경인지. 최초 수집, 수집 실패 뒤 복구, UNKNOWN에서의 변경은 False다.
    notifiable: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    notice: Mapped[ReservationNotice] = relationship(back_populates="status_history")


class OpeningRule(Base):
    """예약 오픈 규칙.

    자동 수집 규칙과 수동 규칙은 별도 행으로 둔다. 서로 다르면 양쪽을 보존하고
    verification_status를 CONFLICT로 표시한다. 규칙을 고치면 기존 행을 닫고
    (is_active=False, valid_to) 새 행을 만들어 변경 이력을 남긴다.
    """

    __tablename__ = "opening_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"))
    court_id: Mapped[int | None] = mapped_column(ForeignKey("courts.id", ondelete="SET NULL"))
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("reservation_notices.id", ondelete="SET NULL"))
    rule_type: Mapped[RuleType] = mapped_column(String(20))
    source: Mapped[DataSource] = mapped_column(String(10))

    # MONTHLY: 매월 day_of_month일 open_time
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    # DAYS_BEFORE_USE: 이용일 days_before일 전 open_time
    days_before: Mapped[int | None] = mapped_column(Integer)
    # 한국 기준 시각
    open_time: Mapped[time | None] = mapped_column(Time)
    # ONE_TIME, NOTICE: 오픈 일시
    opens_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # 이 오픈으로 열리는 이용 기간. MONTHLY는 설명으로 적는다(예: "16일~말일").
    target_use_start: Mapped[date | None] = mapped_column(Date)
    target_use_end: Mapped[date | None] = mapped_column(Date)
    target_description: Mapped[str | None] = mapped_column(String(200))

    source_url: Mapped[str | None] = mapped_column(String(500))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        String(12), default=VerificationStatus.UNVERIFIED
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    note: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    replaces_id: Mapped[int | None] = mapped_column(ForeignKey("opening_rules.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    facility: Mapped[Facility] = relationship()
