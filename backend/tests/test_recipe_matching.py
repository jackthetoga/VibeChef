from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Cookbook, Ingredient, Recipe, RecipeIngredient, User


@pytest.mark.asyncio
async def test_pantry_changes_missing_count_and_staples_are_excluded(
    client: AsyncClient,
) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "cook@example.com", "password": "password-123"},
    )
    token = registration.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "cook@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Test",
            original_filename="test.pdf",
            content_type="application/pdf",
            storage_path=str(Path("/tmp/test.pdf")),
        )
        onion = Ingredient(name="onion")
        salt = Ingredient(name="salt", staple=True)
        db.add_all([cookbook, onion, salt])
        await db.flush()
        recipe = Recipe(
            cookbook_id=cookbook.id,
            title="Onion Soup",
            total_minutes=30,
            protein_grams=5,
        )
        db.add(recipe)
        await db.flush()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=onion.id,
                    quantity=1,
                    unit="cups",
                    raw_text="1 onion",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=salt.id,
                    raw_text="salt",
                    position=1,
                ),
            ]
        )
        await db.commit()
        onion_id = onion.id
        recipe_id = recipe.id

    before = await client.get("/api/v1/recipes?sort=missing_count&max_missing=1", headers=headers)
    assert before.status_code == 200
    assert before.json()["items"][0]["missing_count"] == 1

    pantry = await client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"ingredient_id": str(onion_id), "quantity": 4, "unit": "oz"},
    )
    assert pantry.status_code == 201

    insufficient = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert insufficient.status_code == 200
    assert insufficient.json()["missing_count"] == 1
    assert insufficient.json()["ingredients"][0]["match_status"] == "insufficient"
    assert insufficient.json()["ingredients"][0]["pantry_quantity"] == "4.000"
    assert insufficient.json()["ingredients"][0]["conversion_basis"] == "fresh, diced"

    updated = await client.patch(
        f"/api/v1/pantry/{pantry.json()['id']}",
        headers=headers,
        json={"quantity": 6, "unit": "oz"},
    )
    assert updated.status_code == 200

    after = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert after.status_code == 200
    assert after.json()["missing_count"] == 0
    assert after.json()["ingredients"][0]["match_status"] == "available"
    assert len(after.json()["recipe_ingredients"]) == 2


@pytest.mark.asyncio
async def test_canonical_variant_matches_pantry_ingredient(
    client: AsyncClient,
) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "oil@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "oil@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Oil Recipes",
            original_filename="oil.pdf",
            content_type="application/pdf",
            storage_path="/tmp/oil.pdf",
        )
        olive_oil = Ingredient(name="olive oil")
        extra_virgin = Ingredient(name="extra virgin olive oil")
        db.add_all([cookbook, olive_oil, extra_virgin])
        await db.flush()
        olive_oil.canonical_id = olive_oil.id
        extra_virgin.canonical_id = olive_oil.id

        recipe = Recipe(cookbook_id=cookbook.id, title="Olive Oil Toast")
        db.add(recipe)
        await db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=extra_virgin.id,
                quantity=1,
                unit="tbsp",
                raw_text="1 tbsp extra virgin olive oil",
                position=0,
            )
        )
        await db.commit()
        olive_oil_id = olive_oil.id
        recipe_id = recipe.id

    before = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert before.status_code == 200
    assert before.json()["missing_count"] == 1

    pantry = await client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"ingredient_id": str(olive_oil_id), "quantity": 2, "unit": "tbsp"},
    )
    assert pantry.status_code == 201

    makeable = await client.get("/api/v1/recipes?makeable=true", headers=headers)
    assert makeable.status_code == 200
    assert makeable.json()["items"][0]["missing_count"] == 0

    detail = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert detail.status_code == 200
    ingredient = detail.json()["ingredients"][0]
    assert detail.json()["missing_count"] == 0
    assert ingredient["match_status"] == "available"
    assert ingredient["matched_via"] == "olive oil"
