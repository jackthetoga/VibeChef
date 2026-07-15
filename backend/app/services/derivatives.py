"""Match-time / canonical links from semi-processed forms to whole foods."""

from __future__ import annotations

import re

from app.services.canonicalize import normalize_ingredient_name

# Citrus-focused peel/rind/juice; zest applies to any parent food.
CITRUS_PARENTS = frozenset(
    {
        "lemon",
        "lemons",
        "lime",
        "limes",
        "orange",
        "oranges",
        "grapefruit",
        "grapefruits",
        "tangerine",
        "tangerines",
        "citron",
        "bergamot",
    }
)
LEADING_MODIFIERS = frozenset(
    {
        "fresh",
        "freshly",
        "bottled",
        "unsweetened",
        "grated",
        "squeezed",
        "organic",
        "the",
        "a",
        "an",
    }
)


def _clean_parent(parent: str) -> str | None:
    words = [word for word in parent.split() if word not in LEADING_MODIFIERS]
    parent = " ".join(words).strip()
    if not parent or re.search(r"\d", parent):
        return None
    if re.search(r"\b(in|with|and|or|of|fluid|ounces?|ounce)\b", parent):
        return None
    if len(parent.split()) > 2:
        return None
    return parent


def parent_food_name(name: str) -> str | None:
    """Return the whole-food parent for zest / citrus peel-rind-juice forms."""
    normalized = normalize_ingredient_name(name)
    if not normalized:
        return None

    match = re.fullmatch(r"(.+?)\s+(zest|peel|rind|juice)", normalized)
    if not match:
        match = re.fullmatch(
            r"(zest|peel|rind|juice)\s+of\s+(?:a\s+|an\s+|the\s+)?(.+)",
            normalized,
        )
        if not match:
            return None
        suffix, parent = match.group(1), match.group(2).strip()
    else:
        parent, suffix = match.group(1).strip(), match.group(2)

    parent = _clean_parent(parent)
    if parent is None:
        return None

    if suffix == "zest":
        return parent
    # peel / rind / juice: citrus only (avoids apple juice, pork rind, baker's peel)
    if parent in CITRUS_PARENTS or parent.rstrip("s") in CITRUS_PARENTS:
        return parent.rstrip("s") if parent.endswith("s") and len(parent) > 3 else parent
    return None


def parent_name_candidates(name: str) -> list[str]:
    """Possible pantry names for the parent of a derivative ingredient."""
    parent = parent_food_name(name)
    if not parent:
        return []
    singular = parent.rstrip("s") if parent.endswith("s") and len(parent) > 3 else parent
    candidates = [singular, singular + "s", parent]
    return list(dict.fromkeys(candidates))
