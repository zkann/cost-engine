"""Rule: low Reserved Instance coverage on steady RDS / Aurora compute.

RDS and Aurora database instances that run around the clock are the classic
Reserved Instance candidate, and Compute Savings Plans do NOT cover them, so a
database-heavy bill can look "optimized" while its largest line sits at full
on-demand. CUR carries the price term per line, so coverage is measurable: this
estimates the saving on the steady baseline of on-demand RDS *instance* usage at
a conservative 1-year no-upfront RDS RI discount.

Scope is instance usage (``InstanceUsage`` / ``InstanceUsageIOOptimized``); RDS
storage, backups, and I/O are priced separately and aren't RI-eligible.
"""

from __future__ import annotations

import polars as pl

from ... import schema as S
from ...models import Category, Finding
from . import base

# Share of on-demand RDS instance spend steady enough to reserve.
TARGET_ONDEMAND_COVERAGE = 0.70
# Conservative 1-yr no-upfront RDS/Aurora Reserved Instance discount vs on-demand.
RI_DISCOUNT_RATE = 0.30
MIN_COVERAGE_GAP = 0.10
_COMMITTED_TERMS = ("Reserved", "DiscountedUsage")


class RdsReservedCoverageRule(base.Rule):
    rule_id = "rds-reserved-coverage"
    title = "Cover steady on-demand RDS with Reserved Instances"

    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        usage = base.usage_only(df)
        # RDS/Aurora instance usage. Guard on product code when it's present so
        # other services' "*InstanceUsage*" types can't sneak in.
        rds = usage.filter(
            pl.col(S.USAGE_TYPE).str.contains("InstanceUsage")
            & ((pl.col(S.PRODUCT_CODE) == "AmazonRDS") | pl.col(S.PRODUCT_CODE).is_null())
        )
        if rds.height == 0:
            return []

        ondemand = rds.filter(pl.col(S.PRICING_TERM) == "OnDemand")
        committed = rds.filter(pl.col(S.PRICING_TERM).is_in(_COMMITTED_TERMS))
        ondemand_cost = base.cost_of(ondemand)
        committed_cost = base.cost_of(committed)
        total = ondemand_cost + committed_cost
        if total <= 0 or ondemand_cost <= 0:
            return []

        current_coverage = committed_cost / total
        if current_coverage >= TARGET_ONDEMAND_COVERAGE - MIN_COVERAGE_GAP:
            return []

        coverable = ondemand_cost * TARGET_ONDEMAND_COVERAGE
        savings = round(coverable * RI_DISCOUNT_RATE, 2)
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
                confidence=0.65,
                detail=(
                    f"On-demand RDS/Aurora instance usage is ${ondemand_cost:,.0f}/mo with "
                    f"only {current_coverage:.0%} on a commitment. Reserving ~"
                    f"{int(TARGET_ONDEMAND_COVERAGE * 100)}% of the steady baseline with "
                    f"1-yr no-upfront Reserved Instances (~{int(RI_DISCOUNT_RATE * 100)}% off) "
                    f"saves about ${savings:,.0f}/mo. Compute Savings Plans do not cover RDS, "
                    f"so this spend is easy to miss."
                ),
                recommendation=(
                    "Buy 1-year no-upfront RDS/Aurora Reserved Instances sized to the "
                    "steady database baseline (match engine, class, and region). Confirm "
                    "the instances run continuously before committing."
                ),
            )
        ]
