"""Shared fixtures."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from cost_engine import schema as S
from cost_engine.ingest import generate_synthetic_cur


@pytest.fixture
def synthetic_df() -> pl.DataFrame:
    return generate_synthetic_cur(period=date(2026, 5, 1), seed=42)


@pytest.fixture
def clean_df() -> pl.DataFrame:
    """A tiny, waste-free dataset: one tagged, committed, gp3 workload."""
    rows = [
        {
            S.BILL_PERIOD: date(2026, 5, 1),
            S.USAGE_DATE: date(2026, 5, 1),
            S.ACCOUNT_ID: "111111111111",
            S.PRODUCT_CODE: "AmazonEC2",
            S.SERVICE_NAME: "Amazon Elastic Compute Cloud - Compute",
            S.USAGE_TYPE: "USE2-BoxUsage:m5.large",
            S.OPERATION: "RunInstances",
            S.RESOURCE_ID: "i-clean0001",
            S.LINE_ITEM_TYPE: "Usage",
            S.REGION: "us-east-2",
            S.UNBLENDED_COST: 100.0,
            S.USAGE_AMOUNT: 720.0,
            S.PRICING_TERM: "SavingsPlan",
            S.TAG_TEAM: "platform",
            S.TAG_ENVIRONMENT: "production",
        }
    ]
    return pl.DataFrame(rows, schema=S.SCHEMA)
