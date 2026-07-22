from decimal import Decimal
from pathlib import Path

import pytest
from ebooklib import epub

from app.db.session import SessionLocal
from app.models import Ingredient
from app.services.ingestion import (
    ExtractedIngredient,
    ExtractedRecipe,
    ExtractionEnvelope,
    _html_to_text,
    chunk_sections,
    deduplicate_recipes,
    demo_ingredient,
    demo_parse,
    extract_cover,
    extract_sections,
    extract_structured_epub_recipes,
    parse_servings,
    resolve_ingredient,
)

TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789a63000100000500010d0a2db40000000049454e44ae426082"
)


def _write_sample_epub(path: Path, *, with_cover: bool = True) -> None:
    book = epub.EpubBook()
    book.set_identifier("recipe-finder-test")
    book.set_title("Test Cookbook")
    book.set_language("en")
    if with_cover:
        book.set_cover("cover.png", TINY_PNG)

    chapter = epub.EpubHtml(title="Tomato Pasta", file_name="pasta.xhtml", lang="en")
    chapter.content = """
    <html><body>
      <h1>Tomato Pasta</h1>
      <h2>Ingredients</h2>
      <ul>
        <li>2 cups tomatoes, chopped</li>
        <li>1/2 tsp salt</li>
      </ul>
      <h2>Instructions</h2>
      <ol>
        <li>Simmer the tomatoes.</li>
        <li>Season and serve.</li>
      </ol>
      <p>A great many spices<span>except those that overwhelm</span> the dish.</p>
    </body></html>
    """
    book.add_item(chapter)
    book.toc = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def test_demo_parser_is_deterministic_without_an_api_key() -> None:
    recipes = demo_parse(
        """
        Tomato Pasta
        Ingredients
        2 cups tomatoes, chopped
        1/2 tsp salt
        Instructions
        1. Simmer the tomatoes.
        2. Season and serve.
        """
    )

    assert len(recipes) == 1
    assert recipes[0].title == "Tomato Pasta"
    assert recipes[0].ingredients[0].canonical_name == "tomatoes"
    assert recipes[0].ingredients[0].quantity == Decimal("2")
    assert recipes[0].ingredients[1].canonical_name == "salt"
    assert recipes[0].ingredients[1].quantity == Decimal("0.5")
    assert recipes[0].ingredients[1].unit == "tsp"
    assert recipes[0].steps == ["Simmer the tomatoes.", "Season and serve."]


def test_demo_parser_accepts_ingredients_with_trailing_colon() -> None:
    recipes = demo_parse(
        """
        Broth
        Ingredients:
        1 cup water
        Method:
        1. Boil.
        """
    )
    assert len(recipes) == 1
    assert recipes[0].ingredients[0].canonical_name == "water"


def test_duplicate_extractions_are_removed_without_dropping_distinct_recipes() -> None:
    first = ExtractedRecipe(
        title="Tomato Pasta",
        source_page=12,
        ingredients=[ExtractedIngredient(canonical_name="tomato", raw_text="2 tomatoes")],
        steps=["Simmer."],
    )
    duplicate = first.model_copy(deep=True)
    distinct = first.model_copy(
        update={
            "ingredients": [ExtractedIngredient(canonical_name="tomato", raw_text="4 tomatoes")]
        },
        deep=True,
    )

    assert deduplicate_recipes([first, duplicate, distinct]) == [first, distinct]


@pytest.mark.asyncio
async def test_resolve_ingredient_does_not_merge_llm_taxonomy_into_shared_row() -> None:
    async with SessionLocal() as db:
        existing = Ingredient(name="salt", aliases=["sea salt"], staple=False)
        db.add(existing)
        await db.commit()

        resolved = await resolve_ingredient(
            db,
            ExtractedIngredient(
                canonical_name="salt",
                raw_text="1 tsp salt",
                aliases=["kosher salt"],
                staple=True,
            ),
        )

        assert resolved.id == existing.id
        assert resolved.aliases == ["sea salt"]
        assert resolved.staple is True


def test_prose_canonical_name_is_sanitized_instead_of_failing_validation() -> None:
    prose = (
        "a great many spices except those reserved for the most sophisticated "
        "mestizo cuisine of the central highlands and surrounding valleys with "
        "additional ceremonial notes about family gatherings and feast days "
        "where cooks prepare moles and salsas with careful attention to balance"
    )
    assert len(prose) > 255
    ingredient = ExtractedIngredient(canonical_name=prose, raw_text="2 tsp cumin")
    assert len(ingredient.canonical_name) <= 80
    assert ingredient.canonical_name == "cumin"


def test_html_to_text_keeps_spaces_between_inline_spans() -> None:
    html = b"<p>A great many spices<span>except those</span> that overwhelm.</p>"
    text = _html_to_text(html)
    assert "spices except" in text
    assert "spicesexcept" not in text


def test_txt_extraction_splits_blank_line_sections(tmp_path: Path) -> None:
    txt_path = tmp_path / "recipes.txt"
    txt_path.write_text(
        """Tomato Pasta
Ingredients
2 cups tomatoes, chopped
1/2 tsp salt
Instructions
1. Simmer the tomatoes.
2. Season and serve.

Garlic Toast
Ingredients
2 slices bread
1 tbsp butter
Instructions
1. Toast the bread.
2. Spread butter.
""",
        encoding="utf-8",
    )
    sections = extract_sections(txt_path)
    assert len(sections) == 2
    assert sections[0].startswith("[SECTION 1]")
    assert "Tomato Pasta" in sections[0]
    assert sections[1].startswith("[SECTION 2]")
    assert "Garlic Toast" in sections[1]
    recipes = demo_parse("\n\n".join(sections))
    assert {recipe.title for recipe in recipes} >= {"Tomato Pasta", "Garlic Toast"}


def test_epub_extraction_uses_spine_and_parses_list_recipes(tmp_path: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    _write_sample_epub(epub_path)
    sections = extract_sections(epub_path)
    joined = "\n\n".join(sections)
    assert "[CHAPTER" in joined
    assert "Tomato Pasta" in joined
    assert "• 2 cups tomatoes, chopped" in joined
    assert "spices except" in joined
    recipes = demo_parse(joined)
    assert len(recipes) == 1
    assert recipes[0].title == "Tomato Pasta"


def test_epub_cover_extraction(tmp_path: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    _write_sample_epub(epub_path, with_cover=True)
    cover = extract_cover(epub_path, tmp_path, "11111111-1111-1111-1111-111111111111")
    assert cover is not None
    assert (tmp_path / cover).is_file()
    assert (tmp_path / cover).read_bytes().startswith(b"\x89PNG")


def test_chunk_sections_keeps_chapter_boundaries() -> None:
    sections = [
        "[CHAPTER 1]\nIntro essay " + ("word " * 20),
        "[CHAPTER 2]\nTomato Pasta\nIngredients\n1 cup tomatoes\nInstructions\nCook.",
    ]
    chunks = chunk_sections(sections)
    assert any("Tomato Pasta" in chunk for chunk in chunks)
    assert all(len(chunk) <= 24_000 for chunk in chunks)


def test_unicode_fraction_ingredient_parsing() -> None:
    ingredient = demo_ingredient("½ pound fresh ricotta")
    assert ingredient.quantity == Decimal("0.5")
    assert ingredient.unit == "pound"
    assert ingredient.canonical_name == "fresh ricotta"
    assert demo_ingredient("1½ cups milk").quantity == Decimal("1.5")


def test_parse_servings_ignores_volume_yields() -> None:
    assert parse_servings("For 6 servings") == Decimal("6")
    assert parse_servings("For 6 to 12 servings") == Decimal("9")
    assert parse_servings("For 28 canapés") == Decimal("28")
    assert parse_servings("Serves 4 to 6") == Decimal("5")
    assert parse_servings("Serves 4") == Decimal("4")
    assert parse_servings("Makes 12") == Decimal("12")
    assert parse_servings("1 1/2 to 2 quarts") is None
    assert parse_servings("About 1 2/3 cups medium-thick béchamel") is None
    assert parse_servings("Makes 3/4 cup") is None


def _write_knopf_style_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("knopf-style-test")
    book.set_title("Knopf Style Cookbook")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Appetizers", file_name="c02.xhtml", lang="en")
    chapter.content = """
    <html><body>
      <p class="rt">Crostini Bianchi</p>
      <p class="ry">For 28 canapés</p>
      <p class="rilf">½ pound fresh ricotta</p>
      <p class="ril">1 tablespoon butter</p>
      <p class="rill">7 slices bread</p>
      <p class="rp">1. Preheat oven to 400°.</p>
      <p class="rp">2. Spread and serve.</p>
      <p class="rn">Ahead-of-time note Ignore this essay note.</p>
      <p class="rtaft">Bruschetta</p>
      <p class="rhnf">An introduction that is not a recipe body.</p>
      <p class="rvh">Basic Bruschetta</p>
      <p class="rvy">For 6 to 12 servings</p>
      <p class="rvilf">6 garlic cloves</p>
      <p class="rvil">Extra virgin olive oil</p>
      <p class="rvill">Salt</p>
      <p class="rvp">1. Grill the bread.</p>
      <p class="rvh">Variation with Oil Only</p>
      <p class="rvf">Omit the garlic and drizzle with olive oil.</p>
    </body></html>
    """
    book.add_item(chapter)
    book.toc = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def test_structured_epub_parser_uses_knopf_css_classes(tmp_path: Path) -> None:
    epub_path = tmp_path / "knopf.epub"
    _write_knopf_style_epub(epub_path)
    recipes = extract_structured_epub_recipes(epub_path)
    assert recipes is not None
    by_title = {recipe.title: recipe for recipe in recipes}
    assert set(by_title) == {
        "Crostini Bianchi",
        "Bruschetta — Basic Bruschetta",
        "Bruschetta — Variation with Oil Only",
    }
    crostini = by_title["Crostini Bianchi"]
    assert crostini.servings == Decimal("28")
    assert len(crostini.ingredients) == 3
    assert crostini.ingredients[0].quantity == Decimal("0.5")
    assert crostini.steps == ["Preheat oven to 400°.", "Spread and serve."]
    assert "Ignore this essay note" not in " ".join(crostini.steps)
    bruschetta = by_title["Bruschetta — Basic Bruschetta"]
    assert bruschetta.servings == Decimal("9")
    assert bruschetta.ingredients[0].canonical_name == "garlic cloves"
    variation = by_title["Bruschetta — Variation with Oil Only"]
    assert [item.canonical_name for item in variation.ingredients] == [
        "extra virgin olive oil",
        "salt",
    ]
    assert variation.steps == ["Omit the garlic and drizzle with olive oil."]


def test_ingredient_parser_finds_noun_after_comma_separated_descriptors() -> None:
    potato = demo_ingredient("1½ pounds round, waxy, boiling potatoes")
    assert potato.canonical_name == "potatoes"
    assert potato.quantity == Decimal("1.5")
    assert potato.unit == "pounds"
    assert demo_ingredient("1 pound fresh, ripe, firm tomatoes").canonical_name == "tomatoes"
    assert (
        demo_ingredient("7 slices good-quality, firm white toasting bread").canonical_name
        == "bread"
    )
    assert demo_ingredient("2 tablespoons chopped parsley").canonical_name == "parsley"


def test_canned_tomato_or_alternate_matches_canned_tomatoes_name() -> None:
    """Fresh/canned tomato OR lines must expose a canned-tomatoes alternate for pantry match."""
    from app.services.canonicalize import heuristic_canonical_name
    from app.services.ingestion import parse_ingredient_line

    raw = (
        "2 pounds fresh, ripe tomatoes, prepared as described on this page or "
        "2 cups canned imported Italian plum tomatoes, cut up, with their juice"
    )
    alternates = parse_ingredient_line(raw)
    assert len(alternates) == 2
    assert alternates[0].alternate_group == alternates[1].alternate_group
    assert alternates[0].canonical_name == "tomatoes"
    assert alternates[0].quantity == Decimal("2")
    assert alternates[0].unit == "pounds"
    assert alternates[1].canonical_name == "canned tomatoes"
    assert alternates[1].quantity == Decimal("2")
    assert alternates[1].unit == "cups"
    assert heuristic_canonical_name("canned imported italian plum tomatoes") == "canned tomatoes"


def test_meaty_ripe_red_bell_peppers_keeps_full_noun() -> None:
    """Regression: '3 meaty, ripe red bell peppers' must not collapse to 'meaty'."""
    from app.services.ingestion import (
        _parse_structured_epub_document,
        expand_ambiguous_or_ingredients_sync,
        parse_ingredient_line,
        quality_assure_recipes,
    )

    parsed = parse_ingredient_line("3 meaty, ripe red bell peppers")
    assert len(parsed) == 1
    assert parsed[0].canonical_name == "bell peppers"
    assert parsed[0].quantity == Decimal("3")
    assert parsed[0].canonical_name != "meaty"

    # Full structured-EPUB path used by cookbook reingest.
    content = """
    <html><body>
      <p class="rt">Peas, Peppers, and Prosciutto Sauce with Cream</p>
      <p class="ry">For 4 to 6 servings</p>
      <p class="rilf">3 meaty, ripe red bell peppers</p>
      <p class="ril">3 tablespoons butter</p>
      <p class="ril">1 cup tiny frozen peas, thawed</p>
      <p class="rill">1 cup heavy whipping cream</p>
      <p class="rp">1. Cook.</p>
    </body></html>
    """
    recipes = expand_ambiguous_or_ingredients_sync(
        quality_assure_recipes(_parse_structured_epub_document(content))
    )
    assert len(recipes) == 1
    names = [item.canonical_name for item in recipes[0].ingredients]
    assert "bell peppers" in names
    assert "meaty" not in names
    pepper = next(item for item in recipes[0].ingredients if item.canonical_name == "bell peppers")
    assert pepper.quantity == Decimal("3")
    assert pepper.raw_text == "3 meaty, ripe red bell peppers"


def test_quantified_or_splits_into_alternate_group() -> None:
    from app.services.ingestion import parse_ingredient_line

    squid = parse_ingredient_line(
        "2½ pounds small to medium whole squid or 2 pounds cleaned squid, sliced into rings"
    )
    assert len(squid) == 2
    assert squid[0].alternate_group == squid[1].alternate_group
    assert squid[0].canonical_name == "squid"
    assert squid[0].quantity == Decimal("2.5")
    assert squid[0].unit == "pounds"
    assert squid[1].canonical_name == "squid"
    assert squid[1].quantity == Decimal("2")

    marinara = parse_ingredient_line(
        "2 pounds fresh, ripe, firm plum tomatoes (see note on this page ) or "
        "3 cups canned imported Italian plum tomatoes, drained and cut up"
    )
    assert len(marinara) == 2
    assert marinara[0].canonical_name == "plum tomatoes"
    assert "tomato" in marinara[1].canonical_name
    assert marinara[1].quantity == Decimal("3")
    assert marinara[1].unit == "cups"

    peas = parse_ingredient_line(
        "2 pounds unshelled fresh peas or 1 ten-ounce package frozen peas, thawed"
    )
    assert len(peas) == 2
    assert "pea" in peas[0].canonical_name
    assert "pea" in peas[1].canonical_name


def test_quantity_range_and_color_or_are_not_false_split() -> None:
    from app.services.ingestion import (
        expand_ambiguous_or_ingredients_sync,
        parse_ingredient_line,
    )

    celery = parse_ingredient_line("1 or 2 celery stalks")
    assert len(celery) == 1
    assert celery[0].canonical_name == "celery stalks"
    assert celery[0].quantity == Decimal("1")

    peppers = parse_ingredient_line("red or green bell peppers")
    assert len(peppers) == 1
    assert peppers[0].ambiguous_or is True
    expanded = expand_ambiguous_or_ingredients_sync(
        [
            ExtractedRecipe(
                title="Peppers",
                ingredients=peppers,
                steps=["Cook."],
            )
        ]
    )
    assert len(expanded[0].ingredients) == 1
    assert "bell pepper" in expanded[0].ingredients[0].canonical_name


def test_variation_omit_does_not_swallow_following_ingredients() -> None:
    from app.services.ingestion import _apply_variation_omissions

    base = [
        demo_ingredient("2½ pounds small to medium whole squid"),
        demo_ingredient("2 pounds unshelled fresh peas"),
        demo_ingredient("3 tablespoons extra virgin olive oil"),
    ]
    # Force clean names as after OR split
    base[0] = base[0].model_copy(update={"canonical_name": "squid"})
    base[1] = base[1].model_copy(update={"canonical_name": "peas"})
    kept = _apply_variation_omissions(
        base,
        "Omit the peas from the previous recipe, and when the squid is done, chop it.",
    )
    names = {item.canonical_name for item in kept}
    assert "squid" in names
    assert "peas" not in names
    assert "extra virgin olive oil" in names


def test_rilh_section_headers_attach_without_becoming_ingredients() -> None:
    from app.services.ingestion import (
        _parse_structured_epub_document,
        expand_ambiguous_or_ingredients_sync,
        quality_assure_recipes,
    )

    content = """
    <html><body>
      <p class="rt">Pizza Dough</p>
      <p class="rilh">For the topping</p>
      <p class="rilf">2 pounds plum tomatoes</p>
      <p class="rill">3 tablespoons olive oil</p>
      <p class="rp">1. Bake.</p>
    </body></html>
    """
    recipes = expand_ambiguous_or_ingredients_sync(
        quality_assure_recipes(_parse_structured_epub_document(content))
    )
    assert len(recipes) == 1
    pizza = recipes[0]
    assert [item.canonical_name for item in pizza.ingredients] == [
        "plum tomatoes",
        "olive oil",
    ]
    assert all(item.section == "For the topping" for item in pizza.ingredients)
    assert not any(item.canonical_name == "for the topping" for item in pizza.ingredients)


HAZAN_EPUB = Path(
    "/Users/zizizink/Library/Mobile Documents/com~apple~CloudDocs/Downloads/"
    " Marcella Hazan - Essentials of Classic Italian Cooking _ A Cookbook "
    "(2011, Knopf Doubleday Publishing Group) - libgen.li.epub"
)

SFAH_EPUB = Path(
    "/Users/zizizink/Library/Mobile Documents/com~apple~CloudDocs/Downloads/"
    " Nosrat, Samin - Salt, Fat, Acid, Heat_ Mastering the Elements of Good "
    "Cooking (2017, Simon & Schuster) - libgen.li.epub"
)


def _write_simon_schuster_style_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("ss-style-test")
    book.set_title("Simon Schuster Style Cookbook")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Recipes", file_name="recipes.xhtml", lang="en")
    chapter.content = """
    <html><body>
      <h2 class="h2rec">Persian-ish Rice</h2>
      <p class="right2">Serves 4 to 6</p>
      <p class="noindent">Every Persian has a special relationship with rice.</p>
      <p class="item1">2 cups basmati rice</p>
      <p class="item">Salt</p>
      <p class="item">3 tablespoons plain yogurt</p>
      <p class="itemb">3 tablespoons butter</p>
      <p class="noindent">Fill a large stockpot with water and bring it to a boil.</p>
      <p class="indent">Cook the rice until al dente, then drain.</p>
      <h5 class="h5">Variations</h5>
      <p class="bull1">• To make Saffron Rice, add saffron tea.</p>
      <h2 class="h2rec">Basic Salsa Verde</h2>
      <p class="right2">Makes 3/4 cup</p>
      <p class="item1">3 tablespoons finely diced shallot</p>
      <p class="item">3 tablespoons red wine vinegar</p>
      <p class="itemb">1/4 cup extra-virgin olive oil</p>
      <p class="noindent">Combine the shallot and vinegar and let sit for 15 minutes.</p>
    </body></html>
    """
    book.add_item(chapter)
    book.toc = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def _write_structural_list_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("structural-list-test")
    book.set_title("Generic List Cookbook")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Pasta", file_name="pasta.xhtml", lang="en")
    chapter.content = """
    <html><body>
      <h1>Tomato Pasta</h1>
      <p>Serves 4</p>
      <h2>Ingredients</h2>
      <ul>
        <li>2 cups tomatoes, chopped</li>
        <li>1/2 tsp salt</li>
        <li>2 tablespoons olive oil</li>
      </ul>
      <h2>Instructions</h2>
      <ol>
        <li>Simmer the tomatoes.</li>
        <li>Season and serve.</li>
      </ol>
      <h1>Garlic Toast</h1>
      <h2>Ingredients</h2>
      <ul>
        <li>2 slices bread</li>
        <li>1 tbsp butter</li>
      </ul>
      <h2>Method</h2>
      <ol>
        <li>Toast the bread.</li>
        <li>Spread butter.</li>
      </ol>
    </body></html>
    """
    book.add_item(chapter)
    book.toc = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def test_simon_schuster_profile_skips_headnotes_and_variations(tmp_path: Path) -> None:
    epub_path = tmp_path / "ss.epub"
    _write_simon_schuster_style_epub(epub_path)
    recipes = extract_structured_epub_recipes(epub_path)
    assert recipes is not None
    by_title = {recipe.title: recipe for recipe in recipes}
    assert set(by_title) == {"Persian-ish Rice", "Basic Salsa Verde"}
    rice = by_title["Persian-ish Rice"]
    assert rice.servings == Decimal("5")
    assert [item.canonical_name for item in rice.ingredients][:2] == [
        "basmati rice",
        "salt",
    ]
    assert rice.steps
    assert "Every Persian has a special relationship with rice." not in " ".join(rice.steps)
    assert not any("Saffron" in recipe.title for recipe in recipes)
    salsa = by_title["Basic Salsa Verde"]
    assert salsa.servings is None  # volume yield ignored
    assert len(salsa.ingredients) >= 3
    assert salsa.steps


def test_structural_profile_recovers_list_recipes_without_publisher_classes(
    tmp_path: Path,
) -> None:
    epub_path = tmp_path / "structural.epub"
    _write_structural_list_epub(epub_path)
    recipes = extract_structured_epub_recipes(epub_path)
    assert recipes is not None
    by_title = {recipe.title: recipe for recipe in recipes}
    assert set(by_title) >= {"Tomato Pasta", "Garlic Toast"}
    pasta = by_title["Tomato Pasta"]
    assert pasta.servings == Decimal("4")
    assert len(pasta.ingredients) >= 3
    assert pasta.steps == ["Simmer the tomatoes.", "Season and serve."]
    toast = by_title["Garlic Toast"]
    assert [item.canonical_name for item in toast.ingredients] == ["bread", "butter"]
    assert toast.steps == ["Toast the bread.", "Spread butter."]


def test_knopf_profile_still_wins_over_structural_lookalikes(tmp_path: Path) -> None:
    """Knopf markup must take the exclusive cascade path even if lists exist."""
    epub_path = tmp_path / "knopf.epub"
    _write_knopf_style_epub(epub_path)
    recipes = extract_structured_epub_recipes(epub_path)
    assert recipes is not None
    titles = {recipe.title for recipe in recipes}
    assert "Crostini Bianchi" in titles
    assert "Bruschetta — Basic Bruschetta" in titles


@pytest.mark.skipif(not SFAH_EPUB.is_file(), reason="SFAH EPUB not available locally")
def test_sfah_epub_simon_schuster_profile_recovers_recipes() -> None:
    recipes = extract_structured_epub_recipes(SFAH_EPUB)
    assert recipes is not None
    assert len(recipes) >= 90
    by_title = {recipe.title: recipe for recipe in recipes}
    rice = by_title["Persian-ish Rice"]
    assert rice.servings == Decimal("5")
    assert any("rice" in item.canonical_name for item in rice.ingredients)
    assert rice.steps
    assert "Every Persian has a special relationship with rice" not in " ".join(rice.steps)
    salsa = by_title["Basic Salsa Verde"]
    assert len(salsa.ingredients) >= 3
    assert all(recipe.ingredients for recipe in recipes)


@pytest.mark.skipif(not HAZAN_EPUB.is_file(), reason="Hazan EPUB not available locally")
def test_hazan_epub_structured_parse_recovers_full_cookbook() -> None:
    recipes = extract_structured_epub_recipes(HAZAN_EPUB)
    assert recipes is not None
    assert len(recipes) >= 450
    by_title = {recipe.title: recipe for recipe in recipes}
    crostini = by_title["Crostini Bianchi—Ricotta and Anchovy Canapés"]
    assert crostini.servings == Decimal("28")
    assert crostini.ingredients
    assert crostini.steps
    broth = by_title["Basic Homemade Meat Broth"]
    assert len(broth.steps) == 5
    assert "Bruschetta—Roman Garlic Bread — Basic Bruschetta" in by_title
    assert "Bruschetta—Roman Garlic Bread" not in by_title
    assert "Variation with Butter and Parmesan" not in by_title
    finocchio = by_title["Braised Finocchio with Olive Oil — Variation with Butter and Parmesan"]
    names = {item.canonical_name for item in finocchio.ingredients}
    assert "butter" in names
    assert "parmigiano-reggiano cheese" in names
    assert "extra virgin olive oil" not in names
    assert all(recipe.ingredients for recipe in recipes)
    assert not any(
        item.canonical_name in {"round", "fresh", "black", "medium round"}
        for recipe in recipes
        for item in recipe.ingredients
    )
    squid = by_title["Squid with Tomatoes and Peas, Tuscan Style"]
    squid_names = {item.canonical_name for item in squid.ingredients}
    assert any("squid" in name for name in squid_names)
    assert any("pea" in name for name in squid_names)
    assert any(
        item.alternate_group and "squid" in item.canonical_name for item in squid.ingredients
    )
    variation = by_title[
        "Squid with Tomatoes and Peas, Tuscan Style — Alternative Uses for Squid and Tomatoes"
    ]
    variation_names = {item.canonical_name for item in variation.ingredients}
    assert any("squid" in name for name in variation_names)
    assert not any("pea" in name for name in variation_names)
    marinara = by_title["Marinara Topping: Garlic, Tomatoes, and Olive Oil"]
    marinara_names = {item.canonical_name for item in marinara.ingredients}
    assert any("tomato" in name for name in marinara_names)
    assert any(
        item.alternate_group and "tomato" in item.canonical_name for item in marinara.ingredients
    )
    peas_peppers = by_title["Peas, Peppers, and Prosciutto Sauce with Cream"]
    peas_peppers_names = [item.canonical_name for item in peas_peppers.ingredients]
    assert "bell peppers" in peas_peppers_names
    assert "meaty" not in peas_peppers_names
    pepper = next(
        item for item in peas_peppers.ingredients if item.canonical_name == "bell peppers"
    )
    assert pepper.quantity == Decimal("3")
    assert pepper.raw_text.startswith("3 meaty")


def test_extraction_envelope_ignores_extra_llm_fields() -> None:
    envelope = ExtractionEnvelope.model_validate(
        {
            "recipes": [
                {
                    "title": "Soup",
                    "ingredients": [
                        {
                            "canonical_name": "water",
                            "raw_text": "1 cup water",
                            "notes": "ignored",
                        }
                    ],
                    "steps": ["Boil."],
                    "author_commentary": "ignored",
                }
            ]
        }
    )
    assert envelope.recipes[0].title == "Soup"
    assert envelope.recipes[0].ingredients[0].canonical_name == "water"
