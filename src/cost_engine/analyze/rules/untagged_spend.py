"""Rule: untagged spend (cost-allocation governance).

This is a governance signal, not a direct dollar cut: spend with no ``team`` tag
can't be charged back, budgeted, or attributed, which is what blocks every other
optimization from having an owner. The estimated saving is therefore $0; the
payload is the unallocable amount and its share of total spend.
"""

from __future__ import annotations

import polars as pl

from ... import schema as S
from ...models import Category, Finding, Severity
from . import base

# Surface only once untagged spend clears this share of the bill.
UNTAGGED_THRESHOLD_PCT = 0.05


class UntaggedSpendRule(base.Rule):
    rule_id = "untagged-spend"
    title = "Untagged spend can't be allocated"

    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        usage = base.usage_only(df)
        total = base.cost_of(usage)
        if total <= 0:
            return []

        untagged = usage.filter(pl.col(S.TAG_TEAM).is_null())
        untagged_cost = base.cost_of(untagged)
        pct = untagged_cost / total
        if pct < UNTAGGED_THRESHOLD_PCT:
            return []

        # Which services hide the most untagged spend, for a concrete next step.
        top = (
            untagged.group_by(S.SERVICE_NAME)
            .agg(pl.col(S.UNBLENDED_COST).sum().alias("cost"))
            .sort("cost", descending=True)
            .head(3)
        )
        top_services = ", ".join(
            f"{r[S.SERVICE_NAME]} (${r['cost']:,.0f})" for r in top.iter_rows(named=True)
        )
        ids, count = base.resource_sample(untagged)
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                category=Category.GOVERNANCE,
                severity=Severity.INFO,
                monthly_cost=untagged_cost,
                estimated_monthly_savings=0.0,  # governance, not a direct saving
                resource_ids=ids,
                affected_resource_count=count,
                confidence=0.9,
                detail=(
                    f"${untagged_cost:,.0f}/mo ({pct:.0%} of spend) has no team tag and "
                    f"can't be charged back or owned. Top untagged services: {top_services}."
                ),
                recommendation=(
                    "Enforce a required `team` tag via tag policies / SCPs, backfill "
                    "the top untagged resources, and add a budget alarm on untagged "
                    "spend so it can't creep back up."
                ),
            )
        ]
