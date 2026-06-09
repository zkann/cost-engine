"""Load a cost dataset from a parquet or CSV file into the canonical schema.

Used for the checked-in sample CUR and, in practice, for a CUR exported from
Athena or unloaded from S3. Validates that the required columns are present and
coerces them to the schema dtypes so downstream code can rely on the contract.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .. import schema as S


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

    missing = [c for c in S.SCHEMA if c not in df.columns]
    if missing:
        raise ValueError(f"{p.name} is missing required CUR columns: {missing}")

    # Keep only known columns, in schema order, coerced to the right dtypes.
    return df.select(
        [pl.col(name).cast(dtype, strict=False) for name, dtype in S.SCHEMA.items()]
    )
