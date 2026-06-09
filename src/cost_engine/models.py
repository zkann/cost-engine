"""Domain models that cross the public boundary (CLI output, API, report).

The in-memory cost dataset itself is a ``polars.DataFrame`` keyed on the
columns in ``schema.py`` (fast, columnar). These pydantic models describe the
*results* of analysis: opportunities found and the report wrapping them.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class Severity(StrEnum):
    """Rough priority of a finding, driven by dollar impact and effort."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"  # governance signal, not a direct dollar saving


class Category(StrEnum):
    WASTE = "waste"  # paying for something unused (unattached EBS, idle EIP)
    RIGHTSIZING = "rightsizing"  # cheaper equivalent (gp2 -> gp3)
    COMMITMENT = "commitment"  # Savings Plans / Reserved Instance coverage
    DATA_TRANSFER = "data_transfer"  # NAT, cross-AZ, egress
    GOVERNANCE = "governance"  # tagging / cost allocation hygiene


class Finding(BaseModel):
    """A single, actionable cost-savings opportunity."""

    rule_id: str = Field(description="Stable id of the rule that produced this")
    title: str
    category: Category
    severity: Severity
    monthly_cost: float = Field(
        ge=0, description="Current monthly spend attributable to this finding"
    )
    estimated_monthly_savings: float = Field(
        ge=0, description="Estimated monthly $ recoverable if actioned"
    )
    currency: str = "USD"
    resource_ids: list[str] = Field(
        default_factory=list, description="Affected resources (truncated for display)"
    )
    affected_resource_count: int = 0
    detail: str = Field(description="What was observed, with the numbers behind it")
    recommendation: str = Field(description="Concrete next action")
    confidence: float = Field(
        default=0.8, ge=0, le=1, description="How sure the rule is, given CUR-only signal"
    )

    @computed_field
    @property
    def annual_savings(self) -> float:
        return round(self.estimated_monthly_savings * 12, 2)


class CostSlice(BaseModel):
    """One row of a cost breakdown (by service, account, tag, etc.)."""

    key: str
    cost: float
    share: float = Field(ge=0, le=1, description="Fraction of the grouped total")


class Breakdown(BaseModel):
    dimension: str  # "service", "account", "team", "region"
    total: float
    slices: list[CostSlice]


class Report(BaseModel):
    """The full analysis result for one billing period."""

    billing_period: date
    generated_at: datetime
    currency: str = "USD"
    total_cost: float
    total_estimated_monthly_savings: float
    savings_pct_of_spend: float = Field(ge=0, le=1)
    breakdowns: list[Breakdown] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    executive_summary: str = ""
    summary_source: str = "none"  # "llm" | "fallback" | "none"
    next_step: str = Field(
        default="",
        description="One concrete action, derived from the findings that fired",
    )
    # Provenance, set by the CLI. ``source`` is where the data came from;
    # ``account_note`` records the account(s), from the data itself when present,
    # or the calling credentials' identity for sources that carry no account id.
    source: str = ""
    account_note: str = ""

    @computed_field
    @property
    def total_annual_savings(self) -> float:
        return round(self.total_estimated_monthly_savings * 12, 2)
