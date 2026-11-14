from datetime import date, datetime, time

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
