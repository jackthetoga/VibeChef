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


def _canonicalization_prompt(names: list[str], candidates: list[str]) -> str:
    numbered = "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1))
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
        "- Prefer an exact name from EXISTING CANONICALS when it applies. Otherwise return a "
        "short, lowercase ingredient noun phrase.\n"
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
                user=_canonicalization_prompt(names, candidates),
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
