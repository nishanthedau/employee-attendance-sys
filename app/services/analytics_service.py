"""Admin dashboard aggregation and CSV export."""

import csv
import io
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import AttendanceRecord, AttendanceSession, User


def dashboard_stats(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    day_start = datetime.combine(today, time.min)
    day_end = datetime.combine(today, time.max)

    today_sessions = db.execute(
        select(AttendanceSession).where(AttendanceSession.date == today)
    ).scalars().all()

    enrolled = db.execute(select(func.count(User.id)).where(User.role == "student")).scalar() or 0

    present = db.execute(
        select(func.count(AttendanceRecord.id)).where(
            AttendanceRecord.scan_time.between(day_start, day_end),
            AttendanceRecord.status == "present",
        )
    ).scalar() or 0

    recent = (
        db.execute(
            select(AttendanceSession)
            .options(selectinload(AttendanceSession.records))
            .order_by(AttendanceSession.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )

    activity = (
        db.execute(
            select(AttendanceRecord, User, AttendanceSession)
            .join(User, AttendanceRecord.student_id == User.id)
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .order_by(AttendanceRecord.scan_time.desc())
            .limit(10)
        )
        .all()
    )

    return {
        "today": {
            "enrolled": enrolled,
            "present": present,
            "absent": max(enrolled - present, 0),
            "percentage": round(present / enrolled * 100, 1) if enrolled else 0.0,
            "sessions": len(today_sessions),
        },
        "recent_sessions": [
            {
                "id": s.id,
                "subject": s.subject,
                "faculty": s.faculty,
                "date": s.date.isoformat(),
                "start": s.start_time.strftime("%H:%M"),
                "end": s.end_time.strftime("%H:%M"),
                "marked": len(s.records),
                "radius": s.radius_meters,
            }
            for s in recent
        ],
        "recent_activity": [
            {
                "student": u.name,
                "subject": s.subject,
                "time": r.scan_time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": r.status,
            }
            for r, u, s in activity
        ],
    }


def export_csv(db: Session, subject: str | None = None, day: date | None = None) -> str:
    query = (
        select(
            AttendanceRecord.scan_time,
            User.name,
            User.email,
            AttendanceSession.subject,
            AttendanceSession.faculty,
            AttendanceSession.date,
            AttendanceSession.start_time,
            AttendanceSession.end_time,
            AttendanceRecord.latitude,
            AttendanceRecord.longitude,
            AttendanceRecord.selfie_path,
            AttendanceRecord.status,
        )
        .join(User, AttendanceRecord.student_id == User.id)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .order_by(AttendanceRecord.scan_time.desc())
    )
    if subject:
        query = query.where(AttendanceSession.subject == subject)
    if day:
        query = query.where(AttendanceSession.date == day)

    rows = db.execute(query).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "scan_time",
            "student",
            "email",
            "subject",
            "faculty",
            "date",
            "start",
            "end",
            "latitude",
            "longitude",
            "selfie",
            "status",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row[0].strftime("%Y-%m-%d %H:%M:%S"),
                row[1],
                row[2],
                row[3],
                row[4],
                row[5].isoformat(),
                row[6].strftime("%H:%M"),
                row[7].strftime("%H:%M"),
                row[8],
                row[9],
                "yes" if row[10] else "no",
                row[11],
            ]
        )
    return buffer.getvalue()


def subject_options(db: Session) -> list[str]:
    rows = db.execute(
        select(AttendanceSession.subject).distinct().order_by(AttendanceSession.subject)
    ).scalars().all()
    return list(rows)


def current_week(db: Session, student_id: int, today: date | None = None) -> dict:
    """Attendance for the current week only (Monday -> today's upcoming days)."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    week = [monday + timedelta(days=i) for i in range(7)]

    records = db.execute(
        select(AttendanceRecord, AttendanceSession)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .where(
            AttendanceRecord.student_id == student_id,
            AttendanceSession.date.between(week[0], week[6]),
        )
    ).all()

    by_day: dict[date, list[dict]] = {d: [] for d in week}
    for record, session in records:
        by_day[session.date].append(
            {
                "subject": session.subject,
                "faculty": session.faculty,
                "time": record.scan_time.strftime("%H:%M"),
                "status": record.status,
            }
        )

    return {
        "week_start": week[0].isoformat(),
        "days": [
            {
                "date": d.isoformat(),
                "weekday": d.strftime("%A"),
                "is_today": d == today,
                "is_future": d > today,
                "marked": len(by_day[d]) > 0,
                "count": len(by_day[d]),
                "sessions": by_day[d],
            }
            for d in week
        ],
    }
