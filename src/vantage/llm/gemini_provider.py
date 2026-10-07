"""Google Gemini provider (alternate). Enable with LLM_PROVIDER=gemini."""

from __future__ import annotations

import google.generativeai as genai

from .base import LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: int = 30, temperature: float = 0.0) -> None:
        genai.configure(api_key=api_key)
        self._model_name = model
        self._temperature = temperature
        self._timeout = timeout

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        cfg: dict = {"temperature": self._temperature if temperature is None else temperature}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        if max_tokens is not None:
            cfg["max_output_tokens"] = max_tokens

        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=system,
            generation_config=cfg,
        )
        resp = model.generate_content(user, request_options={"timeout": self._timeout})
        usage = getattr(resp, "usage_metadata", None)
        return LLMResponse(
            text=(resp.text or ""),
            prompt_tokens=getattr(usage, "prompt_token_count", 0) if usage else 0,
            completion_tokens=getattr(usage, "candidates_token_count", 0) if usage else 0,
            model=self._model_name,
        )

    def ping(self) -> bool:
        model = genai.GenerativeModel(self._model_name)
        resp = model.generate_content("ping", request_options={"timeout": self._timeout})
        return bool(resp.text)
