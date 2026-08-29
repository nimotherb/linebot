import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_database_file = tempfile.NamedTemporaryFile(prefix="equalspa-test-", suffix=".sqlite3", delete=False)
_database_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_database_file.name).as_posix()}"
os.environ["ADMIN_INITIAL_PIN"] = "123456"
os.environ["MANAGER_INITIAL_PIN"] = "654321"
os.environ["CUSTOMER_SERIAL_START"] = "4800"

from main import Base, SessionLocal, Staff, app, build_staff_week_appointments, engine, now_taipei_naive  # noqa: E402
from identifiers import customer_serial  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    Path(_database_file.name).unlink(missing_ok=True)


def login(client, username="admin", pin="123456"):
    response = client.post("/api/admin/auth/login", json={"username": username, "pin": pin})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_is_required_and_bootstrap_seeds_two_rooms(client):
    assert client.get("/api/admin/bootstrap").status_code == 401
    headers = login(client)
    response = client.get("/api/admin/bootstrap", headers=headers)
    assert response.status_code == 200
    assert [room["name"] for room in response.json()["rooms"]] == ["房間 1", "房間 2"]
    staff_rows = response.json()["staff"]
    assert len(staff_rows) == 47
    assert all(item["photo_url"].startswith("https://") for item in staff_rows)
    assert customer_serial(1) == "VIP-4800"


def test_staff_photo_upload_and_safe_permanent_delete(client):
    admin_headers = login(client)
    manager_headers = login(client, "jerry", "654321")
    created = client.post(
        "/api/admin/staff",
        headers=admin_headers,
        json={"name": "待刪除師傅", "category": "gay", "photo_url": "https://example.com/portrait.jpg"},
    )
    assert created.status_code == 201, created.text
    staff_id = created.json()["id"]

    png_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZfN0AAAAASUVORK5CYII="
    uploaded = client.put(
        f"/api/admin/staff/{staff_id}/photo",
        headers=admin_headers,
        json={"data_url": f"data:image/png;base64,{png_data}"},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["photo_url"] == f"/api/public/staff/{staff_id}/photo"
    public_photo = client.get(uploaded.json()["photo_url"])
    assert public_photo.status_code == 200
    assert public_photo.headers["content-type"] == "image/png"

    assert client.delete(f"/api/admin/staff/{staff_id}", headers=manager_headers).status_code == 403
    deleted = client.delete(f"/api/admin/staff/{staff_id}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    assert client.get(uploaded.json()["photo_url"]).status_code == 404

    used = client.post(
        "/api/admin/staff",
        headers=admin_headers,
        json={"name": "保留歷史師傅", "category": "straight"},
    )
    assert used.status_code == 201, used.text
    shift = client.post(
        "/api/admin/shifts",
        headers=admin_headers,
        json={
            "staff_id": used.json()["id"],
            "start_time": "2099-01-01T16:00:00",
            "end_time": "2099-01-01T18:00:00",
            "source": "admin",
        },
    )
    assert shift.status_code == 201, shift.text
    blocked = client.delete(f"/api/admin/staff/{used.json()['id']}", headers=admin_headers)
    assert blocked.status_code == 409
    assert "只能設為暫時退役" in blocked.json()["detail"]


def test_appointment_end_and_staff_room_conflicts(client):
    headers = login(client)
    bootstrap = client.get("/api/admin/bootstrap", headers=headers).json()
    ninety_minute_plan = next(item for item in bootstrap["services"] if item["duration_minutes"] == 90)
    room = bootstrap["rooms"][0]
    start_at = (now_taipei_naive() + timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
    overlap_at = start_at + timedelta(hours=1)

    staff_response = client.post(
        "/api/admin/staff",
        headers=headers,
        json={"name": "測試師傅", "category": "gay"},
    )
    assert staff_response.status_code == 201, staff_response.text
    staff = staff_response.json()

    payload = {
        "customer_name": "測試客戶",
        "phone": "0912345678",
        "service_plan_id": ninety_minute_plan["id"],
        "start_time": start_at.isoformat(timespec="seconds"),
        "staff_id": staff["id"],
        "room_id": room["id"],
        "location_type": "onsite",
    }
    first = client.post("/api/admin/appointments", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["end_time"] == (start_at + timedelta(minutes=90)).isoformat(timespec="minutes")
    assert first.json()["customer_serial"] == "VIP-4800"

    with SessionLocal() as db:
        staff_obj = db.query(Staff).filter(Staff.id == staff["id"]).first()
        weekly = build_staff_week_appointments(staff_obj, db)
        assert weekly.alt_text == f"{staff_obj.name}未來一週預約"

    staff_conflict = client.post(
        "/api/admin/appointments",
        headers=headers,
        json={**payload, "phone": "0922222222", "start_time": overlap_at.isoformat(timespec="seconds"), "room_id": bootstrap["rooms"][1]["id"]},
    )
    assert staff_conflict.status_code == 409
    assert "師傅" in staff_conflict.json()["detail"]

    room_conflict = client.post(
        "/api/admin/appointments",
        headers=headers,
        json={**payload, "phone": "0933333333", "start_time": overlap_at.isoformat(timespec="seconds"), "staff_id": None},
    )
    assert room_conflict.status_code == 409
    assert "房間" in room_conflict.json()["detail"]


def test_only_admin_can_create_accounts(client):
    manager_headers = login(client, "jerry", "654321")
    denied_manager = client.post(
        "/api/admin/users",
        headers=manager_headers,
        json={"username": "another-manager", "display_name": "副店長", "pin": "112233", "role": "manager"},
    )
    assert denied_manager.status_code == 403

    denied_clerk = client.post(
        "/api/admin/users",
        headers=manager_headers,
        json={"username": "frontdesk", "display_name": "櫃台", "pin": "112233", "role": "clerk"},
    )
    assert denied_clerk.status_code == 403

    admin_headers = login(client)
    allowed = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": "frontdesk", "display_name": "櫃台", "pin": "112233", "role": "clerk"},
    )
    assert allowed.status_code == 201
    clerk_id = allowed.json()["id"]
    removed = client.delete(f"/api/admin/users/{clerk_id}", headers=manager_headers)
    assert removed.status_code == 200
    assert removed.json()["is_active"] is False

    admin_user = next(item for item in client.get("/api/admin/users", headers=manager_headers).json() if item["username"] == "admin")
    assert client.delete(f"/api/admin/users/{admin_user['id']}", headers=manager_headers).status_code == 403


def test_public_bootstrap_is_read_only_and_redacts_sensitive_fields(client):
    response = client.get("/api/public/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "public"
    assert payload["customers"] == []
    assert payload["admin_users"] == []
    if payload["appointments"]:
        appointment = payload["appointments"][0]
        assert appointment["customer_name"] == "已隱藏"
        assert appointment["phone"] is None
        assert appointment["total_amount"] == 0
        assert appointment["notes"] is None


def test_staff_passwordless_session_only_returns_own_data(client):
    headers = login(client)
    created = client.post(
        "/api/admin/staff",
        headers=headers,
        json={"name": "登入測試師傅", "category": "gay", "phone": "0987654321"},
    )
    assert created.status_code == 201, created.text
    staff = created.json()
    assert client.post("/api/staff/auth/login", json={"staff_id": staff["id"]}).status_code == 422
    assert client.post("/api/staff/auth/login", json={"staff_id": staff["id"], "phone": "0911111111"}).status_code == 401
    login_response = client.post("/api/staff/auth/login", json={"staff_id": staff["id"], "phone": "0987654321"})
    assert login_response.status_code == 200, login_response.text
    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
    bootstrap = client.get("/api/staff/bootstrap", headers=headers)
    assert bootstrap.status_code == 200, bootstrap.text
    data = bootstrap.json()
    assert data["mode"] == "staff"
    assert data["staff_user"]["id"] == staff["id"]
    assert all(item["staff_id"] == staff["id"] for item in data["appointments"])
    assert all(item["staff_id"] == staff["id"] for item in data["shifts"])


def test_staff_line_magic_link_is_short_lived_and_single_use(client):
    db = SessionLocal()
    try:
        staff = db.query(Staff).filter(Staff.phone == "0987654321").first()
        token = app.state.issue_staff_magic_link(staff, db)
    finally:
        db.close()

    first = client.post("/api/staff/auth/line", json={"token": token})
    assert first.status_code == 200, first.text
    assert first.json()["staff"]["name"] == "登入測試師傅"
    assert client.post("/api/staff/auth/line", json={"token": token}).status_code == 401


def test_customer_name_serial_and_multiple_phone_ids(client):
    headers = login(client)
    bootstrap = client.get("/api/admin/bootstrap", headers=headers).json()
    plan = bootstrap["services"][0]
    room = bootstrap["rooms"][0]
    created = client.post(
        "/api/admin/appointments",
        headers=headers,
        json={
            "customer_name": "多手機客戶",
            "phone": "0966000001",
            "service_plan_id": plan["id"],
            "start_time": "2099-08-25T19:00:00",
            "room_id": room["id"],
            "location_type": "onsite",
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["customer_name"] == "多手機客戶"
    assert row["customer_serial"].startswith("VIP-")
    customer_id = row["customer_id"]

    updated = client.patch(
        f"/api/admin/customers/{customer_id}",
        headers=headers,
        json={"display_name": "王先生", "phones": ["0966000001", "0966000002"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "王先生"
    assert updated.json()["phones"] == ["0966000001", "0966000002"]
    assert updated.json()["vip_serial"] == row["customer_serial"]


def test_public_booking_checks_availability_and_is_idempotent(client):
    headers = login(client)
    bootstrap = client.get("/api/admin/bootstrap", headers=headers).json()
    plan = next(item for item in bootstrap["services"] if item["code"] == "B")
    staff_response = client.post(
        "/api/admin/staff",
        headers=headers,
        json={"name": "LIFF 測試師傅", "category": "gay", "phone": "0977000001"},
    )
    assert staff_response.status_code == 201, staff_response.text
    staff = staff_response.json()
    shift = client.post(
        "/api/admin/shifts",
        headers=headers,
        json={
            "staff_id": staff["id"],
                "start_time": "2099-08-27T18:00:00",
                "end_time": "2099-08-27T23:00:00",
            "source": "admin",
        },
    )
    assert shift.status_code == 201, shift.text

    options = client.get("/api/public/booking/options")
    assert options.status_code == 200
    assert options.json()["minimum_lead_minutes"] == 90
    assert any(item["id"] == plan["id"] for item in options.json()["services"])

    availability = client.get(
        "/api/public/booking/availability",
        params={"service_plan_id": plan["id"], "start_time": "2099-08-27T19:00:00"},
    )
    assert availability.status_code == 200, availability.text
    assert [item["id"] for item in availability.json()["staff"]] == [staff["id"]]

    payload = {
        "customer_name": "網頁預約客戶",
        "phone": "0977000002",
        "service_plan_id": plan["id"],
        "start_time": "2099-08-27T19:00:00",
        "staff_id": staff["id"],
        "idempotency_key": "booking-test-key-000001",
        "notes": "請以 LINE 聯絡",
    }
    first = client.post("/api/public/booking/appointments", json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["duplicate"] is False
    assert first.json()["appointment"]["customer_name"] == "網頁預約客戶"
    assert first.json()["appointment"]["phone"] == "0977000002"

    repeated = client.post("/api/public/booking/appointments", json=payload)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["appointment"]["id"] == first.json()["appointment"]["id"]


def test_return_tables_promotions_and_line_pin_binding(client):
    headers = login(client)
    bootstrap = client.get("/api/admin/bootstrap", headers=headers).json()
    table_one = next(item for item in bootstrap["return_rule_sets"] if item["code"] == "TABLE_1")
    table_two = next(item for item in bootstrap["return_rule_sets"] if item["code"] == "TABLE_2")
    assert [(item["service_code"], item["amount"]) for item in table_one["rules"]] == [("A", 700), ("B", 800), ("C", 1000), ("D", 1200), ("E", 1200), ("BORROW", 300)]
    assert [(item["service_code"], item["amount"]) for item in table_two["rules"]] == [("A", 300), ("B", 300), ("C", 400), ("D", 500)]
    assert {"生日月優惠", "新進師傅體驗優惠", "首次到店優惠"}.issubset({item["name"] for item in bootstrap["promotions"]})

    db = SessionLocal()
    try:
        assert app.state.bind_line_admin("U-test-admin", "0000", db) is None
        identity = app.state.bind_line_admin("U-test-admin", "123456", db)
        assert identity["role"] == "admin"
        assert app.state.line_admin_identity("U-test-admin", db)["username"] == "admin"
        app.state.unbind_line_admin("U-test-admin", db)
        assert app.state.line_admin_identity("U-test-admin", db) is None
    finally:
        db.close()


def test_site_content_draft_publish_permissions_and_versions(client):
    public_before = client.get("/api/public/site-content")
    assert public_before.status_code == 200
    assert public_before.json() == {"content": {}, "version": 0, "published_at": None}
    assert client.get("/api/admin/site-content").status_code == 401

    admin_headers = login(client)
    clerk_create = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": "site-clerk", "display_name": "官網測試櫃台", "pin": "778899", "role": "clerk"},
    )
    assert clerk_create.status_code == 201, clerk_create.text
    clerk_headers = login(client, "site-clerk", "778899")
    assert client.get("/api/admin/site-content", headers=clerk_headers).status_code == 403

    manager_headers = login(client, "jerry", "654321")
    current = client.get("/api/admin/site-content", headers=manager_headers)
    assert current.status_code == 200, current.text
    assert current.json()["draft_version"] == 0
    assert current.json()["published_version"] == 0

    first_content = {
        "home": {"eyebrow": "EQUAL SPA", "subtitle": "回到平衡，也回到更自在的自己。"},
        "booking": {"url": "https://example.com/booking"},
        "services": [{"code": "A", "summary": "適合第一次到店的舒壓安排"}],
    }
    saved = client.put(
        "/api/admin/site-content/draft",
        headers=manager_headers,
        json={"content": first_content, "expected_version": 0},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft"] == first_content
    assert saved.json()["draft_version"] == 1
    assert saved.json()["published"] == {}

    public_during_draft = client.get("/api/public/site-content").json()
    assert public_during_draft["content"] == {}
    assert public_during_draft["version"] == 0

    stale_save = client.put(
        "/api/admin/site-content/draft",
        headers=manager_headers,
        json={"content": {"home": {}}, "expected_version": 0},
    )
    assert stale_save.status_code == 409
    assert client.put(
        "/api/admin/site-content/draft",
        headers=clerk_headers,
        json={"content": first_content, "expected_version": 1},
    ).status_code == 403
    assert client.post(
        "/api/admin/site-content/publish",
        headers=clerk_headers,
        json={"expected_version": 1},
    ).status_code == 403

    published = client.post(
        "/api/admin/site-content/publish",
        headers=manager_headers,
        json={"expected_version": 1},
    )
    assert published.status_code == 200, published.text
    assert published.json()["published"] == first_content
    assert published.json()["published_version"] == 1
    assert published.json()["published_at"] is not None

    public_after = client.get("/api/public/site-content")
    assert public_after.status_code == 200
    assert public_after.json()["content"] == first_content
    assert public_after.json()["version"] == 1

    second_content = {**first_content, "home": {**first_content["home"], "subtitle": "新的草稿，尚未發布。"}}
    second_saved = client.put(
        "/api/admin/site-content/draft",
        headers=admin_headers,
        json={"content": second_content, "expected_version": 1},
    )
    assert second_saved.status_code == 200, second_saved.text
    assert second_saved.json()["draft_version"] == 2
    assert client.get("/api/public/site-content").json()["content"] == first_content

    logs = client.get("/api/admin/audit-logs", headers=admin_headers).json()
    site_actions = {item["action"] for item in logs if item["entity_type"] == "site_content"}
    assert {"save_draft", "publish"}.issubset(site_actions)
