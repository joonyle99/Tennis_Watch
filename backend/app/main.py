import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.scheduler.jobs import Collector, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 요청 주소에 인증키가 들어가므로 HTTP 클라이언트의 요청 로그는 남기지 않는다.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_db()
    app.state.collector = Collector(SessionLocal)
    app.state.scheduler = start_scheduler(app.state.collector) if get_settings().scheduler_enabled else None
    yield
    if app.state.scheduler is not None:
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="Tennis Watch", version="0.2.0", lifespan=lifespan)
app.include_router(router)
