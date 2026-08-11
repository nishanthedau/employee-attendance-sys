"""Per-scan anomaly scoring for the audit trail.

Anomalies are informational — they never block a scan. Each signal adds to a
0-100 score and records a human-readable flag; the admin reviews them in the
cockpit (Phase 6). Signals: marking at the edge of the radius, exact-GPS reuse
across sessions, teleport-speed between scans, first scan from a new device, and
a first-time country change for the employee's IP.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AttendanceRecord
from app.services.geo_service import haversine_meters

MAX_SCORE = 100
EDGE_FRACTION = 0.85
IMPLAUSIBLE_SPEED_KMH = 250
MIN_SPEED_GAP_SECONDS = 60


def assess(
    db: Session,
    *,
    student_id: int,
    session_lat: float,
    session_lng: float,
    radius_meters: int,
    scan_lat: float | None,
    scan_lng: float | None,
    scan_time: datetime,
    device_id: int | None,
    country: str | None,
) -> tuple[int, dict]:
    """Score this scan against the employee's history. Never raises.

    Returns (anomaly_score capped at 100, flags dict of {signal: detail}).
    """
    score = 0
    flags: dict = {}

    previous = db.execute(
        select(AttendanceRecord)
        .where(AttendanceRecord.student_id == student_id)
        .order_by(AttendanceRecord.scan_time.desc())
        .limit(1)
    ).scalar_one_or_none()

    if scan_lat is not None and scan_lng is not None:
        distance = haversine_meters(scan_lat, scan_lng, session_lat, session_lng)
        if radius_meters and distance >= EDGE_FRACTION * radius_meters:
            score += 15
            flags["edge_of_radius"] = f"{int(distance)}m from center (radius {radius_meters}m)"

        if previous and previous.latitude == scan_lat and previous.longitude == scan_lng:
            score += 25
            flags["reused_coordinates"] = "exact same GPS as previous scan"

        if (
            previous
            and previous.latitude is not None
            and previous.longitude is not None
            and previous.scan_time is not None
        ):
            gap = (scan_time - previous.scan_time).total_seconds()
            if gap >= MIN_SPEED_GAP_SECONDS:
                moved = haversine_meters(scan_lat, scan_lng, previous.latitude, previous.longitude)
                speed_kmh = (moved / 1000.0) / (gap / 3600.0)
                if speed_kmh > IMPLAUSIBLE_SPEED_KMH:
                    score += 40
                    flags["implausible_speed"] = f"{speed_kmh:.0f} km/h between scans"

    if device_id is not None:
        used_here = db.execute(
            select(AttendanceRecord.id)
            .where(
                AttendanceRecord.student_id == student_id,
                AttendanceRecord.device_id == device_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if used_here is None:
            score += 10
            flags["new_device"] = "first scan from this device"

    if country:
        known_countries = set(
            db.execute(
                select(AttendanceRecord.country).where(
                    AttendanceRecord.student_id == student_id,
                    AttendanceRecord.country.is_not(None),
                )
            ).scalars().all()
        )
        if known_countries and country not in known_countries:
            score += 30
            flags["ip_country_change"] = f"first scan from {country}"

    return min(score, MAX_SCORE), flags
