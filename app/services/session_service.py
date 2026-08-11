"""Attendance session lifecycle: create, validate, QR payload, scan checks."""

import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hmac import compare_digest

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import now
from app.models.entities import (
    AttendanceAttempt,
    AttendanceRecord,
    AttendanceSession,
    User,
    VerificationMode,
)
from app.services.code_service import decrypt_code
from app.services.geo_service import is_within_radius
from app.services.settings_service import get_org_settings


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


def markable_state(session: AttendanceSession, when: datetime) -> tuple[bool, datetime]:
    """Whether a session is markable right now (window active + QR not expired),
    and the effective deadline = whichever comes first: QR expiry or the end of
    the session window. A QR must never appear live after the class window."""
    end = datetime.combine(session.date, session.end_time)
    deadline = min(session.expires_at, end)
    return is_session_active(session, when) and session.expires_at > when, deadline


def validate_scan(
    db: Session,
    session_id: int,
    qr_token: str,
    student: User,
    lat: float,
    lng: float,
    now: datetime | None = None,
) -> AttendanceSession:
    """Run all inexpensive attendance checks *before* any selfie is persisted.

    Order: QR exists/token matches → session active window → QR not expired →
    no duplicate → GPS within radius. Returns the validated session on success,
    raises ``SessionError`` otherwise.
    """
    now = now or datetime.now()

    session = db.get(AttendanceSession, session_id)
    if not session or not secrets.compare_digest(session.qr_token, qr_token):
        raise SessionError("This QR code isn't valid for this class.", code="invalid_qr")

    return validate_live_session(db, session, student, lat, lng, now)


def validate_live_session(
    db: Session,
    session: AttendanceSession,
    student: User,
    lat: float,
    lng: float,
    now: datetime,
) -> AttendanceSession:
    """Shared eligibility checks for QR scans *and* selfie-only marking:
    session active window → not expired → no duplicate → GPS within radius.
    Returns the validated session on success, raises ``SessionError`` otherwise.
    """
    if not is_session_active(session, now):
        raise SessionError(
            "This session isn't open right now. Try again during the class time.",
            code="session_not_active",
        )
    if session.expires_at < now:
        raise SessionError(
            "This session is no longer open. Ask your teacher for a fresh one.", code="qr_expired"
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

    # GPS is soft: missing location is silently skipped (no error, per v2 rule);
    # present-but-outside the radius is a hard block.
    if (
        lat is not None
        and lng is not None
        and not is_within_radius(lat, lng, session.latitude, session.longitude, session.radius_meters)
    ):
        raise SessionError(
            "You're outside the attendance area. Move closer to the class and try again.",
            code="outside_zone",
        )

    return session


def live_sessions(db: Session, when: datetime | None = None) -> list[AttendanceSession]:
    """Currently markable sessions (inside the active window and not expired),
    newest first — used by the selfie-only flow where there is no QR token."""
    when = when or datetime.now()
    rows = db.execute(
        select(AttendanceSession)
        .where(AttendanceSession.date == when.date(), AttendanceSession.expires_at > when)
        .order_by(AttendanceSession.start_time)
    ).scalars().all()
    return [s for s in rows if is_session_active(s, when)]


def record_scan(
    db: Session,
    session: AttendanceSession,
    student: User,
    lat: float,
    lng: float,
    selfie_path: str | None = None,
    now: datetime | None = None,
    *,
    method: str | None = None,
    verification_method_used: str | None = None,
    code_verified: bool | None = None,
    device_id: int | None = None,
) -> AttendanceRecord:
    """Persist an already-validated scan. The unique (student, session)
    constraint is the race-condition backstop for concurrent duplicate scans."""
    now = now or datetime.now()
    record = AttendanceRecord(
        student_id=student.id,
        session_id=session.id,
        device_id=device_id,
        scan_time=now,
        latitude=lat,
        longitude=lng,
        selfie_path=selfie_path,
        status="present",
        method=method,
        verification_method_used=verification_method_used,
        code_verified=code_verified,
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


def org_verification_mode(db: Session) -> VerificationMode:
    return get_org_settings(db).verification_mode


def verify_stored_code(db: Session, student: User, provided_code: str) -> bool:
    """Check a submitted verification code against the employee's assigned code."""
    if not student.verification_code:
        raise SessionError(
            "No code has been assigned to you yet. Ask the admin for your code.",
            code="no_code_assigned",
        )
    try:
        stored = decrypt_code(student.verification_code)
    except ValueError:
        raise SessionError(
            "Your code couldn't be verified. Ask the admin to reassign it.", code="wrong_code"
        ) from None
    if not provided_code or not compare_digest(stored, provided_code):
        raise SessionError("That code isn't right. Please check and try again.", code="wrong_code")
    return True


def check_verification(
    db: Session,
    student: User,
    *,
    has_selfie: bool,
    provided_code: str | None,
) -> tuple[str, bool | None]:
    """Enforce the org's verification mode.

    Returns (verification_method_used, code_verified) where code_verified is
    None when no code was required. Missing required selfie/code raises a
    SessionError; wrong codes raise a SessionError too.
    """
    mode = org_verification_mode(db)
    if mode in (VerificationMode.selfie, VerificationMode.both) and not has_selfie:
        raise SessionError(
            "This class asks for a quick selfie too. Tap to add one and try again.",
            code="selfie_required",
        )
    code_verified = None
    if mode in (VerificationMode.code, VerificationMode.both):
        if not provided_code:
            raise SessionError(
                "This class needs your personal code. Enter it and try again.",
                code="code_required",
            )
        verify_stored_code(db, student, provided_code)
        code_verified = True
    return mode.value, code_verified


def record_attempt(
    db: Session,
    *,
    student_id: int,
    outcome: str,
    session_id: int | None = None,
    device_id: int | None = None,
    fail_reason: str | None = None,
    method: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    ip: str | None = None,
    server_timestamps: dict | None = None,
) -> AttendanceAttempt:
    """Persist one attempt (success or failure) for the audit trail."""
    attempt = AttendanceAttempt(
        student_id=student_id,
        session_id=session_id,
        device_id=device_id,
        attempted_at=now(),
        outcome=outcome,
        fail_reason=fail_reason,
        method=method,
        latitude=lat,
        longitude=lng,
        ip=ip,
        server_timestamps=server_timestamps,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def scan_attendance(
    db: Session,
    session_id: int,
    qr_token: str,
    student: User,
    lat: float,
    lng: float,
    now: datetime | None = None,
    selfie_path: str | None = None,
) -> AttendanceRecord:
    """Validate then record a scan in one call (used by tests and simple flows).
    Production uses ``validate_scan`` + selfie save + ``record_scan`` so the
    selfie is only written after all checks pass."""
    session = validate_scan(db, session_id, qr_token, student, lat, lng, now)
    return record_scan(db, session, student, lat, lng, selfie_path, now)
