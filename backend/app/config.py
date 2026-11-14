from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "sqlite:///./data/tennis_watch.db"

    seoul_openapi_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    http_timeout_seconds: float = 15.0
    # 같은 사이트에 연속 요청할 때 두는 최소 간격
    min_request_interval_seconds: float = 2.0
    user_agent: str = "TennisWatch/0.1 (personal reservation schedule monitor)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
