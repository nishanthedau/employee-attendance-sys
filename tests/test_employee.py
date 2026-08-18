"""Phase 11: anonymous employee check-in — no login, pick yourself, pick status."""

import base64
from datetime import date, timedelta

from sqlalchemy import select

from app.models.entities import AttendanceRecord, AttendanceSession, OrgSettings, Role, VerificationMode
from app.services.auth_service import create_user
from app.services.code_service import encrypt_code

LAT, LNG = 28.6139, 77.2090

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def admin_token(client, db_session):
    create_user(db_session, "Admin", "admin@company.com", "secret123", Role.admin)
    res = client.post("/api/auth/login", json={"email": "admin@company.com", "password": "secret123"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def create_session(client, headers, **overrides):
    payload = {
        "subject": "DBMS",
        "faculty": "Prof. Rao",
        "date": date.today().isoformat(),
        "start_time": "00:00:00",
        "end_time": "23:59:00",
        "latitude": LAT,
        "longitude": LNG,
        "radius_meters": 75,
        "qr_expiry_minutes": 3,
    }
    payload.update(overrides)
    return client.post("/api/admin/attendance/create", json=payload, headers=headers)


def qr_token(db_session, session_id) -> str:
    return db_session.get(AttendanceSession, session_id).qr_token


def mark(client, session_id, token, employee_id, status="present", lat=LAT, lng=LNG, selfie=None, code=None):
    data = {
        "session_id": str(session_id),
        "qr_token": token,
        "employee_id": str(employee_id),
        "status": status,
        "latitude": str(lat),
        "longitude": str(lng),
    }
    if code:
        data["code"] = code
    files = {"selfie": ("selfie.png", selfie, "image/png")} if selfie is not None else None
    return client.post("/api/employee/attendance/mark", data=data, files=files)


def set_mode(db_session, mode):
    settings = db_session.get(OrgSettings, 1) or OrgSettings(id=1)
    settings.verification_mode = mode
    db_session.add(settings)
    db_session.commit()


def test_roster_lists_admin_added_employees(client, db_session):
    create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    create_user(db_session, "Bob", "bob@company.com", "secret123", Role.student)
    create_user(db_session, "Admin", "admin@company.com", "secret123", Role.admin)
    res = client.get("/api/employee/roster")
    assert res.status_code == 200
    names = [e["name"] for e in res.json()["employees"]]
    assert names == ["Alice", "Bob"]


def test_resolve_returns_class_and_mode(client, db_session):
    create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    res = client.post(
        "/api/employee/resolve", json={"session_id": sid, "qr_token": qr_token(db_session, sid)}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["session"]["subject"] == "DBMS"
    assert body["session"]["faculty"] == "Prof. Rao"
    assert body["verification_mode"] == "none"


def test_resolve_bad_qr_is_rejected(client, db_session):
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    res = client.post("/api/employee/resolve", json={"session_id": sid, "qr_token": "nope"})
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_qr"


def test_resolve_expired_qr_is_rejected(client, db_session):
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    session = db_session.get(AttendanceSession, sid)
    session.expires_at = session.expires_at - timedelta(hours=1)
    db_session.commit()
    res = client.post(
        "/api/employee/resolve", json={"session_id": sid, "qr_token": qr_token(db_session, sid)}
    )
    assert res.status_code == 400
    assert res.json()["code"] == "qr_expired"


def test_mark_records_present(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    res = mark(client, sid, qr_token(db_session, sid), alice.id)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["record"]["status"] == "present"
    record = db_session.execute(select(AttendanceRecord)).scalar_one()
    assert record.student_id == alice.id
    assert record.method == "scan"


def test_mark_accepts_late_and_absent(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    token = qr_token(db_session, sid)
    assert mark(client, sid, token, alice.id, status="late").json()["record"]["status"] == "late"
    sid2 = create_session(client, headers, subject="Maths").json()["id"]
    assert (
        mark(client, sid2, qr_token(db_session, sid2), alice.id, status="absent").json()["record"]["status"]
        == "absent"
    )


def test_mark_rejects_invalid_status(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    res = mark(client, sid, qr_token(db_session, sid), alice.id, status="sleeping")
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_status"


def test_mark_unknown_employee_404(client, db_session):
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    res = mark(client, sid, qr_token(db_session, sid), 9999)
    assert res.status_code == 404
    assert res.json()["code"] == "employee_not_found"


def test_mark_duplicate_is_blocked(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    token = qr_token(db_session, sid)
    assert mark(client, sid, token, alice.id).status_code == 200
    res = mark(client, sid, token, alice.id)
    assert res.status_code == 409
    assert res.json()["code"] == "already_marked"


def test_mark_outside_radius_blocked(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    res = mark(client, sid, qr_token(db_session, sid), alice.id, lat=28.4, lng=76.8)
    assert res.status_code == 400
    assert res.json()["code"] == "outside_zone"


def test_mark_requires_selfie_in_selfie_mode(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    set_mode(db_session, VerificationMode.selfie)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    token = qr_token(db_session, sid)
    res = mark(client, sid, token, alice.id)
    assert res.status_code == 400
    assert res.json()["code"] == "selfie_required"
    res = mark(client, sid, token, alice.id, selfie=PNG)
    assert res.status_code == 200
    assert res.json()["record"]["selfie"] is True


def test_mark_verifies_personal_code(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    alice.verification_code = encrypt_code("4826")
    alice.verification_code_assigned_at = date.today()
    db_session.commit()
    set_mode(db_session, VerificationMode.code)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    token = qr_token(db_session, sid)
    res = mark(client, sid, token, alice.id, code="1111")
    assert res.status_code == 400
    assert res.json()["code"] == "wrong_code"
    assert mark(client, sid, token, alice.id, code="4826").status_code == 200


def test_mark_without_login_needs_no_token(client, db_session):
    alice = create_user(db_session, "Alice", "alice@company.com", "secret123", Role.student)
    headers = admin_token(client, db_session)
    sid = create_session(client, headers).json()["id"]
    res = mark(client, sid, qr_token(db_session, sid), alice.id)
    assert res.status_code == 200
    assert "Authorization" not in set(res.request.headers)
