"""Attendance session lifecycle: create, validate, QR payload, scan checks."""

import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import now
from app.models.entities import AttendanceRecord, AttendanceSession, User
from app.services.geo_service import is_within_radius


class SessionError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "session_error"):
        self.message = message
        self.status_code = status_code
        self.code = code


@dataclass
class CreateSessionData:
    subject: str
    faculty: str
    session_date: date
    start_time: time
    end_time: time
    latitude: float
    longitude: float
    radius_meters: int
    qr_expiry_minutes: int


def validate_and_create(db: Session, data: CreateSessionData, admin: User) -> AttendanceSession:
    if not data.subject.strip() or not data.faculty.strip():
        raise SessionError("Please provide a subject and faculty name.", code="invalid_session_data")
    if data.session_date < date.today():
        raise SessionError("Session date can't be in the past.", code="invalid_session_data")
    if data.start_time >= data.end_time:
        raise SessionError("Start time must be before end time.", code="invalid_session_data")
    if not (-90 <= data.latitude <= 90) or not (-180 <= data.longitude <= 180):
        raise SessionError("Please enter valid coordinates.", code="invalid_session_data")
    if data.radius_meters <= 0:
        raise SessionError("Radius must be more than 0 meters.", code="invalid_session_data")
    if data.qr_expiry_minutes <= 0:
        raise SessionError("QR validity must be at least 1 minute.", code="invalid_session_data")

    session_start = datetime.combine(data.session_date, data.start_time)
    base_expiry = session_start + timedelta(minutes=data.qr_expiry_minutes)
    # A freshly created QR must always be scannable for its full duration,
    # even if the admin creates it after the session window began.
    now_ts = now()
    expiry = base_expiry if base_expiry > now_ts else now_ts + timedelta(minutes=data.qr_expiry_minutes)
    session = AttendanceSession(
        subject=data.subject.strip(),
        faculty=data.faculty.strip(),
        date=data.session_date,
        start_time=data.start_time,
        end_time=data.end_time,
        latitude=data.latitude,
        longitude=data.longitude,
        radius_meters=data.radius_meters,
        qr_token=secrets.token_hex(32),
        expires_at=expiry,
        created_by=admin.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def is_session_active(session: AttendanceSession, now: datetime) -> bool:
    start = datetime.combine(session.date, session.start_time)
    end = datetime.combine(session.date, session.end_time)
    return start <= now <= end


def scan_attendance(
    db: Session,
    session_id: int,
    qr_token: str,
    student: User,
    lat: float,
    lng: float,
    now: datetime | None = None,
) -> AttendanceRecord:
    """Validate and record a student scan. Checks, in order:
    QR exists/token matches, QR not expired, session active, no duplicate, GPS within radius."""
    now = now or datetime.now()

    session = db.get(AttendanceSession, session_id)
    if not session or not secrets.compare_digest(session.qr_token, qr_token):
        raise SessionError("This QR code isn't valid for this class.", code="invalid_qr")
    if session.expires_at < now:
        raise SessionError("This QR code has expired. Ask your teacher for a fresh one.", code="qr_expired")
    if not is_session_active(session, now):
        raise SessionError(
            "This session isn't open right now. Try again during the class time.",
            code="session_not_active",
        )

    existing = db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.student_id == student.id,
            AttendanceRecord.session_id == session.id,
        )
    ).scalar_one_or_none()
    if existing:
        raise SessionError(
            "You've already marked attendance for this session.", status_code=409, code="already_marked"
        )

    if not is_within_radius(lat, lng, session.latitude, session.longitude, session.radius_meters):
        raise SessionError(
            "You're outside the attendance area. Move closer to the class and try again.",
            code="outside_zone",
        )

    record = AttendanceRecord(
        student_id=student.id,
        session_id=session.id,
        scan_time=now,
        latitude=lat,
        longitude=lng,
        status="present",
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Race-condition backstop: two concurrent scans for the same student+session.
        db.rollback()
        raise SessionError(
            "You've already marked attendance for this session.", status_code=409, code="already_marked"
        ) from None
    db.refresh(record)
    return record
