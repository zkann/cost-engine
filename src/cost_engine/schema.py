"""Canonical column schema for the in-memory cost dataset.

The names mirror the real AWS Cost & Usage Report (CUR) v1 columns (the
``group/name`` form, lower-snaked) so the synthetic generator, the real CUR
loader, and the rules engine all agree on one vocabulary. Keeping the real
names means a CUR pulled straight from S3 maps onto this schema with a thin
rename rather than a translation layer.

Reference: AWS CUR data dictionary
https://docs.aws.amazon.com/cur/latest/userguide/data-dictionary.html
"""

from __future__ import annotations

import polars as pl

# --- Identity / period -----------------------------------------------------
BILL_PERIOD = "bill_billing_period_start_date"  # e.g. 2026-05-01
USAGE_DATE = "line_item_usage_start_date"  # daily granularity
ACCOUNT_ID = "line_item_usage_account_id"  # 12-digit member account

# --- What was used ---------------------------------------------------------
PRODUCT_CODE = "line_item_product_code"  # AmazonEC2, AmazonS3, ...
SERVICE_NAME = "product_servicename"  # human-readable service
USAGE_TYPE = "line_item_usage_type"  # USE2-BoxUsage:t3.medium, EBS:VolumeUsage.gp2
OPERATION = "line_item_operation"  # RunInstances, CreateVolume-Gp2, ...
RESOURCE_ID = "line_item_resource_id"  # vol-..., i-..., arn:...
LINE_ITEM_TYPE = "line_item_line_item_type"  # Usage, DiscountedUsage, Tax, ...
REGION = "product_region"  # us-east-2, eu-west-1, ...

# --- Money / quantity ------------------------------------------------------
UNBLENDED_COST = "line_item_unblended_cost"  # USD for the line item
USAGE_AMOUNT = "line_item_usage_amount"  # units consumed
PRICING_TERM = "pricing_term"  # OnDemand, Reserved, SavingsPlan, Spot

# --- Allocation ------------------------------------------------------------
# Resource tags are flattened to columns prefixed ``resource_tags_user_``,
# matching how Athena exposes ``resourceTags/user:Team`` etc.
TAG_PREFIX = "resource_tags_user_"
TAG_TEAM = f"{TAG_PREFIX}team"
TAG_ENVIRONMENT = f"{TAG_PREFIX}environment"

#: Columns every cost dataset must carry, with their polars dtypes.
SCHEMA: dict[str, pl.DataType] = {
    BILL_PERIOD: pl.Date,
    USAGE_DATE: pl.Date,
    ACCOUNT_ID: pl.Utf8,
    PRODUCT_CODE: pl.Utf8,
    SERVICE_NAME: pl.Utf8,
    USAGE_TYPE: pl.Utf8,
    OPERATION: pl.Utf8,
    RESOURCE_ID: pl.Utf8,
    LINE_ITEM_TYPE: pl.Utf8,
    REGION: pl.Utf8,
    UNBLENDED_COST: pl.Float64,
    USAGE_AMOUNT: pl.Float64,
    PRICING_TERM: pl.Utf8,
    TAG_TEAM: pl.Utf8,
    TAG_ENVIRONMENT: pl.Utf8,
}

#: Line-item types that represent real, allocable usage cost (exclude tax,
#: refunds, and credits from savings math).
USAGE_LINE_ITEM_TYPES = ("Usage", "DiscountedUsage", "SavingsPlanCoveredUsage")
