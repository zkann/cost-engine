"""Column normalization: resilient to varied CUR shapes."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from cost_engine import schema as S
from cost_engine.analyze import analyze, build_breakdowns
from cost_engine.ingest.normalize import to_canonical, to_snake


def _minimal_raw_cur() -> pl.DataFrame:
    """A CUR with only core columns + product code, no service/region/tags.

    Raw camelCase/slash spelling, to exercise renaming and the fallbacks at once.
    """
    return pl.DataFrame(
        {
            "bill/BillingPeriodStartDate": [date(2026, 5, 1), date(2026, 5, 1)],
            "lineItem/UsageStartDate": [date(2026, 5, 1), date(2026, 5, 2)],
            "lineItem/UsageAccountId": ["111122223333", "111122223333"],
            "lineItem/UsageType": ["USE2-EBS:VolumeUsage.gp2", "USE2-BoxUsage:m5.large"],
            "lineItem/LineItemType": ["Usage", "Usage"],
            "lineItem/UnblendedCost": [2000.0, 500.0],
            "lineItem/ProductCode": ["AmazonEC2", "AmazonEC2"],
        }
    )


def test_to_snake_handles_raw_and_normalized() -> None:
    assert to_snake("lineItem/UnblendedCost") == "line_item_unblended_cost"
    assert to_snake("resourceTags/user:Team") == "resource_tags_user_team"
    assert to_snake("line_item_unblended_cost") == "line_item_unblended_cost"


def test_optional_columns_filled_and_service_falls_back() -> None:
    df = to_canonical(_minimal_raw_cur())
    assert list(df.columns) == list(S.SCHEMA.keys())
    # Service name fell back to the product code.
    assert df[S.SERVICE_NAME].to_list() == ["AmazonEC2", "AmazonEC2"]
    # Absent optional columns are present as all-null.
    assert df[S.REGION].null_count() == df.height
    assert df[S.TAG_TEAM].null_count() == df.height


def test_resilient_cur_still_analyzes() -> None:
    df = to_canonical(_minimal_raw_cur())
    report = analyze(df)
    # gp2 volume is there, so the gp2->gp3 rule should still fire.
    assert any(f.rule_id == "ebs-gp2-to-gp3" for f in report.findings)
    # Breakdowns don't blow up on the null region/team columns.
    assert build_breakdowns(df)


def test_missing_essential_column_raises() -> None:
    raw = _minimal_raw_cur().drop("lineItem/UnblendedCost")
    with pytest.raises(ValueError, match="essential columns"):
        to_canonical(raw)
