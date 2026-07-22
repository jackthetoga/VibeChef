import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.models import Cookbook, Ingredient, PantryItem, Recipe, RecipeIngredient
from app.schemas.api import (
    CommonIngredientOut,
    IngredientConversionOut,
    IngredientOut,
    IngredientUnlockOut,
    IngredientUnlockSetPage,
    Message,
    PantryBulkCreate,
    PantryBulkOut,
    PantryConfirmCreate,
    PantryConfirmOut,
    PantryConfirmReceiptCreate,
    PantryCreate,
    PantryFromTextCreate,
    PantryFromTextOut,
    PantryOut,
    PantryParsedChangeOut,
    PantryScanItemOut,
    PantryScanOut,
    PantryUpdate,
)
from app.services.common_ingredients import (
    COMMON_INGREDIENT_CATEGORIES,
    COMMON_INGREDIENT_DEFAULTS,
    COMMON_INGREDIENTS,
)
from app.services.ingredient_conversions import INGREDIENT_CONVERSIONS
from app.services.pantry_text import apply_quantity_delta, parse_pantry_text
from app.services.pantry_vision import (
    MAX_IMAGE_BYTES,
    normalize_pantry_image,
    scan_groceries_from_image,
    scan_receipt_from_image,
)
from app.services.rate_limits import enforce_rate_limit
from app.services.unlocks import ingredient_unlock_sets, ingredient_unlock_suggestions

ingredient_router = APIRouter(prefix="/ingredients", tags=["ingredients"])
pantry_router = APIRouter(prefix="/pantry", tags=["pantry"])


def visible_ingredient_ids(user_id: uuid.UUID):
    recipe_ingredients = (
        select(RecipeIngredient.ingredient_id)
        .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
        .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
        .where(Cookbook.user_id == user_id)
    )
    recipe_roots = (
        select(Ingredient.canonical_id)
        .join(RecipeIngredient, RecipeIngredient.ingredient_id == Ingredient.id)
        .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
        .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
        .where(Cookbook.user_id == user_id, Ingredient.canonical_id.is_not(None))
    )
    return (
        select(PantryItem.ingredient_id)
        .where(PantryItem.user_id == user_id)
        .union(recipe_ingredients, recipe_roots)
    )


@ingredient_router.get("/common", response_model=list[CommonIngredientOut])
async def common_ingredients(_: CurrentUser) -> list[CommonIngredientOut]:
    return [
        CommonIngredientOut(
            name=item.name,
            category=item.category,
            default_quantity=item.default_quantity,
            default_unit=item.default_unit,
        )
        for item in COMMON_INGREDIENTS
    ]


@ingredient_router.get("/conversions", response_model=list[IngredientConversionOut])
async def ingredient_conversions(_: CurrentUser) -> list[IngredientConversionOut]:
    return [
        IngredientConversionOut(
            name=profile.name,
            grams_per_cup=profile.grams_per_cup,
            basis=profile.basis,
            source=profile.source,
            source_url=profile.source_url,
            confidence=profile.confidence,
            aliases=list(profile.aliases),
            grams_per_item=profile.grams_per_item,
            grams_per_clove=profile.grams_per_clove,
        )
        for profile in INGREDIENT_CONVERSIONS
    ]


@ingredient_router.get("", response_model=list[IngredientOut])
@ingredient_router.get("/autocomplete", response_model=list[IngredientOut])
async def autocomplete(
    db: DB,
    user: CurrentUser,
    q: str | None = Query(default=None, min_length=1, max_length=100),
    query: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[IngredientOut]:
    search = q or query
    if not search:
        raise HTTPException(status_code=422, detail="A q or query parameter is required")
    normalized = " ".join(search.lower().split())
    term = f"%{normalized}%"
    prefix = f"{normalized}%"
    candidate = aliased(Ingredient)
    canonical = aliased(Ingredient)
    match_rank = case(
        (func.lower(canonical.name) == normalized, 0),
        (func.lower(canonical.name).like(prefix), 1),
        (func.lower(candidate.name) == normalized, 2),
        (func.lower(candidate.name).like(prefix), 3),
        else_=4,
    )
    ranked_roots = (
        await db.execute(
            select(
                canonical.id,
                func.min(match_rank).label("match_rank"),
                canonical.name,
            )
            .select_from(candidate)
            .join(canonical, canonical.id == candidate.canonical_id)
            .where(
                canonical.canonical_id == canonical.id,
                candidate.id.in_(visible_ingredient_ids(user.id)),
                candidate.name.ilike(term),
            )
            .group_by(canonical.id, canonical.name)
            .order_by(func.min(match_rank), func.lower(canonical.name))
            .limit(limit)
        )
    ).all()
    root_ids = [row.id for row in ranked_roots]
    if not root_ids:
        return []
    roots = list(
        await db.scalars(
            select(Ingredient).where(Ingredient.id.in_(root_ids))
        )
    )
    by_id = {ingredient.id: ingredient for ingredient in roots}
    return [
        IngredientOut(
            id=by_id[root_id].id,
            name=by_id[root_id].name,
            category=by_id[root_id].category,
            staple=by_id[root_id].staple,
            canonical_id=by_id[root_id].canonical_id,
        )
        for root_id in root_ids
        if root_id in by_id
    ]


async def owned_item(db: DB, user_id: uuid.UUID, item_id: uuid.UUID) -> PantryItem:
    item = await db.scalar(
        select(PantryItem)
        .options(selectinload(PantryItem.ingredient))
        .where(PantryItem.id == item_id, PantryItem.user_id == user_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    return item


@pantry_router.get("", response_model=list[PantryOut])
async def list_pantry(db: DB, user: CurrentUser) -> list[PantryItem]:
    result = await db.scalars(
        select(PantryItem)
        .options(selectinload(PantryItem.ingredient))
        .where(PantryItem.user_id == user.id)
        .order_by(PantryItem.expiry_date.asc().nullslast(), PantryItem.created_at.desc())
    )
    return list(result)


@pantry_router.get("/suggestions", response_model=list[IngredientUnlockOut])
async def list_unlock_suggestions(
    db: DB,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    return await ingredient_unlock_suggestions(db, user_id=user.id, limit=limit)


@pantry_router.get("/unlock-sets", response_model=IngredientUnlockSetPage)
async def list_unlock_sets(
    db: DB,
    user: CurrentUser,
    item_count: int = Query(default=2, alias="size", ge=1, le=3),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, object]:
    return await ingredient_unlock_sets(
        db,
        user_id=user.id,
        item_count=item_count,
        limit=limit,
    )


@pantry_router.post("", response_model=PantryOut, status_code=status.HTTP_201_CREATED)
async def add_pantry(body: PantryCreate, db: DB, user: CurrentUser) -> PantryItem:
    if body.ingredient_id:
        ingredient = await db.scalar(
            select(Ingredient).where(
                Ingredient.id == body.ingredient_id,
                Ingredient.id.in_(visible_ingredient_ids(user.id)),
            )
        )
        if ingredient is None:
            raise HTTPException(status_code=404, detail="Ingredient not found")
    else:
        name = " ".join((body.ingredient_name or "").lower().split())
        ingredient = await db.scalar(select(Ingredient).where(Ingredient.name == name))
        if ingredient is None:
            candidate = Ingredient(
                name=name,
                category=COMMON_INGREDIENT_CATEGORIES.get(name),
            )
            try:
                async with db.begin_nested():
                    db.add(candidate)
                    await db.flush()
                    candidate.canonical_id = candidate.id
                ingredient = candidate
            except IntegrityError:
                ingredient = await db.scalar(select(Ingredient).where(Ingredient.name == name))
                if ingredient is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Ingredient could not be created due to a concurrent update",
                    ) from None

    item = PantryItem(
        user_id=user.id,
        ingredient_id=ingredient.id,
        quantity=body.quantity,
        unit=body.unit,
        expiry_date=body.expiry_date,
    )
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ingredient is already in pantry") from None
    await db.refresh(item)
    item.ingredient = ingredient
    return item


@pantry_router.post("/bulk", response_model=PantryBulkOut, status_code=status.HTTP_201_CREATED)
async def add_pantry_bulk(body: PantryBulkCreate, db: DB, user: CurrentUser) -> PantryBulkOut:
    bulk_items = body.resolved_items()
    # Preserve first occurrence order while deduping by name.
    by_request: dict[str, tuple[Decimal | None, str | None]] = {}
    for item in bulk_items:
        by_request.setdefault(item.name, (item.quantity, item.unit))
    names = list(by_request)

    ingredients = list(
        await db.scalars(select(Ingredient).where(func.lower(Ingredient.name).in_(names)))
    )
    by_name = {ingredient.name.lower(): ingredient for ingredient in ingredients}

    created: list[Ingredient] = []
    for name in names:
        if name not in by_name:
            ingredient = Ingredient(
                name=name,
                category=COMMON_INGREDIENT_CATEGORIES.get(name),
            )
            db.add(ingredient)
            by_name[name] = ingredient
            created.append(ingredient)
    await db.flush()
    for ingredient in created:
        ingredient.canonical_id = ingredient.id

    ingredient_ids = [by_name[name].id for name in names]
    existing_ids = set(
        await db.scalars(
            select(PantryItem.ingredient_id).where(
                PantryItem.user_id == user.id,
                PantryItem.ingredient_id.in_(ingredient_ids),
            )
        )
    )
    added: list[PantryItem] = []
    skipped: list[str] = []
    for name in names:
        ingredient = by_name[name]
        if ingredient.id in existing_ids:
            skipped.append(name)
            continue
        quantity, unit = by_request[name]
        defaults = COMMON_INGREDIENT_DEFAULTS.get(name)
        if defaults:
            default_qty, default_unit = defaults
            if quantity is None:
                quantity = default_qty
            if unit is None:
                unit = default_unit
        item = PantryItem(
            user_id=user.id,
            ingredient_id=ingredient.id,
            quantity=quantity,
            unit=unit,
        )
        item.ingredient = ingredient
        db.add(item)
        added.append(item)

    await db.commit()
    for item in added:
        await db.refresh(item)
        item.ingredient = by_name[item.ingredient.name.lower()]
    return PantryBulkOut(added=added, skipped_existing=skipped)


@pantry_router.post("/from-text", response_model=PantryFromTextOut)
async def update_pantry_from_text(
    request: Request,
    body: PantryFromTextCreate,
    db: DB,
    user: CurrentUser,
) -> PantryFromTextOut:
    await enforce_rate_limit(
        request,
        scope="pantry-text",
        identity=str(user.id),
        limit=settings.pantry_ai_rate_limit_per_hour,
        window_seconds=60 * 60,
        fail_closed=True,
    )
    changes = await parse_pantry_text(body.text)
    if not changes:
        raise HTTPException(
            status_code=422,
            detail="Could not find any ingredient adds or removals in that text",
        )

    names = list({change.name for change in changes})
    ingredients = list(
        await db.scalars(select(Ingredient).where(func.lower(Ingredient.name).in_(names)))
    )
    by_name = {ingredient.name.lower(): ingredient for ingredient in ingredients}

    created: list[Ingredient] = []
    for change in changes:
        if change.action != "add" or change.name in by_name:
            continue
        ingredient = Ingredient(
            name=change.name,
            category=COMMON_INGREDIENT_CATEGORIES.get(change.name),
        )
        db.add(ingredient)
        by_name[change.name] = ingredient
        created.append(ingredient)
    await db.flush()
    for ingredient in created:
        ingredient.canonical_id = ingredient.id

    pantry_items = list(
        await db.scalars(
            select(PantryItem)
            .options(selectinload(PantryItem.ingredient))
            .where(PantryItem.user_id == user.id)
            .with_for_update()
        )
    )
    by_ingredient_id = {item.ingredient_id: item for item in pantry_items}
    by_pantry_name = {
        item.ingredient.name.lower(): item
        for item in pantry_items
        if item.ingredient is not None
    }

    added: list[PantryItem] = []
    updated: list[PantryItem] = []
    removed: list[str] = []
    skipped: list[str] = []
    updated_ids: set[uuid.UUID] = set()

    for change in changes:
        if change.action == "add":
            ingredient = by_name[change.name]
            item = by_ingredient_id.get(ingredient.id)
            if item is None:
                quantity = change.quantity
                unit = change.unit
                defaults = COMMON_INGREDIENT_DEFAULTS.get(change.name)
                if defaults and quantity is None:
                    quantity, unit = defaults
                item = PantryItem(
                    user_id=user.id,
                    ingredient_id=ingredient.id,
                    quantity=quantity,
                    unit=unit,
                )
                item.ingredient = ingredient
                db.add(item)
                by_ingredient_id[ingredient.id] = item
                by_pantry_name[change.name] = item
                added.append(item)
                continue

            new_quantity, new_unit, _ = apply_quantity_delta(
                item.quantity,
                item.unit,
                change.quantity,
                change.unit,
                sign=1,
            )
            item.quantity = new_quantity
            item.unit = new_unit
            if item not in added and item.id not in updated_ids:
                updated.append(item)
                updated_ids.add(item.id)
            continue

        item = by_pantry_name.get(change.name)
        if item is None and change.name in by_name:
            item = by_ingredient_id.get(by_name[change.name].id)
        if item is None:
            skipped.append(change.name)
            continue

        new_quantity, new_unit, remove_item = apply_quantity_delta(
            item.quantity,
            item.unit,
            change.quantity,
            change.unit,
            sign=-1,
        )
        if remove_item:
            removed.append(change.name)
            by_ingredient_id.pop(item.ingredient_id, None)
            by_pantry_name.pop(change.name, None)
            if item in added:
                added.remove(item)
            elif item.id in updated_ids:
                updated = [entry for entry in updated if entry.id != item.id]
                updated_ids.discard(item.id)
            await db.delete(item)
            continue

        item.quantity = new_quantity
        item.unit = new_unit
        if item not in added and item.id not in updated_ids:
            updated.append(item)
            updated_ids.add(item.id)

    await db.commit()
    for item in added + updated:
        await db.refresh(item)
        for ingredient in by_name.values():
            if ingredient.id == item.ingredient_id:
                item.ingredient = ingredient
                break

    return PantryFromTextOut(
        parsed=[
            PantryParsedChangeOut(
                action=change.action,
                name=change.name,
                quantity=change.quantity,
                unit=change.unit,
            )
            for change in changes
        ],
        added=added,
        updated=updated,
        removed=removed,
        skipped=skipped,
    )


async def _read_pantry_image(file: UploadFile, *, default_filename: str) -> tuple[bytes, str]:
    original = Path(file.filename or default_filename)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded image is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image exceeds the 10 MB size limit",
        )
    try:
        content, media_type = normalize_pantry_image(
            content, file.content_type, original.name
        )
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return content, media_type


async def _resolve_confirm_ingredients(
    db: DB,
    names: list[str],
) -> dict[str, Ingredient]:
    ingredients = list(
        await db.scalars(select(Ingredient).where(func.lower(Ingredient.name).in_(names)))
    )
    by_name = {ingredient.name.lower(): ingredient for ingredient in ingredients}

    created: list[Ingredient] = []
    for name in names:
        if name not in by_name:
            ingredient = Ingredient(
                name=name,
                category=COMMON_INGREDIENT_CATEGORIES.get(name),
            )
            db.add(ingredient)
            by_name[name] = ingredient
            created.append(ingredient)
    await db.flush()
    for ingredient in created:
        ingredient.canonical_id = ingredient.id

    return by_name


@pantry_router.post("/scan", response_model=PantryScanOut)
async def scan_pantry_photo(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> PantryScanOut:
    await enforce_rate_limit(
        request,
        scope="pantry-vision",
        identity=str(user.id),
        limit=settings.pantry_ai_rate_limit_per_hour,
        window_seconds=60 * 60,
        fail_closed=True,
    )
    content, media_type = await _read_pantry_image(file, default_filename="grocery.jpg")

    try:
        items = await scan_groceries_from_image(content=content, media_type=media_type)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not analyze the grocery photo. Try again with a clearer image.",
        ) from exc

    return PantryScanOut(
        items=[
            PantryScanItemOut(
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                confidence=item.confidence,
            )
            for item in items
        ]
    )


@pantry_router.post("/scan-receipt", response_model=PantryScanOut)
async def scan_pantry_receipt(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> PantryScanOut:
    await enforce_rate_limit(
        request,
        scope="pantry-vision",
        identity=str(user.id),
        limit=settings.pantry_ai_rate_limit_per_hour,
        window_seconds=60 * 60,
        fail_closed=True,
    )
    content, media_type = await _read_pantry_image(file, default_filename="receipt.jpg")

    try:
        items = await scan_receipt_from_image(content=content, media_type=media_type)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not analyze the receipt photo. Try again with a clearer image.",
        ) from exc

    return PantryScanOut(
        items=[
            PantryScanItemOut(
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                confidence=item.confidence,
            )
            for item in items
        ]
    )


@pantry_router.post("/confirm", response_model=PantryConfirmOut)
async def confirm_pantry_scan(
    body: PantryConfirmCreate, db: DB, user: CurrentUser
) -> PantryConfirmOut:
    # Preserve first occurrence order while deduping by name.
    by_request: dict[str, tuple[Decimal | None, str | None, date | None]] = {}
    for item in body.items:
        by_request.setdefault(
            item.ingredient_name,
            (item.quantity, item.unit, item.expiry_date),
        )
    names = list(by_request)
    by_name = await _resolve_confirm_ingredients(db, names)

    pantry_items = list(
        await db.scalars(
            select(PantryItem)
            .options(selectinload(PantryItem.ingredient))
            .where(
                PantryItem.user_id == user.id,
                PantryItem.ingredient_id.in_([by_name[name].id for name in names]),
            )
            .with_for_update()
        )
    )
    by_ingredient_id = {item.ingredient_id: item for item in pantry_items}

    added: list[PantryItem] = []
    updated: list[PantryItem] = []
    for name in names:
        ingredient = by_name[name]
        quantity, unit, expiry_date = by_request[name]
        existing = by_ingredient_id.get(ingredient.id)
        if existing is None:
            defaults = COMMON_INGREDIENT_DEFAULTS.get(name)
            if defaults and quantity is None:
                quantity, unit = defaults
            item = PantryItem(
                user_id=user.id,
                ingredient_id=ingredient.id,
                quantity=quantity,
                unit=unit,
                expiry_date=expiry_date,
            )
            item.ingredient = ingredient
            db.add(item)
            by_ingredient_id[ingredient.id] = item
            added.append(item)
            continue

        existing.quantity = quantity
        existing.unit = unit
        if expiry_date is not None:
            existing.expiry_date = expiry_date
        existing.ingredient = ingredient
        updated.append(existing)

    await db.commit()
    for item in added + updated:
        await db.refresh(item)
        for ingredient in by_name.values():
            if ingredient.id == item.ingredient_id:
                item.ingredient = ingredient
                break

    return PantryConfirmOut(added=added, updated=updated)


@pantry_router.post("/confirm-receipt", response_model=PantryConfirmOut)
async def confirm_pantry_receipt(
    body: PantryConfirmReceiptCreate, db: DB, user: CurrentUser
) -> PantryConfirmOut:
    # Preserve first occurrence order while deduping by name.
    by_request: dict[str, tuple[Decimal | None, str | None, date | None]] = {}
    for item in body.items:
        by_request.setdefault(
            item.ingredient_name,
            (item.quantity, item.unit, item.expiry_date),
        )
    names = list(by_request)
    by_name = await _resolve_confirm_ingredients(db, names)

    pantry_items = list(
        await db.scalars(
            select(PantryItem)
            .options(selectinload(PantryItem.ingredient))
            .where(
                PantryItem.user_id == user.id,
                PantryItem.ingredient_id.in_([by_name[name].id for name in names]),
            )
            .with_for_update()
        )
    )
    by_ingredient_id = {item.ingredient_id: item for item in pantry_items}

    added: list[PantryItem] = []
    updated: list[PantryItem] = []
    for name in names:
        ingredient = by_name[name]
        quantity, unit, expiry_date = by_request[name]
        existing = by_ingredient_id.get(ingredient.id)
        if existing is None:
            defaults = COMMON_INGREDIENT_DEFAULTS.get(name)
            if defaults and quantity is None:
                quantity, unit = defaults
            item = PantryItem(
                user_id=user.id,
                ingredient_id=ingredient.id,
                quantity=quantity,
                unit=unit,
                expiry_date=expiry_date,
            )
            item.ingredient = ingredient
            db.add(item)
            by_ingredient_id[ingredient.id] = item
            added.append(item)
            continue

        new_quantity, new_unit, _ = apply_quantity_delta(
            existing.quantity,
            existing.unit,
            quantity,
            unit,
            sign=1,
        )
        existing.quantity = new_quantity
        existing.unit = new_unit
        if expiry_date is not None:
            existing.expiry_date = expiry_date
        existing.ingredient = ingredient
        updated.append(existing)

    await db.commit()
    for item in added + updated:
        await db.refresh(item)
        for ingredient in by_name.values():
            if ingredient.id == item.ingredient_id:
                item.ingredient = ingredient
                break

    return PantryConfirmOut(added=added, updated=updated)


@pantry_router.patch("/{item_id}", response_model=PantryOut)
async def update_pantry(
    item_id: uuid.UUID, body: PantryUpdate, db: DB, user: CurrentUser
) -> PantryItem:
    item = await owned_item(db, user.id, item_id)
    for field in body.model_fields_set:
        setattr(item, field, getattr(body, field))
    await db.commit()
    await db.refresh(item)
    return item


@pantry_router.delete("/{item_id}", response_model=Message)
async def delete_pantry(item_id: uuid.UUID, db: DB, user: CurrentUser) -> Message:
    item = await owned_item(db, user.id, item_id)
    await db.delete(item)
    await db.commit()
    return Message(detail="Pantry item deleted")
