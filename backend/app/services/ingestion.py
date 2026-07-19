import asyncio
import json
import logging
import mimetypes
import re
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Cookbook, Ingredient, Recipe, RecipeIngredient, UploadStatus
from app.services.canonicalize import canonicalize_ingredients, resolve_or_alternates
from app.services.catalog import (
    find_or_create_catalog_cookbook,
    recipe_fingerprint,
    sha256_file,
    upsert_catalog_recipe,
)
from app.services.llm import chat_completion
from app.services.nutrition import apply_printed_nutrition_metadata
from app.services.recipe_tagging import assign_recipe_tags

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 24_000
MAX_CANONICAL_CHARS = 80
MAX_CANONICAL_WORDS = 12
AMOUNT_TOKEN = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
EPUB_NOISE_NAME_TOKENS = (
    "toc",
    "nav",
    "copyright",
    "titlepage",
    "title_page",
    "cover",
    "colophon",
    "dedication",
    "contents",
    "frontmatter",
    "front_matter",
)

# Knopf / Random House cookbook EPUB CSS conventions (e.g. Marcella Hazan).
RECIPE_TITLE_CLASSES = frozenset({"rt", "rtaft", "rvh"})
RECIPE_YIELD_CLASSES = frozenset({"ry", "ry-alt", "rvy"})
RECIPE_INGREDIENT_CLASSES = frozenset({"ril", "rilf", "rill", "rils", "rvil", "rvilf", "rvill"})
RECIPE_INGREDIENT_HEADER_CLASSES = frozenset({"rilh"})
RECIPE_STEP_CLASSES = frozenset({"rp", "rpf", "rps", "rp-alt", "rpf-alt", "rvp", "rvps", "rv"})
# Variation intro/body prose often carries the only instructions.
RECIPE_VARIATION_BODY_CLASSES = frozenset({"rvf", "rvhn"})

# Simon & Schuster / Salt Fat Acid Heat-style recipe dialect.
SS_TITLE_CLASSES = frozenset({"h2rec", "h2rec1"})
SS_YIELD_CLASSES = frozenset({"right2"})
SS_INGREDIENT_CLASSES = frozenset({"item", "item1", "itemb"})
SS_PROSE_CLASSES = frozenset({"noindent", "indent"})
SS_VARIATION_HEADER_CLASSES = frozenset({"h5", "h5a"})
SS_VARIATION_BULLET_CLASSES = frozenset({"bull1", "bull1b"})

STRUCTURAL_SECTION_INGREDIENTS_RE = re.compile(
    r"(?i)^(?:ingredients?|what you.?ll need|you will need)\s*:?$"
)
STRUCTURAL_SECTION_STEPS_RE = re.compile(
    r"(?i)^(?:instructions?|directions?|method|preparation)\s*:?$"
)
STRUCTURAL_YIELD_RE = re.compile(r"(?i)^(?:serves|makes|yield|for)\b.{0,60}$")
STRUCTURAL_VARIATIONS_RE = re.compile(r"(?i)^variations?\s*:?$")
MIN_STRUCTURAL_INGREDIENTS = 2
MIN_STRUCTURAL_BOOK_RECIPES = 1

UNIT_PATTERN = (
    r"tablespoons?|tbsp|teaspoons?|tsp|cups?|ounces?|oz|pounds?|lbs?|grams?|g|"
    r"kilograms?|kg|milliliters?|ml|liters?|l|cloves?|cans?|bunch(?:es)?|stalks?|"
    r"slices?|sprigs?|leaves|parts?"
)
INGREDIENT_DESCRIPTORS = frozenset(
    {
        "black",
        "boiling",
        "brown",
        "cleaned",
        "crusted",
        "firm",
        "fresh",
        "good",
        "green",
        "hot",
        "imported",
        "italian",
        "juicy",
        "large",
        "lean",
        "meaty",
        "medium",
        "mild",
        "old",
        "orange",
        "plump",
        "purple",
        "quality",
        "red",
        "ripe",
        "round",
        "small",
        "smoked",
        "sweet",
        "tender",
        "thick",
        "toasting",
        "unshelled",
        "waxy",
        "white",
        "whole",
        "yellow",
    }
)
CONTEXT_TITLE_RE = re.compile(r"(?i)^(?:variation\b|the .+ version\b|when \b|alternative\b)")
CONTEXT_REFERENCE_RE = re.compile(
    r"(?i)\b(?:preceding recipe|previous recipe|recipe above|basic recipe|"
    r"same (?:soup|recipe|dish)|as described above|as given above|ingredients "
    r"(?:given|listed) (?:above|in the preceding recipe))\b"
)
NON_INGREDIENT_REFERENCE_RE = re.compile(
    r"(?i)^(?:all|the|to)\s+(?:of\s+the\s+)?ingredients?\b.*"
    r"(?:above|preceding|previous|recipe)"
)
EQUIPMENT_RE = re.compile(
    r"(?i)\b(?:cake pan|frying pan|saucepan|skillet|stockpot|baking dish|"
    r"cookie sheet|food processor|double boiler|mixing bowl|mold|toothpicks?|"
    r"wooden spoon|paring knife)\b|^(?:a|an|one|\d+)\b.*\bpans?\b"
)

_UNICODE_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅚": "5/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}


class ExtractedIngredient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    canonical_name: str = Field(min_length=1, max_length=255)
    raw_text: str = Field(min_length=1)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=80)
    aliases: list[str] = Field(default_factory=list)
    category: str | None = Field(default=None, max_length=120)
    staple: bool = False
    alternate_group: str | None = None
    section: str | None = Field(default=None, max_length=255)
    ambiguous_or: bool = False

    @field_validator("canonical_name", mode="before")
    @classmethod
    def coerce_canonical_name(cls, value: object) -> str:
        text = " ".join(str(value or "").lower().strip().split())
        if not text:
            raise ValueError("canonical_name required")
        # Never fail the whole cookbook on an oversized LLM string.
        if len(text) > 255:
            text = text[:255].rsplit(" ", 1)[0] or text[:255]
        return text

    @model_validator(mode="after")
    def shorten_prose_names(self) -> "ExtractedIngredient":
        name = self.canonical_name
        if _canonical_looks_like_prose(name):
            fallback = _short_name_from_raw(self.raw_text)
            if fallback and not _canonical_looks_like_prose(fallback):
                name = fallback
            else:
                name = _shorten_canonical_name(name)
        if not name:
            name = (
                _short_name_from_raw(self.raw_text) or self.raw_text.lower()[:MAX_CANONICAL_CHARS]
            )
        self.canonical_name = name[:255]
        return self


class ExtractedRecipe(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=255)
    servings: Decimal | None = None
    prep_minutes: int | None = Field(default=None, ge=0)
    cook_minutes: int | None = Field(default=None, ge=0)
    total_minutes: int | None = Field(default=None, ge=0)
    calories: Decimal | None = Field(default=None, ge=0)
    protein_grams: Decimal | None = Field(default=None, ge=0)
    carbs_grams: Decimal | None = Field(default=None, ge=0)
    fat_grams: Decimal | None = Field(default=None, ge=0)
    cuisine: str | None = Field(default=None, max_length=120)
    rating: Decimal | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    source_page: int | None = Field(default=None, ge=1)
    ingredients: list[ExtractedIngredient] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def coerce_title(cls, value: object) -> str:
        text = " ".join(str(value or "").strip().split())
        if not text:
            raise ValueError("title required")
        return text[:255]


class ExtractionEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    recipes: list[ExtractedRecipe]


def _canonical_looks_like_prose(name: str) -> bool:
    words = name.split()
    return len(name) > MAX_CANONICAL_CHARS or len(words) > MAX_CANONICAL_WORDS


def _shorten_canonical_name(name: str) -> str:
    """Prefer a food noun over blind mid-phrase truncation."""
    cleaned = " ".join(name.split())
    # Drop leaked quantified alternates only, not variety phrases like "red or green …"
    cleaned = re.split(
        rf"\s+or\s+{AMOUNT_TOKEN}\b",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    cleaned = re.split(
        r"\b(?:chopped|diced|minced|sliced|peeled|drained|cut up|with their)\b",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )[0].strip(" ,")
    words = cleaned.split()
    if len(words) > MAX_CANONICAL_WORDS:
        cleaned = " ".join(words[:MAX_CANONICAL_WORDS])
    return cleaned[:MAX_CANONICAL_CHARS].strip()


def _normalize_amount_text(value: str) -> str:
    """Expand unicode vulgar fractions so 1½ becomes 1 1/2."""
    text = value
    for glyph, ascii_frac in _UNICODE_FRACTIONS.items():
        text = re.sub(rf"(\d){re.escape(glyph)}", rf"\1 {ascii_frac}", text)
        text = text.replace(glyph, ascii_frac)
    return text


def parse_number(value: str) -> Decimal | None:
    value = _normalize_amount_text(value).strip()
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


def parse_servings(text: str) -> Decimal | None:
    """Parse yield lines like 'For 6 servings', 'Serves 4 to 6', or 'Makes 12'."""
    normalized = _normalize_amount_text(text)
    # Volume yields ("About 1 2/3 cups", "1 1/2 to 2 quarts") are not servings.
    if re.search(
        r"(?i)\b(?:cups?|quarts?|pints?|liters?|litres?|ml|ounces?|oz|pounds?|lb|grams?|kg)\b",
        normalized,
    ):
        return None
    match = re.search(
        r"(?i)(?:(?:for|serves|makes)\s+)?(\d+)(?:\s*(?:to|-|–|—|/)\s*(\d+))?\s*"
        r"(?:or\s+more\s+)?"
        r"(?:servings?|people|persons?|guests?|canap[eé]s?|portions?)?\b",
        normalized,
    )
    if not match:
        return None
    # Require an explicit serving-like cue.
    if not re.search(
        r"(?i)\b(?:for|serves|makes|servings?|people|persons?|guests?|canap[eé]s?|portions?)\b",
        normalized,
    ):
        return None
    low = Decimal(match.group(1))
    high = match.group(2)
    if high:
        return (low + Decimal(high)) / 2
    return low


def _strip_leading_descriptors(name: str) -> str:
    words = name.split()
    while len(words) > 1:
        leading_parts = re.findall(r"[a-z]+", words[0].lower())
        if not leading_parts or not all(part in INGREDIENT_DESCRIPTORS for part in leading_parts):
            break
        words.pop(0)
    return " ".join(words)


def _segment_is_descriptor_only(segment: str) -> bool:
    words = re.findall(r"[A-Za-z']+", segment.lower())
    return bool(words) and all(word in INGREDIENT_DESCRIPTORS for word in words)


def _ingredient_name_from_remainder(remainder: str) -> str:
    """Keep comma-separated descriptors until the actual ingredient noun appears."""
    remainder = re.sub(r"\([^)]*\)", "", remainder).strip()
    # Drop dimensional prefixes: "A 1/2-inch-thick slice of prosciutto" → "prosciutto…"
    remainder = re.sub(
        r"(?i)^(?:a|an)\s+(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)-inch(?:-thick)?\s+"
        r"(?:slice\s+of\s+)?",
        "",
        remainder,
    ).strip()
    segments = [segment.strip() for segment in remainder.split(",") if segment.strip()]
    if not segments:
        return remainder

    selected: list[str] = []
    crossed_descriptor_comma = False
    for segment in segments:
        selected.append(segment)
        if _segment_is_descriptor_only(segment):
            crossed_descriptor_comma = True
            continue
        break

    name = " ".join(selected)
    name = re.sub(
        r"(?i)^(?:(?:freshly|finely|coarsely)\s+)?"
        r"(?:chopped|diced|minced|sliced|peeled|pitted|trimmed|grated)\s+",
        "",
        name,
    )
    name = re.split(
        r"\b(?:chopped|diced|minced|sliced|peeled|pitted|trimmed|to taste)\b",
        name,
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    # Drop size ranges and processing-state prefixes: "small to medium whole squid" → "squid"
    name = re.sub(
        r"(?i)^(?:(?:small|medium|large)(?:\s+to\s+(?:small|medium|large))?|whole|cleaned|"
        r"unshelled)(?:\s+(?:small|medium|large|whole|cleaned|unshelled))*\s+",
        "",
        name,
    ).strip()
    if crossed_descriptor_comma:
        name = _strip_leading_descriptors(name)

    # If comma-walking left only descriptors (e.g. stopped too early), use the final noun phrase.
    name_words = re.findall(r"[a-z']+", name.lower())
    if not name_words or set(name_words).issubset(INGREDIENT_DESCRIPTORS):
        name = _strip_leading_descriptors(segments[-1])
        name = re.split(
            r"\b(?:chopped|diced|minced|sliced|peeled|pitted|trimmed|to taste)\b",
            name,
            maxsplit=1,
            flags=re.I,
        )[0].strip()
    return name


def _normalize_known_ingredient_name(name: str) -> str:
    """Collapse pantry-equivalent variants to stable matching names."""
    words = set(re.findall(r"[a-z']+", name.lower()))
    if ("tomato" in words or "tomatoes" in words) and ("canned" in words or "tinned" in words):
        return "canned tomatoes"
    return name


def _parse_ingredient_parts(raw: str) -> tuple[str, str, Decimal | None, str | None]:
    """Return (canonical_name, cleaned_raw, quantity, unit) without model validation."""
    cleaned = re.sub(r"^\s*(?:[•*-]|\d+[.)])\s*", "", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    amount_source = _normalize_amount_text(cleaned)
    amount_match = re.match(
        rf"^({AMOUNT_TOKEN})\s*",
        amount_source,
    )
    quantity = parse_number(amount_match.group(1)) if amount_match else None
    remainder = amount_source[amount_match.end() :] if amount_match else amount_source
    remainder = re.sub(
        rf"^(?:or|to|-|–|—)\s*{AMOUNT_TOKEN}\s*",
        "",
        remainder,
        flags=re.I,
    )
    unit_match = re.match(rf"^({UNIT_PATTERN})\b\.?\s*", remainder, flags=re.I)
    unit = unit_match.group(1).lower() if unit_match else None
    name_part = remainder[unit_match.end() :] if unit_match else remainder
    # Safety: if an unsplit quantified alternate leaked into the name, keep the first branch.
    name_part = re.split(
        rf"\s+or\s+{AMOUNT_TOKEN}\b",
        name_part,
        maxsplit=1,
        flags=re.I,
    )[0]
    canonical = _ingredient_name_from_remainder(name_part)
    # Keep fraction slashes so "1/2-inch" does not collapse to "12-inch".
    canonical = re.sub(r"[^a-zA-Z0-9' /-]", "", canonical).strip().lower()
    canonical = re.sub(r"\s+", " ", canonical) or cleaned.lower()
    canonical = _shorten_canonical_name(canonical) or cleaned.lower()[:MAX_CANONICAL_CHARS]
    canonical = _normalize_known_ingredient_name(canonical)
    canonical = canonical[:255] or cleaned.lower()[:MAX_CANONICAL_CHARS]
    return canonical, cleaned, quantity, unit


def _is_quantity_range_or(raw: str) -> bool:
    """True for lines like '1 or 2 celery stalks' (not ingredient alternates)."""
    normalized = _normalize_amount_text(raw)
    return bool(
        re.match(
            rf"^{AMOUNT_TOKEN}\s+or\s+{AMOUNT_TOKEN}\b",
            normalized,
            flags=re.I,
        )
    )


def _looks_like_variety_or(left: str, right: str) -> bool:
    """True for color/variety choices like 'red or green bell peppers'."""
    colors = {"black", "brown", "green", "orange", "purple", "red", "white", "yellow"}
    color_pattern = "|".join(sorted(colors))
    return bool(
        re.search(
            rf"(?i)\b(?:{color_pattern})\b.+\b(?:{color_pattern})\b",
            f"{left} or {right}",
        )
    )


def _split_quantified_or_segments(raw: str) -> list[str] | None:
    """Split '2 lb X or 3 cups Y' (and shared-qty 'N cup X or canned Y') into segments."""
    if _is_quantity_range_or(raw):
        return None
    normalized = _normalize_amount_text(raw)
    pattern = re.compile(rf"\s+or\s+(?={AMOUNT_TOKEN}\b)", flags=re.I)
    matches = list(pattern.finditer(normalized))
    if matches:
        left = normalized[: matches[0].start()].strip()
        # Incomplete left side means a quantity range that slipped past the earlier check.
        if re.fullmatch(rf"{AMOUNT_TOKEN}", left, flags=re.I):
            return None
        if not re.search(rf"{AMOUNT_TOKEN}\s+(?:{UNIT_PATTERN})\b|[A-Za-z]", left, flags=re.I):
            return None
        segments: list[str] = []
        previous = 0
        for match in matches:
            segment = normalized[previous : match.start()].strip(" ,;")
            if segment:
                segments.append(segment)
            previous = match.end()
        tail = normalized[previous:].strip(" ,;")
        if tail:
            segments.append(tail)
        return segments if len(segments) >= 2 else None

    # Shared quantity: "3/4 cup fresh tomatoes ... or canned imported ... tomatoes"
    shared = re.search(
        rf"\s+or\s+(?!{AMOUNT_TOKEN}\b)(?=[A-Za-z])",
        normalized,
        flags=re.I,
    )
    if not shared:
        return None
    left = normalized[: shared.start()].strip(" ,;")
    right = normalized[shared.end() :].strip(" ,;")
    if not re.match(rf"^{AMOUNT_TOKEN}\b", left, flags=re.I):
        return None
    if _looks_like_variety_or(left, right):
        return None
    if len(right.split()) < 2:
        return None
    amount_match = re.match(rf"^({AMOUNT_TOKEN})\s*", left, flags=re.I)
    if not amount_match:
        return None
    remainder = left[amount_match.end() :]
    unit_match = re.match(rf"^({UNIT_PATTERN})\b\.?\s*", remainder, flags=re.I)
    prefix_end = amount_match.end() + (unit_match.end() if unit_match else 0)
    prefix = left[:prefix_end].strip()
    if not prefix:
        return None
    return [left, f"{prefix} {right}".strip()]


def _has_ambiguous_or(raw: str) -> bool:
    """True when 'or' joins varieties/substitutes without separate quantities."""
    if _split_quantified_or_segments(raw) is not None or _is_quantity_range_or(raw):
        return False
    return bool(re.search(r"(?i)\bor\b", raw))


def _short_name_from_raw(raw_text: str) -> str:
    return _parse_ingredient_parts(raw_text)[0]


def deduplicate_recipes(recipes: list[ExtractedRecipe]) -> list[ExtractedRecipe]:
    unique: list[ExtractedRecipe] = []
    seen: set[tuple[object, ...]] = set()
    for recipe in recipes:
        identity = (
            " ".join(recipe.title.lower().split()),
            recipe.source_page,
            tuple(" ".join(item.raw_text.lower().split()) for item in recipe.ingredients),
            tuple(" ".join(step.lower().split()) for step in recipe.steps),
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(recipe)
    return unique


async def resolve_ingredient(db: AsyncSession, extracted: ExtractedIngredient) -> Ingredient:
    from app.services.staples import is_staple_name

    name = extracted.canonical_name
    staple = extracted.staple or is_staple_name(name)
    ingredient = await db.scalar(select(Ingredient).where(func.lower(Ingredient.name) == name))
    if ingredient is None:
        candidate = Ingredient(
            name=name,
            aliases=extracted.aliases,
            category=extracted.category,
            staple=staple,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
            ingredient = candidate
        except IntegrityError:
            ingredient = await db.scalar(
                select(Ingredient).where(func.lower(Ingredient.name) == name)
            )
            if ingredient is None:
                raise RuntimeError(f"Ingredient creation conflicted but {name!r} was not found")

    ingredient.aliases = sorted(set(ingredient.aliases + extracted.aliases))
    ingredient.staple = ingredient.staple or staple
    ingredient.category = ingredient.category or extracted.category
    return ingredient


def _html_to_text(content: bytes | str) -> str:
    """Preserve list/paragraph structure and keep spaces between inline runs.

    BeautifulSoup's get_text(..., strip=True) strips NavigableString values, so
    raw newline markers would disappear. Use placeholders, then restore breaks.
    """
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("[[BR]]")
    for li in soup.find_all("li"):
        li.insert_before("[[LI]]")
        li.append("[[/LI]]")
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        heading.insert_before("[[H]]")
        heading.append("[[/H]]")
    for block in soup.find_all(["p", "div", "section", "article", "tr", "blockquote"]):
        block.insert_before("[[P]]")
        block.append("[[/P]]")
    # Space separator avoids mashing adjacent inline nodes ("spices" + "except").
    text = soup.get_text(" ", strip=True)
    text = (
        text.replace("[[LI]]", "\n• ")
        .replace("[[/LI]]", "\n")
        .replace("[[H]]", "\n")
        .replace("[[/H]]", "\n")
        .replace("[[P]]", "\n")
        .replace("[[/P]]", "\n")
        .replace("[[BR]]", "\n")
    )
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _is_epub_noise_document(item) -> bool:
    item_id = (item.get_id() or "").lower()
    name = (item.get_name() or "").lower()
    properties = {str(value).lower() for value in (getattr(item, "properties", None) or [])}
    if "nav" in properties:
        return True
    return any(token in item_id or token in name for token in EPUB_NOISE_NAME_TOKENS)


def _iter_epub_documents(book):
    import ebooklib

    items_by_id = {item.get_id(): item for item in book.get_items()}
    seen: set[str] = set()
    ordered = []
    for item_id, _linear in book.spine:
        item = items_by_id.get(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        if item_id in seen:
            continue
        seen.add(item_id)
        ordered.append(item)
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        item_id = item.get_id()
        if item_id in seen:
            continue
        seen.add(item_id)
        ordered.append(item)
    return [item for item in ordered if not _is_epub_noise_document(item)]


def _paragraph_classes(tag) -> set[str]:
    return {str(value).lower() for value in (tag.get("class") or [])}


def _epub_class_hit_counts(
    book,
    *,
    title_classes: frozenset[str],
    ingredient_classes: frozenset[str],
) -> tuple[int, int]:
    title_hits = 0
    ingredient_hits = 0
    for item in _iter_epub_documents(book):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup.find_all(True, class_=True):
            classes = _paragraph_classes(tag)
            if classes & title_classes:
                title_hits += 1
            if classes & ingredient_classes:
                ingredient_hits += 1
            if title_hits >= 5 and ingredient_hits >= 10:
                return title_hits, ingredient_hits
    return title_hits, ingredient_hits


def _epub_has_knopf_markup(book) -> bool:
    title_hits, ingredient_hits = _epub_class_hit_counts(
        book,
        title_classes=RECIPE_TITLE_CLASSES,
        ingredient_classes=RECIPE_INGREDIENT_CLASSES,
    )
    return (title_hits >= 5 and ingredient_hits >= 10) or (title_hits >= 3 and ingredient_hits >= 5)


def _epub_has_simon_schuster_markup(book) -> bool:
    title_hits, ingredient_hits = _epub_class_hit_counts(
        book,
        title_classes=SS_TITLE_CLASSES,
        ingredient_classes=SS_INGREDIENT_CLASSES,
    )
    return (title_hits >= 5 and ingredient_hits >= 10) or (title_hits >= 3 and ingredient_hits >= 5)


def _epub_has_recipe_markup(book) -> bool:
    """Backward-compatible alias: Knopf-style markup only."""
    return _epub_has_knopf_markup(book)


def _is_non_ingredient_line(text: str) -> bool:
    cleaned = " ".join(text.split()).strip()
    return bool(
        not cleaned
        or NON_INGREDIENT_REFERENCE_RE.search(cleaned)
        or EQUIPMENT_RE.search(cleaned)
        or re.match(r"(?i)^for (?:the |making |cooking |finishing )?[a-z ]{2,40}$", cleaned)
    )


def _ingredient_is_valid(ingredient: ExtractedIngredient) -> bool:
    name = ingredient.canonical_name.strip().lower()
    words = set(name.split())
    return bool(
        name
        and not _is_non_ingredient_line(ingredient.raw_text)
        and not words.issubset(INGREDIENT_DESCRIPTORS)
    )


def _repair_ingredient(ingredient: ExtractedIngredient) -> ExtractedIngredient:
    name_words = set(ingredient.canonical_name.lower().split())
    if name_words and not name_words.issubset(INGREDIENT_DESCRIPTORS):
        return ingredient
    repaired = demo_ingredient(ingredient.raw_text)
    return repaired.model_copy(
        update={
            "alternate_group": ingredient.alternate_group,
            "section": ingredient.section,
            "ambiguous_or": ingredient.ambiguous_or,
        }
    )


def _ingredient_key(ingredient: ExtractedIngredient) -> str:
    words = [
        word.rstrip("s")
        for word in re.findall(r"[a-z]+", ingredient.canonical_name.lower())
        if word not in INGREDIENT_DESCRIPTORS
    ]
    return " ".join(words) or ingredient.canonical_name.lower()


def _merge_ingredients(
    base: list[ExtractedIngredient],
    overrides: list[ExtractedIngredient],
) -> list[ExtractedIngredient]:
    merged = [ingredient.model_copy(deep=True) for ingredient in base]
    positions = {_ingredient_key(item): index for index, item in enumerate(merged)}
    for ingredient in overrides:
        key = _ingredient_key(ingredient)
        if key in positions:
            merged[positions[key]] = ingredient
        else:
            positions[key] = len(merged)
            merged.append(ingredient)
    return merged


def _ingredient_mentioned(text: str, ingredient: ExtractedIngredient) -> bool:
    haystack = {word.rstrip("s") for word in re.findall(r"[a-z]+", text.lower())}
    needles = [
        word.rstrip("s")
        for word in re.findall(r"[a-z]+", ingredient.canonical_name.lower())
        if word not in INGREDIENT_DESCRIPTORS and len(word) > 2
    ]
    return bool(needles and any(word in haystack for word in needles))


def _apply_variation_omissions(
    ingredients: list[ExtractedIngredient], instructions: str
) -> list[ExtractedIngredient]:
    omission_texts = [
        match.group(1)
        for match in re.finditer(
            r"(?i)\bomit\s+(.+?)(?="
            r"\s+from the (?:previous|preceding) recipe|"
            r"[.,;]|"
            r"\band (?:add|drizzle|replace|substitute|use)\b|"
            r"\bfollow\b|$)",
            instructions,
        )
    ]
    omission_texts.extend(
        match.group(1)
        for match in re.finditer(
            r"(?i)\bsubstitute\b.+?\bfor\s+(.+?)(?=\.|;|,|\band\b|$)",
            instructions,
        )
    )
    if not omission_texts:
        return ingredients
    return [
        ingredient
        for ingredient in ingredients
        if not any(_ingredient_mentioned(text, ingredient) for text in omission_texts)
    ]


def _extract_quantified_ingredients(text: str) -> list[ExtractedIngredient]:
    """Recover quantified additions embedded in variation prose."""
    normalized = _normalize_amount_text(text)
    starts = list(
        re.finditer(
            rf"(?<![\w/])(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s+"
            rf"(?:{UNIT_PATTERN})\b",
            normalized,
            flags=re.I,
        )
    )
    extracted: list[ExtractedIngredient] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(normalized)
        raw = normalized[match.start() : end]
        raw = re.split(r"[.;]|\b(?:follow|cook|prepare|make)\b", raw, maxsplit=1, flags=re.I)[0]
        raw = re.split(r"\s+\bfor\b\s+", raw, maxsplit=1, flags=re.I)[0]
        raw = re.sub(r"(?:,\s*)?(?:and|or|plus)\s*$", "", raw, flags=re.I).strip(" ,")
        if raw and not _is_non_ingredient_line(raw):
            ingredient = demo_ingredient(raw)
            if _ingredient_is_valid(ingredient):
                extracted.append(ingredient)
    return extracted


def _resolve_context_ingredients(
    *,
    parsed: list[ExtractedIngredient],
    base: ExtractedRecipe | None,
    modification_text: str,
) -> list[ExtractedIngredient]:
    concrete = [_repair_ingredient(item) for item in parsed if _ingredient_is_valid(item)]
    if base is None:
        return concrete
    if len(concrete) >= 2:
        return concrete

    inherited = [item.model_copy(deep=True) for item in base.ingredients]
    inherited = _apply_variation_omissions(inherited, modification_text)
    additions = _extract_quantified_ingredients(modification_text)
    return _merge_ingredients(inherited, concrete + additions)


TITLE_AUDIT_STOPWORDS = frozenset(
    {
        "a",
        "alla",
        "alle",
        "alternative",
        "and",
        "basic",
        "con",
        "di",
        "for",
        "from",
        "in",
        "of",
        "only",
        "or",
        "recipe",
        "style",
        "the",
        "to",
        "tuscan",
        "uses",
        "variation",
        "version",
        "with",
        "without",
    }
)
TITLE_AUDIT_METHODS = frozenset(
    {
        "baked",
        "braised",
        "broiled",
        "fried",
        "grilled",
        "marinated",
        "poached",
        "roasted",
        "sauteed",
        "sautéed",
        "simmered",
        "smothered",
        "steamed",
        "stuffed",
    }
)


def _title_food_tokens(title: str) -> list[str]:
    primary = re.split(r"\s+[—–-]\s+", title, maxsplit=1)[0]
    tokens = [
        token.rstrip("s")
        for token in re.findall(r"[A-Za-z']+", primary.lower())
        if len(token) > 3
        and token not in TITLE_AUDIT_STOPWORDS
        and token not in TITLE_AUDIT_METHODS
        and token not in INGREDIENT_DESCRIPTORS
    ]
    # Prefer distinctive tokens; drop very generic dish carriers unless alone.
    generic = {"pasta", "soup", "sauce", "salad", "bread", "pizza", "risotto", "stew"}
    distinctive = [token for token in tokens if token not in generic]
    return distinctive or tokens


def _flag_title_ingredient_gaps(recipe: ExtractedRecipe) -> list[str]:
    """Flag title food nouns absent from ingredient text. Never invent ingredients."""
    corpus = " ".join(
        f"{item.canonical_name} {item.raw_text}" for item in recipe.ingredients
    ).lower()
    corpus_tokens = {word.rstrip("s") for word in re.findall(r"[a-z']+", corpus)}
    warnings: list[str] = []
    for token in _title_food_tokens(recipe.title):
        if token not in corpus_tokens:
            warnings.append(f'title mentions "{token}" but no matching ingredient was parsed')
    return warnings


def quality_assure_recipes(recipes: list[ExtractedRecipe]) -> list[ExtractedRecipe]:
    """Repair suspicious ingredient names and reject incomplete recipe records."""
    accepted: list[ExtractedRecipe] = []
    for recipe in recipes:
        expanded_source: list[ExtractedIngredient] = []
        for original in recipe.ingredients:
            # Re-run line parsing so LLM/demo output also gets quantified OR splits.
            if original.alternate_group or (
                not _has_ambiguous_or(original.raw_text)
                and _split_quantified_or_segments(original.raw_text) is None
            ):
                expanded_source.append(original)
            else:
                expanded_source.extend(
                    parse_ingredient_line(original.raw_text, section=original.section)
                )

        ingredients: list[ExtractedIngredient] = []
        seen_rows: set[tuple[str, str, str | None]] = set()
        for original in expanded_source:
            ingredient = _repair_ingredient(original)
            if not _ingredient_is_valid(ingredient):
                continue
            row_key = (
                _ingredient_key(ingredient),
                ingredient.raw_text.lower(),
                ingredient.alternate_group,
                str(ingredient.quantity),
                ingredient.unit,
            )
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            ingredients.append(ingredient)

        title = " ".join(recipe.title.split()).strip()
        unresolved_context = CONTEXT_TITLE_RE.match(title) and " — " not in title
        if not ingredients or unresolved_context:
            logger.warning(
                "Recipe QA rejected %r: ingredients=%s unresolved_context=%s",
                title,
                len(ingredients),
                bool(unresolved_context),
            )
            continue
        warnings = list(recipe.parse_warnings) + _flag_title_ingredient_gaps(
            recipe.model_copy(update={"title": title, "ingredients": ingredients})
        )
        for warning in warnings:
            logger.info("Recipe parse warning for %r: %s", title, warning)
        accepted.append(
            recipe.model_copy(
                update={
                    "title": title,
                    "ingredients": ingredients,
                    "parse_warnings": warnings,
                }
            )
        )
    return deduplicate_recipes(accepted)


def _finalize_structured_recipe(
    *,
    title: str,
    yield_text: str | None,
    variation_body: list[str],
    ingredient_lines: list[tuple[str | None, str]],
    steps: list[str],
) -> ExtractedRecipe | None:
    title = " ".join(title.split()).strip()
    if not title:
        return None
    cleaned_steps = [
        re.sub(r"^\s*(?:\d+[.)]|[•*-])\s*", "", step).strip() for step in steps if step.strip()
    ]
    # Variation write-ups often put the full method in prose instead of numbered steps.
    if not cleaned_steps and variation_body:
        cleaned_steps = [note.strip() for note in variation_body if note.strip()]
    ingredients: list[ExtractedIngredient] = []
    for section, line in ingredient_lines:
        if not line.strip() or _is_non_ingredient_line(line):
            continue
        ingredients.extend(parse_ingredient_line(line, section=section))
    if not ingredients and not cleaned_steps:
        return None
    return ExtractedRecipe(
        title=title[:255],
        servings=parse_servings(yield_text) if yield_text else None,
        ingredients=ingredients,
        steps=cleaned_steps,
    )


def _parse_structured_epub_document(content: bytes | str) -> list[ExtractedRecipe]:
    soup = BeautifulSoup(content, "html.parser")
    recipes: list[ExtractedRecipe] = []

    current_title: str | None = None
    yield_text: str | None = None
    variation_body: list[str] = []
    ingredient_lines: list[tuple[str | None, str]] = []
    steps: list[str] = []
    current_section: str | None = None
    current_is_variation = False
    primary_title: str | None = None
    primary_recipe: ExtractedRecipe | None = None
    previous_recipe: ExtractedRecipe | None = None

    def flush() -> None:
        nonlocal current_title, yield_text, variation_body, ingredient_lines, steps
        nonlocal current_section, current_is_variation, primary_recipe, previous_recipe
        if current_title is None:
            return
        recipe = _finalize_structured_recipe(
            title=current_title,
            yield_text=yield_text,
            variation_body=variation_body,
            ingredient_lines=ingredient_lines,
            steps=steps,
        )
        if recipe is not None:
            source_text = " ".join([line for _, line in ingredient_lines] + variation_body + steps)
            reference_dependent = not recipe.ingredients and bool(
                CONTEXT_REFERENCE_RE.search(source_text)
            )
            context = primary_recipe if current_is_variation else previous_recipe
            if current_is_variation and primary_title:
                recipe.title = f"{primary_title} — {recipe.title}"[:255]
            if current_is_variation or reference_dependent:
                recipe.ingredients = _resolve_context_ingredients(
                    parsed=recipe.ingredients,
                    base=context,
                    modification_text=" ".join(variation_body + steps),
                )
            if recipe.ingredients:
                recipes.append(recipe)
                previous_recipe = recipe
                if not current_is_variation:
                    primary_recipe = recipe
                elif primary_recipe is None:
                    primary_recipe = recipe
        current_title = None
        yield_text = None
        variation_body = []
        ingredient_lines = []
        steps = []
        current_section = None
        current_is_variation = False

    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4"]):
        classes = _paragraph_classes(tag)
        text = " ".join(tag.get_text(" ", strip=True).split())
        if not text:
            continue

        if classes & RECIPE_TITLE_CLASSES:
            flush()
            current_title = text
            current_is_variation = "rvh" in classes or bool(CONTEXT_TITLE_RE.match(text))
            if not current_is_variation:
                primary_title = text
                primary_recipe = None
            continue

        if current_title is None:
            continue

        if classes & RECIPE_YIELD_CLASSES:
            yield_text = text
        elif classes & RECIPE_INGREDIENT_HEADER_CLASSES:
            # Section labels only — never treated as ingredients.
            current_section = text.rstrip(":").strip()[:255] or None
        elif classes & RECIPE_VARIATION_BODY_CLASSES:
            variation_body.append(text)
        elif classes & RECIPE_INGREDIENT_CLASSES:
            ingredient_lines.append((current_section, text))
        elif classes & RECIPE_STEP_CLASSES:
            steps.append(text)
        # Headnotes (rhn*) and notes (rn*) are skipped: essays reuse those classes.

    flush()
    return recipes


def _parse_simon_schuster_epub_document(content: bytes | str) -> list[ExtractedRecipe]:
    """Parse SFAH-style recipes: h2rec title, right2 yield, item* ingredients."""
    soup = BeautifulSoup(content, "html.parser")
    recipes: list[ExtractedRecipe] = []

    current_title: str | None = None
    yield_text: str | None = None
    ingredient_lines: list[tuple[str | None, str]] = []
    steps: list[str] = []
    # before_ingredients | in_ingredients | in_steps | in_variations
    phase = "before_ingredients"

    def flush() -> None:
        nonlocal current_title, yield_text, ingredient_lines, steps, phase
        if current_title is None:
            return
        recipe = _finalize_structured_recipe(
            title=current_title,
            yield_text=yield_text,
            variation_body=[],
            ingredient_lines=ingredient_lines,
            steps=steps,
        )
        if recipe is not None and recipe.ingredients:
            recipes.append(recipe)
        current_title = None
        yield_text = None
        ingredient_lines = []
        steps = []
        phase = "before_ingredients"

    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
        classes = _paragraph_classes(tag)
        text = " ".join(tag.get_text(" ", strip=True).split())
        if not text:
            continue

        if classes & SS_TITLE_CLASSES:
            flush()
            current_title = text
            phase = "before_ingredients"
            continue

        if current_title is None:
            continue

        if classes & SS_VARIATION_HEADER_CLASSES and STRUCTURAL_VARIATIONS_RE.match(text):
            phase = "in_variations"
            continue

        if phase == "in_variations" or classes & SS_VARIATION_BULLET_CLASSES:
            # Phase 1: skip variation bullets; do not treat as recipes/steps.
            continue

        if classes & SS_YIELD_CLASSES:
            yield_text = text
            continue

        if classes & SS_INGREDIENT_CLASSES:
            ingredient_lines.append((None, text))
            phase = "in_ingredients"
            continue

        if classes & SS_PROSE_CLASSES:
            if phase == "before_ingredients":
                # Headnote between title/yield and the ingredient list — not steps.
                continue
            if phase in {"in_ingredients", "in_steps"}:
                steps.append(text)
                phase = "in_steps"
            continue

    flush()
    return recipes


def _looks_like_ingredient_line(text: str) -> bool:
    cleaned = " ".join(text.split()).strip()
    if not cleaned or len(cleaned) > 180:
        return False
    if STRUCTURAL_SECTION_INGREDIENTS_RE.match(cleaned):
        return False
    if STRUCTURAL_SECTION_STEPS_RE.match(cleaned):
        return False
    if STRUCTURAL_VARIATIONS_RE.match(cleaned):
        return False
    if STRUCTURAL_YIELD_RE.match(cleaned):
        return False
    if _is_non_ingredient_line(cleaned):
        return False
    # Numbered directions are steps, not ingredients.
    if re.match(r"^\d+[.)]\s+\S", cleaned):
        return False
    normalized = _normalize_amount_text(cleaned)
    if re.match(rf"(?i)^{AMOUNT_TOKEN}\b", normalized):
        return True
    lower = cleaned.lower().rstrip(".")
    staples = {
        "salt",
        "pepper",
        "black pepper",
        "freshly ground black pepper",
        "flaky salt",
        "kosher salt",
        "sea salt",
        "olive oil",
        "extra-virgin olive oil",
        "extra virgin olive oil",
        "water",
        "butter",
    }
    return lower in staples


def _is_structural_title_candidate(tag_name: str, text: str) -> bool:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) < 3 or len(cleaned) > 80:
        return False
    if STRUCTURAL_SECTION_INGREDIENTS_RE.match(cleaned):
        return False
    if STRUCTURAL_SECTION_STEPS_RE.match(cleaned):
        return False
    if STRUCTURAL_VARIATIONS_RE.match(cleaned):
        return False
    if STRUCTURAL_YIELD_RE.match(cleaned):
        return False
    if tag_name in {"h1", "h2", "h3", "h4"}:
        return True
    # Allow short title-case paragraphs only when they look like dish names.
    if tag_name == "p" and not cleaned.endswith("."):
        letters = re.sub(r"[^A-Za-z]+", "", cleaned)
        if letters and letters[0].isupper() and " " in cleaned:
            return True
    return False


def _parse_structural_epub_document(content: bytes | str) -> list[ExtractedRecipe]:
    """CSS-agnostic recipe recovery from headings + ingredient-like runs."""
    soup = BeautifulSoup(content, "html.parser")
    blocks: list[tuple[str, str]] = []
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if text:
            blocks.append((tag.name, text))

    recipes: list[ExtractedRecipe] = []
    index = 0
    while index < len(blocks):
        tag_name, text = blocks[index]
        if not _is_structural_title_candidate(tag_name, text):
            index += 1
            continue

        title = text
        cursor = index + 1
        yield_text: str | None = None
        ingredient_lines: list[tuple[str | None, str]] = []
        steps: list[str] = []
        in_ingredient_section = False
        in_step_section = False
        saw_explicit_sections = False

        while cursor < len(blocks):
            next_tag, next_text = blocks[cursor]
            if cursor > index and _is_structural_title_candidate(next_tag, next_text):
                # Next recipe title — stop without consuming it.
                break
            if STRUCTURAL_VARIATIONS_RE.match(next_text):
                break
            if STRUCTURAL_YIELD_RE.match(next_text) and not ingredient_lines and not steps:
                yield_text = next_text
                cursor += 1
                continue
            if STRUCTURAL_SECTION_INGREDIENTS_RE.match(next_text):
                in_ingredient_section = True
                in_step_section = False
                saw_explicit_sections = True
                cursor += 1
                continue
            if STRUCTURAL_SECTION_STEPS_RE.match(next_text):
                in_ingredient_section = False
                in_step_section = True
                saw_explicit_sections = True
                cursor += 1
                continue

            if in_step_section:
                steps.append(next_text)
                cursor += 1
                continue

            if in_ingredient_section or (
                not saw_explicit_sections
                and (next_tag == "li" or _looks_like_ingredient_line(next_text))
            ):
                # Once steps have started without an Ingredients heading, stop
                # treating prose as ingredients.
                if (
                    not in_ingredient_section
                    and ingredient_lines
                    and not _looks_like_ingredient_line(next_text)
                    and next_tag != "li"
                ):
                    in_step_section = True
                    steps.append(next_text)
                    cursor += 1
                    continue
                if _is_non_ingredient_line(next_text) and next_tag != "li":
                    cursor += 1
                    continue
                ingredient_lines.append((None, next_text))
                cursor += 1
                continue

            if ingredient_lines and not in_ingredient_section:
                # Prose after an implicit ingredient run → steps.
                in_step_section = True
                steps.append(next_text)
                cursor += 1
                continue

            # Headnote / unrelated prose before ingredients — skip.
            cursor += 1

        if len(ingredient_lines) >= MIN_STRUCTURAL_INGREDIENTS:
            recipe = _finalize_structured_recipe(
                title=title,
                yield_text=yield_text,
                variation_body=[],
                ingredient_lines=ingredient_lines,
                steps=steps,
            )
            if recipe is not None and recipe.ingredients:
                recipes.append(recipe)
            index = cursor
        else:
            index += 1

    return recipes


def _finalize_profile_recipes(recipes: list[ExtractedRecipe]) -> list[ExtractedRecipe]:
    return expand_ambiguous_or_ingredients_sync(quality_assure_recipes(recipes))


def extract_structured_epub_recipes(path: Path) -> list[ExtractedRecipe] | None:
    """Parse recipes via exclusive cascade: Knopf → S&S → structural → None."""
    if path.suffix.lower() != ".epub":
        return None
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    documents = list(_iter_epub_documents(book))

    if _epub_has_knopf_markup(book):
        recipes: list[ExtractedRecipe] = []
        for item in documents:
            recipes.extend(_parse_structured_epub_document(item.get_content()))
        finalized = _finalize_profile_recipes(recipes)
        logger.info(
            "Knopf EPUB profile recovered %s recipes from %s",
            len(finalized),
            path.name,
        )
        return finalized

    if _epub_has_simon_schuster_markup(book):
        recipes = []
        for item in documents:
            recipes.extend(_parse_simon_schuster_epub_document(item.get_content()))
        finalized = _finalize_profile_recipes(recipes)
        logger.info(
            "Simon & Schuster EPUB profile recovered %s recipes from %s",
            len(finalized),
            path.name,
        )
        return finalized

    recipes = []
    for item in documents:
        recipes.extend(_parse_structural_epub_document(item.get_content()))
    finalized = _finalize_profile_recipes(recipes)
    if len(finalized) >= MIN_STRUCTURAL_BOOK_RECIPES:
        logger.info(
            "Structural EPUB profile recovered %s recipes from %s",
            len(finalized),
            path.name,
        )
        return finalized
    return None


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_sections(path: Path) -> list[str]:
    """Return reading-order text sections (pages for PDF, spine docs for EPUB, blocks for TXT)."""
    if path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(path) as document:
            return [
                f"[PAGE {index + 1}]\n{page.get_text('text')}".strip()
                for index, page in enumerate(document)
                if page.get_text("text").strip()
            ]
    if path.suffix.lower() == ".epub":
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        sections: list[str] = []
        for index, item in enumerate(_iter_epub_documents(book), start=1):
            text = _html_to_text(item.get_content())
            if len(text) < 40:
                continue
            sections.append(f"[CHAPTER {index}]\n{text}")
        return sections
    if path.suffix.lower() == ".txt":
        text = _read_text_file(path).strip()
        if not text:
            return []
        parts = [part.strip() for part in re.split(r"\f|\n\s*\n+", text) if part.strip()]
        if len(parts) <= 1:
            return [f"[SECTION 1]\n{text}"]
        return [f"[SECTION {index}]\n{part}" for index, part in enumerate(parts, start=1)]
    raise ValueError("Unsupported cookbook format")


def extract_document(path: Path) -> str:
    sections = extract_sections(path)
    return "\n\n".join(sections)


def _split_oversized(text: str) -> list[str]:
    """Split long text on paragraph boundaries before hard-cutting mid-recipe."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > MAX_CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            for index in range(0, len(paragraph), MAX_CHUNK_CHARS):
                chunks.append(paragraph[index : index + MAX_CHUNK_CHARS])
            continue
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= MAX_CHUNK_CHARS:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def chunk_document(text: str) -> list[str]:
    boundaries = list(
        re.finditer(
            r"(?im)^(?:recipe\s*[:#-]?\s*)?.{3,100}\n(?:.*\n){0,8}?\s*"
            r"(?:ingredients?|what you.?ll need|you will need)\s*:?\s*$",
            text,
        )
    )
    blocks: list[str]
    if len(boundaries) > 1:
        blocks = [
            text[match.start() : boundaries[index + 1].start()]
            if index + 1 < len(boundaries)
            else text[match.start() :]
            for index, match in enumerate(boundaries)
        ]
    else:
        # Prefer chapter/page markers from extract_sections over blank-line splits alone.
        marked = re.split(r"(?m)(?=^\[(?:PAGE|CHAPTER) \d+\])", text)
        blocks = [block for block in marked if block.strip()] or re.split(r"\n{3,}", text)

    chunks: list[str] = []
    current = ""
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if len(block) > MAX_CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized(block))
        elif len(current) + len(block) + 2 <= MAX_CHUNK_CHARS:
            current = f"{current}\n\n{block}".strip()
        else:
            chunks.append(current)
            current = block
    if current:
        chunks.append(current)
    return chunks or [text[:MAX_CHUNK_CHARS]]


def chunk_sections(sections: list[str]) -> list[str]:
    """Chunk from section list so EPUB chapters stay intact when possible."""
    if not sections:
        return []
    chunks: list[str] = []
    current = ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) > MAX_CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized(section))
        elif not current:
            current = section
        elif len(current) + len(section) + 2 <= MAX_CHUNK_CHARS:
            current = f"{current}\n\n{section}"
        else:
            chunks.append(current)
            current = section
    if current:
        chunks.append(current)
    return chunks


def demo_ingredient(raw: str) -> ExtractedIngredient:
    from app.services.staples import is_staple_name

    canonical, cleaned, quantity, unit = _parse_ingredient_parts(raw)
    return ExtractedIngredient(
        canonical_name=canonical,
        raw_text=cleaned,
        quantity=quantity,
        unit=unit,
        staple=is_staple_name(canonical),
    )


async def expand_ambiguous_or_ingredients(
    recipes: list[ExtractedRecipe],
) -> list[ExtractedRecipe]:
    """Expand ambiguous OR lines into alternate groups via LLM or heuristics."""
    ambiguous: list[ExtractedIngredient] = [
        ingredient
        for recipe in recipes
        for ingredient in recipe.ingredients
        if ingredient.ambiguous_or
    ]
    if not ambiguous:
        return recipes

    fallback_names = {
        " ".join(ingredient.raw_text.split()): ingredient.canonical_name for ingredient in ambiguous
    }
    mapping = await resolve_or_alternates(
        list(fallback_names),
        fallback_names,
    )
    return _apply_or_alternate_mapping(recipes, mapping)


def expand_ambiguous_or_ingredients_sync(
    recipes: list[ExtractedRecipe],
) -> list[ExtractedRecipe]:
    """Heuristic-only expansion for sync extraction paths and tests."""
    from app.services.canonicalize import heuristic_or_alternates

    ambiguous = [
        ingredient
        for recipe in recipes
        for ingredient in recipe.ingredients
        if ingredient.ambiguous_or
    ]
    if not ambiguous:
        return recipes
    mapping = {
        " ".join(ingredient.raw_text.split()): heuristic_or_alternates(
            ingredient.raw_text,
            ingredient.canonical_name,
        )
        for ingredient in ambiguous
    }
    return _apply_or_alternate_mapping(recipes, mapping)


def _apply_or_alternate_mapping(
    recipes: list[ExtractedRecipe],
    mapping: dict[str, list[str]],
) -> list[ExtractedRecipe]:
    expanded_recipes: list[ExtractedRecipe] = []
    for recipe in recipes:
        ingredients: list[ExtractedIngredient] = []
        for ingredient in recipe.ingredients:
            if not ingredient.ambiguous_or:
                ingredients.append(ingredient)
                continue
            key = " ".join(ingredient.raw_text.split())
            names = mapping.get(key) or [ingredient.canonical_name]
            group = ingredient.alternate_group or str(uuid.uuid4())
            if len(names) == 1:
                ingredients.append(
                    ingredient.model_copy(
                        update={
                            "canonical_name": names[0],
                            "alternate_group": None,
                            "ambiguous_or": False,
                        }
                    )
                )
                continue
            for name in names:
                ingredients.append(
                    ingredient.model_copy(
                        update={
                            "canonical_name": name,
                            "alternate_group": group,
                            "ambiguous_or": False,
                        }
                    )
                )
        expanded_recipes.append(recipe.model_copy(update={"ingredients": ingredients}))
    return expanded_recipes


def parse_ingredient_line(
    raw: str,
    *,
    section: str | None = None,
) -> list[ExtractedIngredient]:
    """Parse one source line into one or more ingredients (quantified OR → alternates)."""
    cleaned = re.sub(r"\s+", " ", raw).strip()
    segments = _split_quantified_or_segments(cleaned)
    if segments:
        group = str(uuid.uuid4())
        alternates: list[ExtractedIngredient] = []
        for segment in segments:
            ingredient = demo_ingredient(segment)
            alternates.append(
                ingredient.model_copy(
                    update={
                        "raw_text": cleaned,
                        "alternate_group": group,
                        "section": section,
                        "ambiguous_or": False,
                    }
                )
            )
        return alternates

    ingredient = demo_ingredient(cleaned)
    ambiguous = _has_ambiguous_or(cleaned)
    return [
        ingredient.model_copy(
            update={
                "section": section,
                "ambiguous_or": ambiguous,
                "alternate_group": str(uuid.uuid4()) if ambiguous else None,
            }
        )
    ]


def demo_parse(text: str) -> list[ExtractedRecipe]:
    lines = [line.strip() for line in text.splitlines()]
    ingredient_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(
            r"(?:ingredients?|what you.?ll need|you will need)\s*:?",
            line,
            re.I,
        )
    ]
    recipes: list[ExtractedRecipe] = []
    for recipe_index, ingredient_index in enumerate(ingredient_indexes):
        previous_boundary = ingredient_indexes[recipe_index - 1] if recipe_index else -1
        title_candidates = [
            line
            for line in lines[previous_boundary + 1 : ingredient_index]
            if line and not re.match(r"\[(?:PAGE|CHAPTER) \d+]", line)
        ]
        title = title_candidates[-1] if title_candidates else f"Recipe {recipe_index + 1}"
        end = (
            ingredient_indexes[recipe_index + 1]
            if recipe_index + 1 < len(ingredient_indexes)
            else len(lines)
        )
        direction_index = next(
            (
                index
                for index in range(ingredient_index + 1, end)
                if re.fullmatch(
                    r"(?:instructions?|directions?|method|preparation)\s*:?",
                    lines[index],
                    re.I,
                )
            ),
            end,
        )
        ingredient_lines = [
            line
            for line in lines[ingredient_index + 1 : direction_index]
            if line and not re.match(r"\[(?:PAGE|CHAPTER) \d+]", line)
        ]
        steps = [
            re.sub(r"^(?:[•*-]|\d+[.)])\s*", "", line)
            for line in lines[direction_index + 1 : end]
            if line and not re.match(r"\[(?:PAGE|CHAPTER) \d+]", line)
        ]
        page_match = next(
            (
                re.match(r"\[PAGE (\d+)]", line)
                for line in reversed(lines[:ingredient_index])
                if line.startswith("[PAGE ")
            ),
            None,
        )
        ingredients: list[ExtractedIngredient] = []
        for line in ingredient_lines:
            ingredients.extend(parse_ingredient_line(line))
        recipes.append(
            ExtractedRecipe(
                title=title[:255],
                source_page=int(page_match.group(1)) if page_match else None,
                ingredients=ingredients,
                steps=steps,
            )
        )
    return recipes


def parse_json_response(raw: str) -> ExtractionEnvelope:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    value = json.loads(raw)
    if isinstance(value, list):
        value = {"recipes": value}
    return ExtractionEnvelope.model_validate(value)


async def deepseek_parse(chunk: str) -> list[ExtractedRecipe]:
    if not settings.openai_api_key:
        return demo_parse(chunk)
    schema = json.dumps(ExtractionEnvelope.model_json_schema())
    prompt = (
        "Extract every complete recipe from the source. Return JSON only, exactly matching "
        f"this JSON Schema: {schema}\n\n"
        "Rules:\n"
        "- Include recipes embedded in narrative prose even without an explicit "
        "'Ingredients' heading when a dish name plus ingredients and/or steps are present.\n"
        "- Skip forwards, essays, indexes, and incomplete fragments.\n"
        "- canonical_name must be a short ingredient noun phrase (under 80 characters), "
        "never a full sentence or paragraph.\n\n"
        f"SOURCE:\n{chunk}"
    )
    system = (
        "You extract cookbook recipes faithfully. Never invent values. Use null when "
        "unknown. Canonical ingredient names are singular, lowercase, omit preparation, "
        "and must stay under 80 characters."
    )
    validation_error = ""
    for attempt in range(2):
        user = (
            prompt
            if not validation_error
            else f"{prompt}\n\nYour previous output was invalid: {validation_error}"
        )
        raw = await chat_completion(
            system=system,
            user=user,
            temperature=0,
            max_tokens=8192,
            response_format={"type": "json_object"},
            timeout=120.0,
        )
        try:
            return parse_json_response(raw).recipes
        except (ValidationError, json.JSONDecodeError) as exc:
            validation_error = str(exc)
            if attempt:
                raise
    return []


def _guess_image_extension(name: str, content: bytes) -> str:
    suffix = Path(name or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    if content.startswith(b"\x89PNG"):
        return ".png"
    if content[:3] == b"GIF":
        return ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def _save_cover_bytes(content: bytes, dest_dir: Path, cookbook_id: str, name: str) -> str:
    covers_dir = dest_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    extension = _guess_image_extension(name, content)
    relative = f"covers/{cookbook_id}{extension}"
    (dest_dir / relative).write_bytes(content)
    return relative


def extract_epub_cover(path: Path, dest_dir: Path, cookbook_id: str) -> str | None:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    cover_item = None

    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        cover_item = item
        break

    if cover_item is None:
        for _value, attrs in book.get_metadata("OPF", "cover"):
            cover_id = (attrs or {}).get("content")
            if cover_id:
                cover_item = book.get_item_with_id(cover_id)
                if cover_item is not None:
                    break

    if cover_item is None:
        for item in book.get_items():
            properties = {str(value).lower() for value in (getattr(item, "properties", None) or [])}
            if "cover-image" in properties:
                cover_item = item
                break

    if cover_item is None:
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            name = (item.get_name() or "").lower()
            item_id = (item.get_id() or "").lower()
            if "cover" in name or "cover" in item_id:
                cover_item = item
                break

    if cover_item is None:
        return None
    content = cover_item.get_content()
    if not content:
        return None
    return _save_cover_bytes(content, dest_dir, cookbook_id, cover_item.get_name() or "cover.jpg")


def extract_pdf_cover(path: Path, dest_dir: Path, cookbook_id: str) -> str | None:
    import fitz

    with fitz.open(path) as document:
        if document.page_count < 1:
            return None
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        return _save_cover_bytes(pixmap.tobytes("png"), dest_dir, cookbook_id, "cover.png")


def extract_cover(path: Path, dest_dir: Path, cookbook_id: str) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return extract_epub_cover(path, dest_dir, cookbook_id)
    if suffix == ".pdf":
        return extract_pdf_cover(path, dest_dir, cookbook_id)
    return None


def cover_media_type(cover_path: str) -> str:
    guessed, _ = mimetypes.guess_type(cover_path)
    return guessed or "application/octet-stream"


async def set_progress(cookbook_id: str, progress: int) -> None:
    async with SessionLocal() as db:
        cookbook = await db.get(Cookbook, uuid.UUID(cookbook_id))
        if cookbook:
            cookbook.progress = progress
            await db.commit()


async def _store_cover_path(cookbook_id: str, cover_path: str | None) -> None:
    if not cover_path:
        return
    async with SessionLocal() as db:
        cookbook = await db.get(Cookbook, uuid.UUID(cookbook_id))
        if cookbook:
            cookbook.cover_path = cover_path
            await db.commit()


async def process_cookbook(cookbook_id: str) -> None:
    async with SessionLocal() as db:
        cookbook = await db.get(Cookbook, uuid.UUID(cookbook_id))
        if cookbook is None:
            return
        cookbook.status = UploadStatus.processing
        cookbook.progress = 5
        cookbook.error = None
        await db.commit()
        path = Path(cookbook.storage_path)

    try:
        try:
            cover_path = await asyncio.to_thread(
                extract_cover, path, settings.upload_dir, cookbook_id
            )
            await _store_cover_path(cookbook_id, cover_path)
        except Exception as exc:
            # Cover failure must not abort recipe ingestion.
            logger.warning("Cover extraction failed for %s: %s", cookbook_id, exc)

        await set_progress(cookbook_id, 15)
        structured = await asyncio.to_thread(extract_structured_epub_recipes, path)
        extracted: list[ExtractedRecipe] = []
        if structured:
            extracted = structured
            await set_progress(cookbook_id, 70)
            logger.info(
                "Structured EPUB extraction recovered %s recipes for %s",
                len(extracted),
                cookbook_id,
            )
        else:
            sections = await asyncio.to_thread(extract_sections, path)
            if not any(section.strip() for section in sections):
                raise ValueError("No readable text was found in the cookbook")
            chunks = chunk_sections(sections) or chunk_document("\n\n".join(sections))
            for index, chunk in enumerate(chunks):
                try:
                    extracted.extend(await deepseek_parse(chunk))
                except Exception as exc:
                    logger.warning(
                        "Recipe extraction failed for cookbook %s chunk %s/%s: %s",
                        cookbook_id,
                        index + 1,
                        len(chunks),
                        exc,
                    )
                await set_progress(cookbook_id, 15 + int(55 * (index + 1) / len(chunks)))
        extracted = quality_assure_recipes(extracted)
        extracted = await expand_ambiguous_or_ingredients(extracted)
        if not extracted:
            raise ValueError("No recipes could be identified")

        async with SessionLocal() as db:
            async with db.begin():
                cookbook = await db.get(Cookbook, uuid.UUID(cookbook_id))
                if cookbook is None:
                    return
                await db.execute(delete(Recipe).where(Recipe.cookbook_id == cookbook.id))
                if not cookbook.content_sha256:
                    cookbook.content_sha256 = sha256_file(path)
                catalog_cookbook = await find_or_create_catalog_cookbook(
                    db,
                    content_sha256=cookbook.content_sha256,
                    title=cookbook.title,
                )
                ingredient_cache: dict[str, Ingredient] = {}
                raw_hints: dict[str, str] = {}
                for extracted_recipe in extracted:
                    total = extracted_recipe.total_minutes
                    if total is None and (
                        extracted_recipe.prep_minutes is not None
                        or extracted_recipe.cook_minutes is not None
                    ):
                        total = (extracted_recipe.prep_minutes or 0) + (
                            extracted_recipe.cook_minutes or 0
                        )
                    ingredient_names = [
                        item.canonical_name for item in extracted_recipe.ingredients
                    ]
                    ingredient_categories = [item.category for item in extracted_recipe.ingredients]
                    tagging = await assign_recipe_tags(
                        title=extracted_recipe.title,
                        cuisine=extracted_recipe.cuisine,
                        tags=list(extracted_recipe.tags or []),
                        ingredient_names=ingredient_names,
                        ingredient_categories=ingredient_categories,
                        steps=list(extracted_recipe.steps or []),
                    )
                    fingerprint = recipe_fingerprint(
                        title=extracted_recipe.title,
                        ingredient_raw_texts=[
                            item.raw_text for item in extracted_recipe.ingredients
                        ],
                        steps=list(extracted_recipe.steps or []),
                    )
                    catalog_recipe_id = None
                    if fingerprint is not None:
                        catalog_recipe = await upsert_catalog_recipe(
                            db,
                            catalog_cookbook=catalog_cookbook,
                            fingerprint=fingerprint,
                            title=extracted_recipe.title,
                        )
                        catalog_recipe_id = catalog_recipe.id
                    recipe = Recipe(
                        cookbook_id=cookbook.id,
                        catalog_recipe_id=catalog_recipe_id,
                        title=extracted_recipe.title,
                        servings=extracted_recipe.servings,
                        prep_minutes=extracted_recipe.prep_minutes,
                        cook_minutes=extracted_recipe.cook_minutes,
                        total_minutes=total,
                        calories=extracted_recipe.calories,
                        protein_grams=extracted_recipe.protein_grams,
                        carbs_grams=extracted_recipe.carbs_grams,
                        fat_grams=extracted_recipe.fat_grams,
                        cuisine=tagging.cuisine or extracted_recipe.cuisine,
                        rating=extracted_recipe.rating,
                        rating_count=extracted_recipe.rating_count,
                        tags=tagging.tags or list(extracted_recipe.tags or []),
                        tag_source=tagging.tag_source,
                        steps=extracted_recipe.steps,
                        source_page=extracted_recipe.source_page,
                        parse_warnings=extracted_recipe.parse_warnings,
                    )
                    apply_printed_nutrition_metadata(recipe)
                    db.add(recipe)
                    await db.flush()
                    group_ids: dict[str, uuid.UUID] = {}
                    for position, extracted_ingredient in enumerate(extracted_recipe.ingredients):
                        name = extracted_ingredient.canonical_name
                        ingredient = ingredient_cache.get(name)
                        if ingredient is None:
                            ingredient = await resolve_ingredient(db, extracted_ingredient)
                            ingredient_cache[name] = ingredient
                        raw_hints.setdefault(name, extracted_ingredient.raw_text)
                        alternate_group_id = None
                        if extracted_ingredient.alternate_group:
                            alternate_group_id = group_ids.setdefault(
                                extracted_ingredient.alternate_group,
                                uuid.uuid4(),
                            )
                        db.add(
                            RecipeIngredient(
                                recipe_id=recipe.id,
                                ingredient_id=ingredient.id,
                                quantity=extracted_ingredient.quantity,
                                unit=extracted_ingredient.unit,
                                raw_text=extracted_ingredient.raw_text,
                                position=position,
                                alternate_group_id=alternate_group_id,
                                section=extracted_ingredient.section,
                            )
                        )
                cookbook.status = UploadStatus.processing
                cookbook.progress = 95
                cookbook.error = None
        try:
            async with SessionLocal() as db:
                result = await db.scalars(
                    select(Ingredient)
                    .join(
                        RecipeIngredient,
                        RecipeIngredient.ingredient_id == Ingredient.id,
                    )
                    .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
                    .where(
                        Recipe.cookbook_id == uuid.UUID(cookbook_id),
                        Ingredient.canonical_id.is_(None),
                    )
                )
                ingredients = list(result.unique())
                await canonicalize_ingredients(
                    db,
                    ingredients,
                    timeout=120.0,
                    raw_hints=raw_hints,
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Ingredient canonicalization failed for cookbook %s",
                cookbook_id,
            )

        try:
            from app.services.recipe_images import assign_images_for_cookbook

            await assign_images_for_cookbook(cookbook_id, path)
        except Exception as exc:
            # Imagery failure must not abort an otherwise successful ingest.
            logger.warning("Recipe image assignment failed for %s: %s", cookbook_id, exc)

        try:
            from app.services.nutrition import estimate_nutrition_for_cookbook

            await estimate_nutrition_for_cookbook(cookbook_id)
        except Exception as exc:
            logger.warning("Nutrition estimation failed for %s: %s", cookbook_id, exc)

        async with SessionLocal() as db:
            cookbook = await db.get(Cookbook, uuid.UUID(cookbook_id))
            if cookbook:
                cookbook.status = UploadStatus.completed
                cookbook.progress = 100
                cookbook.error = None
                await db.commit()
    except Exception as exc:
        async with SessionLocal() as db:
            cookbook = await db.get(Cookbook, uuid.UUID(cookbook_id))
            if cookbook:
                cookbook.status = UploadStatus.failed
                cookbook.error = str(exc)[:4000]
                await db.commit()
        logger.exception("Cookbook ingestion failed for %s", cookbook_id)
