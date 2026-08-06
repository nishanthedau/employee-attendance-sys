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


def test_scan_wrong_qr_token(db_session, seeded):
    admin, student = seeded
    session = validate_and_create(db_session, session_data(), admin)
    with pytest.raises(SessionError) as exc:
        scan_attendance(db_session, session.id, "wrong", student, LAT, LNG)
    assert exc.value.status_code == 400
    assert "Invalid QR" in exc.value.message


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
    assert "not currently active" in exc.value.message


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
    assert "Outside attendance zone" in exc.value.message


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
    assert "not currently active" in exc.value.message
