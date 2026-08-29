"""Typed application configuration.

Every value comes from the environment. Secrets have no defaults: a missing
required variable is a loud startup failure that names the variable, never a
silent fallback to something that half-works.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


#: services/api/app/core/config.py -> services/api
_SERVICE_ROOT = Path(__file__).resolve().parents[2]
#: services/api -> repo root
_REPO_ROOT = _SERVICE_ROOT.parents[1]

#: Both are consulted, later wins. The repo-root .env is the one `just bootstrap`
#: writes; the service-local one is an optional per-service override. Absolute
#: paths matter because alembic, pytest and uvicorn all run from different
#: working directories.
ENV_FILES = (_REPO_ROOT / ".env", _SERVICE_ROOT / ".env")


class Settings(BaseSettings):
    """Application settings.

    Read once at startup via :func:`get_settings`. Anything added here that is a
    credential must be `Field(...)` — required, no default — so that a
    misconfigured deployment fails at boot rather than at the first request.
    """

    model_config = SettingsConfigDict(
        env_prefix="SANAD_",
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- runtime ---
    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"
    service_name: str = "sanad-api"

    # --- datastores (required, no defaults) ---
    database_url: PostgresDsn = Field(...)
    redis_url: RedisDsn = Field(...)

    # --- object storage (required, no defaults) ---
    s3_endpoint_url: str = Field(...)
    s3_region: str = Field(...)
    s3_bucket: str = Field(...)
    s3_access_key_id: str = Field(...)
    s3_secret_access_key: str = Field(...)

    # --- auth ---
    # Peppers and keys have no defaults in production. Locally they fall back to
    # a generated value so a developer never has to invent one, and `_check_
    # production_secrets` refuses to start a production process without them.
    otp_pepper: str = "local-dev-otp-pepper-not-a-secret"
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    # Not a credential: this is the placeholder _check_production_secrets rejects.
    invite_secret: str = "local-dev-invite-secret-not-a-secret"  # noqa: S105
    sms_provider: str = "null"

    # --- web ---
    # NoDecode: pydantic-settings would otherwise JSON-parse this env var
    # before the validator below gets to split it on commas.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- AI providers ---
    # These three carry their conventional UNPREFIXED names. Every provider SDK,
    # CI runner and pasted `.env` in the world writes `GROQ_API_KEY`, and a
    # `SANAD_GROQ_API_KEY` that silently ignored the obvious spelling would be a
    # key that looks set and is not. The prefixed form still works.
    #
    # Absence is a documented mode, never a stub (SETUP.md §2): with `ai_live`
    # false the gateway replays recorded fixtures and makes no network call, and
    # a key present with `ai_live` false changes nothing. Spending money or
    # sending data needs BOTH, which is the point.
    ai_live: bool = Field(
        default=False,
        validation_alias=AliasChoices("AI_LIVE", "SANAD_AI_LIVE"),
    )
    #: Which provider the gateway speaks to. docs/12 SS2 routes every decision
    #: point to Groq; "anthropic" is retained because docs/12 leaves DP1 open
    #: pending the interpret_ar eval. A plain string rather than the gateway's
    #: `Provider` enum so that `app.core` keeps no dependency on `app.ai`.
    ai_provider: str = Field(
        default="groq",
        validation_alias=AliasChoices("AI_PROVIDER", "SANAD_AI_PROVIDER"),
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "SANAD_ANTHROPIC_API_KEY"),
    )
    groq_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_API_KEY", "SANAD_GROQ_API_KEY"),
    )
    #: Groq's OpenAI-compatible surface. Overridable so a test can point it at a
    #: local stub without monkeypatching the transport.
    groq_base_url: str = "https://api.groq.com/openai/v1"
    #: The self-hosted Qwen3-ASR host, when one exists. Absent means the ASR
    #: chain is Groq-only, which docs/12 §3.2 calls the failover, not the plan.
    asr_qwen_base_url: str | None = None

    # --- observability (optional: absence disables the exporter) ---
    otel_exporter_otlp_endpoint: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string, which is how env vars carry lists."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Settings:
        """A local-dev default must never silently become a production secret."""
        if self.environment is not Environment.PRODUCTION:
            return self
        missing = [
            name
            for name, value in (
                ("SANAD_JWT_PRIVATE_KEY", self.jwt_private_key),
                ("SANAD_JWT_PUBLIC_KEY", self.jwt_public_key),
            )
            if not value
        ]
        for name, value in (
            ("SANAD_OTP_PEPPER", self.otp_pepper),
            ("SANAD_INVITE_SECRET", self.invite_secret),
        ):
            if value.startswith("local-dev-"):
                missing.append(name)
        if missing:
            raise ValueError(
                "these must be set explicitly in production: " + ", ".join(sorted(missing))
            )
        return self

    @model_validator(mode="after")
    def _check_live_ai_has_a_key(self) -> Settings:
        """`AI_LIVE=1` with no key is a configuration error, not a fallback.

        Degrading to fixtures here would make a live-AI smoke test pass without
        ever reaching a model — the exact failure the fixture design exists to
        make impossible to hide.
        """
        if not self.ai_live:
            return self
        required = {
            "groq": ("GROQ_API_KEY", self.groq_api_key),
            "anthropic": ("ANTHROPIC_API_KEY", self.anthropic_api_key),
        }
        if self.ai_provider not in required:
            raise ValueError(
                f"AI_PROVIDER must be one of {sorted(required)}, got {self.ai_provider!r}"
            )
        name, value = required[self.ai_provider]
        if not value:
            raise ValueError(
                f"AI_LIVE is set with AI_PROVIDER={self.ai_provider} but {name} is not"
            )
        return self

    @property
    def ai_api_key(self) -> str | None:
        """The key for the configured provider, and only that one.

        Returning the wrong provider's key here would produce a 401 from a
        correctly-configured deployment, which is a long afternoon.
        """
        return self.groq_api_key if self.ai_provider == "groq" else self.anthropic_api_key

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def debug_docs_enabled(self) -> bool:
        """OpenAPI docs are served everywhere except production."""
        return not self.is_production


class ConfigurationError(RuntimeError):
    """Raised at startup when configuration is missing or invalid."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once.

    Pydantic's own ValidationError is re-raised as a ConfigurationError whose
    message names every offending variable with its SANAD_ prefix, because the
    person reading that traceback is looking at a deployment, not at this file.
    """
    try:
        return Settings()
    except Exception as exc:
        missing = _describe_validation_failure(exc)
        raise ConfigurationError(
            "Sanad API cannot start: configuration is incomplete.\n"
            f"{missing}\n"
            "Copy .env.example to .env (or set these in the environment) and retry."
        ) from exc


def _describe_validation_failure(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return f"  {exc}"
    lines = []
    for error in errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        variable = f"SANAD_{location.upper()}"
        lines.append(f"  {variable}: {error.get('msg', 'invalid')}")
    return "\n".join(lines) or f"  {exc}"
