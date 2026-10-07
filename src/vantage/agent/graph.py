r"""The analytics agent as a LangGraph ``StateGraph``.

Flow::

    START -> guard_input --(rejected)--> END
                 |(ok)
                 v
            generate_sql <-----------------+
                 |                          | (retry: bad SQL / exec error,
                 v                          |  within max_retries)
            execute --(error)---------------+
                 |(ok)            \(exhausted)
                 v                 v
            summarize            fail
                 |                 |
                 v                 v
                END               END

LangGraph owns the control flow and the conditional retry edge; the LLM layer
stays vendor-agnostic underneath (Groq/Gemini via :mod:`vantage.llm`).
"""

from __future__ import annotations

import time

from langgraph.graph import END, START, StateGraph

from ..config import Settings, get_settings
from ..data import dialect_of, format_dictionary, introspect, load_dictionary, make_engine, run_query
from ..guardrails import UnsafeSQLError, check_grounding, check_input, validate_sql
from ..guardrails.errors import InputRejected
from ..llm import build_provider
from ..observability import Tracer, configure_logging, get_logger
from . import tools
from .state import AgentResult, AgentState

log = get_logger("agent")


class AnalyticsAgent:
    """Builds its dependencies once (engine, schema, provider) and compiles the graph."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        configure_logging(self.settings.log_level)

        self.provider = build_provider(self.settings)
        self.engine = make_engine(self.settings.database_url)
        self.schema = introspect(self.engine)
        self.dictionary = format_dictionary(load_dictionary(self.settings.data_dictionary_path))
        self.dialect = dialect_of(self.engine)
        self.tracer = Tracer(self.settings)
        self._cache: dict[str, AgentResult] = {}

        self._graph = self._build_graph()
        log.info(
            "agent_ready",
            provider=self.provider.name,
            model=self.settings.active_model,
            dialect=self.dialect,
            tables=sorted(self.schema.table_names),
        )

    # ------------------------------------------------------------------ nodes
    def _node_guard_input(self, state: AgentState) -> dict:
        try:
            return {"question": check_input(state["question"])}
        except InputRejected as exc:
            return {"rejected": str(exc)}

    def _node_generate_sql(self, state: AgentState) -> dict:
        with self.tracer.span("generate_sql", retry=state.get("retries", 0)):
            sql, tokens = tools.generate_sql(
                self.provider,
                state["question"],
                self.schema.ddl,
                self.dictionary,
                self.dialect,
                self.settings.max_sql_rows,
                history=state.get("history"),
                prior_sql=state.get("sql"),
                prior_error=state.get("error"),
            )
        return {"sql": sql, "tokens": state.get("tokens", 0) + tokens}

    def _node_execute(self, state: AgentState) -> dict:
        try:
            safe_sql = validate_sql(
                state["sql"], self.schema.table_names, self.dialect, self.settings.max_sql_rows
            )
        except UnsafeSQLError as exc:
            log.warning("sql_guardrail_block", error=str(exc), retries=state.get("retries", 0))
            return {"error": f"Guardrail: {exc}", "retries": state.get("retries", 0) + 1}

        try:
            with self.tracer.span("execute_sql"):
                frame = run_query(
                    self.engine,
                    safe_sql,
                    self.settings.query_timeout_seconds,
                    self.settings.max_sql_rows,
                )
        except Exception as exc:  # noqa: BLE001 - surfaced to the model for self-correction
            log.warning("sql_execution_error", error=str(exc), retries=state.get("retries", 0))
            return {
                "sql": safe_sql,
                "error": f"Execution error: {type(exc).__name__}: {exc}",
                "retries": state.get("retries", 0) + 1,
            }

        return {"sql": safe_sql, "result": frame, "row_count": len(frame), "error": None}

    def _node_summarize(self, state: AgentState) -> dict:
        frame = state.get("result")
        chart = tools.choose_chart(frame, state["question"])
        with self.tracer.span("write_insight"):
            narrative, tokens = tools.write_insight(
                self.provider, state["question"], frame, state["sql"]
            )
        ungrounded = check_grounding(narrative, frame)
        if ungrounded:
            log.warning("ungrounded_numbers", values=ungrounded)
        return {
            "chart": chart,
            "narrative": narrative,
            "ungrounded": ungrounded,
            "tokens": state.get("tokens", 0) + tokens,
        }

    def _node_fail(self, state: AgentState) -> dict:
        return {
            "narrative": (
                "I couldn't produce a reliable answer for that question after "
                f"{state.get('retries', 0)} attempts. Try rephrasing or being more specific. "
                f"(last issue: {state.get('error')})"
            )
        }

    # ------------------------------------------------------------------ edges
    def _route_after_input(self, state: AgentState) -> str:
        return "rejected" if state.get("rejected") else "ok"

    def _route_after_execute(self, state: AgentState) -> str:
        if not state.get("error"):
            return "ok"
        return "retry" if state.get("retries", 0) <= self.settings.max_retries else "fail"

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("guard_input", self._node_guard_input)
        graph.add_node("generate_sql", self._node_generate_sql)
        graph.add_node("execute", self._node_execute)
        graph.add_node("summarize", self._node_summarize)
        graph.add_node("fail", self._node_fail)

        graph.add_edge(START, "guard_input")
        graph.add_conditional_edges(
            "guard_input", self._route_after_input, {"rejected": END, "ok": "generate_sql"}
        )
        graph.add_edge("generate_sql", "execute")
        graph.add_conditional_edges(
            "execute",
            self._route_after_execute,
            {"retry": "generate_sql", "ok": "summarize", "fail": "fail"},
        )
        graph.add_edge("summarize", END)
        graph.add_edge("fail", END)
        return graph.compile()

    # ------------------------------------------------------------------ public
    def answer(
        self,
        question: str,
        history: list[dict] | None = None,
        use_cache: bool | None = None,
    ) -> AgentResult:
        """Answer a question. ``history`` is a list of prior turns
        ``[{"question": str, "sql": str}, ...]`` used to resolve follow-up
        references; pass the last few turns for multi-turn conversations."""
        use_cache = self.settings.enable_cache if use_cache is None else use_cache
        history = history or []
        # Cache key includes the conversation context so follow-ups don't collide
        # with the same text asked fresh.
        hist_sig = "|".join((h.get("question", "")).strip().lower() for h in history)
        key = f"{hist_sig}>>{(question or '').strip().lower()}"
        if use_cache and key in self._cache:
            cached = self._cache[key]
            return AgentResult(**{**cached.__dict__, "cached": True})

        start = time.perf_counter()
        final: AgentState = self._graph.invoke(
            {"question": question, "retries": 0, "tokens": 0, "history": history}
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        self.tracer.flush()

        result = AgentResult(
            question=question,
            narrative=final.get("rejected") or final.get("narrative", ""),
            sql=final.get("sql"),
            dataframe=final.get("result"),
            row_count=final.get("row_count", 0),
            chart=final.get("chart"),
            rejected=final.get("rejected"),
            error=final.get("error") if not final.get("row_count") else None,
            retries=final.get("retries", 0),
            ungrounded=final.get("ungrounded", []),
            tokens=final.get("tokens", 0),
            latency_ms=latency_ms,
        )
        log.info(
            "answer_done",
            ok=result.ok,
            rows=result.row_count,
            retries=result.retries,
            tokens=result.tokens,
            latency_ms=latency_ms,
        )
        if use_cache and result.ok:
            self._cache[key] = result
        return result
