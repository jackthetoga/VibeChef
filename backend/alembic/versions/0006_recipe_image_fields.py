"""Add recipe image_path, image_source, and image_key."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("image_path", sa.String(length=1024), nullable=True))
    op.add_column("recipes", sa.Column("image_source", sa.String(length=20), nullable=True))
    op.add_column("recipes", sa.Column("image_key", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "image_key")
    op.drop_column("recipes", "image_source")
    op.drop_column("recipes", "image_path")
