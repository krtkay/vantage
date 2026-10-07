"""SQL guardrail - the most important safety component.

Uses sqlglot to *parse* (not regex) the generated SQL and enforce:
  1. exactly one statement,
  2. it is a read query (SELECT / CTE / set-operation),
  3. no write/DDL/command node anywhere in the tree,
  4. every referenced table is in the allowlist (derived from the live schema),
  5. a LIMIT is present and capped at ``max_rows``.

Returns the normalised, safe SQL string. Raises :class:`UnsafeSQLError` otherwise.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from .errors import UnsafeSQLError

# Build the forbidden-node tuple from names that exist in the installed sqlglot,
# so this stays robust across versions.
_FORBIDDEN_NAMES = [
    "Insert", "Update", "Delete", "Drop", "Create", "Alter",
    "TruncateTable", "Merge", "Command", "Set", "Use", "Pragma",
]
_FORBIDDEN = tuple(getattr(exp, n) for n in _FORBIDDEN_NAMES if hasattr(exp, n))

# Allowed top-level read expressions (CTEs parse as Select with a `with` arg).
_ALLOWED_TOP = (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)


def validate_sql(
    sql: str,
    allowed_tables: set[str],
    dialect: str = "sqlite",
    max_rows: int = 1000,
) -> str:
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQLError("No SQL was produced.")

    try:
        statements = [s for s in sqlglot.parse(cleaned, read=dialect) if s is not None]
    except Exception as exc:  # noqa: BLE001
        raise UnsafeSQLError(f"Could not parse SQL: {exc}") from exc

    if len(statements) != 1:
        raise UnsafeSQLError("Only a single SQL statement is allowed.")
    stmt = statements[0]

    if not isinstance(stmt, _ALLOWED_TOP):
        raise UnsafeSQLError("Only read-only SELECT queries are allowed.")

    for forbidden in _FORBIDDEN:
        if stmt.find(forbidden) is not None:
            raise UnsafeSQLError("Query contains a non-read operation and was blocked.")

    # Names introduced by CTEs are local aliases, not real tables - exclude them.
    cte_names = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    used = {t.name for t in stmt.find_all(exp.Table) if t.name}
    unknown = sorted(t for t in used if t not in allowed_tables and t not in cte_names)
    if unknown:
        raise UnsafeSQLError(f"Query references unknown tables: {unknown}")

    stmt = _enforce_limit(stmt, max_rows)
    return stmt.sql(dialect=dialect)


def _enforce_limit(stmt: exp.Expression, max_rows: int) -> exp.Expression:
    """Inject a LIMIT if absent, or cap an existing one at ``max_rows``."""
    if not hasattr(stmt, "limit"):
        return stmt
    existing = stmt.args.get("limit")
    if existing is None:
        try:
            return stmt.limit(max_rows)
        except Exception:  # noqa: BLE001
            return stmt
    try:
        current = int(existing.expression.this)
        if current > max_rows:
            return stmt.limit(max_rows)
    except Exception:  # noqa: BLE001
        pass
    return stmt
