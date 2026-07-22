"""Rank pantry additions by the recipes they would make cookable."""

from __future__ import annotations

import heapq
import itertools
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Cookbook, Ingredient, PantryItem, Recipe, RecipeIngredient, UploadStatus
from app.services.ingredient_quality import (
    assess_recipe_ingredient,
    shopping_family_name,
)
from app.services.pantry_matching import PantryMatcher
from app.services.recipe_images import recipe_image_url

MAX_CANDIDATES_BY_SIZE = {1: 1000, 2: 120, 3: 70}


@dataclass
class RecipeRequirement:
    recipe: Recipe
    groups: list[frozenset[uuid.UUID]]


@dataclass
class CandidateState:
    ingredient_id: uuid.UUID
    status: str = "missing"
    pantry_item_id: uuid.UUID | None = None
    potential_recipes: int = 0


@dataclass
class UnlockScoreIndex:
    unlock_bits: dict[frozenset[uuid.UUID], int]
    impact_bits: dict[uuid.UUID, int]


def _ingredient_groups(recipe: Recipe) -> list[list[RecipeIngredient]]:
    groups: dict[object, list[RecipeIngredient]] = {}
    order: list[object] = []
    for item in recipe.recipe_ingredients:
        if item.ingredient.staple:
            continue
        key = item.alternate_group_id or item.id
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    return [groups[key] for key in order]


async def _load_unlock_problem(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> tuple[
    list[RecipeRequirement],
    dict[uuid.UUID, CandidateState],
    dict[uuid.UUID, Ingredient],
    int,
]:
    pantry_items = list(
        await db.scalars(
            select(PantryItem)
            .options(selectinload(PantryItem.ingredient))
            .where(PantryItem.user_id == user_id)
        )
    )
    recipes = list(
        await db.scalars(
            select(Recipe)
            .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
            .options(
                selectinload(Recipe.recipe_ingredients).selectinload(
                    RecipeIngredient.ingredient
                )
            )
            .where(
                Cookbook.user_id == user_id,
                Cookbook.enabled.is_(True),
                Cookbook.status == UploadStatus.completed,
            )
            .order_by(Recipe.title, Recipe.id)
        )
    )
    matcher = PantryMatcher(pantry_items)
    requirements: list[RecipeRequirement] = []
    candidates: dict[uuid.UUID, CandidateState] = {}
    excluded_recipe_count = 0

    for recipe in recipes:
        missing_groups: list[frozenset[uuid.UUID]] = []
        recipe_invalid = False
        for group in _ingredient_groups(recipe):
            valid_items: list[RecipeIngredient] = []
            for item in group:
                dynamic_status, _ = assess_recipe_ingredient(item)
                if item.parse_status == "valid" and dynamic_status == "valid":
                    valid_items.append(item)
            if not valid_items:
                recipe_invalid = True
                break
            matches = [(item, matcher.match(item)) for item in valid_items]
            if any(match.satisfied for _, match in matches):
                continue
            candidate_ids: set[uuid.UUID] = set()
            for item, match in matches:
                key = item.ingredient.canonical_id or item.ingredient_id
                candidate_ids.add(key)
                candidate = candidates.setdefault(key, CandidateState(ingredient_id=key))
                if match.status == "insufficient":
                    candidate.status = "insufficient"
                    if match.pantry_item is not None:
                        candidate.pantry_item_id = match.pantry_item.id
            if candidate_ids:
                missing_groups.append(frozenset(candidate_ids))
        if recipe_invalid:
            excluded_recipe_count += 1
            continue
        if missing_groups:
            requirement = RecipeRequirement(recipe=recipe, groups=missing_groups)
            requirements.append(requirement)
            for key in set().union(*missing_groups):
                candidates[key].potential_recipes += 1

    canonical_ingredients: dict[uuid.UUID, Ingredient] = {
        ingredient.id: ingredient
        for ingredient in await db.scalars(
            select(Ingredient).where(Ingredient.id.in_(list(candidates)))
        )
    }
    return requirements, candidates, canonical_ingredients, excluded_recipe_count


def _build_score_index(
    requirements: list[RecipeRequirement],
) -> UnlockScoreIndex:
    unlock_bits: dict[frozenset[uuid.UUID], int] = {}
    impact_bits: dict[uuid.UUID, int] = {}
    for recipe_index, requirement in enumerate(requirements):
        if len(requirement.groups) > 3:
            continue
        bit = 1 << recipe_index
        for candidate in set().union(*requirement.groups):
            impact_bits[candidate] = impact_bits.get(candidate, 0) | bit
        for choices in itertools.product(*requirement.groups):
            required = frozenset(choices)
            if len(required) <= 3:
                unlock_bits[required] = unlock_bits.get(required, 0) | bit
    return UnlockScoreIndex(unlock_bits=unlock_bits, impact_bits=impact_bits)


def _combination_bits(
    combination: frozenset[uuid.UUID],
    score_index: UnlockScoreIndex,
) -> tuple[int, int, int]:
    unlocked_bits = 0
    for subset_size in range(1, len(combination) + 1):
        for subset in itertools.combinations(combination, subset_size):
            unlocked_bits |= score_index.unlock_bits.get(frozenset(subset), 0)
    singleton_bits = 0
    impact_bits = 0
    for candidate in combination:
        singleton_bits |= score_index.unlock_bits.get(frozenset({candidate}), 0)
        impact_bits |= score_index.impact_bits.get(candidate, 0)
    synergy_count = (unlocked_bits & ~singleton_bits).bit_count()
    near_unlock_count = (impact_bits & ~unlocked_bits).bit_count()
    return unlocked_bits, synergy_count, near_unlock_count


def _recipes_from_bits(
    bits: int,
    requirements: list[RecipeRequirement],
    *,
    limit: int,
) -> list[Recipe]:
    recipes: list[Recipe] = []
    while bits and len(recipes) < limit:
        lowest_bit = bits & -bits
        recipe_index = lowest_bit.bit_length() - 1
        recipes.append(requirements[recipe_index].recipe)
        bits ^= lowest_bit
    return recipes


async def ingredient_unlock_sets(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    item_count: int,
    limit: int,
) -> dict[str, Any]:
    if item_count not in MAX_CANDIDATES_BY_SIZE:
        raise ValueError("item_count must be between 1 and 3")
    requirements, candidates, ingredients, excluded_count = await _load_unlock_problem(
        db,
        user_id=user_id,
    )
    if not requirements or not candidates:
        return {
            "item_count": item_count,
            "candidate_count": len(candidates),
            "quality_excluded_recipe_count": excluded_count,
            "items": [],
        }

    ranked_candidates = sorted(
        candidates,
        key=lambda key: (
            -candidates[key].potential_recipes,
            ingredients.get(key).name.casefold() if key in ingredients else str(key),
        ),
    )[: MAX_CANDIDATES_BY_SIZE[item_count]]

    score_index = _build_score_index(requirements)
    result_heap: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    serial = 0
    for raw_combination in itertools.combinations(ranked_candidates, item_count):
        combination = frozenset(raw_combination)
        unlocked_bits, synergy_count, near_unlock_count = _combination_bits(
            combination,
            score_index,
        )
        unlock_count = unlocked_bits.bit_count()
        best_subset_count = 0
        if item_count > 1:
            best_subset_count = max(
                _combination_bits(combination - {candidate}, score_index)[0].bit_count()
                for candidate in combination
            )
        incremental_count = unlock_count - best_subset_count
        if item_count > 1 and incremental_count <= 0:
            continue
        if unlock_count == 0 and near_unlock_count == 0:
            continue

        ingredient_rows = []
        for key in sorted(
            combination,
            key=lambda candidate_id: ingredients[candidate_id].name.casefold(),
        ):
            ingredient = ingredients[key]
            state = candidates[key]
            ingredient_rows.append(
                {
                    "ingredient_id": key,
                    "name": ingredient.name,
                    "family_name": shopping_family_name(ingredient.name),
                    "category": ingredient.category,
                    "status": state.status,
                    "pantry_item_id": state.pantry_item_id,
                }
            )
        result = {
            "ingredients": ingredient_rows,
            "unlock_count": unlock_count,
            "synergy_count": synergy_count,
            "incremental_count": incremental_count if item_count > 1 else unlock_count,
            "near_unlock_count": near_unlock_count,
            "unlocked_recipes": [
                {
                    "id": recipe.id,
                    "title": recipe.title,
                    "image_url": recipe_image_url(recipe.id, recipe.image_path),
                    "covered_by": list(combination),
                }
                for recipe in _recipes_from_bits(unlocked_bits, requirements, limit=3)
            ],
        }
        serial += 1
        entry = ((unlock_count, synergy_count, near_unlock_count, -serial), result)
        if len(result_heap) < limit:
            heapq.heappush(result_heap, entry)
        elif entry[0] > result_heap[0][0]:
            heapq.heapreplace(result_heap, entry)

    items = [
        entry[1]
        for entry in sorted(
            result_heap,
            key=lambda entry: (
                -entry[1]["unlock_count"],
                -entry[1]["synergy_count"],
                -entry[1]["near_unlock_count"],
                [row["name"] for row in entry[1]["ingredients"]],
            ),
        )
    ]
    return {
        "item_count": item_count,
        "candidate_count": len(ranked_candidates),
        "quality_excluded_recipe_count": excluded_count,
        "items": items,
    }


async def ingredient_unlock_suggestions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int,
) -> list[dict[str, Any]]:
    """Backward-compatible single-ingredient response."""
    page = await ingredient_unlock_sets(
        db,
        user_id=user_id,
        item_count=1,
        limit=limit,
    )
    return [
        {
            **item["ingredients"][0],
            "unlock_count": item["unlock_count"],
            "near_unlock_count": item["near_unlock_count"],
            "unlocked_recipes": [
                {
                    "id": recipe["id"],
                    "title": recipe["title"],
                    "image_url": recipe["image_url"],
                }
                for recipe in item["unlocked_recipes"]
            ],
        }
        for item in page["items"]
    ]
