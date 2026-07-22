"""Shared pantry-to-recipe ingredient matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models import PantryItem, RecipeIngredient
from app.services.canonicalize import ingredient_match_key
from app.services.derivatives import parent_name_candidates
from app.services.units import compare_quantities, ingredient_conversion_for_units

MatchStatus = Literal["available", "insufficient", "unknown", "missing", "staple"]


@dataclass(frozen=True)
class PantryIngredientMatch:
    status: MatchStatus
    pantry_item: PantryItem | None
    matched_via: str | None = None
    conversion_basis: str | None = None
    conversion_source: str | None = None

    @property
    def satisfied(self) -> bool:
        return self.status not in {"missing", "insufficient"}


class PantryMatcher:
    """Match loaded recipe ingredients against a user's loaded pantry items."""

    def __init__(self, pantry_items: list[PantryItem]) -> None:
        self.items = pantry_items
        self.by_canonical = {
            item.ingredient.canonical_id or item.ingredient_id: item for item in pantry_items
        }
        self.by_name = {
            " ".join(item.ingredient.name.lower().split()): item for item in pantry_items
        }
        self.by_match_key = {
            ingredient_match_key(item.ingredient.name): item for item in pantry_items
        }

    def resolve(self, recipe_item: RecipeIngredient) -> tuple[PantryItem | None, str | None]:
        canonical_key = recipe_item.ingredient.canonical_id or recipe_item.ingredient_id
        pantry_item = self.by_canonical.get(canonical_key)
        if pantry_item is not None:
            return pantry_item, None

        pantry_item = self.by_match_key.get(ingredient_match_key(recipe_item.ingredient.name))
        if pantry_item is not None:
            return pantry_item, None

        for candidate in parent_name_candidates(recipe_item.ingredient.name):
            pantry_item = self.by_name.get(candidate)
            if pantry_item is not None:
                return pantry_item, pantry_item.ingredient.name
            for pantry_candidate in self.items:
                pantry_name = " ".join(pantry_candidate.ingredient.name.lower().split())
                if pantry_name == candidate or pantry_name.rstrip("s") == candidate.rstrip("s"):
                    return pantry_candidate, pantry_candidate.ingredient.name
        return None, None

    def match(self, recipe_item: RecipeIngredient) -> PantryIngredientMatch:
        pantry_item, matched_via_parent = self.resolve(recipe_item)
        conversion_name = matched_via_parent or recipe_item.ingredient.name
        conversion_profile = (
            ingredient_conversion_for_units(
                pantry_item.unit,
                recipe_item.unit,
                conversion_name,
            )
            if pantry_item
            else None
        )

        status: MatchStatus
        if recipe_item.ingredient.staple:
            status = "staple"
        elif pantry_item is None:
            status = "missing"
        else:
            comparison = compare_quantities(
                pantry_item.quantity,
                pantry_item.unit,
                recipe_item.quantity,
                recipe_item.unit,
                conversion_name,
            )
            if comparison is True:
                status = "available"
            elif comparison is False:
                # Derivatives (zest/juice) from a whole food: any positive parent counts.
                if matched_via_parent and (
                    pantry_item.quantity is None or pantry_item.quantity > 0
                ):
                    status = "available"
                else:
                    status = "insufficient"
            elif matched_via_parent:
                status = "available"
            else:
                status = "unknown"

        matched_via = matched_via_parent
        if (
            matched_via is None
            and pantry_item is not None
            and pantry_item.ingredient.name != recipe_item.ingredient.name
        ):
            matched_via = pantry_item.ingredient.name

        return PantryIngredientMatch(
            status=status,
            pantry_item=pantry_item,
            matched_via=matched_via,
            conversion_basis=conversion_profile.basis if conversion_profile else None,
            conversion_source=conversion_profile.source_url if conversion_profile else None,
        )

    def response_row(self, recipe_item: RecipeIngredient) -> dict[str, object]:
        match = self.match(recipe_item)
        return {
            "id": recipe_item.id,
            "ingredient_id": recipe_item.ingredient_id,
            "name": recipe_item.ingredient.name,
            "quantity": recipe_item.quantity,
            "unit": recipe_item.unit,
            "preparation": None,
            "raw_text": recipe_item.raw_text,
            "section": recipe_item.section,
            "alternate_group_id": recipe_item.alternate_group_id,
            "in_pantry": match.satisfied,
            "match_status": match.status,
            "pantry_quantity": match.pantry_item.quantity if match.pantry_item else None,
            "pantry_unit": match.pantry_item.unit if match.pantry_item else None,
            "matched_via": match.matched_via,
            "conversion_basis": match.conversion_basis,
            "conversion_source": match.conversion_source,
            "alternates": None,
        }


def collapse_alternate_groups(
    matched: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Collapse OR alternates into one display row with ANY match semantics."""
    groups: dict[object, list[dict[str, object]]] = {}
    order: list[object] = []
    for row in matched:
        key = row.get("alternate_group_id") or row["id"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    collapsed: list[dict[str, object]] = []
    for key in order:
        members = groups[key]
        if len(members) == 1 or members[0].get("alternate_group_id") is None:
            collapsed.append(members[0])
            continue
        status_rank = {
            "available": 0,
            "staple": 1,
            "unknown": 2,
            "insufficient": 3,
            "missing": 4,
        }
        best = min(members, key=lambda row: status_rank.get(str(row["match_status"]), 9))
        display = best.copy()
        display["name"] = " or ".join(str(member["name"]) for member in members)
        display["match_status"] = best["match_status"]
        display["in_pantry"] = best["match_status"] not in {"missing", "insufficient"}
        display["alternates"] = [
            {
                "ingredient_id": member["ingredient_id"],
                "name": member["name"],
                "quantity": member["quantity"],
                "unit": member["unit"],
                "match_status": member["match_status"],
            }
            for member in members
        ]
        collapsed.append(display)
    return collapsed
