"""Add cookbook cover_path for extracted thumbnails."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cookbooks", sa.Column("cover_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("cookbooks", "cover_path")
