"""주기 수집. 업무 로직은 services에 있고, 여기서는 실행 시점과 중복 방지만 다룬다."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import SiteAdapter
from app.adapters.registry import build_adapter
from app.config import get_settings
from app.models import Site
from app.services import collector, notifier
from app.services.backup import backup_database
from app.services.telegram import TelegramClient
from app.services.collector import SyncResult
from app.services.settings import get_setting
from app.timeutil import utcnow

log = logging.getLogger(__name__)

AdapterFactory = Callable[[str], SiteAdapter]


class Collector:
    """수집 실행기. 스케줄러와 수동 실행(API)이 같은 인스턴스를 쓴다."""

    def __init__(self, session_factory: sessionmaker, adapter_factory: AdapterFactory | None = None):
        self.session_factory = session_factory
        self._adapter_factory = adapter_factory or (lambda code: build_adapter(code, get_settings()))
        self._adapters: dict[str, SiteAdapter] = {}
        # 수집이 겹쳐 돌지 않게 한다. 어댑터의 요청 간격 제한도 한 번에 한 실행만 가정한다.
        self._lock = threading.Lock()

    def _adapter(self, code: str) -> SiteAdapter:
        if code not in self._adapters:
            self._adapters[code] = self._adapter_factory(code)
        return self._adapters[code]

    def run(self, *, force: bool = False, hot_only: bool = False, now: datetime | None = None) -> list[SyncResult]:
        """한 번 수집한다.

        force: 사용자가 직접 실행한 경우. 백오프 대기를 건너뛴다(차단으로 멈춘 상태는 건너뛰지 않는다).
        hot_only: 접수 시작 전후 구간의 공고 상세만 확인한다.
        """
        if not self._lock.acquire(blocking=False):
            return [SyncResult(job="all", ok=False, skipped="이미 수집 중입니다")]
        try:
            with self.session_factory() as session:
                return self._run(session, force=force, hot_only=hot_only, now=now)
        finally:
            self._lock.release()

    def _run(self, session: Session, *, force: bool, hot_only: bool, now: datetime | None) -> list[SyncResult]:
        results: list[SyncResult] = []
        paused = get_setting(session, "collection_paused_reason")
        if paused:
            return [SyncResult(job="all", ok=False, skipped=f"수집 중지됨: {paused}")]

        for site in session.scalars(select(Site).where(Site.enabled)).all():
            current = now or utcnow()
            adapter = self._adapter(site.code)
            if hot_only:
                results.append(collector.run_detail_sync(session, adapter, site, current, hot_only=True))
                continue

            until = collector.backoff_until(session, site.id, get_setting(session, "sync_interval_minutes"))
            if not force and until is not None and current < until:
                results.append(
                    SyncResult(job=collector.JOB_LIST, ok=False, skipped=f"연속 실패로 {until:%H:%M} UTC까지 대기")
                )
                continue

            listing = collector.run_list_sync(session, adapter, site, current)
            results.append(listing)
            if listing.ok:
                # 목록 수집에 걸린 시간만큼 지났으므로 시각을 다시 읽는다.
                results.append(collector.run_detail_sync(session, adapter, site, now or utcnow()))
        return results


class Notifier:
    """알림 생성·발송 실행기."""

    def __init__(self, session_factory: sessionmaker, client: TelegramClient):
        self.session_factory = session_factory
        self.client = client
        self._lock = threading.Lock()

    def run(self, now: datetime | None = None) -> dict[str, int] | None:
        if not self._lock.acquire(blocking=False):
            return None
        try:
            with self.session_factory() as session:
                return notifier.run_notifications(session, self.client, now or utcnow())
        finally:
            self._lock.release()


def start_scheduler(runner: Collector, notify: Notifier | None = None) -> BackgroundScheduler:
    with runner.session_factory() as session:
        interval = get_setting(session, "sync_interval_minutes")

    scheduler = BackgroundScheduler(timezone="UTC")
    common = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 60}

    def send_notifications():
        if notify is None:
            return
        try:
            counts = notify.run()
            if counts and any(counts.values()):
                log.info("알림: %s", counts)
        except Exception:
            log.exception("알림 처리 중 예기치 않은 오류")

    def safe(**kwargs):
        def job():
            try:
                for result in runner.run(**kwargs):
                    log.info("수집 결과: %s", result)
                # 수집에서 발견한 변경을 다음 알림 주기까지 기다리지 않고 바로 보낸다.
                send_notifications()
            except Exception:
                # 한 번의 예외로 스케줄러가 멈추지 않게 한다.
                log.exception("수집 중 예기치 않은 오류")

        return job

    # 재시작 직후 한 번 수집해 그동안의 변화를 따라잡는다.
    scheduler.add_job(
        safe(), "interval", minutes=interval, id="sync", next_run_time=utcnow() + timedelta(seconds=5), **common
    )
    scheduler.add_job(safe(hot_only=True), "interval", minutes=1, id="hot", **common)
    def backup():
        try:
            backup_database(get_settings().database_url)
        except Exception:
            log.exception("백업 실패")

    # 매일 새벽 4시(한국시간)에 DB를 백업한다. 최근 14개를 남긴다.
    scheduler.add_job(backup, "cron", hour=19, minute=0, id="backup", **common)
    # 오픈 예정 알림의 시점을 맞추고, 실패한 발송을 다시 시도한다.
    scheduler.add_job(send_notifications, "interval", seconds=30, id="notify", **common)
    scheduler.start()
    return scheduler


def reschedule_sync(scheduler: BackgroundScheduler, interval_minutes: int) -> None:
    scheduler.reschedule_job("sync", trigger="interval", minutes=interval_minutes)
