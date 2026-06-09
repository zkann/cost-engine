"""Executive summary for a Report.

A Claude-generated summary when an API key is present, a deterministic
template otherwise. The fallback is good enough that the tool is useful with
zero secrets: the LLM adds polish, it isn't load-bearing. The model defaults to
Haiku, the cheapest tier, because summarizing a handful of pre-computed numbers
doesn't need a frontier model, and a cost tool should practice what it preaches.
"""

from __future__ import annotations

import os

from ..models import Report

# Cheap on purpose: see module docstring.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400


def summarize(report: Report, use_llm: bool = True) -> Report:
    """Populate ``report.executive_summary`` and ``report.summary_source``.

    Mutates and returns the report. Never raises on LLM failure: it falls back
    to the deterministic summary so a missing key or a network blip can't break
    a run.
    """
    if use_llm and os.environ.get("ANTHROPIC_API_KEY"):
        text = _llm_summary(report)
        if text:
            report.executive_summary = text
            report.summary_source = "llm"
            return report

    report.executive_summary = _fallback_summary(report)
    report.summary_source = "fallback"
    return report


def _facts(report: Report) -> str:
    """A compact, model-friendly digest of the report's numbers."""
    lines = [
        f"Billing period: {report.billing_period:%B %Y}",
        f"Total spend: ${report.total_cost:,.0f}/month",
        f"Total estimated recoverable: ${report.total_estimated_monthly_savings:,.0f}/month "
        f"({report.savings_pct_of_spend:.0%} of spend, "
        f"${report.total_annual_savings:,.0f}/year)",
        "Opportunities (highest dollar impact first):",
    ]
    for f in report.findings:
        if f.estimated_monthly_savings > 0:
            lines.append(
                f"- {f.title}: save ${f.estimated_monthly_savings:,.0f}/mo "
                f"(confidence {f.confidence:.0%})"
            )
        else:
            lines.append(f"- {f.title}: ${f.monthly_cost:,.0f}/mo affected (governance)")
    return "\n".join(lines)


def _llm_summary(report: Report) -> str | None:
    try:
        import anthropic
    except ImportError:
        return None

    model = os.environ.get("COST_ENGINE_LLM_MODEL", DEFAULT_MODEL)
    prompt = (
        "You are a FinOps analyst briefing a startup founder/CTO. Using only the "
        "facts below, write a 3-4 sentence executive summary of their AWS cost "
        "report. Lead with total spend and total recoverable dollars. Name the two "
        "biggest opportunities. End with one concrete next step. Be direct and "
        "specific, no filler, no markdown, no bullet points.\n\n"
        f"{_facts(report)}"
    )
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip() or None
    except Exception:
        # Any API/auth/network error: fall back silently, never break the run.
        return None


def _fallback_summary(report: Report) -> str:
    paying = [f for f in report.findings if f.estimated_monthly_savings > 0]
    if not paying:
        return (
            f"AWS spend for {report.billing_period:%B %Y} was "
            f"${report.total_cost:,.0f}/month with no material savings opportunities "
            f"detected by the current rule set."
        )

    top = paying[:2]
    top_clause = "; ".join(
        f"{f.title} (${f.estimated_monthly_savings:,.0f}/mo)" for f in top
    )
    return (
        f"AWS spend for {report.billing_period:%B %Y} was "
        f"${report.total_cost:,.0f}/month, of which about "
        f"${report.total_estimated_monthly_savings:,.0f}/month "
        f"({report.savings_pct_of_spend:.0%}, ${report.total_annual_savings:,.0f}/year) "
        f"looks recoverable across {len(paying)} opportunities. The two biggest: "
        f"{top_clause}. Start with the highest-confidence, lowest-effort wins "
        f"(gp2-to-gp3 and idle resources), and validate the commitment-based "
        f"savings against a steady usage baseline before buying."
    )
