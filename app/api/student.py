
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import (
    SCAN_LIMIT,
    enforce_rate_limit,
    get_current_user,
    get_request_device,
)
from app.core.storage import delete_selfie, save_selfie
from app.core.time import now
from app.db.database import get_db
from app.models.entities import AttendanceRecord, AttendanceSession, User
from app.services.analytics_service import current_week
from app.services.anomaly_service import assess
from app.services.geoip_service import enrich as geoip_enrich
from app.services.session_service import (
    SessionError,
    check_verification,
    live_sessions,
    org_verification_mode,
    record_attempt,
    record_scan,
    validate_live_session,
    validate_scan,
)

router = APIRouter(prefix="/api/student", tags=["student"])


def _finalize_record(
    db: Session,
    session: AttendanceSession,
    student: User,
    latitude: float | None,
    longitude: float | None,
    filename: str | None,
    start,
    *,
    method: str,
    verification_method_used: str,
    code_verified: bool | None,
    device,
    request: Request,
) -> AttendanceRecord:
    """Persist the record with GeoLite2 enrichment and anomaly scoring.

    Runs after all checks pass, so a rejected scan never writes a record. The
    anomaly score is informational only (the audit trail, reviewed by the admin).
    """
    client_ip = request.client.host if request.client else None
    geo = geoip_enrich(client_ip) if client_ip else {}
    anomaly_score, anomaly_flags = assess(
        db,
        student_id=student.id,
        session_lat=session.latitude,
        session_lng=session.longitude,
        radius_meters=session.radius_meters,
        scan_lat=latitude,
        scan_lng=longitude,
        scan_time=start,
        device_id=device.id if device else None,
        country=geo.get("country"),
    )
    return record_scan(
        db,
        session,
        student,
        latitude,
        longitude,
        filename,
        start,
        method=method,
        verification_method_used=verification_method_used,
        code_verified=code_verified,
        device_id=device.id if device else None,
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
        device=device,
        geo=geo,
        anomaly_score=anomaly_score,
        anomaly_flags=anomaly_flags,
    )


@router.get("/settings")
def student_settings(
    student: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """What the employee app must collect for this org (selfie/code/none)."""
    return {"verification_mode": org_verification_mode(db).value}


@router.get("/attendance/live-sessions")
def my_live_sessions(student: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sessions the student can currently mark via selfie-only mode (active
    window, not expired). The QR flow needs no list — the token points at the
    session directly."""
    return {
        "sessions": [
            {
                "id": s.id,
                "subject": s.subject,
                "faculty": s.faculty,
                "date": s.date.isoformat(),
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
            }
            for s in live_sessions(db)
        ]
    }


@router.post("/attendance/selfie")
def mark_by_selfie(
    session_id: int = Form(...),
    latitude: float | None = Form(default=None, ge=-90, le=90),
    longitude: float | None = Form(default=None, ge=-180, le=180),
    code: str | None = Form(default=None, max_length=16),
    selfie: UploadFile | None = File(default=None),
    request: Request = None,
    student: User = Depends(get_current_user),
    device=Depends(get_request_device),
    db: Session = Depends(get_db),
    _rate: None = Depends(enforce_rate_limit(SCAN_LIMIT)),
):
    """Mark attendance without a QR: the employee picks a currently-live session
    and confirms with a selfie and/or code per the org setting. All checks run
    before any photo is written to disk. Missing GPS is skipped, never fatal."""
    start = now()
    session = None
    try:
        session = db.get(AttendanceSession, session_id)
        if not session:
            raise SessionError(
                "This session isn't open right now. Try again during the class time.",
                code="session_not_active",
            )
        session = validate_live_session(db, session, student, latitude, longitude, start)
        verification_method_used, code_verified = check_verification(
            db, student, has_selfie=selfie is not None, provided_code=code
        )
    except SessionError as e:
        record_attempt(
            db,
            student_id=student.id,
            session_id=session.id if session else None,
            device_id=device.id if device else None,
            outcome="failure",
            fail_reason=e.code,
            method="selfie",
            lat=latitude,
            lng=longitude,
            ip=request.client.host if request.client else None,
            server_timestamps={"attempt_received": start.isoformat(), "rejected": now().isoformat()},
        )
        raise
    filename = save_selfie(selfie) if selfie else None
    try:
        record = _finalize_record(
            db,
            session,
            student,
            latitude,
            longitude,
            filename,
            start,
            method="selfie",
            verification_method_used=verification_method_used,
            code_verified=code_verified,
            device=device,
            request=request,
        )
    except Exception:
        if filename:
            delete_selfie(filename)
        raise
    record_attempt(
        db,
        student_id=student.id,
        session_id=session.id,
        device_id=device.id if device else None,
        outcome="success",
        method="selfie",
        lat=latitude,
        lng=longitude,
        ip=request.client.host if request.client else None,
        server_timestamps={"attempt_received": start.isoformat(), "success": now().isoformat()},
    )
    return {
        "ok": True,
        "message": "Attendance marked",
        "record": {
            "session_id": record.session_id,
            "scan_time": record.scan_time.isoformat(),
            "status": record.status,
            "selfie": record.selfie_path is not None,
        },
    }


@router.post("/attendance/scan")
def scan(
    session_id: int = Form(...),
    qr_token: str = Form(min_length=1, max_length=128),
    latitude: float | None = Form(default=None, ge=-90, le=90),
    longitude: float | None = Form(default=None, ge=-180, le=180),
    code: str | None = Form(default=None, max_length=16),
    selfie: UploadFile | None = File(default=None),
    request: Request = None,
    student: User = Depends(get_current_user),
    device=Depends(get_request_device),
    db: Session = Depends(get_db),
    _rate: None = Depends(enforce_rate_limit(SCAN_LIMIT)),
):
    """Mark attendance for the authenticated student.

    All cheap validations (QR token, session window, QR expiry, duplicate, GPS
    radius, verification selfie/code) run *before* the selfie is written to
    disk, so a rejected scan never leaves an orphaned photo. Identity comes from
    the bearer token, never from client input. GPS is optional: when present it
    is validated (hard block outside the radius); when absent it is skipped.
    """
    start = now()
    session = None
    try:
        session = validate_scan(db, session_id, qr_token, student, latitude, longitude, start)
        verification_method_used, code_verified = check_verification(
            db, student, has_selfie=selfie is not None, provided_code=code
        )
    except SessionError as e:
        record_attempt(
            db,
            student_id=student.id,
            session_id=session.id if session else None,
            device_id=device.id if device else None,
            outcome="failure",
            fail_reason=e.code,
            method="scan",
            lat=latitude,
            lng=longitude,
            ip=request.client.host if request.client else None,
            server_timestamps={"attempt_received": start.isoformat(), "rejected": now().isoformat()},
        )
        raise
    filename = save_selfie(selfie) if selfie else None
    try:
        record = _finalize_record(
            db,
            session,
            student,
            latitude,
            longitude,
            filename,
            start,
            method="scan",
            verification_method_used=verification_method_used,
            code_verified=code_verified,
            device=device,
            request=request,
        )
    except Exception:
        if filename:
            delete_selfie(filename)
        raise
    record_attempt(
        db,
        student_id=student.id,
        session_id=session.id,
        device_id=device.id if device else None,
        outcome="success",
        method="scan",
        lat=latitude,
        lng=longitude,
        ip=request.client.host if request.client else None,
        server_timestamps={"attempt_received": start.isoformat(), "success": now().isoformat()},
    )
    return {
        "ok": True,
        "message": "Attendance marked",
        "record": {
            "session_id": record.session_id,
            "scan_time": record.scan_time.isoformat(),
            "status": record.status,
            "selfie": record.selfie_path is not None,
        },
    }


@router.get("/attendance/current-week")
def my_week(student: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return current_week(db, student.id)
