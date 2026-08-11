import datetime
import enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Role(enum.StrEnum):
    admin = "admin"
    student = "student"


class VerificationMode(enum.StrEnum):
    none = "none"
    selfie = "selfie"
    code = "code"
    both = "both"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(190), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), nullable=False, default=Role.student)
    verification_code: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verification_code_assigned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)

    tokens: Mapped[list["AuthToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="student")
    devices: Mapped[list["DeviceRegistration"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    attempts: Mapped[list["AttendanceAttempt"]] = relationship(back_populates="student")

    def public_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role.value}


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped[User] = relationship(back_populates="tokens")


class OrgSettings(Base):
    """Single-row org-level configuration (id is always 1)."""

    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verification_mode: Mapped[VerificationMode] = mapped_column(
        Enum(VerificationMode, native_enum=False), nullable=False, default=VerificationMode.none
    )
    default_radius_meters: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    selfie_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    sheets_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )


class DeviceRegistration(Base):
    """A phone bound to an employee so they only log in once."""

    __tablename__ = "device_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    screen: Mapped[str | None] = mapped_column(String(30), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)

    user: Mapped[User] = relationship(back_populates="devices")
    attempts: Mapped[list["AttendanceAttempt"]] = relationship(back_populates="device")


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String(120), nullable=False)
    faculty: Mapped[str] = mapped_column(String(120), nullable=False)
    date: Mapped[datetime.date] = mapped_column(nullable=False, index=True)
    start_time: Mapped[datetime.time] = mapped_column(nullable=False)
    end_time: Mapped[datetime.time] = mapped_column(nullable=False)
    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)
    radius_meters: Mapped[int] = mapped_column(nullable=False, default=75)
    qr_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)

    records: Mapped[list["AttendanceRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("student_id", "session_id", name="uq_student_session"),
        Index("ix_record_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id"), nullable=False)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("device_registrations.id"), nullable=True)
    scan_time: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    gps_accuracy_meters: Mapped[float | None] = mapped_column(nullable=True)
    selfie_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="present")
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    verification_method_used: Mapped[str | None] = mapped_column(String(20), nullable=True)
    code_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    isp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    network_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    screen: Mapped[str | None] = mapped_column(String(30), nullable=True)
    anomaly_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomaly_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    student: Mapped[User] = relationship(back_populates="records")
    session: Mapped[AttendanceSession] = relationship(back_populates="records")
    device: Mapped[DeviceRegistration | None] = relationship()


class AttendanceAttempt(Base):
    """Every check-in attempt (success or failure) with an audit snapshot."""

    __tablename__ = "attendance_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_sessions.id"), nullable=True, index=True
    )
    device_id: Mapped[int | None] = mapped_column(ForeignKey("device_registrations.id"), nullable=True)
    attempted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, index=True
    )
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    fail_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    isp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    network_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    screen: Mapped[str | None] = mapped_column(String(30), nullable=True)
    server_timestamps: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    student: Mapped[User] = relationship(back_populates="attempts")
    session: Mapped[AttendanceSession | None] = relationship()
    device: Mapped[DeviceRegistration | None] = relationship(back_populates="attempts")


class AuditLog(Base):
    """Admin/privileged actions: session created, code assigned, device revoked..."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now, index=True)


class SheetsSync(Base):
    """Per-session queue for the Google Sheets mirror."""

    __tablename__ = "sheets_sync"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    spreadsheet_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )

    session: Mapped[AttendanceSession] = relationship()
