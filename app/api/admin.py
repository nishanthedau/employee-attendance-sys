from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_admin
from app.api.schemas import SessionCreateRequest, StudentCreateRequest
from app.core.time import local_iso
from app.db.database import get_db
from app.models.entities import AttendanceRecord, AttendanceSession, Role, User
from app.services.analytics_service import dashboard_stats, export_csv, subject_options
from app.services.auth_service import create_user
from app.services.qr_service import render_session_qr
from app.services.session_service import CreateSessionData, validate_and_create

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _session_dict(s: AttendanceSession) -> dict:
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
    }


@router.post("/attendance/create")
def create_session(
    payload: SessionCreateRequest,
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


@router.get("/dashboard")
def dashboard(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard_stats(db)


@router.get("/sessions")
def list_sessions(
    subject: str | None = Query(default=None),
    session_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = select(AttendanceSession).options(selectinload(AttendanceSession.records))
    if subject:
        query = query.where(AttendanceSession.subject == subject)
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
                "student_id": u.id,
                "student_name": u.name,
                "email": u.email,
                "scan_time": r.scan_time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": r.status,
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
        raise HTTPException(status_code=409, detail="A student with this email already exists.") from None
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
    session_date: date | None = Query(default=None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    csv_data = export_csv(db, subject=subject, day=session_date)
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="attendance_export.csv"'},
    )
