"""Analysis layer: cost breakdowns and the savings rules engine."""

from __future__ import annotations

from .aggregate import build_breakdowns, total_cost
from .engine import analyze

__all__ = ["analyze", "build_breakdowns", "total_cost"]
