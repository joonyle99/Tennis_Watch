"""알림 생성과 발송.

생성: 상태 변경·오픈 예정·수집 오류에서 notification_events 행을 만든다. dedupe_key가
유일 키라 같은 알림은 한 번만 만들어진다.
발송: PENDING 행을 Telegram으로 보낸다. 실패하면 간격을 늘려 다시 시도하고, 재시작해도
DB에 남은 행에서 이어간다.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ChangeKind,
    Court,
    CrawlLog,
    Facility,
    NoticeStatusHistory,
    NotificationEvent,
    NotificationStatus,
    NotificationType,
    ReservationNotice,
    RuleType,
    Site,
    VerificationStatus,
)
from app.services import collector
from app.services.opening_rules import Opening, upcoming_openings
from app.services.settings import get_setting
from app.services.telegram import TelegramClient, TelegramError
from app.services.watch import should_notify
from app.timeutil import to_kst

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 600
# 상태 변경 알림은 이 시간이 지나면 보내지 않는다. 늦게 도착한 "접수 재개"는 오히려 혼란을 준다.
CHANGE_ALERT_MAX_AGE = timedelta(minutes=30)
SEND_BATCH = 10
WEEKDAYS = "월화수목금토일"


def _kst(value: datetime, with_weekday: bool = True) -> str:
    local = to_kst(value)
    text = f"{local:%Y-%m-%d %H:%M}"
    return f"{text} ({WEEKDAYS[local.weekday()]})" if with_weekday else text


def _offset_label(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일 전"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간 전"
    return f"{minutes}분 전"


def _add_event(
    session: Session,
    now: datetime,
    *,
    type: NotificationType,
    dedupe_key: str,
    message: str,
    expires_at: datetime | None,
    configured: bool,
    facility_id: int | None = None,
    notice_id: int | None = None,
    skip_reason: str | None = None,
) -> NotificationEvent | None:
    """같은 dedupe_key의 알림이 없을 때만 만든다."""
    if session.scalar(select(NotificationEvent.id).where(NotificationEvent.dedupe_key == dedupe_key)):
        return None
    if skip_reason is None and not get_setting(session, "notifications_enabled"):
        skip_reason = "알림이 꺼져 있음"
    if skip_reason is None and not configured:
        skip_reason = "Telegram 미설정"
    event = NotificationEvent(
        type=type,
        dedupe_key=dedupe_key,
        message=message,
        facility_id=facility_id,
        notice_id=notice_id,
        status=NotificationStatus.SKIPPED if skip_reason else NotificationStatus.PENDING,
        last_error=skip_reason,
        expires_at=expires_at,
        created_at=now,
    )
    session.add(event)
    session.flush()
    return event


# ---------------------------------------------------------------- 상태 변경 알림


def _change_message(session: Session, change: NoticeStatusHistory, notice: ReservationNotice) -> str:
    facility = session.get(Facility, notice.facility_id) if notice.facility_id else None
    court = session.get(Court, notice.court_id) if notice.court_id else None
    opened = change.kind == ChangeKind.OPENED
    lines = [
        "[Tennis Watch] 예약 오픈 확인" if opened else "[Tennis Watch] 접수 재개 (빈 코트 가능)",
        "",
        f"시설: {facility.name if facility else notice.place_name or '-'}",
        f"공고: {notice.title}",
    ]
    if court:
        lines.append(f"코트: {court.name}{'' if court.verified else ' (공고명에서 추출)'}")
    if notice.use_start_date and notice.use_end_date:
        lines.append(f"이용기간: {notice.use_start_date} ~ {notice.use_end_date}")
    lines.append(f"상태: {change.old_raw_status or change.old_status} → {change.new_raw_status or change.new_status}")
    lines.append(f"확인시각: {_kst(change.changed_at, with_weekday=False)}")
    if not opened:
        lines += ["", "어느 날짜·시간이 비었는지는 사이트에서 확인하세요."]
    if notice.detail_url:
        lines += ["", f"예약 바로가기: {notice.detail_url}"]
    return "\n".join(lines)


def enqueue_changes(session: Session, now: datetime, configured: bool) -> int:
    """알림 대상으로 기록된 공고 상태 변경을 알림으로 만든다."""
    since = now - timedelta(days=1)
    changes = session.scalars(
        select(NoticeStatusHistory)
        .where(NoticeStatusHistory.notifiable, NoticeStatusHistory.changed_at >= since)
        .order_by(NoticeStatusHistory.id)
    ).all()
    created = 0
    for change in changes:
        notice = change.notice
        opened = change.kind == ChangeKind.OPENED
        event = _add_event(
            session,
            now,
            type=NotificationType.OPENED if opened else NotificationType.REOPENED,
            dedupe_key=f"change:{change.id}",
            message=_change_message(session, change, notice),
            expires_at=change.changed_at + CHANGE_ALERT_MAX_AGE,
            configured=configured,
            facility_id=notice.facility_id,
            notice_id=notice.id,
        )
        created += event is not None
    return created


# ---------------------------------------------------------------- 오픈 예정 알림


def _opening_allowed(session: Session, opening: Opening) -> bool:
    facility = session.get(Facility, opening.facility_id)
    if facility is None or not facility.is_watched:
        return False
    if opening.notice_id is not None and opening.rule_type == RuleType.NOTICE:
        notice = session.get(ReservationNotice, opening.notice_id)
        return notice is not None and should_notify(session, notice, ChangeKind.OPENED)
    return True


def _opening_message(session: Session, facility: Facility, group: list[Opening], offset: int) -> str:
    first = group[0]
    lines = [
        f"[Tennis Watch] 예약 오픈 예정 ({_offset_label(offset)})",
        "",
        f"시설: {facility.name}",
        f"오픈: {_kst(first.opens_at)}",
    ]
    uses = {(o.use_start, o.use_end) for o in group if o.use_start}
    if len(uses) == 1:
        start, end = next(iter(uses))
        day = f"{start} ({WEEKDAYS[start.weekday()]})" if start == end else f"{start} ~ {end}"
        lines.append(f"이용일: {day}")
    targets = sorted({o.description for o in group if o.description})
    if targets:
        lines.append("대상:")
        lines += [f" - {t}" for t in targets[:12]]
        if len(targets) > 12:
            lines.append(f" - 외 {len(targets) - 12}건")
    if any(o.verification_status == VerificationStatus.INFERRED for o in group):
        lines.append("※ 추정 규칙입니다. 실제 오픈 시각과 다를 수 있습니다.")
    if any(o.verification_status == VerificationStatus.CONFLICT for o in group):
        lines.append("※ 수집된 값과 충돌하는 규칙입니다. 설정을 확인하세요.")

    url = None
    for opening in group:
        notice = session.get(ReservationNotice, opening.notice_id) if opening.notice_id else None
        if notice is not None and notice.detail_url:
            url = notice.detail_url
            break
    url = url if len({o.notice_id for o in group}) == 1 and url else (facility.booking_url or url)
    if url:
        lines += ["", f"예약 바로가기: {url}"]
    return "\n".join(lines)


def enqueue_openings(session: Session, now: datetime, configured: bool) -> int:
    """오픈 예정 알림을 만든다.

    같은 시설에서 같은 시각에 열리는 오픈은 한 건으로 묶는다(마루공원은 공고 6개가 동시에 열린다).
    보낼 시점이 여러 개 밀려 있으면(서버가 꺼져 있었던 경우) 가장 최근 시점 하나만 보낸다.
    """
    offsets = sorted(set(get_setting(session, "opening_alert_offsets_minutes")), reverse=True)
    if not offsets:
        return 0
    horizon_days = max(offsets) // 1440 + 1
    groups: dict[tuple[int, datetime], list[Opening]] = defaultdict(list)
    for opening in upcoming_openings(session, now, horizon_days):
        if _opening_allowed(session, opening):
            groups[(opening.facility_id, opening.opens_at)].append(opening)

    created = 0
    for (facility_id, opens_at), group in groups.items():
        facility = session.get(Facility, facility_id)
        usable = offsets
        if all(o.rule_type == RuleType.DAYS_BEFORE_USE for o in group):
            # 매일 열리는 규칙에서 "1일 전" 알림은 전날 오픈 시각과 겹치는 소음이다.
            usable = [m for m in offsets if m < 1440]
        due = [m for m in usable if opens_at - timedelta(minutes=m) <= now < opens_at]
        if not due:
            continue
        latest = min(due)
        for offset in due:
            event = _add_event(
                session,
                now,
                type=NotificationType.OPENING_SOON,
                dedupe_key=f"opening:{facility_id}:{opens_at:%Y%m%dT%H%M}:{offset}",
                message=_opening_message(session, facility, group, offset),
                expires_at=opens_at,
                configured=configured,
                facility_id=facility_id,
                skip_reason=None if offset == latest else "더 가까운 시점의 알림으로 대체",
            )
            created += event is not None and event.status == NotificationStatus.PENDING
    return created


# ---------------------------------------------------------------- 시스템 오류 알림


def enqueue_system_alerts(session: Session, now: datetime, configured: bool) -> int:
    created = 0
    threshold = get_setting(session, "failure_threshold")
    for site in session.scalars(select(Site).where(Site.enabled)).all():
        failures = collector.consecutive_failures(session, site.id)
        if failures < threshold:
            continue
        logs = session.scalars(
            select(CrawlLog)
            .where(CrawlLog.site_id == site.id, CrawlLog.job == collector.JOB_LIST, CrawlLog.success.is_(False))
            .order_by(CrawlLog.id.desc())
            .limit(failures)
        ).all()
        last_ok = collector.last_success_at(session, site.id)
        message = "\n".join(
            [
                "[Tennis Watch] 수집 오류",
                "",
                f"사이트: {site.name}",
                f"연속 실패: {failures}회",
                f"마지막 정상 수집: {_kst(last_ok, with_weekday=False) if last_ok else '없음'}",
                f"오류: {logs[0].error_type}: {(logs[0].error_message or '')[:300]}",
                "",
                "예약 상태를 확인할 수 없는 동안에는 알림이 오지 않습니다.",
            ]
        )
        # 실패가 시작된 지점을 키로 써서, 한 번의 장애에 한 번만 알린다.
        event = _add_event(
            session,
            now,
            type=NotificationType.SYSTEM_ERROR,
            dedupe_key=f"sysfail:{site.id}:{logs[-1].id}",
            message=message,
            expires_at=None,
            configured=configured,
        )
        created += event is not None

    paused = get_setting(session, "collection_paused_reason")
    if paused:
        event = _add_event(
            session,
            now,
            type=NotificationType.SYSTEM_ERROR,
            dedupe_key=f"paused:{paused}",
            message=(
                "[Tennis Watch] 수집 중지\n\n"
                f"사유: {paused}\n\n"
                "사이트가 접근을 차단해 수집을 멈췄습니다. 원인을 확인한 뒤 시스템 설정에서 다시 켜세요."
            ),
            expires_at=None,
            configured=configured,
        )
        created += event is not None
    return created


# ---------------------------------------------------------------- 발송


def send_pending(session: Session, client: TelegramClient, now: datetime) -> int:
    """보낼 차례가 된 알림을 보낸다. 보낸 건수를 돌려준다."""
    events = session.scalars(
        select(NotificationEvent)
        .where(NotificationEvent.status == NotificationStatus.PENDING)
        .order_by(NotificationEvent.id)
        .limit(SEND_BATCH * 5)
    ).all()
    sent = 0
    for event in events:
        if event.next_attempt_at is not None and event.next_attempt_at > now:
            continue
        if event.expires_at is not None and now > event.expires_at:
            event.status = NotificationStatus.SKIPPED
            event.last_error = "보낼 시점이 지남" + (f" (마지막 오류: {event.last_error})" if event.last_error else "")
            continue
        if sent >= SEND_BATCH:
            break
        event.attempts += 1
        try:
            client.send_message(event.message)
        except TelegramError as exc:
            event.last_error = str(exc)
            if exc.permanent or event.attempts >= MAX_ATTEMPTS:
                event.status = NotificationStatus.FAILED
                continue
            if exc.retry_after is not None:
                # 전송 제한에 걸리면 알려 준 시간만큼 기다리고, 이번 차례의 나머지도 보내지 않는다.
                event.next_attempt_at = now + timedelta(seconds=exc.retry_after)
                event.attempts -= 1  # 제한은 실패 횟수에 넣지 않는다
                break
            wait = min(RETRY_BASE_SECONDS * 2 ** (event.attempts - 1), RETRY_MAX_SECONDS)
            event.next_attempt_at = now + timedelta(seconds=wait)
            continue
        event.status = NotificationStatus.SENT
        event.sent_at = now
        event.last_error = None
        event.next_attempt_at = None
        sent += 1
    session.commit()
    return sent


def run_notifications(session: Session, client: TelegramClient, now: datetime) -> dict[str, int]:
    """알림을 만들고 보낸다. 스케줄러가 주기적으로 부른다."""
    configured = client.configured
    counts = {
        "changes": enqueue_changes(session, now, configured),
        "openings": enqueue_openings(session, now, configured),
        "system": enqueue_system_alerts(session, now, configured),
    }
    session.commit()
    counts["sent"] = send_pending(session, client, now) if configured else 0
    return counts
