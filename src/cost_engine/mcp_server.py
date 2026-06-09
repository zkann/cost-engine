"""MCP server: let an AI assistant analyze AWS spend through cost-engine.

Exposes the engine's ingestion paths as MCP tools over stdio, so an MCP client
(Claude Desktop, Claude Code, anything speaking the protocol) can answer
questions like "why is my AWS bill this size?" against real data.

Design notes:
- Same trust model as the CLI: runs locally, speaks stdio (no listener), and
  uses the caller's own AWS credential chain. Nothing is stored or transmitted
  beyond the AWS APIs the user already authorized.
- The LLM executive summary is deliberately OFF here (``use_llm=False``): the
  MCP client *is* a model and writes its own narration. Tools return the
  deterministic report, including the findings, breakdowns, and data gaps.

Run it:
    uv run cost-engine-mcp          # needs: pip install 'cost-engine[mcp]'
"""

from __future__ import annotations

from datetime import date
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "the MCP server needs the 'mcp' package. Install with: "
        "pip install 'cost-engine[mcp]'"
    ) from exc

from .analyze import analyze
from .analyze.rules import ALL_RULES
from .report import summarize

mcp = FastMCP(
    "cost-engine",
    instructions=(
        "FinOps analysis of AWS spend. Reports are dollar-quantified: each "
        "finding carries the current monthly cost, the estimated saving, the "
        "assumption behind the number, and a concrete recommendation. "
        "data_gaps lists what the source didn't carry (and which checks were "
        "skipped as a result) — mention them when relevant. Use analyze_demo "
        "for a zero-credential walkthrough on synthetic data."
    ),
)


def _report_dict(df: Any) -> dict:
    report = summarize(analyze(df), use_llm=False)
    payload = report.model_dump(mode="json")
    # The client model narrates; drop the deterministic template prose so it
    # works from the numbers instead of paraphrasing our paraphrase.
    payload.pop("executive_summary", None)
    payload.pop("summary_source", None)
    return payload


@mcp.tool()
def analyze_demo() -> dict:
    """Analyze the built-in synthetic AWS account (no credentials needed).

    Call this to demonstrate the analysis or when the user has no CUR/AWS
    access handy. The data is generated, not real spend.
    """
    from .ingest import generate_synthetic_cur

    return _report_dict(generate_synthetic_cur())


@mcp.tool()
def analyze_cur_file(path: str) -> dict:
    """Analyze a local AWS Cost & Usage Report file (.parquet or .csv).

    Call this when the user has a CUR file on disk. ``path`` must be an
    absolute path. The file is parsed locally; nothing is uploaded.
    """
    from .ingest import load_cur

    return _report_dict(load_cur(path))


@mcp.tool()
def analyze_s3(
    bucket: str,
    prefix: str | None = None,
    key: str | None = None,
    month: str | None = None,
) -> dict:
    """Analyze a CUR straight from the user's S3 bucket (full fidelity).

    Call this when the user has a CUR/Data Export delivered to S3. Provide
    ``prefix`` to auto-select the most recent COMPLETE billing month (the
    newest object is the in-progress month), or an exact ``key``. ``month``
    (YYYY-MM) picks a specific billing month. Uses the local AWS credential
    chain; requires s3:ListBucket + s3:GetObject.
    """
    from .ingest import load_cur_from_s3

    month_date = date.fromisoformat(f"{month}-01") if month else None
    return _report_dict(
        load_cur_from_s3(bucket, prefix=prefix, key=key, month=month_date)
    )


@mcp.tool()
def analyze_cost_explorer(start: str | None = None, end: str | None = None) -> dict:
    """Analyze spend via the AWS Cost Explorer API (no CUR setup needed).

    Call this for a quick top-line view when no CUR exists. Defaults to the
    most recent complete calendar month; ``start``/``end`` are YYYY-MM-DD with
    end exclusive. Carries no tags, resource ids, or purchase term, so the
    untagged-spend and commitment-coverage rules are skipped (reported in
    data_gaps). Uses the local AWS credential chain (ce:GetCostAndUsage);
    note AWS bills ~$0.01 per Cost Explorer API call.
    """
    from .analyze.rules import ALL_RULES as _all
    from .ingest import load_from_cost_explorer
    from .ingest.cost_explorer import CE_UNSUPPORTED_RULE_IDS

    df = load_from_cost_explorer(
        date.fromisoformat(start) if start else None,
        date.fromisoformat(end) if end else None,
    )
    supported = [r for r in _all if r.rule_id not in CE_UNSUPPORTED_RULE_IDS]
    report = summarize(analyze(df, rules=supported), use_llm=False)
    payload = report.model_dump(mode="json")
    payload.pop("executive_summary", None)
    payload.pop("summary_source", None)
    return payload


@mcp.tool()
def list_rules() -> list[dict]:
    """List the savings checks the engine runs, with what each one looks for.

    Call this when the user asks what the analyzer can detect.
    """
    import sys

    out = []
    for r in ALL_RULES:
        # Each rule documents itself in its module docstring; first paragraph.
        doc = sys.modules[type(r).__module__].__doc__ or ""
        out.append(
            {
                "rule_id": r.rule_id,
                "title": r.title,
                "what_it_checks": doc.strip().split("\n\n")[0].replace("\n", " "),
            }
        )
    return out


def main() -> None:
    """Entry point for the ``cost-engine-mcp`` script (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
