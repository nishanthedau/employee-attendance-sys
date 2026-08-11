"""GeoLite2 IP enrichment.

Attendance records store the client IP; ``enrich`` resolves it against MaxMind
GeoLite2 City/ASN databases to attach ISP, city, region and country. Both
databases are optional and loaded lazily from the paths in ``.env``
(``GEOIP_CITY_DB`` / ``GEOIP_ASN_DB``). When a database is missing the lookup
returns whatever the other one can provide; when neither is configured every
field stays ``None`` so the app degrades gracefully in development.
"""

import ipaddress

from geoip2.database import Reader
from geoip2.errors import AddressNotFoundError, GeoIP2Error

from app.core.config import get_settings

_MISSING = object()
_city_reader: Reader | None | object = None
_asn_reader: Reader | None | object = None


def _load(path: str, label: str) -> Reader | None:
    if not path:
        return None
    try:
        return Reader(path)
    except Exception:
        raise RuntimeError(f"Could not open GeoLite2 {label} database at {path}") from None


def _get_city_reader() -> Reader | None:
    global _city_reader
    if _city_reader is _MISSING:
        return None
    if _city_reader is None:
        _city_reader = _load(get_settings().geoip_city_db, "City") or _MISSING
    return _city_reader if _city_reader is not _MISSING else None


def _get_asn_reader() -> Reader | None:
    global _asn_reader
    if _asn_reader is _MISSING:
        return None
    if _asn_reader is None:
        _asn_reader = _load(get_settings().geoip_asn_db, "ASN") or _MISSING
    return _asn_reader if _asn_reader is not _MISSING else None


def is_private_ip(ip: str) -> bool:
    """True for loopback, private, link-local and reserved ranges we don't geo."""
    if not ip or ip == "testclient":
        return True
    try:
        return ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return True


def enrich(ip: str | None) -> dict:
    """Resolve an IP to {isp, city, region, country}. Never raises.

    Private and unknown IPs (and any config problem) yield an empty dict so the
    caller always gets plain strings or None.
    """
    if not ip or is_private_ip(ip):
        return {}
    result: dict = {}
    city_reader = _get_city_reader()
    if city_reader:
        try:
            city = city_reader.city(ip)
            result["country"] = city.country.name or None
            result["region"] = city.subdivisions.most_specific.name or None
            result["city"] = city.city.name or None
        except (AddressNotFoundError, GeoIP2Error, ValueError):
            pass
    asn_reader = _get_asn_reader()
    if asn_reader:
        try:
            result["isp"] = asn_reader.asn(ip).autonomous_system_organization or None
        except (AddressNotFoundError, GeoIP2Error, ValueError):
            result.setdefault("isp", None)
    return result
