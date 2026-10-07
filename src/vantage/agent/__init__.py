"""The analytics agent: a LangGraph state machine that turns a question into a
safe SQL query, a result, a chart spec and a grounded narrative."""

from .graph import AnalyticsAgent
from .state import AgentResult

__all__ = ["AnalyticsAgent", "AgentResult"]
