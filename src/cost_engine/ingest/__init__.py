"""Ingestion: turn a cost data source into the canonical polars DataFrame.

- ``synthetic``: a seeded generator producing a realistic month of CUR data
  with deliberately planted waste. Runs with zero credentials.
- ``cur`` / ``cost_explorer`` (Phase 2): real AWS connectors behind the same
  DataFrame contract.
"""

from __future__ import annotations

from .synthetic import generate_synthetic_cur

__all__ = ["generate_synthetic_cur"]
