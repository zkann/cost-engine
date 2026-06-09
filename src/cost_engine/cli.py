"""cost-engine command line.

    cost-engine demo                       analyze the built-in synthetic account
    cost-engine report -i cur.parquet      analyze a local CUR file
    cost-engine s3 --bucket B --prefix P   pull the latest CUR from S3 and analyze
    cost-engine cost-explorer              pull a top-line dataset from Cost Explorer
    cost-engine gen-sample                 write the sample CUR to data/sample-cur/

The s3 and cost-explorer commands need the optional AWS deps:
    pip install 'cost-engine[aws]'
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .analyze import analyze, distinct_accounts
from .analyze.rules import ALL_RULES
from .ingest import generate_synthetic_cur, load_cur, load_cur_from_s3, load_from_cost_explorer
from .ingest.cost_explorer import CE_UNSUPPORTED_RULE_IDS, caller_identity_label
from .models import Report, Severity
from .report import render_json, render_markdown, summarize


def _account_note_from_data(df) -> str:
    """Provenance from the data itself: which account(s) the rows belong to."""
    accounts = distinct_accounts(df)
    if not accounts:
        return ""
    shown = ", ".join(accounts[:5])
    if len(accounts) > 5:
        shown += f", +{len(accounts) - 5} more"
    return f"accounts: {shown}"


# Hints for the common AWS failure modes, keyed by exception class name so we
# don't import botocore at module load (it's an optional dep).
_AWS_HINTS = {
    "NoCredentialsError": "No AWS credentials found. Set a profile (AWS_PROFILE=...) "
    "or env keys, then retry.",
    "NoSuchBucket": "That bucket does not exist in this account/region. List buckets "
    "with `aws s3 ls`, or find the CUR's bucket with "
    "`aws cur describe-report-definitions`.",
    "AccessDenied": "The credentials lack permission. The s3 command needs "
    "s3:ListBucket + s3:GetObject; cost-explorer needs ce:GetCostAndUsage.",
    "AccessDeniedException": "The credentials lack permission. cost-explorer needs "
    "ce:GetCostAndUsage (and Cost Explorer enabled in the account).",
    "FileNotFoundError": "No CUR data objects under that prefix. Check --prefix, or "
    "pass an exact --key.",
}


def _load_or_exit(loader, *, what: str):
    """Run a data loader, turning expected failures into one clean line.

    AWS/network errors are normal operator mistakes (wrong bucket, missing
    creds, no permission), not bugs, so they get a friendly message and a hint
    instead of a traceback.
    """
    try:
        return loader()
    except ImportError as exc:  # missing [aws] extra
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    except Exception as exc:
        name = type(exc).__name__
        console.print(f"[red]{what} failed ({name}): {exc}[/red]")
        hint = _AWS_HINTS.get(name)
        if hint:
            console.print(f"[yellow]{hint}[/yellow]")
        raise typer.Exit(1) from exc

app = typer.Typer(
    add_completion=False,
    help="FinOps cost analysis: find dollar-quantified AWS savings.",
    no_args_is_help=True,
)
console = Console()


class Format(StrEnum):
    rich = "rich"
    md = "md"
    json = "json"


_SEVERITY_STYLE = {
    Severity.HIGH: "bold red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "dim",
}


def _emit(report: Report, fmt: Format, out: Path | None) -> None:
    if fmt is Format.rich:
        if out:
            out.write_text(render_markdown(report))
            console.print(f"[green]Wrote markdown report to {out}[/green]")
        else:
            _print_rich(report)
        return

    text = render_json(report) if fmt is Format.json else render_markdown(report)
    if out:
        out.write_text(text)
        console.print(f"[green]Wrote {fmt.value} report to {out}[/green]")
    else:
        # Raw to stdout so it pipes cleanly to a file.
        print(text)


def _print_rich(report: Report) -> None:
    head = (
        f"[bold]AWS spend {report.billing_period:%B %Y}:[/bold] "
        f"${report.total_cost:,.0f}/mo\n"
        f"[bold green]Recoverable:[/bold green] "
        f"${report.total_estimated_monthly_savings:,.0f}/mo "
        f"({report.savings_pct_of_spend:.0%}, ${report.total_annual_savings:,.0f}/yr)"
    )
    provenance = []
    if report.source:
        provenance.append(f"[dim]source: {report.source}[/dim]")
    if report.account_note:
        provenance.append(f"[dim]{report.account_note}[/dim]")
    if provenance:
        head += "\n" + "\n".join(provenance)
    console.print(Panel(head, title="cost-engine", border_style="green"))

    if report.executive_summary:
        console.print(Panel(report.executive_summary, title="Executive summary",
                            border_style="blue"))

    table = Table(title="Opportunities", header_style="bold")
    table.add_column("Pri")
    table.add_column("Opportunity")
    table.add_column("Save/mo", justify="right")
    table.add_column("Save/yr", justify="right")
    table.add_column("Conf", justify="right")
    for f in report.findings:
        style = _SEVERITY_STYLE[f.severity]
        save = "—" if f.estimated_monthly_savings == 0 else f"${f.estimated_monthly_savings:,.0f}"
        annual = "—" if f.estimated_monthly_savings == 0 else f"${f.annual_savings:,.0f}"
        table.add_row(
            f"[{style}]{f.severity.value.upper()}[/{style}]",
            f.title,
            save,
            annual,
            f"{f.confidence:.0%}",
        )
    console.print(table)
    console.print(
        "[dim]Run with --format md or --format json for the full report.[/dim]"
    )


@app.command()
def demo(
    fmt: Format = typer.Option(Format.rich, "--format", "-f", help="Output format."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the LLM summary."),
    seed: int = typer.Option(42, help="Synthetic data seed."),
    period: str = typer.Option("2026-05-01", help="Billing period start (YYYY-MM-DD)."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write to file."),
) -> None:
    """Analyze the built-in synthetic AWS account."""
    df = generate_synthetic_cur(period=date.fromisoformat(period), seed=seed)
    report = summarize(analyze(df), use_llm=not no_llm)
    report.source = "synthetic account (generated, not real AWS data)"
    report.account_note = _account_note_from_data(df)
    _emit(report, fmt, out)


@app.command()
def report(
    input: Path = typer.Option(..., "--input", "-i", help="CUR parquet/csv file."),
    fmt: Format = typer.Option(Format.rich, "--format", "-f", help="Output format."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the LLM summary."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write to file."),
) -> None:
    """Analyze a CUR file (parquet or CSV)."""
    df = load_cur(input)
    rep = summarize(analyze(df), use_llm=not no_llm)
    rep.source = f"file: {input}"
    rep.account_note = _account_note_from_data(df)
    _emit(rep, fmt, out)


@app.command()
def s3(
    bucket: str = typer.Option(..., "--bucket", "-b", help="S3 bucket holding the CUR."),
    prefix: str | None = typer.Option(
        None, "--prefix", "-p", help="Prefix to search; the latest object is used."
    ),
    key: str | None = typer.Option(None, "--key", "-k", help="Exact object key."),
    fmt: Format = typer.Option(Format.rich, "--format", "-f", help="Output format."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the LLM summary."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write to file."),
) -> None:
    """Pull a CUR straight from S3 (full fidelity) and analyze it."""
    if not key and not prefix:
        raise typer.BadParameter("provide --prefix or --key")
    df = _load_or_exit(
        lambda: load_cur_from_s3(bucket, prefix=prefix, key=key), what="S3 read"
    )
    rep = summarize(analyze(df), use_llm=not no_llm)
    target = key if key else f"{prefix} (latest)"
    rep.source = f"s3://{bucket}/{target}"
    rep.account_note = _account_note_from_data(df)  # the CUR carries the account id
    _emit(rep, fmt, out)


@app.command(name="cost-explorer")
def cost_explorer(
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD."),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD (exclusive)."),
    fmt: Format = typer.Option(Format.rich, "--format", "-f", help="Output format."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the LLM summary."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write to file."),
) -> None:
    """Pull a top-line dataset from Cost Explorer and analyze it.

    Cost Explorer carries no tags or purchase term, so the untagged-spend and
    Savings Plan coverage rules are skipped. Use `s3` for full fidelity.
    """
    df = _load_or_exit(
        lambda: load_from_cost_explorer(
            date.fromisoformat(start) if start else None,
            date.fromisoformat(end) if end else None,
        ),
        what="Cost Explorer query",
    )
    supported = [r for r in ALL_RULES if r.rule_id not in CE_UNSUPPORTED_RULE_IDS]
    rep = summarize(analyze(df, rules=supported), use_llm=not no_llm)
    rep.source = "Cost Explorer API"
    # Cost Explorer data has no account id; label the calling credentials instead.
    rep.account_note = caller_identity_label() or ""
    if fmt is Format.rich:
        console.print(
            "[dim]Cost Explorer source: untagged-spend and savings-plan-coverage "
            "rules skipped (need the CUR). Use `cost-engine s3` for full fidelity.[/dim]"
        )
    _emit(rep, fmt, out)


@app.command(name="gen-sample")
def gen_sample(
    out_dir: Path = typer.Option(
        Path("data/sample-cur"), "--out-dir", help="Where to write the sample CUR."
    ),
    seed: int = typer.Option(42),
    period: str = typer.Option("2026-05-01"),
) -> None:
    """Write the synthetic CUR to disk as parquet + CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = generate_synthetic_cur(period=date.fromisoformat(period), seed=seed)
    parquet = out_dir / "sample-cur.parquet"
    csv = out_dir / "sample-cur.csv"
    df.write_parquet(parquet)
    df.write_csv(csv)
    console.print(
        f"[green]Wrote {df.height:,} rows[/green] to {parquet} and {csv}"
    )


if __name__ == "__main__":
    app()
