"""Telegram Login Widget authentication endpoints."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import get_settings
from app.db import get_db
from app.schemas import AuthResponseOut, AuthStatusOut, TelegramAuthRequest
from app.services.auth_service import (
    OptionalUserDep,
    create_session_token,
    is_https_request,
    upsert_telegram_user,
    verify_telegram_login,
)
from app.services.rate_limit import auth_ip_limiter, extract_client_ip

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusOut)
def auth_status(user: OptionalUserDep) -> AuthStatusOut:
    settings = get_settings()
    return AuthStatusOut(
        enabled=settings.telegram_auth_enabled,
        bot_username=settings.telegram_login_bot_username,
        authenticated=(user is not None),
        user=user,
    )


@router.post("/telegram", response_model=AuthResponseOut)
def telegram_login(
    payload: TelegramAuthRequest,
    request: Request,
    response: Response,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> AuthResponseOut:
    auth_ip_limiter.check_or_raise(extract_client_ip(request))
    settings = get_settings()
    if not settings.telegram_login_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram Login Widget не налаштовано (потрібен TELEGRAM_LOGIN_BOT_TOKEN)",
        )

    try:
        profile = verify_telegram_login(
            payload,
            settings.telegram_login_bot_token,
            max_age_sec=settings.auth_max_age_sec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = upsert_telegram_user(conn, profile)
    cookie_val = create_session_token(user, settings)
    response.set_cookie(
        key=settings.cookie_name,
        value=cookie_val,
        max_age=settings.session_ttl_sec,
        httponly=True,
        samesite="lax",
        secure=is_https_request(request, settings),
        path="/",
    )
    return AuthResponseOut(authenticated=True, user=user)


@router.post("/logout", response_model=AuthResponseOut)
def logout(request: Request, response: Response) -> AuthResponseOut:
    settings = get_settings()
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_https_request(request, settings),
    )
    response.headers["Clear-Site-Data"] = '"cookies"'
    return AuthResponseOut(authenticated=False, user=None)
