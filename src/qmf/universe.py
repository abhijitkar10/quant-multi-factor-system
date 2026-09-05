"""Phase 0 — the point-in-time tradable universe.

The video's first instruction is to draw the boundary before anything else: decide which
names you are willing to trade, and remember that the answer *changes over time*. Asking
"which tickers are in the universe" without a date is the single easiest way to introduce
survivorship bias — you end up backtesting on the set of companies that happened to survive
until today.

So the universe is stored as membership *intervals* (``added`` .. ``removed``) and every
read is resolved as of a date.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from qmf.config import REFERENCE
from qmf.storage import read_delta, table_exists, write_delta

TABLE = "universe"
SEED_FILE = "universe_seed.csv"


def load_seed() -> pl.DataFrame:
    """Read the hand-maintained membership seed (see data/reference/README.md)."""
    path = REFERENCE / SEED_FILE
    if not path.exists():
        raise FileNotFoundError(f"universe seed not found: {path}")

    return pl.read_csv(
        path,
        schema_overrides={
            "ticker": pl.Utf8,
            "name": pl.Utf8,
            "sector": pl.Utf8,
            "added": pl.Date,
            "removed": pl.Date,
        },
        try_parse_dates=True,
    )


def build_universe() -> pl.DataFrame:
    """Materialise the seed into the ``universe`` Delta table."""
    df = load_seed().with_columns(
        pl.col("ticker").str.strip_chars().str.to_uppercase(),
        pl.lit(SEED_FILE).alias("source"),
    )
    write_delta(df, TABLE, mode="overwrite")
    return df


def _universe_frame() -> pl.DataFrame:
    return read_delta(TABLE) if table_exists(TABLE) else build_universe()


def filter_as_of(frame: pl.DataFrame, as_of: date) -> pl.DataFrame:
    """Pure membership predicate, kept separate from storage so it is directly testable.

    ``added`` is inclusive and ``removed`` is exclusive: a name is tradable on the day it
    joins and no longer tradable on the day it leaves.
    """
    return frame.filter(
        (pl.col("added") <= as_of) & (pl.col("removed").is_null() | (pl.col("removed") > as_of))
    ).sort("ticker")


def filter_active_between(frame: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    """Names tradable at *any* point in ``[start, end]``."""
    return frame.filter(
        (pl.col("added") <= end) & (pl.col("removed").is_null() | (pl.col("removed") > start))
    ).sort("ticker")


def universe_as_of(as_of: date) -> pl.DataFrame:
    """Names tradable on ``as_of``."""
    return filter_as_of(_universe_frame(), as_of)


def tickers_as_of(as_of: date) -> list[str]:
    return universe_as_of(as_of)["ticker"].to_list()


def tickers_active_between(start: date, end: date) -> list[str]:
    """Every name tradable at any point in ``[start, end]``.

    This is the set to ingest prices for: a backtest over the window needs history for
    names that have since left the universe, or it silently becomes survivorship-biased.
    """
    return filter_active_between(_universe_frame(), start, end)["ticker"].to_list()
