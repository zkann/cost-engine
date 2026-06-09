"""Render a Report as JSON or markdown."""

from __future__ import annotations

from ..models import Breakdown, Report, Severity

_SEVERITY_BADGE = {
    Severity.HIGH: "HIGH",
    Severity.MEDIUM: "MED",
    Severity.LOW: "LOW",
    Severity.INFO: "INFO",
}


def render_json(report: Report, indent: int = 2) -> str:
    return report.model_dump_json(indent=indent)


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _breakdown_table(b: Breakdown) -> list[str]:
    lines = [
        f"### Cost by {b.dimension}",
        "",
        f"| {b.dimension.title()} | Cost | Share |",
        "|---|---:|---:|",
    ]
    for s in b.slices:
        lines.append(f"| {s.key} | {_money(s.cost)} | {s.share:.0%} |")
    lines.append("")
    return lines


def render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"# AWS Cost Report, {report.billing_period:%B %Y}")
    lines.append("")
    lines.append(f"_Generated {report.generated_at:%Y-%m-%d %H:%M UTC}_")
    lines.append("")

    # Headline numbers.
    lines.append("## Summary")
    lines.append("")
    if report.source:
        lines.append(f"- **Source:** {report.source}")
    if report.account_note:
        lines.append(f"- **Account:** {report.account_note}")
    lines.append(f"- **Total spend:** {_money(report.total_cost)}/month")
    lines.append(
        f"- **Estimated recoverable:** {_money(report.total_estimated_monthly_savings)}/month "
        f"({report.savings_pct_of_spend:.0%} of spend, "
        f"{_money(report.total_annual_savings)}/year)"
    )
    lines.append(f"- **Opportunities found:** {len(report.findings)}")
    lines.append("")

    if report.executive_summary:
        # Disclose AI-written prose; the deterministic summary needs no qualifier.
        suffix = " _(written by Claude)_" if report.summary_source == "llm" else ""
        lines.append(report.executive_summary + suffix)
        lines.append("")
        if report.next_step:
            lines.append(f"**Next step:** {report.next_step}")
            lines.append("")

    # Opportunities.
    lines.append("## Opportunities")
    lines.append("")
    lines.append("| Priority | Opportunity | Monthly saving | Annual | Confidence |")
    lines.append("|---|---|---:|---:|---:|")
    for f in report.findings:
        is_governance = f.estimated_monthly_savings == 0
        saving = "governance" if is_governance else _money(f.estimated_monthly_savings)
        annual = "" if is_governance else _money(f.annual_savings)
        lines.append(
            f"| {_SEVERITY_BADGE[f.severity]} | {f.title} | {saving} | {annual} | "
            f"{f.confidence:.0%} |"
        )
    lines.append("")

    # Detail per finding.
    for f in report.findings:
        lines.append(f"### {f.title}")
        lines.append("")
        lines.append(
            f"**{_SEVERITY_BADGE[f.severity]}** · {f.category.value} · "
            f"{f.affected_resource_count} resource(s) · confidence {f.confidence:.0%}"
        )
        lines.append("")
        lines.append(f.detail)
        lines.append("")
        lines.append(f"**Do this:** {f.recommendation}")
        lines.append("")

    # Breakdowns.
    lines.append("## Where the money goes")
    lines.append("")
    for b in report.breakdowns:
        lines.extend(_breakdown_table(b))

    return "\n".join(lines).rstrip() + "\n"
