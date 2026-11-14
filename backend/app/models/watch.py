from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models.enums import NotificationStatus, NotificationType
from app.models.facility import Court, Facility
from app.timeutil import utcnow


class WatchRule(Base):
    """개인 관심 조건. 비어 있는 항목은 제한 없음을 뜻한다."""

    __tablename__ = "watch_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(100))
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"))
    court_id: Mapped[int | None] = mapped_column(ForeignKey("courts.id", ondelete="CASCADE"))
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    # 월요일 0 ~ 일요일 6
    weekdays: Mapped[list[int]] = mapped_column(JSON, default=list)
    time_from: Mapped[time | None] = mapped_column(Time)
    time_to: Mapped[time | None] = mapped_column(Time)
    min_consecutive_hours: Mapped[int | None] = mapped_column(Integer)
    notify_opening: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_vacancy: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    facility: Mapped[Facility] = relationship()
    court: Mapped[Court | None] = relationship()


class NotificationEvent(Base):
    """알림 한 건. dedupe_key가 같은 알림은 한 번만 만들어진다."""

    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[NotificationType] = mapped_column(String(20))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id", ondelete="SET NULL"))
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("reservation_notices.id", ondelete="SET NULL"))
    slot_id: Mapped[int | None] = mapped_column(ForeignKey("court_slots.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(String(10), default=NotificationStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CrawlLog(Base):
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    job: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    success: Mapped[bool | None] = mapped_column(Boolean)
    item_count: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)


class AppSetting(Base):
    """웹 화면에서 바꾸는 설정. 값은 JSON으로 저장한다."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
