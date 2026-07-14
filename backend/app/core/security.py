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

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# Short denylist of passwords that routinely appear in breach corpora.
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty123",
        "letmein1",
        "iloveyou",
        "admin123",
        "welcome1",
        "monkey123",
        "dragon123",
        "master123",
        "login123",
        "abc12345",
        "passw0rd",
        "changeme",
        "changeme1",
    }
)


def validate_password_strength(password: str) -> str:
    """NIST-aligned checks: length bounds, no edge whitespace, reject common passwords."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters")
    if password != password.strip():
        raise ValueError("Password must not start or end with whitespace")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common; choose a stronger one")
    return password


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: UUID, credentials_version: int = 0) -> tuple[str, int]:
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "cv": credentials_version,
            "exp": expires,
            "iat": datetime.now(UTC),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, settings.access_token_minutes * 60


def create_refresh_token(
    user_id: UUID,
    credentials_version: int = 0,
) -> tuple[str, str, datetime]:
    jti = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "jti": jti,
            "type": "refresh",
            "cv": credentials_version,
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
