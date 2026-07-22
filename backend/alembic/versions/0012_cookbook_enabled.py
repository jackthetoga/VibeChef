"""Add cookbook enabled state."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("cookbooks", "enabled"):
        op.add_column(
            "cookbooks",
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    if _has_column("cookbooks", "enabled"):
        op.drop_column("cookbooks", "enabled")
