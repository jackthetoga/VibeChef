from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, case, func, or_
from sqlalchemy.sql.elements import ColumnElement

from app.services.ingredient_conversions import (
    CONVERSION_BY_NAME,
    INGREDIENT_CONVERSIONS,
    IngredientConversion,
    get_ingredient_conversion,
)

CUP_MILLILITERS = Decimal("236.5882365")

@dataclass(frozen=True)
class UnitDefinition:
    dimension: str
    factor: Decimal


def _aliases(
    dimension: str, factor: str, *names: str
) -> dict[str, UnitDefinition]:
    definition = UnitDefinition(dimension=dimension, factor=Decimal(factor))
    return {name: definition for name in names}


UNIT_DEFINITIONS = {
    **_aliases("mass", "0.001", "mg", "milligram", "milligrams"),
    **_aliases("mass", "1", "g", "gram", "grams"),
    **_aliases("mass", "1000", "kg", "kilogram", "kilograms"),
    **_aliases("mass", "28.349523125", "oz", "ounce", "ounces"),
    **_aliases("mass", "453.59237", "lb", "lbs", "pound", "pounds"),
    **_aliases("volume", "1", "ml", "milliliter", "milliliters", "millilitre", "millilitres"),
    **_aliases("volume", "1000", "l", "liter", "liters", "litre", "litres"),
    **_aliases("volume", "4.92892159375", "tsp", "teaspoon", "teaspoons"),
    **_aliases("volume", "14.78676478125", "tbsp", "tablespoon", "tablespoons"),
    **_aliases("volume", "29.5735295625", "fl oz", "fluid ounce", "fluid ounces"),
    **_aliases("volume", "236.5882365", "cup", "cups"),
    **_aliases("volume", "473.176473", "pt", "pint", "pints"),
    **_aliases("volume", "946.352946", "qt", "quart", "quarts"),
    **_aliases("volume", "3785.411784", "gal", "gallon", "gallons"),
    **_aliases("count", "1", "piece", "pieces", "item", "items", "count", "whole"),
    **_aliases("clove", "1", "clove", "cloves"),
    **_aliases("can", "1", "can", "cans"),
    **_aliases("bunch", "1", "bunch", "bunches"),
    **_aliases("package", "1", "package", "packages", "packet", "packets"),
}


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    normalized = " ".join(unit.lower().replace(".", "").strip().split())
    return normalized or None


def compare_quantities(
    available_quantity: Decimal | None,
    available_unit: str | None,
    required_quantity: Decimal | None,
    required_unit: str | None,
    ingredient_name: str | None = None,
) -> bool | None:
    """Return sufficiency when it can be determined, otherwise None."""
    if required_quantity is None or available_quantity is None:
        return None

    available_name = normalize_unit(available_unit)
    required_name = normalize_unit(required_unit)
    profile = get_ingredient_conversion(ingredient_name)

    # "1 carrot" (unitless) vs "0.7 lbs carrots" — treat missing unit as count
    # when we know a typical item weight.
    if profile is not None and profile.grams_per_item is not None:
        if available_name is None and required_name is not None:
            available_name = "piece"
        if required_name is None and available_name is not None:
            required_name = "piece"

    if available_name == required_name:
        return available_quantity >= required_quantity
    if not available_name or not required_name:
        return None

    available = UNIT_DEFINITIONS.get(available_name)
    required = UNIT_DEFINITIONS.get(required_name)
    if not available or not required:
        return None
    if available.dimension == required.dimension:
        return available_quantity * available.factor >= required_quantity * required.factor

    if not profile:
        return None
    available_grams = quantity_in_grams(available_quantity, available, profile)
    required_grams = quantity_in_grams(required_quantity, required, profile)
    if available_grams is None or required_grams is None:
        return None
    return available_grams >= required_grams


def quantity_in_grams(
    quantity: Decimal,
    unit: UnitDefinition,
    profile: IngredientConversion,
) -> Decimal | None:
    if unit.dimension == "mass":
        return quantity * unit.factor
    if unit.dimension == "volume":
        return quantity * unit.factor * profile.grams_per_cup / CUP_MILLILITERS
    if unit.dimension == "count" and profile.grams_per_item is not None:
        return quantity * profile.grams_per_item
    if unit.dimension == "clove" and profile.grams_per_clove is not None:
        return quantity * profile.grams_per_clove
    return None


def ingredient_conversion_for_units(
    available_unit: str | None,
    required_unit: str | None,
    ingredient_name: str | None,
) -> IngredientConversion | None:
    available_name = normalize_unit(available_unit)
    required_name = normalize_unit(required_unit)
    profile = get_ingredient_conversion(ingredient_name)
    if profile is not None and profile.grams_per_item is not None:
        if available_name is None and required_name is not None:
            available_name = "piece"
        if required_name is None and available_name is not None:
            required_name = "piece"
    available = UNIT_DEFINITIONS.get(available_name or "")
    required = UNIT_DEFINITIONS.get(required_name or "")
    if not available or not required or not profile or available.dimension == required.dimension:
        return None
    if (
        quantity_in_grams(Decimal(1), available, profile) is None
        or quantity_in_grams(Decimal(1), required, profile) is None
    ):
        return None
    return profile


def normalized_unit_expression(column: ColumnElement[str]) -> ColumnElement[str]:
    return func.lower(func.trim(func.replace(column, ".", "")))


def unit_dimension_expression(column: ColumnElement[str]) -> ColumnElement[str | None]:
    normalized = normalized_unit_expression(column)
    dimensions: dict[str, list[str]] = {}
    for name, definition in UNIT_DEFINITIONS.items():
        dimensions.setdefault(definition.dimension, []).append(name)
    return case(
        *((normalized.in_(names), dimension) for dimension, names in dimensions.items()),
        else_=None,
    )


def unit_factor_expression(column: ColumnElement[str]) -> ColumnElement[Decimal | None]:
    normalized = normalized_unit_expression(column)
    factors: dict[Decimal, list[str]] = {}
    for name, definition in UNIT_DEFINITIONS.items():
        factors.setdefault(definition.factor, []).append(name)
    return case(
        *((normalized.in_(names), factor) for factor, names in factors.items()),
        else_=None,
    )


def ingredient_density_expression(
    ingredient_name: ColumnElement[str],
) -> ColumnElement[Decimal | None]:
    normalized = func.lower(func.trim(ingredient_name))
    densities: dict[Decimal, list[str]] = {}
    for name, profile in CONVERSION_BY_NAME.items():
        density = profile.grams_per_cup / CUP_MILLILITERS
        densities.setdefault(density, []).append(name)
    return case(
        *((normalized.in_(names), density) for density, names in densities.items()),
        else_=None,
    )


def ingredient_unit_grams_expression(
    ingredient_name: ColumnElement[str],
    unit: ColumnElement[str],
) -> ColumnElement[Decimal | None]:
    normalized_name = func.lower(func.trim(ingredient_name))
    unit_dimension = unit_dimension_expression(unit)
    item_cases = []
    clove_cases = []
    for profile in INGREDIENT_CONVERSIONS:
        names = (profile.name, *profile.aliases)
        if profile.grams_per_item is not None:
            item_cases.append((normalized_name.in_(names), profile.grams_per_item))
        if profile.grams_per_clove is not None:
            clove_cases.append((normalized_name.in_(names), profile.grams_per_clove))
    item_grams = case(*item_cases, else_=None)
    clove_grams = case(*clove_cases, else_=None)
    # Unitless recipe lines ("1 carrot") count as pieces when item weight is known.
    count_like = or_(unit_dimension == "count", unit.is_(None))
    return case(
        (count_like, item_grams),
        (unit_dimension == "clove", clove_grams),
        else_=None,
    )


def quantity_in_grams_expression(
    quantity: ColumnElement[Decimal],
    unit: ColumnElement[str],
    ingredient_name: ColumnElement[str],
) -> ColumnElement[Decimal | None]:
    dimension = unit_dimension_expression(unit)
    factor = unit_factor_expression(unit)
    density = ingredient_density_expression(ingredient_name)
    item_grams = ingredient_unit_grams_expression(ingredient_name, unit)
    return case(
        (dimension == "mass", quantity * factor),
        (
            and_(dimension == "volume", density.is_not(None)),
            quantity * factor * density,
        ),
        (item_grams.is_not(None), quantity * item_grams),
        else_=None,
    )
