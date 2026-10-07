from __future__ import annotations

import pandas as pd
import pytest

from vantage.agent.tools import choose_chart, parse_sql_from_response
from vantage.config import Settings


# --- SQL parsing ---------------------------------------------------------- #
def test_parse_json_response():
    assert parse_sql_from_response('{"sql": "SELECT 1", "assumptions": ""}') == "SELECT 1"


def test_parse_fenced_response():
    assert "SELECT" in parse_sql_from_response("```json\n{\"sql\": \"SELECT 1\"}\n```")


def test_parse_raw_select():
    assert "SELECT" in parse_sql_from_response("SELECT rep_id FROM fact_sales")


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_sql_from_response("this is not sql")


# --- chart selection ------------------------------------------------------ #
def test_chart_bar_for_category_numeric():
    df = pd.DataFrame({"territory": ["A", "B"], "rev": [10.0, 20.0]})
    spec = choose_chart(df)
    assert spec and spec["type"] == "bar"


def test_chart_line_for_time():
    df = pd.DataFrame({"month_name": ["Jan", "Feb"], "rev": [1.0, 2.0]})
    spec = choose_chart(df)
    assert spec and spec["type"] == "line"


def test_chart_none_when_no_category():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    assert choose_chart(df) is None


# --- config / key verification -------------------------------------------- #
def test_missing_key_raises():
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_provider="groq", groq_api_key=None)


def test_defaults_applied_with_key():
    s = Settings(_env_file=None, llm_provider="groq", groq_api_key="test-key")
    assert s.database_url.startswith("sqlite:///")
    assert s.active_model == s.groq_model
