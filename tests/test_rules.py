"""Each rule fires with the expected dollars on planted data, and stays quiet on clean data."""

from __future__ import annotations

import polars as pl
import pytest

from cost_engine.analyze.rules import (
    DataTransferRule,
    Gp2ToGp3Rule,
    IdleElasticIpRule,
    SavingsPlanCoverageRule,
    SnapshotRetentionRule,
    UntaggedSpendRule,
)
from cost_engine.models import Category, Severity

# Expected monthly savings on the seed-42 synthetic account, derived by hand
# from the generator specs (see ingest/synthetic.py).
EXPECTED = {
    Gp2ToGp3Rule: 640.0,        # (1850 + 640 + 710) gp2 * 0.20
    IdleElasticIpRule: 227.0,   # staging idle EIP, 100% recoverable
    SnapshotRetentionRule: 1332.0,  # (2150 + 1180) * 0.40
    SavingsPlanCoverageRule: 2570.4,  # 13600 on-demand * 0.70 * 0.27
    DataTransferRule: 1416.0,   # (1100 + 1500 + 1400 + 720) * 0.30
}

ALL_RULE_CLASSES = [*EXPECTED.keys(), UntaggedSpendRule]


@pytest.mark.parametrize("rule_cls,expected", list(EXPECTED.items()))
def test_rule_fires_with_expected_savings(synthetic_df, rule_cls, expected) -> None:
    findings = rule_cls().evaluate(synthetic_df)
    assert len(findings) == 1
    assert findings[0].estimated_monthly_savings == pytest.approx(expected, abs=1.0)


@pytest.mark.parametrize("rule_cls", ALL_RULE_CLASSES)
def test_rule_quiet_on_clean_data(clean_df: pl.DataFrame, rule_cls) -> None:
    assert rule_cls().evaluate(clean_df) == []


def test_untagged_is_governance_not_savings(synthetic_df) -> None:
    findings = UntaggedSpendRule().evaluate(synthetic_df)
    assert len(findings) == 1
    f = findings[0]
    assert f.category is Category.GOVERNANCE
    assert f.severity is Severity.INFO
    assert f.estimated_monthly_savings == 0.0
    assert f.monthly_cost > 0  # there IS unallocable spend to report


def test_idle_eip_is_fully_recoverable(synthetic_df) -> None:
    f = IdleElasticIpRule().evaluate(synthetic_df)[0]
    # An idle EIP does nothing, so the whole cost is the saving.
    assert f.estimated_monthly_savings == f.monthly_cost


def test_snapshot_severity_capped(synthetic_df) -> None:
    # Low-confidence estimate must not present as HIGH even at >$1k.
    f = SnapshotRetentionRule().evaluate(synthetic_df)[0]
    assert f.severity is not Severity.HIGH
