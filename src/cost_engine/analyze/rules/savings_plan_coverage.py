"""Rule: low Savings Plan / Reserved coverage on steady compute.

On-demand compute that runs around the clock is the textbook candidate for a
Compute Savings Plan. CUR carries the price term (``OnDemand`` vs ``SavingsPlan``
/ ``Reserved``) per line, so coverage is measurable directly. We estimate the
saving on the steady baseline portion of on-demand compute at a conservative
1-year no-upfront Compute Savings Plan discount.

Scope is EC2/Fargate compute (BoxUsage / Fargate), which is what a Compute
Savings Plan covers. RDS is committed separately via RDS Reserved Instances and
is called out in the recommendation rather than folded into the dollar estimate.
"""

from __future__ import annotations

import polars as pl

from ... import schema as S
from ...models import Category, Finding
from . import base

# Share of on-demand compute steady enough to sit under a commitment.
TARGET_ONDEMAND_COVERAGE = 0.70
# Conservative 1-yr no-upfront Compute Savings Plan discount vs on-demand.
SP_DISCOUNT_RATE = 0.27
# Don't bother below this current coverage-vs-target gap.
MIN_COVERAGE_GAP = 0.10

_COMPUTE_MARKERS = ("BoxUsage", "Fargate")
_COMMITTED_TERMS = ("SavingsPlan", "Reserved", "SavingsPlanCoveredUsage")


class SavingsPlanCoverageRule(base.Rule):
    rule_id = "savings-plan-coverage"
    title = "Cover steady on-demand compute with a Savings Plan"

    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        usage = base.usage_only(df)
        compute = usage.filter(
            pl.any_horizontal(
                [pl.col(S.USAGE_TYPE).str.contains(m) for m in _COMPUTE_MARKERS]
            )
        )
        if compute.height == 0:
            return []

        ondemand = compute.filter(pl.col(S.PRICING_TERM) == "OnDemand")
        committed = compute.filter(pl.col(S.PRICING_TERM).is_in(_COMMITTED_TERMS))

        ondemand_cost = base.cost_of(ondemand)
        committed_cost = base.cost_of(committed)
        total = ondemand_cost + committed_cost
        if total <= 0 or ondemand_cost <= 0:
            return []

        current_coverage = committed_cost / total
        if current_coverage >= TARGET_ONDEMAND_COVERAGE - MIN_COVERAGE_GAP:
            return []

        coverable = ondemand_cost * TARGET_ONDEMAND_COVERAGE
        savings = round(coverable * SP_DISCOUNT_RATE, 2)
        ids, count = base.resource_sample(ondemand)
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                category=Category.COMMITMENT,
                severity=base.severity_for(savings),
                monthly_cost=ondemand_cost,
                estimated_monthly_savings=savings,
                resource_ids=ids,
                affected_resource_count=count,
                confidence=0.7,
                detail=(
                    f"On-demand EC2/Fargate compute is ${ondemand_cost:,.0f}/mo with only "
                    f"{current_coverage:.0%} of compute on a commitment. Covering ~"
                    f"{int(TARGET_ONDEMAND_COVERAGE * 100)}% of the on-demand baseline with a "
                    f"1-yr no-upfront Compute Savings Plan (~{int(SP_DISCOUNT_RATE * 100)}% off) "
                    f"saves about ${savings:,.0f}/mo. Verify the baseline is steady before "
                    f"committing."
                ),
                recommendation=(
                    "Buy a 1-year no-upfront Compute Savings Plan sized to the steady "
                    "baseline (check the 14-day usage floor first). Commit RDS "
                    "separately with RDS Reserved Instances."
                ),
            )
        ]
