"""Real point-in-time index membership, read from Wikipedia's revision history.

The hand-seeded universe was the weakest part of this system: a list of names that are large
*today*, which is survivorship bias baked into the experiment itself. No amount of
point-in-time query logic fixes a universe chosen with hindsight.

So membership is taken from evidence instead. Wikipedia keeps every past revision of its S&P
500 constituents page, so fetching the page *as it existed* on a past date says who was
actually in the index then -- including companies since acquired, delisted or failed. A
sequence of such snapshots turns into membership intervals.

This is stronger evidence than a curated change log: it is the list itself at that moment,
not somebody's summary of what changed.
"""

from __future__ import annotations

import io
import time
from datetime import date, timedelta

import httpx
import pandas as pd
import polars as pl

from qmf.storage import write_delta

API = "https://en.wikipedia.org/w/api.php"
PAGE = "List of S&P 500 companies"
RAW = "https://en.wikipedia.org/w/index.php"
TABLE = "universe"
UA = {"User-Agent": "qmf/0.1 (personal research project)"}

# ponytail: quarterly snapshots. Membership changes are dated to the next snapshot boundary,
# so a name added in February reads as added in April -- up to ~3 months of error. Drop to
# 30 for monthly resolution at 3x the requests, if that error ever matters.
SNAPSHOT_DAYS = 91

_SCHEMA = {
    "ticker": pl.Utf8,
    "name": pl.Utf8,
    "sector": pl.Utf8,
    "added": pl.Date,
    "removed": pl.Date,
    "source": pl.Utf8,
}


def to_our_ticker(ticker: str) -> str:
    """Wikipedia writes share classes as ``BRK.B``; our price vendor writes ``BRK-B``.

    A third convention for the same security, after ours and OpenFIGI's ``BRK/B``. This is
    exactly what security matching exists for.
    """
    return str(ticker).strip().upper().replace(".", "-")


def _flatten(columns) -> list[str]:
    if isinstance(columns, pd.MultiIndex):
        return [" ".join(str(p) for p in tup).strip().lower() for tup in columns]
    return [str(c).strip().lower() for c in columns]


def _constituents_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    """Find the constituents table by its content, not its position on the page.

    Indexing tables by position is what broke the first version of this: the page layout is
    not a contract, and older revisions label the column "Ticker symbol" rather than "Symbol".
    """
    for table in tables:
        columns = _flatten(table.columns)
        if len(table) > 100 and any("symbol" in c or "ticker" in c for c in columns):
            out = table.copy()
            out.columns = columns
            return out
    return None


def revision_at(when: date, client: httpx.Client) -> int | None:
    """Newest revision id at or before ``when``."""
    resp = client.get(
        API,
        params={
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "titles": PAGE,
            "rvlimit": 1,
            "rvdir": "older",
            "rvstart": f"{when.isoformat()}T23:59:59Z",
            "rvprop": "ids|timestamp",
        },
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        revisions = page.get("revisions") or []
        if revisions:
            return revisions[0]["revid"]
    return None


def members_at(revid: int, client: httpx.Client) -> tuple[set[str], pd.DataFrame | None]:
    """Constituent tickers in a specific past revision of the page."""
    resp = client.get(RAW, params={"title": PAGE, "oldid": revid})
    resp.raise_for_status()
    table = _constituents_table(pd.read_html(io.StringIO(resp.text)))
    if table is None:
        return set(), None
    column = next(c for c in table.columns if "symbol" in c or "ticker" in c)
    return {to_our_ticker(t) for t in table[column] if str(t) != "nan"}, table


def snapshots(
    start: date, end: date, *, step_days: int = SNAPSHOT_DAYS, pause: float = 0.3
) -> tuple[dict[date, set[str]], pd.DataFrame | None]:
    """Membership on a grid of past dates, plus the most recent table for its metadata."""
    grid, cursor = [], start
    while cursor < end:
        grid.append(cursor)
        cursor += timedelta(days=step_days)
    grid.append(end)

    out: dict[date, set[str]] = {}
    newest: pd.DataFrame | None = None
    with httpx.Client(headers=UA, timeout=30.0, follow_redirects=True) as client:
        for when in grid:
            revid = revision_at(when, client)
            if revid is None:
                continue
            members, table = members_at(revid, client)
            if members:
                out[when] = members
                newest = table if table is not None else newest
            time.sleep(pause)
    return out, newest


def intervals_from_snapshots(snaps: dict[date, set[str]]) -> pl.DataFrame:
    """Turn a series of membership snapshots into contiguous membership intervals.

    A name present across consecutive snapshots is one interval; a gap closes it and a later
    reappearance opens another, so names that left and rejoined are represented honestly.
    """
    dates = sorted(snaps)
    if not dates:
        return pl.DataFrame(schema={"ticker": pl.Utf8, "added": pl.Date, "removed": pl.Date})

    rows = []
    for ticker in sorted(set().union(*snaps.values())):
        run_start: date | None = None
        for when in dates:
            present = ticker in snaps[when]
            if present and run_start is None:
                run_start = when
            elif not present and run_start is not None:
                rows.append({"ticker": ticker, "added": run_start, "removed": when})
                run_start = None
        if run_start is not None:
            rows.append({"ticker": ticker, "added": run_start, "removed": None})

    return pl.DataFrame(
        rows, schema={"ticker": pl.Utf8, "added": pl.Date, "removed": pl.Date}
    ).sort(["ticker", "added"])


def build(start: date, end: date, *, step_days: int = SNAPSHOT_DAYS) -> pl.DataFrame:
    """Fetch snapshots, build intervals, and publish the universe table."""
    snaps, newest = snapshots(start, end, step_days=step_days)
    if not snaps:
        raise ValueError("no usable revisions fetched; refusing to overwrite the universe")

    intervals = intervals_from_snapshots(snaps)

    meta = pl.DataFrame(schema={"ticker": pl.Utf8, "name": pl.Utf8, "sector": pl.Utf8})
    if newest is not None:
        sym = next(c for c in newest.columns if "symbol" in c or "ticker" in c)
        name = next((c for c in newest.columns if "security" in c or "company" in c), None)
        sector = next((c for c in newest.columns if "sector" in c), None)
        meta = pl.DataFrame(
            {
                "ticker": [to_our_ticker(t) for t in newest[sym]],
                "name": newest[name].astype(str).tolist() if name else [""] * len(newest),
                "sector": newest[sector].astype(str).tolist() if sector else [""] * len(newest),
            }
        ).unique(subset=["ticker"])

    universe = (
        intervals.join(meta, on="ticker", how="left")
        .with_columns(
            pl.col("name").fill_null(""),
            pl.col("sector").fill_null(""),
            pl.lit("wikipedia-revisions").alias("source"),
        )
        .select(list(_SCHEMA))
    )
    write_delta(universe, TABLE, mode="overwrite")
    return universe
