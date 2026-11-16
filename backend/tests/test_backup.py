import sqlite3
from datetime import timedelta

from sqlalchemy.orm import Session

from app.db import init_db, make_engine
from app.models import Facility, Site
from app.services.backup import backup_database, database_path
from tests.helpers import T0


def test_backup_is_a_consistent_copy_taken_while_the_app_is_running(db_url, engine, session):
    site = session.query(Site).one()
    session.add(Facility(site_id=site.id, name="마루공원", external_name="마루공원", is_watched=True))
    session.commit()

    target = backup_database(db_url, T0)  # 엔진과 세션이 열려 있는 상태

    assert target.name == "tennis_watch-20261114-120000.db"  # 한국시간
    assert target.parent == database_path(db_url).parent / "backups"
    with sqlite3.connect(target) as copy:
        assert copy.execute("SELECT name, is_watched FROM facilities").fetchall() == [("마루공원", 1)]
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # 백업 폴더에는 백업 파일 하나만 남는다(임시 파일, -wal, -shm 없음).
    assert [p.name for p in target.parent.iterdir()] == [target.name]


def test_backup_can_be_restored_by_copying_it_back(db_url, engine, session, tmp_path):
    site = session.query(Site).one()
    session.add(Facility(site_id=site.id, name="마루공원", external_name="마루공원"))
    session.commit()
    target = backup_database(db_url, T0)

    restored_path = tmp_path / "restored.db"
    restored_path.write_bytes(target.read_bytes())
    restored = make_engine(f"sqlite:///{restored_path}")
    init_db(restored)
    with Session(restored) as s:
        assert [f.name for f in s.query(Facility).all()] == ["마루공원"]
        assert s.query(Site).count() == 1
    restored.dispose()


def test_old_backups_are_rotated(db_url, engine):
    made = [backup_database(db_url, T0 + timedelta(days=i), keep=3) for i in range(5)]

    remaining = sorted(p.name for p in made[0].parent.glob("*.db"))
    assert remaining == [p.name for p in made[2:]]


def test_non_file_databases_are_skipped(tmp_path):
    assert backup_database("sqlite:///:memory:") is None
    assert backup_database(f"sqlite:///{tmp_path / 'missing.db'}") is None
    assert database_path("postgresql://u:p@h/db") is None
