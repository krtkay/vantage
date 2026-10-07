"""Metrics for the text-to-SQL agent.

Result-match is a *denotation* check: does the agent return the same answer as a
canonical gold query? It is deliberately tolerant of representation differences
that are NOT correctness errors - column order, extra helper columns, row order,
label decoration ("January" vs "January 2025"), and percent-vs-fraction scaling
(0.1855 vs 18.55). It compares the substance: the set of label (dimension) values
and the set of numeric values.
"""

from __future__ import annotations

import pandas as pd


def _label_values(frame: pd.DataFrame) -> list[str]:
    cats = [c for c in frame.columns if frame[c].dtype == object]
    if not cats:
        return []
    return [str(v).strip().lower() for v in frame[cats[0]].dropna().tolist()]


def _numeric_values(frame: pd.DataFrame) -> list[float]:
    out: list[float] = []
    for col in frame.select_dtypes(include="number").columns:
        out.extend(round(float(v), 2) for v in frame[col].dropna().tolist())
    return out


def _label_score(agent: list[str], gold: list[str]) -> float:
    """Fraction of gold labels matched by an agent label (exact, or substring for
    labels of 3+ chars so 'January' matches 'January 2025')."""
    if not gold:
        return 1.0
    agent_set = set(agent)
    matched = 0
    for g in gold:
        if g in agent_set or (len(g) >= 3 and any(g in a or a in g for a in agent)):
            matched += 1
    return matched / len(gold)


def _numeric_score(agent: list[float], gold: list[float], rel_tol: float = 0.02) -> float:
    """Fraction of gold numbers matched by an agent number at the same or a
    percent-scaled magnitude (handles fraction-vs-percent representations)."""
    if not gold:
        return 1.0 if not agent else 0.5

    def matched(g: float) -> bool:
        return any(
            abs(g * scale - a) <= max(0.5, abs(g * scale) * rel_tol)
            for a in agent
            for scale in (1.0, 100.0, 0.01)
        )

    return sum(1 for g in gold if matched(g)) / len(gold)


def result_match(agent: pd.DataFrame | None, gold: pd.DataFrame | None, threshold: float = 0.6) -> bool:
    if gold is None or gold.empty:
        return agent is None or agent.empty
    if agent is None or agent.empty:
        return False

    gold_labels, gold_nums = _label_values(gold), _numeric_values(gold)
    label_ok = _label_score(_label_values(agent), gold_labels) >= threshold
    numeric_ok = _numeric_score(_numeric_values(agent), gold_nums) >= threshold

    if gold_labels and gold_nums:
        return label_ok and numeric_ok
    if gold_labels:
        return label_ok
    return numeric_ok


def keywords_present(narrative: str, keywords: list[str]) -> bool:
    text = (narrative or "").lower()
    return all(k.lower() in text for k in (keywords or []))
