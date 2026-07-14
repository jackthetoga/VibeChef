from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models import (
    Cookbook,
    FoodNutritionCache,
    Ingredient,
    NutritionBasis,
    NutritionSource,
    Recipe,
    RecipeIngredient,
    UploadStatus,
    User,
)
from app.services.fdc_client import FdcClient, FoodMacros
from app.services.food_nutrition_cache import (
    get_cached_macros,
    put_cached_macros,
    seed_food_nutrition_cache,
)
from app.services.nutrition import (
    apply_printed_nutrition_metadata,
    ensure_ingredient_macros,
    estimate_recipe_nutrition,
    recipe_ingredient_grams,
    select_lines_for_estimation,
)


def test_recipe_ingredient_grams_mass_and_volume() -> None:
    assert recipe_ingredient_grams(Decimal("2"), "lb", "ground beef") == Decimal("907.18474")
    assert recipe_ingredient_grams(Decimal("1"), "cup", "all-purpose flour") == Decimal("120")
    from app.services.ingredient_conversions import get_ingredient_conversion

    eggs = get_ingredient_conversion("eggs")
    assert eggs is not None and eggs.grams_per_item is not None
    assert recipe_ingredient_grams(Decimal("2"), None, "eggs") == Decimal("2") * eggs.grams_per_item


def test_to_taste_without_quantity_skipped() -> None:
    assert (
        recipe_ingredient_grams(None, None, "salt", raw_text="salt to taste") is None
    )


def test_select_lines_picks_first_alternate() -> None:
    group = uuid4()
    a = RecipeIngredient(
        id=uuid4(),
        recipe_id=uuid4(),
        ingredient_id=uuid4(),
        quantity=Decimal("1"),
        unit="cup",
        raw_text="1 cup milk",
        position=0,
        alternate_group_id=group,
    )
    b = RecipeIngredient(
        id=uuid4(),
        recipe_id=uuid4(),
        ingredient_id=uuid4(),
        quantity=Decimal("1"),
        unit="cup",
        raw_text="1 cup cream",
        position=1,
        alternate_group_id=group,
    )
    c = RecipeIngredient(
        id=uuid4(),
        recipe_id=uuid4(),
        ingredient_id=uuid4(),
        quantity=Decimal("1"),
        unit="tsp",
        raw_text="1 tsp salt",
        position=2,
        alternate_group_id=None,
    )
    chosen = select_lines_for_estimation([b, c, a])
    assert [line.position for line in chosen] == [0, 2]


def test_apply_printed_nutrition_metadata() -> None:
    recipe = Recipe(
        cookbook_id=uuid4(),
        title="Printed",
        servings=Decimal("4"),
        calories=Decimal("250"),
        protein_grams=Decimal("10"),
        carbs_grams=None,
        fat_grams=None,
        tags=[],
        steps=[],
        parse_warnings=[],
    )
    apply_printed_nutrition_metadata(recipe)
    assert recipe.nutrition_source == NutritionSource.printed
    assert recipe.nutrition_basis == NutritionBasis.per_serving
    assert recipe.nutrition_coverage == Decimal("1")


@pytest.mark.asyncio
async def test_estimate_recipe_nutrition_from_seed() -> None:
    async with SessionLocal() as db:
        user = User(email="nutrition@example.com", password_hash="x")
        db.add(user)
        await db.flush()
        cookbook = Cookbook(
            user_id=user.id,
            title="Test Book",
            original_filename="test.txt",
            content_type="text/plain",
            storage_path="/tmp/test.txt",
            status=UploadStatus.completed,
        )
        db.add(cookbook)
        await db.flush()

        milk = Ingredient(name="milk", aliases=[], staple=False)
        flour = Ingredient(name="all-purpose flour", aliases=[], staple=False)
        salt = Ingredient(name="salt", aliases=[], staple=True)
        db.add_all([milk, flour, salt])
        await db.flush()

        recipe = Recipe(
            cookbook_id=cookbook.id,
            title="Simple dough",
            servings=Decimal("2"),
            tags=[],
            steps=["mix"],
            parse_warnings=[],
        )
        db.add(recipe)
        await db.flush()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=flour.id,
                    quantity=Decimal("1"),
                    unit="cup",
                    raw_text="1 cup flour",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=milk.id,
                    quantity=Decimal("1"),
                    unit="cup",
                    raw_text="1 cup milk",
                    position=1,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=salt.id,
                    quantity=None,
                    unit=None,
                    raw_text="salt to taste",
                    position=2,
                ),
            ]
        )
        await db.commit()

        loaded = (
            await db.scalars(
                select(Recipe)
                .where(Recipe.id == recipe.id)
                .options(
                    selectinload(Recipe.recipe_ingredients).selectinload(
                        RecipeIngredient.ingredient
                    )
                )
            )
        ).one()
        result = await estimate_recipe_nutrition(db, loaded, client=FdcClient(api_key=None))
        await db.commit()

        assert result is not None
        assert result.basis == NutritionBasis.per_serving
        assert result.matched_lines == 2
        assert loaded.nutrition_source == NutritionSource.estimated
        assert loaded.calories is not None and loaded.calories > 0
        assert loaded.protein_grams is not None and loaded.protein_grams > 0


@pytest.mark.asyncio
async def test_skips_printed_nutrition() -> None:
    async with SessionLocal() as db:
        user = User(email="printed@example.com", password_hash="x")
        db.add(user)
        await db.flush()
        cookbook = Cookbook(
            user_id=user.id,
            title="Book",
            original_filename="t.txt",
            content_type="text/plain",
            storage_path="/tmp/t.txt",
            status=UploadStatus.completed,
        )
        db.add(cookbook)
        await db.flush()
        milk = Ingredient(name="milk", aliases=[], staple=False)
        db.add(milk)
        await db.flush()
        recipe = Recipe(
            cookbook_id=cookbook.id,
            title="Labeled",
            servings=Decimal("1"),
            calories=Decimal("100"),
            protein_grams=Decimal("5"),
            carbs_grams=Decimal("10"),
            fat_grams=Decimal("2"),
            nutrition_source=NutritionSource.printed,
            nutrition_basis=NutritionBasis.per_serving,
            nutrition_coverage=Decimal("1"),
            tags=[],
            steps=[],
            parse_warnings=[],
        )
        db.add(recipe)
        await db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=milk.id,
                quantity=Decimal("1"),
                unit="cup",
                raw_text="1 cup milk",
                position=0,
            )
        )
        await db.commit()

        loaded = (
            await db.scalars(
                select(Recipe)
                .where(Recipe.id == recipe.id)
                .options(
                    selectinload(Recipe.recipe_ingredients).selectinload(
                        RecipeIngredient.ingredient
                    )
                )
            )
        ).one()
        result = await estimate_recipe_nutrition(db, loaded, client=FdcClient(api_key=None))
        assert result is None
        assert loaded.calories == Decimal("100")


@pytest.mark.asyncio
async def test_food_nutrition_cache_avoids_repeat_lookups() -> None:
    async with SessionLocal() as db:
        inserted = await seed_food_nutrition_cache(db)
        assert inserted >= 50
        # Second seed should insert nothing.
        assert await seed_food_nutrition_cache(db) == 0

        macros, hit = await get_cached_macros(db, "milk")
        assert hit is True
        assert macros is not None
        assert macros.calories_per_100g > 0

        # Negative cache: miss should stick without calling USDA.
        await put_cached_macros(db, "unicorn meat", None, source="miss")
        miss, miss_hit = await get_cached_macros(db, "unicorn meat")
        assert miss_hit is True
        assert miss is None

        ingredient = Ingredient(name="milk", aliases=[], staple=False)
        db.add(ingredient)
        await db.flush()
        resolved = await ensure_ingredient_macros(db, ingredient, FdcClient(api_key=None))
        assert resolved is not None
        assert ingredient.calories_per_100g == resolved.calories_per_100g

        cached_rows = list(await db.scalars(select(FoodNutritionCache).limit(5)))
        assert cached_rows
        await db.commit()


@pytest.mark.asyncio
async def test_shared_cache_fills_second_ingredient_without_api() -> None:
    async with SessionLocal() as db:
        await put_cached_macros(
            db,
            "exotic spice blend",
            FoodMacros(
                fdc_id=999001,
                description="Exotic spice blend",
                calories_per_100g=Decimal("250"),
                protein_per_100g=Decimal("5"),
                carbs_per_100g=Decimal("40"),
                fat_per_100g=Decimal("8"),
                source="fdc",
            ),
            source="fdc",
        )
        a = Ingredient(name="exotic spice blend", aliases=[], staple=False)
        b = Ingredient(name="Exotic Spice Blend", aliases=[], staple=False)
        db.add_all([a, b])
        await db.flush()

        client = FdcClient(api_key=None)  # would fail without cache
        first = await ensure_ingredient_macros(db, a, client)
        second = await ensure_ingredient_macros(db, b, client)
        assert first is not None and second is not None
        assert first.calories_per_100g == Decimal("250")
        assert second.calories_per_100g == Decimal("250")
        await db.commit()
