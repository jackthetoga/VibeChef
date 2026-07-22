"""Heuristic + LLM recipe tagging for filter chips."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from app.core.config import settings
from app.services.common_ingredients import COMMON_INGREDIENT_CATEGORIES
from app.services.llm import chat_completion
from app.services.recipe_filters import (
    CATEGORY_SET,
    DISH_TAG_SET,
    DISH_TAGS,
    FOOD_GROUP_SET,
    FOOD_GROUPS,
    FRUIT_NAME_HINTS,
    IMAGE_SLUG_TO_CATEGORY,
    IMAGE_SLUG_TO_DISH_TAG,
    PANTRY_CATEGORY_TO_FOOD_GROUP,
    RECIPE_CATEGORIES,
    RECIPE_CUISINES,
    merge_recipe_tags,
    normalize_category,
    normalize_cuisine,
    normalize_food_group,
    split_recipe_tags,
)

logger = logging.getLogger(__name__)

TagSource = Literal["heuristic", "llm", "manual", "myplate"]

_CUISINE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Italian": (r"\bitalian\b", r"\btuscan\b", r"\bsicilian\b", r"\bcacciatore\b"),
    "Mexican": (r"\bmexican\b", r"\btacos?\b", r"\bburritos?\b", r"\benchiladas?\b", r"\bsalsa\b"),
    "Mediterranean": (r"\bmediterranean\b", r"\bgreek\b", r"\blebanese\b"),
    "Asian": (r"\basian\b", r"\bthai\b", r"\bjapanese\b", r"\bkorean\b", r"\bvietnamese\b"),
    "Indian": (r"\bindian\b", r"\bcurry\b", r"\bmasala\b", r"\btikka\b"),
    "American": (r"\bamerican\b", r"\bsouthern\b", r"\bcajun\b", r"\btex[- ]?mex\b"),
    "Chinese": (r"\bchinese\b", r"\bszechuan\b", r"\bsichuan\b", r"\bcantonese\b"),
}

_CUISINE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (cuisine, tuple(re.compile(pattern, re.I) for pattern in patterns))
    for cuisine, patterns in _CUISINE_KEYWORDS.items()
)

# Dish-shape heuristics used for category / dish-tag chips (not imagery).
_DISH_SHAPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "soup",
        (
            r"\bsoup\b",
            r"\bbroth\b",
            r"\bbisque\b",
            r"\bchowder\b",
            r"\bconsomme\b",
            r"\bconsommé\b",
            r"\bpho\b",
            r"\bmiso\b",
        ),
    ),
    (
        "stew",
        (
            r"\bstew\b",
            r"\bcasserole\b",
            r"\brajout\b",
            r"\bgoulash\b",
            r"\bcurry\b",
            r"\bchili\b",
            r"\bchilli\b",
            r"\btagine\b",
            r"\bbraise",
        ),
    ),
    (
        "pasta",
        (
            r"\bpasta\b",
            r"\bspaghetti\b",
            r"\blinguine\b",
            r"\bfettuccine\b",
            r"\bpenne\b",
            r"\brigatoni\b",
            r"\blasagna\b",
            r"\blasagne\b",
            r"\bnoodle\b",
            r"\bramen\b",
            r"\budon\b",
            r"\bmacaroni\b",
            r"\bgnocchi\b",
        ),
    ),
    ("salad", (r"\bsalad\b", r"\bslaw\b", r"\bceviche\b")),
    (
        "seafood",
        (
            r"\bfish\b",
            r"\bsalmon\b",
            r"\btuna\b",
            r"\bcod\b",
            r"\bshrimp\b",
            r"\bprawn\b",
            r"\bcrab\b",
            r"\blobster\b",
            r"\bmussel\b",
            r"\bclam\b",
            r"\boyster\b",
            r"\bscallop\b",
            r"\bsquid\b",
            r"\bcalamari\b",
            r"\bseafood\b",
            r"\banchov",
        ),
    ),
    (
        "poultry",
        (
            r"\bchicken\b",
            r"\bturkey\b",
            r"\bduck\b",
            r"\bhen\b",
            r"\bpoultry\b",
            r"\bquail\b",
        ),
    ),
    (
        "meat",
        (
            r"\bbeef\b",
            r"\bsteak\b",
            r"\bpork\b",
            r"\blamb\b",
            r"\bveal\b",
            r"\bbacon\b",
            r"\bsausage\b",
            r"\bham\b",
            r"\bribs?\b",
            r"\bbrisket\b",
            r"\bmeatball",
            r"\bburger\b",
        ),
    ),
    (
        "dessert",
        (
            r"\bcake\b",
            r"\bcookie\b",
            r"\bbrownie\b",
            r"\bpie\b",
            r"\btart\b",
            r"\bpudding\b",
            r"\bicecream\b",
            r"\bice cream\b",
            r"\bchocolate\b",
            r"\bdessert\b",
            r"\bcustard\b",
            r"\bsorbet\b",
            r"\bmousse\b",
            r"\bbiscotti\b",
            r"\bcookies?\b",
            r"\bsweet\b",
        ),
    ),
    (
        "bread",
        (
            r"\bbread\b",
            r"\bbaguette\b",
            r"\bbiscuit\b",
            r"\bmuffin\b",
            r"\bscone\b",
            r"\broll\b",
            r"\bbun\b",
            r"\bfocaccia\b",
            r"\bciabatta\b",
            r"\bpizza\b",
            r"\bflatbread\b",
            r"\btortilla\b",
            r"\bpancake\b",
            r"\bwaffle\b",
            r"\bcrepe\b",
            r"\bcrêpe\b",
        ),
    ),
    (
        "breakfast",
        (
            r"\bbreakfast\b",
            r"\begg\b",
            r"\bombelet\b",
            r"\bfrittata\b",
            r"\bgranola\b",
            r"\boatmeal\b",
            r"\bporridge\b",
            r"\bbrunch\b",
        ),
    ),
    (
        "sauce",
        (
            r"\bsauce\b",
            r"\bdressing\b",
            r"\bvinaigrette\b",
            r"\bpesto\b",
            r"\baioli\b",
            r"\bgravy\b",
            r"\bmarinade\b",
            r"\brelish\b",
            r"\bchutney\b",
            r"\bsalsa\b",
        ),
    ),
    (
        "drink",
        (
            r"\bdrink\b",
            r"\bbeverage\b",
            r"\bcocktail\b",
            r"\bsmoothie\b",
            r"\bjuice\b",
            r"\btea\b",
            r"\bcoffee\b",
            r"\bwine\b",
            r"\blemonade\b",
            r"\bpunch\b",
        ),
    ),
    (
        "grain",
        (
            r"\brice\b",
            r"\brisotto\b",
            r"\bquinoa\b",
            r"\bcouscous\b",
            r"\bbarley\b",
            r"\bpolenta\b",
            r"\bgrain\b",
            r"\bbulgur\b",
            r"\bfarro\b",
        ),
    ),
    (
        "vegetable",
        (
            r"\bvegetable\b",
            r"\bveggie\b",
            r"\bvegetarian\b",
            r"\bvegan\b",
            r"\basparagus\b",
            r"\bbroccoli\b",
            r"\bcauliflower\b",
            r"\beggplant\b",
            r"\baubergine\b",
            r"\bzucchini\b",
            r"\bcourgette\b",
            r"\bspinach\b",
            r"\bkale\b",
            r"\btomato\b",
            r"\bmushroom\b",
            r"\bleek\b",
            r"\bfennel\b",
            r"\bpepper\b",
            r"\bcabbage\b",
            r"\bbean\b",
            r"\blentil\b",
            r"\bchickpea\b",
        ),
    ),
)

_COMPILED_DISH_SHAPE_RULES = tuple(
    (slug, tuple(re.compile(pattern, re.I) for pattern in patterns))
    for slug, patterns in _DISH_SHAPE_RULES
)


def classify_recipe_category(
    title: str,
    cuisine: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Return a dish-shape slug for heuristic tagging (not used for imagery)."""
    haystack = _haystack(title, cuisine, tags)
    for slug, patterns in _COMPILED_DISH_SHAPE_RULES:
        if any(pattern.search(haystack) for pattern in patterns):
            return slug
    return "other"


@dataclass
class TagAssignment:
    cuisine: str | None = None
    tags: list[str] = field(default_factory=list)
    tag_source: TagSource | None = None

    @property
    def category(self) -> str | None:
        parts = split_recipe_tags(self.tags)
        return parts["category"]  # type: ignore[return-value]

    @property
    def food_groups(self) -> list[str]:
        parts = split_recipe_tags(self.tags)
        return list(parts["food_groups"])  # type: ignore[arg-type]

    @property
    def is_useful(self) -> bool:
        return bool(self.category or self.cuisine or self.food_groups)


def _haystack(title: str, cuisine: str | None, tags: list[str] | None) -> str:
    return " ".join(part for part in [title, cuisine or "", " ".join(tags or [])] if part).lower()


def guess_cuisine(
    title: str, cuisine: str | None = None, tags: list[str] | None = None
) -> str | None:
    existing = normalize_cuisine(cuisine)
    if existing:
        return existing
    text = _haystack(title, None, tags)
    for label, patterns in _CUISINE_PATTERNS:
        if any(pattern.search(text) for pattern in patterns):
            return label
    return None


def _food_group_from_ingredient(name: str, pantry_category: str | None = None) -> str | None:
    normalized = " ".join(name.lower().split())
    category = pantry_category or COMMON_INGREDIENT_CATEGORIES.get(normalized)
    if category:
        mapped = PANTRY_CATEGORY_TO_FOOD_GROUP.get(category.casefold())
        if mapped == "vegetables" and any(hint in normalized for hint in FRUIT_NAME_HINTS):
            return "fruits"
        if mapped:
            return mapped
    if any(hint in normalized for hint in FRUIT_NAME_HINTS):
        return "fruits"
    return None


def guess_food_groups(
    ingredients: Iterable[str] | None = None,
    ingredient_categories: Iterable[str | None] | None = None,
) -> list[str]:
    names = list(ingredients or [])
    cats = list(ingredient_categories or [])
    found: list[str] = []
    seen: set[str] = set()
    for index, name in enumerate(names):
        cat = cats[index] if index < len(cats) else None
        group = _food_group_from_ingredient(name, cat)
        if group and group not in seen:
            seen.add(group)
            found.append(group)
    return found


def tag_recipe_heuristic(
    *,
    title: str,
    cuisine: str | None = None,
    tags: list[str] | None = None,
    ingredient_names: list[str] | None = None,
    ingredient_categories: list[str | None] | None = None,
) -> TagAssignment:
    """Assign category / cuisine / food-group tags from title + ingredients."""
    existing = split_recipe_tags(tags)
    slug = classify_recipe_category(title, cuisine, tags)
    category = existing["category"]  # type: ignore[assignment]
    if not category and slug != "other":
        category = IMAGE_SLUG_TO_CATEGORY.get(slug)

    dish_tags = list(existing["dish_tags"])  # type: ignore[arg-type]
    dish_from_slug = IMAGE_SLUG_TO_DISH_TAG.get(slug)
    if dish_from_slug and dish_from_slug not in dish_tags:
        dish_tags.append(dish_from_slug)

    food_groups = list(existing["food_groups"])  # type: ignore[arg-type]
    for group in guess_food_groups(ingredient_names, ingredient_categories):
        if group not in food_groups:
            food_groups.append(group)

    resolved_cuisine = guess_cuisine(title, cuisine, tags)
    merged = merge_recipe_tags(
        category=category if isinstance(category, str) else None,
        food_groups=food_groups,
        dish_tags=dish_tags,
        extra=list(existing["other"]),  # type: ignore[arg-type]
    )
    assignment = TagAssignment(
        cuisine=resolved_cuisine,
        tags=merged,
        tag_source="heuristic",
    )
    if not assignment.is_useful:
        assignment.tag_source = None
    return assignment


def _validate_llm_payload(data: dict) -> TagAssignment:
    category_raw = data.get("category")
    category = None
    if category_raw:
        candidate = normalize_category(str(category_raw))
        if candidate in CATEGORY_SET:
            category = candidate

    cuisine = normalize_cuisine(str(data.get("cuisine") or "") or None)

    food_groups: list[str] = []
    for item in data.get("food_groups") or []:
        key = normalize_food_group(str(item))
        if key in FOOD_GROUP_SET and key not in food_groups:
            food_groups.append(key)

    dish_tags: list[str] = []
    for item in data.get("dish_tags") or []:
        cleaned = str(item).strip().lower()
        if cleaned in DISH_TAG_SET and cleaned not in dish_tags:
            dish_tags.append(cleaned)

    tags = merge_recipe_tags(
        category=category,
        food_groups=food_groups,
        dish_tags=dish_tags,
    )
    assignment = TagAssignment(cuisine=cuisine, tags=tags, tag_source="llm")
    if not assignment.is_useful:
        assignment.tag_source = None
    return assignment


async def tag_recipe_llm(
    *,
    title: str,
    ingredient_names: list[str] | None = None,
    steps: list[str] | None = None,
) -> TagAssignment:
    """Ask the LLM for allowlisted tags. Returns empty assignment on failure."""
    if not settings.llm_enabled:
        return TagAssignment()

    ingredients = ", ".join((ingredient_names or [])[:40]) or "(none)"
    step_preview = " ".join((steps or [])[:3])[:500] or "(none)"
    prompt = (
        "Classify this recipe for a recipe finder app. Respond with JSON only:\n"
        '{"category": <string|null>, "cuisine": <string|null>, '
        '"food_groups": [<string>...], "dish_tags": [<string>...]}\n\n'
        f"Allowed category (one or null): {', '.join(RECIPE_CATEGORIES)}\n"
        f"Allowed cuisine (one or null): {', '.join(RECIPE_CUISINES)}\n"
        f"Allowed food_groups (zero or more): {', '.join(FOOD_GROUPS)}\n"
        f"Allowed dish_tags (zero or more): {', '.join(DISH_TAGS)}\n"
        "Never invent values outside these lists. Prefer null / empty over guesses.\n\n"
        f"Title: {title}\n"
        f"Ingredients: {ingredients}\n"
        f"Steps preview: {step_preview}"
    )
    try:
        content = await chat_completion(
            system=(
                "You tag recipes using only the provided allowlists. "
                "Return JSON only. Never invent categories, cuisines, or tags."
            ),
            user=prompt,
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
            timeout=20.0,
        )
        data = json.loads(content)
        if not isinstance(data, dict):
            return TagAssignment()
        return _validate_llm_payload(data)
    except Exception:
        logger.exception("LLM recipe tagging failed for %r", title)
        return TagAssignment()


def has_source_tags(tags: list[str] | None, cuisine: str | None = None) -> bool:
    """True when the recipe already carries useful filter metadata (e.g. MyPlate)."""
    parts = split_recipe_tags(tags)
    return bool(parts["category"] or cuisine or parts["food_groups"])


async def assign_recipe_tags(
    *,
    title: str,
    cuisine: str | None = None,
    tags: list[str] | None = None,
    ingredient_names: list[str] | None = None,
    ingredient_categories: list[str | None] | None = None,
    steps: list[str] | None = None,
    prefer_existing: bool = True,
) -> TagAssignment:
    """Heuristic first; LLM only when heuristics find nothing useful.

    When ``prefer_existing`` and the input already has useful tags/cuisine
    (MyPlate), return those with ``tag_source=myplate`` and skip auto-tagging.
    """
    if prefer_existing and has_source_tags(tags, cuisine):
        parts = split_recipe_tags(tags)
        return TagAssignment(
            cuisine=normalize_cuisine(cuisine) or cuisine,
            tags=merge_recipe_tags(
                category=parts["category"] if isinstance(parts["category"], str) else None,
                food_groups=list(parts["food_groups"]),  # type: ignore[arg-type]
                dish_tags=list(parts["dish_tags"]),  # type: ignore[arg-type]
                extra=list(parts["other"]),  # type: ignore[arg-type]
            ),
            tag_source="myplate" if "myplate" in {t.lower() for t in (tags or [])} else "heuristic",
        )

    heuristic = tag_recipe_heuristic(
        title=title,
        cuisine=cuisine,
        tags=tags,
        ingredient_names=ingredient_names,
        ingredient_categories=ingredient_categories,
    )
    if heuristic.is_useful:
        return heuristic

    llm = await tag_recipe_llm(
        title=title,
        ingredient_names=ingredient_names,
        steps=steps,
    )
    if llm.is_useful:
        return llm

    # Preserve any non-filter tags that were already present.
    leftover = merge_recipe_tags(extra=list(split_recipe_tags(tags)["other"]))  # type: ignore[arg-type]
    return TagAssignment(cuisine=normalize_cuisine(cuisine), tags=leftover, tag_source=None)


def apply_manual_tags(
    *,
    existing_tags: list[str] | None,
    existing_cuisine: str | None = None,
    cuisine: str | None = None,
    update_cuisine: bool = False,
    category: str | None = None,
    update_category: bool = False,
    food_groups: list[str] | None = None,
    dish_tags: list[str] | None = None,
    tags: list[str] | None = None,
) -> TagAssignment:
    """Build a manual tag assignment from partial updates."""
    existing = split_recipe_tags(existing_tags)

    next_category = existing["category"]
    if update_category:
        cleaned = normalize_category(category) if category else None
        next_category = cleaned if cleaned in CATEGORY_SET else None

    next_groups = list(existing["food_groups"])  # type: ignore[arg-type]
    if food_groups is not None:
        next_groups = []
        for group in food_groups:
            key = normalize_food_group(group)
            if key in FOOD_GROUP_SET and key not in next_groups:
                next_groups.append(key)

    next_dish = list(existing["dish_tags"])  # type: ignore[arg-type]
    if dish_tags is not None:
        next_dish = []
        for dish in dish_tags:
            cleaned = dish.strip().lower()
            if cleaned in DISH_TAG_SET and cleaned not in next_dish:
                next_dish.append(cleaned)

    extra = list(existing["other"])  # type: ignore[arg-type]
    if tags is not None:
        partitioned = split_recipe_tags(tags)
        if not update_category and partitioned["category"]:
            next_category = partitioned["category"]
        if food_groups is None and partitioned["food_groups"]:
            next_groups = list(partitioned["food_groups"])  # type: ignore[arg-type]
        if dish_tags is None:
            next_dish = list(partitioned["dish_tags"])  # type: ignore[arg-type]
        extra = list(partitioned["other"])  # type: ignore[arg-type]

    if update_cuisine:
        next_cuisine = normalize_cuisine(cuisine) if cuisine else None
    else:
        next_cuisine = normalize_cuisine(existing_cuisine) or existing_cuisine

    return TagAssignment(
        cuisine=next_cuisine,
        tags=merge_recipe_tags(
            category=next_category if isinstance(next_category, str) else None,
            food_groups=next_groups,
            dish_tags=next_dish,
            extra=extra,
        ),
        tag_source="manual",
    )
