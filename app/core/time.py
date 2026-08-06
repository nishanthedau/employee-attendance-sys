"""Time helpers.

The system stores datetimes as the server's local wall-clock time (naive).
Session dates/times are institution-local, and the campus timezone equals the
server timezone in this deployment. To keep clients correct regardless of the
device clock/timezone, every absolute instant we serialize is annotated with
the server's UTC offset, so `new Date(...)` on the frontend parses an instant.
"""

from datetime import datetime, timezone


def now() -> datetime:
    """Current server-local time."""
    return datetime.now()


def server_offset() -> timezone:
    offset = datetime.now().astimezone().utcoffset()
    return timezone(offset) if offset is not None else timezone.utc


def local_iso(dt: datetime) -> str:
    """Serialize a naive local datetime with the server's UTC offset.

    Example: 2026-08-06T21:25:57+05:30  (instead of a tz-less ISO string)
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=server_offset())
    return dt.isoformat()
