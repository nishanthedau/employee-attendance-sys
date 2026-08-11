"""Phase 6: admin audit cockpit — records with enrichment/anomalies, attempts, activity."""

import base64
from datetime import date

from app.models.entities import Role
from app.services.auth_service import create_user

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _auth(client, db_session, email, role=Role.admin):
    create_user(db_session, "Someone", email, "secret123", role)
    login = client.post("/api/auth/login", json={"email": email, "password": "secret123"}).json()
    return {"Authorization": f"Bearer {login['token']}"}


def _session(client, headers):
    return client.post(
        "/api/admin/attendance/create",
        headers=headers,
        json={
            "subject": "DBMS",
            "faculty": "Prof. Rao",
            "date": date.today().isoformat(),
            "start_time": "00:00:00",
            "end_time": "23:59:00",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "radius_meters": 75,
            "qr_expiry_minutes": 3,
        },
    ).json()


def _scan(client, headers, session_id, token, lat=28.6139, lng=77.2090, ua=None):
    data = {"session_id": str(session_id), "qr_token": token, "latitude": str(lat), "longitude": str(lng)}
    files = {"selfie": ("s.png", PNG, "image/png")}
    kw = {"headers": {**headers, **({"User-Agent": ua} if ua else {})}}
    return client.post("/api/student/attendance/scan", data=data, files=files, **kw)


def test_audit_records_lists_enrichment(client, db_session, tmp_selfie_storage):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    session = _session(client, ah)
    from app.models.entities import AttendanceSession

    token = db_session.get(AttendanceSession, session["id"]).qr_token
    ua = "Mozilla/5.0 (Linux; Android 14) Chrome/126.0.0.0 Mobile Safari/537.36"
    assert _scan(client, sh, session["id"], token, ua=ua).status_code == 200

    res = client.get("/api/admin/audit/records", headers=ah)
    assert res.status_code == 200
    rows = res.json()
    assert rows and rows[0]["employee"]["name"] == "Someone"
    assert rows[0]["session"]["subject"] == "DBMS"
    assert rows[0]["os"]  # parsed from test UA
    assert rows[0]["anomaly_score"] == 0
    assert rows[0]["reviewed"] is False
    assert rows[0]["verification_method_used"] == "none"


def test_audit_records_filter_unreviewed_and_min_anomaly(client, db_session, tmp_selfie_storage):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    session = _session(client, ah)
    from app.models.entities import AttendanceSession

    token = db_session.get(AttendanceSession, session["id"]).qr_token
    assert _scan(client, sh, session["id"], token).status_code == 200

    rows = client.get("/api/admin/audit/records?unreviewed_only=true", headers=ah).json()
    assert len(rows) == 1
    rows = client.get("/api/admin/audit/records?min_anomaly=1", headers=ah).json()
    assert rows == []


def test_review_record(client, db_session, tmp_selfie_storage):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    session = _session(client, ah)
    from app.models.entities import AttendanceSession

    token = db_session.get(AttendanceSession, session["id"]).qr_token
    assert _scan(client, sh, session["id"], token).status_code == 200
    record_id = client.get("/api/admin/audit/records", headers=ah).json()[0]["id"]

    res = client.post(f"/api/admin/audit/records/{record_id}/review", headers=ah)
    assert res.status_code == 200
    assert res.json()["reviewed"] is True
    rows = client.get("/api/admin/audit/records?unreviewed_only=true", headers=ah).json()
    assert rows == []


def test_audit_attempts_captures_rejections(client, db_session, tmp_selfie_storage):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    session = _session(client, ah)
    from app.models.entities import AttendanceSession

    token = db_session.get(AttendanceSession, session["id"]).qr_token
    far = 28.6139 + 0.01
    assert _scan(client, sh, session["id"], token, lat=far).status_code == 400
    assert _scan(client, sh, session["id"], token).status_code == 200

    rows = client.get("/api/admin/audit/attempts", headers=ah).json()
    reasons = {r["fail_reason"] for r in rows}
    assert "outside_zone" in reasons
    assert any(r["outcome"] == "success" for r in rows)


def test_audit_log_returns_actions(client, db_session):
    ah = _auth(client, db_session, "admin@a.com")
    session = _session(client, ah)
    rows = client.get("/api/admin/audit/log", headers=ah).json()
    assert any(r["action"] == "session_created" and r["entity_id"] == session["id"] for r in rows)


def test_audit_requires_admin(client, db_session):
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    res = client.get("/api/admin/audit/records", headers=sh)
    assert res.status_code == 403


def test_geofence_live_returns_sessions_scans_rejections(client, db_session, tmp_selfie_storage):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    session = _session(client, ah)
    from app.models.entities import AttendanceSession

    token = db_session.get(AttendanceSession, session["id"]).qr_token
    far = 28.6139 + 0.01
    assert _scan(client, sh, session["id"], token, lat=far).status_code == 400
    assert _scan(client, sh, session["id"], token).status_code == 200

    data = client.get("/api/admin/geofence/live", headers=ah).json()
    assert data["sessions"]
    assert data["sessions"][0]["id"] == session["id"]
    assert data["sessions"][0]["radius_meters"] == 75
    assert data["scans"] and data["scans"][0]["employee"] == "Someone"
    assert data["scans"][0]["anomaly_score"] == 0
    assert data["rejections"] and data["rejections"][0]["reason"] == "outside_zone"


def test_geofence_live_requires_admin(client, db_session):
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    assert client.get("/api/admin/geofence/live", headers=sh).status_code == 403


# ---------- Phase 8b: audit-log coverage per action ----------


def _log(client, ah):
    return client.get("/api/admin/audit/log", headers=ah).json()


def test_audit_log_settings_updated(client, db_session):
    ah = _auth(client, db_session, "admin@a.com")
    client.put(
        "/api/admin/settings",
        headers=ah,
        json={"verification_mode": "code", "default_radius_meters": 120},
    )
    assert any(e["action"] == "settings_updated" for e in _log(client, ah))


def test_audit_log_code_assigned_and_reassigned(client, db_session):
    ah = _auth(client, db_session, "admin@a.com")
    from app.models.entities import User

    _auth(client, db_session, "stu@a.com", Role.student)
    student = db_session.query(User).filter(User.email == "stu@a.com").one()
    client.put(f"/api/admin/students/{student.id}/code", headers=ah, json={"code": "1111"})
    client.put(f"/api/admin/students/{student.id}/code", headers=ah, json={"code": "2222"})
    entries = [e for e in _log(client, ah) if e["action"] == "code_assigned"]
    assert len(entries) == 2
    assert entries[0]["entity_id"] == student.id
    assert entries[0]["details"]["reassigned"] is True  # newest first: regeneration
    assert entries[1]["details"]["reassigned"] is False  # first assignment


def test_audit_log_code_viewed(client, db_session):
    ah = _auth(client, db_session, "admin@a.com")
    from app.models.entities import User

    _auth(client, db_session, "stu@a.com", Role.student)
    student = db_session.query(User).filter(User.email == "stu@a.com").one()
    client.put(f"/api/admin/students/{student.id}/code", headers=ah, json={"code": "1111"})
    client.get(f"/api/admin/students/{student.id}/code", headers=ah)
    assert any(e["action"] == "code_viewed" for e in _log(client, ah))


def test_audit_log_device_revoked(client, db_session):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    bound = client.post("/api/auth/device", headers=sh, json={"device_name": "iPhone"}).json()
    client.delete(f"/api/admin/devices/{bound['device_id']}", headers=ah)
    entries = [e for e in _log(client, ah) if e["action"] == "device_revoked"]
    assert len(entries) == 1
    assert entries[0]["entity_id"] == bound["device_id"]


def test_audit_log_record_reviewed(client, db_session, tmp_selfie_storage):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    session = _session(client, ah)
    from app.models.entities import AttendanceSession

    token = db_session.get(AttendanceSession, session["id"]).qr_token
    assert _scan(client, sh, session["id"], token).status_code == 200
    record_id = client.get("/api/admin/audit/records", headers=ah).json()[0]["id"]
    client.post(f"/api/admin/audit/records/{record_id}/review", headers=ah)
    entries = [e for e in _log(client, ah) if e["action"] == "record_reviewed"]
    assert len(entries) == 1
    assert entries[0]["entity_id"] == record_id


def test_audit_log_selfie_viewed(client, db_session, tmp_selfie_storage):
    ah = _auth(client, db_session, "admin@a.com")
    sh = _auth(client, db_session, "stu@a.com", Role.student)
    session = _session(client, ah)
    from app.models.entities import AttendanceSession

    token = db_session.get(AttendanceSession, session["id"]).qr_token
    assert _scan(client, sh, session["id"], token).status_code == 200
    record_id = client.get("/api/admin/audit/records", headers=ah).json()[0]["id"]
    client.get(f"/api/admin/selfie/{record_id}", headers=ah)
    entries = [e for e in _log(client, ah) if e["action"] == "selfie_viewed"]
    assert len(entries) == 1
    assert entries[0]["entity_id"] == record_id
