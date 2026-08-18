"""Anonymous employee check-in (no login): scan QR -> pick yourself -> status.

Identity is chosen from the admin-added roster, not a bearer token. The QR
token (issued by the admin per session) is the gate for resolving and marking.
GPS and the org's verification mode (selfie/code) are still enforced.
"""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SCAN_LIMIT, enforce_rate_limit
from app.core.storage import delete_selfie, save_selfie
from app.core.time import now
from app.db.database import get_db
from app.models.entities import AttendanceSession, Role, User
from app.services.anomaly_service import assess
from app.services.geoip_service import enrich as geoip_enrich
from app.services.session_service import (
    SessionError,
    check_verification,
    org_verification_mode,
    record_attempt,
    record_scan,
    resolve_session,
    validate_scan,
)

router = APIRouter(prefix="/api/employee", tags=["employee"])

ALLOWED_STATUSES = ("present", "late", "absent")


def _employee_or_404(db: Session, employee_id: int) -> User:
    employee = db.get(User, employee_id)
    if not employee or employee.role != Role.student:
        raise SessionError(
            "That employee doesn't exist anymore. Refresh the list and try again.",
            status_code=404,
            code="employee_not_found",
        )
    return employee


@router.get("/roster")
def roster(db: Session = Depends(get_db)):
    """Everyone an admin has added — the dropdown an employee picks from."""
    employees = db.execute(
        select(User).where(User.role == Role.student).order_by(User.name).limit(500)
    ).scalars().all()
    return {"employees": [{"id": u.id, "name": u.name} for u in employees]}


@router.post("/resolve")
def resolve(
    payload: dict,
    db: Session = Depends(get_db),
    _rate: None = Depends(enforce_rate_limit(SCAN_LIMIT)),
):
    """Turn a scanned QR into a class: validate the token + window, return what
    the employee needs to see and what verification the class requires."""
    session_id = payload.get("session_id")
    qr_token = payload.get("qr_token")
    if session_id is None or not isinstance(session_id, int):
        raise SessionError("That QR code isn't valid for this class.", code="invalid_qr")
    if not qr_token or not isinstance(qr_token, str):
        raise SessionError("That QR code isn't valid for this class.", code="invalid_qr")
    session = resolve_session(db, session_id, qr_token)
    return {
        "session": {
            "id": session.id,
            "subject": session.subject,
            "faculty": session.faculty,
            "date": session.date.isoformat(),
            "start_time": session.start_time.strftime("%H:%M"),
            "end_time": session.end_time.strftime("%H:%M"),
        },
        "verification_mode": org_verification_mode(db).value,
    }


@router.post("/attendance/mark")
def mark(
    session_id: int = Form(...),
    qr_token: str = Form(min_length=1, max_length=128),
    employee_id: int = Form(...),
    status: str = Form(default="present"),
    latitude: float | None = Form(default=None, ge=-90, le=90),
    longitude: float | None = Form(default=None, ge=-180, le=180),
    code: str | None = Form(default=None, max_length=16),
    selfie: UploadFile | None = File(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    _rate: None = Depends(enforce_rate_limit(SCAN_LIMIT)),
):
    """Register an anonymous check-in.

    Validates the QR, the class window, the chosen employee's duplicate, GPS
    radius and the org's verification mode before anything is written. GPS is
    optional when absent; outside the radius is a hard block.
    """
    if status not in ALLOWED_STATUSES:
        raise SessionError("Pick a status: present, late, or absent.", code="invalid_status")
    start = now()
    employee = _employee_or_404(db, employee_id)
    session: AttendanceSession | None = None
    try:
        session = validate_scan(db, session_id, qr_token, employee, latitude, longitude, start)
        verification_method_used, code_verified = check_verification(
            db, employee, has_selfie=selfie is not None, provided_code=code
        )
    except SessionError as e:
        record_attempt(
            db,
            student_id=employee_id,
            session_id=session.id if session else None,
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
    client_ip = request.client.host if request.client else None
    geo = geoip_enrich(client_ip) if client_ip else {}
    anomaly_score, anomaly_flags = assess(
        db,
        student_id=employee.id,
        session_lat=session.latitude,
        session_lng=session.longitude,
        radius_meters=session.radius_meters,
        scan_lat=latitude,
        scan_lng=longitude,
        scan_time=start,
        device_id=None,
        country=geo.get("country"),
    )
    try:
        record = record_scan(
            db,
            session,
            employee,
            latitude,
            longitude,
            filename,
            start,
            status=status,
            method="scan",
            verification_method_used=verification_method_used,
            code_verified=code_verified,
            device_id=None,
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent"),
            geo=geo,
            anomaly_score=anomaly_score,
            anomaly_flags=anomaly_flags,
        )
    except Exception:
        if filename:
            delete_selfie(filename)
        raise
    record_attempt(
        db,
        student_id=employee.id,
        session_id=session.id,
        outcome="success",
        method="scan",
        lat=latitude,
        lng=longitude,
        ip=client_ip,
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
