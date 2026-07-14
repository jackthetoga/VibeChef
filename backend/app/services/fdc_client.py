"""USDA FoodData Central client with local seed fallback."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.core.config import settings
from app.services.fdc_seed import FdcSeedEntry, get_fdc_seed, normalize_food_name

logger = logging.getLogger(__name__)

# FoodData Central nutrient ids (Foundation / SR Legacy per 100g).
NUTRIENT_ENERGY_KCAL = 1008
NUTRIENT_PROTEIN = 1003
NUTRIENT_CARBS = 1005
NUTRIENT_FAT = 1004

PREFERRED_DATA_TYPES = ("Foundation", "SR Legacy")


@dataclass(frozen=True)
class FoodMacros:
    fdc_id: int | None
    description: str | None
    calories_per_100g: Decimal
    protein_per_100g: Decimal
    carbs_per_100g: Decimal
    fat_per_100g: Decimal
    source: str  # "seed" | "fdc" | "cache"


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _macros_from_nutrients(food: dict) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    amounts: dict[int, Decimal] = {}
    for entry in food.get("foodNutrients") or []:
        nutrient = entry.get("nutrient") or {}
        nutrient_id = nutrient.get("id") or entry.get("nutrientId")
        amount = entry.get("amount")
        if nutrient_id is None or amount is None:
            continue
        parsed = _decimal(amount)
        if parsed is None:
            continue
        unit = (nutrient.get("unitName") or entry.get("unitName") or "").lower()
        if int(nutrient_id) == NUTRIENT_ENERGY_KCAL and unit and unit not in {"kcal", "kcalm"}:
            continue
        amounts[int(nutrient_id)] = parsed

    if not amounts:
        for entry in food.get("foodNutrients") or []:
            nutrient_id = entry.get("nutrientId")
            value = entry.get("value")
            if nutrient_id is None or value is None:
                continue
            parsed = _decimal(value)
            if parsed is None:
                continue
            amounts[int(nutrient_id)] = parsed

    calories = amounts.get(NUTRIENT_ENERGY_KCAL)
    protein = amounts.get(NUTRIENT_PROTEIN)
    carbs = amounts.get(NUTRIENT_CARBS)
    fat = amounts.get(NUTRIENT_FAT)
    if calories is None or protein is None or carbs is None or fat is None:
        return None
    return calories, protein, carbs, fat


def _seed_to_macros(seed: FdcSeedEntry) -> FoodMacros:
    return FoodMacros(
        fdc_id=seed.fdc_id,
        description=seed.description,
        calories_per_100g=seed.calories,
        protein_per_100g=seed.protein,
        carbs_per_100g=seed.carbs,
        fat_per_100g=seed.fat,
        source="seed",
    )


class FdcClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.usda_fdc_api_key
        self.base_url = (base_url or settings.usda_fdc_base_url).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._memory: dict[str, FoodMacros] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def resolve_macros(self, name: str) -> FoodMacros | None:
        key = normalize_food_name(name)
        if key in self._memory:
            return self._memory[key]

        seed = get_fdc_seed(name)
        if seed is not None:
            macros = _seed_to_macros(seed)
            self._memory[key] = macros
            return macros

        if not self.enabled:
            return None

        try:
            macros = await self._search_and_fetch(name)
        except Exception:
            logger.warning("FDC lookup failed for %r", name, exc_info=True)
            return None
        if macros is not None:
            self._memory[key] = macros
        return macros

    async def _request(self, client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            response = await client.get(url, params=params)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 2.0 * (attempt + 1)
            except ValueError:
                delay = 2.0 * (attempt + 1)
            logger.warning(
                "USDA FDC rate limited (429); sleeping %.1fs (attempt %s/%s)",
                delay,
                attempt + 1,
                self.max_retries,
            )
            await asyncio.sleep(delay)
            last_error = httpx.HTTPStatusError(
                "Too Many Requests",
                request=response.request,
                response=response,
            )
        if last_error:
            raise last_error
        raise RuntimeError("FDC request failed without response")

    async def _search_and_fetch(self, name: str) -> FoodMacros | None:
        assert self.api_key
        params = {
            "api_key": self.api_key,
            "query": name,
            "pageSize": 5,
            "dataType": ",".join(PREFERRED_DATA_TYPES),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            search = await self._request(client, f"{self.base_url}/foods/search", params)
            foods = (search.json() or {}).get("foods") or []
            if not foods:
                params.pop("dataType", None)
                search = await self._request(client, f"{self.base_url}/foods/search", params)
                foods = (search.json() or {}).get("foods") or []
            if not foods:
                return None

            ranked = sorted(
                foods,
                key=lambda food: (
                    0 if food.get("dataType") in PREFERRED_DATA_TYPES else 1,
                    food.get("description") or "",
                ),
            )
            chosen = ranked[0]
            fdc_id = chosen.get("fdcId")
            if fdc_id is None:
                return None

            detail = await self._request(
                client,
                f"{self.base_url}/food/{fdc_id}",
                {"api_key": self.api_key},
            )
            food = detail.json() or {}
            parsed = _macros_from_nutrients(food)
            if parsed is None:
                parsed = _macros_from_nutrients(chosen)
            if parsed is None:
                return None
            calories, protein, carbs, fat = parsed
            return FoodMacros(
                fdc_id=int(fdc_id),
                description=food.get("description") or chosen.get("description"),
                calories_per_100g=calories,
                protein_per_100g=protein,
                carbs_per_100g=carbs,
                fat_per_100g=fat,
                source="fdc",
            )
