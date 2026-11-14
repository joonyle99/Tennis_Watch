from datetime import UTC, datetime

from app.models import DataSource, Facility, ReservationNotice, Site, SlotStatus


def test_health_reports_utc_and_kst(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["time_utc"].endswith("+00:00")
    assert body["time_kst"].endswith("+09:00")


def test_sites_lists_seoul(client):
    assert [s["code"] for s in client.get("/api/sites").json()] == ["seoul"]


def test_manual_facility_lifecycle(client):
    created = client.post("/api/facilities", json={"name": "우리동네 테니스장", "area": "강남구"})
    assert created.status_code == 201
    facility = created.json()
    assert facility["source"] == "MANUAL" and facility["is_watched"] is True

    court = client.post(f"/api/facilities/{facility['id']}/courts", json={"name": "1번코트"})
    assert court.status_code == 201
    assert court.json()["source"] == "MANUAL" and court.json()["verified"] is True

    duplicate = client.post(f"/api/facilities/{facility['id']}/courts", json={"name": "1번코트"})
    assert duplicate.status_code == 409

    patched = client.patch(f"/api/courts/{court.json()['id']}", json={"is_watched": True})
    assert patched.json()["is_watched"] is True

    fetched = client.get(f"/api/facilities/{facility['id']}").json()
    assert [c["name"] for c in fetched["courts"]] == ["1번코트"]

    assert client.delete(f"/api/facilities/{facility['id']}").status_code == 204
    assert client.get(f"/api/facilities/{facility['id']}").status_code == 404


def test_facility_validation_and_unknown_site(client):
    assert client.post("/api/facilities", json={"name": ""}).status_code == 422
    assert client.post("/api/facilities", json={"name": "x", "site_code": "nope"}).status_code == 400
    assert client.get("/api/facilities/999").status_code == 404


def test_facility_filters(client):
    client.post("/api/facilities", json={"name": "마루공원", "area": "강남구"})
    client.post("/api/facilities", json={"name": "홍은테니스장", "area": "서대문구", "is_watched": False})

    names = lambda **params: [f["name"] for f in client.get("/api/facilities", params=params).json()]
    assert names() == ["마루공원", "홍은테니스장"]
    assert names(area="강남구") == ["마루공원"]
    assert names(watched=False) == ["홍은테니스장"]
    assert names(q="홍은") == ["홍은테니스장"]


def test_editing_an_auto_facility_locks_the_edited_fields(client, session):
    """사용자가 고친 값은 이후 자동 수집이 덮어쓰지 않도록 필드 단위로 잠근다."""
    site = session.query(Site).one()
    facility = Facility(site_id=site.id, name="마루공원", external_name="마루공원", area="강남구")
    session.add(facility)
    session.commit()

    body = client.patch(
        f"/api/facilities/{facility.id}", json={"phone": "02-000-0000", "is_watched": True}
    ).json()

    assert body["phone"] == "02-000-0000" and body["is_watched"] is True
    assert body["source"] == "AUTO"
    assert body["locked_fields"] == ["phone"]  # 관심 여부는 수집 대상이 아니므로 잠그지 않는다


def test_auto_facility_cannot_be_deleted(client, session):
    site = session.query(Site).one()
    facility = Facility(site_id=site.id, name="마루공원", external_name="마루공원", source=DataSource.AUTO)
    session.add(facility)
    session.commit()
    assert client.delete(f"/api/facilities/{facility.id}").status_code == 409


def test_notice_list_filters_and_utc_output(client, session):
    site = session.query(Site).one()
    watched = Facility(site_id=site.id, name="동부도로사업소 테니스장", external_name="동부", is_watched=True)
    other = Facility(site_id=site.id, name="응봉공원", external_name="응봉")
    session.add_all([watched, other])
    session.flush()
    session.add_all(
        [
            ReservationNotice(
                site_id=site.id,
                facility_id=watched.id,
                external_id="S1",
                title="A코트 주말 11월16일~30일",
                status=SlotStatus.AVAILABLE,
                raw_status="접수중",
                reception_start_at=datetime(2026, 11, 9, 15, 0, tzinfo=UTC),
            ),
            ReservationNotice(
                site_id=site.id,
                facility_id=watched.id,
                external_id="S2",
                title="A코트 평일주간 11월1일~15일",
                status=SlotStatus.UNAVAILABLE,
                raw_status="예약마감",
                is_active=False,
            ),
            ReservationNotice(site_id=site.id, facility_id=other.id, external_id="S3", title="응봉"),
        ]
    )
    session.commit()

    ids = lambda **params: {n["external_id"] for n in client.get("/api/notices", params=params).json()}
    assert ids() == {"S1", "S3"}  # 기본은 현재 목록에 있는 공고만
    assert ids(watched=True) == {"S1"}
    assert ids(facility_id=watched.id, include_inactive=True) == {"S1", "S2"}
    assert ids(status="AVAILABLE") == {"S1"}

    notice = client.get("/api/notices", params={"status": "AVAILABLE"}).json()[0]
    assert notice["reception_start_at"] == "2026-11-09T15:00:00Z"
