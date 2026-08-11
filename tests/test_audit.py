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
