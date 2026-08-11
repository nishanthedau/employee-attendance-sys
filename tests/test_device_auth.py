"""Phase 2: device-bound auth — employees log in once, device token persists."""

from app.models.entities import DeviceRegistration, Role
from app.services.auth_service import create_user


def _login(client, email, password="secret123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _make_student(db_session, email="device@company.com"):
    return create_user(db_session, "Device User", email, "secret123", Role.student)


def test_bind_device_returns_token(client, db_session):
    _make_student(db_session)
    token = _login(client, "device@company.com").json()["token"]
    res = client.post(
        "/api/auth/device",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_name": "Chrome on iPhone",
            "os": "iOS",
            "model": "iPhone 14",
            "screen": "390x844",
            "language": "en",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["device_token"]
    assert body["device_id"]


def test_device_token_works_on_protected_route(client, db_session):
    _make_student(db_session)
    token = _login(client, "device@company.com").json()["token"]
    device_token = client.post(
        "/api/auth/device", headers={"Authorization": f"Bearer {token}"}, json={}
    ).json()["device_token"]
    headers = {"Authorization": f"Bearer {device_token}"}
    assert client.get("/api/student/attendance/current-week", headers=headers).status_code == 200


def test_login_token_still_works_after_device_binding(client, db_session):
    _make_student(db_session)
    token = _login(client, "device@company.com").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/auth/device", headers=headers, json={}).status_code == 200
    assert client.get("/api/student/attendance/current-week", headers=headers).status_code == 200


def test_revoked_device_token_rejected(client, db_session):
    _make_student(db_session)
    login_token = _login(client, "device@company.com").json()["token"]
    bound = client.post(
        "/api/auth/device", headers={"Authorization": f"Bearer {login_token}"}, json={}
    ).json()
    device_id, device_token = bound["device_id"], bound["device_token"]
    device = db_session.get(DeviceRegistration, device_id)
    device.is_active = False
    db_session.commit()

    headers = {"Authorization": f"Bearer {device_token}"}
    res = client.get("/api/student/attendance/current-week", headers=headers)
    assert res.status_code == 401
    assert res.json()["detail"] == "Your session has expired. Please sign in again."


def test_device_token_stored_hashed(client, db_session):
    user = _make_student(db_session)
    token = _login(client, "device@company.com").json()["token"]
    device_token = client.post(
        "/api/auth/device", headers={"Authorization": f"Bearer {token}"}, json={}
    ).json()["device_token"]
    rows = db_session.query(DeviceRegistration).filter(DeviceRegistration.user_id == user.id).all()
    assert len(rows) == 1
    assert rows[0].token_hash != device_token
    assert rows[0].is_active is True


def test_admin_cannot_bind_device(client, db_session):
    create_user(db_session, "Admin", "admin@company.com", "secret123", Role.admin)
    token = _login(client, "admin@company.com").json()["token"]
    res = client.post("/api/auth/device", headers={"Authorization": f"Bearer {token}"}, json={})
    assert res.status_code == 403
