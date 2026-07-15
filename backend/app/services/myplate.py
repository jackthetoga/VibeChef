"""Fetch and map USDA MyPlate Kitchen recipes (public domain via myplate.food)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.services.ingestion import (
    ExtractedIngredient,
    ExtractedRecipe,
    expand_ambiguous_or_ingredients_sync,
    parse_ingredient_line,
    parse_servings,
)

logger = logging.getLogger(__name__)

MYPLATE_API_BASE = "https://myplate.food/api/v1"
DEFAULT_PAGE_SIZE = 100
COOKBOOK_TITLE = "USDA MyPlate Kitchen"
COOKBOOK_FILENAME = "myplate-kitchen-seed.json"
DEFAULT_CACHE_DIR = settings.upload_dir / "seeds" / "myplate-cache"


def _nutrition_amount(nutrition: list[dict[str, Any]], key: str) -> Decimal | None:
    for row in nutrition:
        if row.get("key") == key and row.get("amount") is not None:
            try:
                return Decimal(str(row["amount"]))
            except Exception:
                return None
    return None


def _split_directions(text: str) -> list[str]:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return []
    numbered = re.split(r"(?=\b\d+\.\s+)", cleaned)
    parts = [part.strip(" .") for part in numbered if part.strip(" .")]
    if len(parts) >= 2 and all(re.match(r"^\d+\.", p) for p in parts):
        return [re.sub(r"^\d+\.\s*", "", p).strip() for p in parts if p.strip()]

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", cleaned)
    steps: list[str] = []
    for sentence in sentences:
        piece = sentence.strip()
        if not piece:
            continue
        if steps and len(piece) < 28 and not piece[0].isupper():
            steps[-1] = f"{steps[-1]} {piece}".strip()
        else:
            steps.append(piece)
    return steps or [cleaned]


def _ingredient_raw(item: dict[str, Any]) -> str:
    text = " ".join(str(item.get("text") or "").split()).strip()
    note = " ".join(str(item.get("note") or "").split()).strip()
    if note and note.lower() not in text.lower():
        return f"{text} ({note})" if text else note
    return text


def detail_to_extracted(detail: dict[str, Any]) -> ExtractedRecipe:
    """Map a MyPlate recipe detail payload into ExtractedRecipe."""
    title = " ".join(str(detail.get("name") or detail.get("slug") or "Untitled").split())
    yield_text = str(detail.get("yield") or "")
    servings = parse_servings(yield_text)

    ingredients: list[ExtractedIngredient] = []
    for item in detail.get("ingredients") or []:
        raw = _ingredient_raw(item)
        if not raw:
            continue
        ingredients.extend(parse_ingredient_line(raw))

    category = str(detail.get("category") or "").strip()
    food_groups = detail.get("food_groups") or []
    group_keys: list[str] = []
    for group in food_groups:
        if isinstance(group, dict):
            key = group.get("key") or group.get("label")
        else:
            key = group
        if key:
            normalized = str(key).strip().lower().replace("_", "-").replace(" ", "-")
            aliases = {
                "vegetable": "vegetables",
                "fruit": "fruits",
                "grain": "grains",
                "protein-food": "protein-foods",
                "proteinfoods": "protein-foods",
            }
            group_keys.append(aliases.get(normalized, normalized))

    tags: list[str] = ["myplate", "public-domain"]
    if category:
        tags.append(category.lower())
    tags.extend(key for key in group_keys if key)

    slug = str(detail.get("slug") or "").strip()
    if slug:
        tags.append(f"myplate:{slug}")

    rating = detail.get("rating") or {}
    rating_value = rating.get("value")
    rating_count = rating.get("count")
    parse_warnings: list[str] = []
    source = detail.get("source")
    if source:
        parse_warnings.append(str(source)[:500])
    if rating_value is not None:
        parse_warnings.append(
            f"MyPlate rating {rating_value}"
            + (f" ({rating_count} votes)" if rating_count is not None else "")
        )

    nutrition = detail.get("nutrition") or []
    stored_rating: Decimal | None = None
    stored_count: int | None = None
    try:
        if rating_value is not None:
            stored_rating = Decimal(str(rating_value))
        if rating_count is not None:
            stored_count = int(rating_count)
    except (TypeError, ValueError, ArithmeticError):
        stored_rating = None
        stored_count = None

    recipe = ExtractedRecipe(
        title=title,
        servings=servings,
        calories=_nutrition_amount(nutrition, "total_calories"),
        protein_grams=_nutrition_amount(nutrition, "protein"),
        carbs_grams=_nutrition_amount(nutrition, "carbohydrates"),
        fat_grams=_nutrition_amount(nutrition, "total_fat"),
        cuisine=None,
        rating=stored_rating,
        rating_count=stored_count,
        tags=tags,
        steps=_split_directions(str(detail.get("directions") or "")),
        ingredients=ingredients,
        parse_warnings=parse_warnings,
    )
    return expand_ambiguous_or_ingredients_sync([recipe])[0]


def _rating_value(payload: dict[str, Any]) -> float | None:
    rating = (payload.get("rating") or {}).get("value")
    try:
        return float(rating) if rating is not None else None
    except (TypeError, ValueError):
        return None


class MyPlateClient:
    def __init__(
        self,
        *,
        base_url: str = MYPLATE_API_BASE,
        timeout: float = 30.0,
        request_delay_seconds: float = 0.55,
        max_retries: int = 10,
        cache_dir: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.request_delay_seconds = request_delay_seconds
        self._min_delay = request_delay_seconds
        self._max_delay = 3.0
        self.max_retries = max_retries
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self._client: httpx.AsyncClient | None = None
        self._success_streak = 0

    async def __aenter__(self) -> "MyPlateClient":
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "RecipeFinderMyPlateSeed/1.0"},
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("MyPlateClient must be used as an async context manager")
        return self._client

    def _cache_path(self, slug: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug).strip("._") or "recipe"
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, slug: str) -> dict[str, Any] | None:
        path = self._cache_path(slug)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, slug: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(slug)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _note_success(self) -> None:
        self._success_streak += 1
        if self._success_streak >= 20 and self.request_delay_seconds > self._min_delay:
            self.request_delay_seconds = max(
                self._min_delay, self.request_delay_seconds * 0.9
            )
            self._success_streak = 0

    def _note_rate_limit(self) -> None:
        self._success_streak = 0
        self.request_delay_seconds = min(
            self._max_delay, max(self.request_delay_seconds * 1.5, 1.0)
        )
        logger.info("Raised MyPlate request delay to %.2fs", self.request_delay_seconds)

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        client = self._ensure_client()
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            if self.request_delay_seconds:
                await asyncio.sleep(self.request_delay_seconds)
            try:
                response = await client.get(url, params=params)
                if response.status_code == 429:
                    self._note_rate_limit()
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else min(2**attempt, 45)
                    except ValueError:
                        wait = min(2**attempt, 45)
                    wait = min(max(wait, 5.0), 90.0)
                    logger.warning(
                        "MyPlate rate limited on %s; sleeping %.1fs (attempt %s/%s)",
                        path,
                        wait,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                self._note_success()
                return response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                wait = min(2**attempt, 20)
                logger.warning(
                    "MyPlate request failed for %s: %s; retry in %.1fs",
                    path,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"MyPlate request failed for {path}: {last_error}")

    async def list_recipes(
        self,
        *,
        min_rating: float | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if min_rating is not None:
            params["min_rating"] = min_rating
        return await self._get_json("/recipes", params=params)

    async def get_recipe(self, slug: str) -> dict[str, Any]:
        cached = self._read_cache(slug)
        if cached is not None:
            return cached
        detail = await self._get_json(f"/recipes/{slug}")
        self._write_cache(slug, detail)
        return detail

    async def list_all_cards(
        self,
        *,
        min_rating: float = 3.5,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        offset = 0
        cards: list[dict[str, Any]] = []
        total: int | None = None
        while True:
            payload = await self.list_recipes(
                min_rating=min_rating,
                limit=page_size,
                offset=offset,
            )
            results = payload.get("results") or []
            if total is None:
                total = int(payload.get("total") or 0)
                logger.info(
                    "MyPlate list: total=%s min_rating=%s",
                    total,
                    min_rating,
                )
            if not results:
                break
            cards.extend(results)
            offset += len(results)
            if total is not None and offset >= total:
                break
        return cards

    async def fetch_recipes_above_rating(
        self,
        *,
        min_exclusive: float = 3.5,
        page_size: int = DEFAULT_PAGE_SIZE,
        limit: int | None = None,
    ) -> list[tuple[dict[str, Any], ExtractedRecipe]]:
        """Fetch details for recipes with rating strictly above ``min_exclusive``."""
        cards = await self.list_all_cards(min_rating=min_exclusive, page_size=page_size)
        qualified = [
            card
            for card in cards
            if (value := _rating_value(card)) is not None and value > min_exclusive
        ]
        if limit is not None:
            qualified = qualified[:limit]
        logger.info(
            "MyPlate cards above %s: %s (from %s listed)",
            min_exclusive,
            len(qualified),
            len(cards),
        )

        selected: list[tuple[dict[str, Any], ExtractedRecipe]] = []
        cache_hits = 0
        for index, card in enumerate(qualified, start=1):
            slug = card.get("slug")
            if not slug:
                continue
            slug_text = str(slug)
            was_cached = self._read_cache(slug_text) is not None
            detail = await self.get_recipe(slug_text)
            if was_cached:
                cache_hits += 1
            if not detail.get("category") and card.get("category"):
                detail = {**detail, "category": card["category"]}
            selected.append((detail, detail_to_extracted(detail)))
            if index % 50 == 0 or index == len(qualified):
                logger.info(
                    "Fetched MyPlate details: %s/%s (cache_hits=%s)",
                    index,
                    len(qualified),
                    cache_hits,
                )
        return selected

    async def download_image(self, url: str) -> bytes | None:
        if not url:
            return None
        client = self._ensure_client()
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            if self.request_delay_seconds:
                await asyncio.sleep(min(self.request_delay_seconds, 1.0))
            try:
                response = await client.get(url)
                if response.status_code == 429:
                    self._note_rate_limit()
                    wait = min(2**attempt, 30)
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                content = response.content
                if len(content) < 500:
                    return None
                return content
            except httpx.HTTPError as exc:
                last_error = exc
                await asyncio.sleep(min(2**attempt, 20))
        logger.warning("MyPlate image download failed for %s: %s", url, last_error)
        return None
