from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Cookbook, Ingredient, PantryItem, Recipe, RecipeIngredient, User


@pytest.mark.asyncio
async def test_cook_recipe_subtracts_default_quantities(client: AsyncClient) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "made-this@example.com", "password": "password-123"},
    )
    token = registration.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "made-this@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Weeknight",
            original_filename="weeknight.pdf",
            content_type="application/pdf",
            storage_path=str(Path("/tmp/weeknight.pdf")),
        )
        onion = Ingredient(name="onion")
        garlic = Ingredient(name="garlic")
        salt = Ingredient(name="salt", staple=True)
        db.add_all([cookbook, onion, garlic, salt])
        await db.flush()
        recipe = Recipe(
            cookbook_id=cookbook.id,
            title="Garlic Onion Skillet",
            total_minutes=20,
        )
        db.add(recipe)
        await db.flush()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=onion.id,
                    quantity=2,
                    unit="cups",
                    raw_text="2 cups onion",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=garlic.id,
                    quantity=3,
                    unit="cloves",
                    raw_text="3 cloves garlic",
                    position=1,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=salt.id,
                    raw_text="salt",
                    position=2,
                ),
            ]
        )
        db.add_all(
            [
                PantryItem(
                    user_id=user.id,
                    ingredient_id=onion.id,
                    quantity=5,
                    unit="cups",
                ),
                PantryItem(
                    user_id=user.id,
                    ingredient_id=garlic.id,
                    quantity=3,
                    unit="cloves",
                ),
            ]
        )
        await db.commit()
        recipe_id = recipe.id
        onion_id = onion.id
        garlic_id = garlic.id

    cooked = await client.post(f"/api/v1/recipes/{recipe_id}/cook", headers=headers, json={})
    assert cooked.status_code == 200
    body = cooked.json()
    assert set(body["removed"]) == {"garlic"}
    assert len(body["updated"]) == 1
    assert body["updated"][0]["ingredient"]["name"] == "onion"
    assert body["updated"][0]["quantity"] == "3.000"
    assert body["skipped"] == []

    pantry = await client.get("/api/v1/pantry", headers=headers)
    assert pantry.status_code == 200
    names = {item["ingredient"]["name"] for item in pantry.json()}
    assert names == {"onion"}
    onion_item = next(item for item in pantry.json() if item["ingredient"]["id"] == str(onion_id))
    assert onion_item["quantity"] == "3.000"
    assert str(garlic_id) not in {item["ingredient"]["id"] for item in pantry.json()}


@pytest.mark.asyncio
async def test_cook_recipe_review_overrides_and_skips_unchecked(
    client: AsyncClient,
) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "review-cook@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "review-cook@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Review Book",
            original_filename="review.pdf",
            content_type="application/pdf",
            storage_path="/tmp/review.pdf",
        )
        tomato = Ingredient(name="tomato")
        basil = Ingredient(name="basil")
        db.add_all([cookbook, tomato, basil])
        await db.flush()
        recipe = Recipe(cookbook_id=cookbook.id, title="Tomato Basil")
        db.add(recipe)
        await db.flush()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=tomato.id,
                    quantity=4,
                    unit="cups",
                    raw_text="4 cups tomato",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=basil.id,
                    quantity=1,
                    unit="cups",
                    raw_text="1 cup basil",
                    position=1,
                ),
            ]
        )
        db.add_all(
            [
                PantryItem(user_id=user.id, ingredient_id=tomato.id, quantity=10, unit="cups"),
                PantryItem(user_id=user.id, ingredient_id=basil.id, quantity=2, unit="cups"),
            ]
        )
        await db.commit()
        recipe_id = recipe.id
        tomato_id = tomato.id

    cooked = await client.post(
        f"/api/v1/recipes/{recipe_id}/cook",
        headers=headers,
        json={
            "items": [
                {"ingredient_id": str(tomato_id), "quantity": 1.5, "unit": "cups"},
            ]
        },
    )
    assert cooked.status_code == 200
    body = cooked.json()
    assert body["removed"] == []
    assert len(body["updated"]) == 1
    assert body["updated"][0]["quantity"] == "8.500"
    assert body["skipped"] == []

    pantry = await client.get("/api/v1/pantry", headers=headers)
    items = {item["ingredient"]["name"]: item for item in pantry.json()}
    assert items["tomato"]["quantity"] == "8.500"
    assert items["basil"]["quantity"] == "2.000"


@pytest.mark.asyncio
async def test_cook_recipe_rejects_empty_review_list(client: AsyncClient) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "empty-cook@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "empty-cook@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Empty",
            original_filename="empty.pdf",
            content_type="application/pdf",
            storage_path="/tmp/empty.pdf",
        )
        onion = Ingredient(name="yellow onion")
        db.add_all([cookbook, onion])
        await db.flush()
        recipe = Recipe(cookbook_id=cookbook.id, title="Onion Only")
        db.add(recipe)
        await db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=onion.id,
                quantity=1,
                unit="cups",
                raw_text="1 cup onion",
                position=0,
            )
        )
        await db.commit()
        recipe_id = recipe.id

    response = await client.post(
        f"/api/v1/recipes/{recipe_id}/cook",
        headers=headers,
        json={"items": []},
    )
    assert response.status_code == 422
