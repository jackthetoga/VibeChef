from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.rate_limits import consume_global_llm_quota

logger = logging.getLogger(__name__)

UserContent = str | list[dict[str, Any]]


async def chat_completion(
    *,
    system: str,
    user: UserContent,
    temperature: float = 0,
    max_tokens: int | None = None,
    response_format: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> str:
    """Call the configured OpenAI-compatible chat API (DeepSeek by default).

    ``user`` may be a plain string or a multimodal content list (text + image_url parts).
    """
    if not settings.llm_enabled:
        raise RuntimeError("External AI processing is not enabled")
    await consume_global_llm_quota()

    payload: dict = {
        "model": settings.openai_model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if response_format is not None:
        payload["response_format"] = response_format

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("LLM response content was not a string")
        return content
