"""Turning point-in-time membership snapshots into intervals."""

from datetime import date

import polars as pl

from qmf.data.constituents import intervals_from_snapshots, to_our_ticker

Q1, Q2, Q3, Q4 = date(2020, 1, 1), date(2020, 4, 1), date(2020, 7, 1), date(2020, 10, 1)


def spans(df: pl.DataFrame, ticker: str) -> list[tuple]:
    rows = df.filter(pl.col("ticker") == ticker).sort("added")
    return [(r["added"], r["removed"]) for r in rows.iter_rows(named=True)]


def test_wikipedia_share_class_convention_is_translated():
    # Wikipedia BRK.B -> our BRK-B -> OpenFIGI BRK/B. Three spellings, one security.
    assert to_our_ticker("BRK.B") == "BRK-B"
    assert to_our_ticker(" aapl ") == "AAPL"


def test_name_present_throughout_stays_open():
    out = intervals_from_snapshots({Q1: {"AAPL"}, Q2: {"AAPL"}, Q3: {"AAPL"}})
    assert spans(out, "AAPL") == [(Q1, None)]


def test_name_that_disappears_is_closed_at_that_snapshot():
    """The whole point: a company that left the index still exists in history."""
    out = intervals_from_snapshots({Q1: {"AAPL", "TWTR"}, Q2: {"AAPL", "TWTR"}, Q3: {"AAPL"}})
    assert spans(out, "TWTR") == [(Q1, Q3)]
    assert spans(out, "AAPL") == [(Q1, None)]


def test_name_that_appears_later_starts_then():
    out = intervals_from_snapshots({Q1: {"AAPL"}, Q2: {"AAPL", "TSLA"}, Q3: {"AAPL", "TSLA"}})
    assert spans(out, "TSLA") == [(Q2, None)]


def test_name_that_left_and_rejoined_gets_two_intervals():
    out = intervals_from_snapshots({Q1: {"X"}, Q2: set(), Q3: {"X"}, Q4: {"X"}})
    assert spans(out, "X") == [(Q1, Q2), (Q3, None)]


def test_intervals_never_overlap():
    out = intervals_from_snapshots({Q1: {"X"}, Q2: set(), Q3: {"X"}, Q4: {"X"}})
    runs = spans(out, "X")
    for (_, end), (nxt_start, _) in zip(runs, runs[1:], strict=False):
        assert end <= nxt_start


def test_empty_input_returns_typed_empty_frame():
    out = intervals_from_snapshots({})
    assert out.height == 0
    assert out.schema["added"] == pl.Date
