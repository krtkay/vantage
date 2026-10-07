from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from vantage.data import dialect_of, run_query


def test_introspect_finds_all_tables(schema):
    expected = {
        "dim_date", "dim_region", "dim_territory", "dim_rep", "dim_product",
        "dim_account", "fact_sales", "fact_targets", "fact_activity",
    }
    assert expected <= schema.table_names
    assert "_meta" not in schema.table_names  # internal table hidden
    assert "net_revenue" in schema.tables["fact_sales"]


def test_run_query_returns_rows(engine):
    df = run_query(engine, "SELECT COUNT(*) AS n FROM fact_sales", max_rows=10)
    assert df["n"].iloc[0] > 0


def test_dialect(engine):
    assert dialect_of(engine) == "sqlite"


def test_row_cap_enforced(engine):
    df = run_query(engine, "SELECT * FROM fact_sales", max_rows=5)
    assert len(df) == 5


def test_connection_is_read_only(engine):
    # PRAGMA query_only must make writes fail even outside the guardrail.
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA query_only = ON")
        with pytest.raises(OperationalError):
            conn.exec_driver_sql("DELETE FROM fact_sales")
