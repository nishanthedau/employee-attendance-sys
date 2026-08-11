"""Phase 9: per-session present/absent reporting — one marks, others absent."""

import base64
from datetime import date

from app.models.entities import AttendanceSession, Role
from app.services.auth_service import create_user

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
LAT, LNG = 28.6139, 77.2090


def _headers(client, db_session, email, name, role):
    create_user(db_session, name, email, "secret123", role)
    login = client.post("/api/auth/login", json={"email": email, "password": "secret123"}).json()
    return {"Authorization": f"Bearer {login['token']}"}


def _admin(client, db_session):
    return _headers(client, db_session, "admin@x.com", "Admin", Role.admin)


def _session(client, ah):
    return client.post(
        "/api/admin/attendance/create",
        headers=ah,
        json={
            "subject": "DBMS",
            "faculty": "Prof. Rao",
            "date": date.today().isoformat(),
            "start_time": "00:00:00",
            "end_time": "23:59:00",
            "latitude": LAT,
            "longitude": LNG,
            "radius_meters": 75,
            "qr_expiry_minutes": 3,
        },
    ).json()


def _scan(client, headers, session_id, token):
    data = {"session_id": str(session_id), "qr_token": token, "latitude": str(LAT), "longitude": str(LNG)}
    files = {"selfie": ("s.png", PNG, "image/png")}
    return client.post("/api/student/attendance/scan", data=data, files=files, headers=headers)


def test_history_lists_absent_per_session(client, db_session, tmp_selfie_storage):
    ah = _admin(client, db_session)
    sh = _headers(client, db_session, "stu@x.com", "Stu", Role.student)
    _headers(client, db_session, "other@x.com", "Other", Role.student)

    session = _session(client, ah)
    token = db_session.get(AttendanceSession, session["id"]).qr_token
    assert _scan(client, sh, session["id"], token).status_code == 200

    data = client.get(f"/api/admin/attendance/history?session_id={session['id']}", headers=ah).json()
    assert data["marked"] == 1
    assert data["enrolled"] == 2
    assert data["absent_count"] == 1
    assert data["records"][0]["student_name"] == "Stu"
    assert [a["email"] for a in data["absent"]] == ["other@x.com"]

    # The absent student was never scanned; the marked one is never absent.
    absent_emails = {a["email"] for a in data["absent"]}
    assert "stu@x.com" not in absent_emails


def test_history_all_present(client, db_session, tmp_selfie_storage):
    ah = _admin(client, db_session)
    sh = _headers(client, db_session, "stu@x.com", "Stu", Role.student)
    sh2 = _headers(client, db_session, "other@x.com", "Other", Role.student)

    session = _session(client, ah)
    token = db_session.get(AttendanceSession, session["id"]).qr_token
    assert _scan(client, sh, session["id"], token).status_code == 200
    assert _scan(client, sh2, session["id"], token).status_code == 200

    data = client.get(f"/api/admin/attendance/history?session_id={session['id']}", headers=ah).json()
    assert data["marked"] == 2
    assert data["absent_count"] == 0
    assert data["absent"] == []


def test_history_requires_admin(client, db_session):
    sh = _headers(client, db_session, "stu@x.com", "Stu", Role.student)
    res = client.get("/api/admin/attendance/history?session_id=1", headers=sh)
    assert res.status_code == 403


def test_csv_has_no_absent_rows(client, db_session, tmp_selfie_storage):
    """CSV represents attendance as scan rows; absent employees have no row."""
    ah = _admin(client, db_session)
    sh = _headers(client, db_session, "stu@x.com", "Stu", Role.student)
    _headers(client, db_session, "absent@x.com", "Absentee", Role.student)

    session = _session(client, ah)
    token = db_session.get(AttendanceSession, session["id"]).qr_token
    assert _scan(client, sh, session["id"], token).status_code == 200

    csv_text = client.get("/api/admin/export", headers=ah).text
    assert "stu@x.com" in csv_text
    assert "absent@x.com" not in csv_text
    lines = [ln for ln in csv_text.strip().splitlines() if ln]
    assert lines[0].startswith("scan_time,")
    assert len(lines) == 2  # header + the one present employee
