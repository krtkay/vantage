from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import metrics  # noqa: E402


def test_result_match_tolerant_to_extra_columns_and_order():
    gold = pd.DataFrame({"territory": ["A", "B"], "rev": [100.0, 200.0]})
    agent = pd.DataFrame({"territory": ["B", "A"], "rev": [200.0, 100.0], "extra": [1, 2]})
    assert metrics.result_match(agent, gold)


def test_result_match_false_for_disjoint():
    gold = pd.DataFrame({"territory": ["A", "B"], "rev": [100.0, 200.0]})
    agent = pd.DataFrame({"territory": ["X", "Y"], "rev": [1.0, 2.0]})
    assert not metrics.result_match(agent, gold)


def test_result_match_empty_both():
    assert metrics.result_match(pd.DataFrame(), pd.DataFrame())


def test_keywords_present():
    assert metrics.keywords_present("Top territory is North", ["territory"])
    assert not metrics.keywords_present("No data", ["territory"])
