"""Backfill recipe tags via heuristic (+ LLM fallback). Skips manual/myplate locks."""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models import Recipe, RecipeIngredient
from app.services.recipe_tagging import assign_recipe_tags, has_source_tags

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
SKIP_SOURCES = {"manual", "myplate"}


async def backfill_recipe_tags(*, limit: int | None = None, force: bool = False) -> dict[str, int]:
    """Retag recipes that are not manually locked.

    Skips ``tag_source=manual``. Skips ``myplate`` unless ``force`` and the recipe
    somehow lacks useful filter tags. Never overwrites manual.
    """
    processed = 0
    updated = 0
    skipped = 0
    cursor: uuid.UUID | None = None

    while True:
        batch_limit = BATCH_SIZE
        if limit is not None:
            remaining = limit - processed
            if remaining <= 0:
                break
            batch_limit = min(BATCH_SIZE, remaining)

        async with SessionLocal() as db:
            statement = (
                select(Recipe)
                .options(
                    selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient)
                )
                .order_by(Recipe.id)
                .limit(batch_limit)
            )
            if cursor is not None:
                statement = statement.where(Recipe.id > cursor)
            if not force:
                statement = statement.where(
                    or_(Recipe.tag_source.is_(None), Recipe.tag_source.notin_(SKIP_SOURCES))
                )
            else:
                statement = statement.where(
                    or_(Recipe.tag_source.is_(None), Recipe.tag_source != "manual")
                )

            recipes = list(await db.scalars(statement))
            if not recipes:
                break

            cursor = recipes[-1].id
            for recipe in recipes:
                processed += 1
                if recipe.tag_source == "manual":
                    skipped += 1
                    continue
                if (
                    recipe.tag_source == "myplate"
                    and has_source_tags(list(recipe.tags or []), recipe.cuisine)
                    and not force
                ):
                    skipped += 1
                    continue

                names = [
                    item.ingredient.name
                    for item in recipe.recipe_ingredients
                    if item.ingredient is not None
                ]
                categories = [
                    item.ingredient.category if item.ingredient is not None else None
                    for item in recipe.recipe_ingredients
                ]
                assignment = await assign_recipe_tags(
                    title=recipe.title,
                    cuisine=recipe.cuisine,
                    tags=list(recipe.tags or []),
                    ingredient_names=names,
                    ingredient_categories=categories,
                    steps=list(recipe.steps or []),
                    prefer_existing=False,
                )
                if not assignment.is_useful and not assignment.tags and not assignment.cuisine:
                    skipped += 1
                    continue

                recipe.cuisine = assignment.cuisine or recipe.cuisine
                recipe.tags = assignment.tags
                recipe.tag_source = assignment.tag_source or recipe.tag_source
                updated += 1

            await db.commit()
            logger.info(
                "Recipe tag backfill: processed=%s updated=%s skipped=%s",
                processed,
                updated,
                skipped,
            )

    logger.info(
        "Recipe tag backfill complete: processed=%s updated=%s skipped=%s",
        processed,
        updated,
        skipped,
    )
    return {"processed": processed, "updated": updated, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill recipe filter tags")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Also retag myplate/heuristic/llm recipes (never overwrites manual)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill_recipe_tags(limit=args.limit, force=args.force))


if __name__ == "__main__":
    main()
