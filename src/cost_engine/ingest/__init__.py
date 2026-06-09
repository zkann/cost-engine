"""Ingestion: turn a cost data source into the canonical polars DataFrame.

- ``synthetic``: a seeded generator producing a realistic month of CUR data
  with deliberately planted waste. Runs with zero credentials.
- ``load``: a CUR file (parquet/CSV) from local disk.
- ``cur``: a CUR pulled straight from S3 (real AWS, needs the ``[aws]`` extra).
- ``cost_explorer``: a top-line dataset from the Cost Explorer API (``[aws]``).

All four produce the same DataFrame, so the analysis layer never knows or cares
which source it came from.
"""

from __future__ import annotations

from .cost_explorer import load_from_cost_explorer
from .cur import load_cur_from_s3
from .load import load_cur
from .synthetic import generate_synthetic_cur

__all__ = [
    "generate_synthetic_cur",
    "load_cur",
    "load_cur_from_s3",
    "load_from_cost_explorer",
]
