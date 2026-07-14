import base64
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import (
    Integer,
    Text,
    and_,
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
from app.models import Cookbook, Ingredient, PantryItem, Recipe, RecipeIngredient
from app.schemas.api import NutritionOut, RecipeListItem, RecipeOut, RecipePage
from app.services.units import (
    compare_quantities,
    ingredient_conversion_for_units,
    normalized_unit_expression,
    quantity_in_grams_expression,
    unit_dimension_expression,
    unit_factor_expression,
)

router = APIRouter(prefix="/recipes", tags=["recipes"])
SortField = Literal["total_time", "calories", "protein", "missing_count", "created_at", "title"]
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


def missing_count_expression(user_id: uuid.UUID):
    pantry_ingredient = aliased(Ingredient)
    in_pantry = exists(
        select(literal(1))
        .select_from(PantryItem)
        .join(pantry_ingredient, pantry_ingredient.id == PantryItem.ingredient_id)
        .where(
            PantryItem.user_id == user_id,
            func.coalesce(pantry_ingredient.canonical_id, pantry_ingredient.id)
            == func.coalesce(Ingredient.canonical_id, Ingredient.id),
            pantry_quantity_match_expression(Ingredient.name),
        )
    )
    return (
        select(func.count(RecipeIngredient.id))
        .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
        .where(
            RecipeIngredient.recipe_id == Recipe.id,
            Ingredient.staple.is_(False),
            ~in_pantry,
        )
        .correlate(Recipe)
        .scalar_subquery()
    )


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
        elif sort in {"total_time", "calories", "protein"}:
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
    }:
        raise HTTPException(status_code=422, detail="Unsupported recipe sort")
    missing = missing_count_expression(user.id)
    null_number = 1_000_000_000 if order == "asc" else -1
    sort_expressions = {
        "total_time": func.coalesce(Recipe.total_minutes, null_number),
        "calories": func.coalesce(Recipe.calories, null_number),
        "protein": func.coalesce(Recipe.protein_grams, null_number),
        "missing_count": cast(missing, Integer),
        "created_at": Recipe.created_at,
        "title": func.lower(Recipe.title),
    }
    sort_expr = sort_expressions[canonical_sort]
    statement = (
        select(
            Recipe,
            missing.label("missing_count"),
            sort_expr.label("sort_value"),
            Cookbook.title.label("cookbook_title"),
        )
        .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
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
    if cuisine:
        statement = statement.where(func.lower(Recipe.cuisine) == cuisine.strip().lower())
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
            title=recipe.title,
            total_minutes=recipe.total_minutes,
            calories=recipe.calories,
            protein_grams=recipe.protein_grams,
            cuisine=recipe.cuisine,
            tags=recipe.tags,
            created_at=recipe.created_at,
            missing_count=int(missing_value or 0),
            prep_time_minutes=recipe.prep_minutes,
            cook_time_minutes=recipe.cook_minutes,
            total_time_minutes=recipe.total_minutes,
            missing_ingredients=int(missing_value or 0),
            makeable=int(missing_value or 0) == 0,
            nutrition=NutritionOut(
                calories=recipe.calories,
                protein_g=recipe.protein_grams,
                carbs_g=recipe.carbs_grams,
                fat_g=recipe.fat_grams,
            ),
        )
        for recipe, missing_value, _, cookbook_title in rows
    ]
    next_cursor = None
    if has_more and rows:
        last_recipe, _, last_sort_value, _ = rows[-1]
        next_cursor = encode_cursor(last_sort_value, last_recipe.id)
    return RecipePage(items=items, next_cursor=next_cursor)


@router.get("/{recipe_id}", response_model=RecipeOut)
async def get_recipe(recipe_id: uuid.UUID, db: DB, user: CurrentUser) -> Recipe:
    missing = missing_count_expression(user.id)
    row = (
        await db.execute(
            select(Recipe, missing.label("missing_count"), Cookbook.title.label("cookbook_title"))
            .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
            .options(
                selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient)
            )
            .where(Recipe.id == recipe_id, Cookbook.user_id == user.id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe, missing_value, cookbook_title = row
    recipe.missing_count = int(missing_value or 0)
    recipe.cookbook_title = cookbook_title
    recipe.prep_time_minutes = recipe.prep_minutes
    recipe.cook_time_minutes = recipe.cook_minutes
    recipe.total_time_minutes = recipe.total_minutes
    recipe.missing_ingredients = recipe.missing_count
    recipe.makeable = recipe.missing_count == 0
    pantry_items = {
        item.ingredient.canonical_id or item.ingredient_id: item
        for item in await db.scalars(
            select(PantryItem)
            .options(selectinload(PantryItem.ingredient))
            .where(PantryItem.user_id == user.id)
        )
    }

    def ingredient_match(item: RecipeIngredient) -> dict[str, object]:
        match_key = item.ingredient.canonical_id or item.ingredient_id
        pantry_item = pantry_items.get(match_key)
        conversion_profile = (
            ingredient_conversion_for_units(
                pantry_item.unit,
                item.unit,
                item.ingredient.name,
            )
            if pantry_item
            else None
        )
        if item.ingredient.staple:
            match_status = "staple"
        elif pantry_item is None:
            match_status = "missing"
        else:
            comparison = compare_quantities(
                pantry_item.quantity,
                pantry_item.unit,
                item.quantity,
                item.unit,
                item.ingredient.name,
            )
            if comparison is True:
                match_status = "available"
            elif comparison is False:
                match_status = "insufficient"
            else:
                match_status = "unknown"
        return {
            "id": item.id,
            "ingredient_id": item.ingredient_id,
            "name": item.ingredient.name,
            "quantity": item.quantity,
            "unit": item.unit,
            "preparation": None,
            "in_pantry": match_status not in {"missing", "insufficient"},
            "match_status": match_status,
            "pantry_quantity": pantry_item.quantity if pantry_item else None,
            "pantry_unit": pantry_item.unit if pantry_item else None,
            "matched_via": (
                pantry_item.ingredient.name
                if pantry_item
                and pantry_item.ingredient.name != item.ingredient.name
                else None
            ),
            "conversion_basis": conversion_profile.basis if conversion_profile else None,
            "conversion_source": conversion_profile.source_url if conversion_profile else None,
        }

    recipe.ingredients = [
        ingredient_match(item)
        for item in recipe.recipe_ingredients
    ]
    recipe.nutrition = {
        "calories": recipe.calories,
        "protein_g": recipe.protein_grams,
        "carbs_g": recipe.carbs_grams,
        "fat_g": recipe.fat_grams,
    }
    return recipe
