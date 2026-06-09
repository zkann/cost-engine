"""Rule: NAT gateway and cross-AZ data-transfer spend.

NAT processing and cross-AZ ("regional") transfer are the quiet line items that
balloon as traffic grows. Much of it is avoidable: S3/DynamoDB gateway VPC
endpoints are free and bypass NAT entirely, interface endpoints cut NAT bytes
for other AWS services, and co-locating chatty services in one AZ removes
cross-AZ charges. CUR exposes both via dedicated usage types.

This is framed as a review, not a guaranteed cut: the recoverable share depends
on traffic mix, so the estimate is conservative and lower-confidence.
"""

from __future__ import annotations

import polars as pl

from ... import schema as S
from ...models import Category, Finding, Severity
from . import base

# Conservative share recoverable via VPC endpoints + AZ co-location.
RECOVERABLE_FRACTION = 0.30
# Floor below which the review isn't worth surfacing.
MIN_MONTHLY_COST = 100.0


class DataTransferRule(base.Rule):
    rule_id = "nat-and-data-transfer"
    title = "Review NAT and cross-AZ data-transfer spend"

    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        usage = base.usage_only(df)
        transfer = usage.filter(
            pl.col(S.USAGE_TYPE).str.contains("NatGateway")
            | pl.col(S.USAGE_TYPE).str.contains("DataTransfer-Regional-Bytes")
        )
        monthly_cost = base.cost_of(transfer)
        if monthly_cost < MIN_MONTHLY_COST:
            return []

        nat_cost = base.cost_of(
            transfer.filter(pl.col(S.USAGE_TYPE).str.contains("NatGateway"))
        )
        savings = round(monthly_cost * RECOVERABLE_FRACTION, 2)
        ids, count = base.resource_sample(transfer)
        sev = base.severity_for(savings)
        sev = Severity.MEDIUM if sev == Severity.HIGH else sev  # review, cap impact
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                category=Category.DATA_TRANSFER,
                severity=sev,
                monthly_cost=monthly_cost,
                estimated_monthly_savings=savings,
                resource_ids=ids,
                affected_resource_count=count,
                confidence=0.5,
                detail=(
                    f"NAT and cross-AZ transfer total ${monthly_cost:,.0f}/mo "
                    f"(NAT ${nat_cost:,.0f}/mo). Routing AWS-bound traffic through VPC "
                    f"endpoints and co-locating chatty services in one AZ typically "
                    f"recovers ~{int(RECOVERABLE_FRACTION * 100)}% (~${savings:,.0f}/mo). "
                    f"Exact savings depend on the traffic mix."
                ),
                recommendation=(
                    "Add free S3/DynamoDB gateway endpoints and interface endpoints "
                    "for the busiest AWS services; check VPC flow logs for the top "
                    "NAT talkers; co-locate high-chatter services in a single AZ."
                ),
            )
        ]
