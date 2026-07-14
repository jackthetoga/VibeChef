import pytest
from httpx import AsyncClient


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

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first_tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "chef@example.com"

    rotated = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_tokens["refresh_token"]},
    )
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != first_tokens["refresh_token"]

    reused = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_tokens["refresh_token"]},
    )
    assert reused.status_code == 401

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
async def test_logout_cannot_revoke_another_users_refresh_token(client: AsyncClient) -> None:
    first = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "first@example.com", "password": "password-123"},
        )
    ).json()
    second = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "second@example.com", "password": "password-123"},
        )
    ).json()

    logged_out = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {first['access_token']}"},
        json={"refresh_token": second["refresh_token"]},
    )
    assert logged_out.status_code == 200

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": second["refresh_token"]},
    )
    assert refreshed.status_code == 200


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
