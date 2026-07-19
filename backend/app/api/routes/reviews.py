"""Shared reviews attached to catalog recipe IDs."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.models import CatalogRecipe, Review, ReviewPhoto
from app.schemas.api import (
    CatalogRecipeOut,
    Message,
    ReviewCreate,
    ReviewOut,
    ReviewPage,
    ReviewPhotoOut,
    ReviewUpdate,
)
from app.services.catalog import refresh_catalog_recipe_aggregates

router = APIRouter(prefix="/catalog/recipes", tags=["reviews"])

MAX_REVIEW_PHOTOS = 5
MAX_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def review_photo_url(catalog_recipe_id: uuid.UUID, photo_id: uuid.UUID) -> str:
    return (
        f"{settings.api_prefix}/catalog/recipes/{catalog_recipe_id}"
        f"/reviews/photos/{photo_id}"
    )


def serialize_review(review: Review, display_name: str | None = None) -> ReviewOut:
    name = display_name
    if name is None and review.user is not None:
        name = review.user.display_name
    return ReviewOut(
        id=review.id,
        catalog_recipe_id=review.catalog_recipe_id,
        user_id=review.user_id,
        display_name=name,
        rating=review.rating,
        body=review.body,
        photos=[
            ReviewPhotoOut(
                id=photo.id,
                position=photo.position,
                url=review_photo_url(review.catalog_recipe_id, photo.id),
            )
            for photo in sorted(review.photos, key=lambda item: item.position)
        ],
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


async def get_catalog_recipe_or_404(db: DB, catalog_recipe_id: uuid.UUID) -> CatalogRecipe:
    catalog_recipe = await db.get(CatalogRecipe, catalog_recipe_id)
    if catalog_recipe is None:
        raise HTTPException(status_code=404, detail="Catalog recipe not found")
    return catalog_recipe


async def load_review(
    db: DB,
    *,
    catalog_recipe_id: uuid.UUID,
    review_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Review | None:
    statement = (
        select(Review)
        .options(selectinload(Review.photos), selectinload(Review.user))
        .where(Review.catalog_recipe_id == catalog_recipe_id)
    )
    if review_id is not None:
        statement = statement.where(Review.id == review_id)
    if user_id is not None:
        statement = statement.where(Review.user_id == user_id)
    return await db.scalar(statement)


def resolve_review_photo_file(storage_path: str) -> Path:
    upload_root = settings.upload_dir.resolve()
    candidate = (settings.upload_dir / storage_path).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return candidate


@router.get("/{catalog_recipe_id}", response_model=CatalogRecipeOut)
async def get_catalog_recipe(
    catalog_recipe_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
) -> CatalogRecipe:
    del user
    return await get_catalog_recipe_or_404(db, catalog_recipe_id)


@router.get("/{catalog_recipe_id}/reviews", response_model=ReviewPage)
async def list_reviews(
    catalog_recipe_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=50),
) -> ReviewPage:
    del user
    await get_catalog_recipe_or_404(db, catalog_recipe_id)
    rows = (
        await db.scalars(
            select(Review)
            .options(selectinload(Review.photos), selectinload(Review.user))
            .where(Review.catalog_recipe_id == catalog_recipe_id)
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
    ).all()
    return ReviewPage(items=[serialize_review(row) for row in rows])


@router.get("/{catalog_recipe_id}/reviews/me", response_model=ReviewOut | None)
async def get_my_review(
    catalog_recipe_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
) -> ReviewOut | None:
    await get_catalog_recipe_or_404(db, catalog_recipe_id)
    review = await load_review(db, catalog_recipe_id=catalog_recipe_id, user_id=user.id)
    if review is None:
        return None
    return serialize_review(review, display_name=user.display_name)


@router.post(
    "/{catalog_recipe_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    catalog_recipe_id: uuid.UUID,
    body: ReviewCreate,
    db: DB,
    user: CurrentUser,
) -> ReviewOut:
    await get_catalog_recipe_or_404(db, catalog_recipe_id)
    review = Review(
        user_id=user.id,
        catalog_recipe_id=catalog_recipe_id,
        rating=body.rating,
        body=body.body,
    )
    try:
        async with db.begin_nested():
            db.add(review)
            await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="You have already reviewed this recipe",
        ) from exc
    await refresh_catalog_recipe_aggregates(db, catalog_recipe_id)
    await db.commit()
    loaded = await load_review(db, catalog_recipe_id=catalog_recipe_id, review_id=review.id)
    assert loaded is not None
    return serialize_review(loaded, display_name=user.display_name)


@router.patch("/{catalog_recipe_id}/reviews/me", response_model=ReviewOut)
async def update_my_review(
    catalog_recipe_id: uuid.UUID,
    body: ReviewUpdate,
    db: DB,
    user: CurrentUser,
) -> ReviewOut:
    await get_catalog_recipe_or_404(db, catalog_recipe_id)
    review = await load_review(db, catalog_recipe_id=catalog_recipe_id, user_id=user.id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    fields = body.model_fields_set
    if "rating" in fields and body.rating is not None:
        review.rating = body.rating
    if "body" in fields:
        review.body = body.body
    await refresh_catalog_recipe_aggregates(db, catalog_recipe_id)
    await db.commit()
    loaded = await load_review(db, catalog_recipe_id=catalog_recipe_id, review_id=review.id)
    assert loaded is not None
    return serialize_review(loaded, display_name=user.display_name)


@router.delete("/{catalog_recipe_id}/reviews/me", response_model=Message)
async def delete_my_review(
    catalog_recipe_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
) -> Message:
    await get_catalog_recipe_or_404(db, catalog_recipe_id)
    review = await load_review(db, catalog_recipe_id=catalog_recipe_id, user_id=user.id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    photo_paths = [photo.storage_path for photo in review.photos]
    await db.delete(review)
    await refresh_catalog_recipe_aggregates(db, catalog_recipe_id)
    await db.commit()
    for relative in photo_paths:
        path = settings.upload_dir / relative
        path.unlink(missing_ok=True)
    return Message(detail="Review deleted")


@router.post(
    "/{catalog_recipe_id}/reviews/me/photos",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_review_photo(
    catalog_recipe_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> ReviewOut:
    await get_catalog_recipe_or_404(db, catalog_recipe_id)
    review = await load_review(db, catalog_recipe_id=catalog_recipe_id, user_id=user.id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if len(review.photos) >= MAX_REVIEW_PHOTOS:
        raise HTTPException(status_code=400, detail="Maximum number of photos reached")

    content_type = (file.content_type or "").lower()
    suffix = ALLOWED_PHOTO_TYPES.get(content_type)
    if suffix is None:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP photos are supported")

    data = await file.read(MAX_PHOTO_BYTES + 1)
    await file.close()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo exceeds 5MB limit")
    if not data:
        raise HTTPException(status_code=400, detail="Empty photo upload")

    relative_dir = Path("reviews") / str(review.id)
    absolute_dir = settings.upload_dir / relative_dir
    absolute_dir.mkdir(parents=True, exist_ok=True)
    photo_id = uuid.uuid4()
    relative_path = relative_dir / f"{photo_id}{suffix}"
    absolute_path = settings.upload_dir / relative_path
    absolute_path.write_bytes(data)

    next_position = max((photo.position for photo in review.photos), default=-1) + 1
    review_id = review.id
    db.add(
        ReviewPhoto(
            id=photo_id,
            review_id=review_id,
            storage_path=str(relative_path).replace("\\", "/"),
            position=next_position,
        )
    )
    await db.commit()
    db.expire_all()
    loaded = await load_review(db, catalog_recipe_id=catalog_recipe_id, review_id=review_id)
    assert loaded is not None
    return serialize_review(loaded, display_name=user.display_name)


@router.get("/{catalog_recipe_id}/reviews/photos/{photo_id}")
async def get_review_photo(
    catalog_recipe_id: uuid.UUID,
    photo_id: uuid.UUID,
    db: DB,
) -> FileResponse:
    """Serve review photos by opaque IDs (no bearer header available for <img>)."""
    photo = await db.scalar(
        select(ReviewPhoto)
        .join(Review, Review.id == ReviewPhoto.review_id)
        .where(
            ReviewPhoto.id == photo_id,
            Review.catalog_recipe_id == catalog_recipe_id,
        )
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = resolve_review_photo_file(photo.storage_path)
    media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media)


@router.delete(
    "/{catalog_recipe_id}/reviews/me/photos/{photo_id}",
    response_model=ReviewOut,
)
async def delete_review_photo(
    catalog_recipe_id: uuid.UUID,
    photo_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
) -> ReviewOut:
    review = await load_review(db, catalog_recipe_id=catalog_recipe_id, user_id=user.id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    photo = next((item for item in review.photos if item.id == photo_id), None)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    review_id = review.id
    storage_path = photo.storage_path
    await db.delete(photo)
    await db.commit()
    (settings.upload_dir / storage_path).unlink(missing_ok=True)
    db.expire_all()
    loaded = await load_review(db, catalog_recipe_id=catalog_recipe_id, review_id=review_id)
    assert loaded is not None
    return serialize_review(loaded, display_name=user.display_name)
