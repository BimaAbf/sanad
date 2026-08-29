"""A missing required variable must fail loudly and name the variable."""

from __future__ import annotations

import pytest

from app.core.config import ConfigurationError, Settings, get_settings


def test_settings_load_from_environment() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.s3_bucket == "misk-media"
    assert settings.cors_origins == ["http://localhost:3000"]


def test_missing_required_variable_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISK_DATABASE_URL", raising=False)
    # Ignore any .env sitting next to the tests, so this asserts the env var
    # itself is missing rather than merely absent from the process environment.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    message = str(excinfo.value)
    assert "MISK_DATABASE_URL" in message
    assert "cannot start" in message
    get_settings.cache_clear()


def test_secrets_have_no_defaults() -> None:
    """Every credential field is required — no field may carry a usable default."""
    required = {
        "database_url",
        "redis_url",
        "s3_endpoint_url",
        "s3_region",
        "s3_bucket",
        "s3_access_key_id",
        "s3_secret_access_key",
    }
    for name in required:
        assert Settings.model_fields[name].is_required(), f"{name} must be required"


def test_cors_origins_accepts_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISK_CORS_ORIGINS", "http://a.test, http://b.test")
    get_settings.cache_clear()
    assert get_settings().cors_origins == ["http://a.test", "http://b.test"]
    get_settings.cache_clear()
