"""Create the database, tables, and seed initial users.

Usage:
    uv run python scripts/init_db.py
"""

import sys
from pathlib import Path

import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.db.database import Base, engine  # noqa: E402
from app.models.entities import Role, User  # noqa: E402

settings = get_settings()

ADMIN_EMAIL = "admin@company.com"
ADMIN_PASSWORD = "admin123"

STUDENTS = [
    ("Aarav Sharma", "aarav@company.com", "student123"),
    ("Priya Patel", "priya@company.com", "student123"),
    ("Rahul Verma", "rahul@company.com", "student123"),
    ("Sneha Iyer", "sneha@company.com", "student123"),
    ("Vikram Singh", "vikram@company.com", "student123"),
]


def _create_database() -> None:
    server_url = (
        f"mysql+pymysql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}?charset=utf8mb4"
    )
    eng = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{settings.db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    eng.dispose()
    print(f"database `{settings.db_name}` ready")


def _ensure_selfie_column() -> None:
    with engine.connect() as conn:
        existing = conn.execute(
            text("SHOW COLUMNS FROM attendance_records LIKE 'selfie_path'")
        ).fetchall()
        if not existing:
            conn.execute(text("ALTER TABLE attendance_records ADD COLUMN selfie_path VARCHAR(255) NULL"))
    print("attendance_records.selfie_path ready")


def _seed() -> None:
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        if db.query(User).filter(User.email == ADMIN_EMAIL).first():
            print("admin already exists, skipping seed")
            return

        admin = User(
            name="System Admin",
            email=ADMIN_EMAIL,
            password_hash=bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode(),
            role=Role.admin,
        )
        db.add(admin)

        for name, email, password in STUDENTS:
            db.add(
                User(
                    name=name,
                    email=email,
                    password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
                    role=Role.student,
                )
            )
        db.commit()
        print(f"seeded admin ({ADMIN_EMAIL}) and {len(STUDENTS)} students")


if __name__ == "__main__":
    _create_database()
    Base.metadata.create_all(bind=engine)
    print("tables created")
    _ensure_selfie_column()
    _seed()
