from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.cookies import (
    clear_refresh_cookie,
    read_refresh_cookie,
    require_trusted_origin,
    set_refresh_cookie,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_fingerprint,
    verify_password,
)
from app.models import RefreshToken, User
from app.schemas.api import (
    AccessTokenResponse,
    LoginRequest,
    Message,
    PasswordChangeRequest,
    UserCreate,
    UserOut,
)
from app.services.rate_limits import client_ip, enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)


async def issue_pair(
    db: DB,
    user: User,
    user_agent: str | None,
    response: Response,
) -> AccessTokenResponse:
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
    set_refresh_cookie(response, refresh)
    return AccessTokenResponse(
        access_token=access,
        expires_in=expires_in,
    )


@router.post(
    "/register",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: Request,
    body: UserCreate,
    db: DB,
    response: Response,
    user_agent: str | None = Header(default=None),
) -> AccessTokenResponse:
    await enforce_rate_limit(
        request,
        scope="auth-register",
        identity=client_ip(request),
        limit=settings.auth_rate_limit_per_minute,
        window_seconds=60,
    )
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
    return await issue_pair(db, user, user_agent, response)


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    request: Request,
    body: LoginRequest,
    db: DB,
    response: Response,
    user_agent: str | None = Header(default=None),
) -> AccessTokenResponse:
    await enforce_rate_limit(
        request,
        scope="auth-login",
        identity=client_ip(request),
        limit=settings.auth_rate_limit_per_minute,
        window_seconds=60,
    )
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    candidate_hash = (
        user.password_hash if user is not None and user.is_active else DUMMY_PASSWORD_HASH
    )
    password_valid = verify_password(body.password, candidate_hash)
    if user is None or not user.is_active or not password_valid:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return await issue_pair(db, user, user_agent, response)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: DB,
    user_agent: str | None = Header(default=None),
) -> AccessTokenResponse:
    require_trusted_origin(request)
    refresh_cookie = read_refresh_cookie(request)
    try:
        payload = decode_token(refresh_cookie, "refresh")
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
    if stored is None or expired(stored.expires_at):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    if stored.revoked_at is not None:
        if stored.replaced_by_id is not None:
            user = await db.scalar(
                select(User).where(User.id == user_id).with_for_update()
            )
            if user is not None:
                user.credentials_version = (user.credentials_version or 0) + 1
                await db.execute(
                    update(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                    )
                    .values(revoked_at=datetime.now(UTC))
                )
                await db.commit()
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
    set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(
        access_token=access,
        expires_in=expires_in,
    )


@router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response, db: DB) -> Message:
    require_trusted_origin(request)
    refresh_cookie = request.cookies.get(settings.refresh_cookie_name)
    clear_refresh_cookie(response)
    if not refresh_cookie:
        return Message(detail="Logged out")
    try:
        payload = decode_token(refresh_cookie, "refresh")
        user_id = UUID(payload["sub"])
        stored = await db.scalar(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
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


@router.post("/change-password", response_model=AccessTokenResponse)
async def change_password(
    body: PasswordChangeRequest,
    db: DB,
    user: CurrentUser,
    response: Response,
    user_agent: str | None = Header(default=None),
) -> AccessTokenResponse:
    locked_user = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_user is None or not verify_password(
        body.current_password, locked_user.password_hash
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    locked_user.password_hash = hash_password(body.new_password)
    locked_user.credentials_version = (locked_user.credentials_version or 0) + 1
    now = datetime.now(UTC)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == locked_user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    await db.refresh(locked_user)
    return await issue_pair(db, locked_user, user_agent, response)
