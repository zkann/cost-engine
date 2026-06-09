"""Cost Explorer connector, against a stubbed boto3 client (no live AWS)."""

from __future__ import annotations

from datetime import date

import pytest

boto3 = pytest.importorskip("boto3")
from botocore.stub import Stubber  # noqa: E402

from cost_engine import schema as S  # noqa: E402
from cost_engine.analyze import analyze  # noqa: E402
from cost_engine.analyze.rules import ALL_RULES  # noqa: E402
from cost_engine.ingest.cost_explorer import (  # noqa: E402
    CE_UNSUPPORTED_RULE_IDS,
    load_from_cost_explorer,
)

START, END = date(2026, 5, 1), date(2026, 5, 31)


def _group(service: str, usage_type: str, amount: str) -> dict:
    return {"Keys": [service, usage_type],
            "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}


def _ce_response(groups: list[dict], next_token: str | None = None) -> dict:
    resp = {
        "ResultsByTime": [
            {"TimePeriod": {"Start": "2026-05-01", "End": "2026-06-01"},
             "Groups": groups, "Estimated": False}
        ]
    }
    if next_token:
        resp["NextPageToken"] = next_token
    return resp


def _stubbed_ce():
    client = boto3.client("ce", region_name="us-east-1",
                          aws_access_key_id="x", aws_secret_access_key="x")
    return client, Stubber(client)


def test_loads_service_and_usage_type_rows() -> None:
    client, stub = _stubbed_ce()
    stub.add_response("get_cost_and_usage", _ce_response([
        _group("Amazon Elastic Compute Cloud - Compute", "USE2-EBS:VolumeUsage.gp2", "1850"),
        _group("Amazon Elastic Compute Cloud - Compute", "USE2-ElasticIP:IdleAddress", "227"),
        _group("Amazon Simple Storage Service", "USE2-TimedStorage-ByteHrs", "0"),  # dropped
    ]))
    with stub:
        df = load_from_cost_explorer(START, END, client=client)
    assert df.height == 2  # the $0 row is dropped
    assert df[S.UNBLENDED_COST].sum() == pytest.approx(2077.0)
    # No tags / purchase term / resource ids from Cost Explorer.
    assert df[S.TAG_TEAM].null_count() == df.height
    assert df[S.PRICING_TERM].null_count() == df.height
    assert df[S.RESOURCE_ID].null_count() == df.height


def test_paginates() -> None:
    client, stub = _stubbed_ce()
    stub.add_response("get_cost_and_usage", _ce_response(
        [_group("AmazonEC2", "USE2-EBS:VolumeUsage.gp2", "1000")], next_token="page2"))
    stub.add_response("get_cost_and_usage", _ce_response(
        [_group("AmazonEC2", "USE2-EBS:VolumeUsage.gp2", "500")]))
    with stub:
        df = load_from_cost_explorer(START, END, client=client)
    assert df.height == 2
    assert df[S.UNBLENDED_COST].sum() == pytest.approx(1500.0)


def test_supported_rules_fire_unsupported_skipped() -> None:
    client, stub = _stubbed_ce()
    stub.add_response("get_cost_and_usage", _ce_response([
        _group("Amazon Elastic Compute Cloud - Compute", "USE2-EBS:VolumeUsage.gp2", "1850"),
    ]))
    with stub:
        df = load_from_cost_explorer(START, END, client=client)

    supported = [r for r in ALL_RULES if r.rule_id not in CE_UNSUPPORTED_RULE_IDS]
    findings = analyze(df, rules=supported).findings
    ids = {f.rule_id for f in findings}
    assert "ebs-gp2-to-gp3" in ids
    assert ids.isdisjoint(CE_UNSUPPORTED_RULE_IDS)
