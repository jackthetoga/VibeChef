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
            "ingredients": [
                ExtractedIngredient(canonical_name="tomato", raw_text="4 tomatoes")
            ]
        },
        deep=True,
    )

    assert deduplicate_recipes([first, duplicate, distinct]) == [first, distinct]


@pytest.mark.asyncio
async def test_resolve_ingredient_reuses_and_enriches_existing_ingredient() -> None:
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
        assert resolved.aliases == ["kosher salt", "sea salt"]
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
    assert parse_servings("1 1/2 to 2 quarts") is None
    assert parse_servings("About 1 2/3 cups medium-thick béchamel") is None


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
    assert demo_ingredient("7 slices good-quality, firm white toasting bread").canonical_name == "bread"
    assert demo_ingredient("2 tablespoons chopped parsley").canonical_name == "parsley"


HAZAN_EPUB = Path(
    "/Users/zizizink/Library/Mobile Documents/com~apple~CloudDocs/Downloads/"
    " Marcella Hazan - Essentials of Classic Italian Cooking _ A Cookbook "
    "(2011, Knopf Doubleday Publishing Group) - libgen.li.epub"
)


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
    finocchio = by_title[
        "Braised Finocchio with Olive Oil — Variation with Butter and Parmesan"
    ]
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
