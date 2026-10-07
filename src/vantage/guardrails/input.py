"""Input-stage guardrail: length, emptiness, and prompt-injection screening.

This is a cheap first line of defence. The authoritative protection against
destructive SQL lives in :mod:`vantage.guardrails.sql` and the read-only connection.
"""

from __future__ import annotations

import re

from .errors import InputRejected

MAX_QUESTION_CHARS = 500

_INJECTION_PATTERNS = [
    r"ignore (?:all|the|your|previous|above) .{0,20}instructions",
    r"disregard .{0,20}instructions",
    r"system prompt",
    r"you are now",
    r"\bdrop\s+table\b",
    r"\bdelete\s+from\b",
    r"\btruncate\b",
    r"\bupdate\s+\w+\s+set\b",
]
_INJECTION = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def check_input(question: str) -> str:
    """Return the cleaned question, or raise :class:`InputRejected`."""
    cleaned = (question or "").strip()
    if not cleaned:
        raise InputRejected("Please enter a question about the sales data.")
    if len(cleaned) > MAX_QUESTION_CHARS:
        raise InputRejected(
            f"That question is too long (>{MAX_QUESTION_CHARS} characters). Please shorten it."
        )
    if _INJECTION.search(cleaned):
        raise InputRejected(
            "Your question looks like it contains instructions rather than a data "
            "question. Please ask about territories, reps, products, sales or targets."
        )
    return cleaned
