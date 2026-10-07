"""Runtime schema introspection.

This is *how the agent knows the data*: we read the live schema (tables, columns,
types, foreign keys) and render a compact description for the LLM prompt. Swap the
database and this regenerates - the agent and the guardrail allowlist adapt with
zero code changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.engine import Engine


@dataclass
class SchemaInfo:
    tables: dict[str, list[str]]  # table name -> column names
    ddl: str  # compact schema text for the LLM prompt

    @property
    def table_names(self) -> set[str]:
        return set(self.tables)


def introspect(engine: Engine, exclude_prefix: str = "_") -> SchemaInfo:
    """Introspect the connected DB into a :class:`SchemaInfo`.

    Tables whose name starts with ``exclude_prefix`` (e.g. internal ``_meta``) are
    hidden from the model and excluded from the allowlist.
    """
    insp = inspect(engine)
    tables: dict[str, list[str]] = {}
    lines: list[str] = []

    for tname in sorted(insp.get_table_names()):
        if tname.startswith(exclude_prefix):
            continue
        columns = insp.get_columns(tname)
        tables[tname] = [c["name"] for c in columns]
        col_desc = ", ".join(f'{c["name"]} {c["type"]}' for c in columns)
        lines.append(f"TABLE {tname} ({col_desc})")
        for fk in insp.get_foreign_keys(tname):
            constrained = ",".join(fk.get("constrained_columns", []))
            referred_table = fk.get("referred_table")
            referred = ",".join(fk.get("referred_columns", []))
            if referred_table and constrained:
                lines.append(f"  FK {tname}.{constrained} -> {referred_table}.{referred}")

    return SchemaInfo(tables=tables, ddl="\n".join(lines))
