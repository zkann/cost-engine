"""Seeded synthetic AWS Cost & Usage Report generator.

Produces a month of daily, multi-account line items shaped like a real CUR,
with deliberately planted waste so every rule in the engine has something true
to find. Deterministic given a seed, so tests can assert on the numbers.

Every planted signal is derivable from columns AWS actually emits in a CUR:
- gp2 vs gp3 storage cost lives in ``line_item_usage_type``
  (``EBS:VolumeUsage.gp2`` vs ``.gp3``).
- AWS bills idle Elastic IPs under the ``ElasticIP:IdleAddress`` usage type.
- On-demand vs committed compute lives in ``pricing_term``.
- NAT and cross-AZ transfer have their own usage types.
- Tag coverage is just whether ``resource_tags_user_team`` is null.

Nothing here invents a detection signal that wouldn't exist in production data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import polars as pl

from .. import schema as S

# 12-digit member accounts under one mock organization.
ACCOUNTS = {
    "prod": "112233445566",
    "staging": "223344556677",
    "data": "334455667788",
}

DEFAULT_PERIOD = date(2026, 5, 1)


@dataclass
class ResourceSpec:
    """One logical group of resources billed the same way.

    ``monthly_cost`` is the group total for the month; it is split across
    ``count`` distinct resource ids and across the days in the period, with a
    little daily noise so the series looks real.
    """

    account: str
    service_name: str
    product_code: str
    usage_type: str
    operation: str
    pricing_term: str
    monthly_cost: float
    monthly_usage: float
    id_prefix: str
    count: int = 1
    region: str = "us-east-2"
    team: str | None = None
    environment: str | None = None
    line_item_type: str = "Usage"
    tags: dict = field(default_factory=dict)


def _build_specs() -> list[ResourceSpec]:
    """The scenario: a Series-A startup, a bit wasteful, ~$48k/month.

    Planted findings, by design:
      * gp2 volumes across all three accounts  -> gp2->gp3 migration
      * idle Elastic IPs in staging            -> waste
      * large steady on-demand compute         -> Savings Plan coverage gap
      * NAT + cross-AZ transfer in prod        -> data-transfer review
      * snapshot spend ~70% of volume spend    -> unmanaged retention
      * untagged S3 + compute                  -> cost-allocation governance
    """
    specs: list[ResourceSpec] = []

    # --- prod: the big spender ---------------------------------------------
    specs += [
        # Steady on-demand EC2 — the coverage-gap driver.
        ResourceSpec("prod", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-BoxUsage:m5.2xlarge", "RunInstances", "OnDemand",
                     8600.0, 8928.0, "i-prodweb", count=8, team="platform",
                     environment="production"),
        # A slice already committed — makes the coverage ratio realistic, not 0%.
        ResourceSpec("prod", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-BoxUsage:m5.2xlarge", "RunInstances", "SavingsPlan",
                     2900.0, 4464.0, "i-prodapi", count=4, team="platform",
                     environment="production"),
        # Aurora on-demand — also commitment-eligible.
        ResourceSpec("prod", "Amazon Relational Database Service", "AmazonRDS",
                     "USE2-InstanceUsage:db.r6g.xlarge", "CreateDBInstance", "OnDemand",
                     4100.0, 1488.0, "db-prod", count=2, team="platform",
                     environment="production"),
        # EBS gp2 — migrate to gp3.
        ResourceSpec("prod", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-EBS:VolumeUsage.gp2", "CreateVolume-Gp2", "OnDemand",
                     1850.0, 18500.0, "vol-prodgp2", count=14, team="platform",
                     environment="production"),
        ResourceSpec("prod", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-EBS:VolumeUsage.gp3", "CreateVolume-Gp3", "OnDemand",
                     1200.0, 15000.0, "vol-prodgp3", count=10, team="platform",
                     environment="production"),
        # Snapshot spend high relative to volume spend -> unmanaged retention.
        ResourceSpec("prod", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-EBS:SnapshotUsage", "CreateSnapshot", "OnDemand",
                     2150.0, 43000.0, "snap-prod", count=40, team="platform",
                     environment="production"),
        # NAT gateway hours + bytes (Zak's real single-NAT tradeoff territory).
        ResourceSpec("prod", "Amazon Virtual Private Cloud", "AmazonVPC",
                     "USE2-NatGateway-Hours", "NatGateway", "OnDemand",
                     1100.0, 2232.0, "nat-prod", count=3, team="platform",
                     environment="production"),
        ResourceSpec("prod", "Amazon Virtual Private Cloud", "AmazonVPC",
                     "USE2-NatGateway-Bytes", "NatGateway", "OnDemand",
                     1500.0, 33333.0, "nat-prod", count=3, team="platform",
                     environment="production"),
        # Cross-AZ data transfer.
        ResourceSpec("prod", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-DataTransfer-Regional-Bytes", "InterZone-In", "OnDemand",
                     1400.0, 140000.0, "i-prodweb", count=8, team="platform",
                     environment="production"),
        # S3 — half of it untagged (governance).
        ResourceSpec("prod", "Amazon Simple Storage Service", "AmazonS3",
                     "USE2-TimedStorage-ByteHrs", "StandardStorage", "OnDemand",
                     1400.0, 60869.0, "s3-prod-assets", count=2, team="platform",
                     environment="production"),
        ResourceSpec("prod", "Amazon Simple Storage Service", "AmazonS3",
                     "USE2-TimedStorage-ByteHrs", "StandardStorage", "OnDemand",
                     1100.0, 47826.0, "s3-prod-legacy", count=3, team=None,
                     environment=None),
        ResourceSpec("prod", "AWS Lambda", "AWSLambda",
                     "USE2-Lambda-GB-Second", "Invoke", "OnDemand",
                     620.0, 37200000.0, "fn-prod", count=12, team="platform",
                     environment="production"),
        ResourceSpec("prod", "Amazon CloudFront", "AmazonCloudFront",
                     "DataTransfer-Out-Bytes", "GET", "OnDemand",
                     880.0, 11000.0, "cf-prod", count=1, team="platform",
                     environment="production"),
    ]

    # --- staging: smaller, classic leftover waste --------------------------
    specs += [
        ResourceSpec("staging", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-BoxUsage:t3.large", "RunInstances", "OnDemand",
                     1450.0, 17856.0, "i-stgapp", count=6, team="platform",
                     environment="staging"),
        # Idle Elastic IPs left attached to nothing — pure waste.
        ResourceSpec("staging", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-ElasticIP:IdleAddress", "AssociateAddress", "OnDemand",
                     227.0, 6300.0, "eipalloc-stg", count=18, team="platform",
                     environment="staging"),
        ResourceSpec("staging", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-EBS:VolumeUsage.gp2", "CreateVolume-Gp2", "OnDemand",
                     640.0, 6400.0, "vol-stggp2", count=9, team="platform",
                     environment="staging"),
        ResourceSpec("staging", "Amazon Virtual Private Cloud", "AmazonVPC",
                     "USE2-NatGateway-Hours", "NatGateway", "OnDemand",
                     720.0, 1488.0, "nat-stg", count=2, team=None,
                     environment="staging"),
        ResourceSpec("staging", "Amazon Simple Storage Service", "AmazonS3",
                     "USE2-TimedStorage-ByteHrs", "StandardStorage", "OnDemand",
                     430.0, 18695.0, "s3-stg", count=2, team=None,
                     environment="staging"),
    ]

    # --- data: analytics account, heavy untagged S3 ------------------------
    specs += [
        ResourceSpec("data", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-BoxUsage:r5.4xlarge", "RunInstances", "OnDemand",
                     3550.0, 2976.0, "i-dataemr", count=4, team="data",
                     environment="production"),
        ResourceSpec("data", "Amazon Simple Storage Service", "AmazonS3",
                     "USE2-TimedStorage-ByteHrs", "StandardStorage", "OnDemand",
                     2600.0, 113043.0, "s3-datalake", count=4, team=None,
                     environment=None),
        ResourceSpec("data", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-EBS:VolumeUsage.gp2", "CreateVolume-Gp2", "OnDemand",
                     710.0, 7100.0, "vol-datagp2", count=6, team="data",
                     environment="production"),
        ResourceSpec("data", "Amazon Elastic Compute Cloud - Compute", "AmazonEC2",
                     "USE2-EBS:SnapshotUsage", "CreateSnapshot", "OnDemand",
                     1180.0, 23600.0, "snap-data", count=30, team="data",
                     environment="production"),
        ResourceSpec("data", "Amazon Athena", "AmazonAthena",
                     "USE2-DataScannedInTB", "StartQueryExecution", "OnDemand",
                     820.0, 164.0, "athena-data", count=1, team=None,
                     environment=None),
    ]

    return specs


def _daily_rows(spec: ResourceSpec, period: date, rng: random.Random) -> list[dict]:
    """Expand one spec into daily line items per distinct resource."""
    days = _days_in_month(period)
    rows: list[dict] = []
    # Split the group total across resources, then across days with noise.
    per_resource_cost = spec.monthly_cost / spec.count
    per_resource_usage = spec.monthly_usage / spec.count

    for _ in range(spec.count):
        resource_id = f"{spec.id_prefix}-{rng.randrange(16**8):08x}"
        # Daily weights jitter around uniform so the time series is not flat.
        weights = [rng.uniform(0.85, 1.15) for _ in range(days)]
        wsum = sum(weights)
        for d in range(days):
            usage_date = period + timedelta(days=d)
            frac = weights[d] / wsum
            rows.append(
                {
                    S.BILL_PERIOD: period,
                    S.USAGE_DATE: usage_date,
                    S.ACCOUNT_ID: ACCOUNTS[spec.account],
                    S.PRODUCT_CODE: spec.product_code,
                    S.SERVICE_NAME: spec.service_name,
                    S.USAGE_TYPE: spec.usage_type,
                    S.OPERATION: spec.operation,
                    S.RESOURCE_ID: resource_id,
                    S.LINE_ITEM_TYPE: spec.line_item_type,
                    S.REGION: spec.region,
                    S.UNBLENDED_COST: round(per_resource_cost * frac, 6),
                    S.USAGE_AMOUNT: round(per_resource_usage * frac, 6),
                    S.PRICING_TERM: spec.pricing_term,
                    S.TAG_TEAM: spec.team,
                    S.TAG_ENVIRONMENT: spec.environment,
                }
            )
    return rows


def _days_in_month(period: date) -> int:
    if period.month == 12:
        nxt = date(period.year + 1, 1, 1)
    else:
        nxt = date(period.year, period.month + 1, 1)
    return (nxt - period).days


def generate_synthetic_cur(
    period: date = DEFAULT_PERIOD, seed: int = 42
) -> pl.DataFrame:
    """Return a deterministic synthetic CUR as a polars DataFrame.

    The DataFrame conforms to ``schema.SCHEMA`` and is ready to hand to the
    aggregation and rules layers exactly like real ingested data.
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    for spec in _build_specs():
        rows.extend(_daily_rows(spec, period, rng))
    return pl.DataFrame(rows, schema=S.SCHEMA)
