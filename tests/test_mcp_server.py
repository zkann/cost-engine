"""MCP server: tool registration and tool behavior (no client/transport needed)."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402

from cost_engine import mcp_server  # noqa: E402

EXPECTED_TOOLS = {
    "analyze_demo",
    "analyze_cur_file",
    "analyze_s3",
    "analyze_cost_explorer",
    "list_rules",
}


def test_all_tools_registered() -> None:
    tools = anyio.run(mcp_server.mcp.list_tools)
    assert {t.name for t in tools} == EXPECTED_TOOLS
    # Descriptions are the model's trigger conditions; none may be empty.
    assert all(t.description for t in tools)


def test_analyze_demo_returns_full_report() -> None:
    report = mcp_server.analyze_demo()
    assert report["total_cost"] > 0
    assert len(report["findings"]) == 7
    assert report["next_step"]
    assert "data_gaps" in report
    # The client model narrates; the template prose is deliberately dropped.
    assert "executive_summary" not in report


def test_analyze_cur_file_roundtrip(tmp_path) -> None:
    from cost_engine.ingest import generate_synthetic_cur

    path = tmp_path / "cur.parquet"
    generate_synthetic_cur().write_parquet(path)
    report = mcp_server.analyze_cur_file(str(path))
    assert report["total_cost"] == pytest.approx(41127.0, abs=1)


def test_list_rules_covers_registry() -> None:
    from cost_engine.analyze.rules import ALL_RULES

    rules = mcp_server.list_rules()
    assert len(rules) == len(ALL_RULES)
    assert all(r["rule_id"] and r["title"] and r["what_it_checks"] for r in rules)
