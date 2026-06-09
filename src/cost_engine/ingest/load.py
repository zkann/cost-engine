"""Load a cost dataset from a parquet or CSV file into the canonical schema.

Used for the checked-in sample CUR and for a CUR exported from Athena or
unloaded from S3. Column normalization (see ``normalize.to_canonical``) means the
file can use either the raw export spelling (``lineItem/UnblendedCost``) or the
Athena-normalized spelling (``line_item_unblended_cost``).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .normalize import to_canonical


def load_cur(path: str | Path) -> pl.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    if p.suffix == ".parquet":
        df = pl.read_parquet(p)
    elif p.suffix in (".csv", ".gz"):
        df = pl.read_csv(p, try_parse_dates=True)
    else:
        raise ValueError(f"unsupported file type {p.suffix!r}; use .parquet or .csv")

    return to_canonical(df)
