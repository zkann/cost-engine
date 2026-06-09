"""The engine: run every rule over a dataset and assemble a Report."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from .. import schema as S
from ..models import Finding, Report, Severity
from .aggregate import build_breakdowns, total_cost
from .rules import ALL_RULES, Rule

# Share-of-spend severity floors. Rules triage on absolute dollars (tuned for
# mid-size bills), which under-ranks a small account where $40/mo can be 10% of
# the bill. Findings worth this share of total spend get at least the floor
# severity, gated on decent confidence so the low-confidence rules' deliberate
# severity caps aren't overridden.
_SHARE_FLOORS = ((0.10, Severity.HIGH), (0.05, Severity.MEDIUM))
_ESCALATION_MIN_CONFIDENCE = 0.6
_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
}


# Columns whose absence (all-null) limits a breakdown or rule, with the
# user-facing explanation of what's skipped as a result.
_GAP_COLUMNS: dict[str, str] = {
    S.REGION: "no region data (region breakdown skipped)",
    S.TAG_TEAM: "no team-tag data (team breakdown and untagged-spend rule skipped)",
    S.PRICING_TERM: "no pricing-term data (commitment-coverage rules skipped)",
}


def _data_gaps(df: pl.DataFrame) -> list[str]:
    """Name the data this source doesn't carry, so missing output isn't a mystery."""
    return [
        note
        for col, note in _GAP_COLUMNS.items()
        if col in df.columns and df[col].null_count() == df.height
    ]


def _billing_period(df: pl.DataFrame) -> date:
    vals = df[S.BILL_PERIOD].drop_nulls().unique().to_list()
    return vals[0] if vals else date.today()


def _calibrate_severity(findings: list[Finding], total: float) -> None:
    """Raise severity for findings that are large relative to the whole bill."""
    if total <= 0:
        return
    for f in findings:
        if f.estimated_monthly_savings <= 0 or f.confidence < _ESCALATION_MIN_CONFIDENCE:
            continue
        share = f.estimated_monthly_savings / total
        for threshold, floor in _SHARE_FLOORS:
            if share >= threshold:
                if _SEVERITY_RANK[floor] > _SEVERITY_RANK[f.severity]:
                    f.severity = floor
                break


def _sort_findings(findings: list[Finding]) -> list[Finding]:
    """Rank by dollar impact, then by current cost for the $0-saving ones."""
    return sorted(
        findings,
        key=lambda f: (f.estimated_monthly_savings, f.monthly_cost),
        reverse=True,
    )


def analyze(df: pl.DataFrame, rules: list[Rule] | None = None) -> Report:
    """Run the rules engine and return a Report (without the LLM summary).

    The executive summary is added separately by ``report.summarize`` so the
    analysis stays pure and offline; callers that don't want an LLM in the loop
    get a complete, dollar-quantified report from this function alone.
    """
    rules = rules if rules is not None else ALL_RULES

    findings: list[Finding] = []
    for rule in rules:
        findings.extend(rule.evaluate(df))
    findings = _sort_findings(findings)

    total = total_cost(df)
    _calibrate_severity(findings, total)
    savings = round(sum(f.estimated_monthly_savings for f in findings), 2)

    return Report(
        billing_period=_billing_period(df),
        generated_at=datetime.now(UTC),
        total_cost=total,
        total_estimated_monthly_savings=savings,
        savings_pct_of_spend=(savings / total if total else 0.0),
        breakdowns=build_breakdowns(df),
        findings=findings,
        data_gaps=_data_gaps(df),
    )
