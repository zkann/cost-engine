"""The synthetic generator must be deterministic and carry every planted signal."""

from __future__ import annotations

from datetime import date

import polars as pl

from cost_engine import schema as S
from cost_engine.ingest import generate_synthetic_cur


def test_schema_columns(synthetic_df: pl.DataFrame) -> None:
    assert list(synthetic_df.columns) == list(S.SCHEMA.keys())


def test_deterministic_given_seed() -> None:
    a = generate_synthetic_cur(seed=42)
    b = generate_synthetic_cur(seed=42)
    assert a.equals(b)
    assert a[S.UNBLENDED_COST].sum() == b[S.UNBLENDED_COST].sum()


def test_different_seed_changes_resource_ids() -> None:
    a = generate_synthetic_cur(seed=1)
    b = generate_synthetic_cur(seed=2)
    # Totals are spec-driven (stable); resource ids are seeded (vary).
    assert set(a[S.RESOURCE_ID]) != set(b[S.RESOURCE_ID])


def test_total_is_material(synthetic_df: pl.DataFrame) -> None:
    assert 30_000 < synthetic_df[S.UNBLENDED_COST].sum() < 60_000


def test_planted_signals_present(synthetic_df: pl.DataFrame) -> None:
    types = set(synthetic_df[S.USAGE_TYPE])
    assert any("gp2" in t for t in types)
    assert any("ElasticIP:IdleAddress" in t for t in types)
    assert any("NatGateway" in t for t in types)
    assert any("SnapshotUsage" in t for t in types)
    # Some spend is deliberately untagged.
    assert synthetic_df.filter(pl.col(S.TAG_TEAM).is_null()).height > 0
    # Compute exists in both on-demand and committed terms.
    terms = set(synthetic_df[S.PRICING_TERM])
    assert {"OnDemand", "SavingsPlan"} <= terms


def test_daily_granularity(synthetic_df: pl.DataFrame) -> None:
    dates = synthetic_df[S.USAGE_DATE].unique().sort()
    assert dates.min() == date(2026, 5, 1)
    assert dates.max() == date(2026, 5, 31)
    assert len(dates) == 31
