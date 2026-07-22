import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.rate_limits import consume_global_llm_quota


@pytest.mark.asyncio
async def test_login_rate_limit_returns_retry_after(client: AsyncClient) -> None:
    for _ in range(settings.auth_rate_limit_per_minute):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "incorrect-password"},
        )
        assert response.status_code == 401

    limited = await client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "incorrect-password"},
    )

    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


@pytest.mark.asyncio
async def test_global_llm_quota_fails_closed_after_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_daily_call_limit", 1)
    await consume_global_llm_quota()

    with pytest.raises(RuntimeError, match="budget"):
        await consume_global_llm_quota()
