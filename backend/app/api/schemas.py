from datetime import UTC, date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DataSource, DayType, SlotStatus, TimeBand


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SiteOut(Out):
    id: int
    code: str
    name: str
    base_url: str
    enabled: bool


class CourtOut(Out):
    id: int
    facility_id: int
    name: str
    source: DataSource
    verified: bool
    is_watched: bool
    memo: str | None


class CourtCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_watched: bool = False
    memo: str | None = None


class CourtUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    verified: bool | None = None
    is_watched: bool | None = None
    memo: str | None = None


class FacilityOut(Out):
    id: int
    site_id: int
    name: str
    external_name: str | None
    aliases: list[str]
    area: str | None
    address: str | None
    phone: str | None
    latitude: float | None
    longitude: float | None
    booking_url: str | None
    memo: str | None
    source: DataSource
    locked_fields: list[str]
    is_watched: bool
    courts: list[CourtOut]
    created_at: datetime
    updated_at: datetime


class FacilityCreate(BaseModel):
    """수동 시설 등록."""

    site_code: str = "seoul"
    name: str = Field(min_length=1, max_length=200)
    external_name: str | None = None
    area: str | None = None
    address: str | None = None
    phone: str | None = None
    booking_url: str | None = None
    memo: str | None = None
    is_watched: bool = True


class FacilityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    area: str | None = None
    address: str | None = None
    phone: str | None = None
    booking_url: str | None = None
    memo: str | None = None
    is_watched: bool | None = None


class NoticeOut(Out):
    id: int
    site_id: int
    facility_id: int | None
    court_id: int | None
    external_id: str
    title: str
    place_name: str | None
    area: str | None
    detail_url: str | None
    status: SlotStatus
    raw_status: str | None
    reception_start_at: datetime | None
    reception_end_at: datetime | None
    use_start_date: date | None
    use_end_date: date | None
    daily_open_time: time | None
    daily_close_time: time | None
    open_days_before: int | None
    open_hour: int | None
    selection_method: str | None
    fee_type: str | None
    day_type: DayType
    time_band: TimeBand
    is_active: bool
    last_checked_at: datetime | None
    status_changed_at: datetime | None


# ---------------------------------------------------------------- Phase 3

from typing import Any  # noqa: E402

from pydantic import model_validator  # noqa: E402

from app.models.enums import ChangeKind, RuleType, VerificationStatus  # noqa: E402


class NoticeUpdate(BaseModel):
    """자동 수집된 공고의 보정. 고친 항목은 이후 수집이 덮어쓰지 않는다."""

    facility_id: int | None = None
    court_id: int | None = None
    day_type: DayType | None = None
    time_band: TimeBand | None = None


class StatusChangeOut(Out):
    id: int
    notice_id: int
    old_status: SlotStatus | None
    new_status: SlotStatus
    old_raw_status: str | None
    new_raw_status: str | None
    kind: ChangeKind
    notifiable: bool
    changed_at: datetime


class OpeningRuleOut(Out):
    id: int
    facility_id: int
    court_id: int | None
    notice_id: int | None
    rule_type: RuleType
    source: DataSource
    day_of_month: int | None
    days_before: int | None
    open_time: time | None
    opens_at: datetime | None
    target_use_start: date | None
    target_use_end: date | None
    target_description: str | None
    source_url: str | None
    verification_status: VerificationStatus
    last_verified_at: datetime | None
    note: str | None
    is_active: bool
    valid_from: datetime
    valid_to: datetime | None
    replaces_id: int | None


class OpeningRuleCreate(BaseModel):
    """수동 예약 오픈 규칙. open_time은 한국시간, opens_at은 시간대를 포함한 일시."""

    facility_id: int
    court_id: int | None = None
    rule_type: RuleType
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    days_before: int | None = Field(default=None, ge=0, le=365)
    open_time: time | None = None
    opens_at: datetime | None = None
    target_use_start: date | None = None
    target_use_end: date | None = None
    target_description: str | None = None
    source_url: str | None = None
    note: str | None = None
    # 관측에서 추정한 규칙이면 INFERRED로 등록한다.
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED

    @model_validator(mode="after")
    def _aware(self):
        if self.opens_at is not None and self.opens_at.tzinfo is None:
            raise ValueError("opens_at에는 시간대가 있어야 합니다 (예: 2026-11-25T00:00:00+09:00)")
        if self.opens_at is not None:
            self.opens_at = self.opens_at.astimezone(UTC)
        return self


class OpeningRuleUpdate(BaseModel):
    court_id: int | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    days_before: int | None = Field(default=None, ge=0, le=365)
    open_time: time | None = None
    opens_at: datetime | None = None
    target_use_start: date | None = None
    target_use_end: date | None = None
    target_description: str | None = None
    source_url: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _aware(self):
        if self.opens_at is not None and self.opens_at.tzinfo is None:
            raise ValueError("opens_at에는 시간대가 있어야 합니다")
        if self.opens_at is not None:
            self.opens_at = self.opens_at.astimezone(UTC)
        return self


class OpeningOut(Out):
    rule_id: int
    facility_id: int
    court_id: int | None
    notice_id: int | None
    rule_type: RuleType
    source: DataSource
    verification_status: VerificationStatus
    opens_at: datetime
    use_start: date | None
    use_end: date | None
    description: str | None


class WatchRuleBase(BaseModel):
    name: str | None = None
    court_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    weekdays: list[int] = Field(default_factory=list, description="월요일 0 ~ 일요일 6")
    time_from: time | None = None
    time_to: time | None = None
    min_consecutive_hours: int | None = Field(default=None, ge=1, le=24)
    notify_opening: bool = True
    notify_vacancy: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def _ranges(self):
        if any(d < 0 or d > 6 for d in self.weekdays):
            raise ValueError("weekdays는 0(월)~6(일)이어야 합니다")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from이 date_to보다 늦습니다")
        if self.time_from and self.time_to and self.time_from >= self.time_to:
            raise ValueError("time_from이 time_to보다 늦거나 같습니다")
        return self


class WatchRuleCreate(WatchRuleBase):
    facility_id: int


class WatchRuleOut(WatchRuleBase, Out):
    id: int
    facility_id: int


class SlotManualIn(BaseModel):
    """사용자가 사이트에서 직접 확인한 슬롯 상태. status를 null로 보내면 수동값을 지운다."""

    facility_id: int
    court_id: int | None = None
    use_date: date
    start_time: time
    end_time: time
    status: SlotStatus | None
    note: str | None = None

    @model_validator(mode="after")
    def _order(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time이 end_time보다 늦거나 같습니다")
        return self


class SlotOut(Out):
    id: int
    facility_id: int
    court_id: int | None
    use_date: date
    start_time: time
    end_time: time
    auto_status: SlotStatus
    auto_checked_at: datetime | None
    manual_status: SlotStatus | None
    manual_updated_at: datetime | None
    manual_note: str | None
    has_conflict: bool


class SyncResultOut(Out):
    job: str
    ok: bool
    source: str | None
    seen: int
    created: int
    changed: int
    notifiable: int
    error_type: str | None
    error: str | None
    skipped: str | None


class CrawlLogOut(Out):
    id: int
    site_id: int
    job: str
    started_at: datetime
    finished_at: datetime | None
    success: bool | None
    item_count: int | None
    error_type: str | None
    error_message: str | None


class SiteStatusOut(BaseModel):
    site: SiteOut
    last_success_at: datetime | None
    consecutive_failures: int
    backoff_until: datetime | None


class SystemStatusOut(BaseModel):
    paused_reason: str | None
    sites: list[SiteStatusOut]
    recent_logs: list[CrawlLogOut]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


# ---------------------------------------------------------------- Phase 4

from app.models.enums import NotificationStatus, NotificationType  # noqa: E402


class NotificationOut(Out):
    id: int
    type: NotificationType
    status: NotificationStatus
    facility_id: int | None
    notice_id: int | None
    message: str
    attempts: int
    last_error: str | None
    expires_at: datetime | None
    next_attempt_at: datetime | None
    sent_at: datetime | None
    created_at: datetime


class TelegramStatusOut(BaseModel):
    token_set: bool
    chat_id_set: bool
    notifications_enabled: bool


class TelegramTestOut(BaseModel):
    ok: bool
    bot_name: str | None = None
    error: str | None = None


class TelegramChatOut(BaseModel):
    chat_id: str
    type: str | None
    name: str | None
