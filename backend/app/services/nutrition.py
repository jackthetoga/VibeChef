"""Estimate recipe-level nutrition by summing ingredient macros."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import (
    Ingredient,
    NutritionBasis,
    NutritionSource,
    Recipe,
    RecipeIngredient,
)
from app.services.fdc_client import FdcClient, FoodMacros
from app.services.food_nutrition_cache import (
    get_cached_macros,
    put_cached_macros,
    seed_food_nutrition_cache,
)
from app.services.ingredient_conversions import get_ingredient_conversion
from app.services.units import UNIT_DEFINITIONS, normalize_unit, quantity_in_grams

logger = logging.getLogger(__name__)

TO_TASTE_RE = re.compile(r"\bto taste\b|\bas needed\b|\boptional\b", re.IGNORECASE)
HUNDRED = Decimal("100")
ZERO = Decimal("0")
TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")


@dataclass(frozen=True)
class RecipeNutritionEstimate:
    calories: Decimal
    protein_grams: Decimal
    carbs_grams: Decimal
    fat_grams: Decimal
    coverage: Decimal
    basis: NutritionBasis
    line_count: int
    matched_lines: int


def _quantize(value: Decimal, places: Decimal = TWOPLACES) -> Decimal:
    return value.quantize(places, rounding=ROUND_HALF_UP)


def recipe_ingredient_grams(
    quantity: Decimal | None,
    unit: str | None,
    ingredient_name: str,
    *,
    raw_text: str = "",
) -> Decimal | None:
    """Best-effort mass for a recipe line. Returns None when unknown."""
    if quantity is None:
        return None
    if TO_TASTE_RE.search(raw_text) and normalize_unit(unit) is None:
        return None

    profile = get_ingredient_conversion(ingredient_name)
    unit_name = normalize_unit(unit)
    if unit_name:
        definition = UNIT_DEFINITIONS.get(unit_name)
        if definition is None:
            return None
        if definition.dimension == "mass":
            return quantity * definition.factor
        if profile is None:
            return None
        return quantity_in_grams(quantity, definition, profile)

    # No unit: treat as count when we know item weight (e.g. "2 eggs").
    if profile is not None and profile.grams_per_item is not None:
        return quantity * profile.grams_per_item
    return None


def select_lines_for_estimation(
    lines: Iterable[RecipeIngredient],
) -> list[RecipeIngredient]:
    """Collapse OR alternate groups to the first (lowest position) option."""
    chosen: list[RecipeIngredient] = []
    seen_groups: set[uuid.UUID] = set()
    ordered = sorted(lines, key=lambda line: line.position)
    for line in ordered:
        group = line.alternate_group_id
        if group is not None:
            if group in seen_groups:
                continue
            seen_groups.add(group)
        chosen.append(line)
    return chosen


def _scale_macros(macros: FoodMacros, grams: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    factor = grams / HUNDRED
    return (
        macros.calories_per_100g * factor,
        macros.protein_per_100g * factor,
        macros.carbs_per_100g * factor,
        macros.fat_per_100g * factor,
    )


def apply_printed_nutrition_metadata(recipe: Recipe) -> None:
    """Mark recipes that already have extracted printed macros."""
    has_macros = any(
        value is not None
        for value in (
            recipe.calories,
            recipe.protein_grams,
            recipe.carbs_grams,
            recipe.fat_grams,
        )
    )
    if not has_macros:
        return
    recipe.nutrition_source = NutritionSource.printed
    recipe.nutrition_basis = (
        NutritionBasis.per_serving
        if recipe.servings is not None and recipe.servings > 0
        else NutritionBasis.whole_recipe
    )
    recipe.nutrition_coverage = Decimal("1")


async def ensure_ingredient_macros(
    db: AsyncSession,
    ingredient: Ingredient,
    client: FdcClient,
) -> FoodMacros | None:
    """Resolve macros: ingredient row → shared food cache → seed/USDA → persist both."""
    if (
        ingredient.calories_per_100g is not None
        and ingredient.protein_per_100g is not None
        and ingredient.carbs_per_100g is not None
        and ingredient.fat_per_100g is not None
    ):
        return FoodMacros(
            fdc_id=ingredient.fdc_id,
            description=ingredient.fdc_description,
            calories_per_100g=Decimal(ingredient.calories_per_100g),
            protein_per_100g=Decimal(ingredient.protein_per_100g),
            carbs_per_100g=Decimal(ingredient.carbs_per_100g),
            fat_per_100g=Decimal(ingredient.fat_per_100g),
            source="cache",
        )

    cached, cache_hit = await get_cached_macros(db, ingredient.name)
    if cache_hit:
        if cached is None:
            return None
        ingredient.fdc_id = cached.fdc_id
        ingredient.fdc_description = cached.description
        ingredient.calories_per_100g = cached.calories_per_100g
        ingredient.protein_per_100g = cached.protein_per_100g
        ingredient.carbs_per_100g = cached.carbs_per_100g
        ingredient.fat_per_100g = cached.fat_per_100g
        return cached

    # Prefer seed without hitting USDA; FdcClient resolves seed first when no API needed.
    macros = await client.resolve_macros(ingredient.name)
    await put_cached_macros(
        db,
        ingredient.name,
        macros,
        source=macros.source if macros else "miss",
    )
    if macros is None:
        return None

    ingredient.fdc_id = macros.fdc_id
    ingredient.fdc_description = macros.description
    ingredient.calories_per_100g = macros.calories_per_100g
    ingredient.protein_per_100g = macros.protein_per_100g
    ingredient.carbs_per_100g = macros.carbs_per_100g
    ingredient.fat_per_100g = macros.fat_per_100g
    return macros


async def estimate_recipe_nutrition(
    db: AsyncSession,
    recipe: Recipe,
    *,
    client: FdcClient | None = None,
    force: bool = False,
) -> RecipeNutritionEstimate | None:
    """Estimate and persist nutrition for one recipe. Skips printed macros unless force."""
    if (
        not force
        and recipe.nutrition_source == NutritionSource.printed
        and any(
            value is not None
            for value in (
                recipe.calories,
                recipe.protein_grams,
                recipe.carbs_grams,
                recipe.fat_grams,
            )
        )
    ):
        return None
    if not force and recipe.nutrition_source == NutritionSource.manual:
        return None

    fdc = client or FdcClient()
    lines = select_lines_for_estimation(recipe.recipe_ingredients)
    if not lines:
        return None

    matched_grams = ZERO
    total_grams = ZERO
    matched_lines = 0
    calories = ZERO
    protein = ZERO
    carbs = ZERO
    fat = ZERO

    for line in lines:
        name = line.ingredient.name
        grams = recipe_ingredient_grams(
            line.quantity,
            line.unit,
            name,
            raw_text=line.raw_text or "",
        )
        if grams is None or grams <= 0:
            continue
        total_grams += grams
        macros = await ensure_ingredient_macros(db, line.ingredient, fdc)
        if macros is None:
            continue
        line_cal, line_pro, line_carb, line_fat = _scale_macros(macros, grams)
        calories += line_cal
        protein += line_pro
        carbs += line_carb
        fat += line_fat
        matched_grams += grams
        matched_lines += 1

    if matched_lines == 0 or matched_grams <= 0:
        return None

    coverage = _quantize(matched_grams / total_grams, FOURPLACES) if total_grams > 0 else ZERO
    min_coverage = Decimal(str(settings.nutrition_min_coverage))
    # Still write estimates below threshold; coverage flags low confidence for the UI.

    basis = NutritionBasis.whole_recipe
    divisor = Decimal("1")
    if recipe.servings is not None and recipe.servings > 0:
        basis = NutritionBasis.per_serving
        divisor = Decimal(recipe.servings)

    estimate = RecipeNutritionEstimate(
        calories=_quantize(calories / divisor),
        protein_grams=_quantize(protein / divisor),
        carbs_grams=_quantize(carbs / divisor),
        fat_grams=_quantize(fat / divisor),
        coverage=coverage,
        basis=basis,
        line_count=len(lines),
        matched_lines=matched_lines,
    )

    recipe.calories = estimate.calories
    recipe.protein_grams = estimate.protein_grams
    recipe.carbs_grams = estimate.carbs_grams
    recipe.fat_grams = estimate.fat_grams
    recipe.nutrition_source = NutritionSource.estimated
    recipe.nutrition_basis = estimate.basis
    recipe.nutrition_coverage = estimate.coverage

    if coverage < min_coverage:
        logger.info(
            "Low nutrition coverage for recipe %s (%s): %s",
            recipe.id,
            recipe.title,
            coverage,
        )
    return estimate


async def estimate_nutrition_for_cookbook(
    cookbook_id: str | uuid.UUID,
    *,
    force: bool = False,
) -> int:
    """Estimate nutrition for all recipes in a cookbook. Returns updated count."""
    cookbook_uuid = uuid.UUID(str(cookbook_id))
    client = FdcClient()
    updated = 0

    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        await seed_food_nutrition_cache(db)
        recipes = list(
            await db.scalars(
                select(Recipe)
                .where(Recipe.cookbook_id == cookbook_uuid)
                .options(
                    selectinload(Recipe.recipe_ingredients).selectinload(
                        RecipeIngredient.ingredient
                    )
                )
                .order_by(Recipe.created_at, Recipe.id)
            )
        )
        for recipe in recipes:
            result = await estimate_recipe_nutrition(
                db, recipe, client=client, force=force
            )
            if result is not None:
                updated += 1
        await db.commit()

    logger.info(
        "Nutrition estimate for cookbook %s: updated=%s of %s",
        cookbook_id,
        updated,
        len(recipes),
    )
    return updated


async def estimate_nutrition_for_all_recipes(*, force: bool = False) -> int:
    """Backfill nutrition across the library. Returns updated recipe count."""
    client = FdcClient()
    updated = 0
    cursor: uuid.UUID | None = None
    batch_size = 50

    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        await seed_food_nutrition_cache(db)
        await db.commit()

    while True:
        async with SessionLocal() as db:
            statement = (
                select(Recipe)
                .options(
                    selectinload(Recipe.recipe_ingredients).selectinload(
                        RecipeIngredient.ingredient
                    )
                )
                .order_by(Recipe.id)
                .limit(batch_size)
            )
            if cursor is not None:
                statement = statement.where(Recipe.id > cursor)
            recipes = list(await db.scalars(statement))
            if not recipes:
                break
            cursor = recipes[-1].id
            for recipe in recipes:
                result = await estimate_recipe_nutrition(
                    db, recipe, client=client, force=force
                )
                if result is not None:
                    updated += 1
            await db.commit()
            logger.info("Nutrition backfill progress: updated=%s", updated)

    return updated
