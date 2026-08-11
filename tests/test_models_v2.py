"""Phase 1: v2 audit-layer models round-trip against the test database."""

import datetime
import secrets

from app.core.time import now
from app.models.entities import (
    AttendanceAttempt,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    DeviceRegistration,
    OrgSettings,
    Role,
    SheetsSync,
    User,
    VerificationMode,
)


def _make_user(db, name="Demo Employee", email="demo@company.com"):
    user = User(name=name, email=email, password_hash="x", role=Role.student)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_session(db, user, subject="Basics"):
    session = AttendanceSession(
        subject=subject,
        faculty="Teacher",
        date=datetime.date.today(),
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        latitude=19.2237,
        longitude=73.1334,
        radius_meters=75,
        qr_token=secrets.token_hex(16),
        expires_at=now() + datetime.timedelta(hours=1),
        created_by=user.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def test_org_settings_defaults(db_session):
    settings = OrgSettings()
    db_session.add(settings)
    db_session.commit()
    assert settings.verification_mode == VerificationMode.none
    assert settings.default_radius_meters == 75
    assert settings.sheets_enabled is False
    assert settings.selfie_retention_days == 90


def test_org_settings_verification_modes(db_session):
    settings = db_session.get(OrgSettings, 1)
    if settings is None:
        settings = OrgSettings(id=1)
        db_session.add(settings)
    settings.verification_mode = VerificationMode.both
    db_session.commit()
    assert db_session.get(OrgSettings, 1).verification_mode == VerificationMode.both


def test_user_verification_code_nullable(db_session):
    user = _make_user(db_session)
    assert user.verification_code is None
    assert user.verification_code_assigned_at is None
    user.verification_code = "encrypted-blob"
    user.verification_code_assigned_at = now()
    db_session.commit()
    assert db_session.get(User, user.id).verification_code == "encrypted-blob"


def test_device_registration_roundtrip(db_session):
    user = _make_user(db_session)
    device = DeviceRegistration(
        user_id=user.id,
        token_hash=secrets.token_hex(32),
        device_name="Chrome on iPhone",
        os="iOS",
        os_version="17.0",
        browser="Safari",
        browser_version="17.0",
        model="iPhone 14",
        screen="390x844",
        language="en",
        ip="203.0.113.1",
        is_active=True,
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    assert device.id is not None
    assert user.devices[0].token_hash == device.token_hash
    device.is_active = False
    db_session.commit()
    assert db_session.get(DeviceRegistration, device.id).is_active is False


def test_attendance_attempt_roundtrip(db_session):
    user = _make_user(db_session)
    session = _make_session(db_session, user)
    device = DeviceRegistration(user_id=user.id, token_hash=secrets.token_hex(32), is_active=True)
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    attempt = AttendanceAttempt(
        student_id=user.id,
        session_id=session.id,
        device_id=device.id,
        outcome="failure",
        fail_reason="outside_region",
        method="scan",
        ip="203.0.113.1",
        isp="Test ISP",
        user_agent="Mozilla/5.0 test",
        os="iOS",
        browser="Safari",
        browser_version="17.0",
        device_model="iPhone 14",
        network_type="wifi",
        screen="390x844",
        server_timestamps={"scan_received": "2026-08-07T09:00:01", "rejected": "2026-08-07T09:00:01"},
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    assert attempt.id is not None
    assert attempt.outcome == "failure"
    assert attempt.server_timestamps["scan_received"] == "2026-08-07T09:00:01"
    assert db_session.get(AttendanceAttempt, attempt.id).fail_reason == "outside_region"


def test_attendance_record_soft_gps_and_audit_fields(db_session):
    user = _make_user(db_session)
    session = _make_session(db_session, user)
    record = AttendanceRecord(
        student_id=user.id,
        session_id=session.id,
        latitude=None,
        longitude=None,
        status="present",
        method="selfie",
        verification_method_used="selfie",
        code_verified=None,
        ip="203.0.113.1",
        network_type="cellular",
        anomaly_score=0,
        anomaly_flags=None,
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    assert record.latitude is None
    assert record.longitude is None
    assert record.verification_method_used == "selfie"
    assert record.anomaly_score == 0


def test_audit_log_roundtrip(db_session):
    admin = _make_user(db_session, name="Admin", email="admin@company.com")
    admin.role = Role.admin
    entry = AuditLog(
        actor_id=admin.id,
        actor_role="admin",
        action="device_revoked",
        entity_type="device",
        entity_id=7,
        details={"device": "iPhone 14", "ip": "203.0.113.1"},
        ip="203.0.113.1",
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    assert entry.action == "device_revoked"
    assert entry.details["device"] == "iPhone 14"


def test_sheets_sync_roundtrip(db_session):
    user = _make_user(db_session)
    session = _make_session(db_session, user)
    sync = SheetsSync(session_id=session.id, status="pending")
    db_session.add(sync)
    db_session.commit()
    db_session.refresh(sync)
    assert sync.status == "pending"
    assert sync.attempts == 0
    sync.status = "synced"
    sync.spreadsheet_id = "abc123"
    db_session.commit()
    assert db_session.get(SheetsSync, sync.id).status == "synced"
