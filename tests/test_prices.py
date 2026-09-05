"""The price loader's transform: schema, idempotency, and hygiene."""

from datetime import date

import polars as pl

from qmf.data.prices import SCHEMA, transform


def raw(rows: int = 3, with_adj: bool = True) -> pl.DataFrame:
    data = {
        "ticker": ["aapl"] * rows,
        "dt": [date(2024, 1, 1 + i) for i in range(rows)],
        "open": [100.0 + i for i in range(rows)],
        "high": [101.0 + i for i in range(rows)],
        "low": [99.0 + i for i in range(rows)],
        "close": [100.5 + i for i in range(rows)],
        "volume": [1_000_000.0] * rows,
    }
    if with_adj:
        data["adj_close"] = [100.0 + i for i in range(rows)]
    return pl.DataFrame(data)


def test_output_matches_the_declared_schema():
    out = transform(raw())
    assert set(out.columns) == set(SCHEMA)
    for col, dtype in SCHEMA.items():
        assert out.schema[col] == dtype, col


def test_ticker_is_upper_cased():
    assert transform(raw())["ticker"].unique().to_list() == ["AAPL"]


def test_year_partition_column_is_derived():
    assert transform(raw())["year"].unique().to_list() == [2024]


def test_duplicate_rows_are_collapsed():
    """Re-running an overlapping window must not double-write: the loader is idempotent."""
    doubled = pl.concat([raw(), raw()])
    out = transform(doubled)
    assert out.height == 3
    assert out.select(["ticker", "dt"]).is_duplicated().sum() == 0


def test_null_close_rows_are_dropped():
    df = raw().with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(None).otherwise(pl.col("close")).alias("close")
    )
    assert transform(df).height == 2


def test_missing_adj_close_falls_back_to_close():
    out = transform(raw(with_adj=False))
    assert out["adj_close"].to_list() == out["close"].to_list()


def test_empty_input_returns_empty_typed_frame():
    out = transform(pl.DataFrame(schema={"ticker": pl.Utf8, "dt": pl.Date}))
    assert out.height == 0
    assert set(out.columns) == set(SCHEMA)


def test_output_is_sorted_by_ticker_then_date():
    shuffled = raw().sample(fraction=1.0, shuffle=True, seed=0)
    out = transform(shuffled)
    assert out["dt"].to_list() == sorted(out["dt"].to_list())
