import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    Cookbook,
    Ingredient,
    PantryItem,
    Recipe,
    RecipeIngredient,
    UploadStatus,
    User,
)


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "unlocks@example.com", "password": "password-123"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_suggestions_rank_unlocks_and_respect_pantry_and_cookbooks(
    client: AsyncClient,
) -> None:
    headers = await _auth_headers(client)

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "unlocks@example.com"))
        assert user is not None
        enabled = Cookbook(
            user_id=user.id,
            title="Enabled",
            original_filename="enabled.pdf",
            content_type="application/pdf",
            storage_path="/tmp/enabled.pdf",
            status=UploadStatus.completed,
        )
        disabled = Cookbook(
            user_id=user.id,
            title="Disabled",
            original_filename="disabled.pdf",
            content_type="application/pdf",
            storage_path="/tmp/disabled.pdf",
            status=UploadStatus.completed,
            enabled=False,
        )
        onion = Ingredient(name="onion", category="Produce")
        tomato = Ingredient(name="tomato", category="Produce")
        lime = Ingredient(name="lime", category="Produce")
        yogurt = Ingredient(name="yogurt", category="Dairy")
        sour_cream = Ingredient(name="sour cream", category="Dairy")
        carrot = Ingredient(name="carrot", category="Produce")
        salt = Ingredient(name="salt", staple=True)
        db.add_all(
            [enabled, disabled, onion, tomato, lime, yogurt, sour_cream, carrot, salt]
        )
        await db.flush()

        recipes = [
            Recipe(cookbook_id=enabled.id, title="Onion Toast"),
            Recipe(cookbook_id=enabled.id, title="Onion Soup"),
            Recipe(cookbook_id=enabled.id, title="Tomato Salad"),
            Recipe(cookbook_id=enabled.id, title="Salsa"),
            Recipe(cookbook_id=enabled.id, title="Creamy Dip"),
            Recipe(cookbook_id=disabled.id, title="Carrot Cake"),
        ]
        db.add_all(recipes)
        await db.flush()
        alternate_group = uuid.uuid4()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipes[0].id,
                    ingredient_id=onion.id,
                    quantity=1,
                    unit="piece",
                    raw_text="1 onion",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipes[0].id,
                    ingredient_id=salt.id,
                    raw_text="salt",
                    position=1,
                ),
                RecipeIngredient(
                    recipe_id=recipes[1].id,
                    ingredient_id=onion.id,
                    quantity=1,
                    unit="piece",
                    raw_text="1 onion",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipes[2].id,
                    ingredient_id=tomato.id,
                    quantity=2,
                    unit="pieces",
                    raw_text="2 tomatoes",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipes[3].id,
                    ingredient_id=tomato.id,
                    quantity=3,
                    unit="pieces",
                    raw_text="3 tomatoes",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipes[3].id,
                    ingredient_id=lime.id,
                    quantity=1,
                    unit="piece",
                    raw_text="1 lime",
                    position=1,
                ),
                RecipeIngredient(
                    recipe_id=recipes[4].id,
                    ingredient_id=yogurt.id,
                    quantity=1,
                    unit="cup",
                    raw_text="1 cup yogurt or sour cream",
                    position=0,
                    alternate_group_id=alternate_group,
                ),
                RecipeIngredient(
                    recipe_id=recipes[4].id,
                    ingredient_id=sour_cream.id,
                    quantity=1,
                    unit="cup",
                    raw_text="1 cup yogurt or sour cream",
                    position=1,
                    alternate_group_id=alternate_group,
                ),
                RecipeIngredient(
                    recipe_id=recipes[5].id,
                    ingredient_id=carrot.id,
                    quantity=2,
                    unit="cups",
                    raw_text="2 cups carrots",
                    position=0,
                ),
                PantryItem(
                    user_id=user.id,
                    ingredient_id=tomato.id,
                    quantity=1,
                    unit="piece",
                ),
            ]
        )
        await db.commit()

    response = await client.get("/api/v1/pantry/suggestions", headers=headers)
    assert response.status_code == 200
    suggestions = response.json()
    by_name = {item["name"]: item for item in suggestions}

    assert suggestions[0]["name"] == "onion"
    assert by_name["onion"]["unlock_count"] == 2
    assert by_name["tomato"]["unlock_count"] == 1
    assert by_name["tomato"]["near_unlock_count"] == 1
    assert by_name["tomato"]["status"] == "insufficient"
    assert by_name["tomato"]["pantry_item_id"] is not None
    assert by_name["lime"]["unlock_count"] == 0
    assert by_name["lime"]["near_unlock_count"] == 1
    assert by_name["yogurt"]["unlock_count"] == 1
    assert by_name["sour cream"]["unlock_count"] == 1
    assert "salt" not in by_name
    assert "carrot" not in by_name
    assert [recipe["title"] for recipe in by_name["onion"]["unlocked_recipes"]] == [
        "Onion Soup",
        "Onion Toast",
    ]


@pytest.mark.asyncio
async def test_sufficient_pantry_items_are_not_suggested(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "unlocks@example.com"))
        assert user is not None
        cookbook = Cookbook(
            user_id=user.id,
            title="Makeable",
            original_filename="makeable.pdf",
            content_type="application/pdf",
            storage_path="/tmp/makeable.pdf",
            status=UploadStatus.completed,
        )
        onion = Ingredient(name="onion")
        db.add_all([cookbook, onion])
        await db.flush()
        recipe = Recipe(cookbook_id=cookbook.id, title="Onion Dish")
        db.add(recipe)
        await db.flush()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=onion.id,
                    quantity=1,
                    unit="piece",
                    raw_text="1 onion",
                    position=0,
                ),
                PantryItem(
                    user_id=user.id,
                    ingredient_id=onion.id,
                    quantity=2,
                    unit="pieces",
                ),
            ]
        )
        await db.commit()

    response = await client.get("/api/v1/pantry/suggestions", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_unlock_sets_find_complementary_pair_and_exclude_bad_data(
    client: AsyncClient,
) -> None:
    headers = await _auth_headers(client)
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "unlocks@example.com"))
        assert user is not None
        cookbook = Cookbook(
            user_id=user.id,
            title="Pairings",
            original_filename="pairings.pdf",
            content_type="application/pdf",
            storage_path="/tmp/pairings.pdf",
            status=UploadStatus.completed,
        )
        veal = Ingredient(name="veal")
        marsala = Ingredient(name="marsala")
        onion = Ingredient(name="onion")
        garlic = Ingredient(name="garlic")
        bad = Ingredient(name="choice")
        db.add_all([cookbook, veal, marsala, onion, garlic, bad])
        await db.flush()

        recipes = [
            Recipe(cookbook_id=cookbook.id, title=f"Veal Marsala {index}")
            for index in range(3)
        ]
        recipes.extend(
            [
                Recipe(cookbook_id=cookbook.id, title="Onion Dish"),
                Recipe(cookbook_id=cookbook.id, title="Garlic Dish"),
                Recipe(cookbook_id=cookbook.id, title="Broken Recipe"),
            ]
        )
        db.add_all(recipes)
        await db.flush()
        for recipe in recipes[:3]:
            db.add_all(
                [
                    RecipeIngredient(
                        recipe_id=recipe.id,
                        ingredient_id=veal.id,
                        raw_text="1 pound veal",
                        position=0,
                    ),
                    RecipeIngredient(
                        recipe_id=recipe.id,
                        ingredient_id=marsala.id,
                        raw_text="1/2 cup marsala",
                        position=1,
                    ),
                ]
            )
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipes[3].id,
                    ingredient_id=onion.id,
                    raw_text="1 onion",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipes[4].id,
                    ingredient_id=garlic.id,
                    raw_text="1 garlic clove",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipes[5].id,
                    ingredient_id=bad.id,
                    raw_text="choice",
                    position=0,
                ),
            ]
        )
        await db.commit()

    response = await client.get(
        "/api/v1/pantry/unlock-sets?size=2&limit=10",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quality_excluded_recipe_count"] == 1
    best = body["items"][0]
    assert {item["name"] for item in best["ingredients"]} == {"veal", "marsala"}
    assert best["unlock_count"] == 3
    assert best["synergy_count"] == 3
    assert best["incremental_count"] == 3
