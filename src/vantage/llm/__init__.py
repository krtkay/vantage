"""Provider-agnostic LLM layer. Swap Groq <-> Gemini via config; both are
API-key-based. The agent nodes depend only on the ``LLMProvider`` interface."""

from .base import LLMProvider, LLMResponse
from .factory import build_provider, verify_llm

__all__ = ["LLMProvider", "LLMResponse", "build_provider", "verify_llm"]
