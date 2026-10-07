"""Pure helpers used by the graph nodes: SQL generation/parsing, chart selection,
result formatting and insight writing. Kept free of graph wiring so they're easy
to unit-test in isolation.
"""

from __future__ import annotations

import json
import re

import pandas as pd

from ..llm.base import LLMProvider
from . import prompts

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_sql_from_response(text: str) -> str:
    """Extract the SQL string from a JSON (or near-JSON) model response."""
    text = (text or "").strip()
    # Strip markdown fences if the model added them.
    if text.startswith("```"):
        text = text.strip("`")
        text = re.sub(r"^(json|sql)\s*", "", text, flags=re.IGNORECASE).strip()

    match = _JSON_BLOCK.search(text)
    if match:
        try:
            payload = json.loads(match.group(0))
            sql = payload.get("sql")
            if isinstance(sql, str) and sql.strip():
                return sql.strip()
        except json.JSONDecodeError:
            pass

    # Fallback: treat the whole thing as SQL if it looks like a query.
    if re.search(r"\bselect\b", text, re.IGNORECASE):
        return text
    raise ValueError("Model response did not contain a SQL query.")


def generate_sql(
    provider: LLMProvider,
    question: str,
    schema: str,
    dictionary: str,
    dialect: str,
    max_rows: int,
    history: list[dict] | None = None,
    prior_sql: str | None = None,
    prior_error: str | None = None,
) -> tuple[str, int]:
    system = prompts.SQL_SYSTEM.format(dialect=dialect, max_rows=max_rows)
    user = prompts.build_sql_user(
        question, schema, dictionary, history=history, prior_sql=prior_sql, prior_error=prior_error
    )
    resp = provider.complete(system, user, json_mode=True)
    return parse_sql_from_response(resp.text), resp.total_tokens


def frame_to_text(frame: pd.DataFrame, max_rows: int = 20) -> str:
    """Compact, dependency-free text table for the insight prompt."""
    if frame is None or frame.empty:
        return "(no rows)"
    shown = frame.head(max_rows).copy()

    # Render numbers in plain decimal (never scientific notation) so the model
    # echoes readable figures like 284,444,913 instead of 2.84e+08.
    def _fmt(v):
        if pd.isna(v):
            return ""
        return f"{v:,.4f}" if abs(v) < 1 else f"{v:,.2f}"

    for col in shown.select_dtypes(include="number").columns:
        shown[col] = shown[col].map(_fmt)

    text = shown.to_string(index=False)
    if len(frame) > max_rows:
        text += f"\n... (+{len(frame) - max_rows} more rows)"
    return text


def write_insight(
    provider: LLMProvider,
    question: str,
    frame: pd.DataFrame,
    sql: str,
) -> tuple[str, int]:
    user = prompts.INSIGHT_USER.format(
        question=question,
        sql=sql,
        rows=0 if frame is None else len(frame),
        table=frame_to_text(frame),
    )
    resp = provider.complete(prompts.INSIGHT_SYSTEM, user, json_mode=False, max_tokens=500)
    return resp.text.strip(), resp.total_tokens


def choose_chart(frame: pd.DataFrame, question: str = "") -> dict | None:
    """Heuristic chart spec (rendered by the UI). None -> show the table only."""
    if frame is None or frame.empty or frame.shape[1] < 2 or len(frame) > 50:
        return None
    numeric = frame.select_dtypes(include="number").columns.tolist()
    categorical = [c for c in frame.columns if c not in numeric]
    if not numeric or not categorical:
        return None

    x, y = categorical[0], numeric[0]
    time_like = any(k in x.lower() for k in ("date", "month", "year", "quarter", "period"))
    return {
        "type": "line" if time_like else "bar",
        "x": x,
        "y": y,
        "title": f"{y.replace('_', ' ').title()} by {x.replace('_', ' ').title()}",
    }
