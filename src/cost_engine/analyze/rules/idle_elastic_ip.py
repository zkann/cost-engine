"""Rule: release idle Elastic IP addresses.

AWS bills an Elastic IP that is allocated but not associated with a running
instance under the ``ElasticIP:IdleAddress`` usage type. Every dollar there is
pure waste: the address is reserved and doing nothing. Releasing it (or
attaching it) reclaims the full amount, so the estimated saving is 100% of the
spend.
"""

from __future__ import annotations

import polars as pl

from ... import schema as S
from ...models import Category, Finding
from . import base


class IdleElasticIpRule(base.Rule):
    rule_id = "idle-elastic-ip"
    title = "Release idle Elastic IP addresses"

    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        idle = base.usage_only(df).filter(
            pl.col(S.USAGE_TYPE).str.contains("ElasticIP:IdleAddress")
        )
        monthly_cost = base.cost_of(idle)
        if monthly_cost <= 0:
            return []

        ids, count = base.resource_sample(idle)
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                category=Category.WASTE,
                severity=base.severity_for(monthly_cost),
                monthly_cost=monthly_cost,
                estimated_monthly_savings=monthly_cost,  # 100% recoverable
                resource_ids=ids,
                affected_resource_count=count,
                confidence=0.97,
                detail=(
                    f"{count} Elastic IP(s) are billed as idle (allocated but not "
                    f"attached to a running instance), costing ${monthly_cost:,.0f}/mo. "
                    f"Idle EIPs are charged at the full hourly rate for doing nothing."
                ),
                recommendation=(
                    "Release the idle addresses, or attach them to a running "
                    "instance/NAT/NLB if they are reserved for one. Most are "
                    "leftovers from torn-down resources."
                ),
            )
        ]
