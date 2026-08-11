"""Phase 3: configurable verification — profile codes, selfie/code modes, attempts."""

import base64
from datetime import date

from app.models.entities import (
    AttendanceAttempt,
    AttendanceRecord,
    AttendanceSession,
    OrgSettings,
    Role,
    User,
    VerificationMode,
)
from app.services.auth_service import create_user
from app.services.code_service import encrypt_code

LAT, LNG = 28.6139, 77.2090
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _admin_headers(client, db_session):
    create_user(db_session, "Admin", "admin@company.com", "secret123", Role.admin)
    login = client.post(
        "/api/auth/login", json={"email": "admin@company.com", "password": "secret123"}
    ).json()
    token = login["token"]
    return {"Authorization": f"Bearer {token}"}


def _student_headers(client, db_session, email="stu@company.com"):
    create_user(db_session, "Student", email, "secret123", Role.student)
    return _login_headers(client, email)


def _login_headers(client, email):
    login = client.post("/api/auth/login", json={"email": email, "password": "secret123"}).json()
    token = login["token"]
    return {"Authorization": f"Bearer {token}"}


def _make_coded_student(db_session, email="code@company.com", code="1111"):
    student = create_user(db_session, "Code User", email, "secret123", Role.student)
    student.verification_code = encrypt_code(code)
    db_session.commit()
    return student


def _create_session(client, headers):
    return client.post(
        "/api/admin/attendance/create",
        headers=headers,
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


def _set_mode(db_session, mode):
    settings = db_session.get(OrgSettings, 1) or OrgSettings(id=1)
    settings.verification_mode = mode
    db_session.add(settings)
    db_session.commit()


def _qr_token(db_session, session_id):
    return db_session.get(AttendanceSession, session_id).qr_token


def _scan(client, headers, session_id, token, code=None, selfie=True):
    data = {
        "session_id": str(session_id),
        "qr_token": token,
        "latitude": str(LAT),
        "longitude": str(LNG),
    }
    if code is not None:
        data["code"] = code
    files = {"selfie": ("s.png", PNG, "image/png")} if selfie else None
    return client.post("/api/student/attendance/scan", data=data, files=files, headers=headers)


def test_student_settings_reflects_org_mode(client, db_session):
    _set_mode(db_session, VerificationMode.both)
    headers = _student_headers(client, db_session)
    res = client.get("/api/student/settings", headers=headers)
    assert res.status_code == 200
    assert res.json()["verification_mode"] == "both"


def test_admin_can_read_and_update_settings(client, db_session):
    admin_h = _admin_headers(client, db_session)
    res = client.put(
        "/api/admin/settings",
        headers=admin_h,
        json={"verification_mode": "code", "default_radius_meters": 120},
    )
    assert res.status_code == 200
    assert res.json()["verification_mode"] == "code"
    assert res.json()["default_radius_meters"] == 120
    res = client.get("/api/admin/settings", headers=admin_h)
    assert res.json()["verification_mode"] == "code"


def test_admin_settings_rejects_bad_mode(client, db_session):
    admin_h = _admin_headers(client, db_session)
    res = client.put("/api/admin/settings", headers=admin_h, json={"verification_mode": "otp"})
    assert res.status_code == 422


def test_admin_assigns_and_views_code(client, db_session):
    admin_h = _admin_headers(client, db_session)
    _student_headers(client, db_session)
    student = db_session.query(User).filter(User.email == "stu@company.com").one()
    res = client.put(f"/api/admin/students/{student.id}/code", headers=admin_h, json={"code": "4521"})
    assert res.status_code == 200
    assert res.json()["code"] == "4521"
    res = client.get(f"/api/admin/students/{student.id}/code", headers=admin_h)
    assert res.status_code == 200
    assert res.json()["code"] == "4521"


def test_admin_auto_generates_code_when_blank(client, db_session):
    admin_h = _admin_headers(client, db_session)
    _student_headers(client, db_session)
    student = db_session.query(User).filter(User.email == "stu@company.com").one()
    res = client.put(f"/api/admin/students/{student.id}/code", headers=admin_h, json={})
    assert res.status_code == 200
    code = res.json()["code"]
    assert len(code) >= 4 and code.isdigit()


def test_admin_cannot_assign_code_to_admin(client, db_session):
    admin_h = _admin_headers(client, db_session)
    admin = db_session.query(User).filter(User.email == "admin@company.com").one()
    res = client.put(f"/api/admin/students/{admin.id}/code", headers=admin_h, json={"code": "1234"})
    assert res.status_code == 404


def test_scan_without_code_when_code_mode(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.code)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    student = _make_coded_student(db_session)
    headers = _login_headers(client, student.email)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, code=None, selfie=False)
    assert res.status_code == 400
    assert res.json()["code"] == "code_required"


def test_scan_wrong_code_rejected(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.code)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    student = _make_coded_student(db_session)
    headers = _login_headers(client, student.email)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, code="9999", selfie=False)
    assert res.status_code == 400
    assert res.json()["code"] == "wrong_code"


def test_scan_correct_code_success(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.code)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    student = _make_coded_student(db_session)
    headers = _login_headers(client, student.email)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, code="1111", selfie=False)
    assert res.status_code == 200
    record = db_session.query(AttendanceRecord).filter(AttendanceRecord.student_id == student.id).one()
    assert record.verification_method_used == "code"
    assert record.code_verified is True


def test_scan_no_code_assigned_yet(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.code)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    headers = _student_headers(client, db_session)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, code="1111", selfie=False)
    assert res.status_code == 400
    assert res.json()["code"] == "no_code_assigned"


def test_scan_missing_selfie_when_selfie_mode(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.selfie)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    headers = _student_headers(client, db_session)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, selfie=False)
    assert res.status_code == 400
    assert res.json()["code"] == "selfie_required"


def test_scan_mode_both_requires_selfie_and_code(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.both)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    student = _make_coded_student(db_session)
    headers = _login_headers(client, student.email)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, code=None, selfie=True)
    assert res.status_code == 400
    assert res.json()["code"] == "code_required"
    res = _scan(client, headers, session["id"], token, code="1111", selfie=True)
    assert res.status_code == 200
    record = db_session.query(AttendanceRecord).filter(AttendanceRecord.student_id == student.id).one()
    assert record.verification_method_used == "both"
    assert record.code_verified is True


def test_failed_attempt_is_recorded(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.code)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    student = _make_coded_student(db_session)
    headers = _login_headers(client, student.email)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, code="0000", selfie=False)
    assert res.status_code == 400
    attempts = db_session.query(AttendanceAttempt).filter(AttendanceAttempt.student_id == student.id).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "failure"
    assert attempts[0].fail_reason == "wrong_code"


def test_successful_attempt_is_recorded(client, db_session, tmp_selfie_storage):
    _set_mode(db_session, VerificationMode.code)
    admin_h = _admin_headers(client, db_session)
    session = _create_session(client, admin_h)
    student = _make_coded_student(db_session)
    headers = _login_headers(client, student.email)
    token = _qr_token(db_session, session["id"])
    res = _scan(client, headers, session["id"], token, code="1111", selfie=False)
    assert res.status_code == 200
    attempts = db_session.query(AttendanceAttempt).filter(AttendanceAttempt.student_id == student.id).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "success"
    assert attempts[0].fail_reason is None
