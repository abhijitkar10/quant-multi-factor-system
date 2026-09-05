"""Phase 1c — data auditing.

You cannot depend on a vendor to send correct data every day, and a silently wrong file is
worse than a missing one: the loader succeeds, the factor runs, and it trades on garbage.
So every feed gets statistical checks — coverage of the expected universe, null and
duplicate rates, distributional outliers, freshness — and anything crossing a threshold
halts the feed instead of propagating downstream.

Reports are appended to the ``audits`` Delta table so the check history is queryable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import polars as pl

from qmf.storage import write_delta

AUDIT_TABLE = "audits"

_REPORT_SCHEMA = {
    "table": pl.Utf8,
    "check": pl.Utf8,
    "passed": pl.Boolean,
    "critical": pl.Boolean,
    "value": pl.Float64,
    "threshold": pl.Float64,
    "detail": pl.Utf8,
    "run_at": pl.Datetime("us"),
}


@dataclass
class Check:
    """One assertion about a dataset."""

    name: str
    passed: bool
    value: float | None = None
    threshold: float | None = None
    detail: str = ""
    #: Non-critical checks warn but do not halt the feed.
    critical: bool = True


@dataclass
class AuditReport:
    table: str
    checks: list[Check]
    run_at: datetime

    @property
    def passed(self) -> bool:
        """A report passes when every *critical* check passes."""
        return all(c.passed for c in self.checks if c.critical)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def to_frame(self) -> pl.DataFrame:
        return pl.DataFrame(
            [
                {
                    "table": self.table,
                    "check": c.name,
                    "passed": c.passed,
                    "critical": c.critical,
                    "value": None if c.value is None else float(c.value),
                    "threshold": None if c.threshold is None else float(c.threshold),
                    "detail": c.detail,
                    "run_at": self.run_at,
                }
                for c in self.checks
            ],
            schema=_REPORT_SCHEMA,
        )

    def persist(self) -> None:
        write_delta(self.to_frame(), AUDIT_TABLE, mode="append")


def audit_prices(
    df: pl.DataFrame,
    *,
    expected_tickers: list[str],
    expected_end: date | None = None,
    coverage_threshold: float = 0.95,
    extreme_move: float = 0.5,
    outlier_share_threshold: float = 0.005,
    max_staleness_days: int = 7,
) -> AuditReport:
    """Audit a daily price panel."""
    now = datetime.now(UTC).replace(tzinfo=None)
    checks: list[Check] = []

    n = df.height
    checks.append(Check("row_count", n > 0, float(n), 1.0, f"{n:,} rows"))
    if n == 0:
        return AuditReport("prices_daily", checks, now)

    dupes = int(df.select(["ticker", "dt"]).is_duplicated().sum())
    checks.append(
        Check("no_duplicate_keys", dupes == 0, float(dupes), 0.0, f"{dupes} duplicate (ticker, dt)")
    )

    null_close = int(df["close"].null_count())
    checks.append(Check("no_null_close", null_close == 0, float(null_close), 0.0))

    nonpositive = df.filter(pl.col("close") <= 0).height
    checks.append(Check("positive_prices", nonpositive == 0, float(nonpositive), 0.0))

    expected = {t.upper() for t in expected_tickers}
    got = set(df["ticker"].unique().to_list())
    coverage = len(expected & got) / len(expected) if expected else 1.0
    missing = sorted(expected - got)
    checks.append(
        Check(
            "universe_coverage",
            coverage >= coverage_threshold,
            coverage,
            coverage_threshold,
            f"{len(missing)} missing: {', '.join(missing[:8])}" if missing else "complete",
        )
    )

    # Returns are computed on the adjusted close so splits do not masquerade as outliers.
    rets = df.sort(["ticker", "dt"]).with_columns(
        (pl.col("adj_close") / pl.col("adj_close").shift(1).over("ticker") - 1).alias("ret")
    )
    extreme = rets.filter(pl.col("ret").abs() > extreme_move).height
    share = extreme / n
    checks.append(
        Check(
            "return_outliers",
            share <= outlier_share_threshold,
            share,
            outlier_share_threshold,
            f"{extreme} moves beyond ±{extreme_move:.0%}",
            critical=False,
        )
    )

    if expected_end is not None:
        newest = df["dt"].max()
        lag = (expected_end - newest).days
        checks.append(
            Check(
                "freshness",
                lag <= max_staleness_days,
                float(lag),
                float(max_staleness_days),
                f"newest row {newest}, {lag}d behind {expected_end}",
            )
        )

    return AuditReport("prices_daily", checks, now)


class DataAuditError(RuntimeError):
    """A feed's audit failed, so the feed is halted rather than published."""
