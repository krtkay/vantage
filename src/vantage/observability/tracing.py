"""Lightweight span tracer.

Each span logs start/end with a millisecond duration (structured JSON). If
Langfuse credentials are configured *and* the SDK is installed, a client is also
initialised for richer tracing; otherwise the tracer is a no-op beyond logging,
so the project runs on the minimal dependency set.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from .logging import get_logger

log = get_logger("trace")


class Tracer:
    def __init__(self, settings: Any) -> None:
        self._client = None
        if getattr(settings, "langfuse_enabled", False):
            try:  # optional dependency - degrade gracefully
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=settings.langfuse_public_key.get_secret_value(),
                    secret_key=settings.langfuse_secret_key.get_secret_value(),
                    host=settings.langfuse_host,
                )
                log.info("langfuse_enabled", host=settings.langfuse_host)
            except Exception as exc:  # noqa: BLE001 - never let tracing break the app
                log.warning("langfuse_init_failed", error=str(exc))

    @contextmanager
    def span(self, name: str, **fields: Any):
        start = time.perf_counter()
        log.info("span_start", span=name, **fields)
        try:
            yield
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log.info("span_end", span=name, duration_ms=duration_ms)

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:  # noqa: BLE001
                pass
