from decimal import Decimal

import pytest

from app.services.common_ingredients import COMMON_INGREDIENTS
from app.services.ingredient_conversions import (
    INGREDIENT_CONVERSIONS,
    get_ingredient_conversion,
)
from app.services.units import compare_quantities, normalize_unit


@pytest.mark.parametrize(
    ("available_quantity", "available_unit", "required_quantity", "required_unit", "expected"),
    [
        ("16", "oz", "1", "lb", True),
        ("8", "oz", "1", "lb", False),
        ("1", "cup", "16", "tbsp", True),
        ("500", "ml", "2", "cups", True),
        ("2", "kg", "1500", "g", True),
        ("1", "can", "2", "cans", False),
        ("1", "cup", "8", "oz", None),
        ("1", None, "2", None, False),
        (None, "oz", "1", "lb", None),
    ],
)
def test_compare_quantities(
    available_quantity: str | None,
    available_unit: str | None,
    required_quantity: str,
    required_unit: str | None,
    expected: bool | None,
) -> None:
    available = Decimal(available_quantity) if available_quantity is not None else None
    assert (
        compare_quantities(available, available_unit, Decimal(required_quantity), required_unit)
        is expected
    )


def test_normalize_unit_handles_case_spacing_and_periods() -> None:
    assert normalize_unit(" FL.  OZ ") == "fl oz"


def test_ingredient_density_converts_volume_to_mass() -> None:
    assert compare_quantities(
        Decimal("1"),
        "cup",
        Decimal("4"),
        "oz",
        "all-purpose flour",
    )
    assert not compare_quantities(
        Decimal("3"),
        "oz",
        Decimal("1"),
        "cup",
        "flour",
    )


def test_ingredient_piece_weights_convert_count_to_mass() -> None:
    assert compare_quantities(
        Decimal("2"),
        "pieces",
        Decimal("95"),
        "g",
        "eggs",
    )
    assert not compare_quantities(
        Decimal("1"),
        "whole",
        Decimal("2"),
        "oz",
        "egg",
    )


def test_unitless_count_converts_to_mass_using_item_weight() -> None:
    """Recipe '1 carrot' (no unit) should be satisfied by ~0.7 lb carrots in pantry."""
    assert compare_quantities(
        Decimal("0.7"),
        "lbs",
        Decimal("1"),
        None,
        "carrot",
    )
    assert compare_quantities(
        Decimal("0.7"),
        "lb",
        Decimal("1"),
        None,
        "carrots",
    )
    # Far too little mass for even one carrot (~61g).
    assert not compare_quantities(
        Decimal("0.05"),
        "lb",
        Decimal("1"),
        None,
        "carrot",
    )


def test_all_common_ingredients_have_sourced_conversion_profiles() -> None:
    common_names = {item.name for item in COMMON_INGREDIENTS}
    profile_names = {profile.name for profile in INGREDIENT_CONVERSIONS}
    assert profile_names == common_names
    for name in common_names:
        profile = get_ingredient_conversion(name)
        assert profile is not None
        assert profile.grams_per_cup > 0
        assert profile.basis
        assert profile.source
        assert profile.source_url.startswith("https://")
