"""Assumed-on-hand staples for recipe matching (excluded from missing_count)."""

from __future__ import annotations

import re

STAPLE_NAMES = frozenset(
    {
        "salt",
        "kosher salt",
        "sea salt",
        "flaky salt",
        "pepper",
        "black pepper",
        "freshly ground black pepper",
        "water",
        "cold water",
        "hot water",
        "boiling water",
        "olive oil",
        "extra virgin olive oil",
        "extra-virgin olive oil",
        "vegetable oil",
        "cooking oil",
        "canola oil",
    }
)

# Head nouns that indicate cookware/tools rather than food.
EQUIPMENT_HEAD_NOUNS = frozenset(
    {
        "pot",
        "pots",
        "pan",
        "pans",
        "saucepan",
        "saucepans",
        "skillet",
        "skillets",
        "stockpot",
        "stockpots",
        "wok",
        "woks",
        "casserole",
        "sheet",
        "sheets",
        "tray",
        "trays",
        "dish",
        "dishes",
        "bowl",
        "bowls",
        "colander",
        "strainers",
        "strainer",
        "ladle",
        "ladles",
        "spatula",
        "spatulas",
        "whisk",
        "whisks",
        "tongs",
        "knife",
        "knives",
        "board",
        "boards",
        "grater",
        "graters",
        "peeler",
        "peelers",
        "processor",
        "blender",
        "blenders",
        "mixer",
        "mixers",
        "mold",
        "mould",
        "molds",
        "moulds",
        "thermometer",
        "thermometers",
        "toothpick",
        "toothpicks",
        "skewer",
        "skewers",
        "grill",
        "grills",
        "oven",
        "stove",
    }
)

FOODISH_TOKENS = frozenset(
    {
        "beef",
        "steak",
        "steaks",
        "bread",
        "chicken",
        "fish",
        "pork",
        "lamb",
        "veal",
        "turkey",
        "vegetable",
        "vegetables",
        "pasta",
        "rice",
        "soup",
        "sauce",
        "butter",
        "oil",
        "water",
        "stock",
        "broth",
        "drippings",
        "juice",
        "milk",
        "cream",
        "cheese",
        "egg",
        "eggs",
        "flour",
        "cornstarch",
        "sugar",
        "salt",
        "pepper",
        "garlic",
        "onion",
        "tomato",
        "tomatoes",
    }
)


def normalize_staple_name(value: object) -> str:
    return " ".join(str(value or "").lower().strip().split())


def is_equipment_name(name: str) -> bool:
    """True only when the phrase is primarily cookware, not a food prepared in/on it."""
    normalized = normalize_staple_name(name)
    if not normalized:
        return False
    # "cornstarch in a bowl" / "beef in a pan" — food, not equipment.
    if re.search(r"\bin\s+(?:a|an|the)\b", normalized):
        return False
    cleaned = re.sub(r"^(?:a|an|the|optional|preferably)\s+", "", normalized)
    cleaned = re.sub(
        r"^\d+(?:\s*/\s*\d+)?(?:\s*-\s*\d+)?(?:\s*(?:to|-)\s*\d+)?\s*"
        r"(?:inch|quart|cup|ounce|oz)?(?:-?(?:inch|quart|cup))?\s*",
        "",
        cleaned,
    )
    cleaned = cleaned.strip(" ,")
    words = re.findall(r"[a-z']+", cleaned)
    if not words:
        return False
    if set(words) & FOODISH_TOKENS:
        return False
    head = words[-1]
    if head in EQUIPMENT_HEAD_NOUNS:
        return True
    # "cake pan", "frying pan", "baking dish", "mixing bowl"
    if len(words) >= 2 and words[-1] in EQUIPMENT_HEAD_NOUNS:
        return True
    return False


def is_staple_name(name: str) -> bool:
    normalized = normalize_staple_name(name)
    if not normalized:
        return False
    if normalized in STAPLE_NAMES:
        return True
    return is_equipment_name(normalized)
