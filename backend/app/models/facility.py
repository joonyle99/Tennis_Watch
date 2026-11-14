from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models.enums import DataSource
from app.timeutil import utcnow


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(300))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    facilities: Mapped[list["Facility"]] = relationship(back_populates="site")


class Facility(Base):
    """테니스장. 사이트에는 시설 엔터티가 없어 공고의 장소명으로 묶어 만든다."""

    __tablename__ = "facilities"
    __table_args__ = (UniqueConstraint("site_id", "external_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    name: Mapped[str] = mapped_column(String(200))
    # 사이트가 쓰는 장소명. 새 공고를 이 시설에 연결하는 키다.
    external_name: Mapped[str | None] = mapped_column(String(200))
    # 같은 시설을 가리키는 다른 장소명 표기
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    area: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(50))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    booking_url: Mapped[str | None] = mapped_column(String(500))
    memo: Mapped[str | None] = mapped_column(Text)
    source: Mapped[DataSource] = mapped_column(String(10), default=DataSource.AUTO)
    # 사용자가 고친 필드 이름. 자동 수집이 이 필드는 덮어쓰지 않는다.
    locked_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_watched: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    site: Mapped[Site] = relationship(back_populates="facilities")
    courts: Mapped[list["Court"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan", order_by="Court.name"
    )


class Court(Base):
    __tablename__ = "courts"
    __table_args__ = (UniqueConstraint("facility_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    source: Mapped[DataSource] = mapped_column(String(10), default=DataSource.AUTO)
    # 공고명에서 추출한 코트는 사용자가 확인하기 전까지 False
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_watched: Mapped[bool] = mapped_column(Boolean, default=False)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    facility: Mapped[Facility] = relationship(back_populates="courts")
