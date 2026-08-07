from app.models.entities import Role
from app.services.auth_service import create_user


def make_user(db, name="Student", email="stu@company.com", role=Role.student):
    return create_user(db, name, email, "secret123", role)


def login(client, email, password="secret123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_success(client, db_session):
    make_user(db_session)
    res = login(client, "stu@company.com")
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["user"]["role"] == "student"


def test_login_wrong_password(client, db_session):
    make_user(db_session)
    res = client.post("/api/auth/login", json={"email": "stu@company.com", "password": "nope"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


def test_login_invalid_email_rejected(client, db_session):
    res = client.post("/api/auth/login", json={"email": "not-an-email", "password": "x"})
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], str)
    assert res.json()["code"] == "invalid_input"


def test_login_missing_field_friendly_message(client, db_session):
    res = client.post("/api/auth/login", json={"email": "stu@company.com"})
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], str)
    assert len(res.json()["detail"]) > 0


def test_login_email_case_insensitive(client, db_session):
    make_user(db_session)
    res = login(client, "STU@COMPANY.COM")
    assert res.status_code == 200


def test_protected_route_without_token(client):
    res = client.get("/api/student/attendance/current-week")
    assert res.status_code == 401


def test_logout_revokes_token(client, db_session):
    make_user(db_session)
    token = login(client, "stu@company.com").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/student/attendance/current-week", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/student/attendance/current-week", headers=headers).status_code == 401
