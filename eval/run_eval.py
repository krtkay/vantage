"""Run the agent against the golden dataset and emit a scorecard.

Single run gives point metrics; ``--runs N`` repeats the whole suite N times and
reports **mean +/- std** per metric plus per-case pass stability - the statistical
proof you report (LLMs are stochastic, so variance matters).

Usage:
    python eval/run_eval.py                 # 1 run, full set
    python eval/run_eval.py --runs 3        # 3 runs -> mean +/- std
    python eval/run_eval.py --subset 5      # quick smoke

Requires a valid LLM key and a generated DB.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # local metrics.py

import metrics  # noqa: E402

from vantage.agent import AnalyticsAgent  # noqa: E402
from vantage.data import run_query  # noqa: E402

GOLDEN = ROOT / "eval" / "golden_dataset.yml"
_METRIC_KEYS = [
    "execution_accuracy", "result_match_rate", "keyword_rate", "grounded_rate",
    "guardrail_pass_rate", "latency_ms_p50", "latency_ms_p95", "total_tokens",
]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[idx]


def evaluate_once(
    agent: AnalyticsAgent, cases: list[dict], label: str, sleep: float = 0.0
) -> tuple[dict, list[dict]]:
    rows: list[dict] = []
    for case in cases:
        cid = case["id"]
        t0 = time.perf_counter()
        try:
            result = agent.answer(case["question"], use_cache=False)
        except Exception as exc:  # noqa: BLE001 - usually a transient rate limit
            rows.append({
                "id": cid, "category": case.get("category", "general"),
                "type": "guardrail" if case.get("expect_rejected") else "query",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "tokens": 0, "retries": 0,
                "error": f"{type(exc).__name__}: {str(exc)[:140]}",
                "execution_ok": False, "result_match": False, "keywords_ok": False,
                "grounded": False, "passed": False,
            })
            print(f"  [ERROR] {cid}: {type(exc).__name__} (counted as a miss)")
            if sleep:
                time.sleep(sleep)
            continue

        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        record: dict = {
            "id": cid, "category": case.get("category", "general"),
            "latency_ms": elapsed, "tokens": result.tokens, "retries": result.retries,
        }

        if case.get("expect_rejected"):
            record["type"] = "guardrail"
            record["passed"] = result.rejected is not None
        else:
            record["type"] = "query"
            record["execution_ok"] = result.ok and result.dataframe is not None
            record["keywords_ok"] = metrics.keywords_present(result.narrative, case.get("must_include", []))
            record["grounded"] = len(result.ungrounded) == 0
            try:
                gold = run_query(agent.engine, case["gold_sql"], agent.settings.query_timeout_seconds, 10_000)
                record["result_match"] = bool(
                    record["execution_ok"] and metrics.result_match(result.dataframe, gold)
                )
            except Exception as exc:  # noqa: BLE001
                record["result_match"] = False
                record["gold_error"] = str(exc)

        rows.append(record)
        if sleep:
            time.sleep(sleep)

    scorecard = _aggregate(rows)
    passed = sum(1 for r in rows if (r.get("result_match") or r.get("passed")))
    print(f"  {label}: {passed}/{len(rows)} cases passed | "
          f"exec={scorecard['execution_accuracy']} match={scorecard['result_match_rate']}")
    return scorecard, rows


def _aggregate(rows: list[dict]) -> dict:
    queries = [r for r in rows if r["type"] == "query"]
    guards = [r for r in rows if r["type"] == "guardrail"]
    latencies = [r["latency_ms"] for r in rows]

    def rate(items: list[dict], key: str) -> float:
        return round(sum(1 for r in items if r.get(key)) / len(items), 3) if items else 0.0

    return {
        "execution_accuracy": rate(queries, "execution_ok"),
        "result_match_rate": rate(queries, "result_match"),
        "keyword_rate": rate(queries, "keywords_ok"),
        "grounded_rate": rate(queries, "grounded"),
        "guardrail_pass_rate": rate(guards, "passed"),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "total_tokens": sum(r["tokens"] for r in rows),
    }


def run(subset: int | None, out_dir: Path, runs: int, sleep: float) -> dict:
    spec = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    cases = spec["cases"][:subset] if subset else spec["cases"]
    agent = AnalyticsAgent()

    all_scores, all_rows = [], []
    for i in range(runs):
        score, rows = evaluate_once(agent, cases, label=f"run {i + 1}/{runs}", sleep=sleep)
        all_scores.append(score)
        all_rows.append(rows)

    summary = _summarize(all_scores, all_rows, runs, spec.get("version", "?"))
    _write_reports(summary, all_rows, out_dir)
    return summary


def _summarize(all_scores: list[dict], all_rows: list[list[dict]], runs: int, version: str) -> dict:
    stats = {}
    for key in _METRIC_KEYS:
        vals = [s[key] for s in all_scores]
        stats[key] = {
            "mean": round(statistics.mean(vals), 3),
            "std": round(statistics.pstdev(vals), 3) if runs > 1 else 0.0,
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
        }

    stability = {}
    for rec0 in all_rows[0]:
        cid = rec0["id"]
        passes = 0
        for rows in all_rows:
            rec = next(r for r in rows if r["id"] == cid)
            ok = rec.get("result_match") if rec["type"] == "query" else rec.get("passed")
            passes += 1 if ok else 0
        stability[cid] = f"{passes}/{runs}"

    return {
        "dataset_version": version,
        "runs": runs,
        "n_cases": len(all_rows[0]),
        "metrics": stats,
        "case_stability": stability,
    }


def _write_reports(summary: dict, all_rows: list[list[dict]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scorecard.json").write_text(
        json.dumps({"summary": summary, "runs": all_rows}, indent=2), encoding="utf-8"
    )

    lines = [
        "# Evaluation scorecard", "",
        f"- **dataset_version**: {summary['dataset_version']}",
        f"- **runs**: {summary['runs']}",
        f"- **cases/run**: {summary['n_cases']}", "",
        "## Metrics (mean ± std across runs)", "",
        "| metric | mean | std | min | max |", "|---|---|---|---|---|",
    ]
    for key, s in summary["metrics"].items():
        lines.append(f"| {key} | {s['mean']} | {s['std']} | {s['min']} | {s['max']} |")
    lines += ["", "## Per-case pass stability", "", "| case | passes |", "|---|---|"]
    for cid, st in summary["case_stability"].items():
        lines.append(f"| {cid} | {st} |")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", type=int, default=None)
    parser.add_argument("--runs", type=int, default=1, help="repeat the suite N times for mean±std")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds between cases (free-tier pacing)")
    parser.add_argument("--out", default=str(ROOT / "eval" / "reports"))
    args = parser.parse_args()

    summary = run(args.subset, Path(args.out), args.runs, args.sleep)
    print(f"\n=== SUMMARY over {summary['runs']} run(s) ===")
    for key, s in summary["metrics"].items():
        suffix = f" ± {s['std']}" if summary["runs"] > 1 else ""
        print(f"  {key:<22} {s['mean']}{suffix}")


if __name__ == "__main__":
    main()
