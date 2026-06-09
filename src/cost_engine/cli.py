"""cost-engine command line.

    cost-engine demo                 analyze the built-in synthetic account
    cost-engine demo --format json   machine-readable report
    cost-engine report -i cur.parquet   analyze a real/sample CUR file
    cost-engine gen-sample           write the sample CUR to data/sample-cur/
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .analyze import analyze
from .ingest import generate_synthetic_cur
from .ingest.load import load_cur
from .models import Report, Severity
from .report import render_json, render_markdown, summarize

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
