"""Daily OHLCV prices (yfinance): fetch -> transform -> audit -> write.

The audit runs *before* the write. Auditing a published table means every downstream
factor has already read the bad data by the time anyone notices.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import polars as pl
import yfinance as yf

from qmf.data.audit import AuditReport, DataAuditError, audit_prices
from qmf.storage import write_delta

TABLE = "prices_daily"
# Partition by year, not date: a daily partition over 15y x 500 names is ~3,900
# directories of tiny files, and that metadata overhead costs more than the pruning saves.
PARTITION_BY = ["year"]

_RENAME = {
    "Date": "dt",
    "Ticker": "ticker",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}

SCHEMA = {
    "ticker": pl.Utf8,
    "dt": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "adj_close": pl.Float64,
    "volume": pl.Float64,
    "year": pl.Int32,
    "ingested_at": pl.Datetime("us"),
    "source": pl.Utf8,
}


def fetch(tickers: list[str], start: date, end: date) -> pl.DataFrame:
    raw = yf.download(
        tickers=list(tickers),
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if raw is None or len(raw) == 0:
        return pl.DataFrame(schema={"ticker": pl.Utf8, "dt": pl.Date})

    if isinstance(raw.columns, pd.MultiIndex):
        tidy = raw.stack(level=-1, future_stack=True).reset_index()
    else:
        tidy = raw.reset_index()
        tidy["Ticker"] = list(tickers)[0]

    tidy.columns = [str(c) for c in tidy.columns]
    return pl.from_pandas(tidy.rename(columns=_RENAME))


def transform(df: pl.DataFrame) -> pl.DataFrame:
    if df.height == 0:
        return pl.DataFrame(schema=SCHEMA)

    if "adj_close" not in df.columns:
        df = df.with_columns(pl.col("close").alias("adj_close"))

    return (
        df.select(
            pl.col("ticker").cast(pl.Utf8).str.to_uppercase().alias("ticker"),
            pl.col("dt").cast(pl.Date).alias("dt"),
            pl.col("open").cast(pl.Float64).alias("open"),
            pl.col("high").cast(pl.Float64).alias("high"),
            pl.col("low").cast(pl.Float64).alias("low"),
            pl.col("close").cast(pl.Float64).alias("close"),
            pl.col("adj_close").cast(pl.Float64).alias("adj_close"),
            pl.col("volume").cast(pl.Float64).alias("volume"),
        )
        .filter(pl.col("close").is_not_null() & pl.col("ticker").is_not_null())
        # Re-running an overlapping window must not double-write: load is idempotent.
        .unique(subset=["ticker", "dt"], keep="last")
        .sort(["ticker", "dt"])
        .with_columns(
            pl.col("dt").dt.year().cast(pl.Int32).alias("year"),
            pl.lit(datetime.now(UTC).replace(tzinfo=None))
            .cast(pl.Datetime("us"))
            .alias("ingested_at"),
            pl.lit("yfinance").alias("source"),
        )
    )


def load(
    tickers: list[str],
    start: date,
    end: date,
    *,
    required: list[str] | None = None,
    mode: str = "overwrite",
) -> tuple[int, AuditReport]:
    """Fetch, audit, and publish. A failing critical check halts before the write.

    ``required`` is the subset the vendor is genuinely expected to serve (defaults to all
    of ``tickers``). The rest are reported but do not gate the feed.
    """
    required = list(required) if required is not None else list(tickers)
    df = transform(fetch(tickers, start, end))
    report = audit_prices(
        df,
        expected_tickers=required,
        delisted_tickers=tickers,
        expected_end=min(end, date.today()),
    )
    report.persist()
    if not report.passed:
        failed = ", ".join(c.name for c in report.failures if c.critical)
        raise DataAuditError(f"audit failed ({failed}) — feed halted, {TABLE} not written")
    write_delta(df, TABLE, mode=mode, partition_by=PARTITION_BY)
    return df.height, report
