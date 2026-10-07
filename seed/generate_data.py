"""Synthetic commercial-sales data generator for the Vantage analytics agent.

Builds a realistic **MedTech / consumer-health** sales *star schema* into SQLite.

Why this exists
---------------
The agent is only as good as the data it reasons over, and the evaluation
golden-dataset pins expected answers to *exact* rows. So this generator is:

* **Deterministic** - seeded (`numpy`, `Faker`, `random`); regenerating with the
  same ``--seed`` yields byte-identical data, keeping the golden dataset valid.
* **Realistic** - trend + seasonality, rep performance tiers, target attainment
  spread, product lifecycle, account tiers, and an activity->sales correlation,
  so analytical questions have meaningful answers (real winners/losers).
* **Scalable** - ``--scale {small,rich,large}`` dials volume for your laptop.

Usage
-----
    python seed/generate_data.py --scale rich
    python seed/generate_data.py --scale small --out data/analytics.db --seed 42

Schema (star)
-------------
dims : dim_date, dim_region, dim_territory, dim_rep, dim_product, dim_account
facts: fact_sales, fact_targets, fact_activity
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DATA_VERSION = "1.0.0"  # bump when schema/seed logic changes -> regen golden set

SCALES: dict[str, dict[str, int]] = {
    "small": {"months": 24, "n_territories": 20, "n_reps": 40, "n_accounts": 600},
    "rich": {"months": 36, "n_territories": 45, "n_reps": 120, "n_accounts": 2000},
    "large": {"months": 48, "n_territories": 90, "n_reps": 300, "n_accounts": 6000},
}

END_YEAR, END_MONTH = 2025, 12  # history always ends at Dec 2025

# Calendar-month seasonality multipliers (Q4 uplift, summer dip).
SEASONALITY = {
    1: 0.95, 2: 0.92, 3: 1.05, 4: 0.90, 5: 0.88, 6: 0.90,
    7: 0.98, 8: 1.00, 9: 1.08, 10: 1.15, 11: 1.20, 12: 1.25,
}
ANNUAL_GROWTH = 0.10  # ~10% YoY underlying trend

REGION_NAMES = [
    ("North-1", "North"), ("North-2", "North"),
    ("South-1", "South"), ("South-2", "South"),
    ("East-1", "East"), ("East-2", "East"),
    ("West-1", "West"), ("West-2", "West"),
]

PERF_TIERS = {"Top": 1.35, "Mid": 1.00, "Low": 0.72}      # sales multiplier
PERF_WEIGHTS = {"Top": 0.20, "Mid": 0.55, "Low": 0.25}    # base distribution

ACCOUNT_TYPES = {"Hospital": 0.20, "Clinic": 0.35, "Retail Pharmacy": 0.30, "Distributor": 0.15}
ACCOUNT_TIERS = {"A": 0.15, "B": 0.35, "C": 0.50}
TIER_VOLUME = {"A": 2.2, "B": 1.3, "C": 0.7}              # buying-volume multiplier
TIER_NPRODUCTS = {"A": 6, "B": 4, "C": 3}                 # mean products/month
TIER_DISCOUNT = {"A": 0.18, "B": 0.10, "C": 0.05}
DISTRIBUTOR_DISCOUNT = 0.22

# category: (price_low, price_high, margin_pct, base_units, [subcategories])
CATEGORIES: dict[str, tuple] = {
    "Diagnostics": (1500, 8000, 0.45, 3.0, ["Blood Analyzers", "Test Kits", "Imaging Consumables"]),
    "Monitoring Devices": (3000, 25000, 0.40, 2.0, ["Vital Monitors", "Wearables", "Home Monitors"]),
    "Surgical Instruments": (5000, 60000, 0.50, 1.2, ["Hand Instruments", "Electrosurgery", "Sutures"]),
    "Consumer Wellness": (200, 3000, 0.35, 15.0, ["Supplements", "Thermometers", "First Aid"]),
    "Orthopedic": (8000, 90000, 0.55, 1.0, ["Implants", "Braces", "Prosthetics"]),
}
PRODUCTS_PER_CATEGORY = 6  # 5 categories x 6 = 30 products

ACTIVITY_TYPES = {"Visit": 0.35, "Call": 0.30, "Email": 0.20, "Demo": 0.10, "Conference": 0.05}
ACTIVITY_OUTCOMES = {"Positive": 0.35, "Follow-up": 0.30, "Neutral": 0.25, "No-interest": 0.10}
TIER_ACTIVITY = {"Top": 55, "Mid": 42, "Low": 30}  # mean activities/rep/month


# --------------------------------------------------------------------------- #
# Dimension builders
# --------------------------------------------------------------------------- #
def build_dim_date(months: int) -> pd.DataFrame:
    """Monthly calendar ending at END_YEAR/END_MONTH, oldest first."""
    seq: list[tuple[int, int]] = []
    y, m = END_YEAR, END_MONTH
    for _ in range(months):
        seq.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    seq.reverse()

    rows = []
    for i, (yy, mm) in enumerate(seq, start=1):
        q = (mm - 1) // 3 + 1
        rows.append({
            "date_id": i,
            "month_start": date(yy, mm, 1).isoformat(),
            "year": yy,
            "quarter": q,
            "quarter_label": f"{yy}-Q{q}",
            "month": mm,
            "month_name": date(yy, mm, 1).strftime("%B"),
            "fiscal_year": yy,
        })
    return pd.DataFrame(rows)


def build_dim_region() -> pd.DataFrame:
    rows = [
        {"region_id": i, "region_name": name, "zone": zone, "country": "India"}
        for i, (name, zone) in enumerate(REGION_NAMES, start=1)
    ]
    return pd.DataFrame(rows)


def build_dim_territory(n: int, regions: pd.DataFrame, rng, faker: Faker) -> pd.DataFrame:
    region_ids = regions["region_id"].tolist()
    size_tiers = ["Large", "Medium", "Small"]
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "territory_id": i,
            "territory_name": f"T-{i:03d} {faker.city()}",
            "region_id": region_ids[(i - 1) % len(region_ids)],
            "size_tier": size_tiers[rng.choice(3, p=[0.30, 0.45, 0.25])],
        })
    return pd.DataFrame(rows)


def build_dim_rep(n: int, territories: pd.DataFrame, rng, faker: Faker) -> pd.DataFrame:
    terr_ids = territories["territory_id"].tolist()
    tiers = list(PERF_TIERS)
    base = np.array([PERF_WEIGHTS[t] for t in tiers], dtype=float)
    data_end = date(END_YEAR, END_MONTH, 28)

    rows = []
    for i in range(1, n + 1):
        tenure = int(rng.integers(3, 120))
        hire = data_end - timedelta(days=tenure * 30)
        seniority = "Senior" if tenure >= 72 else "Mid" if tenure >= 24 else "Junior"

        # Performance tier correlated with tenure (veterans skew Top).
        boost = min(0.25, tenure / 480)
        adj = base.copy()
        adj[0] += boost
        adj[2] = max(0.05, adj[2] - boost)
        adj = adj / adj.sum()
        tier = tiers[rng.choice(len(tiers), p=adj)]

        rows.append({
            "rep_id": i,
            "rep_name": faker.name(),
            "territory_id": terr_ids[(i - 1) % len(terr_ids)],
            "manager_id": None,
            "hire_date": hire.isoformat(),
            "tenure_months": tenure,
            "seniority": seniority,
            "performance_tier": tier,
        })

    df = pd.DataFrame(rows)
    # First ~1-in-12 reps are managers (manager_id NULL); rest report to one.
    n_mgr = max(1, n // 12)
    mgr_ids = df.head(n_mgr)["rep_id"].tolist()
    df["manager_id"] = df["rep_id"].apply(
        lambda rid: None if rid in mgr_ids else int(rng.choice(mgr_ids))
    )
    return df


def build_dim_product(rng, months: int) -> pd.DataFrame:
    stages = ["Launch", "Growth", "Mature", "Decline"]
    rows = []
    pid = 1
    for cat, (plo, phi, margin, _base, subcats) in CATEGORIES.items():
        for k in range(PRODUCTS_PER_CATEGORY):
            price = float(round(rng.uniform(plo, phi), -1))  # round to nearest 10
            sub = subcats[k % len(subcats)]
            stage = stages[rng.choice(4, p=[0.15, 0.15, 0.50, 0.20])]
            if stage == "Launch" and months > 12:
                launch_idx = int(rng.integers(6, months - 6))
            else:
                launch_idx = 0
            rows.append({
                "product_id": pid,
                "product_name": f"{cat.split()[0]}-{sub.split()[0][:3].upper()}-{1000 + pid}",
                "category": cat,
                "subcategory": sub,
                "list_price": price,
                "unit_cost": round(price * (1 - margin), 2),
                "margin_pct": margin,
                "launch_month_index": launch_idx,
                "lifecycle_stage": stage,
            })
            pid += 1
    return pd.DataFrame(rows)


def lifecycle_factor_matrix(products: pd.DataFrame, months: int) -> np.ndarray:
    """[months x products] demand multiplier capturing launch ramp / decline."""
    mat = np.ones((months, len(products)))
    for j, (_, p) in enumerate(products.iterrows()):
        li = int(p["launch_month_index"])
        stage = p["lifecycle_stage"]
        for mi in range(months):
            if mi < li:
                mat[mi, j] = 0.0
                continue
            t = mi - li
            if stage == "Launch":
                mat[mi, j] = min(1.0, 0.2 + 0.8 * (t / 6))
            elif stage == "Growth":
                mat[mi, j] = min(1.6, 1.0 + 0.02 * t)
            elif stage == "Decline":
                mat[mi, j] = max(0.3, 1.0 - 0.02 * t)
            else:  # Mature
                mat[mi, j] = 1.0
    return mat


def build_dim_account(n: int, territories: pd.DataFrame, reps: pd.DataFrame, rng, faker: Faker) -> pd.DataFrame:
    terr_ids = territories["territory_id"].tolist()
    terr_reps = reps.groupby("territory_id")["rep_id"].apply(list).to_dict()
    all_reps = reps["rep_id"].tolist()

    types = list(ACCOUNT_TYPES)
    tprob = [ACCOUNT_TYPES[t] for t in types]
    tiers = list(ACCOUNT_TIERS)
    tiprob = [ACCOUNT_TIERS[t] for t in tiers]

    rows = []
    for i in range(1, n + 1):
        terr = int(rng.choice(terr_ids))
        reps_here = terr_reps.get(terr) or all_reps
        atype = types[rng.choice(len(types), p=tprob)]
        suffix = "Hospital" if atype == "Hospital" else atype.split()[0]
        rows.append({
            "account_id": i,
            "account_name": f"{faker.company()} {suffix}",
            "account_type": atype,
            "tier": tiers[rng.choice(len(tiers), p=tiprob)],
            "territory_id": terr,
            "primary_rep_id": int(rng.choice(reps_here)),
            "city": faker.city(),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Fact builders
# --------------------------------------------------------------------------- #
def build_fact_sales(dim_date, products, accounts, reps, life_mat, rng) -> pd.DataFrame:
    """Monthly transactions at (rep, product, account) grain, vectorised per month."""
    months = len(dim_date)
    rep_perf = reps.set_index("rep_id")["performance_tier"].map(PERF_TIERS).to_dict()

    acc = accounts.copy()
    acc_ids = acc["account_id"].to_numpy()
    acc_terr = acc["territory_id"].to_numpy()
    acc_rep = acc["primary_rep_id"].to_numpy()
    acc_tiervol = acc["tier"].map(TIER_VOLUME).to_numpy()
    acc_nprod = acc["tier"].map(TIER_NPRODUCTS).to_numpy()
    acc_disc = acc.apply(
        lambda r: DISTRIBUTOR_DISCOUNT if r["account_type"] == "Distributor" else TIER_DISCOUNT[r["tier"]],
        axis=1,
    ).to_numpy()
    acc_perf = acc["primary_rep_id"].map(rep_perf).fillna(1.0).to_numpy()
    n_acc = len(acc)

    prod_ids = products["product_id"].to_numpy()
    prod_price = products["list_price"].to_numpy()
    prod_cost = products["unit_cost"].to_numpy()
    prod_base = products["category"].map({c: v[3] for c, v in CATEGORIES.items()}).to_numpy()
    n_prod = len(products)

    frames = []
    sale_id = 1
    for mi in range(months):
        seasonal = SEASONALITY[int(dim_date.iloc[mi]["month"])]
        trend = (1 + ANNUAL_GROWTH) ** (mi / 12)
        life = life_mat[mi]
        if life.sum() == 0:
            continue
        weights = life / life.sum()  # unlaunched products get 0 probability

        counts = np.clip(rng.poisson(acc_nprod), 0, n_prod)
        total = int(counts.sum())
        if total == 0:
            continue

        a_idx = np.repeat(np.arange(n_acc), counts)
        p_idx = rng.choice(n_prod, size=total, p=weights)

        units_exp = (
            prod_base[p_idx] * acc_tiervol[a_idx] * seasonal * trend
            * acc_perf[a_idx] * life[p_idx]
        )
        units = np.maximum(1, np.round(units_exp * rng.lognormal(0, 0.3, total))).astype(int)

        # ~1.5% returns -> small negative units
        returns = rng.random(total) < 0.015
        units = np.where(returns, -np.maximum(1, (units * 0.3).astype(int)), units)

        price = prod_price[p_idx]
        disc = acc_disc[a_idx]
        gross = units * price
        disc_amt = np.round(gross * disc, 2)
        net = np.round(gross - disc_amt, 2)
        cogs = np.round(units * prod_cost[p_idx], 2)

        frames.append(pd.DataFrame({
            "sale_id": np.arange(sale_id, sale_id + total),
            "date_id": mi + 1,
            "rep_id": acc_rep[a_idx],
            "product_id": prod_ids[p_idx],
            "account_id": acc_ids[a_idx],
            "territory_id": acc_terr[a_idx],
            "units": units,
            "gross_revenue": np.round(gross, 2),
            "discount_pct": np.round(disc, 4),
            "discount_amount": disc_amt,
            "net_revenue": net,
            "cogs": cogs,
            "margin": np.round(net - cogs, 2),
        }))
        sale_id += total

    return pd.concat(frames, ignore_index=True)


def build_fact_targets(fact_sales, reps, rng) -> pd.DataFrame:
    """Rep-month targets calibrated so ~60-65% of reps hit quota."""
    perf_bias = {"Top": 1.12, "Mid": 1.02, "Low": 0.90}
    rep_tier = reps.set_index("rep_id")["performance_tier"].to_dict()
    rep_terr = reps.set_index("rep_id")["territory_id"].to_dict()

    agg = fact_sales.groupby(["date_id", "rep_id"]).agg(
        actual_rev=("net_revenue", "sum"),
        actual_units=("units", "sum"),
    ).reset_index()

    bias = agg["rep_id"].map(rep_tier).map(perf_bias).fillna(1.0).to_numpy()
    # attainment a = actual / target  =>  target = actual / a
    a_rev = np.clip(bias * rng.normal(1.0, 0.18, len(agg)), 0.55, 1.8)
    a_units = np.clip(bias * rng.normal(1.0, 0.15, len(agg)), 0.60, 1.7)

    target_rev = np.maximum(1000.0, np.round(agg["actual_rev"].to_numpy() / a_rev, 2))
    target_units = np.maximum(1, np.round(agg["actual_units"].to_numpy() / a_units)).astype(int)

    return pd.DataFrame({
        "target_id": np.arange(1, len(agg) + 1),
        "date_id": agg["date_id"],
        "rep_id": agg["rep_id"],
        "territory_id": agg["rep_id"].map(rep_terr),
        "target_revenue": target_rev,
        "target_units": target_units,
    })


def build_fact_activity(dim_date, reps, accounts, rng) -> pd.DataFrame:
    """Rep activities; higher-performing reps log more Visits/Demos (drives the
    activity->sales correlation the agent can surface)."""
    rep_tier = reps.set_index("rep_id")["performance_tier"].to_dict()
    rep_accounts = accounts.groupby("primary_rep_id")["account_id"].apply(list).to_dict()
    all_acc = accounts["account_id"].tolist()

    atypes = list(ACTIVITY_TYPES)
    aprob = [ACTIVITY_TYPES[t] for t in atypes]
    outs = list(ACTIVITY_OUTCOMES)
    oprob = [ACTIVITY_OUTCOMES[t] for t in outs]

    frames = []
    act_id = 1
    for mi in range(len(dim_date)):
        yy = int(dim_date.iloc[mi]["year"])
        mm = int(dim_date.iloc[mi]["month"])
        for rid in reps["rep_id"].tolist():
            tier = rep_tier.get(rid, "Mid")
            n = int(rng.poisson(TIER_ACTIVITY[tier]))
            if n == 0:
                continue
            accs = rep_accounts.get(rid) or all_acc
            type_idx = rng.choice(len(atypes), size=n, p=aprob)
            out_idx = rng.choice(len(outs), size=n, p=oprob)
            days = rng.integers(1, 29, size=n)
            frames.append(pd.DataFrame({
                "activity_id": np.arange(act_id, act_id + n),
                "date_id": mi + 1,
                "rep_id": rid,
                "account_id": rng.choice(accs, size=n),
                "activity_type": [atypes[i] for i in type_idx],
                "activity_date": [date(yy, mm, int(d)).isoformat() for d in days],
                "duration_min": rng.integers(10, 90, size=n),
                "outcome": [outs[i] for i in out_idx],
            }))
            act_id += n

    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def write_sqlite(tables: dict[str, pd.DataFrame], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        for name, df in tables.items():
            df.to_sql(name, conn, if_exists="replace", index=False, chunksize=20000)

        for stmt in (
            "CREATE INDEX idx_sales_date ON fact_sales(date_id)",
            "CREATE INDEX idx_sales_rep ON fact_sales(rep_id)",
            "CREATE INDEX idx_sales_product ON fact_sales(product_id)",
            "CREATE INDEX idx_sales_account ON fact_sales(account_id)",
            "CREATE INDEX idx_sales_territory ON fact_sales(territory_id)",
            "CREATE INDEX idx_targets_date_rep ON fact_targets(date_id, rep_id)",
            "CREATE INDEX idx_activity_date_rep ON fact_activity(date_id, rep_id)",
            "CREATE INDEX idx_activity_account ON fact_activity(account_id)",
        ):
            conn.execute(stmt)

        conn.execute("CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO _meta VALUES (?, ?)",
            [("data_version", DATA_VERSION), ("sales_rows", str(len(tables["fact_sales"])))],
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic sales warehouse.")
    parser.add_argument("--scale", choices=list(SCALES), default="rich")
    parser.add_argument("--out", default="data/analytics.db")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cfg = SCALES[args.scale]
    rng = np.random.default_rng(args.seed)
    random.seed(args.seed)
    faker = Faker("en_IN")
    Faker.seed(args.seed)

    dim_date = build_dim_date(cfg["months"])
    regions = build_dim_region()
    territories = build_dim_territory(cfg["n_territories"], regions, rng, faker)
    reps = build_dim_rep(cfg["n_reps"], territories, rng, faker)
    products = build_dim_product(rng, cfg["months"])

    date_map = dict(zip(dim_date["date_id"], dim_date["month_start"], strict=False))
    products["launch_date"] = products["launch_month_index"].apply(
        lambda i: date_map.get(i + 1, dim_date["month_start"].iloc[0])
    )

    accounts = build_dim_account(cfg["n_accounts"], territories, reps, rng, faker)
    life_mat = lifecycle_factor_matrix(products, cfg["months"])

    fact_sales = build_fact_sales(dim_date, products, accounts, reps, life_mat, rng)
    fact_targets = build_fact_targets(fact_sales, reps, rng)
    fact_activity = build_fact_activity(dim_date, reps, accounts, rng)

    products = products.drop(columns=["launch_month_index"])

    tables = {
        "dim_date": dim_date,
        "dim_region": regions,
        "dim_territory": territories,
        "dim_rep": reps,
        "dim_product": products,
        "dim_account": accounts,
        "fact_sales": fact_sales,
        "fact_targets": fact_targets,
        "fact_activity": fact_activity,
    }
    write_sqlite(tables, args.out)

    print(f"[data v{DATA_VERSION}] scale={args.scale} seed={args.seed} -> {args.out}")
    for name, df in tables.items():
        print(f"  {name:<14} {len(df):>9,} rows")


if __name__ == "__main__":
    main()
