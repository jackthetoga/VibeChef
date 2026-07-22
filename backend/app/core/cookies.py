from __future__ import annotations

import re

from fastapi import HTTPException, Request, Response

from app.core.config import settings


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=settings.refresh_cookie_path,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=settings.refresh_cookie_path,
    )


def read_refresh_cookie(request: Request) -> str:
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or missing refresh token")
    return token


def require_trusted_origin(request: Request) -> None:
    """Reject cross-site browser requests that can carry the refresh cookie."""
    origin = request.headers.get("origin")
    if not origin:
        return
    if origin in settings.cors_origins:
        return
    if settings.cors_origin_regex and re.fullmatch(settings.cors_origin_regex, origin):
        return
    raise HTTPException(status_code=403, detail="Untrusted request origin")
