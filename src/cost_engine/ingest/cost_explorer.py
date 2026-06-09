"""Load a top-line dataset from the Cost Explorer API.

Cost Explorer is the fast path: no CUR setup, no S3, just an API call. The
tradeoff is granularity. A single ``get_cost_and_usage`` call allows at most two
group-by dimensions, so this connector groups by **service and usage type**.
That is enough for the cost-by-service breakdown and every usage-type savings
rule (gp2->gp3, idle EIPs, snapshot retention, NAT / data transfer), but it
carries **no resource IDs, no tags, and no purchase term.**

So two rules can't run on this source and are skipped by the CLI:
- untagged spend (Cost Explorer didn't fetch tags; absent != untagged), and
- Savings Plan coverage (needs the on-demand vs committed split).

For those, and for resource-level detail, use the S3 CUR connector. boto3 is
imported lazily; install with ``pip install cost-engine[aws]``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import polars as pl

from .. import schema as S

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_ce import CostExplorerClient

#: Rules that cannot be evaluated from a Cost Explorer dataset (see module docs).
CE_UNSUPPORTED_RULE_IDS = frozenset({"untagged-spend", "savings-plan-coverage"})


def _require_ce_client(client):
    if client is not None:
        return client
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "the Cost Explorer connector needs boto3. Install with: "
            "pip install 'cost-engine[aws]'"
        ) from exc
    return boto3.client("ce")


def _default_period() -> tuple[date, date]:
    """Current month to date. End is exclusive, per the Cost Explorer API."""
    today = datetime.now(UTC).date()
    return today.replace(day=1), today


def load_from_cost_explorer(
    start: date | None = None,
    end: date | None = None,
    *,
    client: CostExplorerClient | None = None,
) -> pl.DataFrame:
    """Return a canonical DataFrame of cost by service x usage type.

    Defaults to the current month to date. Populates service, usage type, region
    (when present in the key), cost, and date; leaves account, tags, purchase
    term, and resource id null (see module docs).
    """
    if start is None or end is None:
        start, end = _default_period()

    ce = _require_ce_client(client)
    rows: list[dict] = []
    next_token: str | None = None

    while True:
        kwargs = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [
                {"Type": "DIMENSION", "Key": "SERVICE"},
                {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
            ],
        }
        if next_token:
            kwargs["NextPageToken"] = next_token

        resp = ce.get_cost_and_usage(**kwargs)
        for bucket in resp.get("ResultsByTime", []):
            period_start = date.fromisoformat(bucket["TimePeriod"]["Start"])
            for group in bucket.get("Groups", []):
                service, usage_type = group["Keys"][0], group["Keys"][1]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if amount == 0:
                    continue
                rows.append(_row(period_start, service, usage_type, amount))

        next_token = resp.get("NextPageToken")
        if not next_token:
            break

    return pl.DataFrame(rows, schema=S.SCHEMA)


def _row(period_start: date, service: str, usage_type: str, cost: float) -> dict:
    return {
        S.BILL_PERIOD: period_start,
        S.USAGE_DATE: period_start,
        S.ACCOUNT_ID: None,
        S.PRODUCT_CODE: None,
        S.SERVICE_NAME: service,
        S.USAGE_TYPE: usage_type,
        S.OPERATION: None,
        S.RESOURCE_ID: None,
        S.LINE_ITEM_TYPE: "Usage",
        S.REGION: None,
        S.UNBLENDED_COST: cost,
        S.USAGE_AMOUNT: None,
        S.PRICING_TERM: None,
        S.TAG_TEAM: None,
        S.TAG_ENVIRONMENT: None,
    }
