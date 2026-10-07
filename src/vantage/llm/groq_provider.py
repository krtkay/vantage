"""Groq provider (default). Fast inference on Llama 3.3 70B; supports JSON mode."""

from __future__ import annotations

from groq import Groq

from .base import LLMProvider, LLMResponse


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: int = 30, temperature: float = 0.0) -> None:
        self._client = Groq(api_key=api_key, timeout=timeout)
        self._model = model
        self._temperature = temperature

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        extra: dict = {}
        if json_mode:
            extra["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            extra["max_tokens"] = max_tokens

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self._temperature if temperature is None else temperature,
            **extra,
        )
        usage = resp.usage
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=self._model,
        )

    def ping(self) -> bool:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return bool(resp.choices)
