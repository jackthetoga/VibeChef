from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.db.session import SessionLocal
from app.models import Ingredient


async def auth_headers(client: AsyncClient) -> dict[str, str]:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "pantry@example.com", "password": "password-123"},
    )
    return {"Authorization": f"Bearer {registration.json()['access_token']}"}


@pytest.mark.asyncio
async def test_common_ingredients_can_be_added_in_bulk_without_duplicates(
    client: AsyncClient,
) -> None:
    headers = await auth_headers(client)
    common = await client.get("/api/v1/ingredients/common", headers=headers)
    assert common.status_code == 200
    assert len(common.json()) == 100
    olive_oil = next(item for item in common.json() if item["name"] == "olive oil")
    assert olive_oil["category"] == "Oils & Condiments"
    assert olive_oil["default_quantity"] == "500"
    assert olive_oil["default_unit"] == "ml"

    conversions = await client.get("/api/v1/ingredients/conversions", headers=headers)
    assert conversions.status_code == 200
    assert len(conversions.json()) == 100
    flour = next(item for item in conversions.json() if item["name"] == "all-purpose flour")
    assert flour["grams_per_cup"] == "120"
    assert flour["basis"] == "spooned and leveled"
    assert flour["source_url"].startswith("https://")

    first = await client.post(
        "/api/v1/pantry/bulk",
        headers=headers,
        json={"ingredient_names": ["olive oil", "salt", "olive oil"]},
    )
    assert first.status_code == 201
    assert len(first.json()["added"]) == 2
    assert first.json()["skipped_existing"] == []
    added_by_name = {
        item["ingredient"]["name"]: item for item in first.json()["added"]
    }
    assert Decimal(added_by_name["olive oil"]["quantity"]) == Decimal("500")
    assert added_by_name["olive oil"]["unit"] == "ml"
    assert Decimal(added_by_name["salt"]["quantity"]) == Decimal("250")
    assert added_by_name["salt"]["unit"] == "g"

    second = await client.post(
        "/api/v1/pantry/bulk",
        headers=headers,
        json={"ingredient_names": ["salt", "black pepper"]},
    )
    assert second.status_code == 201
    assert [item["ingredient"]["name"] for item in second.json()["added"]] == ["black pepper"]
    assert second.json()["skipped_existing"] == ["salt"]

    pantry = await client.get("/api/v1/pantry", headers=headers)
    categories = {
        item["ingredient"]["name"]: item["ingredient"]["category"]
        for item in pantry.json()
    }
    assert categories == {
        "black pepper": "Spices & Seasonings",
        "olive oil": "Oils & Condiments",
        "salt": "Spices & Seasonings",
    }


@pytest.mark.asyncio
async def test_bulk_add_accepts_optional_quantity_overrides(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    response = await client.post(
        "/api/v1/pantry/bulk",
        headers=headers,
        json={
            "items": [
                {"name": "eggs", "quantity": 6, "unit": "pieces"},
                {"name": "milk"},
            ]
        },
    )
    assert response.status_code == 201
    added = {item["ingredient"]["name"]: item for item in response.json()["added"]}
    assert Decimal(added["eggs"]["quantity"]) == Decimal("6")
    assert added["eggs"]["unit"] == "pieces"
    assert Decimal(added["milk"]["quantity"]) == Decimal("1")
    assert added["milk"]["unit"] == "l"


@pytest.mark.asyncio
async def test_manual_add_uses_known_staple_category(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    response = await client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"ingredient_name": "sesame oil", "quantity": 1, "unit": "ml"},
    )
    assert response.status_code == 201
    assert response.json()["ingredient"]["category"] == "Oils & Condiments"


@pytest.mark.asyncio
async def test_pantry_from_text_adds_updates_and_removes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = await auth_headers(client)

    seeded = await client.post(
        "/api/v1/pantry/bulk",
        headers=headers,
        json={
            "items": [
                {"name": "eggs", "quantity": 6, "unit": "pieces"},
                {"name": "spinach", "quantity": 1, "unit": "bunch"},
            ]
        },
    )
    assert seeded.status_code == 201

    response = await client.post(
        "/api/v1/pantry/from-text",
        headers=headers,
        json={
            "text": (
                "Used 2 eggs\n"
                "Bought 3 tomatoes\n"
                "Finished the spinach\n"
                "+ 1 cup milk"
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert {item["name"] for item in body["parsed"]} >= {
        "eggs",
        "tomatoes",
        "spinach",
        "milk",
    }
    assert [item["ingredient"]["name"] for item in body["added"]] == ["tomatoes", "milk"]
    assert body["removed"] == ["spinach"]
    assert body["skipped"] == []
    updated = {item["ingredient"]["name"]: item for item in body["updated"]}
    assert Decimal(updated["eggs"]["quantity"]) == Decimal("4")

    pantry = await client.get("/api/v1/pantry", headers=headers)
    by_name = {item["ingredient"]["name"]: item for item in pantry.json()}
    assert set(by_name) == {"eggs", "tomatoes", "milk"}
    assert Decimal(by_name["eggs"]["quantity"]) == Decimal("4")
    assert Decimal(by_name["tomatoes"]["quantity"]) == Decimal("3")
    assert Decimal(by_name["milk"]["quantity"]) == Decimal("1")
    assert by_name["milk"]["unit"] == "cup"


@pytest.mark.asyncio
async def test_pantry_from_text_skips_unknown_removals(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = await auth_headers(client)
    response = await client.post(
        "/api/v1/pantry/from-text",
        headers=headers,
        json={"text": "Used 1 lemon"},
    )
    assert response.status_code == 200
    assert response.json()["removed"] == []
    assert response.json()["skipped"] == ["lemon"]
    assert response.json()["added"] == []


@pytest.mark.asyncio
async def test_pantry_from_text_rejects_empty_parse(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = await auth_headers(client)
    response = await client.post(
        "/api/v1/pantry/from-text",
        headers=headers,
        json={"text": "hello there"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pantry_confirm_creates_and_updates_quantities(client: AsyncClient) -> None:
    headers = await auth_headers(client)

    created = await client.post(
        "/api/v1/pantry/confirm",
        headers=headers,
        json={
            "items": [
                {"ingredient_name": "tomatoes", "quantity": 3, "unit": "pieces"},
                {"ingredient_name": "milk", "quantity": 1, "unit": "l"},
            ]
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert {item["ingredient"]["name"] for item in body["added"]} == {"tomatoes", "milk"}
    assert body["updated"] == []
    tomatoes = next(
        item for item in body["added"] if item["ingredient"]["name"] == "tomatoes"
    )
    assert Decimal(tomatoes["quantity"]) == Decimal("3")

    updated = await client.post(
        "/api/v1/pantry/confirm",
        headers=headers,
        json={
            "items": [
                {"ingredient_name": "tomatoes", "quantity": 6, "unit": "pieces"},
                {"ingredient_name": "spinach", "quantity": 1, "unit": "bunch"},
            ]
        },
    )
    assert updated.status_code == 200
    update_body = updated.json()
    assert [item["ingredient"]["name"] for item in update_body["added"]] == ["spinach"]
    assert [item["ingredient"]["name"] for item in update_body["updated"]] == ["tomatoes"]
    assert Decimal(update_body["updated"][0]["quantity"]) == Decimal("6")

    pantry = await client.get("/api/v1/pantry", headers=headers)
    by_name = {item["ingredient"]["name"]: item for item in pantry.json()}
    assert set(by_name) == {"tomatoes", "milk", "spinach"}
    assert Decimal(by_name["tomatoes"]["quantity"]) == Decimal("6")
    assert Decimal(by_name["milk"]["quantity"]) == Decimal("1")
    assert by_name["milk"]["unit"] == "l"


@pytest.mark.asyncio
async def test_pantry_scan_rejects_non_images(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = await auth_headers(client)
    response = await client.post(
        "/api/v1/pantry/scan",
        headers=headers,
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_pantry_scan_returns_demo_items_without_api_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    headers = await auth_headers(client)
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    response = await client.post(
        "/api/v1/pantry/scan",
        headers=headers,
        files={"file": ("groceries.jpg", jpeg, "image/jpeg")},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    assert {item["name"] for item in items} >= {"tomatoes", "milk", "eggs"}
    tomatoes = next(item for item in items if item["name"] == "tomatoes")
    assert Decimal(str(tomatoes["quantity"])) == Decimal("3")
    assert tomatoes["unit"] == "pieces"


@pytest.mark.asyncio
async def test_autocomplete_returns_ranked_canonical_roots_only(
    client: AsyncClient,
) -> None:
    headers = await auth_headers(client)
    async with SessionLocal() as db:
        pancetta = Ingredient(
            name="pancetta",
            aliases=["chopped pancetta", "2 tablespoons chopped pancetta"],
        )
        variant = Ingredient(name="2 tablespoons chopped pancetta")
        orphan = Ingredient(name="3 tablespoons diced pancetta or prosciutto")
        db.add_all([pancetta, variant, orphan])
        await db.flush()
        pancetta.canonical_id = pancetta.id
        variant.canonical_id = pancetta.id
        await db.commit()

    generic = await client.get(
        "/api/v1/ingredients?query=pancetta",
        headers=headers,
    )
    assert generic.status_code == 200
    assert [item["name"] for item in generic.json()] == ["pancetta"]

    specific = await client.get(
        "/api/v1/ingredients?query=2%20tablespoons%20chopped%20pancetta",
        headers=headers,
    )
    assert specific.status_code == 200
    assert [item["name"] for item in specific.json()] == ["pancetta"]

