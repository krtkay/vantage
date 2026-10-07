"""Database engine + safe query execution.

Read-only is enforced in depth: the SQL guardrail only ever lets SELECTs through,
and *here* the connection itself is put in read-only mode (SQLite ``PRAGMA
query_only``; Postgres ``SET TRANSACTION READ ONLY``) with a statement timeout.
Even a hypothetical guardrail bypass cannot write.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def make_engine(database_url: str) -> Engine:
    """Create an engine for any SQLAlchemy URL (sqlite/postgresql/mysql/...)."""
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        # Streamlit reruns across threads; allow cross-thread use of the connection.
        connect_args = {"check_same_thread": False}
    return create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)


def dialect_of(engine: Engine) -> str:
    """Normalised dialect name for the LLM prompt and sqlglot (`postgres`/`sqlite`/`mysql`)."""
    name = engine.dialect.name
    return {"postgresql": "postgres"}.get(name, name)


def run_query(
    engine: Engine,
    sql: str,
    timeout_seconds: int = 15,
    max_rows: int = 1000,
) -> pd.DataFrame:
    """Execute a (pre-validated) SELECT read-only, with a timeout and row cap."""
    with engine.connect() as conn:
        name = engine.dialect.name
        if name == "sqlite":
            conn.exec_driver_sql("PRAGMA query_only = ON")
            conn.exec_driver_sql(f"PRAGMA busy_timeout = {int(timeout_seconds) * 1000}")
        elif name == "postgresql":
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET statement_timeout = {int(timeout_seconds) * 1000}")
        elif name == "mysql":
            conn.exec_driver_sql(f"SET SESSION max_execution_time = {int(timeout_seconds) * 1000}")

        frame = pd.read_sql(text(sql), conn)

    # Final safety net: never hand back more than the cap, whatever the SQL said.
    if len(frame) > max_rows:
        frame = frame.head(max_rows)
    return frame
