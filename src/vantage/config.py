"""Typed application configuration with fail-fast key verification.

All settings come from environment variables / a local ``.env`` file. Secrets are
wrapped in ``SecretStr`` so they never print by accident. The app refuses to start
if the selected LLM provider has no key - no silent fallback (API-key-only).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "analytics.db"
DEFAULT_DICT_PATH = PROJECT_ROOT / "seed" / "data_dictionary.yml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM (API-key-only; no local model) ---------------------------------
    llm_provider: Literal["groq", "gemini"] = "groq"
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.0-flash"
    llm_temperature: float = 0.0
    request_timeout: int = 30

    # --- Data ----------------------------------------------------------------
    database_url: str = ""  # defaults to the bundled SQLite DB (see validator)
    data_dictionary_path: str = str(DEFAULT_DICT_PATH)

    # --- Agent / guardrails --------------------------------------------------
    max_sql_rows: int = 1000
    max_retries: int = 2
    query_timeout_seconds: int = 15
    enable_cache: bool = True

    # --- Observability -------------------------------------------------------
    log_level: str = "INFO"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @model_validator(mode="after")
    def _finalize(self) -> Settings:
        # Default DB -> bundled SQLite file (posix path handles the space in the dir).
        if not self.database_url:
            self.database_url = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

        # Fail fast if the selected provider has no key.
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is required when LLM_PROVIDER=groq. "
                "Copy .env.example to .env and add your key."
            )
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=gemini. "
                "Copy .env.example to .env and add your key."
            )
        return self

    @property
    def active_model(self) -> str:
        return self.groq_model if self.llm_provider == "groq" else self.gemini_model

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Raises ValueError (clear message) if keys are missing."""
    return Settings()
