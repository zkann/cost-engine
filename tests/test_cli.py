"""CLI smoke tests via Typer's runner."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cost_engine.cli import _load_or_exit, app

runner = CliRunner()


def test_load_dotenv_sets_without_overriding(tmp_path, monkeypatch) -> None:
    import os

    from cost_engine.cli import _load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "export FOO_FROM_DOTENV='quoted value'\n"
        "BAR_FROM_DOTENV=plain\n"
        "ALREADY_SET=from-dotenv\n"
        "not a kv line\n"
    )
    monkeypatch.setenv("ALREADY_SET", "from-real-env")
    monkeypatch.delenv("FOO_FROM_DOTENV", raising=False)
    monkeypatch.delenv("BAR_FROM_DOTENV", raising=False)

    _load_dotenv(env_file)
    assert os.environ["FOO_FROM_DOTENV"] == "quoted value"
    assert os.environ["BAR_FROM_DOTENV"] == "plain"
    # A real environment variable always beats the .env file.
    assert os.environ["ALREADY_SET"] == "from-real-env"

    monkeypatch.delenv("FOO_FROM_DOTENV", raising=False)
    monkeypatch.delenv("BAR_FROM_DOTENV", raising=False)


def test_load_dotenv_missing_file_is_noop(tmp_path) -> None:
    from cost_engine.cli import _load_dotenv

    _load_dotenv(tmp_path / "no-such.env")  # must not raise


def test_load_or_exit_turns_aws_error_into_clean_exit() -> None:
    import typer

    class NoSuchBucket(Exception):
        pass

    def boom():
        raise NoSuchBucket("The specified bucket does not exist")

    with pytest.raises(typer.Exit) as exc_info:
        _load_or_exit(boom, what="S3 read")
    assert exc_info.value.exit_code == 1


def test_demo_rich_runs() -> None:
    result = runner.invoke(app, ["demo", "--no-llm"])
    assert result.exit_code == 0
    assert "Recoverable" in result.stdout
    assert "Where the money goes" in result.stdout


def test_demo_json_is_valid() -> None:
    result = runner.invoke(app, ["demo", "--no-llm", "-f", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total_cost"] > 0


def test_gen_sample_and_report_roundtrip(tmp_path) -> None:
    out_dir = tmp_path / "cur"
    gen = runner.invoke(app, ["gen-sample", "--out-dir", str(out_dir)])
    assert gen.exit_code == 0
    parquet = out_dir / "sample-cur.parquet"
    assert parquet.exists()

    rep = runner.invoke(app, ["report", "-i", str(parquet), "--no-llm", "-f", "json"])
    assert rep.exit_code == 0
    assert json.loads(rep.stdout)["total_cost"] > 0
