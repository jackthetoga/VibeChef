"""Persist USDA / seed nutrition lookups in Postgres to avoid API re-hits."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FoodNutritionCache
from app.services.fdc_client import FoodMacros
from app.services.fdc_seed import FDC_SEED_BY_NAME, normalize_food_name

logger = logging.getLogger(__name__)


def row_to_macros(row: FoodNutritionCache) -> FoodMacros | None:
    if not row.found:
        return None
    if (
        row.calories_per_100g is None
        or row.protein_per_100g is None
        or row.carbs_per_100g is None
        or row.fat_per_100g is None
    ):
        return None
    return FoodMacros(
        fdc_id=row.fdc_id,
        description=row.fdc_description,
        calories_per_100g=Decimal(row.calories_per_100g),
        protein_per_100g=Decimal(row.protein_per_100g),
        carbs_per_100g=Decimal(row.carbs_per_100g),
        fat_per_100g=Decimal(row.fat_per_100g),
        source=row.source or "cache",
    )


async def get_cached_macros(
    db: AsyncSession, name: str
) -> tuple[FoodMacros | None, bool]:
    """Return (macros, cache_hit). cache_hit True means do not call USDA again."""
    key = normalize_food_name(name)
    row = await db.scalar(
        select(FoodNutritionCache).where(FoodNutritionCache.query_name == key)
    )
    if row is None:
        return None, False
    if not row.found:
        return None, True
    return row_to_macros(row), True


async def put_cached_macros(
    db: AsyncSession,
    name: str,
    macros: FoodMacros | None,
    *,
    source: str | None = None,
) -> FoodNutritionCache:
    """Upsert a positive or negative cache entry for the normalized name."""
    key = normalize_food_name(name)
    row = await db.scalar(
        select(FoodNutritionCache).where(FoodNutritionCache.query_name == key)
    )
    if row is None:
        row = FoodNutritionCache(query_name=key, found=False, source=source or "fdc")
        db.add(row)

    if macros is None:
        row.found = False
        row.fdc_id = None
        row.fdc_description = None
        row.calories_per_100g = None
        row.protein_per_100g = None
        row.carbs_per_100g = None
        row.fat_per_100g = None
        row.source = source or "miss"
        return row

    row.found = True
    row.fdc_id = macros.fdc_id
    row.fdc_description = macros.description
    row.calories_per_100g = macros.calories_per_100g
    row.protein_per_100g = macros.protein_per_100g
    row.carbs_per_100g = macros.carbs_per_100g
    row.fat_per_100g = macros.fat_per_100g
    row.source = source or macros.source
    return row


async def seed_food_nutrition_cache(db: AsyncSession) -> int:
    """Load offline pantry seed macros into the shared cache. Returns inserted count."""
    inserted = 0
    for name, entry in FDC_SEED_BY_NAME.items():
        key = normalize_food_name(name)
        existing = await db.scalar(
            select(FoodNutritionCache.id).where(FoodNutritionCache.query_name == key)
        )
        if existing is not None:
            continue
        db.add(
            FoodNutritionCache(
                query_name=key,
                found=True,
                fdc_id=entry.fdc_id,
                fdc_description=entry.description,
                calories_per_100g=entry.calories,
                protein_per_100g=entry.protein,
                carbs_per_100g=entry.carbs,
                fat_per_100g=entry.fat,
                source="seed",
            )
        )
        inserted += 1
    if inserted:
        await db.flush()
        logger.info("Seeded food_nutrition_cache with %s pantry foods", inserted)
    return inserted
