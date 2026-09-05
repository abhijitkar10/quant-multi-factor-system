"""Signals, scoring, and the cross-sectional regression."""

from datetime import date, timedelta

import numpy as np
import polars as pl

from qmf.factors import (
    add_alpha,
    covariance,
    daily_ic,
    factor_returns,
    information_coefficient,
    trailing_ic,
    zscore,
)

SIGNALS = ["momentum", "reversal", "low_vol"]


def panel(n_names: int = 8, n_dates: int = 5, seed: int = 0) -> pl.DataFrame:
    """A panel where fwd_ret is exactly 2x the momentum signal, nothing else."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        mom = rng.normal(size=n_names)
        z = (mom - mom.mean()) / mom.std(ddof=1)  # polars .std() is sample std
        for i in range(n_names):
            rows.append(
                {
                    "ticker": f"T{i}",
                    "dt": date(2024, 1, 1) + timedelta(days=d),
                    "momentum": float(mom[i]),
                    "reversal": float(rng.normal()),
                    "low_vol": float(rng.normal()),
                    "fwd_ret": float(2.0 * np.clip(z[i], -3, 3)),
                }
            )
    return pl.DataFrame(rows)


def test_zscore_is_standardised_within_each_date():
    scored = zscore(panel())
    stats = scored.group_by("dt").agg(
        pl.col("z_momentum").mean().alias("mu"), pl.col("z_momentum").std().alias("sd")
    )
    assert np.allclose(stats["mu"].to_numpy(), 0, atol=1e-9)
    assert np.allclose(stats["sd"].to_numpy(), 1, atol=1e-9)


def test_zscore_winsorises_at_three_sigma():
    df = panel()
    # One absurd outlier must not blow past the clip.
    df[0, "momentum"] = 1e6
    scored = zscore(df)
    assert scored["z_momentum"].abs().max() <= 3.0 + 1e-9


def test_alpha_is_the_mean_of_the_scores():
    scored = add_alpha(zscore(panel()))
    row = scored.row(0, named=True)
    expected = np.mean([row[f"z_{s}"] for s in SIGNALS])
    assert abs(row["alpha"] - expected) < 1e-12


def test_perfectly_predictive_signal_scores_ic_of_one():
    ic = information_coefficient(zscore(panel())).row(0, named=True)
    assert ic["momentum"] > 0.99  # fwd_ret is a monotone function of momentum
    assert abs(ic["reversal"]) < 0.9  # noise signals should not


def test_regression_recovers_the_true_coefficient():
    """fwd_ret was built as 2 x z_momentum, so the fitted loading must come back as 2."""
    rets = factor_returns(zscore(panel()))
    assert rets.height == 5
    assert np.allclose(rets["momentum"].to_numpy(), 2.0, atol=1e-6)
    assert np.allclose(rets["reversal"].to_numpy(), 0.0, atol=1e-6)


def test_dates_with_too_few_names_are_skipped():
    # 4 names cannot identify 3 factors plus an intercept.
    assert factor_returns(zscore(panel(n_names=4))).height == 0


def test_covariance_is_square_and_symmetric():
    cov = covariance(factor_returns(zscore(panel(n_dates=40, seed=1))))
    assert cov.shape == (3, 3)
    assert np.allclose(cov, cov.T)


def test_trailing_ic_never_sees_its_own_date():
    """Date t's weight must be built only from ICs measured strictly before t."""
    scored = zscore(panel(n_dates=12))
    daily = daily_ic(scored).drop_nulls()
    weights = trailing_ic(scored, min_obs=3)

    row = weights.filter(pl.col("dt") == daily["dt"][5]).row(0, named=True)
    expected = daily["momentum"][:5].mean()  # first five dates only, not the sixth
    assert abs(row["w_momentum"] - expected) < 1e-12


def test_trailing_ic_withholds_weights_until_enough_evidence():
    scored = zscore(panel(n_dates=12))
    weights = trailing_ic(scored, min_obs=8)
    assert weights["w_momentum"].null_count() >= 8


def test_negative_ic_signal_is_held_short():
    """A signal that has been paid negatively should flip sign, not just get downweighted."""
    scored = zscore(panel(n_dates=3))
    w = pl.DataFrame(
        [
            {"dt": d, "w_momentum": 1.0, "w_reversal": 0.0, "w_low_vol": -1.0}
            for d in sorted(scored["dt"].unique())
        ]
    )
    out = add_alpha(scored, w).row(0, named=True)
    expected = (out["z_momentum"] - out["z_low_vol"]) / 2.0
    assert abs(out["alpha"] - expected) < 1e-12
