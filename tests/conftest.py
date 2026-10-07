"""Shared fixtures. Builds a tiny, fast, deterministic DB by calling the generator
builders directly (no subprocess, no API keys)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from faker import Faker

import generate_data as gd  # on path via pyproject pythonpath=["seed"]
from vantage.data import introspect, make_engine


def build_tiny_db(path: str, seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    faker = Faker("en_IN")
    Faker.seed(seed)

    months = 6
    dim_date = gd.build_dim_date(months)
    regions = gd.build_dim_region()
    territories = gd.build_dim_territory(5, regions, rng, faker)
    reps = gd.build_dim_rep(8, territories, rng, faker)
    products = gd.build_dim_product(rng, months)
    date_map = dict(zip(dim_date["date_id"], dim_date["month_start"], strict=False))
    products["launch_date"] = products["launch_month_index"].apply(
        lambda i: date_map.get(i + 1, dim_date["month_start"].iloc[0])
    )
    accounts = gd.build_dim_account(30, territories, reps, rng, faker)
    life = gd.lifecycle_factor_matrix(products, months)
    sales = gd.build_fact_sales(dim_date, products, accounts, reps, life, rng)
    targets = gd.build_fact_targets(sales, reps, rng)
    activity = gd.build_fact_activity(dim_date, reps, accounts, rng)
    products = products.drop(columns=["launch_month_index"])

    gd.write_sqlite(
        {
            "dim_date": dim_date,
            "dim_region": regions,
            "dim_territory": territories,
            "dim_rep": reps,
            "dim_product": products,
            "dim_account": accounts,
            "fact_sales": sales,
            "fact_targets": targets,
            "fact_activity": activity,
        },
        path,
    )


@pytest.fixture(scope="session")
def tiny_db(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("db") / "tiny.db"
    build_tiny_db(str(path))
    return str(path)


@pytest.fixture(scope="session")
def engine(tiny_db):
    return make_engine(f"sqlite:///{Path(tiny_db).as_posix()}")


@pytest.fixture(scope="session")
def schema(engine):
    return introspect(engine)
