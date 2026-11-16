"""SQLite 백업.

서버가 돌고 있는 중에도 안전하게 복사되도록 SQLite의 온라인 백업 기능을 쓴다.
파일을 그냥 복사하면 쓰는 도중의 상태가 찍혀 깨진 백업이 될 수 있다.
"""

import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.timeutil import to_kst, utcnow

log = logging.getLogger(__name__)

PREFIX = "tennis_watch-"
KEEP = 14


def database_path(database_url: str) -> Path | None:
    """SQLite 파일 경로. 파일 DB가 아니면 None."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def backup_database(database_url: str, now: datetime | None = None, keep: int = KEEP) -> Path | None:
    """DB를 backups 폴더에 복사하고 오래된 백업을 지운다. 만든 파일 경로를 돌려준다."""
    source = database_path(database_url)
    if source is None or not source.exists():
        return None
    folder = source.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = to_kst(now or utcnow()).strftime("%Y%m%d-%H%M%S")
    target = folder / f"{PREFIX}{stamp}.db"
    partial = target.with_suffix(".partial")

    # sqlite3의 with 문은 연결을 닫지 않으므로 closing으로 확실히 닫는다.
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(partial)) as dst:
        src.backup(dst)
        # 원본의 WAL 모드가 복사본에 따라오면 -wal, -shm 파일이 옆에 생긴다. 백업은 파일 하나로 둔다.
        dst.execute("PRAGMA journal_mode=DELETE")
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"백업 파일 검사 실패: {ok}")
    # 검사를 통과한 뒤에만 정식 이름을 붙인다. 중간에 끊긴 백업이 정상처럼 보이지 않게 한다.
    partial.replace(target)

    backups = sorted(folder.glob(f"{PREFIX}*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink()
    log.info("백업 완료: %s", target)
    return target


if __name__ == "__main__":
    from app.config import get_settings

    result = backup_database(get_settings().database_url)
    print(result if result else "백업할 SQLite 파일이 없습니다")
