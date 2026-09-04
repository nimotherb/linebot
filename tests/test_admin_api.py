import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event


_database_file = tempfile.NamedTemporaryFile(prefix="equalspa-test-", suffix=".sqlite3", delete=False)
_database_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_database_file.name).as_posix()}"
os.environ["ADMIN_INITIAL_PIN"] = "123456"
os.environ["MANAGER_INITIAL_PIN"] = "654321"
os.environ["CUSTOMER_SERIAL_START"] = "4800"

import main as main_module  # noqa: E402
from main import Base, SessionLocal, Staff, User, app, build_booking_web_message, build_line_staff_binding_menu, build_staff_bubble, build_staff_week_appointments, engine, handle_line_admin_message, handle_root_action, now_taipei_naive, on_startup, parse_staff_profile_text, public_https_url, repair_legacy_staff_profile_fields  # noqa: E402
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


def test_line_booking_uses_one_small_web_entry_without_postbacks():
    message = build_booking_web_message()
    actions = [item.action for item in message.contents.footer.contents]
    assert all(action.type == "uri" for action in actions)
    assert actions[0].uri.startswith("https://")
    assert "booking" in actions[0].uri


def test_line_root_staff_binding_menu_is_text_only_and_paginated(client):
    with SessionLocal() as db:
        message = build_line_staff_binding_menu(db)
    assert message.alt_text == "師傅 LINE 綁定管理"
    assert message.contents.type == "carousel"
    assert len(message.contents.contents) <= 10
    assert all(getattr(item, "hero", None) is None for item in message.contents.contents)
    assert all(getattr(item.body.contents[0], "text", "") for item in message.contents.contents)


def test_staff_profile_parser_requires_one_complete_strict_update():
    assert parse_staff_profile_text("身高=156\n體重=60\n角色=攻擊手") == {
        "height": "156",
        "weight": "60",
        "role": "攻擊手",
    }
    assert parse_staff_profile_text("角色：攻守兼備 身高 188 體重 80")["role"] == "攻守兼備"
    with pytest.raises(ValueError):
        parse_staff_profile_text("身高=156\n體重=60")
    with pytest.raises(ValueError):
        parse_staff_profile_text("身高=156\n體重=60\n角色=攻擊方")


def test_legacy_staff_profile_text_is_split_without_touching_valid_data():
    legacy = Staff(line_user_id="seeded:legacy-profile", name="舊資料", height="180\n體重 74\n角色 攻守兼備", weight=None, role=None)
    assert repair_legacy_staff_profile_fields(legacy) is True
    assert (legacy.height, legacy.weight, legacy.role) == ("180", "74", "攻守兼備")

    partially_repaired = Staff(
        line_user_id="seeded:partially-repaired-profile",
        name="部分已修正",
        height="157\n體重53\n角色 守備方",
        weight="56",
        role=None,
    )
    assert repair_legacy_staff_profile_fields(partially_repaired) is True
    assert (partially_repaired.height, partially_repaired.weight, partially_repaired.role) == ("157", "56", "守備方")

    valid = Staff(line_user_id="seeded:valid-profile", name="正確資料", height="178", weight="72", role="攻擊手")
    assert repair_legacy_staff_profile_fields(valid) is False
    assert (valid.height, valid.weight, valid.role) == ("178", "72", "攻擊手")


def test_relative_staff_photo_is_converted_to_line_safe_https_url():
    assert public_https_url("/api/public/staff/1/photo").startswith("https://")
    assert public_https_url("ftp://example.com/photo.jpg") is None


def test_booking_availability_uses_bounded_query_count(client):
    Shift = app.state.admin_models["Shift"]
    ServicePlan = app.state.admin_models["ServicePlan"]
    db = SessionLocal()
    try:
        plan = db.query(ServicePlan).filter(ServicePlan.code == "B").first()
        staff = db.query(Staff).filter(Staff.employment_status == "active").order_by(Staff.id).limit(12).all()
        plan_id = plan.id
        staff_count = len(staff)
        for item in staff:
            db.add(Shift(staff_id=item.id, start_time=datetime(2099, 12, 1, 16), end_time=datetime(2099, 12, 1, 20), status="active", source="query-count-test"))
        db.commit()
    finally:
        db.close()

    statements = []

    def count_statement(*_args):
        statements.append(1)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        response = client.get(
            "/api/public/booking/availability",
            params={"service_plan_id": plan_id, "start_time": "2099-12-01T17:00:00"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert response.status_code == 200, response.text
    assert len(response.json()["staff"]) == staff_count
    assert len(statements) <= 5


def test_external_poke_checks_database_once(client):
    statements = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = client.get("/api/health/db")
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "reachable"
    assert len(statements) == 1
    assert statements[0].strip().upper() == "SELECT 1"


def test_login_is_required_and_bootstrap_seeds_two_rooms(client):
    assert client.get("/api/admin/bootstrap").status_code == 401
    headers = login(client)
    response = client.get("/api/admin/bootstrap", headers=headers)
    assert response.status_code == 200
    assert [room["name"] for room in response.json()["rooms"]] == ["657上", "657下"]
    staff_rows = response.json()["staff"]
    assert len(staff_rows) == 47
    assert all(item["photo_url"].startswith("https://") for item in staff_rows)
    assert customer_serial(phone="0912345678", grade="SSR") == "SSR-5678"


def test_staff_photo_upload_and_safe_permanent_delete(client):
    admin_headers = login(client)
    manager_headers = login(client, "jerry", "654321")
    created = client.post(
        "/api/admin/staff",
        headers=admin_headers,
        json={
            "name": "待刪除師傅",
            "category": "gay",
            "photo_url": "https://example.com/portrait.jpg",
            "height": "178",
            "weight": "72",
            "role": "攻守兼備",
        },
    )
    assert created.status_code == 201, created.text
    created_profile = created.json()
    staff_id = created_profile["id"]
    assert (created_profile["height"], created_profile["weight"], created_profile["role"]) == ("178", "72", "攻守兼備")
    public_profile = next(item for item in client.get("/api/public/therapists").json() if item["id"] == staff_id)
    assert (public_profile["height"], public_profile["weight"], public_profile["role"]) == ("178", "72", "攻守兼備")

    updated = client.patch(
        f"/api/admin/staff/{staff_id}",
        headers=admin_headers,
        json={"height": "180", "weight": "75", "role": "攻擊手"},
    )
    assert updated.status_code == 200, updated.text
    assert (updated.json()["height"], updated.json()["weight"], updated.json()["role"]) == ("180", "75", "攻擊手")

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

    deleted = client.delete(f"/api/admin/staff/{staff_id}", headers=manager_headers, params={"reason": "店長永久刪除測試"})
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
    removed_used = client.delete(f"/api/admin/staff/{used.json()['id']}", headers=admin_headers, params={"reason": "驗證強制永久刪除"})
    assert removed_used.status_code == 200
    assert all(item["staff_id"] != used.json()["id"] for item in client.get("/api/admin/bootstrap", headers=admin_headers).json()["shifts"])


def test_appointment_end_and_staff_room_conflicts(client):
    headers = login(client)
    created_clerk = client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "conflict-clerk", "display_name": "clerk", "pin": "112233", "role": "clerk"},
    )
    assert created_clerk.status_code == 201, created_clerk.text
    clerk_headers = login(client, "conflict-clerk", "112233")
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
    first = client.post("/api/admin/appointments", headers=clerk_headers, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["end_time"] == (start_at + timedelta(minutes=90)).isoformat(timespec="minutes")
    assert first.json()["customer_serial"] == "N-5678"

    with SessionLocal() as db:
        staff_obj = db.query(Staff).filter(Staff.id == staff["id"]).first()
        weekly = build_staff_week_appointments(staff_obj, db)
        assert weekly.alt_text == f"{staff_obj.name}未來一週預約"

    staff_conflict = client.post(
        "/api/admin/appointments",
        headers=clerk_headers,
        json={**payload, "phone": "0922222222", "start_time": overlap_at.isoformat(timespec="seconds"), "room_id": bootstrap["rooms"][1]["id"]},
    )
    assert staff_conflict.status_code == 409
    assert "師傅" in staff_conflict.json()["detail"]

    room_conflict = client.post(
        "/api/admin/appointments",
        headers=clerk_headers,
        json={**payload, "phone": "0933333333", "start_time": overlap_at.isoformat(timespec="seconds"), "staff_id": None},
    )
    assert room_conflict.status_code == 409
    assert "房間" in room_conflict.json()["detail"]
    admin_override = client.post(
        "/api/admin/appointments",
        headers=headers,
        json={**payload, "phone": "0944444444", "start_time": overlap_at.isoformat(timespec="seconds")},
    )
    assert admin_override.status_code == 201, admin_override.text


def test_manager_can_only_create_clerk_accounts(client):
    manager_headers = login(client, "jerry", "654321")
    denied_manager = client.post(
        "/api/admin/users",
        headers=manager_headers,
        json={"username": "another-manager", "display_name": "副店長", "pin": "112233", "role": "manager"},
    )
    assert denied_manager.status_code == 403

    allowed_clerk = client.post(
        "/api/admin/users",
        headers=manager_headers,
        json={"username": "frontdesk", "display_name": "櫃台", "pin": "112233", "role": "clerk"},
    )
    assert allowed_clerk.status_code == 201
    clerk_id = allowed_clerk.json()["id"]
    assert allowed_clerk.json()["can_override_time_rules"] is False
    staff_id = client.get("/api/admin/bootstrap", headers=manager_headers).json()["staff"][0]["id"]
    cross_day = client.post(
        "/api/admin/shifts",
        headers=manager_headers,
        json={"staff_id": staff_id, "start_time": "2099-01-01T23:30:00", "end_time": "2099-01-02T00:15:00"},
    )
    assert cross_day.status_code == 201, cross_day.text
    clerk_headers = login(client, "frontdesk", "112233")
    blocked_overlap = client.post(
        "/api/admin/shifts",
        headers=clerk_headers,
        json={"staff_id": staff_id, "start_time": "2099-01-01T23:45:00", "end_time": "2099-01-02T00:05:00"},
    )
    assert blocked_overlap.status_code == 409
    enabled = client.patch(
        f"/api/admin/users/{clerk_id}/permissions",
        headers=manager_headers,
        json={"can_override_time_rules": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["can_override_time_rules"] is True
    forced_overlap = client.post(
        "/api/admin/shifts",
        headers=clerk_headers,
        json={"staff_id": staff_id, "start_time": "2099-01-01T23:45:00", "end_time": "2099-01-02T00:05:00"},
    )
    assert forced_overlap.status_code == 201, forced_overlap.text
    removed = client.delete(f"/api/admin/users/{clerk_id}", headers=manager_headers)
    assert removed.status_code == 200
    assert removed.json()["ok"] is True
    assert all(item["id"] != clerk_id for item in client.get("/api/admin/users", headers=manager_headers).json())

    admin_user = next(item for item in client.get("/api/admin/users", headers=manager_headers).json() if item["username"] == "admin")
    assert client.delete(f"/api/admin/users/{admin_user['id']}", headers=manager_headers).status_code == 403
    assert client.post(
        "/api/admin/bulk-delete",
        headers=manager_headers,
        json={"entity": "users", "ids": [admin_user["id"]], "reason": "不可刪除 Admin"},
    ).status_code == 403
    audit_id = client.get("/api/admin/audit-logs", headers=manager_headers).json()[0]["id"]
    assert client.delete(f"/api/admin/audit-logs/{audit_id}", headers=manager_headers).status_code == 403
    assert client.post(
        "/api/admin/bulk-delete",
        headers=manager_headers,
        json={"entity": "audit_logs", "ids": [audit_id], "reason": "店長只能查看"},
    ).status_code == 403


def test_booking_request_waits_for_review_and_can_be_confirmed_without_shift(client):
    headers = login(client)
    options = client.get("/api/public/booking/options").json()
    plan = next(item for item in options["services"] if item["can_choose_staff"])
    staff = options["staff"][0]
    start_at = (now_taipei_naive() + timedelta(days=4)).replace(hour=19, minute=0, second=0, microsecond=0)
    availability = client.get("/api/public/booking/availability", params={
        "service_plan_id": plan["id"],
        "start_time": start_at.isoformat(timespec="seconds"),
        "requested_staff_id": staff["id"],
        "request_only": "true",
    })
    assert availability.status_code == 200, availability.text
    assert availability.json()["request_only"] is True
    assert availability.json()["staff"][0]["id"] == staff["id"]
    before = len(client.get("/api/admin/appointments", headers=headers).json())
    created = client.post("/api/public/booking/requests", json={
        "customer_name": "通知測試客戶",
        "phone": "0966666666",
        "service_plan_id": plan["id"],
        "start_time": start_at.isoformat(timespec="seconds"),
        "staff_id": staff["id"],
        "promotion_id": None,
        "notes": "官網指定師傅",
        "id_token": None,
        "idempotency_key": "booking-request-test-0001",
        "source": "official_website",
        "website": "",
    })
    assert created.status_code == 201, created.text
    request_row = created.json()["booking_request"]
    assert request_row["status"] == "pending"
    assert request_row["staff_id"] == staff["id"]
    assert len(client.get("/api/admin/appointments", headers=headers).json()) == before

    confirmed = client.post(f"/api/admin/booking-requests/{request_row['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["booking_request"]["status"] == "confirmed"
    assert confirmed.json()["appointment"]["staff_id"] == staff["id"]
    assert len(client.get("/api/admin/appointments", headers=headers).json()) == before + 1


def test_manager_can_unlink_staff_line_without_deleting_history(client, monkeypatch):
    class FakeLineBot:
        def push_message(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(main_module, "bot_staff_api", FakeLineBot())
    admin_headers = login(client)
    manager_headers = login(client, "jerry", "654321")
    line_user_id = "U" + "a" * 32
    created = client.post("/api/admin/staff", headers=admin_headers, json={
        "name": "LINE 解綁測試師傅",
        "category": "gay",
        "line_user_id": line_user_id,
    })
    assert created.status_code == 201, created.text
    assert created.json()["line_connected"] is True
    unlinked = client.delete(f"/api/admin/staff/{created.json()['id']}/line-link", headers=manager_headers)
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["line_connected"] is False
    with SessionLocal() as db:
        RevokedStaffLine = app.state.admin_models["RevokedStaffLine"]
        assert db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == line_user_id).count() == 1


def test_staff_profile_line_rebinding_and_root_dual_identity(client, monkeypatch):
    class FakeLineBot:
        def __init__(self):
            self.sent = []

        def push_message(self, recipient, message):
            self.sent.append((recipient, message.text))

    fake_bot = FakeLineBot()
    monkeypatch.setattr(main_module, "bot_staff_api", fake_bot)
    headers = login(client)
    created = client.post("/api/admin/staff", headers=headers, json={
        "name": "資料串接測試師傅",
        "category": "straight",
    })
    assert created.status_code == 201, created.text
    staff_id = created.json()["id"]

    updated = client.patch(f"/api/admin/staff/{staff_id}", headers=headers, json={
        "height": 177,
        "weight": 80,
        "role": "守備方",
    })
    assert updated.status_code == 200, updated.text
    assert (updated.json()["height"], updated.json()["weight"], updated.json()["role"]) == ("177", "80", "守備方")

    first_line_id = "U" + "b" * 32
    second_line_id = "U" + "c" * 32
    linked = client.put(f"/api/admin/staff/{staff_id}/line-link", headers=headers, json={"line_user_id": first_line_id})
    assert linked.status_code == 200, linked.text
    assert linked.json()["line_connected"] is True
    assert linked.json()["notification_sent"] is True

    rebound = client.put(f"/api/admin/staff/{staff_id}/line-link", headers=headers, json={"line_user_id": second_line_id})
    assert rebound.status_code == 200, rebound.text
    assert [item[0] for item in fake_bot.sent[-2:]] == [first_line_id, second_line_id]

    with SessionLocal() as db:
        RevokedStaffLine = app.state.admin_models["RevokedStaffLine"]
        assert db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == first_line_id).count() == 1
        assert db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == second_line_id).count() == 0

        app.state.bind_line_admin(second_line_id, "123456", db)
        assert app.state.line_admin_identity(second_line_id, db)["role"] == "admin"
        assert db.query(Staff).filter(Staff.id == staff_id, Staff.line_user_id == second_line_id).first()

        ordered_staff_ids = [row.id for row in db.query(Staff).order_by(Staff.name, Staff.id).all()]
        menu_offset = (ordered_staff_ids.index(staff_id) // 9) * 9
        menu = build_line_staff_binding_menu(db, current_line_user_id=second_line_id, offset=menu_offset)
        assert any(
            getattr(content, "text", "") == "已綁定目前 LINE"
            for bubble in menu.contents.contents
            for content in bubble.body.contents
        )

        clerk_reply = handle_line_admin_message("新增客服 測試客服 lineclerk01 2468", second_line_id, db)
        assert "客服帳號已建立" in clerk_reply.text
        AdminUser = app.state.admin_models["AdminUser"]
        clerk = db.query(AdminUser).filter(AdminUser.username == "lineclerk01").first()
        assert clerk and clerk.role == "clerk"

        manager_line_id = "U" + "f" * 32
        app.state.bind_line_admin(manager_line_id, "654321", db)
        manager_reply = handle_line_admin_message("新增客服 店長新增客服 lineclerk02 1357", manager_line_id, db)
        assert "客服帳號已建立" in manager_reply.text
        manager_clerk = db.query(AdminUser).filter(AdminUser.username == "lineclerk02").first()
        assert manager_clerk and manager_clerk.role == "clerk"

        old_target_line_id = "U" + "e" * 32
        replacement_target = Staff(
            line_user_id=old_target_line_id,
            name="Root 改綁測試師傅",
            category="gay",
            employment_status="active",
        )
        db.add(replacement_target)
        db.commit()
        app.state.unlink_staff_line(staff_id, db, actor_id=app.state.line_admin_identity(second_line_id, db)["id"])
        root_reply = handle_root_action(
            f"action=confirm_bind_staff&staff_id={replacement_target.id}",
            second_line_id,
            db,
            is_staff_side=True,
        )
        assert "管理員權限會同時保留" in root_reply.text
        db.refresh(replacement_target)
        assert replacement_target.line_user_id == second_line_id
        assert db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == old_target_line_id).count() == 1


def test_staff_line_binding_rolls_back_when_notification_fails(client, monkeypatch):
    class FailingLineBot:
        def push_message(self, *_args, **_kwargs):
            raise RuntimeError("not reachable")

    monkeypatch.setattr(main_module, "bot_staff_api", FailingLineBot())
    headers = login(client)
    created = client.post("/api/admin/staff", headers=headers, json={
        "name": "無法通知測試師傅",
        "category": "gay",
    })
    assert created.status_code == 201, created.text
    staff_id = created.json()["id"]
    line_user_id = "U" + "d" * 32

    response = client.put(f"/api/admin/staff/{staff_id}/line-link", headers=headers, json={"line_user_id": line_user_id})
    assert response.status_code == 502, response.text
    with SessionLocal() as db:
        item = db.query(Staff).filter(Staff.id == staff_id).first()
        assert item.line_user_id.startswith("pending:")


def test_legacy_public_backoffice_bootstrap_is_disabled(client):
    response = client.get("/api/public/bootstrap")
    assert response.status_code == 404


def test_staff_passwordless_session_only_returns_own_data(client):
    headers = login(client)
    created = client.post(
        "/api/admin/staff",
        headers=headers,
        json={"name": "登入測試師傅", "category": "gay", "phone": "0987654321"},
    )
    assert created.status_code == 201, created.text
    staff = created.json()
    assert client.post("/api/staff/auth/login", json={}).status_code == 422
    assert client.post("/api/staff/auth/login", json={"phone": "0911111111"}).status_code == 401
    duplicate = client.post(
        "/api/admin/staff",
        headers=headers,
        json={"name": "重複手機測試師傅", "category": "gay", "phone": "0987654321"},
    )
    assert duplicate.status_code == 409
    login_response = client.post("/api/staff/auth/login", json={"phone": "0987654321"})
    assert login_response.status_code == 200, login_response.text
    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
    bootstrap = client.get("/api/staff/bootstrap", headers=headers)
    assert bootstrap.status_code == 200, bootstrap.text
    data = bootstrap.json()
    assert data["mode"] == "staff"
    assert data["staff_user"]["id"] == staff["id"]
    assert all(item["staff_id"] == staff["id"] for item in data["appointments"])
    assert all(item["staff_id"] == staff["id"] for item in data["shifts"])


def test_permanent_staff_delete_is_confirmed_and_preserves_history(client):
    headers = login(client)
    removable = client.post(
        "/api/admin/staff",
        headers=headers,
        json={"name": "永久刪除測試師傅", "category": "gay", "phone": "0955000001"},
    )
    assert removable.status_code == 201, removable.text
    removable_staff = removable.json()

    with SessionLocal() as db:
        staff_obj = db.query(Staff).filter(Staff.id == removable_staff["id"]).first()
        bubble = build_staff_bubble(staff_obj)
        actions = str(bubble)
        assert "request_permanent_delete_staff" in actions
        assert "永久刪除" in actions

    assert client.delete(f"/api/admin/staff/{removable_staff['id']}", headers=headers).status_code == 422
    deleted = client.delete(
        f"/api/admin/staff/{removable_staff['id']}",
        headers=headers,
        params={"reason": "重複建立的測試帳戶"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_staff_name"] == "永久刪除測試師傅"
    assert all(item["id"] != removable_staff["id"] for item in client.get("/api/admin/bootstrap", headers=headers).json()["staff"])

    protected = client.post(
        "/api/admin/staff",
        headers=headers,
        json={"name": "保留歷史測試師傅", "category": "gay"},
    ).json()
    shift = client.post(
        "/api/admin/shifts",
        headers=headers,
        json={
            "staff_id": protected["id"],
            "start_time": "2030-01-02T14:00:00",
            "end_time": "2030-01-02T18:00:00",
            "source": "admin",
        },
    )
    assert shift.status_code == 201, shift.text
    removed_protected = client.delete(
        f"/api/admin/staff/{protected['id']}",
        headers=headers,
        params={"reason": "強制刪除已有歷史的師傅"},
    )
    assert removed_protected.status_code == 200
    assert all(item["id"] != shift.json()["id"] for item in client.get("/api/admin/bootstrap", headers=headers).json()["shifts"])


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
    assert row["customer_serial"] == "N-0001"
    customer_id = row["customer_id"]

    updated = client.patch(
        f"/api/admin/customers/{customer_id}",
        headers=headers,
        json={"display_name": "王先生", "phones": ["0966000001", "0966000002"], "customer_grade": "SSR"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "王先生"
    assert updated.json()["phones"] == ["0966000001", "0966000002"]
    assert updated.json()["vip_serial"] == "SSR-0001"


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
    assert first.json()["appointment"]["staff_id"] == staff["id"]
    assert "customer_serial" not in first.json()["appointment"]
    assert "customer_grade" not in first.json()["appointment"]
    assert "customer_id" not in first.json()["appointment"]

    repeated = client.post("/api/public/booking/appointments", json=payload)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["appointment"]["id"] == first.json()["appointment"]["id"]

    automatic = client.post("/api/public/booking/appointments", json={
        **payload,
        "phone": "0977000003",
        "customer_name": "自動派單客戶",
        "start_time": "2099-08-27T21:00:00",
        "staff_id": None,
        "idempotency_key": "booking-test-key-auto-0001",
    })
    assert automatic.status_code == 201, automatic.text
    assert automatic.json()["appointment"]["staff_id"] == staff["id"]


def test_admin_can_update_own_login_and_bulk_delete(client):
    headers = login(client)
    changed = client.patch(
        "/api/admin/auth/me",
        headers=headers,
        json={"current_pin": "123456", "display_name": "Admin 測試", "username": "admin-test", "new_pin": "123457"},
    )
    assert changed.status_code == 200, changed.text
    changed_headers = login(client, "admin-test", "123457")
    service = client.post(
        "/api/admin/services",
        headers=changed_headers,
        json={"code": "DELETE-ME", "name": "批量刪除測試", "duration_minutes": 60, "price": 1},
    )
    assert service.status_code == 201, service.text
    deleted = client.post(
        "/api/admin/bulk-delete",
        headers=changed_headers,
        json={"entity": "services", "ids": [service.json()["id"]], "reason": "自動測試批量刪除"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_ids"] == [service.json()["id"]]
    restored = client.patch(
        "/api/admin/auth/me",
        headers=changed_headers,
        json={"current_pin": "123457", "display_name": "Admin", "username": "admin", "new_pin": "123456"},
    )
    assert restored.status_code == 200, restored.text


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


def test_catalog_create_and_delete_preserves_historical_order_links(client):
    headers = login(client)
    service = client.post(
        "/api/admin/services",
        headers=headers,
        json={
            "code": "ARCHIVE_TEST",
            "name": "歷史保留測試方案",
            "duration_minutes": 60,
            "price": 1800,
            "description": "刪除後仍保留舊訂單關聯",
        },
    )
    assert service.status_code == 201, service.text
    service_row = service.json()

    promotion = client.post(
        "/api/admin/promotions",
        headers=headers,
        json={
            "name": "歷史保留測試優惠",
            "calculation_type": "fixed_discount",
            "value": 100,
            "description": "舊訂單仍可辨識",
        },
    )
    assert promotion.status_code == 201, promotion.text
    promotion_row = promotion.json()

    appointment = client.post(
        "/api/admin/appointments",
        headers=headers,
        json={
            "customer_name": "歷史保留客戶",
            "phone": "0911222333",
            "service_plan_id": service_row["id"],
            "promotion_id": promotion_row["id"],
            "start_time": "2099-12-20T11:00:00",
            "location_type": "pending",
        },
    )
    assert appointment.status_code == 201, appointment.text
    appointment_id = appointment.json()["id"]

    removed_service = client.delete(f"/api/admin/services/{service_row['id']}", headers=headers)
    removed_promotion = client.delete(f"/api/admin/promotions/{promotion_row['id']}", headers=headers)
    assert removed_service.status_code == 200, removed_service.text
    assert removed_service.json()["history_preserved"] is True
    assert removed_promotion.status_code == 200, removed_promotion.text
    assert removed_promotion.json()["history_preserved"] is True

    assert all(item["id"] != service_row["id"] for item in client.get("/api/admin/services", headers=headers).json())
    assert all(item["id"] != promotion_row["id"] for item in client.get("/api/admin/promotions", headers=headers).json())
    appointment_after = next(item for item in client.get("/api/admin/bootstrap", headers=headers).json()["appointments"] if item["id"] == appointment_id)
    assert appointment_after["service_name"] == "歷史保留測試方案"
    assert appointment_after["promotion_name"] == "歷史保留測試優惠"


def test_admin_can_reset_booking_data_without_deleting_master_data(client):
    admin_headers = login(client)
    manager_headers = login(client, "jerry", "654321")
    before = client.get("/api/admin/bootstrap", headers=admin_headers).json()
    assert before["appointments"]
    staff_count = len(before["staff"])
    customer_count = len(before["customers"])
    service_count = len(before["services"])

    denied = client.post(
        "/api/admin/maintenance/reset-booking-data",
        headers=manager_headers,
        json={"confirmation": "DELETE_ALL_BOOKING_DATA"},
    )
    assert denied.status_code == 403
    invalid = client.post(
        "/api/admin/maintenance/reset-booking-data",
        headers=admin_headers,
        json={"confirmation": "DELETE_SOMETHING_ELSE"},
    )
    assert invalid.status_code == 422

    reset = client.post(
        "/api/admin/maintenance/reset-booking-data",
        headers=admin_headers,
        json={"confirmation": "DELETE_ALL_BOOKING_DATA"},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["deleted"]["appointments"] > 0

    after = client.get("/api/admin/bootstrap", headers=admin_headers).json()
    assert after["appointments"] == []
    assert after["booking_requests"] == []
    assert len(after["staff"]) == staff_count
    assert len(after["customers"]) == customer_count
    assert len(after["services"]) == service_count


def test_startup_clears_invalid_legacy_phone_without_deleting_customer(client):
    with SessionLocal() as db:
        customer = User(line_user_id="legacy-invalid-phone-test", phone="B;4", display_name="舊測試客戶")
        db.add(customer)
        db.commit()
        customer_id = customer.id

    on_startup()

    with SessionLocal() as db:
        customer = db.query(User).filter(User.id == customer_id).first()
        assert customer is not None
        assert customer.phone is None
