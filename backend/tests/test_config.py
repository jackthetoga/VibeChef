import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_the_default_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY must be a unique value"):
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
    assert configured.cors_origin_regex is None
    assert configured.refresh_cookie_secure


def test_all_environments_require_a_strong_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="development", secret_key="too-short", _env_file=None)


def test_external_ai_requires_explicit_opt_in() -> None:
    disabled = Settings(
        secret_key="a-unique-development-secret-with-32-characters",
        openai_api_key="provider-key",
        _env_file=None,
    )
    enabled = Settings(
        secret_key="a-unique-development-secret-with-32-characters",
        openai_api_key="provider-key",
        external_ai_enabled=True,
        _env_file=None,
    )

    assert not disabled.llm_enabled
    assert enabled.llm_enabled
