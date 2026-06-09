"""The engine: run every rule over a dataset and assemble a Report."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from .. import schema as S
from ..models import Finding, Report
from .aggregate import build_breakdowns, total_cost
from .rules import ALL_RULES, Rule


def _billing_period(df: pl.DataFrame) -> date:
    vals = df[S.BILL_PERIOD].drop_nulls().unique().to_list()
    return vals[0] if vals else date.today()


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
    savings = round(sum(f.estimated_monthly_savings for f in findings), 2)

    return Report(
        billing_period=_billing_period(df),
        generated_at=datetime.now(UTC),
        total_cost=total,
        total_estimated_monthly_savings=savings,
        savings_pct_of_spend=(savings / total if total else 0.0),
        breakdowns=build_breakdowns(df),
        findings=findings,
    )
