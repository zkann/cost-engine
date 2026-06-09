"""Engine assembly, aggregation, and report rendering."""

from __future__ import annotations

import json

from cost_engine.analyze import analyze, build_breakdowns, distinct_accounts, total_cost
from cost_engine.report import render_json, render_markdown, summarize


def test_distinct_accounts_from_synthetic(synthetic_df) -> None:
    accts = distinct_accounts(synthetic_df)
    assert accts == ["112233445566", "223344556677", "334455667788"]


def test_markdown_shows_provenance_when_set(synthetic_df) -> None:
    r = analyze(synthetic_df)
    r.source = "file: my-cur.parquet"
    r.account_note = "accounts: 112233445566"
    md = render_markdown(r)
    assert "**Source:** file: my-cur.parquet" in md
    assert "**Account:** accounts: 112233445566" in md


def test_markdown_omits_provenance_when_absent(synthetic_df) -> None:
    md = render_markdown(analyze(synthetic_df))
    assert "**Source:**" not in md
    assert "**Account:**" not in md


def test_analyze_assembles_full_report(synthetic_df) -> None:
    r = analyze(synthetic_df)
    assert r.total_cost == total_cost(synthetic_df)
    assert len(r.findings) == 7  # all rules fire on the synthetic account
    assert {"savings-plan-coverage", "rds-reserved-coverage"} <= {f.rule_id for f in r.findings}
    assert r.total_estimated_monthly_savings > 0
    assert 0 < r.savings_pct_of_spend < 1


def test_findings_sorted_by_savings(synthetic_df) -> None:
    r = analyze(synthetic_df)
    savings = [f.estimated_monthly_savings for f in r.findings]
    assert savings == sorted(savings, reverse=True)


def test_breakdown_shares_sum_to_one(synthetic_df) -> None:
    for b in build_breakdowns(synthetic_df):
        assert abs(sum(s.share for s in b.slices) - 1.0) < 0.02


def test_untagged_shows_in_team_breakdown(synthetic_df) -> None:
    team = next(b for b in build_breakdowns(synthetic_df) if b.dimension == "team")
    assert "untagged" in {s.key for s in team.slices}


def test_null_region_not_labeled_untagged(synthetic_df) -> None:
    import polars as pl

    from cost_engine import schema as S
    from cost_engine.analyze.aggregate import build_breakdown

    # Null out region on some rows; the null bucket is "no region", not "untagged".
    df = synthetic_df.with_columns(
        pl.when(pl.col(S.PRODUCT_CODE) == "AmazonS3")
        .then(None)
        .otherwise(pl.col(S.REGION))
        .alias(S.REGION)
    )
    region = build_breakdown(df, "region")
    keys = {s.key for s in region.slices}
    assert "no region" in keys
    assert "untagged" not in keys


def test_all_null_dimension_breakdown_suppressed(synthetic_df) -> None:
    import polars as pl

    from cost_engine import schema as S

    df = synthetic_df.with_columns(pl.lit(None).cast(pl.Utf8).alias(S.REGION))
    dims = {b.dimension for b in build_breakdowns(df)}
    assert "region" not in dims  # nothing to break down, so it's dropped
    assert "service" in dims  # other dimensions still present


def _make_report(findings) -> object:
    from datetime import UTC, date, datetime

    from cost_engine.models import Report

    total_savings = sum(f.estimated_monthly_savings for f in findings)
    return Report(
        billing_period=date(2026, 5, 1),
        generated_at=datetime.now(UTC),
        total_cost=450.0,
        total_estimated_monthly_savings=total_savings,
        savings_pct_of_spend=min(total_savings / 450.0, 1.0),
        findings=findings,
    )


def _finding(rule_id, title, category, savings, confidence):
    from cost_engine.models import Finding, Severity

    return Finding(
        rule_id=rule_id,
        title=title,
        category=category,
        severity=Severity.LOW,
        monthly_cost=savings * 2,
        estimated_monthly_savings=savings,
        detail="x",
        recommendation="y",
        confidence=confidence,
    )


def test_fallback_advice_never_names_absent_rules() -> None:
    from cost_engine.models import Category

    # Commitment-only report: the old hardcoded closer named gp2-to-gp3 and
    # idle resources even when those rules didn't fire.
    report = _make_report(
        [
            _finding(
                "rds-reserved-coverage",
                "Cover steady on-demand RDS with Reserved Instances",
                Category.COMMITMENT,
                41.0,
                0.65,
            )
        ]
    )
    summarize(report, use_llm=False)
    combined = report.executive_summary + " " + report.next_step
    assert "gp2" not in combined and "idle" not in combined.lower()
    assert "commitment" in report.next_step.lower()  # the caveat that IS relevant


def test_fallback_advice_names_quick_wins_when_present() -> None:
    from cost_engine.models import Category

    report = _make_report(
        [
            _finding(
                "idle-elastic-ip",
                "Release idle Elastic IP addresses",
                Category.WASTE,
                100.0,
                0.97,
            )
        ]
    )
    summarize(report, use_llm=False)
    assert "release idle elastic ip addresses" in report.next_step.lower()


def test_severity_escalates_on_share_of_spend(synthetic_df) -> None:
    import polars as pl

    from cost_engine import schema as S
    from cost_engine.models import Severity

    # Shrink the synthetic bill so the RDS finding's savings clear 10% of total
    # spend; the absolute-dollar triage would call it LOW, the share floor
    # raises it.
    small = synthetic_df.with_columns(
        (pl.col(S.UNBLENDED_COST) / 100).alias(S.UNBLENDED_COST)
    )
    r = analyze(small)
    rds = next(f for f in r.findings if f.rule_id == "rds-reserved-coverage")
    assert rds.estimated_monthly_savings / r.total_cost < 0.05
    sp = next(f for f in r.findings if f.rule_id == "savings-plan-coverage")
    assert sp.estimated_monthly_savings / r.total_cost >= 0.05
    assert sp.severity in (Severity.MEDIUM, Severity.HIGH)


def test_low_confidence_not_escalated() -> None:
    from cost_engine.analyze.engine import _calibrate_severity
    from cost_engine.models import Category, Severity

    # 20% of spend but only 0.5 confidence: a low-confidence rule's deliberate
    # severity cap must survive share-of-spend escalation.
    f = _finding("nat-and-data-transfer", "x", Category.DATA_TRANSFER, 90.0, 0.5)
    _calibrate_severity([f], total=450.0)
    assert f.severity is Severity.LOW


def test_fallback_summary_singular_grammar() -> None:
    from datetime import UTC, date, datetime

    from cost_engine.models import Category, Finding, Report, Severity

    report = Report(
        billing_period=date(2026, 5, 1),
        generated_at=datetime.now(UTC),
        total_cost=1000.0,
        total_estimated_monthly_savings=100.0,
        savings_pct_of_spend=0.1,
        findings=[
            Finding(
                rule_id="ebs-gp2-to-gp3",
                title="Migrate gp2 EBS volumes to gp3",
                category=Category.RIGHTSIZING,
                severity=Severity.MEDIUM,
                monthly_cost=500.0,
                estimated_monthly_savings=100.0,
                detail="x",
                recommendation="y",
            )
        ],
    )
    summarize(report, use_llm=False)
    s = report.executive_summary
    assert "1 opportunity" in s and "opportunities" not in s
    assert "The biggest:" in s and "two biggest" not in s


def test_clean_data_has_no_findings(clean_df) -> None:
    assert analyze(clean_df).findings == []


def test_render_json_is_valid_and_has_computed_fields(synthetic_df) -> None:
    r = analyze(synthetic_df)
    data = json.loads(render_json(r))
    assert data["total_annual_savings"] == r.total_annual_savings
    assert all("annual_savings" in f for f in data["findings"])


def test_render_markdown_has_no_em_dash(synthetic_df) -> None:
    # Em dashes read as AI-generated; keep them out of the report prose. The
    # markdown table separator `---` is legitimate syntax and not in scope.
    r = summarize(analyze(synthetic_df), use_llm=False)
    md = render_markdown(r)
    assert "—" not in md
    assert " -- " not in md  # spaced double-hyphen used as punctuation
    assert "## Opportunities" in md


def test_summarize_fallback_without_key(synthetic_df, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = summarize(analyze(synthetic_df), use_llm=True)
    assert r.summary_source == "fallback"
    assert "recoverable" in r.executive_summary
