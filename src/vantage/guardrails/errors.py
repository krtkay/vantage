"""Guardrail exception hierarchy."""

from __future__ import annotations


class GuardrailError(Exception):
    """Base class for all guardrail violations."""


class InputRejected(GuardrailError):
    """The user's question failed an input-stage check."""


class UnsafeSQLError(GuardrailError):
    """Generated SQL is not a safe, single read-only statement."""
