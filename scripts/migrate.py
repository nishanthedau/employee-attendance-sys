"""Apply pending SQL migrations in database/migrations/ in order.

Applied versions are tracked in the ``schema_migrations`` table so reruns
are no-ops. Run from the project root: ``uv run python scripts/migrate.py``
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "database" / "migrations"


def _db_connect(settings):
    if settings.database_url:
        url = urlparse(settings.database_url)
        return pymysql.connect(
            host=url.hostname,
            port=url.port or 3306,
            user=url.username,
            password=url.password or "",
            database=url.path.lstrip("/") or None,
            charset="utf8mb4",
        )
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
    )


def _load_statements(path: Path) -> list[str]:
    text = path.read_text()
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return [s.strip() for s in text.split(";") if s.strip()]


def main() -> int:
    settings = get_settings()
    conn = _db_connect(settings)
    applied: set[str] = set()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version VARCHAR(64) PRIMARY KEY,"
                " applied_at DATETIME NOT NULL"
                ") ENGINE=InnoDB"
            )
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in applied:
                print(f"skip {version} (already applied)")
                continue
            statements = _load_statements(path)
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
                    (version, datetime.now()),
                )
            conn.commit()
            print(f"applied {version} ({len(statements)} statements)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
