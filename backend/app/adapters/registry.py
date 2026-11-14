from app.adapters.base import SiteAdapter
from app.adapters.seoul import SeoulAdapter
from app.config import Settings


def build_adapter(site_code: str, settings: Settings) -> SiteAdapter:
    """사이트 코드에 맞는 어댑터를 만든다. 2차 사이트는 여기에 추가한다."""
    if site_code == "seoul":
        return SeoulAdapter(
            api_key=settings.seoul_openapi_key,
            timeout=settings.http_timeout_seconds,
            min_interval=settings.min_request_interval_seconds,
            user_agent=settings.user_agent,
        )
    raise ValueError(f"지원하지 않는 사이트입니다: {site_code}")
