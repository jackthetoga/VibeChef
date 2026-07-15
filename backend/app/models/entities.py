import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UUIDTimestampMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class UploadStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ImageSource(StrEnum):
    extracted = "extracted"
    category = "category"  # legacy SVG fallbacks; cleared by backfill
    corpus = "corpus"
    generated = "generated"
    user = "user"
    none = "none"


class NutritionSource(StrEnum):
    printed = "printed"
    estimated = "estimated"
    manual = "manual"


class NutritionBasis(StrEnum):
    per_serving = "per_serving"
    whole_recipe = "whole_recipe"


class User(UUIDTimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    credentials_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    cookbooks: Mapped[list["Cookbook"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    pantry_items: Mapped[list["PantryItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Cookbook(UUIDTimestampMixin, Base):
    __tablename__ = "cookbooks"
    __table_args__ = (
        Index("ix_cookbooks_user_created", "user_id", "created_at"),
        Index("ix_cookbooks_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    cover_path: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, native_enum=False, length=20),
        default=UploadStatus.pending,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    owner: Mapped[User] = relationship(back_populates="cookbooks")
    recipes: Mapped[list["Recipe"]] = relationship(
        back_populates="cookbook", cascade="all, delete-orphan"
    )


class Recipe(UUIDTimestampMixin, Base):
    __tablename__ = "recipes"
    __table_args__ = (
        Index("ix_recipes_cookbook_created", "cookbook_id", "created_at"),
        Index("ix_recipes_total_time", "total_minutes", "id"),
        Index("ix_recipes_calories", "calories", "id"),
        Index("ix_recipes_protein", "protein_grams", "id"),
        Index("ix_recipes_title", "title", "id"),
        Index("ix_recipes_cuisine", "cuisine"),
        Index("ix_recipes_rating", "rating", "id"),
    )

    cookbook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cookbooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    servings: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    cook_minutes: Mapped[int | None] = mapped_column(Integer)
    total_minutes: Mapped[int | None] = mapped_column(Integer)
    calories: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    protein_grams: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    carbs_grams: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fat_grams: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    nutrition_source: Mapped[NutritionSource | None] = mapped_column(
        Enum(NutritionSource, native_enum=False, length=20)
    )
    nutrition_basis: Mapped[NutritionBasis | None] = mapped_column(
        Enum(NutritionBasis, native_enum=False, length=20)
    )
    nutrition_coverage: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    cuisine: Mapped[str | None] = mapped_column(String(120))
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    rating_count: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tag_source: Mapped[str | None] = mapped_column(String(20))
    steps: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    parse_warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(1024))
    image_source: Mapped[ImageSource | None] = mapped_column(
        Enum(ImageSource, native_enum=False, length=20)
    )
    image_key: Mapped[str | None] = mapped_column(String(64))

    cookbook: Mapped[Cookbook] = relationship(back_populates="recipes")
    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.position",
    )


class Ingredient(UUIDTimestampMixin, Base):
    __tablename__ = "ingredients"
    __table_args__ = (
        Index("ix_ingredients_name", "name"),
        Index("ix_ingredients_category", "category"),
        Index("ix_ingredients_canonical", "canonical_id"),
    )

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    staple: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    canonical_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingredients.id", ondelete="SET NULL")
    )
    fdc_id: Mapped[int | None] = mapped_column(Integer, index=True)
    fdc_description: Mapped[str | None] = mapped_column(String(512))
    calories_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    protein_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    carbs_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fat_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="ingredient")
    pantry_items: Mapped[list["PantryItem"]] = relationship(back_populates="ingredient")


class FoodNutritionCache(UUIDTimestampMixin, Base):
    """Shared per-100g macros keyed by normalized food name (central USDA cache)."""

    __tablename__ = "food_nutrition_cache"
    __table_args__ = (
        Index("ix_food_nutrition_cache_fdc_id", "fdc_id"),
        Index("ix_food_nutrition_cache_found", "found"),
    )

    # Normalized query name, e.g. "yellow onion"
    query_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    found: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fdc_id: Mapped[int | None] = mapped_column(Integer)
    fdc_description: Mapped[str | None] = mapped_column(String(512))
    calories_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    protein_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    carbs_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fat_per_100g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="fdc")


class RecipeIngredient(UUIDTimestampMixin, Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        UniqueConstraint("recipe_id", "position", name="uq_recipe_ingredient_position"),
        Index("ix_recipe_ingredients_recipe", "recipe_id", "position"),
        Index("ix_recipe_ingredients_ingredient", "ingredient_id"),
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(80))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    alternate_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    section: Mapped[str | None] = mapped_column(String(255))

    recipe: Mapped[Recipe] = relationship(back_populates="recipe_ingredients")
    ingredient: Mapped[Ingredient] = relationship(back_populates="recipe_ingredients")


class PantryItem(UUIDTimestampMixin, Base):
    __tablename__ = "pantry_items"
    __table_args__ = (
        UniqueConstraint("user_id", "ingredient_id", name="uq_pantry_user_ingredient"),
        Index("ix_pantry_user_expiry", "user_id", "expiry_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(80))
    expiry_date: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="pantry_items")
    ingredient: Mapped[Ingredient] = relationship(back_populates="pantry_items")


class RefreshToken(UUIDTimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_user_expires", "user_id", "expires_at"),
        Index("ix_refresh_jti_hash", "jti_hash", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    jti_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
    replaced_by: Mapped["RefreshToken | None"] = relationship(remote_side="RefreshToken.id")


JSONValue = dict[str, Any]
