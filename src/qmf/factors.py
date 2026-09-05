"""Phase 2 — signals, alpha, and factor returns.

Signals come from the price panel alone. Value, size and quality need fundamentals we do
not load yet, so they are not here — add them the day a fundamentals loader exists.

The pipeline is the standard one: a raw signal is not tradable, so each is z-scored
cross-sectionally per date, and the combination is the alpha. Factor returns come from a
cross-sectional regression of next-day return on those scores — the same decomposition
that separates common factor moves from a name's own idiosyncratic return.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from qmf.storage import read_delta, write_delta

SIGNALS = ["momentum", "reversal", "low_vol"]
TABLE = "factors"
RETURNS_TABLE = "factor_returns"

_MONTH, _YEAR, _VOL_WINDOW = 21, 252, 60


def compute_signals(prices: pl.DataFrame) -> pl.DataFrame:
    """Raw signals plus the next-day return the regression fits against."""
    px = pl.col("adj_close")
    ret = px / px.shift(1) - 1
    return (
        prices.sort(["ticker", "dt"])
        .with_columns(
            # 12-1 momentum: skip the most recent month, which is reversal, not trend.
            (px.shift(_MONTH) / px.shift(_YEAR) - 1).over("ticker").alias("momentum"),
            (-(px / px.shift(_MONTH) - 1)).over("ticker").alias("reversal"),
            (-ret.rolling_std(_VOL_WINDOW)).over("ticker").alias("low_vol"),
            (px.shift(-1) / px - 1).over("ticker").alias("fwd_ret"),
        )
        .select(["ticker", "dt", *SIGNALS, "fwd_ret"])
    )


def zscore(panel: pl.DataFrame, signals: list[str] = SIGNALS) -> pl.DataFrame:
    """Cross-sectional z-score per date, winsorised at ±3 so one bad print cannot dominate."""
    return panel.with_columns(
        [
            ((pl.col(s) - pl.col(s).mean().over("dt")) / pl.col(s).std().over("dt"))
            .clip(-3, 3)
            .alias(f"z_{s}")
            for s in signals
        ]
    )


def add_alpha(
    panel: pl.DataFrame, weights: pl.DataFrame | None = None, signals: list[str] = SIGNALS
) -> pl.DataFrame:
    """Combine the scores into one forecast.

    With ``weights`` (a trailing-IC frame) each signal is scaled by its measured skill, so a
    signal that has been paid negatively is held short rather than diluting the blend.
    Without them, equal weights.
    """
    if weights is None:
        return panel.with_columns(
            pl.mean_horizontal([pl.col(f"z_{s}") for s in signals]).alias("alpha")
        )

    joined = panel.join(weights, on="dt", how="left")
    numerator = sum(pl.col(f"w_{s}") * pl.col(f"z_{s}") for s in signals)
    denominator = sum(pl.col(f"w_{s}").abs() for s in signals)
    return joined.with_columns((numerator / denominator).alias("alpha")).drop(
        [f"w_{s}" for s in signals]
    )


def daily_ic(panel: pl.DataFrame, signals: list[str] = SIGNALS) -> pl.DataFrame:
    """Per-date cross-sectional rank correlation of each score with the next-day return."""
    return (
        panel.drop_nulls(["fwd_ret", *[f"z_{s}" for s in signals]])
        .group_by("dt")
        .agg([pl.corr(f"z_{s}", "fwd_ret", method="spearman").alias(s) for s in signals])
        .sort("dt")
    )


def information_coefficient(panel: pl.DataFrame, signals: list[str] = SIGNALS) -> pl.DataFrame:
    """Mean IC — the "skill" term in IR ~= IC * sqrt(breadth).

    Says whether a signal carries any information at all.
    """
    return daily_ic(panel, signals).select([pl.col(s).mean().alias(s) for s in signals])


def _expanding_weight(signal: str, method: str) -> pl.Expr:
    """Expanding-window signal weight from the daily IC series.

    ``mean`` is the average IC so far. ``tstat`` divides that by its standard error, which
    is the point: a signal whose IC averages zero with a wide spread is noise, and raw-mean
    weighting still hands it a weight whose sign flips around. Dividing by the standard
    error shrinks a signal toward zero weight until its skill is measured consistently.
    Absolute scale does not matter -- ``add_alpha`` normalises by the sum of magnitudes.
    """
    column = pl.col(signal)
    n = column.cum_count()
    total = column.cum_sum()
    mean = total / n
    if method == "mean":
        return mean
    if method != "tstat":
        raise ValueError(f"unknown weighting method: {method!r}")
    variance = ((column**2).cum_sum() - total**2 / n) / (n - 1)
    return mean / (variance / n).sqrt()


def trailing_ic(
    panel: pl.DataFrame,
    signals: list[str] = SIGNALS,
    min_obs: int = 252,
    method: str = "mean",
) -> pl.DataFrame:
    """Expanding-window IC, lagged one day, for use as signal weights.

    Weighting by the *full-sample* IC would be in-sample fitting: you would be telling the
    backtest which signals worked using the very returns you are about to trade. Each date
    therefore sees only ICs measured strictly before it, and nothing is weighted until
    ``min_obs`` days of evidence exist.
    """
    daily = daily_ic(panel, signals).drop_nulls()
    return daily.with_row_index("_n").select(
        pl.col("dt"),
        *[
            pl.when(pl.col("_n") >= min_obs)
            .then(_expanding_weight(s, method).shift(1))
            .alias(f"w_{s}")
            for s in signals
        ],
    )


def factor_returns(panel: pl.DataFrame, signals: list[str] = SIGNALS) -> pl.DataFrame:
    """Per-date cross-sectional OLS of next-day return on the scores."""
    cols = [f"z_{s}" for s in signals]
    rows = []
    for (dt,), g in panel.drop_nulls([*cols, "fwd_ret"]).group_by(["dt"], maintain_order=True):
        if g.height < len(signals) + 2:  # need more names than factors to identify betas
            continue
        x = np.column_stack([np.ones(g.height), *[g[c].to_numpy() for c in cols]])
        beta = np.linalg.lstsq(x, g["fwd_ret"].to_numpy(), rcond=None)[0]
        rows.append({"dt": dt, "market": beta[0]} | dict(zip(signals, beta[1:], strict=True)))
    # Explicit schema so a date range with too few names returns empty, not column-less.
    schema = {"dt": pl.Date, "market": pl.Float64} | dict.fromkeys(signals, pl.Float64)
    return pl.DataFrame(rows, schema=schema).sort("dt")


def covariance(rets: pl.DataFrame, signals: list[str] = SIGNALS) -> np.ndarray:
    """Factor covariance.

    ponytail: sample covariance. With 3 factors and ~2000 observations it is well
    conditioned; switch to Ledoit-Wolf shrinkage when the factor count approaches the
    number of observations.
    """
    return np.cov(rets.select(signals).drop_nulls().to_numpy(), rowvar=False)


def build(method: str = "mean") -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Read prices, publish the factor panel and factor returns, return (panel, rets, ic)."""
    scored = zscore(compute_signals(read_delta("prices_daily")))
    panel = add_alpha(scored, trailing_ic(scored, method=method))
    rets = factor_returns(panel)

    write_delta(
        panel.with_columns(pl.col("dt").dt.year().cast(pl.Int32).alias("year")),
        TABLE,
        partition_by=["year"],
    )
    write_delta(rets, RETURNS_TABLE)
    return panel, rets, information_coefficient(panel)
