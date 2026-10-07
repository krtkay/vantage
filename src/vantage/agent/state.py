"""Graph state (mutable, passed between nodes) and the public result object."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

import pandas as pd


class AgentState(TypedDict, total=False):
    question: str
    history: list  # prior turns [{"question", "sql"}, ...] for follow-up context
    rejected: str | None
    sql: str | None
    error: str | None
    retries: int
    result: Any  # pd.DataFrame
    row_count: int
    chart: dict | None
    narrative: str
    ungrounded: list
    tokens: int


@dataclass
class AgentResult:
    question: str
    narrative: str = ""
    sql: str | None = None
    dataframe: pd.DataFrame | None = None
    row_count: int = 0
    chart: dict | None = None
    rejected: str | None = None
    error: str | None = None
    retries: int = 0
    ungrounded: list = field(default_factory=list)
    tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.rejected is None and self.error is None
