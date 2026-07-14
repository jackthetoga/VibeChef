from __future__ import annotations

import json
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Ingredient
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_CANDIDATES = 200
MAX_CANONICAL_LENGTH = 255
IGNORED_CANDIDATE_TOKENS = {
    "and",
    "fresh",
    "large",
    "medium",
    "of",
    "or",
    "small",
    "the",
}
COLOR_WORDS = frozenset(
    {"black", "brown", "green", "orange", "purple", "red", "white", "yellow"}
)


def normalize_ingredient_name(value: object) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _candidate_tokens(names: list[str]) -> set[str]:
    return {
        token
        for name in names
        for token in re.findall(r"[a-z0-9]+", name)
        if len(token) > 2 and token not in IGNORED_CANDIDATE_TOKENS
    }


async def _canonical_candidates(
    db: AsyncSession,
    names: list[str],
) -> list[str]:
    roots = list(
        await db.scalars(
            select(Ingredient)
            .where(Ingredient.canonical_id == Ingredient.id)
            .order_by(Ingredient.name)
        )
    )
    tokens = _candidate_tokens(names)
    candidates = [
        root.name
        for root in roots
        if set(re.findall(r"[a-z0-9]+", root.name.lower())) & tokens
    ]
    return candidates[:MAX_CANDIDATES]


def _canonicalization_prompt(
    names: list[str],
    candidates: list[str],
    *,
    raw_hints: dict[str, str] | None = None,
) -> str:
    numbered_lines: list[str] = []
    for index, name in enumerate(names, start=1):
        hint = (raw_hints or {}).get(name)
        if hint and hint != name:
            numbered_lines.append(f"{index}. {name}\n   source: {hint}")
        else:
            numbered_lines.append(f"{index}. {name}")
    numbered = "\n".join(numbered_lines)
    return (
        "Canonicalize each input for pantry-to-recipe ingredient matching.\n"
        "Return one JSON object whose keys are the exact inputs and whose values are canonical "
        "ingredient names.\n\n"
        "Rules:\n"
        "- Remove preparation, grade, size, and style modifiers when the resulting ingredient "
        "is interchangeable for ordinary recipe matching.\n"
        "- Preserve compounds that are not interchangeable with their head noun: coconut milk "
        "is not milk, almond butter is not butter, and garlic powder is not garlic.\n"
        "- Distinct oils, flours, dairy products, meats, and produce remain distinct unless one "
        "input is merely a variety or grade of the same ingredient.\n"
        "- When a source line offers true substitutes (fresh tomatoes or canned tomatoes), "
        "canonicalize the input name itself; do not invent a second option here.\n"
        "- Prefer an exact name from EXISTING CANONICALS when it applies. Otherwise return a "
        "short, lowercase ingredient noun phrase.\n"
        "- Use the optional source line for context when the input name is truncated or messy.\n"
        "- Include every input exactly once. Return JSON only.\n\n"
        "Examples:\n"
        '{"coconut milk":"coconut milk","extra virgin olive oil":"olive oil",'
        '"vegetable oil":"vegetable oil","chopped parsley":"parsley"}\n\n'
        f"EXISTING CANONICALS:\n{json.dumps(candidates, ensure_ascii=False)}\n\n"
        f"INPUTS:\n{numbered}"
    )


def _parse_mapping(raw: str, expected_names: list[str]) -> dict[str, str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Canonicalization response must be a JSON object")

    expected = set(expected_names)
    mapping: dict[str, str] = {}
    for raw_name, raw_canonical in value.items():
        if not isinstance(raw_canonical, str):
            continue
        name = normalize_ingredient_name(raw_name)
        canonical = normalize_ingredient_name(raw_canonical)
        if (
            name in expected
            and canonical
            and len(canonical) <= MAX_CANONICAL_LENGTH
            and "\n" not in canonical
        ):
            mapping[name] = canonical
    return mapping


def _or_alternates_prompt(lines: list[str], candidates: list[str]) -> str:
    numbered = "\n".join(f"{index}. {line}" for index, line in enumerate(lines, start=1))
    return (
        "Each input is an ingredient line containing 'or'. Decide whether the options are "
        "interchangeable varieties of one ingredient or true substitutes that should match "
        "the pantry separately.\n"
        "Return JSON object mapping each exact input string to a list of 1+ short lowercase "
        "canonical ingredient names.\n\n"
        "Rules:\n"
        "- Color/size varieties of the same food → one name "
        '(e.g. "red or green bell peppers" → ["bell peppers"]).\n'
        "- True substitutes → multiple names "
        '(e.g. "pancetta or prosciutto" → ["pancetta","prosciutto"]).\n'
        "- Prefer EXISTING CANONICALS when applicable.\n"
        "- Include every input exactly once. Return JSON only.\n\n"
        f"EXISTING CANONICALS:\n{json.dumps(candidates, ensure_ascii=False)}\n\n"
        f"INPUTS:\n{numbered}"
    )


def _parse_alternates_mapping(raw: str, expected_lines: list[str]) -> dict[str, list[str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("OR alternate response must be a JSON object")
    expected = set(expected_lines)
    mapping: dict[str, list[str]] = {}
    for raw_line, raw_names in value.items():
        line = " ".join(str(raw_line or "").split())
        if line not in expected:
            continue
        names: list[str] = []
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        if not isinstance(raw_names, list):
            continue
        for item in raw_names:
            name = normalize_ingredient_name(item)
            if name and len(name) <= MAX_CANONICAL_LENGTH and "\n" not in name:
                if name not in names:
                    names.append(name)
        if names:
            mapping[line] = names
    return mapping


def heuristic_or_alternates(raw_text: str, fallback_name: str) -> list[str]:
    """Deterministic fallback when the LLM is unavailable."""
    cleaned = " ".join(raw_text.split())
    color_pattern = "|".join(sorted(COLOR_WORDS))
    color_match = re.search(
        rf"(?i)\b((?:{color_pattern})\s+or\s+(?:{color_pattern}))\s+(.+)$",
        cleaned,
    )
    if color_match:
        remainder = color_match.group(2).strip(" ,")
        name = normalize_ingredient_name(
            re.sub(
                r"(?i)^(?:[\d/.\s]+(?:tablespoons?|tbsp|teaspoons?|tsp|cups?|ounces?|oz|"
                r"pounds?|lbs?|grams?|g)\s+)?",
                "",
                remainder,
            )
        )
        name = re.split(
            r"\b(?:chopped|diced|minced|sliced|peeled|to taste)\b",
            name,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" ,")
        return [name or fallback_name]

    parts = [
        normalize_ingredient_name(part)
        for part in re.split(r"\s+or\s+", fallback_name, flags=re.I)
    ]
    parts = [part for part in parts if part]
    if len(parts) >= 2 and all(len(part.split()) <= 4 for part in parts):
        return parts
    return [fallback_name]


async def resolve_or_alternates(
    lines: list[str],
    fallback_names: dict[str, str],
    *,
    db: AsyncSession | None = None,
    timeout: float = 20.0,
) -> dict[str, list[str]]:
    """Map ambiguous OR raw lines to one or more canonical names."""
    unique_lines = list(dict.fromkeys(" ".join(line.split()) for line in lines if line.strip()))
    if not unique_lines:
        return {}

    if not settings.openai_api_key:
        return {
            line: heuristic_or_alternates(line, fallback_names.get(line, line))
            for line in unique_lines
        }

    mapping: dict[str, list[str]] = {}
    for offset in range(0, len(unique_lines), BATCH_SIZE):
        batch = unique_lines[offset : offset + BATCH_SIZE]
        try:
            candidates: list[str] = []
            if db is not None:
                candidates = await _canonical_candidates(
                    db,
                    [fallback_names.get(line, line) for line in batch],
                )
            raw = await chat_completion(
                system=(
                    "You resolve grocery ingredient 'or' phrases conservatively for pantry "
                    "matching. Prefer a single shared ingredient for color/size varieties."
                ),
                user=_or_alternates_prompt(batch, candidates),
                temperature=0,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
            mapping.update(_parse_alternates_mapping(raw, batch))
        except Exception:
            logger.exception("Failed to resolve OR alternates starting with %r", batch[0])
        for line in batch:
            if line not in mapping:
                mapping[line] = heuristic_or_alternates(line, fallback_names.get(line, line))
    return mapping


async def _find_or_create_root(
    db: AsyncSession,
    canonical_name: str,
    source: Ingredient,
) -> Ingredient:
    root = await db.scalar(
        select(Ingredient).where(func.lower(Ingredient.name) == canonical_name)
    )
    if root is None:
        candidate = Ingredient(
            name=canonical_name,
            category=source.category,
            staple=source.staple,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
            root = candidate
        except IntegrityError:
            root = await db.scalar(
                select(Ingredient).where(func.lower(Ingredient.name) == canonical_name)
            )
            if root is None:
                raise RuntimeError(
                    f"Ingredient creation conflicted but {canonical_name!r} was not found"
                )

    if root.canonical_id is not None and root.canonical_id != root.id:
        canonical_root = await db.get(Ingredient, root.canonical_id)
        if canonical_root is not None:
            root = canonical_root
    if root.canonical_id is None:
        root.canonical_id = root.id
    return root


async def canonicalize_ingredients(
    db: AsyncSession,
    ingredients: list[Ingredient],
    *,
    timeout: float = 20.0,
    raw_hints: dict[str, str] | None = None,
) -> None:
    """Resolve ingredients to stable canonical roots without failing the caller."""
    if not settings.openai_api_key:
        return

    by_name = {
        normalize_ingredient_name(ingredient.name): ingredient
        for ingredient in ingredients
        if ingredient.canonical_id is None and normalize_ingredient_name(ingredient.name)
    }
    unresolved = list(by_name)
    for offset in range(0, len(unresolved), BATCH_SIZE):
        names = unresolved[offset : offset + BATCH_SIZE]
        try:
            candidates = await _canonical_candidates(db, names)
            raw = await chat_completion(
                system=(
                    "You normalize grocery ingredient names conservatively. False matches are "
                    "worse than missed matches. Never collapse a compound ingredient into a "
                    "different food."
                ),
                user=_canonicalization_prompt(names, candidates, raw_hints=raw_hints),
                temperature=0,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
            mapping = _parse_mapping(raw, names)
            for name in names:
                canonical_name = mapping.get(name)
                if canonical_name is None:
                    logger.warning("Canonicalization omitted ingredient %r", name)
                    continue
                ingredient = by_name[name]
                root = await _find_or_create_root(db, canonical_name, ingredient)
                ingredient.canonical_id = root.id
                if ingredient.name != root.name:
                    root.aliases = sorted(set(root.aliases + [ingredient.name]))
                root.category = root.category or ingredient.category
                root.staple = root.staple or ingredient.staple
        except Exception:
            logger.exception("Failed to canonicalize ingredient batch starting with %r", names[0])
