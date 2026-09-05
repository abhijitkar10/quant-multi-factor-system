"""Phase 3 — risk model, portfolio construction, costs, and the backtest.

The risk model is the reason the factor structure exists. Measuring how every stock moves
with every other stock needs n(n-1)/2 covariances — hopeless to estimate from finite
history. Expressing each stock as exposures to k factors collapses it to::

    V = B F B' + diag(d)

where B is the exposure matrix (our z-scores), F the k x k factor covariance, and d each
name's specific variance. That is the whole "980,000 numbers becomes 2,000" argument, and
it is what makes V computable at all.

Construction then balances return against that risk, and implementation subtracts as
little value as possible on the way to the target.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from qmf.factors import RETURNS_TABLE, SIGNALS, TABLE, covariance
from qmf.storage import read_delta

REBALANCE_DAYS = 21
COST_BPS = 3.0  # 1bp commission + 2bp half-spread, charged on notional traded
MAX_WEIGHT = 0.05
TRADING_DAYS = 252


def specific_risk(
    panel: pl.DataFrame, rets: pl.DataFrame, signals: list[str] = SIGNALS
) -> pl.DataFrame:
    """Residual variance per name, once the common factor return is stripped out.

    Even for a stock that tracks its sector tightly, this idiosyncratic piece is a large
    share of total movement — stocks are more individual than they look.
    """
    factor_rets = rets.select(["dt", "market", *signals]).rename(
        {"market": "fret_market"} | {s: f"fret_{s}" for s in signals}
    )
    joined = panel.join(factor_rets, on="dt", how="inner")
    predicted = pl.col("fret_market")
    for s in signals:
        predicted = predicted + pl.col(f"z_{s}") * pl.col(f"fret_{s}")
    return (
        joined.with_columns((pl.col("fwd_ret") - predicted).alias("residual"))
        .group_by("ticker")
        .agg(pl.col("residual").var().alias("specific_var"))
        .drop_nulls()
    )


def stock_covariance(exposures: np.ndarray, factor_cov: np.ndarray, spec_var: np.ndarray):
    """V = B F B' + diag(d)."""
    return exposures @ factor_cov @ exposures.T + np.diag(spec_var)


def target_weights(
    alpha: np.ndarray, cov: np.ndarray, *, max_weight: float = MAX_WEIGHT, max_iter: int = 100
):
    """Risk-aware weights: dollar-neutral, gross exposure 1, position-capped.

    ponytail: w = V^-1 alpha projected onto the constraint set by iterating
    demean -> renormalise -> cap to a fixed point, rather than solved jointly. The
    constraints do hold, but this is the unconstrained optimum nudged into the feasible
    set, not the constrained optimum. Move to a cvxpy QP when turnover or sector-neutrality
    constraints are added, since those cannot be projected this way.
    """
    w = np.linalg.solve(cov, alpha)
    for _ in range(max_iter):
        w -= w.mean()  # dollar neutral
        gross = np.abs(w).sum()
        if gross:
            w /= gross  # gross exposure 1
        capped = np.clip(w, -max_weight, max_weight)
        if np.allclose(capped, w):
            # Return the capped vector, not w: allclose converges to a tolerance, and a
            # position limit is a hard constraint that must not breach even by 1e-6.
            return capped
        w = capped
    # Did not converge: max_weight * n < 1 makes gross 1 infeasible. Honour the cap and
    # accept the smaller book rather than quietly breaching the position limit.
    return w


def _wide(frame: pl.DataFrame, values: str, tickers: list[str]) -> np.ndarray:
    """Pivot a long panel to a dates x tickers matrix with a fixed column order."""
    wide = frame.pivot(on="ticker", index="dt", values=values).sort("dt")
    missing = [t for t in tickers if t not in wide.columns]
    if missing:
        wide = wide.with_columns([pl.lit(None, dtype=pl.Float64).alias(t) for t in missing])
    return wide.select(tickers).to_numpy()


def backtest(
    panel: pl.DataFrame,
    rets: pl.DataFrame,
    prices: pl.DataFrame,
    *,
    rebalance: int = REBALANCE_DAYS,
    cost_bps: float = COST_BPS,
    max_weight: float = MAX_WEIGHT,
) -> tuple[pl.DataFrame, dict]:
    """Hold target weights between rebalances; charge costs on the notional traded.

    ponytail: weights are held fixed between rebalance dates rather than drifting with
    returns, and costs are linear in turnover. Market impact is deliberately absent — it is
    a function of participation rate, and this book has no capital base to be a fraction of.
    Add both when the backtest is sized to real notional.
    """
    daily = prices.sort(["ticker", "dt"]).with_columns(
        (pl.col("adj_close") / pl.col("adj_close").shift(1) - 1).over("ticker").alias("ret")
    )
    tickers = sorted(set(panel["ticker"].unique()) & set(daily["ticker"].unique()))
    dates = panel.select("dt").unique().sort("dt")["dt"].to_list()

    aligned = panel.filter(pl.col("ticker").is_in(tickers))
    alpha_m = _wide(aligned, "alpha", tickers)
    expo_m = np.stack([_wide(aligned, f"z_{s}", tickers) for s in SIGNALS], axis=-1)
    ret_m = _wide(
        daily.filter(pl.col("ticker").is_in(tickers)).select(["ticker", "dt", "ret"]),
        "ret",
        tickers,
    )

    # f(t) is the factor return realised over (t -> t+1), so the move on day i is
    # explained by f(i-1) applied to the exposures the book had at the close of i-1.
    fret_m = pl.DataFrame({"dt": dates}).join(rets, on="dt", how="left").select(SIGNALS).to_numpy()
    factor_cov = covariance(rets)
    spec = specific_risk(panel, rets)
    spec_map = dict(zip(spec["ticker"], spec["specific_var"], strict=True))
    spec_var = np.array([spec_map.get(t, np.nan) for t in tickers])

    w = np.zeros(len(tickers))
    rows = []
    for i, d in enumerate(dates):
        # Today's return is earned by the weights we were already holding. Rebalancing
        # happens at today's close using today's alpha, so the new book only starts
        # earning tomorrow — setting weights and collecting the same day's return would
        # be look-ahead, which is the exact bias this system is built to avoid.
        r = float(np.nansum(w * np.nan_to_num(ret_m[i])))

        # Attribution: how much of today's move came from the factor bets we meant to
        # make, and how much is specific -- the part that is either skill or noise.
        contrib = np.zeros(len(SIGNALS))
        if i:
            exposure = w @ np.nan_to_num(expo_m[i - 1])
            contrib = exposure * np.nan_to_num(fret_m[i - 1])

        turnover = 0.0
        if i % rebalance == 0:
            a, b = alpha_m[i], expo_m[i]
            ok = np.isfinite(a) & np.isfinite(b).all(axis=1) & np.isfinite(spec_var)
            if ok.sum() > len(SIGNALS) + 1:
                cov = stock_covariance(b[ok], factor_cov, spec_var[ok])
                target = np.zeros(len(tickers))
                target[ok] = target_weights(a[ok], cov, max_weight=max_weight)
                turnover = float(np.abs(target - w).sum())
                w = target

        cost = turnover * cost_bps / 1e4
        rows.append(
            {"dt": d, "gross": r, "cost": cost, "net": r - cost, "turnover": turnover}
            | {f"attr_{s}": float(c) for s, c in zip(SIGNALS, contrib, strict=True)}
            | {"attr_specific": r - float(contrib.sum())}
        )

    curve = pl.DataFrame(rows).sort("dt")
    return curve, summarise(curve, rebalance)


def attribution(curve: pl.DataFrame, signals: list[str] = SIGNALS) -> dict:
    """Annualised split of the gross return into factor bets plus a specific residual.

    By construction the parts sum back to gross -- that identity is the check that the
    exposure and factor-return indices are lined up rather than off by a day.
    """
    parts = {s: curve[f"attr_{s}"].mean() * TRADING_DAYS for s in signals}
    parts["specific"] = curve["attr_specific"].mean() * TRADING_DAYS
    return parts


def summarise(curve: pl.DataFrame, rebalance: int = REBALANCE_DAYS) -> dict:
    """Information ratio and the cost that separates the paper book from the real one."""
    net = curve["net"].to_numpy()
    gross = curve["gross"].to_numpy()
    vol = net.std(ddof=1) * np.sqrt(TRADING_DAYS)
    ann_net = net.mean() * TRADING_DAYS
    equity = np.cumprod(1 + net)
    return {
        "ann_return_net": ann_net,
        "ann_return_gross": gross.mean() * TRADING_DAYS,
        "ann_vol": vol,
        "information_ratio": ann_net / vol if vol else 0.0,
        # Paper portfolio minus real portfolio: the total cost of implementation.
        "implementation_shortfall": (gross.mean() - net.mean()) * TRADING_DAYS,
        "ann_turnover": curve["turnover"].sum() / len(curve) * TRADING_DAYS,
        "max_drawdown": float((equity / np.maximum.accumulate(equity) - 1).min()),
        "days": len(curve),
    } | {f"from_{k}": v for k, v in attribution(curve).items()}


def run(**kwargs) -> tuple[pl.DataFrame, dict]:
    """Backtest straight off the lake."""
    panel = read_delta(TABLE)
    rets = read_delta(RETURNS_TABLE)
    prices = read_delta("prices_daily").select(["ticker", "dt", "adj_close"])
    return backtest(panel, rets, prices, **kwargs)
