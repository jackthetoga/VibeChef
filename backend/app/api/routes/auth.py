from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, CurrentUser
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_fingerprint,
    verify_password,
)
from app.models import RefreshToken, User
from app.schemas.api import (
    LoginRequest,
    Message,
    PasswordChangeRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)


async def issue_pair(db: DB, user: User, user_agent: str | None) -> TokenPair:
    access, expires_in = create_access_token(user.id, user.credentials_version)
    refresh, jti, expires_at = create_refresh_token(user.id, user.credentials_version)
    db.add(
        RefreshToken(
            user_id=user.id,
            jti_hash=token_fingerprint(jti),
            expires_at=expires_at,
            user_agent=user_agent,
        )
    )
    await db.commit()
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    db: DB,
    user_agent: str | None = Header(default=None),
) -> TokenPair:
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from None
    return await issue_pair(db, user, user_agent)


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    db: DB,
    user_agent: str | None = Header(default=None),
) -> TokenPair:
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return await issue_pair(db, user, user_agent)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    db: DB,
    user_agent: str | None = Header(default=None),
) -> TokenPair:
    try:
        payload = decode_token(body.refresh_token, "refresh")
        user_id = UUID(payload["sub"])
        jti_hash = token_fingerprint(payload["jti"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token") from None

    stored = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.jti_hash == jti_hash,
        ).with_for_update()
    )
    if stored is None or stored.revoked_at is not None or expired(stored.expires_at):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User is unavailable")
    try:
        token_version = int(payload.get("cv") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token") from None
    if token_version != user.credentials_version:
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    access, expires_in = create_access_token(user.id, user.credentials_version)
    refresh_token, new_jti, expires_at = create_refresh_token(
        user.id,
        user.credentials_version,
    )
    replacement = RefreshToken(
        user_id=user.id,
        jti_hash=token_fingerprint(new_jti),
        expires_at=expires_at,
        user_agent=user_agent,
    )
    db.add(replacement)
    await db.flush()
    stored.revoked_at = datetime.now(UTC)
    stored.replaced_by_id = replacement.id
    await db.commit()
    return TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/logout", response_model=Message)
async def logout(body: RefreshRequest, db: DB, user: CurrentUser) -> Message:
    try:
        payload = decode_token(body.refresh_token, "refresh")
        stored = await db.scalar(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                RefreshToken.jti_hash == token_fingerprint(payload["jti"]),
            )
        )
    except (ValueError, KeyError):
        stored = None
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        await db.commit()
    return Message(detail="Logged out")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.post("/change-password", response_model=TokenPair)
async def change_password(
    body: PasswordChangeRequest,
    db: DB,
    user: CurrentUser,
    user_agent: str | None = Header(default=None),
) -> TokenPair:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    user.credentials_version = (user.credentials_version or 0) + 1
    now = datetime.now(UTC)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    await db.refresh(user)
    return await issue_pair(db, user, user_agent)
