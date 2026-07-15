"""Add recipe rating fields for highest-rated sorting."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("rating", sa.Numeric(precision=4, scale=2), nullable=True))
    op.add_column("recipes", sa.Column("rating_count", sa.Integer(), nullable=True))
    op.create_index("ix_recipes_rating", "recipes", ["rating", "id"])


def downgrade() -> None:
    op.drop_index("ix_recipes_rating", table_name="recipes")
    op.drop_column("recipes", "rating_count")
    op.drop_column("recipes", "rating")
