"""S3 CUR connector, exercised against a stubbed boto3 client (no live AWS)."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import polars as pl
import pytest

boto3 = pytest.importorskip("boto3")
from datetime import date  # noqa: E402

from botocore.response import StreamingBody  # noqa: E402
from botocore.stub import Stubber  # noqa: E402

from cost_engine.analyze import analyze  # noqa: E402
from cost_engine.ingest import cur as curmod  # noqa: E402
from cost_engine.ingest import generate_synthetic_cur  # noqa: E402
from cost_engine.ingest.cur import (  # noqa: E402
    _period_of,
    _select_period_keys,
    find_latest_cur_key,
    load_cur_from_s3,
)

BUCKET = "cur-bucket"
PREFIX = "exports/cur/"


def _mt(day: int):
    return datetime(2026, 6, day, tzinfo=UTC)


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
    # Full fidelity: every rule fires just like a local file.
    assert len(analyze(df).findings) == 7


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


# --- billing-period selection ---------------------------------------------

def test_period_of_parses_both_layouts() -> None:
    assert _period_of("p/cur/data/BILLING_PERIOD=2026-05/x-00001.parquet") == date(2026, 5, 1)
    assert _period_of("p/report/20260501-20260601/abc/r-00001.parquet") == date(2026, 5, 1)
    assert _period_of("p/cur/no-period-here.parquet") is None


def test_select_prefers_most_recent_complete_month(monkeypatch) -> None:
    # "Now" is June, so June is the partial current month and May is complete.
    monkeypatch.setattr(curmod, "_current_month_start", lambda: date(2026, 6, 1))
    objs = [
        (PREFIX + "BILLING_PERIOD=2026-05/d-00001.parquet", _mt(2)),
        (PREFIX + "BILLING_PERIOD=2026-06/d-00001.parquet", _mt(9)),  # newer but partial
    ]
    keys, period = _select_period_keys(objs, month=None)
    assert period == date(2026, 5, 1)
    assert keys == [PREFIX + "BILLING_PERIOD=2026-05/d-00001.parquet"]


def test_select_loads_all_parts_in_latest_folder(monkeypatch) -> None:
    monkeypatch.setattr(curmod, "_current_month_start", lambda: date(2026, 6, 1))
    base = PREFIX + "BILLING_PERIOD=2026-05/assemblyA/"
    objs = [
        (base + "d-00001.parquet", _mt(2)),
        (base + "d-00002.parquet", _mt(2)),
        (PREFIX + "BILLING_PERIOD=2026-05/assemblyOLD/d-00001.parquet", _mt(1)),  # stale
    ]
    keys, _ = _select_period_keys(objs, month=None)
    assert sorted(keys) == sorted([base + "d-00001.parquet", base + "d-00002.parquet"])


def test_select_explicit_month() -> None:
    objs = [
        (PREFIX + "BILLING_PERIOD=2026-04/d.parquet", _mt(1)),
        (PREFIX + "BILLING_PERIOD=2026-05/d.parquet", _mt(2)),
    ]
    keys, period = _select_period_keys(objs, month=date(2026, 4, 1))
    assert period == date(2026, 4, 1)
    assert keys == [PREFIX + "BILLING_PERIOD=2026-04/d.parquet"]


def test_load_s3_picks_complete_month_not_partial(monkeypatch) -> None:
    monkeypatch.setattr(curmod, "_current_month_start", lambda: date(2026, 6, 1))
    data = _parquet_bytes()
    may_key = PREFIX + "BILLING_PERIOD=2026-05/d-00001.parquet"
    jun_key = PREFIX + "BILLING_PERIOD=2026-06/d-00001.parquet"
    client, stub = _stubbed_s3()
    stub.add_response("list_objects_v2",
                      {"Contents": [_obj(may_key, _mt(2)), _obj(jun_key, _mt(9))],
                       "IsTruncated": False},
                      {"Bucket": BUCKET, "Prefix": PREFIX})
    # Only May's get_object is stubbed; if it asked for June the stub would error.
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(data), len(data)), "ContentLength": len(data)},
        {"Bucket": BUCKET, "Key": may_key},
    )
    with stub:
        df = load_cur_from_s3(BUCKET, prefix=PREFIX, client=client)
    assert df.height > 0
