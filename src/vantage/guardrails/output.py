"""Output-stage guardrail: numeric grounding.

Heuristic check that flags numbers in the narrative that cannot be traced to the
result set - a cheap hallucination tripwire. It *flags* (returns a list) rather
than blocking. Matching is magnitude-aware (the model may say "284 million" for
284,444,913) and ignores years and percentages (usually derived, not raw cells).
"""

from __future__ import annotations

import re

import pandas as pd

# Captures a number and whether a '%' immediately follows it. The lookbehind
# skips digits embedded in identifiers like "T-042" or "SKU-1203" (codes, not data).
_NUMBER = re.compile(r"(?<![\w-])(-?\d[\d,]*\.?\d*)(\s*%)?")
_TRIVIAL = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 100, 1000}
# Magnitudes to try so "284" / "284 million" both match 284,444,913.
_SCALES = (1, 1e2, 1e3, 1e5, 1e6, 1e7, 1e8, 1e9)


def _numbers(text: str) -> list[tuple[float, bool]]:
    out: list[tuple[float, bool]] = []
    for match in _NUMBER.finditer(text or ""):
        token, is_pct = match.group(1), bool(match.group(2))
        try:
            out.append((float(token.replace(",", "")), is_pct))
        except ValueError:
            continue
    return out


def check_grounding(narrative: str, frame: pd.DataFrame | None, rel_tol: float = 0.02) -> list[float]:
    """Return numbers in ``narrative`` not traceable (within tolerance) to ``frame``."""
    if frame is None or frame.empty:
        return []

    values: set[float] = set()
    for col in frame.select_dtypes(include="number").columns:
        for value in frame[col].dropna().tolist():
            values.add(round(float(value), 2))
    if not values:
        return []

    def is_year(n: float) -> bool:
        return float(n).is_integer() and 1900 <= n <= 2100

    def grounded(n: float) -> bool:
        return any(
            abs(n * scale - v) <= max(0.5, abs(v) * rel_tol)
            for v in values
            for scale in _SCALES
        )

    return [
        n for n, is_pct in _numbers(narrative)
        if n not in _TRIVIAL and not is_pct and not is_year(n) and not grounded(n)
    ]
