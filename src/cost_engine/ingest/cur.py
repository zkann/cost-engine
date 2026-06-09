"""Load a CUR straight from S3, no manual download.

Point it at the bucket and prefix where your Cost & Usage Report / Data Export
lands. By default it picks the **most recent complete billing month**, because
AWS keeps rewriting the in-progress month, so the newest object is a partial
month whose ``$/mo`` figure is misleading. The billing period is read from the
S3 key path (both the legacy ``.../20260501-20260601/...`` layout and the CUR 2.0
``.../BILLING_PERIOD=2026-05/...`` layout), and all data parts of the chosen
period's latest delivery are loaded and concatenated.

boto3 is imported lazily so the base package stays dependency-free. Install with
``pip install cost-engine[aws]`` and use a read-only billing/S3 credential.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import polars as pl

from .normalize import to_canonical

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3 import S3Client

# Object suffixes a CUR delivers. Manifests and JSON are ignored.
_CUR_SUFFIXES = (".parquet", ".snappy.parquet", ".csv", ".csv.gz", ".gz")

# Billing period encoded in the key path: CUR 2.0 then legacy.
_PERIOD_V2 = re.compile(r"BILLING_PERIOD=(\d{4})-(\d{2})")
_PERIOD_LEGACY = re.compile(r"/(\d{4})(\d{2})\d{2}-\d{8}/")


def _require_s3_client(client):
    if client is not None:
        return client
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "the S3 CUR connector needs boto3. Install with: pip install 'cost-engine[aws]'"
        ) from exc
    return boto3.client("s3")


def _period_of(key: str) -> date | None:
    """Billing month (first of month) parsed from a CUR key path, or None."""
    m = _PERIOD_V2.search(key) or _PERIOD_LEGACY.search(key)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _current_month_start() -> date:
    return datetime.now(UTC).date().replace(day=1)


def _list_cur_objects(client: S3Client, bucket: str, prefix: str) -> list[tuple[str, object]]:
    """(key, last_modified) for every CUR data object under the prefix."""
    paginator = client.get_paginator("list_objects_v2")
    objs: list[tuple[str, object]] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(_CUR_SUFFIXES):
                objs.append((key, obj["LastModified"]))
    return objs


def find_latest_cur_key(client: S3Client, bucket: str, prefix: str) -> str:
    """Key of the most recently modified CUR data object under prefix (partial month)."""
    objs = _list_cur_objects(client, bucket, prefix)
    if not objs:
        raise FileNotFoundError(f"no CUR data objects found under s3://{bucket}/{prefix}")
    return max(objs, key=lambda o: o[1])[0]


def _select_period_keys(
    objs: list[tuple[str, object]], month: date | None
) -> tuple[list[str], date | None]:
    """Choose which objects to load and report the period.

    With ``month`` set, use that period. Otherwise prefer the most recent
    *complete* month (period before the current one); if none of the keys encode
    a period, fall back to the single most recently modified object so the
    connector still works on an unrecognized layout.

    Within the chosen period, load every part that shares the latest delivery's
    folder (handles multi-part reports without mixing restatements).
    """
    if not objs:
        raise FileNotFoundError("no CUR data objects to choose from")

    periodized = [(k, mt, _period_of(k)) for k, mt in objs]
    if month is None:
        complete = sorted({p for _, _, p in periodized if p and p < _current_month_start()})
        if not complete:
            # Layout without a recognizable period: latest object, period unknown.
            latest = max(objs, key=lambda o: o[1])[0]
            return [latest], None
        month = complete[-1]

    in_period = [(k, mt) for k, mt, p in periodized if p == month]
    if not in_period:
        raise FileNotFoundError(f"no CUR objects for billing month {month:%Y-%m}")

    # The latest delivery's folder, to load all its parts and nothing older.
    latest_key = max(in_period, key=lambda o: o[1])[0]
    folder = latest_key.rsplit("/", 1)[0] + "/"
    keys = [k for k, _ in in_period if k.startswith(folder)]
    return keys, month


def _read_bytes(data: bytes, key: str) -> pl.DataFrame:
    if key.lower().endswith(".parquet"):
        return pl.read_parquet(io.BytesIO(data))
    return pl.read_csv(io.BytesIO(data), try_parse_dates=True)


def load_cur_from_s3(
    bucket: str,
    *,
    prefix: str | None = None,
    key: str | None = None,
    month: date | None = None,
    latest: bool = False,
    client: S3Client | None = None,
) -> pl.DataFrame:
    """Load a CUR from S3 into the canonical DataFrame.

    Pass an exact ``key``, or a ``prefix`` to auto-select. Under a prefix the
    default is the most recent complete billing month; ``month`` picks a specific
    one (first-of-month), and ``latest=True`` forces the newest (partial) object.
    ``client`` is injectable for tests.
    """
    if not key and not prefix:
        raise ValueError("provide either key= or prefix=")

    s3 = _require_s3_client(client)

    if key:
        keys = [key]
    elif latest:
        keys = [find_latest_cur_key(s3, bucket, prefix)]
    else:
        objs = _list_cur_objects(s3, bucket, prefix)
        keys, _ = _select_period_keys(objs, month)

    frames = []
    for k in keys:
        obj = s3.get_object(Bucket=bucket, Key=k)
        frames.append(_read_bytes(obj["Body"].read(), k))
    raw = frames[0] if len(frames) == 1 else pl.concat(frames, how="diagonal_relaxed")
    return to_canonical(raw)
