"""The generator must be deterministic - the golden dataset depends on it."""

from __future__ import annotations

import sqlite3

from conftest import build_tiny_db


def _sales_fingerprint(path: str) -> tuple[int, float]:
    conn = sqlite3.connect(path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
        total = conn.execute("SELECT ROUND(SUM(net_revenue), 2) FROM fact_sales").fetchone()[0]
        return n, round(float(total), 2)
    finally:
        conn.close()


def test_same_seed_is_identical(tmp_path):
    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    build_tiny_db(str(a), seed=11)
    build_tiny_db(str(b), seed=11)
    assert _sales_fingerprint(str(a)) == _sales_fingerprint(str(b))


def test_different_seed_differs(tmp_path):
    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    build_tiny_db(str(a), seed=1)
    build_tiny_db(str(b), seed=2)
    assert _sales_fingerprint(str(a)) != _sales_fingerprint(str(b))
