"""Initial Recipe Finder schema."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        *timestamps(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "cookbooks",
        *timestamps(),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_cookbooks_user_id", "cookbooks", ["user_id"])
    op.create_index("ix_cookbooks_user_created", "cookbooks", ["user_id", "created_at"])
    op.create_index("ix_cookbooks_user_status", "cookbooks", ["user_id", "status"])

    op.create_table(
        "ingredients",
        *timestamps(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("category", sa.String(120)),
        sa.Column("staple", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_ingredients_name", "ingredients", ["name"])
    op.create_index("ix_ingredients_category", "ingredients", ["category"])

    op.create_table(
        "recipes",
        *timestamps(),
        sa.Column(
            "cookbook_id",
            sa.Uuid(),
            sa.ForeignKey("cookbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("servings", sa.Numeric(10, 2)),
        sa.Column("prep_minutes", sa.Integer()),
        sa.Column("cook_minutes", sa.Integer()),
        sa.Column("total_minutes", sa.Integer()),
        sa.Column("calories", sa.Numeric(10, 2)),
        sa.Column("protein_grams", sa.Numeric(10, 2)),
        sa.Column("carbs_grams", sa.Numeric(10, 2)),
        sa.Column("fat_grams", sa.Numeric(10, 2)),
        sa.Column("cuisine", sa.String(120)),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("source_page", sa.Integer()),
    )
    op.create_index("ix_recipes_cookbook_id", "recipes", ["cookbook_id"])
    op.create_index("ix_recipes_cookbook_created", "recipes", ["cookbook_id", "created_at"])
    op.create_index("ix_recipes_total_time", "recipes", ["total_minutes", "id"])
    op.create_index("ix_recipes_calories", "recipes", ["calories", "id"])
    op.create_index("ix_recipes_protein", "recipes", ["protein_grams", "id"])
    op.create_index("ix_recipes_title", "recipes", ["title", "id"])
    op.create_index("ix_recipes_cuisine", "recipes", ["cuisine"])

    op.create_table(
        "recipe_ingredients",
        *timestamps(),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.Uuid(),
            sa.ForeignKey("ingredients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("unit", sa.String(80)),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("recipe_id", "position", name="uq_recipe_ingredient_position"),
    )
    op.create_index("ix_recipe_ingredients_recipe", "recipe_ingredients", ["recipe_id", "position"])
    op.create_index("ix_recipe_ingredients_ingredient", "recipe_ingredients", ["ingredient_id"])

    op.create_table(
        "pantry_items",
        *timestamps(),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "ingredient_id",
            sa.Uuid(),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("unit", sa.String(80)),
        sa.Column("expiry_date", sa.Date()),
        sa.UniqueConstraint("user_id", "ingredient_id", name="uq_pantry_user_ingredient"),
    )
    op.create_index("ix_pantry_items_user_id", "pantry_items", ["user_id"])
    op.create_index("ix_pantry_items_ingredient_id", "pantry_items", ["ingredient_id"])
    op.create_index("ix_pantry_user_expiry", "pantry_items", ["user_id", "expiry_date"])

    op.create_table(
        "refresh_tokens",
        *timestamps(),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("jti_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "replaced_by_id",
            sa.Uuid(),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        ),
        sa.Column("user_agent", sa.String(512)),
    )
    op.create_index("ix_refresh_jti_hash", "refresh_tokens", ["jti_hash"], unique=True)
    op.create_index("ix_refresh_user_expires", "refresh_tokens", ["user_id", "expires_at"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE INDEX ix_recipes_search_gin ON recipes USING GIN (
              to_tsvector(
                'english',
                coalesce(title, '') || ' ' || coalesce(cuisine, '') || ' ' ||
                coalesce(tags::text, '')
              )
            )
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_recipes_search_gin")
    op.drop_table("refresh_tokens")
    op.drop_table("pantry_items")
    op.drop_table("recipe_ingredients")
    op.drop_table("recipes")
    op.drop_table("ingredients")
    op.drop_table("cookbooks")
    op.drop_table("users")
