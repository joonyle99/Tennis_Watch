"""예약 오픈 규칙: 오픈 시각 계산, 수동 규칙 관리, 자동 수집값과의 대조."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DataSource,
    OpeningRule,
    ReservationNotice,
    RuleType,
    VerificationStatus,
    WatchRule,
)
from app.timeutil import kst_datetime, kst_today, to_kst


@dataclass(frozen=True)
class Opening:
    """예약이 열리는 한 시점."""

    rule_id: int
    facility_id: int
    court_id: int | None
    notice_id: int | None
    rule_type: RuleType
    source: DataSource
    verification_status: VerificationStatus
    opens_at: datetime
    # 이 오픈으로 예약할 수 있게 되는 이용일 범위(알 수 있는 경우)
    use_start: date | None
    use_end: date | None
    description: str | None


def rolling_open_at(use_date: date, days_before: int, open_time: time) -> datetime:
    """이용일 N일 전 규칙에서 use_date의 예약이 열리는 시각(UTC)."""
    return kst_datetime(use_date - timedelta(days=days_before), open_time)


def monthly_occurrences(day_of_month: int, open_time: time, start: datetime, end: datetime):
    """start 이후 end 이전에 오는 '매월 N일 HH:MM'(한국시간)을 차례로 낸다.

    그 달에 N일이 없으면(예: 2월 30일) 건너뛴다. 사이트가 그런 달에 어떻게 여는지
    확인된 바 없으므로 추측하지 않는다.
    """
    cursor = to_kst(start).date().replace(day=1)
    last = to_kst(end).date()
    while cursor <= last:
        if day_of_month <= calendar.monthrange(cursor.year, cursor.month)[1]:
            at = kst_datetime(cursor.replace(day=day_of_month), open_time)
            if start <= at <= end:
                yield at
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)


def _wanted_use_dates(rules: list[WatchRule], start: date, end: date) -> set[date] | None:
    """관심 조건이 가리키는 이용일. 조건이 없으면 None(모든 날짜)."""
    if not rules:
        return None
    wanted: set[date] = set()
    day = start
    while day <= end:
        for rule in rules:
            if rule.date_from and day < rule.date_from:
                continue
            if rule.date_to and day > rule.date_to:
                continue
            if rule.weekdays and day.weekday() not in rule.weekdays:
                continue
            wanted.add(day)
            break
        day += timedelta(days=1)
    return wanted


def upcoming_openings(
    session: Session, now: datetime, horizon_days: int = 30, facility_id: int | None = None
) -> list[Opening]:
    """now부터 horizon_days일 안에 오는 예약 오픈을 시각 순으로 돌려준다."""
    end = now + timedelta(days=horizon_days)
    stmt = select(OpeningRule).where(OpeningRule.is_active)
    if facility_id is not None:
        stmt = stmt.where(OpeningRule.facility_id == facility_id)

    openings: list[Opening] = []
    for rule in session.scalars(stmt).all():

        def make(opens_at, use_start=None, use_end=None, description=None, rule=rule):
            return Opening(
                rule_id=rule.id,
                facility_id=rule.facility_id,
                court_id=rule.court_id,
                notice_id=rule.notice_id,
                rule_type=RuleType(rule.rule_type),
                source=DataSource(rule.source),
                verification_status=VerificationStatus(rule.verification_status),
                opens_at=opens_at,
                use_start=use_start,
                use_end=use_end,
                description=description or rule.target_description,
            )

        if rule.rule_type in (RuleType.ONE_TIME, RuleType.NOTICE):
            if rule.opens_at and now <= rule.opens_at <= end:
                openings.append(make(rule.opens_at, rule.target_use_start, rule.target_use_end))

        elif rule.rule_type == RuleType.MONTHLY:
            if rule.day_of_month and rule.open_time:
                for at in monthly_occurrences(rule.day_of_month, rule.open_time, now, end):
                    openings.append(make(at))

        elif rule.rule_type == RuleType.DAYS_BEFORE_USE:
            if rule.days_before is None or rule.open_time is None:
                continue
            watch_stmt = select(WatchRule).where(
                WatchRule.facility_id == rule.facility_id,
                WatchRule.enabled,
                WatchRule.notify_opening,
            )
            watch_rules = [
                w
                for w in session.scalars(watch_stmt).all()
                if w.court_id is None or rule.court_id is None or w.court_id == rule.court_id
            ]
            today = kst_today(now)
            first_use = today + timedelta(days=rule.days_before)
            last_use = kst_today(end) + timedelta(days=rule.days_before)
            wanted = _wanted_use_dates(watch_rules, first_use, last_use)
            use_date = first_use
            while use_date <= last_use:
                at = rolling_open_at(use_date, rule.days_before, rule.open_time)
                if now <= at <= end and (wanted is None or use_date in wanted):
                    openings.append(make(at, use_date, use_date))
                use_date += timedelta(days=1)

    openings.sort(key=lambda o: (o.opens_at, o.facility_id, o.rule_id))
    return openings


# ---------------------------------------------------------------- 수동 규칙


def _validate(rule: OpeningRule) -> None:
    kind = rule.rule_type
    if kind == RuleType.MONTHLY:
        ok = rule.day_of_month is not None and 1 <= rule.day_of_month <= 31 and rule.open_time
    elif kind == RuleType.DAYS_BEFORE_USE:
        ok = rule.days_before is not None and 0 <= rule.days_before <= 365 and rule.open_time
    else:
        ok = rule.opens_at is not None
    if not ok:
        raise ValueError(f"{kind} 규칙에 필요한 값이 빠졌거나 범위를 벗어났습니다")


RULE_VALUE_FIELDS = (
    "court_id", "rule_type", "day_of_month", "days_before", "open_time", "opens_at",
    "target_use_start", "target_use_end", "target_description", "source_url", "note",
)  # fmt: skip


def create_manual_rule(session: Session, now: datetime, **values) -> OpeningRule:
    rule = OpeningRule(source=DataSource.MANUAL, valid_from=now, **values)
    _validate(rule)
    session.add(rule)
    session.flush()
    refresh_conflicts(session, rule.facility_id, now)
    return rule


def replace_manual_rule(session: Session, rule: OpeningRule, now: datetime, **changes) -> OpeningRule:
    """규칙을 고친다. 기존 행은 닫아 두고 새 행을 만들어 변경 이력을 남긴다."""
    if rule.source != DataSource.MANUAL:
        raise ValueError("자동 수집된 규칙은 고칠 수 없습니다. 수동 규칙을 따로 등록하세요.")
    if not rule.is_active:
        raise ValueError("이미 닫힌 규칙입니다")
    values = {field: getattr(rule, field) for field in RULE_VALUE_FIELDS}
    values.update(changes)
    new_rule = OpeningRule(
        facility_id=rule.facility_id,
        source=DataSource.MANUAL,
        valid_from=now,
        replaces_id=rule.id,
        **values,
    )
    _validate(new_rule)
    rule.is_active = False
    rule.valid_to = now
    session.add(new_rule)
    session.flush()
    refresh_conflicts(session, rule.facility_id, now)
    return new_rule


def close_rule(session: Session, rule: OpeningRule, now: datetime) -> None:
    rule.is_active = False
    rule.valid_to = now
    session.flush()
    refresh_conflicts(session, rule.facility_id, now)


# ---------------------------------------------------------------- 자동 규칙과 대조


def _active_rules(session: Session, facility_id: int, rule_type: RuleType, source: DataSource):
    return session.scalars(
        select(OpeningRule).where(
            OpeningRule.facility_id == facility_id,
            OpeningRule.rule_type == rule_type,
            OpeningRule.source == source,
            OpeningRule.is_active,
        )
    ).all()


def refresh_conflicts(session: Session, facility_id: int, now: datetime) -> None:
    """수동 '이용일 N일 전' 규칙을 사이트에서 수집한 규칙과 비교한다.

    다르면 양쪽 행을 그대로 두고 수동 규칙을 CONFLICT로 표시한다. 같으면 VERIFIED.
    비교할 자동 규칙이 없으면 건드리지 않는다.
    """
    autos = _active_rules(session, facility_id, RuleType.DAYS_BEFORE_USE, DataSource.AUTO)
    for manual in _active_rules(session, facility_id, RuleType.DAYS_BEFORE_USE, DataSource.MANUAL):
        comparable = [
            a for a in autos if manual.court_id is None or a.court_id in (None, manual.court_id)
        ]
        if not comparable:
            if manual.verification_status == VerificationStatus.CONFLICT:
                manual.verification_status = VerificationStatus.UNVERIFIED
            continue
        same = all(
            (a.days_before, a.open_time) == (manual.days_before, manual.open_time) for a in comparable
        )
        manual.verification_status = (
            VerificationStatus.VERIFIED if same else VerificationStatus.CONFLICT
        )
        manual.last_verified_at = now


def verify_monthly_rules(session: Session, notice: ReservationNotice, now: datetime) -> None:
    """새 공고의 실제 접수 시작 일시로 수동 '매월 N일' 규칙을 검증한다.

    일치하는 규칙은 VERIFIED. 일치하는 규칙이 없으면 날짜가 가장 가까운 규칙을 CONFLICT로
    표시한다. 규칙 값은 바꾸지 않는다.
    """
    if notice.facility_id is None or notice.reception_start_at is None:
        return
    rules = [
        r
        for r in _active_rules(session, notice.facility_id, RuleType.MONTHLY, DataSource.MANUAL)
        if r.court_id is None or notice.court_id is None or r.court_id == notice.court_id
    ]
    if not rules:
        return
    opened = to_kst(notice.reception_start_at)
    actual = (opened.day, opened.time().replace(second=0, microsecond=0))
    matched = [r for r in rules if (r.day_of_month, r.open_time) == actual]
    if matched:
        for rule in matched:
            rule.verification_status = VerificationStatus.VERIFIED
            rule.last_verified_at = now
        return

    def distance(rule: OpeningRule) -> int:
        diff = abs(rule.day_of_month - opened.day)
        return min(diff, 31 - diff)

    nearest = min(rules, key=distance)
    nearest.verification_status = VerificationStatus.CONFLICT
    nearest.last_verified_at = now
    nearest.note = (
        f"{nearest.note + ' / ' if nearest.note else ''}"
        f"실제 접수 시작 {opened:%Y-%m-%d %H:%M} (공고 {notice.external_id})와 다름"
    )
