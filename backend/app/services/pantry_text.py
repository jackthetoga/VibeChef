from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.services.llm import chat_completion
from app.services.units import UNIT_DEFINITIONS, normalize_unit

logger = logging.getLogger(__name__)

Action = Literal["add", "remove"]
MAX_CANONICAL_CHARS = 80
MAX_CANONICAL_WORDS = 8

REMOVE_PREFIXES = (
    r"used|removed|ate|finished|threw\s+away|threw\s+out|tossed|ran\s+out\s+of|"
    r"out\s+of|consumed|discarded|wasted|subtract(?:ed)?|minus|-"
)
ADD_PREFIXES = (
    r"bought|added|got|picked\s+up|restocked|purchased|received|brought|"
    r"stocked|grabbed|plus|\+"
)


def _parse_number(value: str) -> Decimal | None:
    value = value.strip()
    try:
        if " " in value and "/" in value:
            whole, fraction = value.split(" ", 1)
            numerator, denominator = fraction.split("/", 1)
            return Decimal(whole) + Decimal(numerator) / Decimal(denominator)
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return Decimal(numerator) / Decimal(denominator)
        return Decimal(value)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None


def _parse_ingredient_parts(raw: str) -> tuple[str, Decimal | None, str | None]:
    cleaned = re.sub(r"^\s*(?:[•*-]|\d+[.)])\s*", "", raw).strip()
    amount_match = re.match(
        r"^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*",
        cleaned,
    )
    quantity = _parse_number(amount_match.group(1)) if amount_match else None
    remainder = cleaned[amount_match.end() :] if amount_match else cleaned
    units = (
        "tablespoons?|tbsp|teaspoons?|tsp|cups?|ounces?|oz|pounds?|lb|grams?|g|"
        "kilograms?|kg|milliliters?|ml|liters?|l|cloves?|cans?|pieces?|bunch(?:es)?"
    )
    unit_match = re.match(rf"^({units})\b\.?\s*", remainder, flags=re.I)
    unit = unit_match.group(1).lower() if unit_match else None
    name_part = remainder[unit_match.end() :] if unit_match else remainder
    canonical = re.split(
        r",|\(|\b(?:chopped|diced|minced|sliced|to taste)\b",
        name_part,
        maxsplit=1,
    )[0]
    canonical = re.sub(r"[^a-zA-Z0-9' -]", "", canonical).strip().lower()
    canonical = re.sub(r"\s+", " ", canonical) or cleaned.lower()
    canonical = " ".join(canonical.split()[:MAX_CANONICAL_WORDS])[:MAX_CANONICAL_CHARS].strip()
    canonical = canonical[:255] or cleaned.lower()[:MAX_CANONICAL_CHARS]
    return canonical, quantity, unit


class ParsedPantryChange(BaseModel):
    action: Action
    name: str = Field(min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = " ".join(value.lower().split())
        if not name:
            raise ValueError("Ingredient name is required")
        return name

    @field_validator("unit")
    @classmethod
    def normalize_unit_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.lower().split())
        return cleaned or None


class ParsedPantryChanges(BaseModel):
    changes: list[ParsedPantryChange] = Field(default_factory=list)


def convert_quantity(
    quantity: Decimal,
    from_unit: str | None,
    to_unit: str | None,
) -> Decimal | None:
    """Convert quantity between units when they share a dimension.

    Missing unit on either side is treated as the other side's unit.
    """
    from_name = normalize_unit(from_unit) or normalize_unit(to_unit)
    to_name = normalize_unit(to_unit) or normalize_unit(from_unit)
    if from_name == to_name:
        return quantity
    if not from_name or not to_name:
        return quantity if not from_unit and not to_unit else None
    source = UNIT_DEFINITIONS.get(from_name)
    target = UNIT_DEFINITIONS.get(to_name)
    if not source or not target or source.dimension != target.dimension:
        return None
    return quantity * source.factor / target.factor


def apply_quantity_delta(
    current_quantity: Decimal | None,
    current_unit: str | None,
    delta: Decimal | None,
    delta_unit: str | None,
    *,
    sign: Literal[1, -1],
) -> tuple[Decimal | None, str | None, bool]:
    """Return (new_quantity, new_unit, remove_item).

    When remove_item is True the pantry row should be deleted.
    """
    if delta is None:
        if sign < 0:
            return None, current_unit, True
        return current_quantity, current_unit, False

    if current_quantity is None:
        if sign < 0:
            return None, current_unit, True
        return delta, delta_unit or current_unit, False

    converted = convert_quantity(delta, delta_unit, current_unit)
    if converted is None:
        if sign > 0:
            return delta, delta_unit or current_unit, False
        return None, current_unit, True

    new_quantity = current_quantity + (converted * sign)
    if new_quantity <= 0:
        return None, current_unit, True
    return new_quantity, current_unit or delta_unit, False


def _strip_action_prefix(line: str) -> tuple[Action | None, str]:
    cleaned = line.strip()
    cleaned = re.sub(r"^\s*(?:[•*]|\d+[.)])\s*", "", cleaned)
    remove_match = re.match(rf"^(?:{REMOVE_PREFIXES})\s+", cleaned, flags=re.I)
    if remove_match:
        return "remove", cleaned[remove_match.end() :].strip()
    add_match = re.match(rf"^(?:{ADD_PREFIXES})\s+", cleaned, flags=re.I)
    if add_match:
        return "add", cleaned[add_match.end() :].strip()
    if cleaned.startswith("-"):
        return "remove", cleaned[1:].strip()
    if cleaned.startswith("+"):
        return "add", cleaned[1:].strip()
    return None, cleaned


def _split_text_segments(text: str) -> list[str]:
    segments: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"\s*;\s*|\s*,\s+(?=(?:and\s+)?(?:\d|a |an |some |the ))", line)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            and_parts = re.split(r"\s+and\s+", part, flags=re.I)
            if len(and_parts) > 1 and all(
                re.match(r"^(?:\d|a |an |some |\+|-)", piece.strip(), flags=re.I)
                or _strip_action_prefix(piece)[0]
                for piece in and_parts
            ):
                segments.extend(piece.strip() for piece in and_parts if piece.strip())
            else:
                segments.append(part)
    return segments


def parse_pantry_text_rules(text: str) -> list[ParsedPantryChange]:
    """Deterministic parser for bullet/keyword inventory notes.

    Requires an explicit add/remove cue (+/−, bought, used, finished, …)
    so free prose without cues does not invent pantry changes.
    """
    changes: list[ParsedPantryChange] = []
    inherited_action: Action | None = None
    for segment in _split_text_segments(text):
        action, remainder = _strip_action_prefix(segment)
        if action is None:
            action = inherited_action
        else:
            inherited_action = action
        if action is None or not remainder:
            continue
        remainder = re.sub(r"^(?:of|the|some|a|an)\s+", "", remainder, flags=re.I).strip()
        if not remainder:
            continue
        name, quantity, unit = _parse_ingredient_parts(remainder)
        if not name:
            continue
        changes.append(
            ParsedPantryChange(action=action, name=name, quantity=quantity, unit=unit)
        )
    return _dedupe_changes(changes)


async def parse_pantry_text_llm(text: str) -> list[ParsedPantryChange] | None:
    if not settings.openai_api_key:
        return None
    prompt = (
        "Parse a home cook's fridge/pantry inventory note into structured changes.\n"
        "Each change is either an add (bought/got/restocked) or remove "
        "(used/ate/finished/threw out).\n"
        "Use short lowercase ingredient names (e.g. \"olive oil\", \"eggs\").\n"
        "Include quantity and unit when stated; otherwise null.\n"
        "If someone finished/ran out of an item with no amount, action=remove and "
        "quantity=null.\n"
        "Ignore non-ingredient chatter.\n"
        'Respond with JSON only: {"changes":[{"action":"add"|"remove",'
        '"name":"...","quantity":number|null,"unit":string|null}]}\n\n'
        f"Note:\n{text}"
    )
    try:
        content = await chat_completion(
            system=(
                "You extract grocery inventory changes for a pantry app. "
                "Return strict JSON only."
            ),
            user=prompt,
            temperature=0,
            response_format={"type": "json_object"},
            timeout=20.0,
        )
        data = json.loads(content)
        parsed = ParsedPantryChanges.model_validate(data)
        return _dedupe_changes(parsed.changes)
    except Exception:
        logger.exception("Failed to parse pantry text with LLM")
        return None


def _dedupe_changes(changes: list[ParsedPantryChange]) -> list[ParsedPantryChange]:
    """Merge same action+name into one change (sum quantities when both present)."""
    merged: dict[tuple[str, str], ParsedPantryChange] = {}
    order: list[tuple[str, str]] = []
    for change in changes:
        key = (change.action, change.name)
        existing = merged.get(key)
        if existing is None:
            merged[key] = change
            order.append(key)
            continue
        if change.quantity is None and existing.quantity is None:
            continue
        if change.quantity is None:
            if change.action == "remove":
                merged[key] = change
            continue
        if existing.quantity is None:
            merged[key] = change
            continue
        converted = convert_quantity(change.quantity, change.unit, existing.unit)
        if converted is None:
            merged[key] = change
            continue
        merged[key] = ParsedPantryChange(
            action=change.action,
            name=change.name,
            quantity=existing.quantity + converted,
            unit=existing.unit or change.unit,
        )
    return [merged[key] for key in order]


async def parse_pantry_text(text: str) -> list[ParsedPantryChange]:
    cleaned = text.strip()
    if not cleaned:
        return []
    llm_changes = await parse_pantry_text_llm(cleaned)
    if llm_changes is not None:
        return llm_changes
    return parse_pantry_text_rules(cleaned)
