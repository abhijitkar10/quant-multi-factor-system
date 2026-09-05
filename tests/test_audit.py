"""The audit exists to stop bad vendor data reaching a factor, so it must actually catch it."""

from datetime import date, timedelta

import polars as pl

from qmf.data.audit import audit_prices


def panel(tickers=("AAA", "BBB"), days: int = 10) -> pl.DataFrame:
    rows = []
    for t in tickers:
        for i in range(days):
            price = 100.0 + i
            rows.append(
                {
                    "ticker": t,
                    "dt": date(2024, 1, 1) + timedelta(days=i),
                    "close": price,
                    "adj_close": price,
                }
            )
    return pl.DataFrame(rows)


def check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_clean_panel_passes():
    report = audit_prices(panel(), expected_tickers=["AAA", "BBB"])
    assert report.passed
    assert report.failures == []


def test_empty_panel_fails_row_count():
    report = audit_prices(panel(days=0), expected_tickers=["AAA"])
    assert not report.passed
    assert not check(report, "row_count").passed


def test_duplicate_keys_are_caught():
    df = pl.concat([panel(), panel().head(1)])
    report = audit_prices(df, expected_tickers=["AAA", "BBB"])
    assert not report.passed
    assert check(report, "no_duplicate_keys").value == 2  # both sides of the dup


def test_null_close_is_caught():
    df = panel().with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(None).otherwise(pl.col("close")).alias("close")
    )
    report = audit_prices(df, expected_tickers=["AAA", "BBB"])
    assert not report.passed
    assert not check(report, "no_null_close").passed


def test_nonpositive_price_is_caught():
    df = panel().with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(-1.0).otherwise(pl.col("close")).alias("close")
    )
    report = audit_prices(df, expected_tickers=["AAA", "BBB"])
    assert not check(report, "positive_prices").passed


def test_missing_ticker_drops_coverage_below_threshold():
    report = audit_prices(panel(tickers=("AAA",)), expected_tickers=["AAA", "BBB"])
    coverage = check(report, "universe_coverage")
    assert coverage.value == 0.5
    assert not coverage.passed
    assert "BBB" in coverage.detail


def test_outliers_warn_but_do_not_halt_the_feed():
    """Return outliers are non-critical: they flag for review without blocking the write."""
    df = panel()
    spiked = df.with_columns(
        pl.when((pl.col("ticker") == "AAA") & (pl.col("dt") == date(2024, 1, 5)))
        .then(1000.0)
        .otherwise(pl.col("adj_close"))
        .alias("adj_close")
    )
    report = audit_prices(spiked, expected_tickers=["AAA", "BBB"])
    outliers = check(report, "return_outliers")
    assert not outliers.passed
    assert not outliers.critical
    assert report.passed  # critical checks all pass, so the feed is not halted


def test_stale_data_is_caught():
    report = audit_prices(panel(), expected_tickers=["AAA", "BBB"], expected_end=date(2024, 6, 1))
    assert not check(report, "freshness").passed


def test_report_frame_round_trips():
    report = audit_prices(panel(), expected_tickers=["AAA", "BBB"])
    frame = report.to_frame()
    assert frame.height == len(report.checks)
    assert set(frame.columns) >= {"table", "check", "passed", "critical", "run_at"}
