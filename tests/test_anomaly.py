"""Phase 5: anomaly detection — scoring + flags persisted on scans."""

import base64
import secrets
from datetime import date, datetime, time, timedelta

from app.models.entities import AttendanceRecord, AttendanceSession, Role, User
from app.services.anomaly_service import assess
from app.services.auth_service import create_user

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

CENTER_LAT, CENTER_LNG, RADIUS = 28.6139, 77.2090, 100


def _make_context(db, student):
    admin = (
        db.query(User).filter(User.email == "anom-admin@x.com").one_or_none()
        or create_user(db, "Admin", "anom-admin@x.com", "secret123", Role.admin)
    )
    session = AttendanceSession(
        subject="DBMS",
        faculty="Prof",
        date=date.today(),
        start_time=time(0, 0),
        end_time=time(23, 59),
        latitude=CENTER_LAT,
        longitude=CENTER_LNG,
        radius_meters=RADIUS,
        qr_token=secrets.token_hex(32),
        expires_at=datetime(2099, 1, 1),
        created_by=admin.id,
    )
    db.add(session)
    db.commit()
    return session


def _auth(client, db_session, email, name="X"):
    create_user(db_session, name, email, "secret123", Role.admin if email.startswith("a@") else Role.student)
    login = client.post("/api/auth/login", json={"email": email, "password": "secret123"}).json()
    return {"Authorization": f"Bearer {login['token']}"}


def _scan(client, headers, session_id, token, lat=CENTER_LAT, lng=CENTER_LNG):
    data = {
        "session_id": str(session_id),
        "qr_token": token,
        "latitude": str(lat),
        "longitude": str(lng),
    }
    files = {"selfie": ("s.png", PNG, "image/png")}
    return client.post("/api/student/attendance/scan", data=data, files=files, headers=headers)


def test_edge_of_radius_flagged(client, db_session, tmp_selfie_storage):
    _auth(client, db_session, "a@x.com")
    sh = _auth(client, db_session, "s@x.com")
    session = _make_context(db_session, None)
    token = db_session.get(AttendanceSession, session.id).qr_token
    # ~89m from center (radius 100m): inside but above the 85% edge threshold.
    edge_lat = CENTER_LAT + 0.0008
    res = _scan(client, sh, session.id, token, lat=edge_lat, lng=CENTER_LNG)
    assert res.status_code == 200

    student = db_session.query(User).filter(User.email == "s@x.com").one()
    record = db_session.query(AttendanceRecord).filter(AttendanceRecord.student_id == student.id).one()
    assert record.anomaly_score > 0
    assert "edge_of_radius" in (record.anomaly_flags or {})


def test_outside_radius_still_hard_blocked(client, db_session, tmp_selfie_storage):
    _auth(client, db_session, "a@x.com")
    sh = _auth(client, db_session, "s@x.com")
    session = _make_context(db_session, None)
    token = db_session.get(AttendanceSession, session.id).qr_token
    far = CENTER_LAT + 0.01
    res = _scan(client, sh, session.id, token, lat=far, lng=CENTER_LNG)
    assert res.status_code == 400
    assert res.json()["code"] == "outside_zone"


def test_reused_coordinates_flagged(client, db_session, tmp_selfie_storage):
    _auth(client, db_session, "a@x.com")
    sh = _auth(client, db_session, "s@x.com")

    session1 = _make_context(db_session, None)
    token1 = db_session.get(AttendanceSession, session1.id).qr_token
    assert _scan(client, sh, session1.id, token1, lat=28.6142, lng=77.2090).status_code == 200

    session2 = _make_context(db_session, None)
    token2 = db_session.get(AttendanceSession, session2.id).qr_token
    res = _scan(client, sh, session2.id, token2, lat=28.6142, lng=77.2090)
    assert res.status_code == 200

    student = db_session.query(User).filter(User.email == "s@x.com").one()
    records = db_session.query(AttendanceRecord).filter(AttendanceRecord.student_id == student.id).all()
    latest = max(records, key=lambda r: r.id)
    assert "reused_coordinates" in (latest.anomaly_flags or {})


def test_assess_implausible_speed(db_session):
    student = create_user(db_session, "Stu", "s@x.com", "secret123", Role.student)
    session = _make_context(db_session, student)
    t0 = datetime(2026, 8, 11, 10, 0, 0)
    # Previous scan ~33km away 2 minutes earlier -> ~990 km/h.
    db_session.add(
        AttendanceRecord(
            student_id=student.id,
            session_id=session.id,
            scan_time=t0 - timedelta(minutes=2),
            latitude=CENTER_LAT + 0.3,
            longitude=CENTER_LNG,
            status="present",
        )
    )
    db_session.commit()

    score, flags = assess(
        db_session,
        student_id=student.id,
        session_lat=CENTER_LAT,
        session_lng=CENTER_LNG,
        radius_meters=RADIUS,
        scan_lat=CENTER_LAT,
        scan_lng=CENTER_LNG,
        scan_time=t0,
        device_id=None,
        country=None,
    )
    assert score >= 40
    assert "implausible_speed" in flags


def test_assess_new_device(db_session):
    student = create_user(db_session, "Stu", "s@x.com", "secret123", Role.student)
    _make_context(db_session, student)
    score, flags = assess(
        db_session,
        student_id=student.id,
        session_lat=CENTER_LAT,
        session_lng=CENTER_LNG,
        radius_meters=RADIUS,
        scan_lat=CENTER_LAT,
        scan_lng=CENTER_LNG,
        scan_time=datetime(2026, 8, 11, 10, 0, 0),
        device_id=999,
        country=None,
    )
    assert score >= 10
    assert "new_device" in flags


def test_assess_country_change(db_session):
    student = create_user(db_session, "Stu", "s@x.com", "secret123", Role.student)
    session = _make_context(db_session, student)
    db_session.add(
        AttendanceRecord(
            student_id=student.id,
            session_id=session.id,
            scan_time=datetime(2026, 8, 10, 10, 0, 0),
            latitude=CENTER_LAT,
            longitude=CENTER_LNG,
            status="present",
            country="India",
        )
    )
    db_session.commit()

    score, flags = assess(
        db_session,
        student_id=student.id,
        session_lat=CENTER_LAT,
        session_lng=CENTER_LNG,
        radius_meters=RADIUS,
        scan_lat=CENTER_LAT,
        scan_lng=CENTER_LNG,
        scan_time=datetime(2026, 8, 11, 10, 0, 0),
        device_id=None,
        country="Singapore",
    )
    assert score >= 30
    assert "ip_country_change" in flags


def test_clean_scan_scores_zero(db_session):
    student = create_user(db_session, "Stu", "s@x.com", "secret123", Role.student)
    _make_context(db_session, student)
    score, flags = assess(
        db_session,
        student_id=student.id,
        session_lat=CENTER_LAT,
        session_lng=CENTER_LNG,
        radius_meters=RADIUS,
        scan_lat=CENTER_LAT,
        scan_lng=CENTER_LNG,
        scan_time=datetime(2026, 8, 11, 10, 0, 0),
        device_id=None,
        country=None,
    )
    assert score == 0
    assert flags == {}


def test_score_capped_at_100(db_session):
    student = create_user(db_session, "Stu", "s@x.com", "secret123", Role.student)
    session = _make_context(db_session, student)
    # First scan from device 999 (new) + country change to Singapore.
    db_session.add(
        AttendanceRecord(
            student_id=student.id,
            session_id=session.id,
            scan_time=datetime(2026, 8, 10, 10, 0, 0),
            latitude=CENTER_LAT,
            longitude=CENTER_LNG,
            status="present",
            country="India",
        )
    )
    db_session.commit()
    score, flags = assess(
        db_session,
        student_id=student.id,
        session_lat=CENTER_LAT,
        session_lng=CENTER_LNG,
        radius_meters=RADIUS,
        scan_lat=CENTER_LAT + 0.0009,
        scan_lng=CENTER_LNG,
        scan_time=datetime(2026, 8, 11, 10, 0, 0),
        device_id=999,
        country="Singapore",
    )
    assert score <= 100
    assert {"edge_of_radius", "new_device", "ip_country_change"} <= set(flags)
