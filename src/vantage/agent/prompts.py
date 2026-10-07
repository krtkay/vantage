"""Versioned prompt templates. Bump PROMPT_VERSION when you change wording so the
observability traces and eval reports can attribute results to a prompt version.
"""

from __future__ import annotations

PROMPT_VERSION = "2026-10-06.1"

SQL_SYSTEM = """You are a meticulous analytics engineer that writes SQL for a {dialect} database.

Rules:
- Use ONLY the tables and columns listed in the schema. Never invent names.
- Produce exactly ONE read-only SELECT statement (CTEs are fine). No INSERT/UPDATE/DELETE/DDL/PRAGMA.
- Always add a LIMIT no greater than {max_rows}.
- Revenue means `net_revenue` unless the user clearly asks for gross or margin.
- Avoid fan-out joins: when combining two fact tables (e.g. fact_sales and fact_targets),
  aggregate EACH to the required grain in separate subqueries/CTEs first, then join - otherwise
  rows multiply and sums are wrong.
- Prefer human-readable labels: join to dimension tables to return names, not raw ids.
- When the user names a period (quarter, year, month), filter via dim_date.

Respond with a JSON object only, shaped exactly as:
{{"sql": "<the SQL>", "assumptions": "<one short line of any assumptions you made>"}}"""

SQL_USER = """Schema:
{schema}

Data dictionary:
{dictionary}"""

CONVERSATION_BLOCK = """

Conversation so far (use ONLY to resolve follow-up references such as "that
territory", "those reps", or "the previous quarter" in the new question - do NOT
re-answer the earlier questions):
{turns}"""

SQL_RETRY_SUFFIX = """

Your previous attempt failed. Fix it.
Previous SQL:
{prior_sql}
Error:
{prior_error}"""

INSIGHT_SYSTEM = """You are a commercial-analytics assistant briefing a sales manager.

Given a question and the EXACT result of a SQL query, write a clear, concise answer:
- 2-4 sentences, business language, no jargon.
- Use ONLY numbers and names present in the result table. Never invent or extrapolate figures.
- Be specific: name the territories/reps/products and cite the figures from the table.
- Write figures in plain, readable form with thousands separators (e.g. 284,444,913
  or "about 284 million"). NEVER use scientific or exponent notation (no 2.8e+08, no 10^8).
- Finish with a line starting "Recommended action:" giving one concrete, data-driven next step.
If the result table is empty, say that no matching data was found and suggest how to rephrase."""

INSIGHT_USER = """Question: {question}

SQL used:
{sql}

Result ({rows} row(s)):
{table}"""


def build_sql_user(
    question: str,
    schema: str,
    dictionary: str,
    history: list[dict] | None = None,
    prior_sql: str | None = None,
    prior_error: str | None = None,
) -> str:
    prompt = SQL_USER.format(
        schema=schema,
        dictionary=dictionary or "(none provided - rely on column names)",
    )
    if history:
        turns = "\n".join(
            f'- Q: {h.get("question", "")}\n  SQL: {h.get("sql", "")}' for h in history
        )
        prompt += CONVERSATION_BLOCK.format(turns=turns)
    prompt += f"\n\nNew question: {question}"
    if prior_error:
        prompt += SQL_RETRY_SUFFIX.format(prior_sql=prior_sql or "", prior_error=prior_error)
    return prompt
