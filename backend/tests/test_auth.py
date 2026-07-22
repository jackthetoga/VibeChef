import pytest
from httpx import AsyncClient


async def _register(
    client: AsyncClient,
    email: str = "chef@example.com",
    password: str = "correct-horse-battery",
    display_name: str | None = "Chef",
) -> dict:
    body: dict = {"email": email, "password": password}
    if display_name is not None:
        body["display_name"] = display_name
    response = await client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_register_login_refresh_rotation_and_me(client: AsyncClient) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "chef@example.com",
            "password": "correct-horse-battery",
            "display_name": "Chef",
        },
    )
    assert registered.status_code == 201
    first_tokens = registered.json()
    assert "refresh_token" not in first_tokens
    first_refresh = client.cookies.get("rf_refresh")
    assert first_refresh
    set_cookie = registered.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first_tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "chef@example.com"

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    assert "refresh_token" not in rotated.json()
    rotated_refresh = client.cookies.get("rf_refresh")
    assert rotated_refresh and rotated_refresh != first_refresh

    reused = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"rf_refresh={first_refresh}"},
    )
    assert reused.status_code == 401
    descendant = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"rf_refresh={rotated_refresh}"},
    )
    assert descendant.status_code == 401

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "CHEF@example.com", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_email_is_rejected(client: AsyncClient) -> None:
    body = {"email": "same@example.com", "password": "password-123"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_logout_revokes_and_clears_refresh_cookie(client: AsyncClient) -> None:
    await _register(client, email="logout@example.com")
    refresh_token = client.cookies.get("rf_refresh")
    assert refresh_token

    logged_out = await client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 200
    assert client.cookies.get("rf_refresh") is None

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"rf_refresh={refresh_token}"},
    )
    assert refreshed.status_code == 401


@pytest.mark.asyncio
async def test_cors_allows_loopback_development_origins(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"


@pytest.mark.asyncio
async def test_cors_rejects_untrusted_origins(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": "https://malicious.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_refresh_rejects_untrusted_origin(client: AsyncClient) -> None:
    await _register(client, email="origin@example.com")
    response = await client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": "https://malicious.example"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_register_rejects_common_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "password123"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_rotates_credentials_and_revokes_other_sessions(
    client: AsyncClient,
) -> None:
    first = await _register(client, email="changer@example.com")
    first_refresh = client.cookies.get("rf_refresh")
    assert first_refresh
    second_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "changer@example.com", "password": "correct-horse-battery"},
    )
    assert second_login.status_code == 200
    other_refresh = client.cookies.get("rf_refresh")
    assert other_refresh and other_refresh != first_refresh

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {first['access_token']}"},
        json={
            "current_password": "correct-horse-battery",
            "new_password": "new-correct-horse-42",
        },
    )
    assert changed.status_code == 200
    new_tokens = changed.json()
    assert "refresh_token" not in new_tokens
    assert client.cookies.get("rf_refresh") not in {first_refresh, other_refresh}

    old_refresh = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"rf_refresh={first_refresh}"},
    )
    assert old_refresh.status_code == 401

    other_session = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"rf_refresh={other_refresh}"},
    )
    assert other_session.status_code == 401

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "changer@example.com", "password": "correct-horse-battery"},
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "changer@example.com", "password": "new-correct-horse-42"},
    )
    assert new_login.status_code == 200

    stale_me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert stale_me.status_code == 401

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert me.status_code == 200


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password(client: AsyncClient) -> None:
    tokens = await _register(client, email="wrong-current@example.com")
    response = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={
            "current_password": "not-the-real-password",
            "new_password": "new-correct-horse-42",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect"


@pytest.mark.asyncio
async def test_change_password_rejects_same_password(client: AsyncClient) -> None:
    tokens = await _register(client, email="same-password@example.com")
    response = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={
            "current_password": "correct-horse-battery",
            "new_password": "correct-horse-battery",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "correct-horse-battery",
            "new_password": "new-correct-horse-42",
        },
    )
    assert response.status_code == 401
