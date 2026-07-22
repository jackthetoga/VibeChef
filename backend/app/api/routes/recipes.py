import base64
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import (
    Integer,
    Text,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    literal_column,
    not_,
    or_,
    select,
)
from sqlalchemy.orm import aliased, selectinload

from app.api.deps import DB, CurrentUser
from app.models import CatalogRecipe, Cookbook, Ingredient, PantryItem, Recipe, RecipeIngredient
from app.schemas.api import (
    NutritionOut,
    RecipeCookCreate,
    RecipeCookOut,
    RecipeListItem,
    RecipeOut,
    RecipePage,
    RecipeUpdate,
)
from app.services.canonicalize import (
    COOKING_ONION_NAMES,
    SAUSAGE_NAMES,
    ingredient_match_key,
)
from app.services.pantry_matching import PantryMatcher, collapse_alternate_groups
from app.services.pantry_text import apply_quantity_delta
from app.services.recipe_filters import (
    food_group_tag_candidates,
    normalize_category,
    tags_contain,
    tags_contain_any,
)
from app.services.recipe_images import (
    recipe_image_media_type,
    recipe_image_url,
    resolve_recipe_image_file,
)
from app.services.recipe_tagging import apply_manual_tags
from app.services.units import (
    compare_quantities,
    normalized_unit_expression,
    quantity_in_grams_expression,
    unit_dimension_expression,
    unit_factor_expression,
)

router = APIRouter(prefix="/recipes", tags=["recipes"])


def nutrition_out(recipe: Recipe) -> NutritionOut | None:
    has_macros = any(
        value is not None
        for value in (
            recipe.calories,
            recipe.protein_grams,
            recipe.carbs_grams,
            recipe.fat_grams,
        )
    )
    if not has_macros and recipe.nutrition_source is None:
        return None
    return NutritionOut(
        calories=recipe.calories,
        protein_g=recipe.protein_grams,
        carbs_g=recipe.carbs_grams,
        fat_g=recipe.fat_grams,
        source=recipe.nutrition_source.value if recipe.nutrition_source else None,
        basis=recipe.nutrition_basis.value if recipe.nutrition_basis else None,
        coverage=recipe.nutrition_coverage,
    )


SortField = Literal[
    "total_time",
    "calories",
    "protein",
    "missing_count",
    "created_at",
    "title",
    "rating",
]
SortOrder = Literal["asc", "desc"]


def pantry_quantity_match_expression(ingredient_name):
    pantry_unit = normalized_unit_expression(PantryItem.unit)
    recipe_unit = normalized_unit_expression(RecipeIngredient.unit)
    pantry_dimension = unit_dimension_expression(PantryItem.unit)
    recipe_dimension = unit_dimension_expression(RecipeIngredient.unit)
    pantry_factor = unit_factor_expression(PantryItem.unit)
    recipe_factor = unit_factor_expression(RecipeIngredient.unit)
    pantry_grams = quantity_in_grams_expression(
        PantryItem.quantity,
        PantryItem.unit,
        ingredient_name,
    )
    recipe_grams = quantity_in_grams_expression(
        RecipeIngredient.quantity,
        RecipeIngredient.unit,
        ingredient_name,
    )

    both_unitless = and_(PantryItem.unit.is_(None), RecipeIngredient.unit.is_(None))
    same_unit = and_(
        PantryItem.unit.is_not(None),
        RecipeIngredient.unit.is_not(None),
        pantry_unit == recipe_unit,
    )
    convertible = and_(
        pantry_dimension.is_not(None),
        recipe_dimension.is_not(None),
        pantry_dimension == recipe_dimension,
    )
    density_convertible = and_(pantry_grams.is_not(None), recipe_grams.is_not(None))
    comparable = or_(both_unitless, same_unit, convertible, density_convertible)
    return or_(
        RecipeIngredient.quantity.is_(None),
        PantryItem.quantity.is_(None),
        not_(comparable),
        and_(
            or_(both_unitless, same_unit),
            PantryItem.quantity >= RecipeIngredient.quantity,
        ),
        and_(
            convertible,
            PantryItem.quantity * pantry_factor >= RecipeIngredient.quantity * recipe_factor,
        ),
        and_(density_convertible, pantry_grams >= recipe_grams),
    )


def _ingredient_match_key_expression(name_column):
    """SQL mirror of ingredient_match_key for list/makeable queries."""
    normalized = func.lower(func.trim(name_column))
    return case(
        (normalized.in_(sorted(COOKING_ONION_NAMES)), "onion"),
        (normalized.in_(sorted(SAUSAGE_NAMES)), "sausage"),
        else_=normalized,
    )


def missing_count_expression(user_id: uuid.UUID):
    """Count unsatisfied ingredient groups (OR alternates use ANY matching)."""
    pantry_ingredient = aliased(Ingredient)
    group_key = func.coalesce(RecipeIngredient.alternate_group_id, RecipeIngredient.id)
    recipe_name = func.lower(func.trim(Ingredient.name))
    pantry_name = func.lower(func.trim(pantry_ingredient.name))
    # Portable parent extraction for "... zest/peel/rind/juice"
    parent_name = func.trim(
        func.replace(
            func.replace(
                func.replace(
                    func.replace(recipe_name, " zest", ""),
                    " peel",
                    "",
                ),
                " rind",
                "",
            ),
            " juice",
            "",
        )
    )
    same_canonical = func.coalesce(
        pantry_ingredient.canonical_id, pantry_ingredient.id
    ) == func.coalesce(Ingredient.canonical_id, Ingredient.id)
    same_match_key = _ingredient_match_key_expression(
        pantry_ingredient.name
    ) == _ingredient_match_key_expression(Ingredient.name)
    derivative_parent_match = and_(
        recipe_name != parent_name,
        or_(
            pantry_name == parent_name,
            pantry_name == parent_name + "s",
            and_(
                func.length(parent_name) > 1,
                pantry_name == func.substr(parent_name, 1, func.length(parent_name) - 1),
            ),
        ),
    )
    in_pantry = exists(
        select(literal(1))
        .select_from(PantryItem)
        .join(pantry_ingredient, pantry_ingredient.id == PantryItem.ingredient_id)
        .where(
            PantryItem.user_id == user_id,
            or_(same_canonical, same_match_key, derivative_parent_match),
            pantry_quantity_match_expression(Ingredient.name),
        )
    )
    total_groups = (
        select(func.count(func.distinct(group_key)))
        .select_from(RecipeIngredient)
        .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
        .where(
            RecipeIngredient.recipe_id == Recipe.id,
            Ingredient.staple.is_(False),
        )
        .correlate(Recipe)
        .scalar_subquery()
    )
    satisfied_groups = (
        select(func.count(func.distinct(group_key)))
        .select_from(RecipeIngredient)
        .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
        .where(
            RecipeIngredient.recipe_id == Recipe.id,
            Ingredient.staple.is_(False),
            in_pantry,
        )
        .correlate(Recipe)
        .scalar_subquery()
    )
    return total_groups - satisfied_groups


def encode_cursor(value: object, recipe_id: uuid.UUID) -> str:
    if isinstance(value, datetime):
        serialized = value.isoformat()
    elif isinstance(value, Decimal):
        serialized = str(value)
    else:
        serialized = value
    payload = json.dumps({"v": serialized, "id": str(recipe_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, sort: SortField) -> tuple[object, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        value: object = payload["v"]
        if sort == "created_at":
            value = datetime.fromisoformat(str(value))
        elif sort in {"total_time", "calories", "protein", "rating"}:
            value = Decimal(str(value))
        elif sort == "missing_count":
            value = int(value)
        return value, uuid.UUID(payload["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from None


@router.get("", response_model=RecipePage)
async def list_recipes(
    db: DB,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=200),
    query: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="created_at"),
    order: SortOrder = "desc",
    max_time: int | None = Query(default=None, ge=0),
    min_protein: Decimal | None = Query(default=None, ge=0),
    max_missing: int | None = Query(default=None, ge=0),
    cuisine: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=80),
    food_group: str | None = Query(default=None, max_length=80),
    tag: list[str] | None = Query(default=None, max_length=80),
    cookbook_id: uuid.UUID | None = None,
    makeable: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> RecipePage:
    sort_aliases = {"time": "total_time", "relevance": "missing_count"}
    canonical_sort = sort_aliases.get(sort, sort)
    if canonical_sort not in {
        "total_time",
        "calories",
        "protein",
        "missing_count",
        "created_at",
        "title",
        "rating",
    }:
        raise HTTPException(status_code=422, detail="Unsupported recipe sort")
    missing = missing_count_expression(user.id)
    null_number = 1_000_000_000 if order == "asc" else -1
    rating_null = Decimal("-1") if order == "desc" else Decimal("1000000")
    sort_expressions = {
        "total_time": func.coalesce(Recipe.total_minutes, null_number),
        "calories": func.coalesce(Recipe.calories, null_number),
        "protein": func.coalesce(Recipe.protein_grams, null_number),
        "missing_count": cast(missing, Integer),
        "created_at": Recipe.created_at,
        "title": func.lower(Recipe.title),
        "rating": func.coalesce(Recipe.rating, rating_null),
    }
    sort_expr = sort_expressions[canonical_sort]
    statement = (
        select(
            Recipe,
            missing.label("missing_count"),
            sort_expr.label("sort_value"),
            Cookbook.title.label("cookbook_title"),
            CatalogRecipe.user_rating_avg,
            CatalogRecipe.user_rating_count,
        )
        .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
        .outerjoin(CatalogRecipe, CatalogRecipe.id == Recipe.catalog_recipe_id)
        .where(Cookbook.user_id == user.id)
    )
    search = q or query
    if search:
        if db.get_bind().dialect.name == "postgresql":
            document = func.to_tsvector(
                literal_column("'english'"),
                func.coalesce(Recipe.title, "")
                + " "
                + func.coalesce(Recipe.cuisine, "")
                + " "
                + func.coalesce(cast(Recipe.tags, Text), ""),
            )
            statement = statement.where(
                document.op("@@")(func.plainto_tsquery(literal_column("'english'"), search.strip()))
            )
        else:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Recipe.title.ilike(term),
                    Recipe.cuisine.ilike(term),
                    cast(Recipe.tags, Text).ilike(term),
                )
            )
    if max_time is not None:
        statement = statement.where(Recipe.total_minutes <= max_time)
    if min_protein is not None:
        statement = statement.where(Recipe.protein_grams >= min_protein)
    if max_missing is not None:
        statement = statement.where(missing <= max_missing)
    if makeable:
        statement = statement.where(missing <= 0)
    # Cuisine is exclusive: a single value only (not combinable with other cuisines).
    if cuisine:
        statement = statement.where(func.lower(Recipe.cuisine) == cuisine.strip().lower())
    if category:
        category_clause = tags_contain(normalize_category(category))
        statement = statement.where(category_clause)
    if food_group:
        group_clause = tags_contain_any(food_group_tag_candidates(food_group))
        if group_clause is not None:
            statement = statement.where(group_clause)
    # Extra tags stack (AND). Useful for dish styles that are not cuisine.
    for raw_tag in tag or []:
        cleaned = raw_tag.strip().lower()
        if cleaned:
            statement = statement.where(tags_contain(cleaned))
    if cookbook_id:
        statement = statement.where(Recipe.cookbook_id == cookbook_id)

    direction = sort_expr.asc if order == "asc" else sort_expr.desc
    id_direction = Recipe.id.asc if order == "asc" else Recipe.id.desc
    if cursor:
        cursor_value, cursor_id = decode_cursor(cursor, canonical_sort)
        comparator = sort_expr > cursor_value if order == "asc" else sort_expr < cursor_value
        id_comparator = Recipe.id > cursor_id if order == "asc" else Recipe.id < cursor_id
        statement = statement.where(
            or_(
                comparator,
                and_(sort_expr == cursor_value, id_comparator),
            )
        )
    statement = statement.order_by(direction(), id_direction()).limit(limit + 1)
    rows = (await db.execute(statement)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        RecipeListItem(
            id=recipe.id,
            cookbook_id=recipe.cookbook_id,
            cookbook_title=cookbook_title,
            catalog_recipe_id=recipe.catalog_recipe_id,
            title=recipe.title,
            total_minutes=recipe.total_minutes,
            calories=recipe.calories,
            protein_grams=recipe.protein_grams,
            cuisine=recipe.cuisine,
            rating=recipe.rating,
            rating_count=recipe.rating_count,
            user_rating_avg=user_rating_avg,
            user_rating_count=int(user_rating_count or 0)
            if user_rating_count is not None
            else None,
            tags=recipe.tags,
            tag_source=recipe.tag_source,
            created_at=recipe.created_at,
            missing_count=int(missing_value or 0),
            image_url=recipe_image_url(recipe.id, recipe.image_path),
            image_source=recipe.image_source.value if recipe.image_source else None,
            prep_time_minutes=recipe.prep_minutes,
            cook_time_minutes=recipe.cook_minutes,
            total_time_minutes=recipe.total_minutes,
            missing_ingredients=int(missing_value or 0),
            makeable=int(missing_value or 0) == 0,
            nutrition=nutrition_out(recipe),
        )
        for (
            recipe,
            missing_value,
            _,
            cookbook_title,
            user_rating_avg,
            user_rating_count,
        ) in rows
    ]
    next_cursor = None
    if has_more and rows:
        last_recipe, _, last_sort_value, _, _, _ = rows[-1]
        next_cursor = encode_cursor(last_sort_value, last_recipe.id)
    return RecipePage(items=items, next_cursor=next_cursor)


@router.patch("/{recipe_id}", response_model=RecipeOut)
async def update_recipe(
    recipe_id: uuid.UUID,
    body: RecipeUpdate,
    db: DB,
    user: CurrentUser,
) -> Recipe:
    recipe = (
        await db.execute(
            select(Recipe)
            .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
            .where(Recipe.id == recipe_id, Cookbook.user_id == user.id)
        )
    ).scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    fields = body.model_fields_set
    assignment = apply_manual_tags(
        existing_tags=list(recipe.tags or []),
        existing_cuisine=recipe.cuisine,
        cuisine=body.cuisine,
        update_cuisine="cuisine" in fields,
        category=body.category,
        update_category="category" in fields,
        food_groups=body.food_groups if "food_groups" in fields else None,
        dish_tags=body.dish_tags if "dish_tags" in fields else None,
        tags=body.tags if "tags" in fields else None,
    )
    recipe.cuisine = assignment.cuisine
    recipe.tags = assignment.tags
    recipe.tag_source = "manual"
    await db.commit()

    return await get_recipe(recipe_id, db, user)


@router.get("/{recipe_id}", response_model=RecipeOut)
async def get_recipe(recipe_id: uuid.UUID, db: DB, user: CurrentUser) -> Recipe:
    missing = missing_count_expression(user.id)
    row = (
        await db.execute(
            select(
                Recipe,
                missing.label("missing_count"),
                Cookbook.title.label("cookbook_title"),
                CatalogRecipe.user_rating_avg,
                CatalogRecipe.user_rating_count,
            )
            .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
            .outerjoin(CatalogRecipe, CatalogRecipe.id == Recipe.catalog_recipe_id)
            .options(
                selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient)
            )
            .where(Recipe.id == recipe_id, Cookbook.user_id == user.id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe, missing_value, cookbook_title, user_rating_avg, user_rating_count = row
    recipe.missing_count = int(missing_value or 0)
    recipe.cookbook_title = cookbook_title
    recipe.user_rating_avg = user_rating_avg
    recipe.user_rating_count = (
        int(user_rating_count or 0) if recipe.catalog_recipe_id is not None else None
    )
    recipe.prep_time_minutes = recipe.prep_minutes
    recipe.cook_time_minutes = recipe.cook_minutes
    recipe.total_time_minutes = recipe.total_minutes
    recipe.missing_ingredients = recipe.missing_count
    recipe.makeable = recipe.missing_count == 0
    recipe.image_url = recipe_image_url(recipe.id, recipe.image_path)
    recipe.image_source = recipe.image_source.value if recipe.image_source else None
    pantry_items = list(
        await db.scalars(
            select(PantryItem)
            .options(selectinload(PantryItem.ingredient))
            .where(PantryItem.user_id == user.id)
        )
    )
    matcher = PantryMatcher(pantry_items)
    recipe.ingredients = collapse_alternate_groups(
        [matcher.response_row(item) for item in recipe.recipe_ingredients]
    )
    recipe.parse_warnings = list(recipe.parse_warnings or [])
    recipe.nutrition = nutrition_out(recipe)
    return recipe


def _resolve_cook_pantry_item(
    recipe_item: RecipeIngredient,
    pantry_by_canonical: dict[object, PantryItem],
    pantry_by_match_key: dict[str, PantryItem],
    pantry_by_ingredient_id: dict[uuid.UUID, PantryItem] | None = None,
) -> PantryItem | None:
    match_key = recipe_item.ingredient.canonical_id or recipe_item.ingredient_id
    pantry_item = pantry_by_canonical.get(match_key)
    if pantry_item is not None:
        return pantry_item
    pantry_item = pantry_by_match_key.get(ingredient_match_key(recipe_item.ingredient.name))
    if pantry_item is not None:
        return pantry_item
    if pantry_by_ingredient_id is not None:
        return pantry_by_ingredient_id.get(recipe_item.ingredient_id)
    return None


def _default_cook_ingredients(
    recipe_ingredients: list[RecipeIngredient],
    pantry_by_canonical: dict[object, PantryItem],
    pantry_by_match_key: dict[str, PantryItem],
) -> list[tuple[RecipeIngredient, Decimal | None, str | None]]:
    """Pick one ingredient per OR-group (prefer pantry match) and skip staples."""
    groups: dict[object, list[RecipeIngredient]] = {}
    order: list[object] = []
    for item in recipe_ingredients:
        key = item.alternate_group_id or item.id
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    selected: list[tuple[RecipeIngredient, Decimal | None, str | None]] = []
    for key in order:
        members = groups[key]
        non_staples = [member for member in members if not member.ingredient.staple]
        candidates = non_staples or members
        if all(member.ingredient.staple for member in candidates):
            continue

        def rank(member: RecipeIngredient) -> tuple[int, int]:
            pantry_item = _resolve_cook_pantry_item(
                member, pantry_by_canonical, pantry_by_match_key
            )
            if pantry_item is None:
                return (2, 0)
            comparison = compare_quantities(
                pantry_item.quantity,
                pantry_item.unit,
                member.quantity,
                member.unit,
                member.ingredient.name,
            )
            if comparison is True:
                return (0, 0)
            if comparison is False:
                return (1, 0)
            return (1, 1)

        best = min(candidates, key=rank)
        if best.ingredient.staple:
            continue
        selected.append((best, best.quantity, best.unit))
    return selected


@router.post("/{recipe_id}/cook", response_model=RecipeCookOut)
async def cook_recipe(
    recipe_id: uuid.UUID,
    body: RecipeCookCreate,
    db: DB,
    user: CurrentUser,
) -> RecipeCookOut:
    recipe = (
        await db.execute(
            select(Recipe)
            .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
            .options(
                selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient)
            )
            .where(Recipe.id == recipe_id, Cookbook.user_id == user.id)
        )
    ).scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    pantry_items = list(
        await db.scalars(
            select(PantryItem)
            .options(selectinload(PantryItem.ingredient))
            .where(PantryItem.user_id == user.id)
            .with_for_update()
        )
    )
    pantry_by_canonical: dict[object, PantryItem] = {}
    pantry_by_match_key: dict[str, PantryItem] = {}
    pantry_by_ingredient_id: dict[uuid.UUID, PantryItem] = {}
    for item in pantry_items:
        pantry_by_ingredient_id[item.ingredient_id] = item
        key = item.ingredient.canonical_id or item.ingredient_id
        pantry_by_canonical[key] = item
        pantry_by_match_key[ingredient_match_key(item.ingredient.name)] = item

    recipe_by_id = {item.ingredient_id: item for item in recipe.recipe_ingredients}

    if body.items is None:
        deductions = _default_cook_ingredients(
            recipe.recipe_ingredients, pantry_by_canonical, pantry_by_match_key
        )
    else:
        if not body.items:
            raise HTTPException(
                status_code=422,
                detail="Select at least one ingredient to subtract from your fridge",
            )
        deductions = []
        for entry in body.items:
            recipe_item = recipe_by_id.get(entry.ingredient_id)
            if recipe_item is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Ingredient {entry.ingredient_id} is not part of this recipe",
                )
            quantity = entry.quantity if entry.quantity is not None else recipe_item.quantity
            unit = entry.unit if entry.unit is not None else recipe_item.unit
            deductions.append((recipe_item, quantity, unit))

    updated: list[PantryItem] = []
    removed: list[str] = []
    skipped: list[str] = []
    touched: set[uuid.UUID] = set()

    for recipe_item, quantity, unit in deductions:
        pantry_item = _resolve_cook_pantry_item(
            recipe_item,
            pantry_by_canonical,
            pantry_by_match_key,
            pantry_by_ingredient_id,
        )
        if pantry_item is None:
            skipped.append(recipe_item.ingredient.name)
            continue
        if pantry_item.id in touched:
            continue

        new_quantity, new_unit, remove_item = apply_quantity_delta(
            pantry_item.quantity,
            pantry_item.unit,
            quantity,
            unit,
            sign=-1,
        )
        name = (
            pantry_item.ingredient.name
            if pantry_item.ingredient is not None
            else recipe_item.ingredient.name
        )
        if remove_item:
            removed.append(name)
            canonical_key = (
                pantry_item.ingredient.canonical_id or pantry_item.ingredient_id
            )
            pantry_by_canonical.pop(canonical_key, None)
            pantry_by_match_key.pop(
                ingredient_match_key(pantry_item.ingredient.name), None
            )
            pantry_by_ingredient_id.pop(pantry_item.ingredient_id, None)
            await db.delete(pantry_item)
            touched.add(pantry_item.id)
            continue

        pantry_item.quantity = new_quantity
        pantry_item.unit = new_unit
        updated.append(pantry_item)
        touched.add(pantry_item.id)

    await db.commit()
    for item in updated:
        await db.refresh(item, attribute_names=["ingredient"])

    return RecipeCookOut(updated=updated, removed=removed, skipped=skipped)


@router.get("/{recipe_id}/image")
async def recipe_image(recipe_id: uuid.UUID, db: DB, user: CurrentUser) -> FileResponse:
    row = (
        await db.execute(
            select(Recipe.image_path)
            .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
            .where(Recipe.id == recipe_id, Cookbook.user_id == user.id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    image_path = row[0]
    if not image_path:
        raise HTTPException(status_code=404, detail="Recipe image not found")
    try:
        path = resolve_recipe_image_file(image_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recipe image not found") from exc
    return FileResponse(path, media_type=recipe_image_media_type(image_path))
