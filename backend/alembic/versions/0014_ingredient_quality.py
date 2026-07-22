"""Add ingredient families and quality metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(op.get_bind()).get_columns(table))


def _has_index(table: str, name: str) -> bool:
    return any(idx["name"] == name for idx in inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if not _has_table("ingredient_families"):
        op.create_table(
            "ingredient_families",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("category", sa.String(length=120), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
    if not _has_index("ingredient_families", "ix_ingredient_families_name"):
        op.create_index(
            "ix_ingredient_families_name",
            "ingredient_families",
            ["name"],
            unique=True,
        )

    if not _has_column("ingredients", "family_id"):
        op.add_column("ingredients", sa.Column("family_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_ingredients_family_id_ingredient_families",
            "ingredients",
            "ingredient_families",
            ["family_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_index("ingredients", "ix_ingredients_family"):
        op.create_index("ix_ingredients_family", "ingredients", ["family_id"])
    if not _has_column("ingredients", "quality_flags"):
        op.add_column(
            "ingredients",
            sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="[]"),
        )
    if not _has_column("ingredients", "normalization_version"):
        op.add_column(
            "ingredients",
            sa.Column("normalization_version", sa.Integer(), nullable=False, server_default="1"),
        )
    if not _has_column("ingredients", "canonicalization_confidence"):
        op.add_column(
            "ingredients",
            sa.Column("canonicalization_confidence", sa.Numeric(4, 3), nullable=True),
        )

    if not _has_column("recipe_ingredients", "parse_status"):
        op.add_column(
            "recipe_ingredients",
            sa.Column("parse_status", sa.String(length=20), nullable=False, server_default="valid"),
        )
    if not _has_column("recipe_ingredients", "quality_flags"):
        op.add_column(
            "recipe_ingredients",
            sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    for column in ("quality_flags", "parse_status"):
        if _has_column("recipe_ingredients", column):
            op.drop_column("recipe_ingredients", column)
    for column in (
        "canonicalization_confidence",
        "normalization_version",
        "quality_flags",
    ):
        if _has_column("ingredients", column):
            op.drop_column("ingredients", column)
    if _has_index("ingredients", "ix_ingredients_family"):
        op.drop_index("ix_ingredients_family", table_name="ingredients")
    if _has_column("ingredients", "family_id"):
        op.drop_constraint(
            "fk_ingredients_family_id_ingredient_families",
            "ingredients",
            type_="foreignkey",
        )
        op.drop_column("ingredients", "family_id")
    if _has_table("ingredient_families"):
        if _has_index("ingredient_families", "ix_ingredient_families_name"):
            op.drop_index("ix_ingredient_families_name", table_name="ingredient_families")
        op.drop_table("ingredient_families")
