"""Rule: migrate gp2 EBS volumes to gp3.

gp3 storage lists ~20% cheaper than gp2 ($0.08 vs $0.10 per GB-month in
us-east-2) at equal or better baseline performance, and the migration is an
online volume-type change with no downtime. This is one of the highest-
confidence CUR-only findings: the volume type is right there in the usage type.
"""

from __future__ import annotations

import polars as pl

from ... import schema as S
from ...models import Category, Finding
from . import base

# gp3 storage is ~20% cheaper than gp2 per GB-month at the same capacity.
GP3_SAVINGS_RATE = 0.20


class Gp2ToGp3Rule(base.Rule):
    rule_id = "ebs-gp2-to-gp3"
    title = "Migrate gp2 EBS volumes to gp3"

    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        gp2 = base.usage_only(df).filter(
            pl.col(S.USAGE_TYPE).str.contains("EBS:VolumeUsage.gp2")
        )
        monthly_cost = base.cost_of(gp2)
        if monthly_cost <= 0:
            return []

        savings = round(monthly_cost * GP3_SAVINGS_RATE, 2)
        ids, count = base.resource_sample(gp2)
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                category=Category.RIGHTSIZING,
                severity=base.severity_for(savings),
                monthly_cost=monthly_cost,
                estimated_monthly_savings=savings,
                resource_ids=ids,
                affected_resource_count=count,
                confidence=0.95,
                detail=(
                    f"{count} gp2 volume(s) cost ${monthly_cost:,.0f}/mo. gp3 lists "
                    f"~{int(GP3_SAVINGS_RATE * 100)}% cheaper per GB-month at equal "
                    f"baseline performance, so the same capacity on gp3 saves about "
                    f"${savings:,.0f}/mo."
                ),
                recommendation=(
                    "Change the volume type from gp2 to gp3 (online, no downtime). "
                    "gp3 also decouples IOPS/throughput from size if any volume "
                    "needs more than the 3,000 IOPS baseline."
                ),
            )
        ]
