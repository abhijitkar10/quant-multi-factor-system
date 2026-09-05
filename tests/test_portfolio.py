"""Risk model, weight construction, and the cost accounting."""

from datetime import date, timedelta

import numpy as np
import polars as pl

from qmf.portfolio import (
    backtest,
    specific_risk,
    stock_covariance,
    summarise,
    target_weights,
)

SIGNALS = ["momentum", "reversal", "low_vol"]


def test_weights_are_dollar_neutral():
    alpha = np.array([0.3, -0.1, 0.5, -0.4, 0.2])
    w = target_weights(alpha, np.eye(5), max_weight=1.0)
    assert abs(w.sum()) < 1e-12


def test_gross_exposure_is_one():
    alpha = np.array([0.3, -0.1, 0.5, -0.4, 0.2])
    w = target_weights(alpha, np.eye(5), max_weight=1.0)
    assert abs(np.abs(w).sum() - 1.0) < 1e-12


def test_position_cap_is_respected():
    alpha = np.array([10.0, -0.1, 0.1, -0.1, 0.1])  # one name wants to dominate
    w = target_weights(alpha, np.eye(5), max_weight=0.30)
    assert np.abs(w).max() <= 0.30 + 1e-9


def test_identity_risk_reduces_to_demeaned_alpha():
    """With V = I the optimum is just alpha, so weights must rank exactly like alpha."""
    alpha = np.array([0.3, -0.1, 0.5, -0.4, 0.2])
    w = target_weights(alpha, np.eye(5), max_weight=1.0)
    centred = alpha - alpha.mean()
    assert np.allclose(w, centred / np.abs(centred).sum())


def test_stock_covariance_is_the_factor_formula():
    b = np.array([[1.0, 0.0], [0.5, 1.0], [-1.0, 0.5]])
    f = np.array([[0.04, 0.01], [0.01, 0.09]])
    d = np.array([0.01, 0.02, 0.03])
    v = stock_covariance(b, f, d)
    assert np.allclose(v, b @ f @ b.T + np.diag(d))
    assert np.allclose(v, v.T)
    assert (np.linalg.eigvalsh(v) > 0).all()  # positive definite, so solvable


def _panel_and_rets(n_dates=40, tickers=("A", "B", "C", "D", "E", "F")):
    rng = np.random.default_rng(7)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_dates)]
    rows = []
    for d in dates:
        for t in tickers:
            z = {f"z_{s}": float(rng.normal()) for s in SIGNALS}
            rows.append(
                {
                    "ticker": t,
                    "dt": d,
                    **z,
                    "alpha": float(np.mean(list(z.values()))),
                    "fwd_ret": float(rng.normal(scale=0.01)),
                }
            )
    panel = pl.DataFrame(rows)
    rets = pl.DataFrame(
        [
            {"dt": d, "market": 0.0, **{s: float(rng.normal(scale=0.001)) for s in SIGNALS}}
            for d in dates
        ]
    )
    return panel, rets


def test_specific_risk_is_positive_for_every_name():
    panel, rets = _panel_and_rets()
    spec = specific_risk(panel, rets)
    assert spec.height == 6
    assert (spec["specific_var"] > 0).all()


def test_costs_open_a_gap_between_paper_and_real():
    curve = pl.DataFrame(
        {
            "dt": [date(2024, 1, 1), date(2024, 1, 2)],
            "gross": [0.01, 0.02],
            "cost": [0.001, 0.0],
            "net": [0.009, 0.02],
            "turnover": [1.0, 0.0],
            **{f"attr_{s}": [0.0, 0.0] for s in SIGNALS},
            "attr_specific": [0.01, 0.02],
        }
    )
    stats = summarise(curve)
    assert stats["implementation_shortfall"] > 0
    assert stats["ann_return_net"] < stats["ann_return_gross"]


def test_backtest_produces_a_curve_and_charges_only_on_rebalance():
    panel, rets = _panel_and_rets()
    prices = pl.DataFrame(
        [
            {"ticker": t, "dt": d, "adj_close": 100.0 + i}
            for t in ("A", "B", "C", "D", "E", "F")
            for i, d in enumerate(sorted(panel["dt"].unique()))
        ]
    )
    curve, stats = backtest(panel, rets, prices, rebalance=10)
    assert curve.height == 40
    assert {"dt", "gross", "cost", "net", "turnover"} <= set(curve.columns)
    assert (curve["cost"] >= 0).all()
    # Costs land only on rebalance days, not every day.
    assert (curve["turnover"] > 0).sum() <= 4


def test_rebalance_day_does_not_earn_its_own_return():
    """Weights set at today's close must not collect today's return — that is look-ahead."""
    panel, rets = _panel_and_rets(n_dates=5)
    dates = sorted(panel["dt"].unique())
    # Day 0 has a violent move; the book starts empty, so day 0 P&L must be exactly zero.
    prices = pl.DataFrame(
        [
            {"ticker": t, "dt": d, "adj_close": 100.0 * (10.0 if i == 1 else 1.0) ** 1}
            for t in ("A", "B", "C", "D", "E", "F")
            for i, d in enumerate(dates)
        ]
    )
    curve, _ = backtest(panel, rets, prices, rebalance=1)
    assert curve["gross"][0] == 0.0


def test_attribution_sums_back_to_gross():
    """Factor contributions plus the specific residual must reconstruct the gross return.

    This identity is what catches an off-by-one between exposures and factor returns.
    """
    panel, rets = _panel_and_rets(n_dates=30)
    prices = pl.DataFrame(
        [
            {"ticker": t, "dt": d, "adj_close": 100.0 + i * 0.5}
            for t in ("A", "B", "C", "D", "E", "F")
            for i, d in enumerate(sorted(panel["dt"].unique()))
        ]
    )
    curve, stats = backtest(panel, rets, prices, rebalance=5)
    parts = curve.select([f"attr_{s}" for s in SIGNALS] + ["attr_specific"]).sum_horizontal()
    assert np.allclose(parts.to_numpy(), curve["gross"].to_numpy(), atol=1e-12)
    assert "from_specific" in stats
