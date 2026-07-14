"""Add nutrition estimate metadata and ingredient FDC macros."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("nutrition_source", sa.String(length=20), nullable=True))
    op.add_column("recipes", sa.Column("nutrition_basis", sa.String(length=20), nullable=True))
    op.add_column(
        "recipes",
        sa.Column("nutrition_coverage", sa.Numeric(precision=5, scale=4), nullable=True),
    )
    op.add_column("ingredients", sa.Column("fdc_id", sa.Integer(), nullable=True))
    op.add_column(
        "ingredients", sa.Column("fdc_description", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "ingredients",
        sa.Column("calories_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "ingredients",
        sa.Column("protein_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "ingredients",
        sa.Column("carbs_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "ingredients",
        sa.Column("fat_per_100g", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.create_index("ix_ingredients_fdc_id", "ingredients", ["fdc_id"])


def downgrade() -> None:
    op.drop_index("ix_ingredients_fdc_id", table_name="ingredients")
    op.drop_column("ingredients", "fat_per_100g")
    op.drop_column("ingredients", "carbs_per_100g")
    op.drop_column("ingredients", "protein_per_100g")
    op.drop_column("ingredients", "calories_per_100g")
    op.drop_column("ingredients", "fdc_description")
    op.drop_column("ingredients", "fdc_id")
    op.drop_column("recipes", "nutrition_coverage")
    op.drop_column("recipes", "nutrition_basis")
    op.drop_column("recipes", "nutrition_source")
