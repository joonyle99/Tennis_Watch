import pytest

from app.api import routes
from app.config import get_settings
from app.services import auth

PASSWORD = "correct horse"


@pytest.fixture
def protected(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "dashboard_password", PASSWORD)
    monkeypatch.setattr(routes, "login_throttle", auth.LoginThrottle())
    return client


def test_without_a_password_everything_is_open(client):
    assert client.get("/api/auth/status").json() == {"required": False, "authenticated": True}
    assert client.get("/api/facilities").status_code == 200


def test_api_requires_login_when_a_password_is_set(protected):
    assert protected.get("/api/auth/status").json() == {"required": True, "authenticated": False}
    for method, path in [("get", "/api/facilities"), ("get", "/api/settings"), ("post", "/api/sync"),
                         ("post", "/api/telegram/test"), ("put", "/api/settings")]:  # fmt: skip
        assert getattr(protected, method)(path).status_code == 401, path
    assert protected.get("/api/health").status_code == 200  # 상태 확인은 열려 있다


def test_login_sets_a_session_cookie_and_logout_clears_it(protected):
    assert protected.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert protected.get("/api/facilities").status_code == 401

    response = protected.post("/api/auth/login", json={"password": PASSWORD})
    assert response.json() == {"required": True, "authenticated": True}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and PASSWORD not in cookie

    assert protected.get("/api/facilities").status_code == 200
    assert protected.get("/api/auth/status").json()["authenticated"] is True

    protected.post("/api/auth/logout")
    assert protected.get("/api/facilities").status_code == 401


def test_forged_and_expired_sessions_are_rejected(protected):
    protected.cookies.set(auth.COOKIE_NAME, "9999999999.deadbeef")
    assert protected.get("/api/facilities").status_code == 401

    protected.cookies.set(auth.COOKIE_NAME, auth.make_token("other password"))
    assert protected.get("/api/facilities").status_code == 401

    expired = auth.make_token(PASSWORD, now=0)
    protected.cookies.set(auth.COOKIE_NAME, expired)
    assert protected.get("/api/facilities").status_code == 401

    protected.cookies.set(auth.COOKIE_NAME, auth.make_token(PASSWORD))
    assert protected.get("/api/facilities").status_code == 200


def test_repeated_wrong_passwords_lock_login_for_a_while(protected):
    for _ in range(auth.MAX_FAILURES):
        assert protected.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    locked = protected.post("/api/auth/login", json={"password": PASSWORD})
    assert locked.status_code == 429 and "초 후" in locked.json()["detail"]


def test_throttle_unlocks_after_the_lock_period():
    throttle = auth.LoginThrottle()
    for _ in range(auth.MAX_FAILURES):
        throttle.record(False, now=1000)
    assert throttle.locked_for(now=1000) == auth.LOCK_SECONDS
    assert throttle.locked_for(now=1000 + auth.LOCK_SECONDS) == 0
    throttle.record(False, now=2000)
    throttle.record(True, now=2000)
    assert throttle.failures == 0


def test_openings_can_start_from_a_past_date_for_the_calendar(client, session):
    from datetime import time

    from app.models import DataSource, Facility, OpeningRule, RuleType, Site

    site = session.query(Site).one()
    facility = Facility(site_id=site.id, name="동부", external_name="동부", is_watched=True)
    session.add(facility)
    session.flush()
    session.add(OpeningRule(
        facility_id=facility.id, rule_type=RuleType.MONTHLY, source=DataSource.MANUAL,
        day_of_month=10, open_time=time(0, 0),
    ))  # fmt: skip
    session.commit()

    openings = client.get("/api/openings", params={"start": "2020-03-01", "days": 31}).json()
    assert [o["opens_at"] for o in openings] == ["2020-03-09T15:00:00Z"]  # 3월 10일 00:00 KST
