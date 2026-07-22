from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Hashable
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_memory_counts: dict[tuple[Hashable, int], int] = {}
_memory_lock = asyncio.Lock()
_INCREMENT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
    fail_closed: bool = False,
) -> None:
    if not settings.rate_limit_enabled or limit <= 0:
        return

    now = int(time.time())
    bucket = now // window_seconds
    retry_after = window_seconds - (now % window_seconds)
    key = f"rate:{scope}:{identity}:{bucket}"
    pool = getattr(request.app.state, "arq_pool", None)

    if pool is not None:
        try:
            count = int(await pool.eval(_INCREMENT_SCRIPT, 1, key, window_seconds + 1))
        except Exception as exc:
            logger.warning("Redis rate limit check failed for %s: %s", scope, exc)
            if fail_closed:
                raise HTTPException(
                    status_code=503,
                    detail="Usage controls are temporarily unavailable",
                ) from None
        else:
            if count > limit:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
            return
    elif settings.is_production and fail_closed:
        raise HTTPException(
            status_code=503,
            detail="Usage controls are temporarily unavailable",
        )

    memory_key = (key, bucket)
    async with _memory_lock:
        count = _memory_counts.get(memory_key, 0) + 1
        _memory_counts[memory_key] = count
        if len(_memory_counts) > 10_000:
            cutoff = bucket - 2
            stale = [item for item in _memory_counts if item[1] < cutoff]
            for item in stale:
                _memory_counts.pop(item, None)
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


async def reset_memory_rate_limits() -> None:
    async with _memory_lock:
        _memory_counts.clear()


async def consume_global_llm_quota() -> None:
    """Reserve one provider call, failing closed in production."""
    limit = settings.llm_daily_call_limit
    if not settings.rate_limit_enabled or limit <= 0:
        return

    day = datetime.now(UTC).date().isoformat()
    key = f"quota:llm:global:{day}"
    if settings.redis_url and settings.app_env != "test":
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            count = int(await client.eval(_INCREMENT_SCRIPT, 1, key, 25 * 60 * 60))
        except Exception as exc:
            logger.warning("Redis LLM quota check failed: %s", exc)
            if settings.is_production:
                raise RuntimeError("LLM usage controls are unavailable") from None
        else:
            if count > limit:
                raise RuntimeError("Daily LLM call budget has been exhausted")
            return
        finally:
            await client.aclose()
    elif settings.is_production:
        raise RuntimeError("LLM usage controls are unavailable")

    memory_key = ("llm-global", hash(day))
    async with _memory_lock:
        count = _memory_counts.get(memory_key, 0) + 1
        _memory_counts[memory_key] = count
    if count > limit:
        raise RuntimeError("Daily LLM call budget has been exhausted")
