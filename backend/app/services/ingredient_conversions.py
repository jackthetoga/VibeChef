from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

USDA_SOURCE = "USDA FoodData Central household portions"
USDA_URL = "https://fdc.nal.usda.gov/"
KING_ARTHUR_SOURCE = "King Arthur Baking ingredient weight chart"
KING_ARTHUR_URL = "https://www.kingarthurbaking.com/learn/ingredient-weight-chart"


@dataclass(frozen=True)
class IngredientConversion:
    name: str
    grams_per_cup: Decimal
    basis: str
    source: str
    source_url: str
    confidence: Literal["high", "medium", "low"] = "medium"
    aliases: tuple[str, ...] = ()
    grams_per_item: Decimal | None = None
    grams_per_clove: Decimal | None = None


def conversion(
    name: str,
    grams_per_cup: str,
    basis: str,
    *,
    source: str = USDA_SOURCE,
    source_url: str = USDA_URL,
    confidence: Literal["high", "medium", "low"] = "medium",
    aliases: tuple[str, ...] = (),
    grams_per_item: str | None = None,
    grams_per_clove: str | None = None,
) -> IngredientConversion:
    return IngredientConversion(
        name=name,
        grams_per_cup=Decimal(grams_per_cup),
        basis=basis,
        source=source,
        source_url=source_url,
        confidence=confidence,
        aliases=aliases,
        grams_per_item=Decimal(grams_per_item) if grams_per_item else None,
        grams_per_clove=Decimal(grams_per_clove) if grams_per_clove else None,
    )


# Household weights are deliberately preparation-specific. They are suitable for
# best-effort inventory matching, not nutrition labeling or precision baking.
INGREDIENT_CONVERSIONS = (
    conversion(
        "olive oil",
        "200",
        "oil",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("extra virgin olive oil",),
    ),
    conversion(
        "vegetable oil",
        "198",
        "neutral cooking oil",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("canola oil", "cooking oil"),
    ),
    conversion(
        "salt",
        "288",
        "fine table salt",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="medium",
        aliases=("table salt",),
    ),
    conversion("black pepper", "110.4", "ground", aliases=("pepper", "ground black pepper")),
    conversion(
        "garlic",
        "136",
        "raw, chopped",
        aliases=("garlic cloves",),
        grams_per_item="3",
        grams_per_clove="3",
    ),
    conversion(
        "onions",
        "142",
        "fresh, diced; 1 large onion ≈ 2 cups",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        aliases=("onion", "yellow onion", "red onion", "white onion"),
        # Cooking yield: one large onion ≈ 2 cups diced (142 g/cup → 284 g/item).
        grams_per_item="284",
    ),
    conversion(
        "all-purpose flour",
        "120",
        "spooned and leveled",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("flour", "plain flour", "ap flour"),
    ),
    conversion(
        "granulated sugar",
        "198",
        "white granulated",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("sugar", "white sugar"),
    ),
    conversion(
        "brown sugar",
        "213",
        "packed",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("light brown sugar", "dark brown sugar"),
    ),
    conversion(
        "baking powder",
        "192",
        "level measure",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
    ),
    conversion(
        "baking soda",
        "288",
        "level measure",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("bicarbonate of soda",),
    ),
    conversion(
        "eggs",
        "243",
        "raw whole egg",
        aliases=("egg", "large eggs", "large egg"),
        grams_per_item="50",
    ),
    conversion(
        "butter",
        "226",
        "solid or melted",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("unsalted butter", "salted butter"),
        grams_per_item="113",
    ),
    conversion(
        "milk",
        "244",
        "fluid milk",
        confidence="high",
        aliases=("whole milk", "skim milk", "low-fat milk"),
    ),
    conversion(
        "rice",
        "185",
        "dry, uncooked long-grain",
        aliases=("white rice", "brown rice", "uncooked rice"),
    ),
    conversion(
        "pasta",
        "100",
        "dry short pasta; shape-dependent",
        confidence="low",
        aliases=("dry pasta", "uncooked pasta"),
    ),
    conversion(
        "canned tomatoes",
        "242",
        "canned with liquid",
        aliases=(
            "tomatoes, canned",
            "tinned tomatoes",
            "diced tomatoes",
            "canned plum tomatoes",
            "canned imported italian plum tomatoes",
            "imported italian plum tomatoes",
        ),
    ),
    conversion(
        "tomato paste",
        "262",
        "canned paste",
        confidence="high",
        aliases=("tomato puree concentrate",),
    ),
    conversion(
        "chicken broth", "240", "prepared liquid", confidence="high", aliases=("chicken stock",)
    ),
    conversion("beef broth", "240", "prepared liquid", confidence="high", aliases=("beef stock",)),
    conversion("soy sauce", "255", "regular soy sauce", confidence="high"),
    conversion(
        "white vinegar",
        "238",
        "distilled vinegar",
        confidence="high",
        aliases=("vinegar", "distilled white vinegar"),
    ),
    conversion(
        "apple cider vinegar", "239", "liquid", confidence="high", aliases=("cider vinegar",)
    ),
    conversion(
        "honey",
        "336",
        "liquid honey",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
    ),
    conversion(
        "mustard", "249", "prepared yellow mustard", aliases=("yellow mustard", "prepared mustard")
    ),
    conversion("mayonnaise", "230", "prepared mayonnaise", aliases=("mayo",)),
    conversion("ketchup", "272", "tomato ketchup", confidence="high", aliases=("catsup",)),
    conversion("hot sauce", "240", "thin vinegar-based sauce", confidence="low"),
    conversion("paprika", "108.8", "ground"),
    conversion("ground cumin", "100.8", "ground", aliases=("cumin", "cumin powder")),
    conversion("dried oregano", "48", "dried leaves", aliases=("oregano",)),
    conversion("dried basil", "33.6", "dried leaves", aliases=("basil, dried",)),
    conversion("dried thyme", "43.2", "dried leaves", aliases=("thyme",)),
    conversion("ground cinnamon", "124.8", "ground", aliases=("cinnamon",)),
    conversion(
        "chili powder", "110.4", "ground spice blend", confidence="low", aliases=("chilli powder",)
    ),
    conversion(
        "red pepper flakes",
        "76.8",
        "crushed flakes",
        confidence="low",
        aliases=("chili flakes", "chilli flakes", "crushed red pepper"),
    ),
    conversion("potatoes", "150", "raw, diced", aliases=("potato",), grams_per_item="213"),
    conversion("carrots", "128", "raw, chopped", aliases=("carrot",), grams_per_item="61"),
    conversion("celery", "101", "raw, chopped", aliases=("celery stalks",), grams_per_item="40"),
    conversion(
        "bell peppers",
        "149",
        "raw, chopped",
        aliases=("bell pepper", "sweet pepper", "red bell pepper", "green bell pepper"),
        grams_per_item="119",
    ),
    conversion(
        "lemons",
        "212",
        "raw sections, without peel",
        confidence="low",
        aliases=("lemon",),
        grams_per_item="58",
    ),
    conversion(
        "limes",
        "180",
        "raw sections, without peel",
        confidence="low",
        aliases=("lime",),
        grams_per_item="67",
    ),
    conversion(
        "parmesan cheese",
        "100",
        "finely grated",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        aliases=("parmesan", "grated parmesan"),
    ),
    conversion(
        "cheddar cheese",
        "113",
        "shredded",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        aliases=("shredded cheddar",),
    ),
    conversion(
        "canned beans",
        "177",
        "cooked, drained",
        confidence="low",
        aliases=("beans, canned", "tinned beans"),
    ),
    conversion("breadcrumbs", "108", "dry, plain", confidence="low", aliases=("bread crumbs",)),
    conversion(
        "cornstarch",
        "112",
        "spooned",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("corn starch", "cornflour"),
    ),
    conversion(
        "vanilla extract",
        "224",
        "liquid extract",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("vanilla",),
    ),
    conversion(
        "cocoa powder",
        "84",
        "unsweetened, spooned",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("cocoa", "unsweetened cocoa"),
    ),
    conversion(
        "rolled oats",
        "89",
        "old-fashioned or quick-cooking",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("oats", "old-fashioned oats"),
    ),
    # Additional common staples
    conversion(
        "sesame oil",
        "218",
        "toasted or plain sesame oil",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="medium",
    ),
    conversion("balsamic vinegar", "255", "aged balsamic vinegar", confidence="medium"),
    conversion(
        "worcestershire sauce",
        "275",
        "bottled sauce",
        confidence="low",
        aliases=("worcestershire",),
    ),
    conversion("fish sauce", "290", "bottled fish sauce", confidence="medium"),
    conversion(
        "peanut butter",
        "258",
        "smooth or creamy",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("creamy peanut butter",),
    ),
    conversion("tahini", "240", "sesame paste", confidence="medium", aliases=("sesame paste",)),
    conversion(
        "maple syrup",
        "312",
        "pure maple syrup",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
    ),
    conversion(
        "coconut oil",
        "218",
        "solid or melted",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
    ),
    conversion("garlic powder", "112", "dehydrated ground garlic", confidence="medium"),
    conversion("onion powder", "112", "dehydrated ground onion", confidence="medium"),
    conversion(
        "bay leaves",
        "20",
        "dried whole leaves",
        confidence="low",
        aliases=("bay leaf", "dried bay leaves"),
        grams_per_item="0.6",
    ),
    conversion(
        "ground turmeric", "112", "ground spice", confidence="medium", aliases=("turmeric",)
    ),
    conversion("smoked paprika", "108.8", "ground smoked paprika", confidence="medium"),
    conversion(
        "italian seasoning",
        "48",
        "dried herb blend",
        confidence="low",
        aliases=("italian herbs",),
    ),
    conversion("curry powder", "104", "ground spice blend", confidence="medium"),
    conversion(
        "cayenne pepper",
        "85",
        "ground cayenne",
        confidence="medium",
        aliases=("cayenne", "ground cayenne"),
    ),
    conversion(
        "tomatoes",
        "180",
        "fresh, chopped",
        aliases=("tomato", "fresh tomatoes"),
        grams_per_item="123",
    ),
    conversion(
        "avocados",
        "150",
        "fresh, cubed",
        aliases=("avocado",),
        grams_per_item="136",
    ),
    conversion(
        "mushrooms",
        "70",
        "fresh, sliced",
        aliases=("mushroom", "button mushrooms"),
        grams_per_item="18",
    ),
    conversion(
        "spinach",
        "30",
        "fresh leaves",
        aliases=("fresh spinach", "baby spinach"),
    ),
    conversion(
        "broccoli",
        "91",
        "fresh florets",
        aliases=("broccoli florets",),
        grams_per_item="225",
    ),
    conversion(
        "zucchini",
        "124",
        "fresh, sliced",
        aliases=("courgette",),
        grams_per_item="196",
    ),
    conversion(
        "cucumbers",
        "104",
        "fresh, sliced",
        aliases=("cucumber",),
        grams_per_item="300",
    ),
    conversion(
        "ginger",
        "96",
        "fresh, minced",
        aliases=("fresh ginger", "ginger root"),
        grams_per_item="15",
    ),
    conversion(
        "green onions",
        "64",
        "fresh, sliced",
        aliases=("scallions", "spring onions"),
        grams_per_item="15",
    ),
    conversion(
        "lettuce",
        "36",
        "fresh, shredded",
        aliases=("romaine lettuce", "iceberg lettuce"),
        grams_per_item="300",
    ),
    conversion(
        "bananas",
        "150",
        "fresh, sliced",
        aliases=("banana",),
        grams_per_item="118",
    ),
    conversion(
        "apples",
        "125",
        "fresh, chopped",
        aliases=("apple",),
        grams_per_item="182",
    ),
    conversion(
        "yogurt",
        "245",
        "plain yogurt",
        confidence="high",
        aliases=("plain yogurt",),
    ),
    conversion(
        "greek yogurt",
        "245",
        "strained yogurt",
        confidence="high",
        aliases=("plain greek yogurt",),
    ),
    conversion(
        "heavy cream",
        "238",
        "fluid heavy cream",
        confidence="high",
        aliases=("whipping cream", "heavy whipping cream"),
    ),
    conversion("sour cream", "230", "cultured sour cream", confidence="high"),
    conversion(
        "cream cheese",
        "232",
        "block cream cheese",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
    ),
    conversion(
        "mozzarella cheese",
        "113",
        "shredded",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        aliases=("mozzarella", "shredded mozzarella"),
    ),
    conversion(
        "powdered sugar",
        "113",
        "unsifted",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("confectioners sugar", "icing sugar"),
    ),
    conversion(
        "active dry yeast",
        "150",
        "dry granules",
        confidence="medium",
        aliases=("dry yeast", "instant yeast"),
        grams_per_item="7",
    ),
    conversion(
        "chocolate chips",
        "170",
        "semi-sweet chips",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
        aliases=("semi-sweet chocolate chips",),
    ),
    conversion(
        "spaghetti",
        "100",
        "dry long pasta",
        confidence="medium",
        aliases=("dry spaghetti",),
    ),
    conversion(
        "bread",
        "120",
        "sliced sandwich bread",
        confidence="low",
        aliases=("sandwich bread", "white bread"),
        grams_per_item="28",
    ),
    conversion(
        "tortillas",
        "140",
        "flour tortillas",
        confidence="low",
        aliases=("flour tortillas", "corn tortillas"),
        grams_per_item="45",
    ),
    conversion("quinoa", "170", "dry, uncooked", confidence="medium", aliases=("dry quinoa",)),
    conversion(
        "cornmeal",
        "156",
        "yellow cornmeal",
        source=KING_ARTHUR_SOURCE,
        source_url=KING_ARTHUR_URL,
        confidence="high",
    ),
    conversion(
        "coconut milk",
        "240",
        "canned coconut milk",
        confidence="medium",
        aliases=("canned coconut milk",),
    ),
    conversion(
        "canned tuna",
        "160",
        "drained canned tuna",
        confidence="medium",
        aliases=("tuna, canned", "tinned tuna"),
    ),
    conversion(
        "chickpeas",
        "164",
        "cooked, drained",
        confidence="medium",
        aliases=("garbanzo beans", "canned chickpeas"),
    ),
    conversion(
        "black beans",
        "172",
        "cooked, drained",
        confidence="medium",
        aliases=("canned black beans",),
    ),
    conversion(
        "canned corn",
        "164",
        "drained canned corn",
        confidence="medium",
        aliases=("corn, canned", "sweet corn"),
    ),
    conversion(
        "chicken breasts",
        "140",
        "raw boneless skinless",
        confidence="medium",
        aliases=("chicken breast", "boneless chicken breast"),
        grams_per_item="174",
    ),
    conversion(
        "bacon",
        "100",
        "raw sliced bacon",
        confidence="low",
        aliases=("bacon strips",),
        grams_per_item="16",
    ),
    conversion(
        "ground beef",
        "226",
        "raw ground beef",
        confidence="medium",
        aliases=("beef mince", "minced beef", "hamburger meat"),
    ),
)


CONVERSION_BY_NAME: dict[str, IngredientConversion] = {}
for profile in INGREDIENT_CONVERSIONS:
    for profile_name in (profile.name, *profile.aliases):
        normalized = " ".join(profile_name.lower().split())
        if normalized in CONVERSION_BY_NAME:
            raise RuntimeError(f"Duplicate ingredient conversion alias: {normalized}")
        CONVERSION_BY_NAME[normalized] = profile


def get_ingredient_conversion(name: str | None) -> IngredientConversion | None:
    if not name:
        return None
    return CONVERSION_BY_NAME.get(" ".join(name.lower().split()))
