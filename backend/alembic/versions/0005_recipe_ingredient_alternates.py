"""Add alternate groups, sections, and parse warnings for ingredients."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_ingredients") as batch_op:
        batch_op.add_column(sa.Column("alternate_group_id", sa.Uuid(as_uuid=True), nullable=True))
        batch_op.add_column(sa.Column("section", sa.String(length=255), nullable=True))
        batch_op.create_index(
            "ix_recipe_ingredients_alternate_group",
            ["recipe_id", "alternate_group_id"],
        )
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "parse_warnings",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.drop_column("parse_warnings")
    with op.batch_alter_table("recipe_ingredients") as batch_op:
        batch_op.drop_index("ix_recipe_ingredients_alternate_group")
        batch_op.drop_column("section")
        batch_op.drop_column("alternate_group_id")
