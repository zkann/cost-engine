"""Normalize a raw CUR into the canonical schema.

A CUR can arrive with column names in a few spellings:
- raw export form: ``lineItem/UnblendedCost``, ``resourceTags/user:Team``;
- Athena/Glue form: ``line_item_unblended_cost``, ``resource_tags_user_team``.

Both collapse to the same thing under one rule: split camelCase, turn ``/`` and
``:`` into underscores, lowercase. That output is exactly the canonical schema in
``schema.py`` (which is why the schema is named the way it is), so a single
normalization step accepts either spelling, and a file that is already
normalized passes through unchanged.
"""

from __future__ import annotations

import re

import polars as pl

from .. import schema as S

_CAMEL_1 = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_2 = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")


def to_snake(name: str) -> str:
    """``lineItem/UnblendedCost`` -> ``line_item_unblended_cost``."""
    name = name.replace("/", " ").replace(":", " ").replace("-", " ")
    name = _CAMEL_1.sub(" ", name)
    name = _CAMEL_2.sub(" ", name)
    return "_".join(part.lower() for part in name.split())


def normalize_column_names(df: pl.DataFrame) -> pl.DataFrame:
    return df.rename({c: to_snake(c) for c in df.columns})


def _derive_pricing_term(df: pl.DataFrame) -> pl.DataFrame:
    """Fill a usable ``pricing_term`` for committed lines.

    In a real CUR, Savings Plan and Reserved usage carry their commitment in
    ``line_item_line_item_type`` (``SavingsPlanCoveredUsage`` / ``DiscountedUsage``)
    while ``pricing/term`` is often blank. The coverage rule reads ``pricing_term``,
    so map those line-item types onto it when it isn't already set.
    """
    if S.PRICING_TERM not in df.columns or S.LINE_ITEM_TYPE not in df.columns:
        return df
    term = pl.col(S.PRICING_TERM)
    blank = term.is_null() | (term.cast(pl.Utf8).str.strip_chars() == "")
    return df.with_columns(
        pl.when(blank & (pl.col(S.LINE_ITEM_TYPE) == "SavingsPlanCoveredUsage"))
        .then(pl.lit("SavingsPlan"))
        .when(blank & (pl.col(S.LINE_ITEM_TYPE) == "DiscountedUsage"))
        .then(pl.lit("Reserved"))
        .otherwise(term)
        .alias(S.PRICING_TERM)
    )


def to_canonical(df: pl.DataFrame) -> pl.DataFrame:
    """Rename, validate, and coerce a raw CUR frame to the canonical schema.

    Raises ``ValueError`` listing any required columns the file lacks (a CUR 2.0
    export keeps ``product`` and ``resource_tags`` nested; flatten via Athena or
    a Glue table first).
    """
    df = normalize_column_names(df)
    df = _derive_pricing_term(df)

    missing = [c for c in S.SCHEMA if c not in df.columns]
    if missing:
        raise ValueError(f"CUR is missing required columns after normalization: {missing}")

    return df.select(
        [pl.col(name).cast(dtype, strict=False) for name, dtype in S.SCHEMA.items()]
    )
