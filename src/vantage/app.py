"""Streamlit UI for the Vantage analytics agent.

Features:
- Multiple independent conversations (sidebar), each retaining its own context.
- A polished, themed look (hero header, KPI cards, styled chat + charts).

Run:  streamlit run src/vantage/app.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

# Make `vantage` importable whether or not the package is pip-installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from vantage.agent import AnalyticsAgent  # noqa: E402
from vantage.config import get_settings  # noqa: E402
from vantage.data import make_engine, run_query  # noqa: E402

EXAMPLE_QUESTIONS = [
    "Which 5 territories had the highest net revenue in 2025?",
    "Show total net revenue by quarter for 2025.",
    "Which reps are furthest below their revenue target this year?",
    "What are the top 5 products by margin?",
    "Compare net revenue by account tier.",
    "Which regions grew the most from 2024 to 2025?",
]

MAX_CONTEXT_TURNS = 3
CHART_COLORS = ["#7C8CF8", "#34D399", "#F59E0B", "#F472B6", "#22D3EE", "#A78BFA"]

st.set_page_config(
    page_title="Vantage · Commercial Analytics Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{
  --bg:#0B0F19; --panel:#151A28; --card:#1B2233; --border:#2A3348;
  --text:#E8ECF4; --muted:#9AA4B8; --accent:#7C8CF8;
}
html, body, .stApp, [class*="css"]{ font-family:'Inter',system-ui,sans-serif; }
.stApp{ background:radial-gradient(1200px 600px at 18% -12%, #1a2140 0%, #0B0F19 48%) fixed; }
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer{ display:none !important; }
[data-testid="stHeader"]{ background:transparent; }
.block-container{ padding-top:1.4rem; padding-bottom:3rem; max-width:1160px; }

.vtg-hero{
  background:linear-gradient(120deg,#6366F1 0%,#8B5CF6 52%,#22D3EE 130%);
  border-radius:18px; padding:22px 28px; margin-bottom:18px;
  box-shadow:0 14px 44px rgba(99,102,241,.28);
}
.vtg-hero h1{ color:#fff; font-size:1.65rem; font-weight:800; margin:0; letter-spacing:-.02em; }
.vtg-hero p{ color:rgba(255,255,255,.92); margin:.3rem 0 0; font-size:.95rem; }

[data-testid="stMetric"]{
  background:var(--card); border:1px solid var(--border); border-radius:14px;
  padding:14px 16px; box-shadow:0 4px 18px rgba(0,0,0,.25);
}
[data-testid="stMetricLabel"] p{ color:var(--muted); font-weight:600; font-size:.78rem; text-transform:uppercase; letter-spacing:.03em; }
[data-testid="stMetricValue"]{ color:var(--text); font-weight:800; }

.stButton>button{
  border-radius:10px; border:1px solid var(--border); background:var(--panel);
  color:var(--text); font-weight:600; transition:all .15s ease;
}
.stButton>button:hover{ border-color:var(--accent); color:#fff; transform:translateY(-1px); }

[data-testid="stChatMessage"]{
  background:var(--panel); border:1px solid var(--border); border-radius:14px;
  padding:2px 12px; margin-bottom:8px; box-shadow:0 2px 12px rgba(0,0,0,.18);
}
[data-testid="stSidebar"]{ background:#0D1220; border-right:1px solid var(--border); }
[data-testid="stSidebar"] .stButton>button{ text-align:left; background:transparent; border-color:transparent; }
[data-testid="stSidebar"] .stButton>button:hover{ background:var(--panel); border-color:var(--border); }
[data-testid="stDataFrame"]{ border:1px solid var(--border); border-radius:12px; }
[data-testid="stExpander"]{ border:1px solid var(--border); border-radius:12px; background:var(--panel); }
.vtg-pill{ color:var(--muted); font-size:.85rem; }
</style>
"""


def fmt_money(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"₹{value / 1e7:,.0f} Cr"


@st.cache_data(show_spinner=False)
def load_kpis(db_url: str) -> dict:
    eng = make_engine(db_url)
    sql = """
        WITH yrs AS (SELECT MAX(year) AS my FROM dim_date)
        SELECT
          (SELECT SUM(net_revenue) FROM fact_sales s JOIN dim_date d ON s.date_id=d.date_id
             WHERE d.year=(SELECT my FROM yrs)) AS rev_latest,
          (SELECT SUM(net_revenue) FROM fact_sales s JOIN dim_date d ON s.date_id=d.date_id
             WHERE d.year=(SELECT my-1 FROM yrs)) AS rev_prev,
          (SELECT my FROM yrs) AS latest_year,
          (SELECT COUNT(*) FROM dim_rep) AS reps,
          (SELECT COUNT(*) FROM dim_territory) AS territories,
          (SELECT COUNT(*) FROM dim_product) AS products
    """
    row = run_query(eng, sql, max_rows=1).iloc[0].to_dict()
    rl, rp = row.get("rev_latest"), row.get("rev_prev")
    row["yoy"] = ((rl - rp) / rp * 100) if (rl and rp) else None
    return row


@st.cache_resource(show_spinner="Starting the analytics agent…")
def load_agent() -> AnalyticsAgent:
    return AnalyticsAgent()


# --------------------------------------------------------------------------- #
# Conversation (session) management
# --------------------------------------------------------------------------- #
def _new_conversation() -> str:
    cid = uuid.uuid4().hex[:8]
    st.session_state["conversations"][cid] = {"title": "New chat", "history": []}
    st.session_state["active"] = cid
    return cid


def _init_conversations() -> None:
    if "conversations" not in st.session_state:
        st.session_state["conversations"] = {}
    if not st.session_state["conversations"]:
        _new_conversation()
    if st.session_state.get("active") not in st.session_state["conversations"]:
        st.session_state["active"] = next(iter(st.session_state["conversations"]))


def _active() -> dict:
    return st.session_state["conversations"][st.session_state["active"]]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render_chart(spec: dict, frame: pd.DataFrame) -> None:
    try:
        if spec["type"] == "line":
            fig = px.line(frame, x=spec["x"], y=spec["y"], title=spec["title"], markers=True)
        else:
            fig = px.bar(frame, x=spec["x"], y=spec["y"], title=spec["title"])
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#C8D0E0", family="Inter"),
            colorway=CHART_COLORS,
            margin=dict(l=10, r=10, t=48, b=10),
            title_font=dict(size=16, color="#E8ECF4"),
            xaxis=dict(gridcolor="#2A3348", zeroline=False),
            yaxis=dict(gridcolor="#2A3348", zeroline=False),
        )
        fig.update_traces(marker_line_width=0)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:  # noqa: BLE001
        st.caption(f"(Chart unavailable: {exc})")


def render_result(result) -> None:
    if result.rejected:
        st.warning(result.narrative)
        return

    st.markdown(result.narrative or "_(no answer)_")
    if result.ungrounded:
        st.warning(f"⚠️ Numbers not found in the data (verify): {result.ungrounded}")
    if result.chart is not None and result.dataframe is not None:
        render_chart(result.chart, result.dataframe)
    if result.dataframe is not None and not result.dataframe.empty:
        st.dataframe(result.dataframe, use_container_width=True, hide_index=True)

    badge = "⚡ cached" if result.cached else f"{result.latency_ms:.0f} ms"
    header = f"🔎 SQL & details · {result.row_count} rows · {result.retries} retries · {result.tokens} tokens · {badge}"
    with st.expander(header):
        if result.sql:
            st.code(result.sql, language="sql")
        if result.error:
            st.error(result.error)


# --------------------------------------------------------------------------- #
# Cloud helpers
# --------------------------------------------------------------------------- #
def _bridge_streamlit_secrets() -> None:
    """Expose Streamlit Cloud dashboard secrets as env vars so pydantic-settings
    (which reads env/.env) picks them up. No-op locally when no secrets exist."""
    try:
        for key, value in st.secrets.items():
            os.environ.setdefault(key, str(value))
    except Exception:  # noqa: BLE001 - st.secrets raises when nothing is configured
        pass


def _ensure_database(settings) -> None:
    """Generate the SQLite DB on first run if missing (e.g. a fresh cloud deploy
    where the .db is git-ignored)."""
    if not settings.database_url.startswith("sqlite"):
        return
    db_path = settings.database_url.replace("sqlite:///", "")
    if Path(db_path).exists():
        return
    scale = os.environ.get("AUTO_SEED_SCALE", "small")
    generator = Path(__file__).resolve().parents[2] / "seed" / "generate_data.py"
    with st.spinner(f"First run — generating the sample database ({scale})… this takes a few seconds."):
        subprocess.run([sys.executable, str(generator), "--scale", scale, "--out", db_path], check=True)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    _bridge_streamlit_secrets()

    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Configuration error: {exc}")
        st.info("On Streamlit Cloud, add GROQ_API_KEY in the app's Secrets. Locally, copy .env.example to .env.")
        st.stop()

    try:
        _ensure_database(settings)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not prepare the database: {exc}")
        st.code("python seed/generate_data.py --scale rich", language="bash")
        st.stop()

    try:
        agent = load_agent()
        kpis = load_kpis(settings.database_url)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not start the agent: {exc}")
        st.stop()

    _init_conversations()
    conv = _active()

    # ---- Hero ----
    st.markdown(
        '<div class="vtg-hero"><h1>📊 Vantage</h1>'
        "<p>Ask about commercial sales performance in plain English — the agent writes safe SQL, "
        "runs it, charts it, and explains the result.</p></div>",
        unsafe_allow_html=True,
    )

    # ---- KPI row ----
    c1, c2, c3, c4, c5 = st.columns(5)
    yr = int(kpis["latest_year"]) if kpis.get("latest_year") else "—"
    c1.metric(f"Net revenue {yr}", fmt_money(kpis.get("rev_latest")),
              delta=(f"{kpis['yoy']:+.1f}% YoY" if kpis.get("yoy") is not None else None))
    c2.metric("Reps", f"{int(kpis.get('reps', 0)):,}")
    c3.metric("Territories", f"{int(kpis.get('territories', 0)):,}")
    c4.metric("Products", f"{int(kpis.get('products', 0)):,}")
    c5.metric("Model", settings.active_model.split("/")[-1])

    # ---- Sidebar: conversation manager ----
    with st.sidebar:
        st.markdown("### 💬 Conversations")
        if st.button("➕  New chat", use_container_width=True):
            _new_conversation()
            st.rerun()

        for cid in reversed(list(st.session_state["conversations"])):
            c = st.session_state["conversations"][cid]
            prefix = "🟣 " if cid == st.session_state["active"] else "   "
            if st.button(prefix + c["title"], key=f"conv_{cid}", use_container_width=True):
                st.session_state["active"] = cid
                st.rerun()

        if len(st.session_state["conversations"]) > 0:
            if st.button("🗑️  Delete this chat", use_container_width=True):
                st.session_state["conversations"].pop(st.session_state["active"], None)
                if not st.session_state["conversations"]:
                    _new_conversation()
                st.session_state["active"] = next(iter(st.session_state["conversations"]))
                st.rerun()

        st.divider()
        n_ctx = min(len(conv["history"]), MAX_CONTEXT_TURNS)
        st.caption(f"Provider: **{agent.provider.name}** · Dialect: **{agent.dialect}**")
        st.caption(f"Follow-up context: last **{n_ctx}** turn(s) in this chat")

    # ---- Empty state: onboarding examples ----
    if not conv["history"]:
        st.markdown('<span class="vtg-pill">Try one of these — then ask follow-ups in the same chat:</span>',
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for i, q in enumerate(EXAMPLE_QUESTIONS):
            if cols[i % 2].button(q, key=f"ex_{i}", use_container_width=True):
                st.session_state["pending"] = q

    # ---- Replay this conversation ----
    for turn in conv["history"]:
        with st.chat_message("user"):
            st.write(turn["q"])
        with st.chat_message("assistant", avatar="📊"):
            render_result(turn["result"])

    # ---- Input ----
    typed = st.chat_input("Ask a question — then follow up, e.g. 'what about 2024?'")
    question = typed or st.session_state.pop("pending", None)

    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant", avatar="📊"):
            with st.spinner("Thinking…"):
                prior = [t for t in conv["history"] if t["result"].ok and t["result"].sql]
                history = [
                    {"question": t["q"], "sql": t["result"].sql}
                    for t in prior[-MAX_CONTEXT_TURNS:]
                ]
                result = agent.answer(question, history=history)
            render_result(result)

        conv["history"].append({"q": question, "result": result})
        if conv["title"] == "New chat":
            conv["title"] = (question[:34] + "…") if len(question) > 35 else question
        st.rerun()


if __name__ == "__main__":
    main()
