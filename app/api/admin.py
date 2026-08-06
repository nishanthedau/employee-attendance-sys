from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.api.schemas import SessionCreateRequest
from app.db.database import get_db
from app.models.entities import AttendanceRecord, AttendanceSession, Role, User
from app.services.analytics_service import dashboard_stats, export_csv, subject_options
from app.services.qr_service import render_session_qr
from app.services.session_service import SessionError, CreateSessionData, validate_and_create

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/attendance/create")
def create_session(payload: SessionCreateRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
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
    except SessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "id": session.id,
        "subject": session.subject,
        "faculty": session.faculty,
        "date": session.date.isoformat(),
        "start_time": session.start_time.strftime("%H:%M"),
        "end_time": session.end_time.strftime("%H:%M"),
        "latitude": session.latitude,
        "longitude": session.longitude,
        "radius_meters": session.radius_meters,
        "qr_expires_at": session.expires_at.isoformat(),
    }


@router.get("/attendance/qr")
def get_qr(session_id: int = Query(...), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    session = db.get(AttendanceSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
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
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = select(AttendanceSession)
    if subject:
        query = query.where(AttendanceSession.subject == subject)
    if session_date:
        query = query.where(AttendanceSession.date == session_date)
    sessions = db.execute(query.order_by(AttendanceSession.date.desc())).scalars().all()
    return [
        {
            "id": s.id,
            "subject": s.subject,
            "faculty": s.faculty,
            "date": s.date.isoformat(),
            "start_time": s.start_time.strftime("%H:%M"),
            "end_time": s.end_time.strftime("%H:%M"),
            "marked": len(s.records),
            "radius_meters": s.radius_meters,
            "qr_expires_at": s.expires_at.isoformat(),
        }
        for s in sessions
    ]


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
        raise HTTPException(status_code=404, detail="Session not found")
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
def list_students(q: str | None = Query(default=None), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(User).where(User.role == Role.student)
    if q:
        query = query.where(User.name.like(f"%{q}%") | User.email.like(f"%{q}%"))
    students = db.execute(query.order_by(User.name).limit(50)).scalars().all()
    return [{"id": u.id, "name": u.name, "email": u.email} for u in students]


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
