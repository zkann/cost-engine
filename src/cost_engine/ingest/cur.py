"""Load a CUR straight from S3, no manual download.

Point it at the bucket and prefix where your Cost & Usage Report / Data Export
lands. It finds the most recent delivered object, reads it in memory, and
normalizes it to the canonical schema, full line-item fidelity, so every rule
works exactly as it does on a local file.

boto3 is imported lazily so the base package stays dependency-free. Install the
optional connector deps with ``pip install cost-engine[aws]`` and use a
read-only billing/S3 credential (standard boto3 credential chain).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import polars as pl

from .normalize import to_canonical

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3 import S3Client

# Object suffixes a CUR delivers. Manifests and JSON are ignored.
_CUR_SUFFIXES = (".parquet", ".snappy.parquet", ".csv", ".csv.gz", ".gz")


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


def find_latest_cur_key(client: S3Client, bucket: str, prefix: str) -> str:
    """Return the key of the most recently modified CUR data object under prefix."""
    paginator = client.get_paginator("list_objects_v2")
    latest_key: str | None = None
    latest_mtime = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith(_CUR_SUFFIXES):
                continue
            if latest_mtime is None or obj["LastModified"] > latest_mtime:
                latest_mtime = obj["LastModified"]
                latest_key = key
    if latest_key is None:
        raise FileNotFoundError(
            f"no CUR data objects found under s3://{bucket}/{prefix}"
        )
    return latest_key


def _read_bytes(data: bytes, key: str) -> pl.DataFrame:
    if key.lower().endswith(".parquet"):
        return pl.read_parquet(io.BytesIO(data))
    return pl.read_csv(io.BytesIO(data), try_parse_dates=True)


def load_cur_from_s3(
    bucket: str,
    *,
    prefix: str | None = None,
    key: str | None = None,
    client: S3Client | None = None,
) -> pl.DataFrame:
    """Load a CUR from S3 into the canonical DataFrame.

    Pass either an exact ``key`` or a ``prefix`` (the latest object under it is
    chosen). ``client`` is injectable for testing; otherwise a default S3 client
    is created from the boto3 credential chain.
    """
    if not key and not prefix:
        raise ValueError("provide either key= or prefix=")

    s3 = _require_s3_client(client)
    if not key:
        key = find_latest_cur_key(s3, bucket, prefix)

    obj = s3.get_object(Bucket=bucket, Key=key)
    data = obj["Body"].read()
    return to_canonical(_read_bytes(data, key))
