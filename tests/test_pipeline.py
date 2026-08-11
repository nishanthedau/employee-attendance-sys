"""Phase 8a: end-to-end pipeline gaps — device metadata over HTTP, anomaly from a
bound device and from IP country, nonzero scores reaching the admin cockpit."""

import base64
from datetime import date

from app.models.entities import (
    AttendanceRecord,
    AttendanceSession,
    DeviceRegistration,
    Role,
    User,
)
from app.services.auth_service import create_user

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

CENTER_LAT, CENTER_LNG = 28.6139, 77.2090


def _user_headers(client, db_session, email, name, role):
    create_user(db_session, name, email, "secret123", role)
    login = client.post("/api/auth/login", json={"email": email, "password": "secret123"}).json()
    return {"Authorization": f"Bearer {login['token']}"}


def _admin(client, db_session):
    return _user_headers(client, db_session, "admin@x.com", "Admin", Role.admin)


def _student(client, db_session, email="stu@x.com", name="Stu"):
    return _user_headers(client, db_session, email, name, Role.student)


def _session(client, headers, radius=75, start="00:00:00", end="23:59:00"):
    return client.post(
        "/api/admin/attendance/create",
        headers=headers,
        json={
            "subject": "DBMS",
            "faculty": "Prof. Rao",
            "date": date.today().isoformat(),
            "start_time": start,
            "end_time": end,
            "latitude": CENTER_LAT,
            "longitude": CENTER_LNG,
            "radius_meters": radius,
            "qr_expiry_minutes": 3,
        },
    ).json()


def _token(db, session_id):
    return db.get(AttendanceSession, session_id).qr_token


def _bind(client, headers, **meta):
    payload = {
        "device_name": "Chrome on iPhone",
        "os": "iOS",
        "os_version": "17.2",
        "model": "iPhone 14",
        "screen": "390x844",
        "language": "en",
    }
    payload.update(meta)
    res = client.post("/api/auth/device", headers=headers, json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _scan(client, headers, session_id, token, lat=CENTER_LAT, lng=CENTER_LNG):
    data = {
        "session_id": str(session_id),
        "qr_token": token,
        "latitude": str(lat),
        "longitude": str(lng),
    }
    files = {"selfie": ("s.png", PNG, "image/png")}
    return client.post("/api/student/attendance/scan", data=data, files=files, headers=headers)


def _record_for(db, email):
    student = db.query(User).filter(User.email == email).one()
    return db.query(AttendanceRecord).filter(AttendanceRecord.student_id == student.id).all()


def test_http_device_bind_persists_metadata_and_owner(client, db_session):
    sh = _student(client, db_session)
    _bind(
        client,
        sh,
        device_name="Chrome on iPhone",
        os="iOS",
        os_version="17.2",
        model="iPhone 14",
        screen="390x844",
        language="en",
    )
    student = db_session.query(User).filter(User.email == "stu@x.com").one()
    rows = db_session.query(DeviceRegistration).filter(DeviceRegistration.user_id == student.id).all()
    assert len(rows) == 1
    dev = rows[0]
    assert dev.device_name == "Chrome on iPhone"
    assert dev.os == "iOS"
    assert dev.os_version == "17.2"
    assert dev.model == "iPhone 14"
    assert dev.screen == "390x844"
    assert dev.language == "en"
    assert dev.user_id == student.id
    assert dev.is_active is True


def test_http_scan_from_bound_device_flags_new_device_once(client, db_session):
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    bound = _bind(client, sh, device_name="Chrome on iPhone", os="iOS")
    device_headers = {"Authorization": f"Bearer {bound['device_token']}"}

    session1 = _session(client, ah)
    res1 = _scan(client, device_headers, session1["id"], _token(db_session, session1["id"]))
    assert res1.status_code == 200
    first = _record_for(db_session, "stu@x.com")[0]
    assert first.device_id == bound["device_id"]
    assert "new_device" in (first.anomaly_flags or {})

    session2 = _session(client, ah)
    res2 = _scan(client, device_headers, session2["id"], _token(db_session, session2["id"]))
    assert res2.status_code == 200
    records = _record_for(db_session, "stu@x.com")
    second = max(records, key=lambda r: r.id)
    assert "new_device" not in (second.anomaly_flags or {})


def test_http_country_change_flags_via_enrichment(client, db_session, monkeypatch):
    from app.api import student as student_api

    countries = iter(["India", "Singapore"])
    monkeypatch.setattr(
        student_api, "geoip_enrich", lambda ip: {"country": next(countries), "city": "X"}
    )

    ah = _admin(client, db_session)
    sh = _student(client, db_session)

    session1 = _session(client, ah)
    assert _scan(client, sh, session1["id"], _token(db_session, session1["id"])).status_code == 200

    session2 = _session(client, ah)
    res = _scan(client, sh, session2["id"], _token(db_session, session2["id"]))
    assert res.status_code == 200

    records = _record_for(db_session, "stu@x.com")
    latest = max(records, key=lambda r: r.id)
    assert latest.country == "Singapore"
    assert "ip_country_change" in (latest.anomaly_flags or {})
    assert latest.anomaly_score >= 30


def test_nonzero_anomaly_score_reaches_admin_cockpit(client, db_session, tmp_selfie_storage):
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah, radius=100)
    # ~89m from center (radius 100): inside but at the edge -> score 15.
    edge_lat = CENTER_LAT + 0.0008
    res = _scan(client, sh, session["id"], _token(db_session, session["id"]), lat=edge_lat)
    assert res.status_code == 200

    rows = client.get("/api/admin/audit/records", headers=ah).json()
    assert len(rows) == 1
    assert rows[0]["anomaly_score"] == 15
    assert "edge_of_radius" in rows[0]["anomaly_flags"]

    flagged = client.get("/api/admin/audit/records?min_anomaly=1", headers=ah).json()
    assert len(flagged) == 1
