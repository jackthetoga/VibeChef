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


@pytest.mark.asyncio
async def test_or_alternate_group_uses_any_matching(client: AsyncClient) -> None:
    import uuid

    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "or-match@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "or-match@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="OR Recipes",
            original_filename="or.pdf",
            content_type="application/pdf",
            storage_path="/tmp/or.pdf",
        )
        plum = Ingredient(name="plum tomatoes")
        canned = Ingredient(name="canned tomatoes")
        oil = Ingredient(name="olive oil", staple=True)
        db.add_all([cookbook, plum, canned, oil])
        await db.flush()
        plum.canonical_id = plum.id
        canned.canonical_id = canned.id
        oil.canonical_id = oil.id

        recipe = Recipe(cookbook_id=cookbook.id, title="Marinara")
        db.add(recipe)
        await db.flush()
        group_id = uuid.uuid4()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=plum.id,
                    quantity=2,
                    unit="pounds",
                    raw_text="2 pounds plum tomatoes or 3 cups canned tomatoes",
                    position=0,
                    alternate_group_id=group_id,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=canned.id,
                    quantity=3,
                    unit="cups",
                    raw_text="2 pounds plum tomatoes or 3 cups canned tomatoes",
                    position=1,
                    alternate_group_id=group_id,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=oil.id,
                    quantity=3,
                    unit="tablespoons",
                    raw_text="3 tablespoons olive oil",
                    position=2,
                ),
            ]
        )
        await db.commit()
        canned_id = canned.id
        recipe_id = recipe.id

    before = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert before.status_code == 200
    assert before.json()["missing_count"] == 1
    assert len(before.json()["ingredients"]) == 2
    assert " or " in before.json()["ingredients"][0]["name"]

    pantry = await client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"ingredient_id": str(canned_id), "quantity": 3, "unit": "cups"},
    )
    assert pantry.status_code == 201

    after = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert after.status_code == 200
    assert after.json()["missing_count"] == 0
    assert after.json()["ingredients"][0]["match_status"] == "available"


@pytest.mark.asyncio
async def test_unitless_carrot_matches_pantry_weight(client: AsyncClient) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "carrot@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "carrot@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Carrot Book",
            original_filename="carrot.pdf",
            content_type="application/pdf",
            storage_path="/tmp/carrot.pdf",
        )
        carrot = Ingredient(name="carrot")
        db.add_all([cookbook, carrot])
        await db.flush()
        carrot.canonical_id = carrot.id
        recipe = Recipe(cookbook_id=cookbook.id, title="Simple Carrot")
        db.add(recipe)
        await db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=carrot.id,
                quantity=1,
                unit=None,
                raw_text="1 carrot",
                position=0,
            )
        )
        await db.commit()
        carrot_id = carrot.id
        recipe_id = recipe.id

    pantry = await client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"ingredient_id": str(carrot_id), "quantity": 0.7, "unit": "lbs"},
    )
    assert pantry.status_code == 201

    detail = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["missing_count"] == 0
    assert detail.json()["ingredients"][0]["match_status"] == "available"


@pytest.mark.asyncio
async def test_lemon_zest_matches_pantry_lemon(client: AsyncClient) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "zest@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "zest@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Zest Book",
            original_filename="zest.pdf",
            content_type="application/pdf",
            storage_path="/tmp/zest.pdf",
        )
        zest = Ingredient(name="lemon zest")
        lemon = Ingredient(name="lemon")
        db.add_all([cookbook, zest, lemon])
        await db.flush()
        zest.canonical_id = zest.id
        lemon.canonical_id = lemon.id
        recipe = Recipe(cookbook_id=cookbook.id, title="Zesty Pasta")
        db.add(recipe)
        await db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=zest.id,
                quantity=1,
                unit="tsp",
                raw_text="1 teaspoon lemon zest",
                position=0,
            )
        )
        await db.commit()
        lemon_id = lemon.id
        recipe_id = recipe.id

    before = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert before.status_code == 200
    assert before.json()["missing_count"] == 1

    pantry = await client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"ingredient_id": str(lemon_id), "quantity": 2, "unit": "pieces"},
    )
    assert pantry.status_code == 201

    after = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert after.status_code == 200
    assert after.json()["missing_count"] == 0
    ingredient = after.json()["ingredients"][0]
    assert ingredient["match_status"] == "available"
    assert ingredient["matched_via"] == "lemon"


@pytest.mark.asyncio
async def test_water_and_pan_are_treated_as_staples(client: AsyncClient) -> None:
    from app.services.staples import is_staple_name

    assert is_staple_name("water")
    assert is_staple_name("large pot")
    assert is_staple_name("frying pan")
    assert not is_staple_name("carrots")

    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "staple2@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "staple2@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Staple Book",
            original_filename="staple.pdf",
            content_type="application/pdf",
            storage_path="/tmp/staple.pdf",
        )
        water = Ingredient(name="water", staple=True)
        pot = Ingredient(name="large pot", staple=True)
        onion = Ingredient(name="onion", staple=False)
        db.add_all([cookbook, water, pot, onion])
        await db.flush()
        for item in (water, pot, onion):
            item.canonical_id = item.id
        recipe = Recipe(cookbook_id=cookbook.id, title="Boil Onion")
        db.add(recipe)
        await db.flush()
        db.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=water.id,
                    raw_text="water",
                    position=0,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=pot.id,
                    raw_text="1 large pot",
                    position=1,
                ),
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=onion.id,
                    quantity=1,
                    raw_text="1 onion",
                    position=2,
                ),
            ]
        )
        await db.commit()
        recipe_id = recipe.id

    detail = await client.get(f"/api/v1/recipes/{recipe_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["missing_count"] == 1
    by_name = {row["name"]: row for row in detail.json()["ingredients"]}
    assert by_name["water"]["match_status"] == "staple"
    assert by_name["large pot"]["match_status"] == "staple"
    assert by_name["onion"]["match_status"] == "missing"
