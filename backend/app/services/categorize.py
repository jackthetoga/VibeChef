from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.services.common_ingredients import COMMON_INGREDIENT_CATEGORIES, INGREDIENT_CATEGORIES
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)

CATEGORY_SET = {category.casefold(): category for category in INGREDIENT_CATEGORIES}


async def categorize_ingredient(name: str) -> str | None:
    """Return a pantry category for a free-typed ingredient name."""
    normalized = " ".join(name.lower().split())
    if not normalized:
        return None

    known = COMMON_INGREDIENT_CATEGORIES.get(normalized)
    if known:
        return known

    if not settings.openai_api_key:
        return None

    categories = ", ".join(INGREDIENT_CATEGORIES)
    prompt = (
        "Classify this kitchen ingredient into exactly one pantry category.\n"
        f"Allowed categories: {categories}\n"
        'Respond with JSON only: {"category": "<one allowed category>"}\n'
        f"Ingredient: {normalized}"
    )
    try:
        content = await chat_completion(
            system=(
                "You categorize grocery ingredients for a home pantry. "
                "Never invent categories outside the allowed list."
            ),
            user=prompt,
            temperature=0,
            response_format={"type": "json_object"},
            timeout=12.0,
        )
        data = json.loads(content)
        raw = str(data.get("category") or "").strip()
        return CATEGORY_SET.get(raw.casefold())
    except Exception:
        logger.exception("Failed to categorize ingredient %r", normalized)
        return None
