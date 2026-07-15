"""Recipe list filter helpers and shared tag allowlists."""

from __future__ import annotations

from sqlalchemy import Text, cast, or_

from app.models import Recipe

# MyPlate dish categories (stored lowercase on recipe.tags).
RECIPE_CATEGORIES = (
    "main dish",
    "side dish",
    "salad",
    "soup",
    "sauce",
    "dessert",
    "breakfast",
    "bread",
    "snack",
    "beverage",
)
CATEGORY_SET = set(RECIPE_CATEGORIES)

# Canonical food-group keys → accepted tag spellings (label or key forms).
FOOD_GROUP_ALIASES: dict[str, tuple[str, ...]] = {
    "vegetables": ("vegetables", "vegetable"),
    "fruits": ("fruits", "fruit"),
    "grains": ("grains", "grain"),
    "protein-foods": ("protein-foods", "protein foods", "protein food"),
    "dairy": ("dairy",),
}
FOOD_GROUPS = tuple(FOOD_GROUP_ALIASES.keys())
FOOD_GROUP_SET = set(FOOD_GROUPS)

# Exclusive cuisine values stored on Recipe.cuisine (display casing).
RECIPE_CUISINES = (
    "Italian",
    "Mexican",
    "Mediterranean",
    "Asian",
    "Indian",
    "American",
    "Chinese",
)
CUISINE_BY_KEY = {cuisine.casefold(): cuisine for cuisine in RECIPE_CUISINES}

# Stackable non-cuisine dish-style tags.
DISH_TAGS = (
    "pasta",
    "seafood",
    "stew",
    "meat",
    "poultry",
    "grain",
    "vegetable",
)
DISH_TAG_SET = set(DISH_TAGS)

# Image-classifier slug → filter category (+ optional dish style tag).
IMAGE_SLUG_TO_CATEGORY: dict[str, str] = {
    "soup": "soup",
    "salad": "salad",
    "dessert": "dessert",
    "bread": "bread",
    "sauce": "sauce",
    "breakfast": "breakfast",
    "drink": "beverage",
    "pasta": "main dish",
    "seafood": "main dish",
    "meat": "main dish",
    "poultry": "main dish",
    "stew": "main dish",
    "grain": "main dish",
    "vegetable": "side dish",
}

IMAGE_SLUG_TO_DISH_TAG: dict[str, str] = {
    "pasta": "pasta",
    "seafood": "seafood",
    "stew": "stew",
    "meat": "meat",
    "poultry": "poultry",
    "grain": "grain",
    "vegetable": "vegetable",
}

# Pantry / common-ingredient categories → MyPlate food groups.
PANTRY_CATEGORY_TO_FOOD_GROUP: dict[str, str] = {
    "produce": "vegetables",
    "meat & seafood": "protein-foods",
    "dairy & eggs": "dairy",
    "grains & pasta": "grains",
    "baking": "grains",
}

# Produce names that are fruits rather than vegetables.
FRUIT_NAME_HINTS = (
    "apple",
    "banana",
    "berry",
    "berries",
    "cherry",
    "grape",
    "lemon",
    "lime",
    "mango",
    "orange",
    "peach",
    "pear",
    "pineapple",
    "plum",
    "strawberry",
    "watermelon",
    "melon",
    "kiwi",
    "avocado",  # often grouped with produce; keep as fruit for MyPlate-ish filters
)


def normalize_category(value: str) -> str:
    return " ".join(value.strip().lower().split())


def normalize_food_group(value: str) -> str:
    cleaned = " ".join(value.strip().lower().replace("_", "-").split())
    cleaned = cleaned.replace(" ", "-")
    aliases = {
        "vegetable": "vegetables",
        "fruit": "fruits",
        "grain": "grains",
        "protein-food": "protein-foods",
        "proteinfoods": "protein-foods",
    }
    return aliases.get(cleaned, cleaned)


def food_group_tag_candidates(value: str) -> tuple[str, ...]:
    key = normalize_food_group(value)
    return FOOD_GROUP_ALIASES.get(key, (key,))


def normalize_cuisine(value: str | None) -> str | None:
    if not value:
        return None
    return CUISINE_BY_KEY.get(value.strip().casefold())


def tags_contain(tag: str):
    """Match a JSON string tag element across SQLite and Postgres."""
    needle = tag.strip().lower()
    return cast(Recipe.tags, Text).ilike(f'%"{needle}"%')


def tags_contain_any(tags: tuple[str, ...] | list[str]):
    values = [tag.strip().lower() for tag in tags if tag and tag.strip()]
    if not values:
        return None
    if len(values) == 1:
        return tags_contain(values[0])
    return or_(*(tags_contain(tag) for tag in values))


def split_recipe_tags(tags: list[str] | None) -> dict[str, object]:
    """Partition stored tags into category / food_groups / dish_tags / other."""
    category: str | None = None
    food_groups: list[str] = []
    dish_tags: list[str] = []
    other: list[str] = []
    seen_groups: set[str] = set()
    seen_dish: set[str] = set()

    for raw in tags or []:
        tag = raw.strip().lower()
        if not tag:
            continue
        if tag in CATEGORY_SET and category is None:
            category = tag
            continue
        group = normalize_food_group(tag)
        if group in FOOD_GROUP_SET:
            if group not in seen_groups:
                seen_groups.add(group)
                food_groups.append(group)
            continue
        if tag in DISH_TAG_SET:
            if tag not in seen_dish:
                seen_dish.add(tag)
                dish_tags.append(tag)
            continue
        other.append(tag)

    return {
        "category": category,
        "food_groups": food_groups,
        "dish_tags": dish_tags,
        "other": other,
    }


def merge_recipe_tags(
    *,
    category: str | None = None,
    food_groups: list[str] | None = None,
    dish_tags: list[str] | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    """Build a normalized tags list from structured parts."""
    result: list[str] = []
    seen: set[str] = set()

    def add(tag: str | None) -> None:
        if not tag:
            return
        cleaned = tag.strip().lower()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        result.append(cleaned)

    if category:
        normalized = normalize_category(category)
        if normalized in CATEGORY_SET:
            add(normalized)

    for group in food_groups or []:
        key = normalize_food_group(group)
        if key in FOOD_GROUP_SET:
            add(key)

    for dish in dish_tags or []:
        cleaned = dish.strip().lower()
        if cleaned in DISH_TAG_SET:
            add(cleaned)

    for tag in extra or []:
        add(tag)

    return result
