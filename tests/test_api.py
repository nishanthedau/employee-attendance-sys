from datetime import date

from app.models.entities import AttendanceSession, Role
from app.services.auth_service import create_user

LAT, LNG = 28.6139, 77.2090


def admin_token(client, db_session):
    create_user(db_session, "Admin", "admin@campus.edu", "secret123", Role.admin)
    res = client.post("/api/auth/login", json={"email": "admin@campus.edu", "password": "secret123"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def student_token(client, db_session, email="stu@campus.edu"):
    create_user(db_session, "Student", email, "secret123", Role.student)
    res = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
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


def session_qr_token(db_session, session_id) -> str:
    row = db_session.get(AttendanceSession, session_id)
    assert row is not None
    return row.qr_token


def test_student_cannot_create_session(client, db_session):
    headers = student_token(client, db_session)
    res = create_session(client, headers)
    assert res.status_code == 403


def test_create_session_and_qr(client, db_session):
    headers = admin_token(client, db_session)
    res = create_session(client, headers)
    assert res.status_code == 200
    session = res.json()
    assert session["id"]
    qr = client.get(f"/api/admin/attendance/qr?session_id={session['id']}", headers=headers)
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"


def test_scan_success_duplicate_409(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    body = {"session_id": session["id"], "qr_token": token, "latitude": LAT, "longitude": LNG}

    res = client.post("/api/student/attendance/scan", json=body, headers=stu_h)
    assert res.status_code == 200
    assert res.json()["ok"] is True

    dup = client.post("/api/student/attendance/scan", json=body, headers=stu_h)
    assert dup.status_code == 409


def test_scan_outside_zone(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = client.post(
        "/api/student/attendance/scan",
        json={"session_id": session["id"], "qr_token": token, "latitude": LAT + 0.01, "longitude": LNG},
        headers=stu_h,
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Outside attendance zone"


def test_scan_wrong_token(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()

    stu_h = student_token(client, db_session)
    res = client.post(
        "/api/student/attendance/scan",
        json={"session_id": session["id"], "qr_token": "deadbeef", "latitude": LAT, "longitude": LNG},
        headers=stu_h,
    )
    assert res.status_code == 400
    assert "Invalid QR" in res.json()["detail"]


def test_admin_dashboard_and_sessions(client, db_session):
    headers = admin_token(client, db_session)
    create_session(client, headers)
    dash = client.get("/api/admin/dashboard", headers=headers)
    assert dash.status_code == 200
    assert "today" in dash.json()

    sessions = client.get("/api/admin/sessions", headers=headers)
    assert sessions.status_code == 200
    body = sessions.json()
    assert body["total"] >= 1
    assert body["sessions"][0]["qr_expires_at"]


def test_student_management(client, db_session):
    headers = admin_token(client, db_session)
    created = client.post(
        "/api/admin/students",
        json={"name": "New Kid", "email": "newkid@campus.edu", "password": "secret123"},
        headers=headers,
    )
    assert created.status_code == 200
    new_id = created.json()["id"]

    listed = client.get("/api/admin/students?q=newkid", headers=headers)
    assert listed.status_code == 200
    assert any(s["id"] == new_id for s in listed.json())

    dup = client.post(
        "/api/admin/students",
        json={"name": "Dup", "email": "newkid@campus.edu", "password": "secret123"},
        headers=headers,
    )
    assert dup.status_code == 409

    assert client.delete(f"/api/admin/students/{new_id}", headers=headers).status_code == 200


def test_export_csv(client, db_session):
    headers = admin_token(client, db_session)
    res = client.get("/api/admin/export", headers=headers)
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "scan_time,student,email" in res.text


def test_current_week_shape(client, db_session):
    stu_h = student_token(client, db_session)
    res = client.get("/api/student/attendance/current-week", headers=stu_h)
    assert res.status_code == 200
    days = res.json()["days"]
    assert len(days) == 7
    assert any(d["is_today"] for d in days)


def test_student_cannot_access_admin_apis(client, db_session):
    stu_h = student_token(client, db_session)
    assert client.get("/api/admin/dashboard", headers=stu_h).status_code == 403
