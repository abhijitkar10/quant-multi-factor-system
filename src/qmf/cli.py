"""Command line entry point: ``qmf <command>``."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from qmf import config, storage
from qmf import factors as fac
from qmf import portfolio as pf
from qmf import universe as uni
from qmf.data import prices
from qmf.data import security_master as sm
from qmf.data.audit import AuditReport, DataAuditError

app = typer.Typer(help="Multi-factor equity trading system.", no_args_is_help=True)
console = Console()


def _mark(check) -> str:
    """A failing non-critical check warns; a failing critical one halts the feed."""
    if check.passed:
        return "[green]PASS[/]"
    return "[red]FAIL[/]" if check.critical else "[yellow]WARN[/]"


def _render_report(report: AuditReport) -> None:
    table = Table(title=f"audit · {report.table}", header_style="bold")
    for col in ("check", "result", "value", "threshold", "detail"):
        table.add_column(col)
    for c in report.checks:
        table.add_row(
            c.name,
            _mark(c),
            "—" if c.value is None else f"{c.value:,.4g}",
            "—" if c.threshold is None else f"{c.threshold:,.4g}",
            c.detail,
        )
    console.print(table)


@app.command()
def universe(
    as_of: str = typer.Option(None, help="ISO date; defaults to today."),
    rebuild: bool = typer.Option(False, help="Rebuild the table from the seed CSV."),
) -> None:
    """Show the point-in-time tradable universe."""
    config.ensure_dirs()
    if rebuild:
        uni.build_universe()
        console.print("[green]rebuilt[/] universe from seed")

    d = date.fromisoformat(as_of) if as_of else date.today()
    members = uni.universe_as_of(d)

    table = Table(title=f"universe as of {d}  ({members.height} names)", header_style="bold")
    for col in ("ticker", "name", "sector", "added"):
        table.add_column(col)
    for row in members.head(50).iter_rows(named=True):
        table.add_row(row["ticker"], row["name"], row["sector"], str(row["added"]))
    console.print(table)

    total = uni._universe_frame().height
    console.print(f"[dim]{total} in the seed; {total - members.height} not members on {d}[/]")


@app.command()
def ingest(
    start: str = typer.Option(None, help="ISO start date."),
    end: str = typer.Option(None, help="ISO end date (exclusive)."),
    mode: str = typer.Option("overwrite", help="overwrite | append"),
) -> None:
    """Load daily prices for every name active in the window."""
    config.ensure_dirs()
    start_d = date.fromisoformat(start) if start else config.START_DATE
    end_d = date.fromisoformat(end) if end else date.today()
    tickers = uni.tickers_active_between(start_d, end_d)

    console.print(f"ingesting [bold]{len(tickers)}[/] tickers, {start_d} → {end_d}")
    try:
        rows, report = prices.load(tickers, start_d, end_d, mode=mode)
    except DataAuditError as exc:
        console.print(f"[red]HALTED[/] {exc}")
        raise typer.Exit(code=1) from exc

    _render_report(report)
    console.print(f"[green]wrote[/] {rows:,} rows → {prices.TABLE}")


@app.command()
def match(as_of: str = typer.Option(None, help="ISO date for universe selection.")) -> None:
    """Resolve universe tickers to FIGIs and build the security master."""
    config.ensure_dirs()
    d = date.fromisoformat(as_of) if as_of else date.today()
    tickers = uni.tickers_as_of(d)

    console.print(f"matching [bold]{len(tickers)}[/] tickers via OpenFIGI…")
    master = sm.build(tickers)
    rate = sm.match_rate(master)

    table = Table(title=f"security master  ({master.height} rows)", header_style="bold")
    for col in ("ticker", "figi", "security_name", "status"):
        table.add_column(col)
    for row in master.head(15).iter_rows(named=True):
        table.add_row(
            row["ticker"],
            row["figi"] or "—",
            (row["security_name"] or "—")[:32],
            row["match_status"],
        )
    console.print(table)

    colour = "green" if rate >= 0.95 else "yellow" if rate > 0 else "red"
    console.print(f"match rate: [{colour}]{rate:.1%}[/]")


@app.command()
def factors() -> None:
    """Build signals, alpha, and factor returns from the price panel."""
    config.ensure_dirs()
    panel, rets, ic = fac.build()

    table = Table(title="signal skill (mean daily IC)", header_style="bold")
    for col in ("signal", "IC", "factor return (ann.)", "factor vol (ann.)"):
        table.add_column(col)
    ic_row = ic.row(0, named=True)
    for s in fac.SIGNALS:
        mu, sd = rets[s].mean() * 252, rets[s].std() * (252**0.5)
        table.add_row(s, f"{ic_row[s]:+.4f}", f"{mu:+.2%}", f"{sd:.2%}")
    console.print(table)
    console.print(
        f"[green]wrote[/] {panel.height:,} rows → {fac.TABLE}, "
        f"{rets.height:,} dates → {fac.RETURNS_TABLE}"
    )


@app.command()
def backtest(
    rebalance: int = typer.Option(21, help="Trading days between rebalances."),
    cost_bps: float = typer.Option(3.0, help="Round-trip cost in bps of notional traded."),
) -> None:
    """Construct portfolios from alpha + risk, trade them, and score the result."""
    config.ensure_dirs()
    curve, stats = pf.run(rebalance=rebalance, cost_bps=cost_bps)

    table = Table(title="backtest", header_style="bold")
    table.add_column("metric")
    table.add_column("value", justify="right")
    pct = {
        "ann_return_net",
        "ann_return_gross",
        "ann_vol",
        "implementation_shortfall",
        "max_drawdown",
        "ann_turnover",
    }
    for k, v in stats.items():
        as_pct = k in pct or k.startswith("from_")
        table.add_row(k, f"{v:.2%}" if as_pct else f"{v:,.2f}")
    console.print(table)


@app.command()
def status() -> None:
    """Show every Delta table in the lake with its version and row count."""
    tables = storage.list_tables()
    if not tables:
        console.print("[yellow]lake is empty[/] — run `qmf phase1`")
        return

    table = Table(title=f"lake · {config.LAKE}", header_style="bold")
    for col in ("table", "version", "rows", "columns"):
        table.add_column(col)
    for name in tables:
        df = storage.read_delta(name)
        table.add_row(name, str(storage.latest_version(name)), f"{df.height:,}", str(df.width))
    console.print(table)


@app.command()
def phase1(
    start: str = typer.Option(None, help="ISO start date."),
    end: str = typer.Option(None, help="ISO end date (exclusive)."),
    skip_match: bool = typer.Option(False, help="Skip the OpenFIGI step (offline runs)."),
) -> None:
    """Run the data block: universe → prices → security master → status."""
    config.ensure_dirs()
    console.rule("[bold]Phase 0 — universe")
    uni.build_universe()
    d = date.fromisoformat(end) if end else date.today()
    console.print(f"{len(uni.tickers_as_of(d))} names tradable as of {d}")

    console.rule("[bold]Phase 1 — prices")
    ingest(start=start, end=end, mode="overwrite")

    if not skip_match:
        console.rule("[bold]Phase 1b — security matching")
        match(as_of=end)

    console.rule("[bold]lake")
    status()


@app.command("point-in-time")
def point_in_time(ticker: str = typer.Argument(..., help="Ticker to inspect, e.g. TWTR.")) -> None:
    """Demonstrate why membership must be resolved as of a date, not as of today."""
    frame = uni._universe_frame().filter(pl.col("ticker") == ticker.upper())
    if frame.height == 0:
        console.print(f"[red]{ticker.upper()} is not in the seed[/]")
        raise typer.Exit(code=1)

    row = frame.row(0, named=True)
    removed = row["removed"]
    console.print(f"[bold]{row['ticker']}[/] — {row['name']}")
    console.print(f"  added   {row['added']}")
    console.print(f"  removed {removed or '— still a member'}")

    probes = [row["added"] + timedelta(days=1), date.today()]
    if removed:
        probes.insert(1, removed - timedelta(days=1))
        probes.insert(2, removed + timedelta(days=1))

    for p in probes:
        member = ticker.upper() in set(uni.tickers_as_of(p))
        console.print(
            f"  as of {p}: " + ("[green]in universe[/]" if member else "[red]not in universe[/]")
        )


if __name__ == "__main__":
    app()
