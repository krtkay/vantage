"""SQL guardrail: the most safety-critical component."""

from __future__ import annotations

import pytest

from vantage.guardrails import UnsafeSQLError, validate_sql

ALLOWED = {"fact_sales", "dim_rep", "dim_territory", "dim_date", "fact_targets"}


def test_allows_plain_select_and_injects_limit():
    out = validate_sql("SELECT rep_id FROM fact_sales", ALLOWED, "sqlite", max_rows=100)
    assert "LIMIT" in out.upper()


def test_allows_cte():
    sql = (
        "WITH a AS (SELECT rep_id, SUM(net_revenue) r FROM fact_sales GROUP BY rep_id) "
        "SELECT * FROM a ORDER BY r DESC"
    )
    out = validate_sql(sql, ALLOWED, "sqlite", max_rows=50)
    assert out  # no exception


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM fact_sales",
        "DROP TABLE dim_rep",
        "INSERT INTO fact_sales (rep_id) VALUES (1)",
        "UPDATE fact_sales SET units = 0",
        "CREATE TABLE x (id INT)",
    ],
)
def test_blocks_write_operations(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql, ALLOWED, "sqlite")


def test_blocks_unknown_table():
    with pytest.raises(UnsafeSQLError):
        validate_sql("SELECT * FROM secret_table", ALLOWED, "sqlite")


def test_blocks_multiple_statements():
    with pytest.raises(UnsafeSQLError):
        validate_sql("SELECT 1 FROM fact_sales; DROP TABLE dim_rep", ALLOWED, "sqlite")


def test_caps_large_limit():
    out = validate_sql("SELECT rep_id FROM fact_sales LIMIT 999999", ALLOWED, "sqlite", max_rows=1000)
    assert "1000" in out
    assert "999999" not in out
