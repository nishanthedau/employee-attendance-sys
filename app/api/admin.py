import re
import secrets
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_admin
from app.api.schemas import (
    AssignCodeRequest,
    SessionCreateRequest,
    SettingsUpdateRequest,
    StudentCreateRequest,
)
from app.core.storage import selfie_path
from app.core.time import local_iso, now
from app.db.database import get_db
from app.models.entities import (
    AttendanceAttempt,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    DeviceRegistration,
    Role,
    User,
)
from app.services.analytics_service import dashboard_stats, export_csv, faculty_options, subject_options
from app.services.audit_service import log_action
from app.services.auth_service import create_user
from app.services.code_service import decrypt_code, encrypt_code
from app.services.qr_service import render_session_qr
from app.services.session_service import CreateSessionData, markable_state, validate_and_create
from app.services.settings_service import get_org_settings, update_org_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _session_dict(s: AttendanceSession) -> dict:
    live, deadline = markable_state(s, now())
    return {
        "id": s.id,
        "subject": s.subject,
        "faculty": s.faculty,
        "date": s.date.isoformat(),
        "start_time": s.start_time.strftime("%H:%M"),
        "end_time": s.end_time.strftime("%H:%M"),
        "latitude": s.latitude,
        "longitude": s.longitude,
        "radius_meters": s.radius_meters,
        "marked": len(s.records),
        "qr_expires_at": local_iso(s.expires_at),
        "live": live,
        "deadline": local_iso(deadline),
    }


@router.post("/attendance/create")
def create_session(
    payload: SessionCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    session = validate_and_create(
        db,
        CreateSessionData(
            subject=payload.subject,
            faculty=payload.faculty,
            session_date=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            latitude=payload.latitude,
            longitude=payload.longitude,
            radius_meters=payload.radius_meters,
            qr_expiry_minutes=payload.qr_expiry_minutes,
        ),
        admin,
    )
    log_action(
        db,
        admin,
        "session_created",
        entity_type="attendance_session",
        entity_id=session.id,
        details={
            "subject": session.subject,
            "date": session.date.isoformat(),
            "start_time": session.start_time.strftime("%H:%M"),
            "end_time": session.end_time.strftime("%H:%M"),
        },
        ip=request.client.host if request.client else None,
    )
    return _session_dict(session)


@router.get("/attendance/qr")
def get_qr(session_id: int = Query(...), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    session = db.get(AttendanceSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return Response(
        content=render_session_qr(session),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/selfie/{record_id}")
def get_selfie(
    record_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    record = db.get(AttendanceRecord, record_id)
    if not record or not record.selfie_path:
        raise HTTPException(status_code=404, detail="No selfie for this record.")
    path = selfie_path(record.selfie_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Selfie file is missing.")
    media_type = "image/png" if record.selfie_path.endswith(".png") else "image/jpeg"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.get("/dashboard")
def dashboard(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard_stats(db)


@router.get("/sessions")
def list_sessions(
    subject: str | None = Query(default=None),
    faculty: str | None = Query(default=None),
    session_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = select(AttendanceSession).options(selectinload(AttendanceSession.records))
    if subject:
        query = query.where(AttendanceSession.subject == subject)
    if faculty:
        query = query.where(AttendanceSession.faculty == faculty)
    if session_date:
        query = query.where(AttendanceSession.date == session_date)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    sessions = (
        db.execute(query.order_by(AttendanceSession.date.desc(), AttendanceSession.id.desc())
                   .limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sessions": [_session_dict(s) for s in sessions],
    }


@router.get("/subjects")
def subjects(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"subjects": subject_options(db)}


@router.get("/faculties")
def faculties(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"faculties": faculty_options(db)}


@router.get("/attendance/history")
def history(
    session_id: int = Query(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    session = db.get(AttendanceSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    records = db.execute(
        select(User, AttendanceRecord)
        .join(AttendanceRecord.student)
        .where(AttendanceRecord.session_id == session.id)
        .order_by(AttendanceRecord.scan_time)
    ).all()
    return {
        "session": {
            "id": session.id,
            "subject": session.subject,
            "faculty": session.faculty,
            "date": session.date.isoformat(),
        },
        "marked": len(records),
        "records": [
            {
                "id": r.id,
                "student_id": u.id,
                "student_name": u.name,
                "email": u.email,
                "scan_time": r.scan_time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": r.status,
                "has_selfie": bool(r.selfie_path),
            }
            for u, r in records
        ],
    }


@router.get("/students")
def list_students(
    q: str | None = Query(default=None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = select(User).where(User.role == Role.student)
    if q:
        query = query.where(User.name.like(f"%{q}%") | User.email.like(f"%{q}%"))
    students = db.execute(query.order_by(User.name).limit(200)).scalars().all()
    return [{"id": u.id, "name": u.name, "email": u.email} for u in students]


@router.post("/students")
def add_student(
    payload: StudentCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        user = create_user(db, payload.name, payload.email, payload.password, Role.student)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An employee with this email already exists.") from None
    return {"id": user.id, "name": user.name, "email": user.email}


@router.delete("/students/{student_id}")
def remove_student(student_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, student_id)
    if not user or user.role != Role.student:
        raise HTTPException(status_code=404, detail="Student not found.")
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.get("/export")
def export(
    subject: str | None = Query(default=None),
    faculty: str | None = Query(default=None),
    session_date: date | None = Query(default=None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    csv_data = export_csv(db, subject=subject, day=session_date, faculty=faculty)
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="attendance_export.csv"'},
    )


@router.get("/settings")
def org_settings(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    settings = get_org_settings(db)
    return {
        "verification_mode": settings.verification_mode.value,
        "default_radius_meters": settings.default_radius_meters,
        "selfie_retention_days": settings.selfie_retention_days,
        "sheets_enabled": settings.sheets_enabled,
    }


@router.put("/settings")
def update_settings(
    payload: SettingsUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    before = get_org_settings(db)
    fields = payload.model_dump(exclude_unset=True)
    try:
        updated = update_org_settings(db, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    log_action(
        db,
        admin,
        "settings_updated",
        entity_type="org_settings",
        entity_id=updated.id,
        details={
            "changed": fields,
            "before": {
                "verification_mode": before.verification_mode.value,
                "default_radius_meters": before.default_radius_meters,
                "selfie_retention_days": before.selfie_retention_days,
                "sheets_enabled": before.sheets_enabled,
            },
        },
        ip=request.client.host if request.client else None,
    )
    return {
        "verification_mode": updated.verification_mode.value,
        "default_radius_meters": updated.default_radius_meters,
        "selfie_retention_days": updated.selfie_retention_days,
        "sheets_enabled": updated.sheets_enabled,
    }


def _normalize_code(raw: str | None) -> str:
    if raw is None:
        return f"{secrets.randbelow(10**5):05d}"
    code = re.sub(r"\D", "", raw)
    if len(code) < 4 or len(code) > 6:
        raise HTTPException(status_code=422, detail="Code must be 4 to 6 digits.")
    return code


@router.put("/students/{student_id}/code")
def assign_code(
    student_id: int,
    payload: AssignCodeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, student_id)
    if not user or user.role != Role.student:
        raise HTTPException(status_code=404, detail="Employee not found.")
    code = _normalize_code(payload.code)
    user.verification_code = encrypt_code(code)
    user.verification_code_assigned_at = now()
    db.commit()
    log_action(
        db,
        admin,
        "code_assigned",
        entity_type="user",
        entity_id=user.id,
        details={"reassigned": user.verification_code_assigned_at is not None},
        ip=request.client.host if request.client else None,
    )
    return {"id": user.id, "code": code}


@router.get("/students/{student_id}/code")
def view_code(
    student_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, student_id)
    if not user or user.role != Role.student:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if not user.verification_code:
        return {"id": user.id, "code": None}
    try:
        code = decrypt_code(user.verification_code)
    except ValueError:
        raise HTTPException(status_code=500, detail="Stored code cannot be decrypted.") from None
    log_action(
        db,
        admin,
        "code_viewed",
        entity_type="user",
        entity_id=user.id,
        ip=request.client.host if request.client else None,
    )
    return {"id": user.id, "code": code}


@router.get("/devices")
def list_devices(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.execute(
            select(User, DeviceRegistration)
            .join(DeviceRegistration.user)
            .where(User.role == Role.student)
            .order_by(DeviceRegistration.last_seen_at.desc())
            .limit(200)
        )
        .all()
    )
    return [
        {
            "id": d.id,
            "employee_id": u.id,
            "employee_name": u.name,
            "device_name": d.device_name,
            "os": d.os,
            "os_version": d.os_version,
            "browser": d.browser,
            "browser_version": d.browser_version,
            "model": d.model,
            "screen": d.screen,
            "language": d.language,
            "ip": d.ip,
            "last_seen_at": local_iso(d.last_seen_at) if d.last_seen_at else None,
            "is_active": d.is_active,
            "created_at": local_iso(d.created_at),
        }
        for u, d in rows
    ]


@router.delete("/devices/{device_id}")
def revoke_device(
    device_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    device = db.get(DeviceRegistration, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found.")
    device.is_active = False
    db.commit()
    log_action(
        db,
        admin,
        "device_revoked",
        entity_type="device",
        entity_id=device.id,
        details={"employee_id": device.user_id, "device_name": device.device_name},
        ip=request.client.host if request.client else None,
    )
    return {"ok": True}


# ---------- Audit cockpit ----------


@router.get("/audit/records")
def audit_records(
    session_id: int | None = Query(default=None),
    min_anomaly: int = Query(default=0, ge=0, le=100),
    unreviewed_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Audit view of marked records with enrichment, device and anomaly detail."""
    query = (
        select(AttendanceRecord, User, AttendanceSession)
        .join(User, AttendanceRecord.student_id == User.id)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
    )
    if session_id is not None:
        query = query.where(AttendanceRecord.session_id == session_id)
    if min_anomaly:
        query = query.where(AttendanceRecord.anomaly_score >= min_anomaly)
    if unreviewed_only:
        query = query.where(AttendanceRecord.reviewed.is_(False))
    rows = db.execute(query.order_by(AttendanceRecord.scan_time.desc()).limit(limit)).all()
    return [
        {
            "id": r.id,
            "employee": {"id": u.id, "name": u.name, "email": u.email},
            "session": {
                "id": s.id,
                "subject": s.subject,
                "date": s.date.isoformat(),
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
            },
            "scan_time": local_iso(r.scan_time),
            "method": r.method,
            "verification_method_used": r.verification_method_used,
            "code_verified": r.code_verified,
            "selfie": r.selfie_path is not None,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "ip": r.ip,
            "isp": r.isp,
            "city": r.city,
            "region": r.region,
            "country": r.country,
            "os": r.os,
            "browser": r.browser,
            "browser_version": r.browser_version,
            "device_model": r.device_model,
            "screen": r.screen,
            "anomaly_score": r.anomaly_score,
            "anomaly_flags": r.anomaly_flags,
            "reviewed": r.reviewed,
        }
        for r, u, s in rows
    ]


@router.post("/audit/records/{record_id}/review")
def review_record(
    record_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    record = db.get(AttendanceRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    record.reviewed = True
    db.commit()
    log_action(
        db,
        admin,
        "record_reviewed",
        entity_type="attendance_record",
        entity_id=record.id,
        details={"student_id": record.student_id, "score": record.anomaly_score},
        ip=request.client.host if request.client else None,
    )
    return {"ok": True, "id": record.id, "reviewed": True}


@router.get("/audit/attempts")
def audit_attempts(
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Most recent check-in attempts (successes and rejections) with the reason."""
    rows = (
        db.execute(
            select(AttendanceAttempt, User, AttendanceSession)
            .join(User, AttendanceAttempt.student_id == User.id)
            .outerjoin(AttendanceSession, AttendanceAttempt.session_id == AttendanceSession.id)
            .order_by(AttendanceAttempt.attempted_at.desc())
            .limit(limit)
        )
        .all()
    )
    return [
        {
            "id": a.id,
            "employee": {"id": u.id, "name": u.name},
            "session": (
                {"id": s.id, "subject": s.subject, "date": s.date.isoformat()} if s else None
            ),
            "attempted_at": local_iso(a.attempted_at),
            "outcome": a.outcome,
            "fail_reason": a.fail_reason,
            "method": a.method,
            "ip": a.ip,
            "latitude": a.latitude,
            "longitude": a.longitude,
        }
        for a, u, s in rows
    ]


@router.get("/audit/log")
def audit_log_view(
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Recent admin/privileged actions."""
    rows = (
        db.execute(
            select(AuditLog, User)
            .outerjoin(User, AuditLog.actor_id == User.id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        .all()
    )
    return [
        {
            "id": e.id,
            "actor": u.name if u else None,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "details": e.details,
            "ip": e.ip,
            "created_at": local_iso(e.created_at),
        }
        for e, u in rows
    ]
