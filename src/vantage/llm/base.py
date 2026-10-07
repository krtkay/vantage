"""The interface every LLM provider implements. Keeping this tiny is deliberate:
the agent only needs text completion (+ optional JSON mode) and a health ping."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Single-turn completion. ``json_mode`` asks the model for a JSON object."""

    @abstractmethod
    def ping(self) -> bool:
        """Cheap liveness check used for fail-fast key verification at startup."""
