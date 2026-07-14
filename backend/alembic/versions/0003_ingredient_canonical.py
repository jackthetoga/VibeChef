"""Add canonical ingredient links."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ingredients") as batch_op:
        batch_op.add_column(
            sa.Column(
                "canonical_id",
                sa.Uuid(),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_ingredients_canonical_id_ingredients",
            "ingredients",
            ["canonical_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_ingredients_canonical",
            ["canonical_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ingredients") as batch_op:
        batch_op.drop_index("ix_ingredients_canonical")
        batch_op.drop_constraint(
            "fk_ingredients_canonical_id_ingredients",
            type_="foreignkey",
        )
        batch_op.drop_column("canonical_id")
