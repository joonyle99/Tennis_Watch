import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.scheduler.jobs import Collector, Notifier, start_scheduler
from app.services import auth
from app.services.telegram import TelegramClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 요청 주소에 인증키가 들어가므로 HTTP 클라이언트의 요청 로그는 남기지 않는다.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # 작업이 돌 때마다 찍히는 스케줄러 로그는 줄이고, 수집·알림 결과만 남긴다.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    init_db()
    settings = get_settings()
    app.state.collector = Collector(SessionLocal)
    app.state.telegram = TelegramClient(
        settings.telegram_bot_token, settings.telegram_chat_id, timeout=settings.http_timeout_seconds
    )
    app.state.scheduler = (
        start_scheduler(app.state.collector, Notifier(SessionLocal, app.state.telegram))
        if settings.scheduler_enabled
        else None
    )
    yield
    if app.state.scheduler is not None:
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="Tennis Watch", version="0.4.0", lifespan=lifespan)

# 로그인 없이 열려 있는 경로. 그 밖의 /api는 DASHBOARD_PASSWORD가 있으면 세션이 필요하다.
OPEN_PATHS = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"}


@app.middleware("http")
async def require_session(request: Request, call_next):
    password = get_settings().dashboard_password
    path = request.url.path
    if password and path.startswith("/api") and path not in OPEN_PATHS:
        if not auth.token_valid(password, request.cookies.get(auth.COOKIE_NAME)):
            return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
    return await call_next(request)


app.include_router(router)
