"""Add catalog cookbooks/recipes and user reviews."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(op.get_bind()).get_columns(table))


def _has_index(table: str, name: str) -> bool:
    return any(idx["name"] == name for idx in inspect(op.get_bind()).get_indexes(table))


def _has_fk(table: str, name: str) -> bool:
    return any(fk["name"] == name for fk in inspect(op.get_bind()).get_foreign_keys(table))


def upgrade() -> None:
    if not _has_table("catalog_cookbooks"):
        op.create_table(
            "catalog_cookbooks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("content_sha256", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("catalog_cookbooks", "ix_catalog_cookbooks_content_sha256"):
        op.create_index(
            "ix_catalog_cookbooks_content_sha256",
            "catalog_cookbooks",
            ["content_sha256"],
            unique=True,
        )

    if not _has_table("catalog_recipes"):
        op.create_table(
            "catalog_recipes",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("catalog_cookbook_id", sa.Uuid(), nullable=False),
            sa.Column("recipe_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("user_rating_avg", sa.Numeric(precision=4, scale=2), nullable=True),
            sa.Column("user_rating_count", sa.Integer(), nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(
                ["catalog_cookbook_id"],
                ["catalog_cookbooks.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "catalog_cookbook_id",
                "recipe_fingerprint",
                name="uq_catalog_recipe_fingerprint",
            ),
        )
    if not _has_index("catalog_recipes", "ix_catalog_recipes_cookbook"):
        op.create_index(
            "ix_catalog_recipes_cookbook",
            "catalog_recipes",
            ["catalog_cookbook_id"],
        )
    if not _has_index("catalog_recipes", "ix_catalog_recipes_user_rating"):
        op.create_index(
            "ix_catalog_recipes_user_rating",
            "catalog_recipes",
            ["user_rating_avg", "id"],
        )

    if not _has_column("cookbooks", "content_sha256"):
        op.add_column("cookbooks", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    if not _has_index("cookbooks", "ix_cookbooks_content_sha256"):
        op.create_index("ix_cookbooks_content_sha256", "cookbooks", ["content_sha256"])

    if not _has_column("recipes", "catalog_recipe_id"):
        op.add_column("recipes", sa.Column("catalog_recipe_id", sa.Uuid(), nullable=True))
    if not _has_fk("recipes", "fk_recipes_catalog_recipe_id_catalog_recipes"):
        op.create_foreign_key(
            "fk_recipes_catalog_recipe_id_catalog_recipes",
            "recipes",
            "catalog_recipes",
            ["catalog_recipe_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_index("recipes", "ix_recipes_catalog_recipe"):
        op.create_index("ix_recipes_catalog_recipe", "recipes", ["catalog_recipe_id"])

    if not _has_table("reviews"):
        op.create_table(
            "reviews",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("catalog_recipe_id", sa.Uuid(), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["catalog_recipe_id"],
                ["catalog_recipes.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "catalog_recipe_id",
                name="uq_review_user_catalog_recipe",
            ),
        )
    if not _has_index("reviews", "ix_reviews_user"):
        op.create_index("ix_reviews_user", "reviews", ["user_id"])
    if not _has_index("reviews", "ix_reviews_catalog_recipe_created"):
        op.create_index(
            "ix_reviews_catalog_recipe_created",
            "reviews",
            ["catalog_recipe_id", "created_at"],
        )

    if not _has_table("review_photos"):
        op.create_table(
            "review_photos",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("review_id", sa.Uuid(), nullable=False),
            sa.Column("storage_path", sa.String(length=1024), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("review_id", "position", name="uq_review_photo_position"),
        )
    if not _has_index("review_photos", "ix_review_photos_review"):
        op.create_index(
            "ix_review_photos_review",
            "review_photos",
            ["review_id", "position"],
        )


def downgrade() -> None:
    if _has_table("review_photos"):
        if _has_index("review_photos", "ix_review_photos_review"):
            op.drop_index("ix_review_photos_review", table_name="review_photos")
        op.drop_table("review_photos")
    if _has_table("reviews"):
        if _has_index("reviews", "ix_reviews_catalog_recipe_created"):
            op.drop_index("ix_reviews_catalog_recipe_created", table_name="reviews")
        if _has_index("reviews", "ix_reviews_user"):
            op.drop_index("ix_reviews_user", table_name="reviews")
        op.drop_table("reviews")
    if _has_index("recipes", "ix_recipes_catalog_recipe"):
        op.drop_index("ix_recipes_catalog_recipe", table_name="recipes")
    if _has_fk("recipes", "fk_recipes_catalog_recipe_id_catalog_recipes"):
        op.drop_constraint(
            "fk_recipes_catalog_recipe_id_catalog_recipes",
            "recipes",
            type_="foreignkey",
        )
    if _has_column("recipes", "catalog_recipe_id"):
        op.drop_column("recipes", "catalog_recipe_id")
    if _has_index("cookbooks", "ix_cookbooks_content_sha256"):
        op.drop_index("ix_cookbooks_content_sha256", table_name="cookbooks")
    if _has_column("cookbooks", "content_sha256"):
        op.drop_column("cookbooks", "content_sha256")
    if _has_table("catalog_recipes"):
        if _has_index("catalog_recipes", "ix_catalog_recipes_user_rating"):
            op.drop_index("ix_catalog_recipes_user_rating", table_name="catalog_recipes")
        if _has_index("catalog_recipes", "ix_catalog_recipes_cookbook"):
            op.drop_index("ix_catalog_recipes_cookbook", table_name="catalog_recipes")
        op.drop_table("catalog_recipes")
    if _has_table("catalog_cookbooks"):
        if _has_index("catalog_cookbooks", "ix_catalog_cookbooks_content_sha256"):
            op.drop_index(
                "ix_catalog_cookbooks_content_sha256",
                table_name="catalog_cookbooks",
            )
        op.drop_table("catalog_cookbooks")
