"""Content-addressed catalog identity for shared reviews."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCookbook, CatalogRecipe, Review


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def recipe_fingerprint(
    *,
    title: str,
    ingredient_raw_texts: Sequence[str],
    steps: Sequence[str],
) -> str | None:
    """Return SHA-256 hex of normalized recipe content, or None if too weak to catalog."""
    normalized_title = _normalize_text(title)
    ingredients = tuple(_normalize_text(raw) for raw in ingredient_raw_texts if raw.strip())
    normalized_steps = tuple(_normalize_text(step) for step in steps if step.strip())
    if not normalized_title or not ingredients or not normalized_steps:
        return None
    payload = "\n".join(
        [
            normalized_title,
            *[f"i:{item}" for item in ingredients],
            *[f"s:{item}" for item in normalized_steps],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def find_or_create_catalog_cookbook(
    db: AsyncSession,
    *,
    content_sha256: str,
    title: str | None = None,
) -> CatalogCookbook:
    existing = await db.scalar(
        select(CatalogCookbook).where(CatalogCookbook.content_sha256 == content_sha256)
    )
    if existing is not None:
        if title and not existing.title:
            existing.title = title[:255]
        return existing

    candidate = CatalogCookbook(content_sha256=content_sha256, title=(title or None))
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
        return candidate
    except IntegrityError:
        existing = await db.scalar(
            select(CatalogCookbook).where(CatalogCookbook.content_sha256 == content_sha256)
        )
        if existing is None:
            raise RuntimeError(
                f"Catalog cookbook conflicted but {content_sha256!r} was not found"
            )
        return existing


async def upsert_catalog_recipe(
    db: AsyncSession,
    *,
    catalog_cookbook: CatalogCookbook,
    fingerprint: str,
    title: str,
) -> CatalogRecipe:
    existing = await db.scalar(
        select(CatalogRecipe).where(
            CatalogRecipe.catalog_cookbook_id == catalog_cookbook.id,
            CatalogRecipe.recipe_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        if title and existing.title != title:
            existing.title = title[:255]
        return existing

    candidate = CatalogRecipe(
        catalog_cookbook_id=catalog_cookbook.id,
        recipe_fingerprint=fingerprint,
        title=title[:255],
        user_rating_count=0,
    )
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
        return candidate
    except IntegrityError:
        existing = await db.scalar(
            select(CatalogRecipe).where(
                CatalogRecipe.catalog_cookbook_id == catalog_cookbook.id,
                CatalogRecipe.recipe_fingerprint == fingerprint,
            )
        )
        if existing is None:
            raise RuntimeError(
                f"Catalog recipe conflicted but fingerprint {fingerprint!r} was not found"
            )
        return existing


async def refresh_catalog_recipe_aggregates(
    db: AsyncSession,
    catalog_recipe_id,
) -> CatalogRecipe | None:
    catalog_recipe = await db.get(CatalogRecipe, catalog_recipe_id)
    if catalog_recipe is None:
        return None
    row = (
        await db.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                Review.catalog_recipe_id == catalog_recipe_id
            )
        )
    ).one()
    avg_value, count = row
    catalog_recipe.user_rating_count = int(count or 0)
    catalog_recipe.user_rating_avg = (
        Decimal(str(round(float(avg_value), 2))) if avg_value is not None else None
    )
    return catalog_recipe
