"""Rule contract and shared helpers.

A rule is a small, pure check over the cost DataFrame that returns zero or more
``Finding``s. Each rule owns one savings hypothesis and the assumption behind
its dollar estimate, stated in the finding's ``detail`` so the number is never
a black box.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import polars as pl

from ... import schema as S
from ...models import Finding, Severity

# How many affected resource ids to attach to a finding for display.
MAX_RESOURCE_IDS = 10


class Rule(ABC):
    """Base class for a savings rule."""

    #: Stable identifier, also used to group findings.
    rule_id: str
    #: Human title for the finding this rule emits.
    title: str

    @abstractmethod
    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        """Return findings for this dataset (empty list if nothing to flag)."""
        raise NotImplementedError


def usage_only(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col(S.LINE_ITEM_TYPE).is_in(S.USAGE_LINE_ITEM_TYPES))


def cost_of(df: pl.DataFrame) -> float:
    """Sum unblended cost of a (pre-filtered) frame."""
    return round(df[S.UNBLENDED_COST].sum() or 0.0, 2)


def resource_sample(df: pl.DataFrame) -> tuple[list[str], int]:
    """Distinct resource ids: a display sample plus the full count."""
    ids = df[S.RESOURCE_ID].unique().to_list()
    ids = [i for i in ids if i is not None]
    return ids[:MAX_RESOURCE_IDS], len(ids)


def severity_for(monthly_savings: float) -> Severity:
    """Triage by dollar impact. Thresholds tuned for SMB-scale monthly spend."""
    if monthly_savings >= 1000:
        return Severity.HIGH
    if monthly_savings >= 250:
        return Severity.MEDIUM
    return Severity.LOW
