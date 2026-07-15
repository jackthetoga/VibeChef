from app.services.derivatives import parent_food_name, parent_name_candidates
from app.services.staples import is_equipment_name, is_staple_name


def test_parent_food_name_for_zest_peel_juice() -> None:
    assert parent_food_name("lemon zest") == "lemon"
    assert parent_food_name("orange peel") == "orange"
    assert parent_food_name("lime rind") == "lime"
    assert parent_food_name("lemon juice") == "lemon"
    assert parent_food_name("fresh lime juice") == "lime"
    assert parent_food_name("freshly squeezed lemon juice") == "lemon"
    assert parent_food_name("grated lemon peel") == "lemon"
    assert parent_food_name("zest of a lemon") == "lemon"
    assert parent_food_name("garlic powder") is None
    assert parent_food_name("coconut milk") is None
    assert parent_food_name("apple juice") is None
    assert parent_food_name("pork rind") is None
    assert parent_food_name("pineapple chunks in juice") is None
    assert parent_food_name("cucumber with peel") is None
    assert parent_name_candidates("lemon zest") == ["lemon", "lemons"]


def test_staple_names_include_water_and_cookware() -> None:
    assert is_staple_name("water")
    assert is_staple_name("boiling water")
    assert is_staple_name("olive oil")
    assert is_equipment_name("large pot")
    assert is_staple_name("frying pan")
    assert is_staple_name("mixing bowl")
    assert not is_staple_name("carrots")
    assert not is_staple_name("chicken stock")
    assert not is_staple_name("pan-frying beef steaks")
    assert not is_staple_name("grilled bread")
    assert not is_staple_name("cornstarch in a 1 quart bowl")
    assert not is_equipment_name("pan-frying beef steaks")
