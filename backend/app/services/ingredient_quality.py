"""Deterministic ingredient quality checks and shopping-family assignment."""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ingredient, IngredientFamily, RecipeIngredient

NORMALIZATION_VERSION = 1

DESCRIPTOR_TOKENS = frozenset(
    {
        "choice",
        "coarse",
        "coarsely",
        "baby",
        "bottled",
        "dry",
        "fine",
        "finely",
        "fresh",
        "freshly",
        "frozen",
        "good",
        "large",
        "long",
        "medium",
        "optional",
        "quality",
        "small",
        "thick",
        "thin",
        "whole",
        "unflavored",
    }
)
GENERIC_NAMES = frozenset(
    {
        "as needed",
        "ingredient",
        "ingredients",
        "more",
        "optional",
        "to serve",
        "to taste",
        "your choice",
    }
)
MEAT_FAMILIES = frozenset(
    {
        "beef",
        "chicken",
        "duck",
        "goat",
        "ham",
        "lamb",
        "pork",
        "prosciutto",
        "rabbit",
        "sausage",
        "turkey",
        "veal",
        "venison",
    }
)
DIMENSIONAL_RE = re.compile(
    r"(?i)(?:^|\b)\d+(?:\s+\d+/\d+|/\d+)?[- ](?:inch|cm|centimeter|mm|millimeter)"
)


def normalized_name(value: object) -> str:
    return " ".join(str(value or "").casefold().strip().split())


def ingredient_quality_flags(name: str, raw_text: str | None = None) -> list[str]:
    normalized = normalized_name(name)
    words = re.findall(r"[a-z]+", normalized)
    flags: list[str] = []
    if not words:
        flags.append("no_food_name")
    elif normalized in GENERIC_NAMES:
        flags.append("generic_name")
    elif set(words).issubset(DESCRIPTOR_TOKENS):
        flags.append("descriptor_only")
    if re.match(r"^\d", normalized):
        flags.append("numeric_prefix")
    if DIMENSIONAL_RE.search(normalized) or (
        raw_text is not None
        and DIMENSIONAL_RE.search(raw_text)
        and re.match(r"^\d", normalized)
    ):
        flags.append("dimensional_name")
    if len(normalized) > 120:
        flags.append("overlong_name")
    return flags


def parse_status_for_flags(flags: Iterable[str]) -> str:
    flag_set = set(flags)
    if flag_set & {"descriptor_only", "generic_name", "no_food_name"}:
        return "invalid"
    if flag_set:
        return "suspect"
    return "valid"


def shopping_family_name(canonical_name: str) -> str:
    normalized = normalized_name(canonical_name)
    words = set(re.findall(r"[a-z]+", normalized))
    for family in sorted(MEAT_FAMILIES):
        if family in words:
            return family
    return normalized


def assess_recipe_ingredient(item: RecipeIngredient) -> tuple[str, list[str]]:
    flags = ingredient_quality_flags(item.ingredient.name, item.raw_text)
    return parse_status_for_flags(flags), flags


async def assign_ingredient_metadata(
    db: AsyncSession,
    ingredients: list[Ingredient],
) -> None:
    """Assign deterministic quality flags and shopping families."""
    if not ingredients:
        return
    root_ids = {
        ingredient.canonical_id or ingredient.id
        for ingredient in ingredients
    }
    roots = {
        ingredient.id: ingredient
        for ingredient in await db.scalars(
            select(Ingredient).where(Ingredient.id.in_(root_ids))
        )
    }
    family_names = {
        shopping_family_name(
            roots.get(ingredient.canonical_id or ingredient.id, ingredient).name
        )
        for ingredient in ingredients
    }
    existing_families = {
        family.name: family
        for family in await db.scalars(
            select(IngredientFamily).where(
                func.lower(IngredientFamily.name).in_(family_names)
            )
        )
    }
    for family_name in sorted(family_names):
        if family_name not in existing_families:
            family = IngredientFamily(name=family_name)
            db.add(family)
            existing_families[family_name] = family
    await db.flush()

    for ingredient in ingredients:
        root = roots.get(ingredient.canonical_id or ingredient.id, ingredient)
        family_name = shopping_family_name(root.name)
        family = existing_families[family_name]
        family.category = family.category or root.category or ingredient.category
        ingredient.family_id = family.id
        ingredient.quality_flags = ingredient_quality_flags(ingredient.name)
        ingredient.normalization_version = NORMALIZATION_VERSION
