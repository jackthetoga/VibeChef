import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: UUID) -> tuple[str, int]:
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode(
        {"sub": str(user_id), "type": "access", "exp": expires, "iat": datetime.now(UTC)},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, settings.access_token_minutes * 60


def create_refresh_token(user_id: UUID) -> tuple[str, str, datetime]:
    jti = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "jti": jti,
            "type": "refresh",
            "exp": expires,
            "iat": datetime.now(UTC),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, jti, expires


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError as exc:
        raise ValueError("Invalid or expired token") from exc
    if payload.get("type") != expected_type or not payload.get("sub"):
        raise ValueError("Invalid token type")
    return payload


def token_fingerprint(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()
