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
    include_inactive: bool = False,
    session: Session = Depends(get_session),
):
    """예약 공고. 기본은 현재 사이트 목록에 있는 공고만 준다."""
    stmt = select(ReservationNotice).order_by(
        ReservationNotice.reception_start_at.desc(), ReservationNotice.id
    )
    if facility_id is not None:
        stmt = stmt.where(ReservationNotice.facility_id == facility_id)
    if status is not None:
        stmt = stmt.where(ReservationNotice.status == status)
    if not include_inactive:
        stmt = stmt.where(ReservationNotice.is_active)
    if watched is not None:
        stmt = stmt.join(Facility, ReservationNotice.facility_id == Facility.id).where(
            Facility.is_watched == watched
        )
    return session.scalars(stmt).all()


# ---------------------------------------------------------------- Phase 3: 수집 엔진

from datetime import date, timedelta  # noqa: E402

from fastapi import Request  # noqa: E402

from app.models import (  # noqa: E402
    CourtSlot,
    CrawlLog,
    NoticeStatusHistory,
    OpeningRule,
    WatchRule,
)
from app.services import availability, collector, opening_rules  # noqa: E402
from app.services import settings as app_settings  # noqa: E402


def get_collector(request: Request):
    runner = getattr(request.app.state, "collector", None)
    if runner is None:
        raise HTTPException(503, "수집기가 준비되지 않았습니다")
    return runner


def _check_court(session: Session, facility_id: int, court_id: int | None) -> None:
    _get_or_404(session, Facility, facility_id)
    if court_id is not None:
        court = _get_or_404(session, Court, court_id)
        if court.facility_id != facility_id:
            raise HTTPException(400, "코트가 해당 시설에 속하지 않습니다")


# ---- 수집 실행과 상태


@router.post("/sync", response_model=list[schemas.SyncResultOut])
def run_sync(runner=Depends(get_collector)):
    """지금 한 번 수집한다. 연속 실패로 인한 대기는 건너뛰지만, 차단으로 멈춘 상태는 건너뛰지 않는다."""
    return runner.run(force=True)


@router.post("/sync/resume", status_code=204)
def resume_sync(session: Session = Depends(get_session)):
    """사이트 차단으로 멈춘 수집을 다시 켠다."""
    app_settings.set_setting(session, "collection_paused_reason", None)
    session.commit()


@router.get("/status", response_model=schemas.SystemStatusOut)
def system_status(session: Session = Depends(get_session)):
    interval = app_settings.get_setting(session, "sync_interval_minutes")
    sites = [
        schemas.SiteStatusOut(
            site=schemas.SiteOut.model_validate(site),
            last_success_at=collector.last_success_at(session, site.id),
            consecutive_failures=collector.consecutive_failures(session, site.id),
            backoff_until=collector.backoff_until(session, site.id, interval),
        )
        for site in session.scalars(select(Site).order_by(Site.id)).all()
    ]
    logs = session.scalars(select(CrawlLog).order_by(CrawlLog.id.desc()).limit(30)).all()
    return schemas.SystemStatusOut(
        paused_reason=app_settings.get_setting(session, "collection_paused_reason"),
        sites=sites,
        recent_logs=[schemas.CrawlLogOut.model_validate(entry) for entry in logs],
    )


@router.get("/settings")
def read_settings(session: Session = Depends(get_session)):
    return app_settings.get_all(session)


@router.put("/settings")
def update_settings(
    body: schemas.SettingsUpdate, request: Request, session: Session = Depends(get_session)
):
    try:
        for key, value in body.values.items():
            app_settings.set_setting(session, key, value)
    except KeyError as exc:
        raise HTTPException(400, f"없는 설정입니다: {exc.args[0]}") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None and "sync_interval_minutes" in body.values:
        from app.scheduler.jobs import reschedule_sync

        reschedule_sync(scheduler, body.values["sync_interval_minutes"])
    return app_settings.get_all(session)


# ---- 공고 보정과 변경 이력


@router.patch("/notices/{notice_id}", response_model=schemas.NoticeOut)
def update_notice(notice_id: int, body: schemas.NoticeUpdate, session: Session = Depends(get_session)):
    notice = _get_or_404(session, ReservationNotice, notice_id)
    changes = body.model_dump(exclude_unset=True)
    facility_id = changes.get("facility_id", notice.facility_id)
    if "facility_id" in changes and facility_id is not None:
        _get_or_404(session, Facility, facility_id)
    if changes.get("court_id") is not None:
        if facility_id is None:
            raise HTTPException(400, "시설이 없는 공고에는 코트를 지정할 수 없습니다")
        _check_court(session, facility_id, changes["court_id"])
    for field, value in changes.items():
        setattr(notice, field, value)
    notice.locked_fields = sorted(set(notice.locked_fields) | changes.keys())
    session.commit()
    return notice


@router.get("/notices/{notice_id}/history", response_model=list[schemas.StatusChangeOut])
def notice_history(notice_id: int, session: Session = Depends(get_session)):
    return _get_or_404(session, ReservationNotice, notice_id).status_history


@router.get("/changes", response_model=list[schemas.StatusChangeOut])
def recent_changes(
    kind: schemas.ChangeKind | None = None,
    notifiable: bool | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    """최근 상태 변경. 최초 수집 기록은 기본으로 제외한다."""
    stmt = select(NoticeStatusHistory).order_by(NoticeStatusHistory.id.desc()).limit(min(limit, 200))
    if kind is not None:
        stmt = stmt.where(NoticeStatusHistory.kind == kind)
    else:
        stmt = stmt.where(NoticeStatusHistory.kind != schemas.ChangeKind.INITIAL)
    if notifiable is not None:
        stmt = stmt.where(NoticeStatusHistory.notifiable == notifiable)
    return session.scalars(stmt).all()


# ---- 예약 오픈 규칙


@router.get("/opening-rules", response_model=list[schemas.OpeningRuleOut])
def list_opening_rules(
    facility_id: int | None = None, include_inactive: bool = False, session: Session = Depends(get_session)
):
    """예약 오픈 규칙. include_inactive를 켜면 고치기 전 규칙(변경 이력)도 함께 준다."""
    stmt = select(OpeningRule).order_by(OpeningRule.facility_id, OpeningRule.id)
    if facility_id is not None:
        stmt = stmt.where(OpeningRule.facility_id == facility_id)
    if not include_inactive:
        stmt = stmt.where(OpeningRule.is_active)
    return session.scalars(stmt).all()


@router.post("/opening-rules", response_model=schemas.OpeningRuleOut, status_code=201)
def create_opening_rule(body: schemas.OpeningRuleCreate, session: Session = Depends(get_session)):
    _check_court(session, body.facility_id, body.court_id)
    try:
        rule = opening_rules.create_manual_rule(session, utcnow(), **body.model_dump())
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from None
    session.commit()
    return rule


@router.patch("/opening-rules/{rule_id}", response_model=schemas.OpeningRuleOut)
def update_opening_rule(
    rule_id: int, body: schemas.OpeningRuleUpdate, session: Session = Depends(get_session)
):
    """수동 규칙을 고친다. 기존 규칙은 닫히고 새 규칙이 만들어진다(변경 이력 보존)."""
    rule = _get_or_404(session, OpeningRule, rule_id)
    changes = body.model_dump(exclude_unset=True)
    if "court_id" in changes:
        _check_court(session, rule.facility_id, changes["court_id"])
    try:
        new_rule = opening_rules.replace_manual_rule(session, rule, utcnow(), **changes)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(409, str(exc)) from None
    session.commit()
    return new_rule


@router.delete("/opening-rules/{rule_id}", status_code=204)
def delete_opening_rule(rule_id: int, session: Session = Depends(get_session)):
    rule = _get_or_404(session, OpeningRule, rule_id)
    if rule.source != DataSource.MANUAL:
        raise HTTPException(409, "자동 수집된 규칙은 지울 수 없습니다")
    opening_rules.close_rule(session, rule, utcnow())
    session.commit()


@router.get("/openings", response_model=list[schemas.OpeningOut])
def list_openings(
    days: int = 30,
    facility_id: int | None = None,
    watched: bool = True,
    session: Session = Depends(get_session),
):
    """앞으로 days일 안의 예약 오픈 예정. 기본은 관심 시설만."""
    if not 1 <= days <= 120:
        raise HTTPException(422, "days는 1~120이어야 합니다")
    openings = opening_rules.upcoming_openings(session, utcnow(), days, facility_id)
    if watched:
        watched_ids = set(session.scalars(select(Facility.id).where(Facility.is_watched)).all())
        openings = [o for o in openings if o.facility_id in watched_ids]
    return openings


# ---- 관심 조건


@router.get("/watch-rules", response_model=list[schemas.WatchRuleOut])
def list_watch_rules(facility_id: int | None = None, session: Session = Depends(get_session)):
    stmt = select(WatchRule).order_by(WatchRule.id)
    if facility_id is not None:
        stmt = stmt.where(WatchRule.facility_id == facility_id)
    return session.scalars(stmt).all()


@router.post("/watch-rules", response_model=schemas.WatchRuleOut, status_code=201)
def create_watch_rule(body: schemas.WatchRuleCreate, session: Session = Depends(get_session)):
    _check_court(session, body.facility_id, body.court_id)
    rule = WatchRule(**body.model_dump())
    session.add(rule)
    session.commit()
    return rule


@router.put("/watch-rules/{rule_id}", response_model=schemas.WatchRuleOut)
def replace_watch_rule(rule_id: int, body: schemas.WatchRuleBase, session: Session = Depends(get_session)):
    rule = _get_or_404(session, WatchRule, rule_id)
    _check_court(session, rule.facility_id, body.court_id)
    for field, value in body.model_dump().items():
        setattr(rule, field, value)
    session.commit()
    return rule


@router.delete("/watch-rules/{rule_id}", status_code=204)
def delete_watch_rule(rule_id: int, session: Session = Depends(get_session)):
    session.delete(_get_or_404(session, WatchRule, rule_id))
    session.commit()


# ---- 수동 슬롯 상태


@router.get("/slots", response_model=list[schemas.SlotOut])
def list_slots(
    facility_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    stmt = select(CourtSlot).order_by(CourtSlot.use_date, CourtSlot.start_time, CourtSlot.id)
    if facility_id is not None:
        stmt = stmt.where(CourtSlot.facility_id == facility_id)
    if date_from is not None:
        stmt = stmt.where(CourtSlot.use_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(CourtSlot.use_date <= date_to)
    return session.scalars(stmt.limit(1000)).all()


@router.put("/slots/manual", response_model=schemas.SlotOut)
def set_manual_slot(body: schemas.SlotManualIn, session: Session = Depends(get_session)):
    """사용자가 직접 확인한 슬롯 상태를 기록한다. 자동 확인값과 따로 저장된다."""
    _check_court(session, body.facility_id, body.court_id)
    stmt = select(CourtSlot).where(
        CourtSlot.facility_id == body.facility_id,
        CourtSlot.use_date == body.use_date,
        CourtSlot.start_time == body.start_time,
        CourtSlot.end_time == body.end_time,
    )
    stmt = stmt.where(
        CourtSlot.court_id.is_(None) if body.court_id is None else CourtSlot.court_id == body.court_id
    )
    slot = session.scalar(stmt)
    if slot is None:
        slot = CourtSlot(
            facility_id=body.facility_id,
            court_id=body.court_id,
            use_date=body.use_date,
            start_time=body.start_time,
            end_time=body.end_time,
        )
        session.add(slot)
    availability.set_manual_slot_status(slot, body.status, utcnow(), body.note)
    session.commit()
    return slot


# ---------------------------------------------------------------- Phase 4: Telegram 알림

from app.models import NotificationEvent  # noqa: E402
from app.services.telegram import TelegramClient, TelegramError  # noqa: E402
from app.timeutil import to_kst as _to_kst  # noqa: E402


def get_telegram(request: Request) -> TelegramClient:
    client = getattr(request.app.state, "telegram", None)
    if client is None:
        raise HTTPException(503, "Telegram 클라이언트가 준비되지 않았습니다")
    return client


@router.get("/telegram", response_model=schemas.TelegramStatusOut)
def telegram_status(client: TelegramClient = Depends(get_telegram), session: Session = Depends(get_session)):
    """설정 여부만 알려 준다. 토큰과 채팅 ID 값은 내보내지 않는다."""
    return schemas.TelegramStatusOut(
        token_set=bool(client.token),
        chat_id_set=bool(client.chat_id),
        notifications_enabled=app_settings.get_setting(session, "notifications_enabled"),
    )


@router.post("/telegram/test", response_model=schemas.TelegramTestOut)
def telegram_test(client: TelegramClient = Depends(get_telegram)):
    """봇 토큰을 확인하고 테스트 메시지를 보낸다."""
    try:
        name = client.bot_name()
        client.send_message(
            f"[Tennis Watch] 연결 테스트\n\n알림이 이 채팅으로 전송됩니다.\n확인시각: {_to_kst(utcnow()):%Y-%m-%d %H:%M}"
        )
    except TelegramError as exc:
        return schemas.TelegramTestOut(ok=False, error=str(exc))
    return schemas.TelegramTestOut(ok=True, bot_name=name)


@router.get("/telegram/chats", response_model=list[schemas.TelegramChatOut])
def telegram_chats(client: TelegramClient = Depends(get_telegram)):
    """봇에게 최근 메시지를 보낸 채팅. TELEGRAM_CHAT_ID에 넣을 값을 찾는 데 쓴다."""
    try:
        return client.recent_chats()
    except TelegramError as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/notifications", response_model=list[schemas.NotificationOut])
def list_notifications(
    status: schemas.NotificationStatus | None = None,
    type: schemas.NotificationType | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    stmt = select(NotificationEvent).order_by(NotificationEvent.id.desc()).limit(min(limit, 200))
    if status is not None:
        stmt = stmt.where(NotificationEvent.status == status)
    if type is not None:
        stmt = stmt.where(NotificationEvent.type == type)
    return session.scalars(stmt).all()
