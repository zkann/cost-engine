"""cost-engine: a FinOps cost-analysis engine.

Ingest AWS Cost & Usage Report data (synthetic or real), find dollar-quantified
savings opportunities, and render an executive report.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cost-engine")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0"
