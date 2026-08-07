import base64
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models.entities import AttendanceRecord, AttendanceSession, Role
from app.services.auth_service import create_user

LAT, LNG = 28.6139, 77.2090

# A real 1x1 PNG so the server's magic-byte check passes.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


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


def scan(client, headers, session_id, token, lat=LAT, lng=LNG, selfie=PNG, selfie_type="image/png"):
    data = {
        "session_id": str(session_id),
        "qr_token": token,
        "latitude": str(lat),
        "longitude": str(lng),
    }
    files = {"selfie": ("selfie.png", selfie, selfie_type)} if selfie is not None else None
    return client.post("/api/student/attendance/scan", data=data, files=files, headers=headers)


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


def test_scan_success_duplicate_409(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], token)
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["record"]["selfie"] is True

    dup = scan(client, stu_h, session["id"], token)
    assert dup.status_code == 409
    assert dup.json()["code"] == "already_marked"
    assert len(list(tmp_selfie_storage.glob("*"))) == 1


def test_scan_outside_zone(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], token, lat=LAT + 0.01)
    assert res.status_code == 400
    assert "outside the attendance area" in res.json()["detail"]
    assert res.json()["code"] == "outside_zone"
    # Rejected scans must not leave orphaned selfies on disk.
    assert list(tmp_selfie_storage.glob("*")) == []


def test_scan_wrong_token(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], "deadbeef")
    assert res.status_code == 400
    assert "isn't valid for this class" in res.json()["detail"]
    assert list(tmp_selfie_storage.glob("*")) == []


def test_scan_expired_qr(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    row = db_session.get(AttendanceSession, session["id"])
    row.expires_at = datetime.now() - timedelta(seconds=1)
    db_session.commit()

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], row.qr_token)
    assert res.status_code == 400
    assert res.json()["code"] == "qr_expired"


def test_scan_missing_selfie_rejected(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], token, selfie=None)
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], str)


def test_scan_invalid_selfie_type(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], token, selfie=b"not an image", selfie_type="text/plain")
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_selfie"


def test_scan_oversized_selfie(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    huge = PNG + b"\x00" * (2 * 1024 * 1024)
    res = scan(client, stu_h, session["id"], token, selfie=huge)
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_selfie"


def test_scan_fake_image_content_type(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    fake = b"plain text pretending to be a photo"
    res = scan(client, stu_h, session["id"], token, selfie=fake, selfie_type="image/png")
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_selfie"


def test_scan_missing_gps_rejected(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    data = {"session_id": str(session["id"]), "qr_token": token}
    files = {"selfie": ("selfie.png", PNG, "image/png")}
    res = client.post("/api/student/attendance/scan", data=data, files=files, headers=stu_h)
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], str)
    assert res.json()["code"] == "invalid_input"


def test_scan_invalid_token(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    res = scan(client, {"Authorization": "Bearer not-a-real-token"}, session["id"], token)
    assert res.status_code == 401


def test_admin_can_view_selfie(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    scan(client, stu_h, session["id"], token)

    record_id = db_session.execute(
        select(AttendanceRecord.id).where(AttendanceRecord.session_id == session["id"])
    ).scalar_one()
    res = client.get(f"/api/admin/selfie/{record_id}", headers=admin_h)
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"

    # Students must not be able to view selfies.
    blocked = client.get(f"/api/admin/selfie/{record_id}", headers=stu_h)
    assert blocked.status_code == 403


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
