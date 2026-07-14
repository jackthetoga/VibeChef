"""Offline USDA-style per-100g macros for common pantry ingredients.

Values are rounded SR Legacy / Foundation approximations suitable for
best-effort recipe estimates, not nutrition labeling. FDC IDs are preferred
matches when present; the API client can refresh macros from FoodData Central.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FdcSeedEntry:
    fdc_id: int
    description: str
    calories: Decimal
    protein: Decimal
    carbs: Decimal
    fat: Decimal


def _e(
    fdc_id: int,
    description: str,
    calories: str,
    protein: str,
    carbs: str,
    fat: str,
) -> FdcSeedEntry:
    return FdcSeedEntry(
        fdc_id=fdc_id,
        description=description,
        calories=Decimal(calories),
        protein=Decimal(protein),
        carbs=Decimal(carbs),
        fat=Decimal(fat),
    )


FDC_SEED_BY_NAME: dict[str, FdcSeedEntry] = {
    "olive oil": _e(
        171413, "Oil", "884", "0", "0", "100"
    ),
    "vegetable oil": _e(
        167697, "Oil", "884", "0", "0", "100"
    ),
    "salt": _e(
        173468, "Salt", "0", "0", "0", "0"
    ),
    "black pepper": _e(
        170931, "Spices", "251", "10.39", "63.95", "3.26"
    ),
    "garlic": _e(
        169230, "Garlic", "149", "6.36", "33.06", "0.5"
    ),
    "onions": _e(
        170000, "Onions", "40", "1.1", "9.34", "0.1"
    ),
    "all-purpose flour": _e(
        168894, "Wheat flour", "364", "10.33", "76.31", "0.98"
    ),
    "granulated sugar": _e(
        169655, "Sugars", "387", "0", "99.98", "0"
    ),
    "brown sugar": _e(
        168833, "Sugars", "380", "0.12", "98.09", "0"
    ),
    "baking powder": _e(
        172803, "Leavening agents", "53", "0", "27.7", "0"
    ),
    "baking soda": _e(
        173424, "Leavening agents", "0", "0", "0", "0"
    ),
    "eggs": _e(
        171287, "Egg", "143", "12.56", "0.72", "9.51"
    ),
    "butter": _e(
        173410, "Butter", "717", "0.85", "0.06", "81.11"
    ),
    "milk": _e(
        171265, "Milk", "61", "3.15", "4.78", "3.25"
    ),
    "rice": _e(
        168875, "Rice", "365", "7.13", "79.95", "0.66"
    ),
    "pasta": _e(
        168928, "Pasta", "371", "13.04", "74.67", "1.51"
    ),
    "canned tomatoes": _e(
        170051, "Tomatoes", "17", "0.78", "3.91", "0.13"
    ),
    "tomato paste": _e(
        170459, "Tomato products", "82", "4.32", "18.91", "0.47"
    ),
    "chicken broth": _e(
        172884, "Soup", "15", "1.04", "0.96", "0.52"
    ),
    "beef broth": _e(
        172885, "Soup", "7", "1.14", "0.04", "0.22"
    ),
    "soy sauce": _e(
        174273, "Soy sauce made from soy and wheat (shoyu)", "53", "8.14", "4.93", "0.04"
    ),
    "white vinegar": _e(
        172237, "Vinegar", "18", "0", "0.04", "0"
    ),
    "apple cider vinegar": _e(
        173469, "Vinegar", "21", "0", "0.93", "0"
    ),
    "honey": _e(
        169640, "Honey", "304", "0.3", "82.4", "0"
    ),
    "mustard": _e(
        172234, "Mustard", "60", "3.74", "5.83", "3.34"
    ),
    "mayonnaise": _e(
        171009, "Salad dressing", "680", "0.96", "0.57", "74.85"
    ),
    "ketchup": _e(
        170051, "Catsup", "112", "1.74", "27.12", "0.1"
    ),
    "hot sauce": _e(
        174066, "Sauce", "11", "0.51", "1.75", "0.37"
    ),
    "paprika": _e(
        171329, "Spices", "282", "14.14", "53.99", "12.89"
    ),
    "ground cumin": _e(
        170923, "Spices", "375", "17.81", "44.24", "22.27"
    ),
    "dried oregano": _e(
        171328, "Spices", "265", "9", "68.92", "4.28"
    ),
    "dried basil": _e(
        171316, "Spices", "233", "22.98", "47.75", "4.07"
    ),
    "dried thyme": _e(
        170938, "Spices", "276", "9.11", "63.94", "7.43"
    ),
    "ground cinnamon": _e(
        171320, "Spices", "247", "3.99", "80.59", "1.24"
    ),
    "chili powder": _e(
        171319, "Spices", "282", "13.46", "49.7", "14.28"
    ),
    "red pepper flakes": _e(
        170932, "Spices", "318", "12.01", "56.63", "17.27"
    ),
    "potatoes": _e(
        170030, "Potatoes", "77", "2.05", "17.49", "0.09"
    ),
    "carrots": _e(
        170393, "Carrots", "41", "0.93", "9.58", "0.24"
    ),
    "celery": _e(
        169988, "Celery", "16", "0.69", "2.97", "0.17"
    ),
    "bell peppers": _e(
        170427, "Peppers", "31", "0.99", "6.03", "0.3"
    ),
    "lemons": _e(
        167747, "Lemons", "29", "1.1", "9.32", "0.3"
    ),
    "limes": _e(
        168154, "Limes", "30", "0.7", "10.54", "0.2"
    ),
    "parmesan cheese": _e(
        173436, "Cheese", "420", "28.42", "13.91", "27.84"
    ),
    "cheddar cheese": _e(
        173414, "Cheese", "403", "22.87", "3.37", "33.14"
    ),
    "canned beans": _e(
        173735, "Beans", "94", "4.75", "21.14", "0.37"
    ),
    "breadcrumbs": _e(
        174250, "Bread crumbs", "395", "13.35", "71.98", "5.3"
    ),
    "cornstarch": _e(
        168884, "Cornstarch", "381", "0.26", "91.27", "0.05"
    ),
    "vanilla extract": _e(
        173471, "Vanilla extract", "288", "0.06", "12.65", "0.06"
    ),
    "cocoa powder": _e(
        169593, "Cocoa", "228", "19.6", "57.9", "13.7"
    ),
    "rolled oats": _e(
        173904, "Cereals", "379", "13.15", "67.7", "6.52"
    ),
    "sesame oil": _e(
        171016, "Oil", "884", "0", "0", "100"
    ),
    "balsamic vinegar": _e(
        172237, "Vinegar", "88", "0.49", "17.03", "0"
    ),
    "worcestershire sauce": _e(
        174066, "Sauce", "78", "0", "19.42", "0"
    ),
    "fish sauce": _e(
        174066, "Sauce", "35", "5.06", "3.64", "0.01"
    ),
    "peanut butter": _e(
        172470, "Peanut butter", "588", "25.09", "19.56", "50.39"
    ),
    "tahini": _e(
        168614, "Sesame butter", "595", "17", "21.19", "53.76"
    ),
    "maple syrup": _e(
        169661, "Syrups", "260", "0.04", "67.04", "0.06"
    ),
    "coconut oil": _e(
        171412, "Oil", "892", "0", "0", "99.06"
    ),
    "garlic powder": _e(
        171325, "Spices", "331", "16.55", "72.73", "0.73"
    ),
    "onion powder": _e(
        171327, "Spices", "341", "10.41", "79.12", "1.04"
    ),
    "bay leaves": _e(
        170917, "Spices", "313", "7.61", "74.97", "8.36"
    ),
    "ground turmeric": _e(
        172231, "Spices", "312", "9.68", "67.14", "3.25"
    ),
    "smoked paprika": _e(
        171329, "Spices", "282", "14.14", "53.99", "12.89"
    ),
    "italian seasoning": _e(
        171328, "Spices", "265", "9", "68.92", "4.28"
    ),
    "curry powder": _e(
        171321, "Spices", "325", "14.29", "55.83", "14.01"
    ),
    "cayenne pepper": _e(
        170932, "Spices", "318", "12.01", "56.63", "17.27"
    ),
    "tomatoes": _e(
        170457, "Tomatoes", "18", "0.88", "3.89", "0.2"
    ),
    "avocados": _e(
        171705, "Avocados", "160", "2", "8.53", "14.66"
    ),
    "mushrooms": _e(
        169251, "Mushrooms", "22", "3.09", "3.26", "0.34"
    ),
    "spinach": _e(
        168462, "Spinach", "23", "2.86", "3.63", "0.39"
    ),
    "broccoli": _e(
        170379, "Broccoli", "34", "2.82", "6.64", "0.37"
    ),
    "zucchini": _e(
        169291, "Squash", "17", "1.21", "3.11", "0.32"
    ),
    "cucumbers": _e(
        168409, "Cucumber", "15", "0.65", "3.63", "0.11"
    ),
    "ginger": _e(
        169231, "Ginger root", "80", "1.82", "17.77", "0.75"
    ),
    "green onions": _e(
        170005, "Onions", "32", "1.83", "7.34", "0.19"
    ),
    "lettuce": _e(
        169249, "Lettuce", "17", "1.23", "3.29", "0.3"
    ),
    "bananas": _e(
        173944, "Bananas", "89", "1.09", "22.84", "0.33"
    ),
    "apples": _e(
        171688, "Apples", "52", "0.26", "13.81", "0.17"
    ),
    "yogurt": _e(
        171284, "Yogurt", "61", "3.47", "4.66", "3.25"
    ),
    "greek yogurt": _e(
        170903, "Yogurt", "59", "10.19", "3.6", "0.39"
    ),
    "heavy cream": _e(
        170859, "Cream", "340", "2.84", "2.74", "36.08"
    ),
    "sour cream": _e(
        171257, "Cream", "198", "2.44", "4.63", "19.35"
    ),
    "cream cheese": _e(
        173418, "Cheese", "342", "5.93", "4.14", "34.24"
    ),
    "mozzarella cheese": _e(
        173430, "Cheese", "300", "22.17", "2.19", "22.35"
    ),
    "powdered sugar": _e(
        169656, "Sugars", "389", "0", "99.77", "0"
    ),
    "active dry yeast": _e(
        175043, "Leavening agents", "325", "40.44", "41.22", "7.61"
    ),
    "chocolate chips": _e(
        167587, "Candies", "480", "4.2", "63.1", "30"
    ),
    "spaghetti": _e(
        168928, "Pasta", "371", "13.04", "74.67", "1.51"
    ),
    "bread": _e(
        174924, "Bread", "265", "8.85", "49.42", "3.33"
    ),
    "tortillas": _e(
        174994, "Tortillas", "312", "8.2", "50.75", "7.99"
    ),
    "quinoa": _e(
        168874, "Quinoa", "368", "14.12", "64.16", "6.07"
    ),
    "cornmeal": _e(
        168865, "Cornmeal", "362", "8.12", "76.89", "3.59"
    ),
    "coconut milk": _e(
        170172, "Nuts", "197", "2.02", "2.81", "21.33"
    ),
    "canned tuna": _e(
        175156, "Fish", "86", "19.44", "0", "0.96"
    ),
    "chickpeas": _e(
        173757, "Chickpeas (garbanzo beans", "164", "8.86", "27.42", "2.59"
    ),
    "black beans": _e(
        175189, "Beans", "132", "8.86", "23.71", "0.54"
    ),
    "canned corn": _e(
        169288, "Corn", "67", "2.15", "15.28", "0.95"
    ),
    "chicken breasts": _e(
        171477, "Chicken", "120", "22.5", "0", "2.62"
    ),
    "bacon": _e(
        168322, "Pork", "417", "12.62", "1.28", "39.69"
    ),
    "ground beef": _e(
        174032, "Beef", "215", "18.59", "0", "15"
    ),
}


def normalize_food_name(name: str) -> str:
    return " ".join(name.lower().split())


def get_fdc_seed(name: str | None) -> FdcSeedEntry | None:
    if not name:
        return None
    normalized = normalize_food_name(name)
    direct = FDC_SEED_BY_NAME.get(normalized)
    if direct:
        return direct
    from app.services.ingredient_conversions import get_ingredient_conversion

    profile = get_ingredient_conversion(name)
    if profile is None:
        return None
    return FDC_SEED_BY_NAME.get(normalize_food_name(profile.name))
