"""Builds the configured provider and verifies its key with a live ping."""

from __future__ import annotations

from ..config import Settings, get_settings
from .base import LLMProvider


def build_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()

    if settings.llm_provider == "groq":
        from .groq_provider import GroqProvider

        assert settings.groq_api_key is not None  # guaranteed by Settings validator
        return GroqProvider(
            api_key=settings.groq_api_key.get_secret_value(),
            model=settings.groq_model,
            timeout=settings.request_timeout,
            temperature=settings.llm_temperature,
        )

    if settings.llm_provider == "gemini":
        from .gemini_provider import GeminiProvider

        assert settings.gemini_api_key is not None
        return GeminiProvider(
            api_key=settings.gemini_api_key.get_secret_value(),
            model=settings.gemini_model,
            timeout=settings.request_timeout,
            temperature=settings.llm_temperature,
        )

    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


def verify_llm(settings: Settings | None = None) -> bool:
    """Fail-fast check: raises on an invalid key instead of failing mid-query."""
    settings = settings or get_settings()
    return build_provider(settings).ping()
