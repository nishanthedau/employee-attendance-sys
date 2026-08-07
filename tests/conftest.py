import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    db = TestingSession()
    yield db
    db.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_rate_limits():
    from app.api.deps import LOGIN_LIMIT, SCAN_LIMIT

    LOGIN_LIMIT._hits.clear()
    SCAN_LIMIT._hits.clear()
    yield


@pytest.fixture(autouse=True)
def tmp_selfie_storage(tmp_path, monkeypatch):
    from app.core import storage

    target = tmp_path / "selfies"
    monkeypatch.setattr(storage, "_selfies_dir", lambda: target)
    yield target
