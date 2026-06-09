"""Cost breakdowns: group the dataset along a dimension and rank by spend."""

from __future__ import annotations

import polars as pl

from .. import schema as S
from ..models import Breakdown, CostSlice

# Dimension label -> column it groups on. ``team`` nulls become "untagged".
DIMENSIONS: dict[str, str] = {
    "service": S.SERVICE_NAME,
    "account": S.ACCOUNT_ID,
    "team": S.TAG_TEAM,
    "region": S.REGION,
}


def _usage_only(df: pl.DataFrame) -> pl.DataFrame:
    """Drop tax/refund/credit lines so breakdowns reflect real usage spend."""
    return df.filter(pl.col(S.LINE_ITEM_TYPE).is_in(S.USAGE_LINE_ITEM_TYPES))


def total_cost(df: pl.DataFrame) -> float:
    return round(_usage_only(df)[S.UNBLENDED_COST].sum() or 0.0, 2)


def build_breakdown(df: pl.DataFrame, dimension: str, top_n: int = 12) -> Breakdown:
    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown dimension {dimension!r}; expected {list(DIMENSIONS)}")
    col = DIMENSIONS[dimension]
    usage = _usage_only(df)
    total = round(usage[S.UNBLENDED_COST].sum() or 0.0, 2)

    grouped = (
        usage.with_columns(pl.col(col).fill_null("untagged"))
        .group_by(col)
        .agg(pl.col(S.UNBLENDED_COST).sum().alias("cost"))
        .sort("cost", descending=True)
    )

    slices: list[CostSlice] = []
    rows = grouped.head(top_n).iter_rows(named=True)
    for row in rows:
        cost = round(row["cost"], 2)
        slices.append(
            CostSlice(key=str(row[col]), cost=cost, share=cost / total if total else 0.0)
        )

    # Fold the long tail into a single "other" slice so shares sum to ~1.
    if grouped.height > top_n:
        shown = sum(s.cost for s in slices)
        other = round(total - shown, 2)
        if other > 0:
            slices.append(CostSlice(key="other", cost=other, share=other / total))

    return Breakdown(dimension=dimension, total=total, slices=slices)


def build_breakdowns(df: pl.DataFrame) -> list[Breakdown]:
    return [build_breakdown(df, dim) for dim in DIMENSIONS]
