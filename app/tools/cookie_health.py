"""X / Twitter cookie health check for proactive expiry detection.

X (Twitter) search uses Playwright with exported browser cookies.  Session
cookies typically expire within 7-30 days.  This module provides a health
check that can be called from the CLI ``status`` command *before* a run and
from the tool executor *during* a run when results come back empty.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def check_x_cookie_health(cookies_path: str = "x_cookies.json") -> dict:
    """Return cookie-health summary.

    Returns a dict with:
        status: "OK" | "EXPIRING_SOON" | "EXPIRED" | "MISSING" | "INVALID"
        days_remaining: float | None   (shortest-lived cookie)
        expired_cookies: list[str]
        message: str                    (human-readable one-liner)
    """

    path = Path(cookies_path)
    if not path.exists():
        return {
            "status": "MISSING",
            "days_remaining": None,
            "expired_cookies": [],
            "message": "X cookie file not found: " + str(cookies_path),
        }

    try:
        raw = path.read_text(encoding="utf-8")
        cookies = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "INVALID",
            "days_remaining": None,
            "expired_cookies": [],
            "message": "X cookie file parse error: " + str(exc),
        }

    if not isinstance(cookies, list) or not cookies:
        return {
            "status": "INVALID",
            "days_remaining": None,
            "expired_cookies": [],
            "message": "X cookie file is empty or not a cookie array",
        }

    now = datetime.now(timezone.utc)
    expired: list[str] = []
    min_days: float = float("inf")
    has_expiry = False

    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        expires = cookie.get("expirationDate") or cookie.get("expires")
        if expires is None:
            continue
        has_expiry = True
        try:
            exp = datetime.fromtimestamp(float(expires), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            continue
        days = (exp - now).total_seconds() / 86400.0
        if days <= 0:
            expired.append(cookie.get("name", "unknown"))
        min_days = min(min_days, days)

    if not has_expiry:
        return {
            "status": "OK",
            "days_remaining": None,
            "expired_cookies": [],
            "message": "Cookie file has no expiry fields; unable to auto-detect, update regularly",
        }

    if min_days <= 0:
        names = ", ".join(expired[:5])
        return {
            "status": "EXPIRED",
            "days_remaining": 0,
            "expired_cookies": expired,
            "message": "X cookie expired (" + names + "), re-export from browser",
        }

    days_str = str(round(min_days, 1))
    if min_days < 3:
        return {
            "status": "EXPIRING_SOON",
            "days_remaining": round(min_days, 1),
            "expired_cookies": [],
            "message": "X cookie expires in " + days_str + " days, re-export soon",
        }

    return {
        "status": "OK",
        "days_remaining": round(min_days, 1),
        "expired_cookies": [],
        "message": "X cookie valid for " + days_str + " more days",
    }
