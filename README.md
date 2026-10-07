# 📊 Vantage — Commercial Analytics Agent

A production-shaped **AI agent** that lets a non-technical sales manager ask
questions in plain English and get back a **chart + a grounded, business-ready
insight** — by writing safe SQL, running it, and explaining the result.

> _"Which 5 territories underperformed vs target in 2025, and what's driving it?"_
> → the agent plans, writes SQL, self-corrects on errors, runs it read-only,
> renders a chart, and writes a recommendation — all in a few seconds.

Built around a synthetic **MedTech / consumer-health commercial sales** warehouse
(sales-force effectiveness, territory performance, target attainment, next-best
action) — the kind of self-service analytics that commercial-analytics consulting
teams build for clients.

---

## Why this project is interesting (engineering, not just a chatbot)

| Concern | How it's handled |
|---|---|
| **How the agent "knows" the data** | Runtime **schema introspection** + an optional **data dictionary** — not memorized rows. Swap the DB and it adapts. |
| **Pluggable data source** | Any SQLAlchemy URL (SQLite/Postgres/MySQL) via `DATABASE_URL`. Guardrail allowlist auto-derives from the live schema. |
| **Agent orchestration** | A **LangGraph** state machine with a **conditional retry edge** for self-correction. |
| **Multi-turn context** | Follow-ups ("what about 2024?", "…the top territory") resolve against the last few turns fed into SQL generation; bounded. |
| **Separate conversations** | A sidebar chat manager — create/switch/delete independent conversations, each keeping its *own* context. |
| **Safety** | 3 guardrail stages: input (injection/scope), **SQL (SELECT-only, allowlist, LIMIT via sqlglot)**, output (numeric grounding) — plus a **read-only DB connection** as defense-in-depth. |
| **Provider-agnostic LLM** | Groq (default) / Gemini behind one interface; **API-key-only**, fail-fast key verification, no local fallback. |
| **Observability** | Structured JSON logs with per-step timings + token counts; optional **Langfuse** tracing. |
| **Evaluation** | A **golden dataset** + tolerant **result-match** metrics, guardrail red-team cases, latency/token tracking → a scorecard, wired as a **CI gate**. |
| **Quality** | Typed, modular, `ruff`-clean, 36 unit tests, deterministic data generator. |

---

## Architecture

```
                 ┌─────────────────────── Streamlit UI ───────────────────────┐
  question ───►  │  chat · chart · "Details" (SQL, retries, latency, tokens)   │
                 └───────────────────────────────┬────────────────────────────┘
                                                 ▼
                                    LangGraph StateGraph
   guard_input ──rejected──► END
        │ ok
        ▼
   generate_sql ◄───────────────── retry (bad SQL / exec error, ≤ MAX_RETRIES)
        │                                        ▲
        ▼                                        │
   execute (SQL guardrail → read-only query) ──error
        │ ok                         \ exhausted
        ▼                             ▼
   summarize (chart + grounded insight)   fail
        │                                  │
        └──────────────► END ◄─────────────┘

 cross-cutting: config/key verification · structured logging · tracing · eval harness
```

- **LangGraph** owns the control flow and the retry loop.
- The **LLM layer stays vendor-agnostic** underneath (Groq/Gemini), so you can swap
  providers from config without touching the graph.

---

## The data (so testing is meaningful)

You don't need any data of your own — a **deterministic, seeded generator** builds a
realistic star schema:

```
dim_date · dim_region · dim_territory · dim_rep · dim_product · dim_account
fact_sales (~272k rows @ rich) · fact_targets · fact_activity (~195k rows)
```

Baked-in business logic (so questions have real answers): YoY growth + seasonality,
rep performance tiers, a realistic **target-attainment spread** (Top reps 1.08 >
Mid 0.98 > Low 0.87), **activity→sales correlation (+0.46)**, product lifecycles,
account tiers and discounting. See [`seed/`](seed/) and the embedded
[`data_dictionary.yml`](seed/data_dictionary.yml).

Scale is configurable: `--scale small` (~60k rows, ~15 MB) · `rich` (default,
~270k rows, ~40 MB) · `large` (~1M+ rows).

---

## Quickstart (local, no Docker)

**Prereqs:** Python 3.11, a free **Groq** API key (<https://console.groq.com>).

```bash
# 1) install
python -m pip install -r requirements.txt

# 2) configure your key
cp .env.example .env            # Windows: copy .env.example .env
#   then edit .env and set GROQ_API_KEY=...

# 3) generate the database (one time)
python seed/generate_data.py --scale rich

# 4) run
streamlit run src/vantage/app.py
```

Open <http://localhost:8501> and ask away. Click an example question in the sidebar
to start.

> **Presentation tip:** the agent caches answers. Run your demo questions once to
> warm the cache — replays return in well under a second.

---

## How the agent knows your data (and using your own DB)

The agent **introspects the connected database at startup** — it reads the tables,
columns and types, renders them for the model, and derives the guardrail allowlist
from them. Point it at a different database and everything adapts:

```bash
# in .env
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/yourdb
# optional: a YAML dictionary describing your columns boosts accuracy
DATA_DICTIONARY_PATH=path/to/your_dictionary.yml
```

Install the matching driver (`psycopg[binary]` for Postgres, `PyMySQL` for MySQL —
commented in `requirements.txt`). No code changes needed. Use a **read-only DB
user** in production; the app also forces the connection read-only itself.

---

## Configuration

All via env / `.env` (see [`.env.example`](.env.example)). Highlights:

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq` or `gemini` |
| `GROQ_API_KEY` | — | required for Groq (fail-fast if missing) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | must be a model your key can access |
| `DATABASE_URL` | bundled SQLite | any SQLAlchemy URL |
| `MAX_SQL_ROWS` | `1000` | hard row cap |
| `MAX_RETRIES` | `2` | self-correction attempts |
| `QUERY_TIMEOUT_SECONDS` | `15` | statement timeout |
| `LANGFUSE_*` | — | optional tracing |

---

## Guardrails

1. **Input** — length limit, empty-check, prompt-injection screen.
2. **SQL** (sqlglot, parse-based not regex) — exactly one statement; must be a
   read query; **no** INSERT/UPDATE/DELETE/DDL/PRAGMA anywhere; every table in the
   **allowlist**; a `LIMIT` is injected/capped.
3. **Output** — flags numbers in the narrative that aren't traceable to the result
   set (hallucination tripwire).
4. **Defense-in-depth** — the DB connection itself is opened read-only
   (`PRAGMA query_only` / `SET TRANSACTION READ ONLY`).

---

## Evaluation

```bash
python eval/run_eval.py              # full golden set
python eval/run_eval.py --subset 5   # quick smoke
```

Produces `eval/reports/scorecard.json` + `report.md`. Metrics: **execution
accuracy**, **result-match** (tolerant set-overlap vs a canonical gold SQL),
**keyword coverage**, **grounding**, **guardrail pass-rate**, and **latency
p50/p95 + tokens**. The golden set includes adversarial cases that must be blocked.

---

## Testing & CI

```bash
ruff check src seed eval tests
pytest                 # 36 tests, no API key required
```

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs lint + unit tests on
every push/PR, then an **eval gate** (skips cleanly if the `GROQ_API_KEY` repo
secret isn't set). See the CI/CD + cloud guides:

- **Simple deploy + CI/CD:** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- **Containerize (Docker):** [docs/DOCKER.md](docs/DOCKER.md) — *provided but not built locally*
- **Professional AWS deploy:** [docs/DEPLOYMENT_AWS.md](docs/DEPLOYMENT_AWS.md)

---

## Project layout

```
src/vantage/        config · llm/ · data/ · guardrails/ · agent/ (LangGraph) · observability/ · app.py
seed/           generate_data.py · data_dictionary.yml
eval/           golden_dataset.yml · metrics.py · run_eval.py
tests/          unit tests (guardrails, data, generator, tools, config, metrics)
docs/           DEPLOYMENT.md · DOCKER.md · DEPLOYMENT_AWS.md
```

---

## Talking points for the interview

- **Text-to-SQL agent** with **self-correction** (LangGraph conditional edge).
- **Multi-turn**: follow-up questions resolve against prior turns (conversational analytics), kept per-session so a deployed instance never mixes users' context.
- **Safety-first**: parse-based SQL guardrail + read-only connection + allowlist.
- **Evaluation-driven**: golden dataset, result-match metric, CI eval gate — I can
  prove the agent's accuracy, not just demo it.
- **Pluggable & scalable**: swap the LLM provider or the database from config.
- **Observable**: every run emits structured traces with timings and token cost.

_Stack: Python 3.11 · LangGraph · Groq (GPT-OSS 120B) / Gemini · SQLAlchemy ·
sqlglot · Pandas · Plotly · Streamlit · structlog · pytest · ruff._
