"""Phase 4: GeoLite2 IP/ISP enrichment + UA parsing for audit columns."""

import base64
from datetime import date

from app.models.entities import AttendanceRecord, Role, User
from app.services.auth_service import create_user
from app.services.geoip_service import enrich, is_private_ip
from app.services.session_service import record_scan
from app.services.ua_service import parse_ua

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _session(client, headers):
    return client.post(
        "/api/admin/attendance/create",
        headers=headers,
        json={
            "subject": "DBMS",
            "faculty": "Prof. Rao",
            "date": date.today().isoformat(),
            "start_time": "00:00:00",
            "end_time": "23:59:00",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "radius_meters": 75,
            "qr_expiry_minutes": 3,
        },
    ).json()


def _qr_token(db, session_id):
    from app.models.entities import AttendanceSession

    return db.get(AttendanceSession, session_id).qr_token


def _scan(client, headers, session_id, token, ua=None):
    data = {
        "session_id": str(session_id),
        "qr_token": token,
        "latitude": "28.6139",
        "longitude": "77.2090",
    }
    files = {"selfie": ("s.png", PNG, "image/png")}
    kw = {"headers": {**headers, **({"User-Agent": ua} if ua else {})}}
    return client.post("/api/student/attendance/scan", data=data, files=files, **kw)


# ---------- UA parsing ----------

def test_parse_ua_iphone_safari():
    out = parse_ua(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
    )
    assert out["os"] == "iOS"
    assert out["browser"] == "Safari"
    assert out["device_model"] == "iPhone"


def test_parse_ua_android_chrome():
    out = parse_ua(
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AD1A.240802.019) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    )
    assert out["os"] == "Android"
    assert out["browser"] == "Chrome"
    assert out["device_model"] == "Android phone"


def test_parse_ua_windows_edge():
    out = parse_ua(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
    )
    assert out["os"] == "Windows"
    assert out["browser"] == "Edge"
    assert out["device_model"] == "Desktop"


def test_parse_ua_macos_firefox():
    out = parse_ua("Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:126.0) Gecko/20100101 Firefox/126.0")
    assert out["os"] == "macOS"
    assert out["browser"] == "Firefox"
    assert out["device_model"] == "Desktop"


def test_parse_ua_samsung():
    out = parse_ua(
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36"
    )
    assert out["browser"] == "Samsung Internet"
    assert out["device_model"] == "Android phone"


def test_parse_ua_empty():
    assert parse_ua(None) == {"os": "", "browser": "", "browser_version": "", "device_model": ""}


# ---------- GeoIP ----------

def test_is_private_ip():
    assert is_private_ip("127.0.0.1")
    assert is_private_ip("10.1.2.3")
    assert is_private_ip("192.168.0.1")
    assert is_private_ip("testclient")
    assert is_private_ip("")
    assert not is_private_ip("8.8.8.8")
    assert not is_private_ip("49.207.60.120")


def test_enrich_private_ip_empty():
    assert enrich("127.0.0.1") == {}


def test_enrich_no_db_configured_empty(monkeypatch):
    monkeypatch.setattr("app.services.geoip_service._get_city_reader", lambda: None)
    monkeypatch.setattr("app.services.geoip_service._get_asn_reader", lambda: None)
    assert enrich("8.8.8.8") == {}


class _FakeCity:
    country = type("C", (), {"name": "India"})()
    city = type("C", (), {"name": "Mumbai"})()
    subdivisions = type("S", (), {"most_specific": type("C", (), {"name": "Maharashtra"})()})


class _FakeAsn:
    autonomous_system_organization = "Example Telecom"


def test_enrich_with_readers(monkeypatch):
    calls = {"city": 0, "asn": 0}

    def fake_city():
        return type("Reader", (), {"city": lambda self, ip: calls.__setitem__("city", 1) or _FakeCity()})()

    def fake_asn():
        return type("Reader", (), {"asn": lambda self, ip: calls.__setitem__("asn", 1) or _FakeAsn()})()

    monkeypatch.setattr("app.services.geoip_service._get_city_reader", fake_city)
    monkeypatch.setattr("app.services.geoip_service._get_asn_reader", fake_asn)
    out = enrich("49.207.60.120")
    assert calls["city"] == 1 and calls["asn"] == 1
    assert out == {
        "isp": "Example Telecom",
        "city": "Mumbai",
        "region": "Maharashtra",
        "country": "India",
    }


def test_enrich_reader_error_is_swallowed(monkeypatch):
    from geoip2.errors import AddressNotFoundError

    def bad_city():
        reader = type("Reader", (), {})
        reader.city = lambda self, ip: (_ for _ in ()).throw(AddressNotFoundError("x"))
        return reader()

    monkeypatch.setattr("app.services.geoip_service._get_city_reader", bad_city)
    monkeypatch.setattr("app.services.geoip_service._get_asn_reader", lambda: None)
    assert enrich("8.8.8.8") == {}


# ---------- record_scan enrichment ----------

def test_record_scan_stores_enriched_columns(db_session, monkeypatch):
    from app.models.entities import AttendanceSession

    monkeypatch.setattr(
        "app.services.session_service.geoip_enrich",
        lambda ip: {"isp": "Example Telecom", "city": "Mumbai", "region": "Maharashtra", "country": "India"},
    )
    monkeypatch.setattr(
        "app.services.session_service.parse_ua",
        lambda ua: {"os": "iOS", "browser": "Safari", "browser_version": "17.2", "device_model": "iPhone"},
    )

    admin = create_user(db_session, "Admin", "admin@x.com", "secret123", Role.admin)
    student = create_user(db_session, "Stu", "stu@x.com", "secret123", Role.student)
    session = AttendanceSession(
        subject="DBMS",
        faculty="Prof",
        date=date.today(),
        start_time=__import__("datetime").time(9, 0),
        end_time=__import__("datetime").time(10, 0),
        latitude=28.6139,
        longitude=77.2090,
        radius_meters=75,
        qr_token="tok" * 12,
        expires_at=__import__("datetime").datetime(2099, 1, 1),
        created_by=admin.id,
    )
    db_session.add(session)
    db_session.commit()

    record = record_scan(
        db_session,
        session,
        student,
        28.6139,
        77.2090,
        None,
        method="scan",
        client_ip="49.207.60.120",
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/17.2 Mobile Safari/604.1"
        ),
    )
    db_session.refresh(record)
    assert record.ip == "49.207.60.120"
    assert record.isp == "Example Telecom"
    assert record.city == "Mumbai"
    assert record.region == "Maharashtra"
    assert record.country == "India"
    assert record.os == "iOS"
    assert record.browser == "Safari"
    assert record.browser_version == "17.2"
    assert record.device_model == "iPhone"


def test_record_scan_without_enrichment(client, db_session, tmp_selfie_storage):
    """Real HTTP scan: IP is private (testclient) so geo is skipped, but the
    User-Agent still lands in the audit columns."""
    create_user(db_session, "Admin", "admin@c.com", "secret123", Role.admin)
    login = client.post("/api/auth/login", json={"email": "admin@c.com", "password": "secret123"}).json()
    ah = {"Authorization": f"Bearer {login['token']}"}
    create_user(db_session, "Stu", "stu@c.com", "secret123", Role.student)
    login = client.post("/api/auth/login", json={"email": "stu@c.com", "password": "secret123"}).json()
    sh = {"Authorization": f"Bearer {login['token']}"}

    session = _session(client, ah)
    token = _qr_token(db_session, session["id"])
    ua = "Mozilla/5.0 (Linux; Android 14) Chrome/126.0.0.0 Mobile Safari/537.36"
    res = _scan(client, sh, session["id"], token, ua=ua)
    assert res.status_code == 200

    student = db_session.query(User).filter(User.email == "stu@c.com").one()
    record = db_session.query(AttendanceRecord).filter(AttendanceRecord.student_id == student.id).one()
    assert record.os == "Android"
    assert record.browser == "Chrome"
    assert record.device_model == "Android phone"
    assert record.ip == "testclient"
    assert record.isp is None
