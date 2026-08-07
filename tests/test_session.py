from datetime import date, datetime, time, timedelta

import pytest

from app.models.entities import Role
from app.services.auth_service import create_user
from app.services.session_service import (
    CreateSessionData,
    SessionError,
    scan_attendance,
    validate_and_create,
)

LAT, LNG, RADIUS = 28.6139, 77.2090, 75


def make_users(db):
    admin = create_user(db, "Admin", "admin@campus.edu", "secret123", Role.admin)
    student = create_user(db, "Student", "stu@campus.edu", "secret123", Role.student)
    return admin, student


def session_data(**overrides):
    base = {
        "subject": "Operating Systems",
        "faculty": "Dr. Mehta",
        "session_date": date.today(),
        "start_time": time(0, 0),
        "end_time": time(23, 59),
        "latitude": LAT,
        "longitude": LNG,
        "radius_meters": RADIUS,
        "qr_expiry_minutes": 3,
    }
    base.update(overrides)
    return CreateSessionData(**base)


@pytest.fixture
def seeded(db_session):
    return make_users(db_session)


def test_create_session_success(db_session, seeded):
    admin, _ = seeded
    session = validate_and_create(db_session, session_data(), admin)
    assert session.qr_token and len(session.qr_token) == 64
    assert session.expires_at > datetime.now()
    assert session.created_by == admin.id


def test_fresh_qr_always_scannable(db_session, seeded):
    admin, _ = seeded
    # Session window already started (00:00 today); the freshly created QR must
    # still be valid for its full duration instead of expiring at 00:03.
    session = validate_and_create(
        db_session, session_data(start_time=time(0, 0), qr_expiry_minutes=3), admin
    )
    remaining = session.expires_at - datetime.now()
    assert timedelta(minutes=2) < remaining <= timedelta(minutes=4)


@pytest.mark.parametrize(
    "override",
    [
        {"session_date": date(2020, 1, 1)},
        {"start_time": time(23, 0), "end_time": time(9, 0)},
        {"latitude": 91.0},
        {"longitude": -181.0},
        {"radius_meters": 0},
        {"qr_expiry_minutes": 0},
    ],
)
def test_create_session_validation_errors(db_session, seeded, override):
    admin, _ = seeded
    with pytest.raises(SessionError):
        validate_and_create(db_session, session_data(**override), admin)


def test_create_session_subject_blank(db_session, seeded):
    admin, _ = seeded
    with pytest.raises(SessionError):
        validate_and_create(db_session, session_data(subject="   "), admin)


def test_scan_success(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(db_session, session_data(), admin)
    record = scan_attendance(db_session, session.id, session.qr_token, student, LAT, LNG)
    assert record.status == "present"
    assert record.student_id == student.id
    assert record.selfie_path is None


def test_scan_stores_selfie_path(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(db_session, session_data(), admin)
    record = scan_attendance(
        db_session, session.id, session.qr_token, student, LAT, LNG, selfie_path="photo.jpg"
    )
    assert record.selfie_path == "photo.jpg"


def test_scan_wrong_qr_token(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(db_session, session_data(), admin)
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, session.id, "wrong", student, LAT, LNG)
    assert exc.value.status_code == 400
    assert "isn't valid for this class" in exc.value.message
    assert exc.value.code == "invalid_qr"


def test_scan_unknown_session(db_session, seeded):
    _, student = seeded
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, 99999, "abc", student, LAT, LNG)
    assert exc.value.status_code == 400


def test_scan_expired_qr(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(db_session, session_data(), admin)
    session.expires_at = datetime.now() - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, session.id, session.qr_token, student, LAT, LNG)
    assert "expired" in exc.value.message


def test_scan_session_not_active(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(
        db_session,
        session_data(start_time=time(1, 0), end_time=time(2, 0)),
        admin,
    )
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, session.id, session.qr_token, student, LAT, LNG)
    assert exc.value.status_code == 400
    assert "isn't open right now" in exc.value.message
    assert exc.value.code == "session_not_active"


def test_scan_duplicate(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(db_session, session_data(), admin)
    scan_attendance(db_session, session.id, session.qr_token, student, LAT, LNG)
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, session.id, session.qr_token, student, LAT, LNG)
    assert exc.value.status_code == 409
    assert "already marked" in exc.value.message


def test_scan_outside_zone(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(db_session, session_data(), admin)
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, session.id, session.qr_token, student, LAT + 0.01, LNG)
    assert exc.value.status_code == 400
    assert "outside the attendance area" in exc.value.message
    assert exc.value.code == "outside_zone"


def test_scan_injects_now(db_session, seeded):
    admin, student = seeded
    # A session scheduled tomorrow is inactive today but its QR isn't expired.
    session = validate_and_create(
        db_session,
        session_data(session_date=date.today() + timedelta(days=1)),
        admin,
    )
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, session.id, session.qr_token, student, LAT, LNG)
    assert exc.value.status_code == 400
    assert "isn't open right now" in exc.value.message
