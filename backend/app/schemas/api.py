from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.core.security import validate_password_strength
from app.models import UploadStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(
        default=None,
        max_length=120,
        validation_alias=AliasChoices("display_name", "name"),
    )

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return validate_password_strength(value)

    @model_validator(mode="after")
    def passwords_must_differ(self) -> "PasswordChangeRequest":
        if self.current_password == self.new_password:
            raise ValueError("New password must be different from the current password")
        return self


class UserOut(ORMModel):
    id: UUID
    email: EmailStr
    display_name: str | None
    name: str | None = Field(validation_alias="display_name")
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class Message(BaseModel):
    detail: str


class CookbookOut(ORMModel):
    id: UUID
    title: str
    original_filename: str
    content_type: str
    status: UploadStatus
    progress: int
    recipe_count: int = 0
    error: str | None
    cover_url: str | None = None
    created_at: datetime
    updated_at: datetime


class IngredientOut(ORMModel):
    id: UUID
    name: str
    aliases: list[str]
    category: str | None
    staple: bool
    canonical_id: UUID | None = None


class CommonIngredientOut(BaseModel):
    name: str
    category: str
    default_quantity: Decimal
    default_unit: str


class PantryBulkItem(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = " ".join(value.lower().split())
        if not name:
            raise ValueError("Ingredient names must be between 1 and 255 characters")
        return name


class IngredientConversionOut(BaseModel):
    name: str
    grams_per_cup: Decimal
    basis: str
    source: str
    source_url: str
    confidence: Literal["high", "medium", "low"]
    aliases: list[str]
    grams_per_item: Decimal | None
    grams_per_clove: Decimal | None


class PantryCreate(BaseModel):
    ingredient_id: UUID | None = None
    ingredient_name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=80)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=80)
    expiry_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("expiry_date", "expires_at"),
    )

    @model_validator(mode="after")
    def require_ingredient(self) -> "PantryCreate":
        if bool(self.ingredient_id) == bool(self.ingredient_name):
            raise ValueError("Provide exactly one of ingredient_id or ingredient_name")
        return self


class PantryUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=80)
    expiry_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("expiry_date", "expires_at"),
    )


class PantryOut(ORMModel):
    id: UUID
    ingredient: IngredientOut
    quantity: Decimal | None
    unit: str | None
    expiry_date: date | None
    expires_at: date | None = Field(validation_alias="expiry_date")
    created_at: datetime
    updated_at: datetime


class PantryBulkCreate(BaseModel):
    items: list[PantryBulkItem] | None = Field(default=None, min_length=1, max_length=100)
    ingredient_names: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("ingredient_names")
    @classmethod
    def normalize_names(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        names = [" ".join(value.lower().split()) for value in values]
        if any(not name or len(name) > 255 for name in names):
            raise ValueError("Ingredient names must be between 1 and 255 characters")
        return names

    @model_validator(mode="after")
    def require_items_or_names(self) -> "PantryBulkCreate":
        if bool(self.items) == bool(self.ingredient_names):
            raise ValueError("Provide exactly one of items or ingredient_names")
        return self

    def resolved_items(self) -> list[PantryBulkItem]:
        if self.items is not None:
            return self.items
        return [PantryBulkItem(name=name) for name in self.ingredient_names or []]


class PantryBulkOut(BaseModel):
    added: list[PantryOut]
    skipped_existing: list[str]


class PantryFromTextCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PantryParsedChangeOut(BaseModel):
    action: Literal["add", "remove"]
    name: str
    quantity: Decimal | None = None
    unit: str | None = None


class PantryFromTextOut(BaseModel):
    parsed: list[PantryParsedChangeOut]
    added: list[PantryOut]
    updated: list[PantryOut]
    removed: list[str]
    skipped: list[str]


class PantryScanItemOut(BaseModel):
    name: str
    quantity: Decimal | None = None
    unit: str | None = None
    confidence: float | None = None


class PantryScanOut(BaseModel):
    items: list[PantryScanItemOut]


class PantryConfirmItem(BaseModel):
    ingredient_name: str = Field(min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=80)
    expiry_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("expiry_date", "expires_at"),
    )

    @field_validator("ingredient_name")
    @classmethod
    def normalize_ingredient_name(cls, value: str) -> str:
        name = " ".join(value.lower().split())
        if not name:
            raise ValueError("Ingredient name is required")
        return name

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.lower().split())
        return cleaned or None


class PantryConfirmCreate(BaseModel):
    items: list[PantryConfirmItem] = Field(min_length=1, max_length=50)


class PantryConfirmOut(BaseModel):
    added: list[PantryOut]
    updated: list[PantryOut]
    skipped_existing: list[str] = Field(default_factory=list)


class RecipeIngredientOut(ORMModel):
    id: UUID
    ingredient: IngredientOut
    quantity: Decimal | None
    unit: str | None
    raw_text: str
    position: int
    alternate_group_id: UUID | None = None
    section: str | None = None


class RecipeIngredientCompat(BaseModel):
    id: UUID
    ingredient_id: UUID
    name: str
    quantity: Decimal | None
    unit: str | None
    preparation: str | None = None
    raw_text: str | None = None
    section: str | None = None
    alternate_group_id: UUID | None = None
    in_pantry: bool
    match_status: Literal["available", "insufficient", "unknown", "missing", "staple"]
    pantry_quantity: Decimal | None = None
    pantry_unit: str | None = None
    matched_via: str | None = None
    conversion_basis: str | None = None
    conversion_source: str | None = None
    alternates: list[dict[str, object]] | None = None


class NutritionOut(BaseModel):
    calories: Decimal | None
    protein_g: Decimal | None
    carbs_g: Decimal | None
    fat_g: Decimal | None


class RecipeOut(ORMModel):
    id: UUID
    cookbook_id: UUID
    cookbook_title: str | None = None
    title: str
    servings: Decimal | None
    prep_minutes: int | None
    cook_minutes: int | None
    total_minutes: int | None
    calories: Decimal | None
    protein_grams: Decimal | None
    carbs_grams: Decimal | None
    fat_grams: Decimal | None
    cuisine: str | None
    tags: list[str]
    steps: list[str]
    source_page: int | None
    created_at: datetime
    recipe_ingredients: list[RecipeIngredientOut]
    parse_warnings: list[str] = Field(default_factory=list)
    missing_count: int = 0
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    total_time_minutes: int | None = None
    missing_ingredients: int = 0
    makeable: bool = False
    ingredients: list[RecipeIngredientCompat] = Field(default_factory=list)
    nutrition: NutritionOut | None = None


class RecipeListItem(ORMModel):
    id: UUID
    cookbook_id: UUID
    cookbook_title: str | None = None
    title: str
    total_minutes: int | None
    calories: Decimal | None
    protein_grams: Decimal | None
    cuisine: str | None
    tags: list[str]
    created_at: datetime
    missing_count: int
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    total_time_minutes: int | None = None
    missing_ingredients: int = 0
    makeable: bool = False
    nutrition: NutritionOut | None = None


class RecipePage(BaseModel):
    items: list[RecipeListItem]
    next_cursor: str | None
