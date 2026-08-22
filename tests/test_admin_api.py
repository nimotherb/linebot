import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_database_file = tempfile.NamedTemporaryFile(prefix="equalspa-test-", suffix=".sqlite3", delete=False)
_database_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_database_file.name).as_posix()}"
os.environ["ADMIN_INITIAL_PIN"] = "123456"
os.environ["MANAGER_INITIAL_PIN"] = "654321"

from main import Base, app, engine  # noqa: E402


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


def test_appointment_end_and_staff_room_conflicts(client):
    headers = login(client)
    bootstrap = client.get("/api/admin/bootstrap", headers=headers).json()
    ninety_minute_plan = next(item for item in bootstrap["services"] if item["duration_minutes"] == 90)
    room = bootstrap["rooms"][0]

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
        "start_time": "2026-08-24T16:00:00",
        "staff_id": staff["id"],
        "room_id": room["id"],
        "location_type": "onsite",
    }
    first = client.post("/api/admin/appointments", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["end_time"] == "2026-08-24T17:30"

    staff_conflict = client.post(
        "/api/admin/appointments",
        headers=headers,
        json={**payload, "phone": "0922222222", "start_time": "2026-08-24T17:00:00", "room_id": bootstrap["rooms"][1]["id"]},
    )
    assert staff_conflict.status_code == 409
    assert "師傅" in staff_conflict.json()["detail"]

    room_conflict = client.post(
        "/api/admin/appointments",
        headers=headers,
        json={**payload, "phone": "0933333333", "start_time": "2026-08-24T17:00:00", "staff_id": None},
    )
    assert room_conflict.status_code == 409
    assert "房間" in room_conflict.json()["detail"]


def test_manager_can_only_create_clerk_account(client):
    manager_headers = login(client, "jerry", "654321")
    denied = client.post(
        "/api/admin/users",
        headers=manager_headers,
        json={"username": "another-manager", "display_name": "副店長", "pin": "112233", "role": "manager"},
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/api/admin/users",
        headers=manager_headers,
        json={"username": "frontdesk", "display_name": "櫃台", "pin": "112233", "role": "clerk"},
    )
    assert allowed.status_code == 201
