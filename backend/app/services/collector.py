"""수집 엔진: 어댑터가 가져온 공고를 DB와 비교해 저장하고 변경을 기록한다.

수집 실패 정책
- 실패한 수집에서는 저장된 상태를 바꾸지 않는다(값을 추측하지 않는다).
- 연속 실패가 failure_threshold에 이르면 진행 중인 공고의 상태를 UNKNOWN으로 바꾼다.
  오래된 값을 최신인 것처럼 보여 주지 않기 위해서다.
- 실패 뒤 처음 성공한 수집에서 발견된 접수 재개는 알림 대상에서 뺀다.
- 사이트가 차단하면 수집을 멈추고, 사용자가 다시 켤 때까지 요청하지 않는다.
"""

import logging
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import (
    AdapterError,
    BlockedError,
    NoticeData,
    NoticeDetail,
    SiteAdapter,
)
from app.config import Settings, get_settings
from app.models import (
    ChangeKind,
    Court,
    CrawlLog,
    DataSource,
    Facility,
    NoticeStatusHistory,
    OpeningRule,
    ReservationNotice,
    RuleType,
    Site,
    SlotStatus,
    VerificationStatus,
)
from app.services import opening_rules
from app.services.availability import classify_change
from app.services.settings import get_setting, set_setting
from app.services.watch import should_notify
from app.timeutil import utcnow

log = logging.getLogger(__name__)

JOB_LIST = "list"
JOB_DETAIL = "detail"

# 목록 수집으로 갱신하는 공고 필드. 값이 없는(None) 항목으로는 덮어쓰지 않는다.
_LIST_FIELDS = (
    "title", "place_name", "area", "detail_url", "reception_start_at", "reception_end_at",
    "use_start_date", "use_end_date", "daily_open_time", "daily_close_time",
    "selection_method", "fee_type", "target",
)  # fmt: skip
_DETAIL_FIELDS = (
    "title", "reception_start_at", "reception_end_at", "use_start_date", "use_end_date",
    "selection_method", "fee_type", "open_days_before", "open_hour", "close_days_before",
    "close_hour", "min_use_hours", "max_use_hours",
)  # fmt: skip


@dataclass
class SyncResult:
    job: str
    ok: bool
    source: str | None = None
    seen: int = 0
    created: int = 0
    changed: int = 0
    notifiable: int = 0
    error_type: str | None = None
    error: str | None = None
    skipped: str | None = None
    changes: list[int] = field(default_factory=list)  # notice_status_history.id


# ---------------------------------------------------------------- 수집 기록


def consecutive_failures(session: Session, site_id: int, job: str = JOB_LIST) -> int:
    """가장 최근 성공 이후 연속으로 실패한 횟수."""
    logs = session.scalars(
        select(CrawlLog)
        .where(CrawlLog.site_id == site_id, CrawlLog.job == job, CrawlLog.success.is_not(None))
        .order_by(CrawlLog.id.desc())
        .limit(50)
    ).all()
    count = 0
    for entry in logs:
        if entry.success:
            break
        count += 1
    return count


def last_success_at(session: Session, site_id: int, job: str = JOB_LIST) -> datetime | None:
    return session.scalar(
        select(CrawlLog.finished_at)
        .where(CrawlLog.site_id == site_id, CrawlLog.job == job, CrawlLog.success)
        .order_by(CrawlLog.id.desc())
        .limit(1)
    )


def backoff_until(session: Session, site_id: int, interval_minutes: int) -> datetime | None:
    """연속 실패 중이면 다음 시도가 허용되는 시각. 실패할수록 간격이 두 배씩 늘어난다(최대 1시간)."""
    failures = consecutive_failures(session, site_id)
    if failures == 0:
        return None
    last = session.scalar(
        select(CrawlLog.finished_at)
        .where(CrawlLog.site_id == site_id, CrawlLog.job == JOB_LIST)
        .order_by(CrawlLog.id.desc())
        .limit(1)
    )
    if last is None:
        return None
    wait = min(interval_minutes * 2 ** (failures - 1), 60)
    return last + timedelta(minutes=wait)


def _finish_log(session: Session, entry: CrawlLog, result: SyncResult, now: datetime, started: float) -> None:
    # now는 수집을 시작한 시각이다. 종료 시각은 실제로 걸린 시간을 더해 기록한다.
    entry.finished_at = now + timedelta(seconds=round(time_module.monotonic() - started))
    entry.success = result.ok
    entry.item_count = result.seen
    entry.error_type = result.error_type
    entry.error_message = result.error
    session.commit()


# ---------------------------------------------------------------- 목록 수집


def _fetch_list(
    adapter: SiteAdapter, session: Session, site: Site, has_key: bool
) -> tuple[list[NoticeData], set[str] | None, str]:
    """(공고 목록, 수집 범위 지역, 수집 경로). 범위가 None이면 전체 목록이다."""
    if has_key:
        try:
            return adapter.fetch_notices(), None, "openapi"
        except BlockedError:
            raise
        except AdapterError as exc:
            log.warning("Open API 수집 실패, HTML 목록으로 대체합니다: %s", exc)
            openapi_error = exc
    else:
        openapi_error = None

    # HTML 목록은 페이지당 6건이라 관심 시설이 있는 지역만 수집한다.
    areas = set(
        session.scalars(
            select(Facility.area).where(
                Facility.site_id == site.id, Facility.is_watched, Facility.area.is_not(None)
            )
        ).all()
    )
    if not areas:
        areas = _default_areas()
    if not areas:
        raise openapi_error or AdapterError(
            "HTML 목록으로 수집할 지역이 없습니다. 관심 시설을 등록하거나 Open API 키를 설정하세요."
        )
    notices: list[NoticeData] = []
    for area in sorted(areas):
        notices.extend(adapter.fetch_notices_html(area))
    return notices, areas, "html"


def _default_areas() -> set[str]:
    """관심 시설이 아직 하나도 없을 때 HTML 수집을 시작할 지역."""
    areas = get_settings().default_watched_areas
    return {a.strip() for a in areas.split(",") if a.strip()}


def run_list_sync(
    session: Session,
    adapter: SiteAdapter,
    site: Site,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> SyncResult:
    now = now or utcnow()
    settings = settings or get_settings()
    result = SyncResult(job=JOB_LIST, ok=False)

    started = time_module.monotonic()
    failures_before = consecutive_failures(session, site.id)
    entry = CrawlLog(site_id=site.id, job=JOB_LIST, started_at=now)
    session.add(entry)
    session.commit()

    try:
        notices, scope, source = _fetch_list(
            adapter, session, site, has_key=bool(getattr(adapter, "api_key", ""))
        )
    except AdapterError as exc:
        session.rollback()
        result.error_type = type(exc).__name__
        result.error = str(exc)
        if isinstance(exc, BlockedError):
            set_setting(session, "collection_paused_reason", f"사이트 차단 감지 ({now:%Y-%m-%d %H:%M} UTC)")
        if failures_before + 1 >= get_setting(session, "failure_threshold"):
            _mark_unknown(session, site, now)
        _finish_log(session, entry, result, now, started)
        return result

    result.source = source
    result.seen = len(notices)
    watched_names = {n.strip() for n in settings.default_watched_places.split(",") if n.strip()}
    facilities = _FacilityIndex(session, site, watched_names)
    existing = {
        n.external_id: n
        for n in session.scalars(
            select(ReservationNotice).where(ReservationNotice.site_id == site.id)
        ).all()
    }
    after_failure = failures_before > 0

    seen_ids = set()
    for data in notices:
        if data.external_id in seen_ids:
            continue
        seen_ids.add(data.external_id)
        notice = existing.get(data.external_id)
        if notice is None:
            notice = _create_notice(session, site, data, adapter, facilities, now)
            existing[data.external_id] = notice
            result.created += 1
            opening_rules.verify_monthly_rules(session, notice, now)
        else:
            _update_notice_from_list(session, notice, data, adapter, facilities)
            change = _apply_status(session, notice, data.status, data.raw_status, now, after_failure)
            if change is not None:
                result.changed += 1
                result.changes.append(change.id)
                result.notifiable += change.notifiable
        notice.is_active = True
        notice.last_checked_at = now
        _sync_notice_rule(session, notice, now)

    # 이번 수집 범위에 있어야 하는데 목록에서 빠진 공고는 이용이 끝난 것이다.
    for notice in existing.values():
        if notice.external_id in seen_ids or not notice.is_active:
            continue
        if scope is None or notice.area in scope:
            notice.is_active = False

    result.ok = True
    _finish_log(session, entry, result, now, started)
    return result


class _FacilityIndex:
    """장소명으로 시설을 찾고, 없으면 만든다."""

    def __init__(self, session: Session, site: Site, watched_names: set[str]):
        self.session = session
        self.site = site
        self.watched_names = watched_names
        self.by_name: dict[str, Facility] = {}
        for facility in session.scalars(select(Facility).where(Facility.site_id == site.id)).all():
            for name in [facility.external_name, *facility.aliases]:
                if name:
                    self.by_name.setdefault(name, facility)

    def resolve(self, data: NoticeData) -> Facility | None:
        if not data.place_name:
            return None
        facility = self.by_name.get(data.place_name)
        if facility is None:
            facility = Facility(
                site_id=self.site.id,
                name=data.place_name,
                external_name=data.place_name,
                source=DataSource.AUTO,
                is_watched=data.place_name in self.watched_names,
                aliases=[],
                locked_fields=[],
            )
            self.session.add(facility)
            self.by_name[data.place_name] = facility
        # 자동 수집 값으로 빈 칸만 채운다. 사용자가 고친 필드는 건드리지 않는다.
        for attr, value in (
            ("area", data.area),
            ("phone", data.phone),
            ("latitude", data.latitude),
            ("longitude", data.longitude),
        ):
            if value is not None and attr not in (facility.locked_fields or []) and getattr(facility, attr) is None:
                setattr(facility, attr, value)
        self.session.flush()
        return facility


def _resolve_court(session: Session, facility: Facility | None, label: str | None) -> Court | None:
    if facility is None or not label:
        return None
    court = next((c for c in facility.courts if c.name == label), None)
    if court is None:
        # 공고명에서 추출한 코트는 사용자가 확인하기 전까지 verified=False다.
        court = Court(name=label, source=DataSource.AUTO, verified=False)
        facility.courts.append(court)
        session.flush()
    return court


def _apply_title(session: Session, notice: ReservationNotice, adapter: SiteAdapter, facility) -> None:
    info = adapter.parse_title(notice.title)
    locked = set(notice.locked_fields or [])
    if "court_id" not in locked:
        court = _resolve_court(session, facility, info.court_label)
        notice.court_id = court.id if court else None
    if "day_type" not in locked:
        notice.day_type = info.day_type
    if "time_band" not in locked:
        notice.time_band = info.time_band
    notice.lighting = info.lighting


def _create_notice(session, site, data: NoticeData, adapter, facilities: _FacilityIndex, now):
    facility = facilities.resolve(data)
    notice = ReservationNotice(
        site_id=site.id,
        external_id=data.external_id,
        facility_id=facility.id if facility else None,
        status=data.status,
        raw_status=data.raw_status,
        first_seen_at=now,
        status_changed_at=now,
        **{f: getattr(data, f) for f in _LIST_FIELDS},
    )
    session.add(notice)
    _apply_title(session, notice, adapter, facility)
    # 최초 수집은 변경이 아니다. 이력에는 남기되 알림 대상에서 뺀다.
    notice.status_history.append(
        NoticeStatusHistory(
            old_status=None,
            new_status=data.status,
            new_raw_status=data.raw_status,
            kind=ChangeKind.INITIAL,
            notifiable=False,
            changed_at=now,
        )
    )
    session.flush()
    return notice


def _update_notice_from_list(session, notice, data: NoticeData, adapter, facilities: _FacilityIndex):
    locked = set(notice.locked_fields or [])
    title_before = notice.title
    for attr in _LIST_FIELDS:
        value = getattr(data, attr)
        if value is not None and attr not in locked:
            setattr(notice, attr, value)
    facility = notice.facility
    if "facility_id" not in locked:
        facility = facilities.resolve(data)
        notice.facility_id = facility.id if facility else None
    if notice.title != title_before or notice.court_id is None:
        _apply_title(session, notice, adapter, facility)


def _apply_status(
    session: Session,
    notice: ReservationNotice,
    new_status: SlotStatus,
    new_raw: str | None,
    now: datetime,
    after_failure: bool,
) -> NoticeStatusHistory | None:
    """공고 상태를 반영하고, 바뀌었으면 이력 한 줄을 돌려준다.

    공고명이나 기간만 고쳐진 경우처럼 상태가 그대로면 변경으로 보지 않는다.
    """
    old_status, old_raw = SlotStatus(notice.status), notice.raw_status
    if old_status == new_status:
        notice.raw_status = new_raw
        return None
    kind, notifiable = classify_change(old_status, new_status, after_failure=after_failure)
    if notifiable:
        notifiable = should_notify(session, notice, kind)
    notice.status = new_status
    notice.raw_status = new_raw
    notice.status_changed_at = now
    change = NoticeStatusHistory(
        old_status=old_status,
        new_status=new_status,
        old_raw_status=old_raw,
        new_raw_status=new_raw,
        kind=kind,
        notifiable=notifiable,
        changed_at=now,
    )
    notice.status_history.append(change)
    session.flush()
    return change


def _mark_unknown(session: Session, site: Site, now: datetime) -> None:
    """수집이 계속 실패하면 진행 중인 공고의 상태를 확인 불가로 바꾼다."""
    notices = session.scalars(
        select(ReservationNotice).where(
            ReservationNotice.site_id == site.id,
            ReservationNotice.is_active,
            ReservationNotice.status != SlotStatus.UNKNOWN,
        )
    ).all()
    for notice in notices:
        notice.status_history.append(
            NoticeStatusHistory(
                old_status=notice.status,
                new_status=SlotStatus.UNKNOWN,
                old_raw_status=notice.raw_status,
                new_raw_status=None,
                kind=ChangeKind.OTHER,
                notifiable=False,
                changed_at=now,
            )
        )
        notice.status = SlotStatus.UNKNOWN
        notice.status_changed_at = now


# ---------------------------------------------------------------- 자동 오픈 규칙


def _sync_notice_rule(session: Session, notice: ReservationNotice, now: datetime) -> None:
    """관심 시설의 공고에 적힌 접수 시작 일시를 오픈 규칙으로 기록한다."""
    if notice.facility_id is None or notice.reception_start_at is None:
        return
    if not notice.facility or not notice.facility.is_watched:
        return
    # 롤링 오픈 공고의 접수 시작 일시는 서비스 개시일일 뿐, 예약이 열리는 시각이 아니다.
    if notice.open_days_before is not None:
        return
    rule = session.scalar(
        select(OpeningRule).where(
            OpeningRule.notice_id == notice.id,
            OpeningRule.rule_type == RuleType.NOTICE,
            OpeningRule.source == DataSource.AUTO,
            OpeningRule.is_active,
        )
    )
    if rule is None:
        rule = OpeningRule(
            facility_id=notice.facility_id,
            notice_id=notice.id,
            rule_type=RuleType.NOTICE,
            source=DataSource.AUTO,
            valid_from=now,
        )
        session.add(rule)
    rule.court_id = notice.court_id
    rule.opens_at = notice.reception_start_at
    rule.target_use_start = notice.use_start_date
    rule.target_use_end = notice.use_end_date
    rule.target_description = notice.title
    rule.source_url = notice.detail_url
    rule.verification_status = VerificationStatus.VERIFIED
    rule.last_verified_at = now


def _sync_rolling_rule(session: Session, notice: ReservationNotice, now: datetime) -> None:
    """상세 페이지의 '이용일 N일 전 HH시' 규칙을 기록한다. 값이 바뀌면 새 행으로 이력을 남긴다."""
    if notice.facility_id is None:
        return
    current = session.scalars(
        select(OpeningRule).where(
            OpeningRule.notice_id == notice.id,
            OpeningRule.rule_type == RuleType.DAYS_BEFORE_USE,
            OpeningRule.source == DataSource.AUTO,
            OpeningRule.is_active,
        )
    ).first()
    has_rule = notice.open_days_before is not None and notice.open_hour is not None
    wanted = (notice.open_days_before, time(notice.open_hour % 24, 0)) if has_rule else None

    if current is not None and (current.days_before, current.open_time) == wanted:
        current.court_id = notice.court_id
        current.last_verified_at = now
    else:
        replaced_id = None
        if current is not None:
            current.is_active = False
            current.valid_to = now
            replaced_id = current.id
        if wanted is not None:
            session.add(
                OpeningRule(
                    facility_id=notice.facility_id,
                    court_id=notice.court_id,
                    notice_id=notice.id,
                    rule_type=RuleType.DAYS_BEFORE_USE,
                    source=DataSource.AUTO,
                    days_before=wanted[0],
                    open_time=wanted[1],
                    target_description=notice.title,
                    source_url=notice.detail_url,
                    verification_status=VerificationStatus.VERIFIED,
                    last_verified_at=now,
                    valid_from=now,
                    replaces_id=replaced_id,
                )
            )
            # 롤링 오픈으로 확인된 공고에 접수 시작 일시 규칙이 남아 있으면 닫는다.
            for stale in session.scalars(
                select(OpeningRule).where(
                    OpeningRule.notice_id == notice.id,
                    OpeningRule.rule_type == RuleType.NOTICE,
                    OpeningRule.source == DataSource.AUTO,
                    OpeningRule.is_active,
                )
            ).all():
                stale.is_active = False
                stale.valid_to = now
    session.flush()
    opening_rules.refresh_conflicts(session, notice.facility_id, now)


# ---------------------------------------------------------------- 상세 수집


def notices_needing_detail(session: Session, now: datetime, *, hot_only: bool = False) -> list[ReservationNotice]:
    """상세 페이지를 확인할 공고. 관심 시설의 진행 중인 공고만 대상이다.

    접수 시작 전후 구간에 있는 공고가 먼저 오고, 그다음은 확인한 지 오래된 순이다.
    """
    before = timedelta(minutes=get_setting(session, "hot_window_before_minutes"))
    after = timedelta(minutes=get_setting(session, "hot_window_after_minutes"))
    refresh = timedelta(hours=get_setting(session, "detail_refresh_hours"))

    candidates = session.scalars(
        select(ReservationNotice)
        .join(Facility, ReservationNotice.facility_id == Facility.id)
        .where(Facility.is_watched, ReservationNotice.is_active)
    ).all()

    hot, stale = [], []
    for notice in candidates:
        start = notice.reception_start_at
        # 접수 시작 직전부터 실제로 열린 것이 확인될 때까지만 자주 확인한다.
        in_window = start is not None and start - before <= now <= start + after
        if in_window and notice.status != SlotStatus.AVAILABLE and notice.open_days_before is None:
            hot.append(notice)
        elif not hot_only and (
            notice.detail_checked_at is None or now - notice.detail_checked_at >= refresh
        ):
            stale.append(notice)
    stale.sort(key=lambda n: (n.detail_checked_at is not None, n.detail_checked_at or now, n.id))
    return hot + stale


def run_detail_sync(
    session: Session,
    adapter: SiteAdapter,
    site: Site,
    now: datetime | None = None,
    *,
    hot_only: bool = False,
) -> SyncResult:
    now = now or utcnow()
    job = JOB_DETAIL
    result = SyncResult(job=job, ok=False, source="html")
    targets = notices_needing_detail(session, now, hot_only=hot_only)
    targets = [n for n in targets if n.site_id == site.id][: get_setting(session, "detail_batch_size")]
    if not targets:
        result.ok = True
        result.skipped = "확인할 공고 없음"
        return result

    started = time_module.monotonic()
    entry = CrawlLog(site_id=site.id, job=job, started_at=now)
    session.add(entry)
    session.commit()
    after_failure = consecutive_failures(session, site.id, job) > 0

    errors = []
    for notice in targets:
        try:
            detail = adapter.fetch_notice_detail(notice.external_id)
        except BlockedError as exc:
            session.rollback()
            set_setting(session, "collection_paused_reason", f"사이트 차단 감지 ({now:%Y-%m-%d %H:%M} UTC)")
            result.error_type, result.error = type(exc).__name__, str(exc)
            _finish_log(session, entry, result, now, started)
            return result
        except AdapterError as exc:
            # 한 건이 실패해도 그 공고의 값은 그대로 두고 다음 공고로 넘어간다.
            errors.append(f"{notice.external_id}: {type(exc).__name__}: {exc}")
            continue
        result.seen += 1
        change = _apply_detail(session, notice, detail, now, after_failure)
        if change is not None:
            result.changed += 1
            result.changes.append(change.id)
            result.notifiable += change.notifiable

    result.ok = not errors
    if errors:
        result.error_type = "AdapterError"
        result.error = "; ".join(errors)[:2000]
    _finish_log(session, entry, result, now, started)
    return result


def _apply_detail(
    session: Session, notice: ReservationNotice, detail: NoticeDetail, now: datetime, after_failure: bool
) -> NoticeStatusHistory | None:
    locked = set(notice.locked_fields or [])
    for attr in _DETAIL_FIELDS:
        value = getattr(detail, attr)
        # 롤링 규칙 필드는 None도 의미가 있다(규칙이 없어진 경우).
        if attr in locked or (value is None and not attr.startswith(("open_", "close_"))):
            continue
        setattr(notice, attr, value)
    notice.detail_checked_at = now
    notice.last_checked_at = now
    change = _apply_status(session, notice, detail.status, detail.raw_status, now, after_failure)
    _sync_rolling_rule(session, notice, now)
    _sync_notice_rule(session, notice, now)
    return change
