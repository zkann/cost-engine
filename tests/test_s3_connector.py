"""S3 CUR connector, exercised against a stubbed boto3 client (no live AWS)."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import polars as pl
import pytest

boto3 = pytest.importorskip("boto3")
from botocore.response import StreamingBody  # noqa: E402
from botocore.stub import Stubber  # noqa: E402

from cost_engine.analyze import analyze  # noqa: E402
from cost_engine.ingest import generate_synthetic_cur  # noqa: E402
from cost_engine.ingest.cur import find_latest_cur_key, load_cur_from_s3  # noqa: E402

BUCKET = "cur-bucket"
PREFIX = "exports/cur/"


def _parquet_bytes() -> bytes:
    buf = io.BytesIO()
    generate_synthetic_cur().write_parquet(buf)
    return buf.getvalue()


def _stubbed_s3():
    client = boto3.client("s3", region_name="us-east-2",
                          aws_access_key_id="x", aws_secret_access_key="x")
    return client, Stubber(client)


def _obj(key: str, mtime: datetime, size: int = 100) -> dict:
    return {"Key": key, "LastModified": mtime, "Size": size, "ETag": '"x"',
            "StorageClass": "STANDARD"}


def test_find_latest_cur_key_picks_newest_parquet() -> None:
    client, stub = _stubbed_s3()
    older = datetime(2026, 4, 1, tzinfo=UTC)
    newer = datetime(2026, 5, 1, tzinfo=UTC)
    stub.add_response(
        "list_objects_v2",
        {
            "Contents": [
                _obj(PREFIX + "2026-04/data-00001.parquet", older),
                _obj(PREFIX + "2026-05/data-00001.parquet", newer),
                _obj(PREFIX + "2026-05/Manifest.json", newer),  # ignored
            ],
            "IsTruncated": False,
        },
        {"Bucket": BUCKET, "Prefix": PREFIX},
    )
    with stub:
        key = find_latest_cur_key(client, BUCKET, PREFIX)
    assert key == PREFIX + "2026-05/data-00001.parquet"


def test_find_latest_raises_when_no_cur_objects() -> None:
    client, stub = _stubbed_s3()
    stub.add_response("list_objects_v2",
                      {"Contents": [_obj(PREFIX + "Manifest.json",
                                         datetime(2026, 5, 1, tzinfo=UTC))],
                       "IsTruncated": False},
                      {"Bucket": BUCKET, "Prefix": PREFIX})
    with stub, pytest.raises(FileNotFoundError):
        find_latest_cur_key(client, BUCKET, PREFIX)


def test_load_cur_from_s3_by_key_runs_full_analysis() -> None:
    data = _parquet_bytes()
    client, stub = _stubbed_s3()
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(data), len(data)), "ContentLength": len(data)},
        {"Bucket": BUCKET, "Key": "k.parquet"},
    )
    with stub:
        df = load_cur_from_s3(BUCKET, key="k.parquet", client=client)
    assert isinstance(df, pl.DataFrame) and df.height > 0
    # Full fidelity: all six rules fire just like a local file.
    assert len(analyze(df).findings) == 6


def test_load_cur_from_s3_finds_latest_then_downloads() -> None:
    data = _parquet_bytes()
    mtime = datetime(2026, 5, 1, tzinfo=UTC)
    client, stub = _stubbed_s3()
    stub.add_response("list_objects_v2",
                      {"Contents": [_obj(PREFIX + "data-00001.parquet", mtime)],
                       "IsTruncated": False},
                      {"Bucket": BUCKET, "Prefix": PREFIX})
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(data), len(data)), "ContentLength": len(data)},
        {"Bucket": BUCKET, "Key": PREFIX + "data-00001.parquet"},
    )
    with stub:
        df = load_cur_from_s3(BUCKET, prefix=PREFIX, client=client)
    assert df.height > 0


def test_requires_key_or_prefix() -> None:
    with pytest.raises(ValueError):
        load_cur_from_s3(BUCKET, client=object())
