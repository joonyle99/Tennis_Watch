from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import schemas
from app.db import get_session
from app.models import Court, DataSource, Facility, ReservationNotice, Site, SlotStatus
from app.timeutil import to_kst, utcnow

router = APIRouter(prefix="/api")

# 자동 수집이 채우는 시설 필드. 사용자가 고치면 잠가서 덮어쓰지 않게 한다.
AUTO_FACILITY_FIELDS = {"name", "area", "address", "phone", "booking_url"}


def _get_or_404(session: Session, model, item_id: int):
    item = session.get(model, item_id)
    if item is None:
        raise HTTPException(404, "찾을 수 없습니다")
    return item


def _commit(session: Session, conflict_message: str) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, conflict_message) from None


@router.get("/health")
def health(session: Session = Depends(get_session)):
    session.execute(text("SELECT 1"))
    now = utcnow()
    return {"status": "ok", "time_utc": now.isoformat(), "time_kst": to_kst(now).isoformat()}


@router.get("/sites", response_model=list[schemas.SiteOut])
def list_sites(session: Session = Depends(get_session)):
    return session.scalars(select(Site).order_by(Site.id)).all()


@router.get("/facilities", response_model=list[schemas.FacilityOut])
def list_facilities(
    watched: bool | None = None,
    area: str | None = None,
    q: str | None = None,
    session: Session = Depends(get_session),
):
    stmt = select(Facility).order_by(Facility.area, Facility.name)
    if watched is not None:
        stmt = stmt.where(Facility.is_watched == watched)
    if area:
        stmt = stmt.where(Facility.area == area)
    if q:
        stmt = stmt.where(Facility.name.contains(q))
    return session.scalars(stmt).all()


@router.post("/facilities", response_model=schemas.FacilityOut, status_code=201)
def create_facility(body: schemas.FacilityCreate, session: Session = Depends(get_session)):
    site = session.scalar(select(Site).where(Site.code == body.site_code))
    if site is None:
        raise HTTPException(400, f"등록되지 않은 사이트입니다: {body.site_code}")
    facility = Facility(
        site_id=site.id,
        source=DataSource.MANUAL,
        **body.model_dump(exclude={"site_code"}),
    )
    session.add(facility)
    _commit(session, "같은 장소명의 시설이 이미 있습니다")
    return facility


@router.get("/facilities/{facility_id}", response_model=schemas.FacilityOut)
def get_facility(facility_id: int, session: Session = Depends(get_session)):
    return _get_or_404(session, Facility, facility_id)


@router.patch("/facilities/{facility_id}", response_model=schemas.FacilityOut)
def update_facility(
    facility_id: int, body: schemas.FacilityUpdate, session: Session = Depends(get_session)
):
    facility = _get_or_404(session, Facility, facility_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(facility, field, value)
    locked = set(facility.locked_fields) | (changes.keys() & AUTO_FACILITY_FIELDS)
    facility.locked_fields = sorted(locked)
    session.commit()
    return facility


@router.delete("/facilities/{facility_id}", status_code=204)
def delete_facility(facility_id: int, session: Session = Depends(get_session)):
    facility = _get_or_404(session, Facility, facility_id)
    if facility.source != DataSource.MANUAL:
        raise HTTPException(
            409, "자동 수집된 시설은 삭제할 수 없습니다. 관심 해제(is_watched=false)를 사용하세요."
        )
    session.delete(facility)
    session.commit()


@router.post("/facilities/{facility_id}/courts", response_model=schemas.CourtOut, status_code=201)
def create_court(
    facility_id: int, body: schemas.CourtCreate, session: Session = Depends(get_session)
):
    _get_or_404(session, Facility, facility_id)
    court = Court(
        facility_id=facility_id, source=DataSource.MANUAL, verified=True, **body.model_dump()
    )
    session.add(court)
    _commit(session, "같은 이름의 코트가 이미 있습니다")
    return court


@router.patch("/courts/{court_id}", response_model=schemas.CourtOut)
def update_court(court_id: int, body: schemas.CourtUpdate, session: Session = Depends(get_session)):
    court = _get_or_404(session, Court, court_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(court, field, value)
    _commit(session, "같은 이름의 코트가 이미 있습니다")
    return court


@router.delete("/courts/{court_id}", status_code=204)
def delete_court(court_id: int, session: Session = Depends(get_session)):
    session.delete(_get_or_404(session, Court, court_id))
    session.commit()


@router.get("/notices", response_model=list[schemas.NoticeOut])
def list_notices(
    facility_id: int | None = None,
    status: SlotStatus | None = None,
    watched: bool | None = None,
    active: bool | None = True,
    session: Session = Depends(get_session),
):
    stmt = select(ReservationNotice).order_by(
        ReservationNotice.reception_start_at.desc(), ReservationNotice.id
    )
    if facility_id is not None:
        stmt = stmt.where(ReservationNotice.facility_id == facility_id)
    if status is not None:
        stmt = stmt.where(ReservationNotice.status == status)
    if active is not None:
        stmt = stmt.where(ReservationNotice.is_active == active)
    if watched is not None:
        stmt = stmt.join(Facility, ReservationNotice.facility_id == Facility.id).where(
            Facility.is_watched == watched
        )
    return session.scalars(stmt).all()
