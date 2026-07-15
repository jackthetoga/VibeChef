"""Seed USDA MyPlate Kitchen recipes into a user's cookbook library."""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import uuid
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Cookbook,
    ImageSource,
    Recipe,
    RecipeIngredient,
    UploadStatus,
    User,
)
from app.services.ingestion import resolve_ingredient
from app.services.myplate import (
    COOKBOOK_FILENAME,
    COOKBOOK_TITLE,
    MyPlateClient,
)
from app.services.nutrition import apply_printed_nutrition_metadata
from app.services.recipe_images import _save_extracted_image, corpus_assignment

logger = logging.getLogger(__name__)

DEFAULT_OWNER_EMAIL = "zizizink@gmail.com"
IMAGE_KEY_MAX_LEN = 64
MYPLATE_CDN = "https://storage.googleapis.com/peppermint-cdn/myplate.food-recipe-images"


def _image_key(slug: str, recipe_id: uuid.UUID) -> str:
    raw = f"myplate:{slug}" if slug else f"myplate:{recipe_id}"
    return raw[:IMAGE_KEY_MAX_LEN]


def _slug_from_tags(tags: list[str] | None) -> str | None:
    for tag in tags or []:
        if tag.startswith("myplate:") and len(tag) > len("myplate:"):
            return tag.split(":", 1)[1]
    return None


async def _resolve_owner(email: str, *, create_if_missing: bool) -> User:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            return user
        if not create_if_missing:
            raise RuntimeError(
                f"No user with email {email!r}. Pass --create-user or a different --email."
            )
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(24)),
            display_name="MyPlate Seed",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("Created seed owner user %s (%s)", user.email, user.id)
        return user


async def _get_or_create_cookbook(user_id: uuid.UUID, *, force: bool) -> Cookbook:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    marker = settings.upload_dir / "seeds" / "myplate-kitchen.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if not marker.is_file():
        marker.write_text(
            '{"source":"https://myplate.food/api","license":"public-domain"}\n',
            encoding="utf-8",
        )

    async with SessionLocal() as db:
        cookbook = await db.scalar(
            select(Cookbook).where(
                Cookbook.user_id == user_id,
                Cookbook.title == COOKBOOK_TITLE,
            )
        )
        if cookbook is not None:
            if not force:
                raise RuntimeError(
                    f"Cookbook {COOKBOOK_TITLE!r} already exists "
                    f"({cookbook.id}). Re-run with --force to replace."
                )
            await db.execute(delete(Recipe).where(Recipe.cookbook_id == cookbook.id))
            cookbook.status = UploadStatus.processing
            cookbook.progress = 5
            cookbook.error = None
            cookbook.original_filename = COOKBOOK_FILENAME
            cookbook.content_type = "application/json"
            cookbook.storage_path = str(marker)
            await db.commit()
            await db.refresh(cookbook)
            logger.info("Cleared existing MyPlate cookbook %s", cookbook.id)
            return cookbook

        cookbook = Cookbook(
            user_id=user_id,
            title=COOKBOOK_TITLE,
            original_filename=COOKBOOK_FILENAME,
            content_type="application/json",
            storage_path=str(marker),
            status=UploadStatus.processing,
            progress=5,
        )
        db.add(cookbook)
        await db.commit()
        await db.refresh(cookbook)
        logger.info("Created MyPlate cookbook %s", cookbook.id)
        return cookbook


async def seed_myplate(
    *,
    email: str,
    min_rating_exclusive: float,
    force: bool,
    create_user: bool,
    download_images: bool,
    limit: int | None,
) -> dict[str, int]:
    owner = await _resolve_owner(email, create_if_missing=create_user)
    cookbook = await _get_or_create_cookbook(owner.id, force=force)

    async with MyPlateClient() as client:
        pairs = await client.fetch_recipes_above_rating(
            min_exclusive=min_rating_exclusive,
            limit=limit,
        )

        if not pairs:
            async with SessionLocal() as db:
                row = await db.get(Cookbook, cookbook.id)
                if row:
                    row.status = UploadStatus.failed
                    row.error = "No MyPlate recipes matched the rating filter"
                    row.progress = 100
                    await db.commit()
            raise RuntimeError("No MyPlate recipes matched the rating filter")

        imported = 0
        imaged = 0
        pending_images: list[tuple[uuid.UUID, str, str]] = []
        ingredient_cache: dict[str, object] = {}

        async with SessionLocal() as db:
            async with db.begin():
                cookbook_row = await db.get(Cookbook, cookbook.id)
                if cookbook_row is None:
                    raise RuntimeError("Cookbook disappeared during import")

                for detail, extracted in pairs:
                    total = extracted.total_minutes
                    if total is None and (
                        extracted.prep_minutes is not None
                        or extracted.cook_minutes is not None
                    ):
                        total = (extracted.prep_minutes or 0) + (
                            extracted.cook_minutes or 0
                        )

                    recipe = Recipe(
                        cookbook_id=cookbook_row.id,
                        title=extracted.title,
                        servings=extracted.servings,
                        prep_minutes=extracted.prep_minutes,
                        cook_minutes=extracted.cook_minutes,
                        total_minutes=total,
                        calories=extracted.calories,
                        protein_grams=extracted.protein_grams,
                        carbs_grams=extracted.carbs_grams,
                        fat_grams=extracted.fat_grams,
                        cuisine=extracted.cuisine,
                        rating=extracted.rating,
                        rating_count=extracted.rating_count,
                        tags=extracted.tags,
                        tag_source="myplate",
                        steps=extracted.steps,
                        source_page=extracted.source_page,
                        parse_warnings=extracted.parse_warnings,
                    )
                    apply_printed_nutrition_metadata(recipe)

                    fallback = corpus_assignment(
                        recipe.title, recipe.cuisine, recipe.tags
                    )
                    if fallback is not None:
                        recipe.image_path = fallback.path
                        recipe.image_source = fallback.source
                        recipe.image_key = fallback.key

                    db.add(recipe)
                    await db.flush()

                    for position, extracted_ingredient in enumerate(
                        extracted.ingredients
                    ):
                        name = extracted_ingredient.canonical_name
                        ingredient = ingredient_cache.get(name)
                        if ingredient is None:
                            ingredient = await resolve_ingredient(
                                db, extracted_ingredient
                            )
                            ingredient_cache[name] = ingredient
                        alternate_group_id = None
                        if extracted_ingredient.alternate_group:
                            try:
                                alternate_group_id = uuid.UUID(
                                    extracted_ingredient.alternate_group
                                )
                            except ValueError:
                                alternate_group_id = uuid.uuid4()
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

                    image_url = str(detail.get("image_url") or "")
                    slug = str(detail.get("slug") or "")
                    if download_images and image_url:
                        pending_images.append((recipe.id, image_url, slug))

                    imported += 1
                    if imported % 50 == 0:
                        cookbook_row.progress = min(
                            90, 10 + int(80 * imported / len(pairs))
                        )
                        logger.info(
                            "Persisted %s/%s MyPlate recipes", imported, len(pairs)
                        )

                cookbook_row.status = UploadStatus.processing
                cookbook_row.progress = 92
                cookbook_row.error = None

        if pending_images:
            logger.info("Downloading %s MyPlate images", len(pending_images))
            for index, (recipe_id, image_url, slug) in enumerate(
                pending_images, start=1
            ):
                content = await client.download_image(image_url)
                if not content:
                    continue
                relative = _save_extracted_image(
                    content,
                    settings.upload_dir,
                    str(cookbook.id),
                    str(recipe_id),
                    Path(image_url).name or "recipe.jpg",
                )
                try:
                    async with SessionLocal() as db:
                        recipe = await db.get(Recipe, recipe_id)
                        if recipe is None:
                            continue
                        recipe.image_path = relative
                        recipe.image_source = ImageSource.extracted
                        recipe.image_key = _image_key(slug, recipe_id)
                        await db.commit()
                    imaged += 1
                except Exception:
                    logger.exception(
                        "Failed to save MyPlate image for recipe %s (%s)",
                        recipe_id,
                        slug,
                    )
                if index % 50 == 0:
                    logger.info(
                        "Downloaded images %s/%s", index, len(pending_images)
                    )

    async with SessionLocal() as db:
        cookbook_row = await db.get(Cookbook, cookbook.id)
        if cookbook_row:
            cookbook_row.status = UploadStatus.completed
            cookbook_row.progress = 100
            cookbook_row.error = None
            await db.commit()

    return {"imported": imported, "imaged": imaged, "listed": len(pairs)}


async def resume_myplate_images(*, email: str) -> dict[str, int]:
    """Download missing MyPlate images for an already-seeded cookbook."""
    owner = await _resolve_owner(email, create_if_missing=False)
    async with SessionLocal() as db:
        cookbook = await db.scalar(
            select(Cookbook).where(
                Cookbook.user_id == owner.id,
                Cookbook.title == COOKBOOK_TITLE,
            )
        )
        if cookbook is None:
            raise RuntimeError(f"No {COOKBOOK_TITLE!r} cookbook for {email}")
        recipes = list(
            await db.scalars(
                select(Recipe).where(
                    Recipe.cookbook_id == cookbook.id,
                    Recipe.image_source != ImageSource.extracted,
                )
            )
        )
        cookbook_id = cookbook.id

    pending: list[tuple[uuid.UUID, str, str]] = []
    for recipe in recipes:
        slug = _slug_from_tags(recipe.tags) or ""
        if not slug and recipe.image_key and recipe.image_key.startswith("myplate:"):
            slug = recipe.image_key.split(":", 1)[1]
        if not slug:
            logger.warning("No MyPlate slug for recipe %s (%s)", recipe.id, recipe.title)
            continue
        image_url = f"{MYPLATE_CDN}/{slug}.jpg"
        pending.append((recipe.id, image_url, slug))

    imaged = 0
    async with MyPlateClient() as client:
        # Prefer cached detail image_url when available.
        resolved: list[tuple[uuid.UUID, str, str]] = []
        for recipe_id, fallback_url, slug in pending:
            detail = client._read_cache(slug)
            url = str((detail or {}).get("image_url") or fallback_url)
            resolved.append((recipe_id, url, slug))

        logger.info("Resuming MyPlate images: %s remaining", len(resolved))
        for index, (recipe_id, image_url, slug) in enumerate(resolved, start=1):
            content = await client.download_image(image_url)
            if not content:
                continue
            relative = _save_extracted_image(
                content,
                settings.upload_dir,
                str(cookbook_id),
                str(recipe_id),
                Path(image_url).name or "recipe.jpg",
            )
            try:
                async with SessionLocal() as db:
                    recipe = await db.get(Recipe, recipe_id)
                    if recipe is None:
                        continue
                    recipe.image_path = relative
                    recipe.image_source = ImageSource.extracted
                    recipe.image_key = _image_key(slug, recipe_id)
                    await db.commit()
                imaged += 1
            except Exception:
                logger.exception(
                    "Failed to save MyPlate image for recipe %s (%s)",
                    recipe_id,
                    slug,
                )
            if index % 50 == 0 or index == len(resolved):
                logger.info("Downloaded images %s/%s", index, len(resolved))

    async with SessionLocal() as db:
        cookbook_row = await db.get(Cookbook, cookbook_id)
        if cookbook_row:
            cookbook_row.status = UploadStatus.completed
            cookbook_row.progress = 100
            cookbook_row.error = None
            await db.commit()

    return {"imported": 0, "imaged": imaged, "listed": len(resolved)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import USDA MyPlate Kitchen recipes rated above a threshold"
    )
    parser.add_argument(
        "--email",
        default=DEFAULT_OWNER_EMAIL,
        help=f"Owner account email (default: {DEFAULT_OWNER_EMAIL})",
    )
    parser.add_argument(
        "--min-rating",
        type=float,
        default=3.5,
        help="Import recipes with rating strictly above this value (default: 3.5)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing USDA MyPlate Kitchen cookbook for this user",
    )
    parser.add_argument(
        "--create-user",
        action="store_true",
        help="Create the owner user if missing",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip downloading MyPlate images (use category fallbacks)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap for testing",
    )
    parser.add_argument(
        "--images-only",
        action="store_true",
        help="Resume image downloads for an existing MyPlate cookbook",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.images_only:
        stats = asyncio.run(resume_myplate_images(email=args.email))
    else:
        stats = asyncio.run(
            seed_myplate(
                email=args.email,
                min_rating_exclusive=args.min_rating,
                force=args.force,
                create_user=args.create_user,
                download_images=not args.no_images,
                limit=args.limit,
            )
        )
    logger.info(
        "MyPlate seed complete: imported=%s imaged=%s listed=%s",
        stats["imported"],
        stats["imaged"],
        stats["listed"],
    )


if __name__ == "__main__":
    main()
