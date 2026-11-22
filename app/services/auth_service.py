"""Telegram Login Widget verification, HMAC session cookies, and auth dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas import TelegramAuthRequest, UserOut


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(val: str) -> bytes:
    pad = "=" * (-len(val) % 4)
    return base64.urlsafe_b64decode(f"{val}{pad}".encode("ascii"))


def is_https_request(request: Request, settings: Settings | None = None) -> bool:
    """Determine if request arrived over HTTPS (Cloudflare proxy or direct)."""
    cfg = settings or get_settings()
    if cfg.cookie_secure_override is not None:
        return cfg.cookie_secure_override
    xfp = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if xfp:
        return xfp == "https"
    return request.url.scheme == "https"


def verify_telegram_login(
    payload: TelegramAuthRequest,
    bot_token: str,
    *,
    now_ts: int | None = None,
    max_age_sec: int = 300,
) -> dict[str, object]:
    """Validate Telegram Login Widget HMAC-SHA256 signature and auth_date freshness."""
    if not bot_token:
        raise RuntimeError("Telegram login bot token is not configured")

    now = int(time.time()) if now_ts is None else now_ts
    age = now - payload.auth_date
    if age > max_age_sec or age < -60:
        raise ValueError("Telegram auth payload expired or invalid timestamp")

    raw_fields: dict[str, object] = {
        "id": payload.id,
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "username": payload.username,
        "photo_url": payload.photo_url,
        "auth_date": payload.auth_date,
    }
    check_lines = [
        f"{k}={v}"
        for k, v in sorted(raw_fields.items())
        if v is not None and v != ""
    ]
    data_check_string = "\n".join(check_lines)

    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, payload.hash.strip().lower()):
        raise ValueError("Invalid Telegram login signature")

    display_parts = [payload.first_name.strip()]
    if payload.last_name and payload.last_name.strip():
        display_parts.append(payload.last_name.strip())
    return {
        "tg_id": payload.id,
        "username": (payload.username or "").strip(),
        "display_name": " ".join(display_parts),
        "photo_url": (payload.photo_url or "").strip(),
    }


def upsert_telegram_user(conn: sqlite3.Connection, profile: dict[str, object]) -> UserOut:
    """Create or refresh user row from verified Telegram profile."""
    settings = get_settings()
    tg_id = int(profile["tg_id"])
    role = "admin" if tg_id in settings.admin_tg_ids else "student"
    now_ts = int(time.time())

    conn.execute(
        """
        INSERT INTO users (tg_id, username, display_name, photo_url, role, created_ts, last_seen_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tg_id) DO UPDATE SET
            username = excluded.username,
            display_name = excluded.display_name,
            photo_url = excluded.photo_url,
            role = excluded.role,
            last_seen_ts = excluded.last_seen_ts
        """,
        (
            tg_id,
            str(profile["username"]),
            str(profile["display_name"]),
            str(profile["photo_url"]),
            role,
            now_ts,
            now_ts,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, tg_id, username, display_name, photo_url, role FROM users WHERE tg_id = ?",
        (tg_id,),
    ).fetchone()
    return UserOut(
        id=int(row["id"]),
        tg_id=int(row["tg_id"]),
        username=row["username"],
        display_name=row["display_name"],
        photo_url=row["photo_url"],
        role=row["role"],
    )


def create_session_token(user: UserOut, settings: Settings | None = None) -> str:
    """Create signed opaque session cookie value."""
    cfg = settings or get_settings()
    exp = int(time.time()) + cfg.session_ttl_sec
    payload = json.dumps({"uid": user.id, "tg_id": user.tg_id, "exp": exp}, separators=(",", ":")).encode("utf-8")
    b64 = _b64url_encode(payload)
    sig = hmac.new(cfg.token_secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{b64}.{sig}"


def decode_session_token(token: str, settings: Settings | None = None) -> dict[str, int] | None:
    """Verify signed session cookie value and check expiration."""
    cfg = settings or get_settings()
    if not token or "." not in token:
        return None
    b64, sig = token.split(".", 1)
    expected = hmac.new(cfg.token_secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_b64url_decode(b64).decode("utf-8"))
        uid = int(data["uid"])
        tg_id = int(data["tg_id"])
        exp = int(data["exp"])
    except Exception:
        return None
    if exp < int(time.time()):
        return None
    return {"uid": uid, "tg_id": tg_id}


def get_optional_user(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> UserOut | None:
    """Return authenticated UserOut from HttpOnly cookie, or None for guests."""
    settings = get_settings()
    raw_cookie = request.cookies.get(settings.cookie_name)
    if not raw_cookie:
        return None
    parsed = decode_session_token(raw_cookie, settings)
    if parsed is None:
        return None
    row = conn.execute(
        "SELECT id, tg_id, username, display_name, photo_url, role FROM users WHERE id = ? AND tg_id = ?",
        (parsed["uid"], parsed["tg_id"]),
    ).fetchone()
    if row is None:
        return None
    return UserOut(
        id=int(row["id"]),
        tg_id=int(row["tg_id"]),
        username=row["username"],
        display_name=row["display_name"],
        photo_url=row["photo_url"],
        role=row["role"],
    )


def require_current_user(
    user: Annotated[UserOut | None, Depends(get_optional_user)],
) -> UserOut:
    """Dependency requiring an authenticated user (401 for guests)."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Потрібна авторизація через Telegram",
        )
    return user


OptionalUserDep = Annotated[UserOut | None, Depends(get_optional_user)]
CurrentUserDep = Annotated[UserOut, Depends(require_current_user)]
