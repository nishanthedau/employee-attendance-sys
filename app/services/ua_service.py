"""Lightweight User-Agent parsing for the audit columns.

Full UA parsing libraries are overkill for three columns; this covers the
browsers and OSes these users actually ship (Chrome, Safari, Firefox, Edge,
Samsung Internet on iOS/Android/desktop). Unknown strings yield empty values
instead of guessed ones.
"""

import re

_OS_PATTERNS = [
    (re.compile(r"iPhone OS (\d+[_\d]*)"), "iOS"),
    (re.compile(r"iPad; .*?OS (\d+[_\d]*)"), "iPadOS"),
    (re.compile(r"Android (\d+[.\d]*)"), "Android"),
    (re.compile(r"Windows NT 10\.0"), "Windows"),
    (re.compile(r"Windows NT 6\.\d"), "Windows"),
    (re.compile(r"Mac OS X (\d+[_\d]*)"), "macOS"),
    (re.compile(r"CrOS"), "ChromeOS"),
    (re.compile(r"Linux"), "Linux"),
]

_BROWSER_PATTERNS = [
    (re.compile(r"SamsungBrowser/(\d+\.\d+)"), "Samsung Internet"),
    (re.compile(r"Edg(?:e|A|iOS)?/(\d+\.\d+)"), "Edge"),
    (re.compile(r"OPR/(\d+\.\d+)"), "Opera"),
    (re.compile(r"Firefox/(\d+\.\d+)"), "Firefox"),
    (re.compile(r"Chrome/(\d+\.\d+)"), "Chrome"),
    (re.compile(r"Version/(\d+\.\d+).*?Safari/"), "Safari"),
    (re.compile(r"Mobile Safari"), "Safari"),
]


def _os_name(ua: str) -> tuple[str, str | None]:
    for pattern, name in _OS_PATTERNS:
        m = pattern.search(ua)
        if m:
            version = m.group(1).replace("_", ".") if m.groups() else None
            return name, version
    return "", None


def _browser(ua: str) -> tuple[str, str | None]:
    for pattern, name in _BROWSER_PATTERNS:
        m = pattern.search(ua)
        if m:
            return name, (m.group(1) if m.groups() else None)
    return "", None


def parse_ua(user_agent: str | None) -> dict:
    """Return {os, browser, browser_version, device_model} from a User-Agent."""
    ua = (user_agent or "").strip()
    if not ua:
        return {"os": "", "browser": "", "browser_version": "", "device_model": ""}
    os_name, os_version = _os_name(ua)
    browser, version = _browser(ua)
    device_model = "Desktop"
    if "iPhone" in ua:
        device_model = "iPhone"
    elif "iPad" in ua:
        device_model = "iPad"
    elif "Android" in ua and "Mobile" in ua:
        device_model = "Android phone"
    elif "Android" in ua:
        device_model = "Android tablet"
    return {
        "os": os_name,
        "browser": browser,
        "browser_version": version or "",
        "device_model": device_model,
    }
