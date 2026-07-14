"""Add shared food_nutrition_cache for USDA per-100g macros."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "food_nutrition_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("query_name", sa.String(length=255), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False),
        sa.Column("fdc_id", sa.Integer(), nullable=True),
        sa.Column("fdc_description", sa.String(length=512), nullable=True),
        sa.Column("calories_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("protein_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("carbs_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("fat_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_name"),
    )
    op.create_index("ix_food_nutrition_cache_fdc_id", "food_nutrition_cache", ["fdc_id"])
    op.create_index("ix_food_nutrition_cache_found", "food_nutrition_cache", ["found"])


def downgrade() -> None:
    op.drop_index("ix_food_nutrition_cache_found", table_name="food_nutrition_cache")
    op.drop_index("ix_food_nutrition_cache_fdc_id", table_name="food_nutrition_cache")
    op.drop_table("food_nutrition_cache")
