from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models import Ingredient, RecipeIngredient
from app.services.ingestion import _parse_ingredient_parts
from app.services.ingredient_quality import (
    assess_recipe_ingredient,
    assign_ingredient_metadata,
    ingredient_quality_flags,
    shopping_family_name,
)


async def audit_and_backfill(*, apply: bool, repair: bool = False) -> dict[str, object]:
    async with SessionLocal() as db:
        ingredients = list(await db.scalars(select(Ingredient).order_by(Ingredient.name)))
        recipe_items = list(
            await db.scalars(
                select(RecipeIngredient)
                .options(selectinload(RecipeIngredient.ingredient))
                .order_by(RecipeIngredient.id)
            )
        )
        roots = {
            ingredient.id: ingredient
            for ingredient in await db.scalars(
                select(Ingredient).where(
                    Ingredient.id.in_(
                        {
                            ingredient.canonical_id or ingredient.id
                            for ingredient in ingredients
                        }
                    )
                )
            )
        }
        ingredients_by_name = {ingredient.name.casefold(): ingredient for ingredient in ingredients}

        ingredient_flag_counts: Counter[str] = Counter()
        family_counts: Counter[str] = Counter()
        ingredient_examples: list[dict[str, object]] = []
        for ingredient in ingredients:
            flags = ingredient_quality_flags(ingredient.name)
            ingredient_flag_counts.update(flags)
            root = roots.get(ingredient.canonical_id or ingredient.id, ingredient)
            family_name = shopping_family_name(root.name)
            family_counts[family_name] += 1
            if flags and len(ingredient_examples) < 50:
                ingredient_examples.append(
                    {
                        "name": ingredient.name,
                        "canonical": root.name,
                        "family": family_name,
                        "flags": flags,
                    }
                )

        parse_status_counts: Counter[str] = Counter()
        recipe_examples: list[dict[str, object]] = []
        eligible_repairs = 0
        repaired = 0
        for item in recipe_items:
            status, flags = assess_recipe_ingredient(item)
            suggested_name, _, suggested_quantity, suggested_unit = _parse_ingredient_parts(
                item.raw_text
            )
            suggested_flags = ingredient_quality_flags(suggested_name, item.raw_text)
            root = roots.get(item.ingredient.canonical_id or item.ingredient_id)
            root_is_valid = root is not None and not ingredient_quality_flags(root.name)
            can_repair = (
                status != "valid"
                and suggested_name != item.ingredient.name
                and not suggested_flags
                and root_is_valid
            )
            if can_repair:
                eligible_repairs += 1
            if apply and repair and can_repair and root is not None:
                replacement = ingredients_by_name.get(suggested_name.casefold())
                if replacement is None:
                    replacement = Ingredient(
                        name=suggested_name,
                        category=item.ingredient.category or root.category,
                        staple=item.ingredient.staple,
                        canonical_id=root.id,
                    )
                    db.add(replacement)
                    ingredients.append(replacement)
                    ingredients_by_name[suggested_name.casefold()] = replacement
                elif replacement.canonical_id is None:
                    replacement.canonical_id = root.id
                item.ingredient = replacement
                if suggested_quantity is not None:
                    item.quantity = suggested_quantity
                if suggested_unit is not None:
                    item.unit = suggested_unit
                status, flags = assess_recipe_ingredient(item)
                repaired += 1
            parse_status_counts[status] += 1
            if status != "valid" and len(recipe_examples) < 50:
                recipe_examples.append(
                    {
                        "raw_text": item.raw_text,
                        "current_name": item.ingredient.name,
                        "suggested_name": suggested_name,
                        "status": status,
                        "flags": flags,
                    }
                )
            if apply:
                item.parse_status = status
                item.quality_flags = flags

        if apply:
            await db.flush()
            await assign_ingredient_metadata(db, ingredients)
            await db.commit()

        return {
            "applied": apply,
            "ingredients": len(ingredients),
            "recipe_ingredients": len(recipe_items),
            "ingredient_flags": dict(sorted(ingredient_flag_counts.items())),
            "parse_statuses": dict(sorted(parse_status_counts.items())),
            "shopping_families": len(family_counts),
            "eligible_repairs": eligible_repairs,
            "repaired": repaired,
            "ingredient_examples": ingredient_examples,
            "recipe_ingredient_examples": recipe_examples,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit ingredient quality; pass --apply to store flags and shopping families."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--repair",
        action="store_true",
        help=(
            "Apply conservative raw-text reparsing when an existing valid canonical root is known."
        ),
    )
    args = parser.parse_args()
    report = asyncio.run(audit_and_backfill(apply=args.apply or args.repair, repair=args.repair))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
