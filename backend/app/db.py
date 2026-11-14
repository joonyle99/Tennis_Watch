from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class UTCDateTime(TypeDecorator):
    """UTC로만 저장하고 항상 시간대가 붙은 값으로 돌려준다.

    SQLite는 시간대를 보존하지 않으므로, 시간대 없는 값이 섞여 들어오는 것을 여기서 막는다.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("시간대 없는 datetime은 저장할 수 없습니다")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    connect_args = {}
    if parsed.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args)

    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def init_db(bind: Engine | None = None) -> None:
    """테이블을 만들고 기본 사이트 행을 넣는다. 여러 번 실행해도 안전하다."""
    from app import models

    bind = bind or engine
    Base.metadata.create_all(bind)
    with Session(bind) as session:
        if session.query(models.Site).filter_by(code="seoul").first() is None:
            session.add(
                models.Site(
                    code="seoul",
                    name="서울시 공공서비스예약",
                    base_url="https://yeyak.seoul.go.kr",
                )
            )
            session.commit()
