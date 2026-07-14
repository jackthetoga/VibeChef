from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env next to the backend package root so scripts work from any cwd.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Recipe Finder"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    secret_key: str = "development-only-change-me-please"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    database_url: str = "sqlite+aiosqlite:///./recipe_finder.db"
    redis_url: str | None = None
    upload_dir: Path = Path("./uploads")
    max_upload_bytes: int = 50 * 1024 * 1024
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )
    cors_origin_regex: str | None = (
        r"^https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$"
    )
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.deepseek.com"
    openai_model: str = "deepseek-v4-flash"
    usda_fdc_api_key: str | None = None
    usda_fdc_base_url: str = "https://api.nal.usda.gov/fdc/v1"
    nutrition_min_coverage: float = 0.6
    dev_sync_ingestion: bool = True
    auto_create_tables: bool = True

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @model_validator(mode="after")
    def require_secure_production_secret(self) -> "Settings":
        if self.is_production and (
            self.secret_key == "development-only-change-me-please"
            or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY must be changed to at least 32 characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
