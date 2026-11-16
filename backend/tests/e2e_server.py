"""화면 E2E 테스트용 서버.

임시 DB에 예시 데이터를 넣고, 실제 사이트와 Telegram 대신 가짜를 붙여 백엔드를 띄운다.
frontend/playwright.config.ts가 실행한다.  (backend 폴더에서: python -m tests.e2e_server)
"""

import os
import tempfile

PORT = int(os.environ.get("E2E_BACKEND_PORT", "8100"))
PASSWORD = os.environ.get("E2E_PASSWORD", "e2e-password")

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp(prefix='tennis-watch-e2e-')}/e2e.db"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DASHBOARD_PASSWORD"] = PASSWORD
os.environ["SEOUL_OPENAPI_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""

from datetime import UTC, date, datetime, time, timedelta  # noqa: E402

import uvicorn  # noqa: E402

from app.api.routes import get_collector, get_telegram  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Facility, RuleType, Site, VerificationStatus, WatchRule  # noqa: E402
from app.scheduler.jobs import Collector  # noqa: E402
from app.services import collector, opening_rules  # noqa: E402
from tests.helpers import FakeAdapter, detail, notice  # noqa: E402

MARU_COURTS = ["1면", "2면", "3면", "1면 (조명)", "2면 (조명)", "3면 (조명)"]


class StubTelegram:
    token = "stub"
    chat_id = "stub"
    configured = True

    def bot_name(self):
        return "e2e_test_bot"

    def send_message(self, text):
        pass

    def recent_chats(self):
        return []


def build_listing(now: datetime, weekend_status: str):
    def dongbu(i, label, status, use_start, use_end, opens):
        return notice(
            f"D{i}", status, title=f"동부 도로사업소 테니스장 A코트 {label}", reception_start_at=opens,
            use_start_date=use_start, use_end_date=use_end, daily_open_time=time(6), daily_close_time=time(22),
        )  # fmt: skip

    today = (now + timedelta(hours=9)).date()
    period_end = today + timedelta(days=14)
    opened = now - timedelta(days=4)
    listing = [
        dongbu(1, "평일주간 이번 회차", "접수중", today, period_end, opened),
        dongbu(2, "평일야간 이번 회차", "예약마감", today, period_end, opened),
        dongbu(3, "주말 및 공휴일 이번 회차", weekend_status, today, period_end, opened),
        dongbu(4, "주말 및 공휴일 다음 회차", "안내중", period_end + timedelta(days=1), period_end + timedelta(days=15), now + timedelta(days=3)),
        notice("H1", title="홍은테니스장 평일 주간", place="홍은테니스장", area="서대문구"),
        notice("J1", title="잠원 한강공원 테니스장 2번 코트 평일", place="잠원한강테니스장", area="서초구"),
    ]  # fmt: skip
    listing += [
        notice(
            f"M{i}", title=f"마루공원 테니스장 {name}", place="마루공원", reception_start_at=now - timedelta(days=30),
            use_start_date=date(2025, 6, 1), use_end_date=today + timedelta(days=90),
            daily_open_time=time(6), daily_close_time=time(21),
        )  # fmt: skip
        for i, name in enumerate(MARU_COURTS)
    ]
    return listing


def set_site_state(adapter: FakeAdapter, now: datetime, weekend_status: str) -> None:
    """가짜 사이트의 목록과 상세 페이지를 같은 내용으로 맞춘다."""
    adapter.listing = build_listing(now, weekend_status)
    for item in adapter.listing:
        if item.external_id.startswith("M"):
            adapter.details[item.external_id] = detail(item.external_id, title=item.title)
        else:
            adapter.details[item.external_id] = detail(
                item.external_id, item.raw_status, title=item.title, place_name=item.place_name,
                reception_start_at=item.reception_start_at, use_start_date=item.use_start_date,
                use_end_date=item.use_end_date, open_days_before=None, open_hour=None,
                close_days_before=None, close_hour=None,
            )  # fmt: skip


def seed() -> FakeAdapter:
    init_db()
    now = datetime.now(UTC).replace(microsecond=0)
    adapter = FakeAdapter()

    with SessionLocal() as session:
        site = session.query(Site).one()
        set_site_state(adapter, now, "예약마감")
        collector.run_list_sync(session, adapter, site, now - timedelta(minutes=30))
        collector.run_detail_sync(session, adapter, site, now - timedelta(minutes=30))
        # 접수 재개 한 건을 만든다.
        set_site_state(adapter, now, "접수중")
        collector.run_list_sync(session, adapter, site, now - timedelta(minutes=10))

        dongbu = session.query(Facility).filter_by(name="동부도로사업소 테니스장").one()
        # 언제 실행해도 14일 안에 한 번 오도록, 5일 뒤 날짜를 "매월 N일" 규칙으로 등록한다.
        soon = (now + timedelta(hours=9, days=5)).date()
        opening_rules.create_manual_rule(
            session, now, facility_id=dongbu.id, rule_type=RuleType.MONTHLY, day_of_month=soon.day, open_time=time(0),
            target_description="추정 규칙 예시", verification_status=VerificationStatus.INFERRED,
        )  # fmt: skip
        maru = session.query(Facility).filter_by(name="마루공원").one()
        session.add(WatchRule(facility_id=maru.id, name="기존 조건", weekdays=[5]))
        session.commit()
    return adapter


if __name__ == "__main__":
    fake = seed()
    runner = Collector(SessionLocal, lambda code: fake)
    app.dependency_overrides[get_collector] = lambda: runner
    app.dependency_overrides[get_telegram] = lambda: StubTelegram()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
