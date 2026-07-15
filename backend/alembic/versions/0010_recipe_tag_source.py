"""Add recipe.tag_source for auto vs manual tagging."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("tag_source", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "tag_source")
