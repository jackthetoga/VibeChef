from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Ingredient
from app.services.canonicalize import BATCH_SIZE, canonicalize_ingredients

logger = logging.getLogger(__name__)


async def backfill_canonical_ingredients() -> tuple[int, int]:
    if not settings.llm_enabled:
        raise RuntimeError("OPENAI_API_KEY is required for ingredient canonicalization")

    attempted = 0
    resolved = 0
    cursor: uuid.UUID | None = None

    while True:
        async with SessionLocal() as db:
            statement = (
                select(Ingredient)
                .where(Ingredient.canonical_id.is_(None))
                .order_by(Ingredient.id)
                .limit(BATCH_SIZE)
            )
            if cursor is not None:
                statement = statement.where(Ingredient.id > cursor)
            ingredients = list(await db.scalars(statement))
            if not ingredients:
                break

            cursor = ingredients[-1].id
            attempted += len(ingredients)
            await canonicalize_ingredients(db, ingredients, timeout=120.0)
            resolved += sum(ingredient.canonical_id is not None for ingredient in ingredients)
            await db.commit()
            logger.info(
                "Canonical ingredient backfill: attempted=%s resolved=%s",
                attempted,
                resolved,
            )

    async with SessionLocal() as db:
        remaining = int(
            await db.scalar(
                select(func.count(Ingredient.id)).where(Ingredient.canonical_id.is_(None))
            )
            or 0
        )
    logger.info(
        "Canonical ingredient backfill complete: attempted=%s resolved=%s remaining=%s",
        attempted,
        resolved,
        remaining,
    )
    return resolved, remaining


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill_canonical_ingredients())


if __name__ == "__main__":
    main()
