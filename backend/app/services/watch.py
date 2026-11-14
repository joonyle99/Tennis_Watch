"""개인 관심 조건과 공고의 일치 여부."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChangeKind, DayType, Facility, ReservationNotice, WatchRule

WEEKDAYS = {0, 1, 2, 3, 4}
WEEKEND = {5, 6}


def rule_matches_notice(rule: WatchRule, notice: ReservationNotice) -> bool:
    """공고가 관심 조건에 해당할 수 있는지.

    공고에서 알 수 없는 항목(요일 구분, 운영 시각 등)은 제외 사유로 쓰지 않는다.
    모르는 것을 이유로 알림을 빠뜨리지 않기 위해서다.
    """
    if not rule.enabled or rule.facility_id != notice.facility_id:
        return False
    if rule.court_id is not None and notice.court_id is not None and rule.court_id != notice.court_id:
        return False

    # 이용 날짜: 관심 기간과 공고의 이용 기간이 겹쳐야 한다.
    if rule.date_from and notice.use_end_date and notice.use_end_date < rule.date_from:
        return False
    if rule.date_to and notice.use_start_date and notice.use_start_date > rule.date_to:
        return False

    # 요일: 공고가 평일용인지 주말용인지 아는 경우에만 걸러낸다. 공휴일은 판단하지 않는다.
    if rule.weekdays:
        wanted = set(rule.weekdays)
        if notice.day_type == DayType.WEEKDAY and not wanted & WEEKDAYS:
            return False
        if notice.day_type == DayType.WEEKEND and not wanted & WEEKEND:
            return False

    # 시간대: 관심 시간대와 공고의 하루 운영 시각이 겹쳐야 한다.
    if rule.time_from and notice.daily_close_time and notice.daily_close_time <= rule.time_from:
        return False
    if rule.time_to and notice.daily_open_time and notice.daily_open_time >= rule.time_to:
        return False

    # 최소 연속 이용 시간: 공고의 1회 최대 이용 시간보다 길면 불가능하다.
    if (
        rule.min_consecutive_hours
        and notice.max_use_hours
        and rule.min_consecutive_hours > notice.max_use_hours
    ):
        return False
    return True


def _rule_wants(rule: WatchRule, kind: ChangeKind) -> bool:
    if kind == ChangeKind.REOPENED:
        return rule.notify_vacancy
    return rule.notify_opening


def should_notify(session: Session, notice: ReservationNotice, kind: ChangeKind) -> bool:
    """이 공고의 이 변경을 사용자에게 알려야 하는지.

    관심 시설이 아니면 알리지 않는다. 관심 시설인데 조건을 하나도 만들지 않았으면
    그 시설의 모든 공고를 알린다. 조건이 있으면 그중 하나에는 해당해야 한다.
    """
    if notice.facility_id is None:
        return False
    facility = session.get(Facility, notice.facility_id)
    if facility is None or not facility.is_watched:
        return False
    rules = session.scalars(
        select(WatchRule).where(WatchRule.facility_id == facility.id, WatchRule.enabled)
    ).all()
    if not rules:
        return True
    return any(rule_matches_notice(r, notice) and _rule_wants(r, kind) for r in rules)
