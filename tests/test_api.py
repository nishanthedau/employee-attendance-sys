import base64
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models.entities import AttendanceRecord, AttendanceSession, Role, User
from app.services.auth_service import create_user
from app.services.qr_service import render_session_qr, session_payload

LAT, LNG = 28.6139, 77.2090

# A real 1x1 PNG so the server's magic-byte check passes.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def admin_token(client, db_session):
    create_user(db_session, "Admin", "admin@company.com", "secret123", Role.admin)
    res = client.post("/api/auth/login", json={"email": "admin@company.com", "password": "secret123"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def student_token(client, db_session, email="stu@company.com"):
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


# ---------- Selfie-only attendance (no QR) ----------

def selfie_scan(client, headers, session_id, lat=LAT, lng=LNG, selfie=PNG, selfie_type="image/png"):
    data = {"session_id": str(session_id), "latitude": str(lat), "longitude": str(lng)}
    files = {"selfie": ("selfie.png", selfie, selfie_type)} if selfie is not None else None
    return client.post("/api/student/attendance/selfie", data=data, files=files, headers=headers)


def test_selfie_only_success(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()

    stu_h = student_token(client, db_session)
    res = selfie_scan(client, stu_h, session["id"])
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["record"]["selfie"] is True
    assert len(list(tmp_selfie_storage.glob("*"))) == 1

    rec = db_session.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.student_id == student_id_from(client, db_session),
            AttendanceRecord.session_id == session["id"],
        )
    ).scalar_one_or_none()
    assert rec is not None and rec.status == "present"


def student_id_from(client, db_session):
    return db_session.execute(select(User.id).where(User.email == "stu@company.com")).scalar_one()


def test_selfie_only_duplicate_409(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    stu_h = student_token(client, db_session)

    assert selfie_scan(client, stu_h, session["id"]).status_code == 200
    dup = selfie_scan(client, stu_h, session["id"])
    assert dup.status_code == 409
    assert dup.json()["code"] == "already_marked"
    assert len(list(tmp_selfie_storage.glob("*"))) == 1


def test_selfie_only_outside_zone_no_orphan(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    stu_h = student_token(client, db_session)

    res = selfie_scan(client, stu_h, session["id"], lat=LAT + 0.01)
    assert res.status_code == 400
    assert res.json()["code"] == "outside_zone"
    assert list(tmp_selfie_storage.glob("*")) == []


def test_selfie_only_unknown_session(client, db_session, tmp_selfie_storage):
    stu_h = student_token(client, db_session)
    res = selfie_scan(client, stu_h, 99999)
    assert res.status_code == 400
    assert res.json()["code"] == "session_not_active"
    assert list(tmp_selfie_storage.glob("*")) == []


def test_selfie_only_ignores_class_window(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    row = db_session.get(AttendanceSession, session["id"])
    row.date = date.today() - timedelta(days=1)
    db_session.commit()

    stu_h = student_token(client, db_session)
    res = selfie_scan(client, stu_h, session["id"], selfie=PNG)
    assert res.status_code == 200
    assert len(list(tmp_selfie_storage.glob("*"))) == 1


def test_selfie_only_expired_session(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    row = db_session.get(AttendanceSession, session["id"])
    row.expires_at = datetime.now() - timedelta(seconds=1)
    db_session.commit()

    stu_h = student_token(client, db_session)
    res = selfie_scan(client, stu_h, session["id"])
    assert res.status_code == 400
    assert res.json()["code"] == "qr_expired"
    assert list(tmp_selfie_storage.glob("*")) == []


def test_live_sessions_endpoint(client, db_session):
    admin_h = admin_token(client, db_session)
    live = create_session(client, admin_h).json()
    expired = create_session(client, admin_h, subject="Networks").json()
    row = db_session.get(AttendanceSession, expired["id"])
    row.expires_at = datetime.now() - timedelta(seconds=1)
    db_session.commit()

    stu_h = student_token(client, db_session)
    data = client.get("/api/student/attendance/live-sessions", headers=stu_h).json()
    ids = {s["id"] for s in data["sessions"]}
    assert live["id"] in ids
    assert expired["id"] not in ids


def test_scan_without_selfie_succeeds_when_not_required(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], token, selfie=None)
    assert res.status_code == 200
    assert res.json()["record"]["selfie"] is False


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


def test_scan_without_gps_succeeds_when_absent(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    data = {"session_id": str(session["id"]), "qr_token": token}
    files = {"selfie": ("selfie.png", PNG, "image/png")}
    res = client.post("/api/student/attendance/scan", data=data, files=files, headers=stu_h)
    assert res.status_code == 200
    assert res.json()["record"]["status"] == "present"


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
        json={"name": "New Kid", "email": "newkid@company.com", "password": "secret123"},
        headers=headers,
    )
    assert created.status_code == 200
    new_id = created.json()["id"]

    listed = client.get("/api/admin/students?q=newkid", headers=headers)
    assert listed.status_code == 200
    assert any(s["id"] == new_id for s in listed.json())

    dup = client.post(
        "/api/admin/students",
        json={"name": "Dup", "email": "newkid@company.com", "password": "secret123"},
        headers=headers,
    )
    assert dup.status_code == 409

    assert client.delete(f"/api/admin/students/{new_id}", headers=headers).status_code == 200


def test_export_csv(client, db_session):
    headers = admin_token(client, db_session)
    res = client.get("/api/admin/export", headers=headers)
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "scan_time,employee,email" in res.text


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


# ---------- Rate limiting ----------

def test_login_rate_limited(client, db_session):
    for _ in range(10):
        res = client.post("/api/auth/login", json={"email": "x@y.z", "password": "bad"})
        assert res.status_code == 401
    res = client.post("/api/auth/login", json={"email": "x@y.z", "password": "bad"})
    assert res.status_code == 429
    assert res.json()["code"] == "error"


def test_scan_rate_limited(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    stu_h = student_token(client, db_session)
    for _ in range(30):
        client.post("/api/student/attendance/scan", data={
            "session_id": str(session["id"]), "qr_token": "bad", "latitude": str(LAT), "longitude": str(LNG),
        }, files={"selfie": ("s.png", PNG, "image/png")}, headers=stu_h)
    res = client.post("/api/student/attendance/scan", data={
        "session_id": str(session["id"]), "qr_token": "bad", "latitude": str(LAT), "longitude": str(LNG),
    }, files={"selfie": ("s.png", PNG, "image/png")}, headers=stu_h)
    assert res.status_code == 429


# ---------- Session creation validation via API ----------

def test_create_session_past_date_rejected(client, db_session):
    headers = admin_token(client, db_session)
    res = create_session(client, headers, date=(date.today() - timedelta(days=1)).isoformat())
    assert res.status_code == 400
    assert "past" in res.json()["detail"]


def test_create_session_end_before_start_rejected(client, db_session):
    headers = admin_token(client, db_session)
    res = create_session(client, headers, start_time="12:00:00", end_time="09:00:00")
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_input"


def test_create_session_invalid_radius_rejected(client, db_session):
    headers = admin_token(client, db_session)
    res = create_session(client, headers, radius_meters=0)
    assert res.status_code == 422


def test_create_session_blank_subject_rejected(client, db_session):
    headers = admin_token(client, db_session)
    res = create_session(client, headers, subject="   ")
    assert res.status_code == 422


# ---------- QR payload correctness ----------

def test_qr_payload_and_png(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    row = db_session.get(AttendanceSession, session["id"])
    assert session_payload(row) == {"session_id": row.id, "qr_token": row.qr_token}
    assert render_session_qr(row).startswith(b"\x89PNG\r\n\x1a\n")


# ---------- Scan edge cases ----------

def test_scan_unknown_session(client, db_session):
    admin_h = admin_token(client, db_session)
    create_session(client, admin_h)
    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, 999999, "whatever")
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_qr"


def test_scan_future_session_scannable_while_qr_valid(client, db_session):
    admin_h = admin_token(client, db_session)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    session = create_session(client, admin_h, date=tomorrow).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], token)
    assert res.status_code == 200


def test_scan_out_of_range_lat(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    token = session_qr_token(db_session, session["id"])

    stu_h = student_token(client, db_session)
    res = scan(client, stu_h, session["id"], token, lat=95.0)
    assert res.status_code == 422


def test_scan_empty_qr_token(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()

    stu_h = student_token(client, db_session)
    data = {"session_id": str(session["id"]), "qr_token": "", "latitude": str(LAT), "longitude": str(LNG)}
    res = client.post("/api/student/attendance/scan", data=data,
                      files={"selfie": ("s.png", PNG, "image/png")}, headers=stu_h)
    assert res.status_code == 422


# ---------- Selfie endpoint 404 paths ----------

def test_selfie_missing_record_404(client, db_session):
    headers = admin_token(client, db_session)
    assert client.get("/api/admin/selfie/999999", headers=headers).status_code == 404


def test_selfie_record_without_photo_404(client, db_session):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    student_token(client, db_session)
    student = db_session.execute(select(User).where(User.role == Role.student)).scalar_one()
    record = AttendanceRecord(
        student_id=student.id,
        session_id=session["id"],
        scan_time=datetime.now(),
        latitude=LAT,
        longitude=LNG,
        selfie_path=None,
        status="present",
    )
    db_session.add(record)
    db_session.commit()
    assert client.get(f"/api/admin/selfie/{record.id}", headers=admin_h).status_code == 404


def test_selfie_file_missing_on_disk_404(client, db_session, tmp_selfie_storage):
    admin_h = admin_token(client, db_session)
    session = create_session(client, admin_h).json()
    stu_h = student_token(client, db_session)
    scan(client, stu_h, session["id"], session_qr_token(db_session, session["id"]))
    record_id = db_session.execute(
        select(AttendanceRecord.id).where(AttendanceRecord.session_id == session["id"])
    ).scalar_one()
    for f in tmp_selfie_storage.glob("*"):
        f.unlink()
    assert client.get(f"/api/admin/selfie/{record_id}", headers=admin_h).status_code == 404


# ---------- Pagination & CSV filters ----------

def test_sessions_pagination(client, db_session):
    headers = admin_token(client, db_session)
    for subject in ("DBMS", "Networks", "AI"):
        create_session(client, headers, subject=subject)

    page1 = client.get("/api/admin/sessions?limit=2&offset=0", headers=headers).json()
    assert page1["total"] >= 3
    assert len(page1["sessions"]) == 2

    page2 = client.get("/api/admin/sessions?limit=2&offset=2", headers=headers).json()
    assert len(page2["sessions"]) == page1["total"] - 2
    ids1 = {s["id"] for s in page1["sessions"]}
    assert not (ids1 & {s["id"] for s in page2["sessions"]})


def test_export_csv_subject_filter(client, db_session):
    headers = admin_token(client, db_session)
    create_session(client, headers, subject="DBMS")
    networks = create_session(client, headers, subject="Networks").json()

    stu_h = student_token(client, db_session)
    scan(client, stu_h, networks["id"], session_qr_token(db_session, networks["id"]))

    filtered = client.get("/api/admin/export?subject=Networks", headers=headers)
    assert filtered.status_code == 200
    assert "Networks" in filtered.text
    assert "DBMS" not in filtered.text.split("scan_time")[1]


def test_export_csv_faculty_filter(client, db_session):
    headers = admin_token(client, db_session)
    create_session(client, headers, subject="DBMS", faculty="Prof. Rao")
    networks = create_session(client, headers, subject="Networks", faculty="Dr. Gupta").json()

    stu_h = student_token(client, db_session)
    scan(client, stu_h, networks["id"], session_qr_token(db_session, networks["id"]))

    filtered = client.get("/api/admin/export?faculty=Dr.%20Gupta", headers=headers)
    assert filtered.status_code == 200
    assert "Networks" in filtered.text
    assert "Prof. Rao" not in filtered.text


def test_export_csv_date_filter(client, db_session):
    headers = admin_token(client, db_session)
    today_sess = create_session(client, headers, date=date.today().isoformat()).json()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    later = create_session(client, headers, subject="Networks", date=tomorrow).json()

    stu_h = student_token(client, db_session)
    scan(client, stu_h, today_sess["id"], session_qr_token(db_session, today_sess["id"]))
    scan(client, stu_h, later["id"], session_qr_token(db_session, later["id"]))

    filtered = client.get(f"/api/admin/export?session_date={date.today().isoformat()}", headers=headers)
    assert filtered.status_code == 200
    assert "DBMS" in filtered.text
    assert "Networks" not in filtered.text.split("scan_time")[1]


def test_faculties_endpoint(client, db_session):
    headers = admin_token(client, db_session)
    create_session(client, headers, faculty="Prof. Rao")
    create_session(client, headers, subject="Networks", faculty="Dr. Gupta")

    data = client.get("/api/admin/faculties", headers=headers).json()
    assert "Prof. Rao" in data["faculties"]
    assert "Dr. Gupta" in data["faculties"]


def test_sessions_faculty_filter(client, db_session):
    headers = admin_token(client, db_session)
    create_session(client, headers, faculty="Prof. Rao")
    create_session(client, headers, subject="Networks", faculty="Dr. Gupta")

    data = client.get("/api/admin/sessions?faculty=Dr.%20Gupta", headers=headers).json()
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["faculty"] == "Dr. Gupta"
