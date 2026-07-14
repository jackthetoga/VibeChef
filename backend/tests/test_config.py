import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_the_default_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY must be changed"):
        Settings(
            app_env="production",
            secret_key="development-only-change-me-please",
            _env_file=None,
        )


def test_production_accepts_a_strong_secret() -> None:
    configured = Settings(
        app_env="production",
        secret_key="a-unique-production-secret-with-32-characters",
        _env_file=None,
    )

    assert configured.is_production
