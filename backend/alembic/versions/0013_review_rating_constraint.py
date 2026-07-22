"""Constrain catalog review ratings."""

from collections.abc import Sequence

from sqlalchemy import inspect

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_constraint(name: str) -> bool:
    constraints = inspect(op.get_bind()).get_check_constraints("reviews")
    return any(item.get("name") == name for item in constraints)


def upgrade() -> None:
    if not _has_constraint("ck_reviews_rating_range"):
        op.create_check_constraint(
            "ck_reviews_rating_range",
            "reviews",
            "rating >= 1 AND rating <= 5",
        )


def downgrade() -> None:
    if _has_constraint("ck_reviews_rating_range"):
        op.drop_constraint("ck_reviews_rating_range", "reviews", type_="check")
