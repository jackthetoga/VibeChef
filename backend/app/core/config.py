from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "recipe-finder"
    jwt_audience: str = "recipe-finder-web"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    refresh_cookie_name: str = "rf_refresh"
    refresh_cookie_path: str = "/api/v1/auth"
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
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "[::1]", "test"]
    )
    rate_limit_enabled: bool = True
    auth_rate_limit_per_minute: int = 10
    upload_rate_limit_per_hour: int = 5
    pantry_ai_rate_limit_per_hour: int = 30
    llm_daily_call_limit: int = 1000
    max_active_ingestions_per_user: int = 1
    max_pdf_pages: int = 1000
    max_pdf_text_chars: int = 10_000_000
    max_epub_entries: int = 2000
    max_epub_entry_bytes: int = 8 * 1024 * 1024
    max_epub_uncompressed_bytes: int = 250 * 1024 * 1024
    max_ingestion_llm_chunks: int = 100
    max_image_pixels: int = 20_000_000
    max_image_dimension: int = 10_000
    openai_api_key: str | None = None
    external_ai_enabled: bool = False
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
    def require_secure_configuration(self) -> "Settings":
        insecure_values = {
            "development-only-change-me-please",
            "replace-with-a-random-secret",
            "changeme",
        }
        if self.secret_key.lower() in insecure_values or len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be a unique value of at least 32 characters")
        if self.is_production and self.cors_origin_regex:
            self.cors_origin_regex = None
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def refresh_cookie_secure(self) -> bool:
        return self.is_production

    @property
    def llm_enabled(self) -> bool:
        return self.external_ai_enabled and bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
