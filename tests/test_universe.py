"""Point-in-time membership is the guard against survivorship bias, so it gets real tests."""

from datetime import date

import polars as pl
from hypothesis import given
from hypothesis import strategies as st

from qmf.universe import filter_active_between, filter_as_of

REMOVED_ON = date(2022, 11, 8)
ADDED_LATE = date(2020, 12, 21)


def frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ticker": ["ALIVE", "LEFT", "LATE"],
            "added": [date(2015, 1, 1), date(2015, 1, 1), ADDED_LATE],
            "removed": [None, REMOVED_ON, None],
        },
        schema={"ticker": pl.Utf8, "added": pl.Date, "removed": pl.Date},
    )


def tickers_as_of(d: date) -> list[str]:
    return filter_as_of(frame(), d)["ticker"].to_list()


def test_removed_name_is_a_member_before_removal():
    assert "LEFT" in tickers_as_of(date(2022, 11, 7))


def test_removed_date_is_exclusive():
    # A name is not tradable on the day it leaves.
    assert "LEFT" not in tickers_as_of(REMOVED_ON)


def test_added_date_is_inclusive():
    assert "LATE" in tickers_as_of(ADDED_LATE)
    assert "LATE" not in tickers_as_of(date(2020, 12, 20))


def test_never_removed_name_is_always_a_member_after_adding():
    assert "ALIVE" in tickers_as_of(date(2015, 1, 1))
    assert "ALIVE" in tickers_as_of(date(2030, 1, 1))


def test_active_between_keeps_names_that_left_mid_window():
    """The survivorship-bias guard: ingest must cover names that have since disappeared."""
    active = filter_active_between(frame(), date(2021, 1, 1), date(2024, 1, 1))["ticker"].to_list()
    assert "LEFT" in active


def test_active_between_excludes_names_that_left_before_the_window():
    active = filter_active_between(frame(), date(2023, 1, 1), date(2024, 1, 1))["ticker"].to_list()
    assert "LEFT" not in active


@given(st.dates(min_value=date(2010, 1, 1), max_value=date(2035, 1, 1)))
def test_as_of_equals_a_degenerate_window(d: date):
    """`as of d` and `active between d and d` must describe the same set."""
    as_of = set(filter_as_of(frame(), d)["ticker"].to_list())
    window = set(filter_active_between(frame(), d, d)["ticker"].to_list())
    assert as_of == window


@given(st.dates(min_value=date(2010, 1, 1), max_value=date(2035, 1, 1)))
def test_membership_is_never_larger_than_the_seed(d: date):
    assert filter_as_of(frame(), d).height <= frame().height
