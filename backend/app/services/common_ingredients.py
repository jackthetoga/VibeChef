from decimal import Decimal
from typing import NamedTuple


class CommonIngredient(NamedTuple):
    name: str
    category: str
    default_quantity: Decimal
    default_unit: str


INGREDIENT_CATEGORIES = [
    "Oils & Condiments",
    "Spices & Seasonings",
    "Produce",
    "Baking",
    "Dairy & Eggs",
    "Grains & Pasta",
    "Canned Goods",
    "Meat & Seafood",
]


def _q(value: str) -> Decimal:
    return Decimal(value)


COMMON_INGREDIENTS: list[CommonIngredient] = [
    # Existing staples
    CommonIngredient("olive oil", "Oils & Condiments", _q("500"), "ml"),
    CommonIngredient("vegetable oil", "Oils & Condiments", _q("500"), "ml"),
    CommonIngredient("salt", "Spices & Seasonings", _q("250"), "g"),
    CommonIngredient("black pepper", "Spices & Seasonings", _q("50"), "g"),
    CommonIngredient("garlic", "Produce", _q("1"), "whole"),
    CommonIngredient("onions", "Produce", _q("3"), "pieces"),
    CommonIngredient("all-purpose flour", "Baking", _q("1"), "kg"),
    CommonIngredient("granulated sugar", "Baking", _q("1"), "kg"),
    CommonIngredient("brown sugar", "Baking", _q("500"), "g"),
    CommonIngredient("baking powder", "Baking", _q("100"), "g"),
    CommonIngredient("baking soda", "Baking", _q("100"), "g"),
    CommonIngredient("eggs", "Dairy & Eggs", _q("12"), "pieces"),
    CommonIngredient("butter", "Dairy & Eggs", _q("250"), "g"),
    CommonIngredient("milk", "Dairy & Eggs", _q("1"), "l"),
    CommonIngredient("rice", "Grains & Pasta", _q("1"), "kg"),
    CommonIngredient("pasta", "Grains & Pasta", _q("500"), "g"),
    CommonIngredient("canned tomatoes", "Canned Goods", _q("2"), "cans"),
    CommonIngredient("tomato paste", "Canned Goods", _q("1"), "cans"),
    CommonIngredient("chicken broth", "Canned Goods", _q("1"), "l"),
    CommonIngredient("beef broth", "Canned Goods", _q("1"), "l"),
    CommonIngredient("soy sauce", "Oils & Condiments", _q("250"), "ml"),
    CommonIngredient("white vinegar", "Oils & Condiments", _q("500"), "ml"),
    CommonIngredient("apple cider vinegar", "Oils & Condiments", _q("500"), "ml"),
    CommonIngredient("honey", "Oils & Condiments", _q("250"), "g"),
    CommonIngredient("mustard", "Oils & Condiments", _q("200"), "g"),
    CommonIngredient("mayonnaise", "Oils & Condiments", _q("400"), "g"),
    CommonIngredient("ketchup", "Oils & Condiments", _q("400"), "g"),
    CommonIngredient("hot sauce", "Oils & Condiments", _q("150"), "ml"),
    CommonIngredient("paprika", "Spices & Seasonings", _q("40"), "g"),
    CommonIngredient("ground cumin", "Spices & Seasonings", _q("40"), "g"),
    CommonIngredient("dried oregano", "Spices & Seasonings", _q("20"), "g"),
    CommonIngredient("dried basil", "Spices & Seasonings", _q("20"), "g"),
    CommonIngredient("dried thyme", "Spices & Seasonings", _q("20"), "g"),
    CommonIngredient("ground cinnamon", "Spices & Seasonings", _q("40"), "g"),
    CommonIngredient("chili powder", "Spices & Seasonings", _q("40"), "g"),
    CommonIngredient("red pepper flakes", "Spices & Seasonings", _q("30"), "g"),
    CommonIngredient("potatoes", "Produce", _q("5"), "pieces"),
    CommonIngredient("carrots", "Produce", _q("5"), "pieces"),
    CommonIngredient("celery", "Produce", _q("1"), "bunches"),
    CommonIngredient("bell peppers", "Produce", _q("3"), "pieces"),
    CommonIngredient("lemons", "Produce", _q("3"), "pieces"),
    CommonIngredient("limes", "Produce", _q("3"), "pieces"),
    CommonIngredient("parmesan cheese", "Dairy & Eggs", _q("200"), "g"),
    CommonIngredient("cheddar cheese", "Dairy & Eggs", _q("250"), "g"),
    CommonIngredient("canned beans", "Canned Goods", _q("2"), "cans"),
    CommonIngredient("breadcrumbs", "Grains & Pasta", _q("200"), "g"),
    CommonIngredient("cornstarch", "Baking", _q("200"), "g"),
    CommonIngredient("vanilla extract", "Baking", _q("100"), "ml"),
    CommonIngredient("cocoa powder", "Baking", _q("200"), "g"),
    CommonIngredient("rolled oats", "Grains & Pasta", _q("500"), "g"),
    # 50 additional common staples
    CommonIngredient("sesame oil", "Oils & Condiments", _q("250"), "ml"),
    CommonIngredient("balsamic vinegar", "Oils & Condiments", _q("250"), "ml"),
    CommonIngredient("worcestershire sauce", "Oils & Condiments", _q("150"), "ml"),
    CommonIngredient("fish sauce", "Oils & Condiments", _q("200"), "ml"),
    CommonIngredient("peanut butter", "Oils & Condiments", _q("400"), "g"),
    CommonIngredient("tahini", "Oils & Condiments", _q("250"), "g"),
    CommonIngredient("maple syrup", "Oils & Condiments", _q("250"), "ml"),
    CommonIngredient("coconut oil", "Oils & Condiments", _q("400"), "g"),
    CommonIngredient("garlic powder", "Spices & Seasonings", _q("50"), "g"),
    CommonIngredient("onion powder", "Spices & Seasonings", _q("50"), "g"),
    CommonIngredient("bay leaves", "Spices & Seasonings", _q("1"), "packages"),
    CommonIngredient("ground turmeric", "Spices & Seasonings", _q("40"), "g"),
    CommonIngredient("smoked paprika", "Spices & Seasonings", _q("40"), "g"),
    CommonIngredient("italian seasoning", "Spices & Seasonings", _q("30"), "g"),
    CommonIngredient("curry powder", "Spices & Seasonings", _q("40"), "g"),
    CommonIngredient("cayenne pepper", "Spices & Seasonings", _q("30"), "g"),
    CommonIngredient("tomatoes", "Produce", _q("4"), "pieces"),
    CommonIngredient("avocados", "Produce", _q("2"), "pieces"),
    CommonIngredient("mushrooms", "Produce", _q("250"), "g"),
    CommonIngredient("spinach", "Produce", _q("1"), "bunches"),
    CommonIngredient("broccoli", "Produce", _q("1"), "pieces"),
    CommonIngredient("zucchini", "Produce", _q("2"), "pieces"),
    CommonIngredient("cucumbers", "Produce", _q("2"), "pieces"),
    CommonIngredient("ginger", "Produce", _q("1"), "pieces"),
    CommonIngredient("green onions", "Produce", _q("1"), "bunches"),
    CommonIngredient("lettuce", "Produce", _q("1"), "pieces"),
    CommonIngredient("bananas", "Produce", _q("6"), "pieces"),
    CommonIngredient("apples", "Produce", _q("4"), "pieces"),
    CommonIngredient("yogurt", "Dairy & Eggs", _q("500"), "g"),
    CommonIngredient("greek yogurt", "Dairy & Eggs", _q("500"), "g"),
    CommonIngredient("heavy cream", "Dairy & Eggs", _q("250"), "ml"),
    CommonIngredient("sour cream", "Dairy & Eggs", _q("400"), "g"),
    CommonIngredient("cream cheese", "Dairy & Eggs", _q("225"), "g"),
    CommonIngredient("mozzarella cheese", "Dairy & Eggs", _q("250"), "g"),
    CommonIngredient("powdered sugar", "Baking", _q("500"), "g"),
    CommonIngredient("active dry yeast", "Baking", _q("1"), "packages"),
    CommonIngredient("chocolate chips", "Baking", _q("340"), "g"),
    CommonIngredient("spaghetti", "Grains & Pasta", _q("500"), "g"),
    CommonIngredient("bread", "Grains & Pasta", _q("1"), "packages"),
    CommonIngredient("tortillas", "Grains & Pasta", _q("10"), "pieces"),
    CommonIngredient("quinoa", "Grains & Pasta", _q("500"), "g"),
    CommonIngredient("cornmeal", "Grains & Pasta", _q("500"), "g"),
    CommonIngredient("coconut milk", "Canned Goods", _q("2"), "cans"),
    CommonIngredient("canned tuna", "Canned Goods", _q("3"), "cans"),
    CommonIngredient("chickpeas", "Canned Goods", _q("2"), "cans"),
    CommonIngredient("black beans", "Canned Goods", _q("2"), "cans"),
    CommonIngredient("canned corn", "Canned Goods", _q("2"), "cans"),
    CommonIngredient("chicken breasts", "Meat & Seafood", _q("500"), "g"),
    CommonIngredient("bacon", "Meat & Seafood", _q("300"), "g"),
    CommonIngredient("ground beef", "Meat & Seafood", _q("500"), "g"),
]

COMMON_INGREDIENT_CATEGORIES = {item.name: item.category for item in COMMON_INGREDIENTS}
COMMON_INGREDIENT_DEFAULTS = {
    item.name: (item.default_quantity, item.default_unit) for item in COMMON_INGREDIENTS
}
