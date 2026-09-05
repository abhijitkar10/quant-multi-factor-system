# Build log

## 2026-09-05 — Phases 0 and 1

Scaffolded the repo and built the data block end to end. `uv run qmf phase1` now runs
universe → prices → security matching → lake status, with an audit gate in the middle.

### What exists

| Module | Role |
|---|---|
| `qmf.config` | pydantic-settings; `QMF_`-prefixed env overrides so the same code runs local or on S3 |
| `qmf.storage` | Delta read/write, versions, history, time travel |
| `qmf.universe` | point-in-time membership intervals |
| `qmf.data.loaders.base` | the loader contract: fetch → transform → audit → write |
| `qmf.data.loaders.prices` | yfinance daily bars → tidy long panel |
| `qmf.data.security_master` | OpenFIGI ticker → FIGI, SCD-2 shaped |
| `qmf.data.audit` | statistical checks with critical/non-critical severity |
| `qmf.cli` | typer CLI |

31 tests, ruff clean.

### Design decisions worth defending in an interview

**Audit runs before the write, not after.** Auditing a published table means every
downstream factor has already seen the bad data by the time anyone notices. A failing
*critical* check raises `DataAuditError` and the table is never written — the feed halts
instead of propagating. Non-critical checks (return outliers) warn without blocking, since
real markets do produce genuine 50% moves.

**Partition by year, not by date.** The obvious reading of "partition by date" gives ~3,900
directories of tiny files over 15 years × 500 names. The metadata overhead of the
small-file problem costs more than the extra partition pruning saves at this scale. Year
partitions keep files in a sensible size range and date filters still prune well.

**Membership is an interval, not a list.** `universe_as_of(d)` resolves `added <= d <
removed`. Asking "what is in the universe" without a date is the single easiest way to
introduce survivorship bias. `tickers_active_between(start, end)` is deliberately separate:
ingestion must cover names that have *since* disappeared, or the backtest silently only
ever sees survivors.

**FIGI is the key, ticker is an attribute.** Tickers get reused and reassigned; FIGI does
not. The security master is kept in SCD-2 shape (`valid_from`/`valid_to`) so a mapping is
read as of a date rather than as "what is true today".

### What real data broke (both genuinely useful findings)

**1. Vendor ticker conventions disagree.** The first matching run came back 97.5%, with one
failure: `BRK-B`. yfinance writes share classes with a dash; OpenFIGI and Bloomberg write
`BRK/B`. Neither is wrong — they are different conventions for the same security, which is
exactly why matching needs a translation layer rather than a string join. Fixed with a
convention cascade: try OpenFIGI's spelling, retry anything unresolved with the ticker as
we hold it. Match rate went to 100%.

This is also a clean demonstration of Delta time travel — `security_master` version 0 has
`BRK-B` unmatched and version 1 has it resolved, same table, same path:

```
security_master BEFORE the fix (version 0):  unmatched: ['BRK-B']
security_master AFTER  the fix (version 1):  unmatched: []
```

**2. The coverage audit caught real survivorship bias.** Ingesting 2018→today for all 43
seeded names returned only 41: yfinance has no history for `FRC` (First Republic, failed
2023) or `TWTR` (acquired 2022). The audit flagged them by name at 95.35% coverage. That is
a true positive, not a bug — it is the vendor telling us its history has been rewritten to
exclude companies that stopped existing, which is precisely the bias the point-in-time
universe is designed to expose. Left visible rather than papered over.

### Next
Phase 2 — signal library, alpha refinement, cross-sectional factor returns, and a
Ledoit-Wolf shrunk factor covariance. See [feature-plan.md](feature-plan.md).

## 2026-09-06 — ponytail audit applied, then Phase 2

### Cuts (audit findings applied before adding anything)
Deleted the six phase-stub modules (121 lines of prose in `.py` clothing), the `Loader` ABC
with its single implementation, the `loaders/` package and its re-export facade, `LoadResult`,
the `halt_on_audit_failure` flag nobody set, `read_delta`'s unused `as_of`/`columns` params,
`security_master_as_of`, `settings.raw`, the `WriteMode` alias, `identity_ticker`, `_today()`,
and `__version__`.

Replaced with stdlib/native: `itertools.batched` for the hand-rolled OpenFIGI batching loop,
`DeltaTable.is_deltatable` for the try/except existence check, `str` for `identity_ticker`,
and plain module constants + `os.environ` for the pydantic-settings class.

Dependencies: **13 → 9**. Dropped duckdb, pandera, scipy, statsmodels, scikit-learn, pydantic,
pydantic-settings (all declared, none imported), plus four speculative optional-dep groups.
`prices.py` became three functions instead of a class hierarchy.

### Phase 2 — signals, alpha, factor returns
One module, `qmf/factors.py`. Signals come from the price panel only: 12-1 momentum,
one-month reversal, and trailing 60-day low-volatility. Value/size/quality need fundamentals
we do not load, so they are not there yet.

Each signal is z-scored cross-sectionally per date and winsorised at ±3; alpha is the
equal-weight mean. Factor returns come from a per-date cross-sectional OLS of next-day
return on the scores, and the factor covariance is the sample covariance.

Two deliberate simplifications, both marked `ponytail:` in the source:
- **Equal weights, not IC weights.** Weight by IC once there is a measured IC to weight by.
- **Sample covariance, not Ledoit-Wolf.** With 3 factors and ~1,900 observations it is well
  conditioned. Shrinkage earns its place when the factor count approaches the observation
  count, not before.

### First real result (2018→2026, 41 names)

| signal | mean daily IC | factor return (ann.) | factor vol (ann.) |
|---|---|---|---|
| momentum | +0.0227 | +7.72% | 11.58% |
| reversal | +0.0015 | +0.24% | 9.53% |
| low_vol | −0.0096 | −7.61% | 13.07% |

Only momentum carries information, and an IC of 0.023 is a realistic number — published
equity signals live around 0.02–0.05, so this is neither broken nor too good to be true.
Reversal is indistinguishable from noise. Low-vol is *negatively* paid over this window,
which is what you would expect from a 41-name mega-cap universe across a growth-led bull
market: the high-beta names led. None of this is a bug; it is the sample telling the truth.

### Bug found by the tests
`factor_returns` crashed on an empty result — `pl.DataFrame([])` has no columns, so `.sort("dt")`
raised `ColumnNotFoundError`. Fixed with an explicit schema. The test that caught it was the
one asserting dates with fewer names than factors get skipped.

### Next
Phase 3 — portfolio construction (cvxpy) and the transaction-cost model.

## 2026-09-06 (later) — Phase 3: risk model, construction, costs, backtest

One module, `qmf/portfolio.py`. No cvxpy: at 41 names a 41x41 solve is one numpy line, so
the dependency has not earned its place yet.

- **Risk model.** `V = B F B' + diag(d)` — exposures (the z-scores) times factor covariance,
  plus specific variance from the regression residuals. This is the "980,000 numbers becomes
  2,000" argument made concrete.
- **Construction.** `w = V^-1 alpha`, projected onto the constraint set by iterating
  demean → renormalise → cap to a fixed point. Dollar-neutral, gross 1, 5% position cap.
- **Costs.** Linear: 1bp commission + 2bp half-spread on notional traded. Market impact is
  deliberately absent — it is a function of participation rate, and a unit-notional book has
  no capital base to be a fraction of.
- **Backtest.** Monthly rebalance, weights held between dates, implementation shortfall
  measured as paper-minus-real.

### Three bugs, all caught by tests or by reading the result

**1. Look-ahead in the backtest loop.** Weights set at date `i` were collecting date `i`'s
own return. Fixed by accruing the day's return on the weights already held, *then*
rebalancing at the close. The correction was material:

| | IR | gross (ann.) | max DD |
|---|---|---|---|
| with look-ahead | −0.60 | −3.58% | −33.86% |
| corrected | −0.02 | +0.24% | −19.46% |

**2. `specific_risk` depended on a join *suffix*** that only appears when column names
happen to collide. It worked on the real panel and broke on a synthetic one. Renamed the
factor-return columns explicitly instead of relying on incidental overlap.

**3. The position cap did not cap.** Clip-then-renormalise let the largest weight drift back
above `max_weight`, and even after fixing that, returning the pre-clip vector on
`np.allclose` convergence breached the limit by ~1e-6. A position limit is a hard
constraint; it now returns the clipped vector.

### IC weighting — added because the data asked for it
The equal-weight alpha earned an IR of −0.02, which is exactly what you would predict from
blending momentum (IC +0.023) with a dead signal and a negatively-paid one. That was the
trigger condition named in the previous entry, so signals are now weighted by their measured
IC — using an **expanding-window IC lagged one day**, with no weights at all until 252 days
of evidence exist. Weighting by full-sample IC would be in-sample fitting: telling the
backtest which signals worked using the very returns it is about to trade.

| | IR | net (ann.) | turnover | max DD |
|---|---|---|---|---|
| equal weights | −0.02 | −0.13% | 1249% | −19.46% |
| trailing-IC weights | **+0.66** | **+5.65%** | 533% | −11.27% |

Turnover more than halved as well: IC weights are steadier than an equal blend of three
noisy signals.

### Is 0.66 believable?
The fundamental law says IR ≈ IC × √breadth. With IC 0.023 and breadth ≈ 41 names × 12
rebalances ≈ 492, that predicts IR ≈ 0.023 × 22 ≈ 0.51. Observed 0.66 is the same order —
close enough to be consistent with theory rather than a bug, and far from the implausible
numbers that signal a leak.

**Caveats worth stating before this goes on a CV:** the 43-name seed universe is hand-picked
and dominated by names that are large *today*, so the universe itself carries selection bias
that no amount of point-in-time membership logic can remove. It is one sample period, and
the choice of which three signals to build was made by someone who already knew momentum
works in equities. The pipeline is honest; the experiment is still small.

### Next
Phase 4 proper — return attribution (factor vs specific vs cost). Phase 5 — Spark/Delta at
scale. A real point-in-time constituent source would do more for credibility than either.

## 2026-09-06 (later still) — published, then Phase 4: attribution

Repo is public: https://github.com/abhijitkar10/quant-multi-factor-system

Attribution folded into the existing backtest loop rather than a new module. Each day the
book's factor exposure is `x(t) = w . B(t)`, and the contribution of factor k to the move
realised over `(t -> t+1)` is `x_k(t) * f_k(t)`. Whatever gross return is left over is the
specific part.

The indexing is the whole difficulty: `f(t)` comes from regressing `fwd_ret(t)` on `z(t)`,
so it explains the return realised on day `t+1`, and the exposures it multiplies must be the
ones the book actually held at the close of `t`. Getting that off by one day would silently
manufacture or destroy performance, so the test asserts the identity
`sum(factor contributions) + specific == gross` exactly.

### Where the 5.81% gross came from

| source | ann. contribution |
|---|---|
| momentum | +4.61% |
| low_vol | +1.31% |
| reversal | +0.39% |
| specific | −0.49% |
| **gross** | **+5.81%** |

Momentum is 79% of the return, which matches its being the only signal with a real IC.

Low-vol contributing **positively** is the IC weighting doing its job: the signal was paid
−0.0096, so the trailing-IC weight holds it short, and a negatively-paid factor held short
is a positive contribution. That is the difference between the equal-weight blend (IR −0.02)
and this one (IR 0.66) shown at the factor level.

Specific is ≈0 and slightly negative, which is the correct result rather than a
disappointing one: the alpha is built purely from factor scores, so there is no
name-specific view in it, and there should be no name-specific return. A large positive
specific number here would have been a red flag that something was leaking.

### Next
Phase 5 — Spark/Delta at scale. Still true that a real point-in-time constituent source
would buy more credibility than any further modelling.

## 2026-09-06 (final) — real universe, and the result it destroyed

### The universe is now evidence, not hindsight
`qmf universe --rebuild` reconstructs membership from Wikipedia's **revision history**:
fetch the constituents page as it existed on a quarterly grid of past dates, and contiguous
runs of snapshots become membership intervals.

43 hand-picked names → **700 tickers, 703 intervals**. 503 still members, 200 departed,
3 that left and rejoined. ~505 members at any past date, which matches the index's true
count once dual share classes (GOOG/GOOGL, FOX/FOXA) are counted.

The first attempt indexed page tables by position and broke immediately — Wikipedia has
since deleted the change-log table entirely. Tables are now located by content.

### The ingest halted, and the diagnosis mattered more than the fix
703 tickers, 99 failed downloads, coverage 86%, feed halted. Some failures looked wrong —
MMC and BK trade daily — so throttling seemed likely. It was not:

- a control ticker fetched fine → not rate-limited
- clearing yfinance's timezone cache changed nothing → not a stale cache
- the vendor returns an explicit `404 Quote not found`

Then the measurement that settled it: **all 99 failures are names the universe says left the
index; zero current members failed.** The suspicion was wrong because the corporate actions
happened after the author's knowledge cutoff — the data knew, memory did not.

So the check was measuring the wrong thing: gating on history a free vendor cannot serve for
companies that no longer exist. Coverage now gates on names still in the index; departed
names get a non-critical `delisted_coverage` check. Not a relaxed threshold — a missing
*current* name still halts the feed, and a test pins that.

Ingest now: **1,239,426 rows**, coverage 100%, delisted coverage 49.7% (98 of 197 departed
names have history, 99 do not).

### The honest result

| | 41 hand-picked names | 604 real point-in-time names |
|---|---|---|
| information ratio | **0.66** | **0.02** |
| net return (ann.) | +5.65% | +0.15% |
| turnover (ann.) | 533% | 1084% |
| max drawdown | −11.27% | −15.00% |

**The IR of 0.66 was survivorship bias.** A universe of 41 companies that are large *today*
is selected on outcome, and it flattered the strategy by roughly the entire result. On a
universe chosen without hindsight the edge is indistinguishable from zero.

Signal ICs on the real universe: momentum +0.0202 (holds up), reversal +0.0072 (improved,
more names means more cross-sectional dispersion), low_vol +0.0007 (was −0.0096; now
indistinguishable from noise).

Attribution of the +0.48% gross: momentum +2.43%, reversal +0.83%, low_vol −1.46%,
specific −1.32%. Momentum still earns; low_vol now *destroys* value because its IC sits at
zero, so the trailing-IC weight is fitting noise and flipping sign on it.

### What this is worth
This is the most valuable thing the project has produced. A pipeline that reports IR 0.66 on
a rigged universe is worse than useless — it is confidently wrong. The same pipeline
reporting 0.02 on an honest one is a working instrument. The system did not get worse; the
measurement got truthful.

Deliberately **not** tuned afterwards. Dropping low_vol, or weighting by an IC t-statistic
instead of a raw IC, would very likely lift the number — and doing that after seeing the
result is how backtests get overfitted. Recorded as a hypothesis to test properly, not a
change to make now.

Remaining honest limitation: the universe is free of survivorship bias but the price history
is not, because 99 departed names have no history to load. The free vendor is now the
binding constraint, not the universe.

## 2026-09-06 — testing the t-stat hypothesis (rejected)

The previous entry logged a hypothesis: weighting signals by a raw trailing IC fits noise
when that IC sits at zero, so weighting by an IC *t-statistic* — the mean IC divided by its
standard error — should suppress noise signals and lift the result.

Since the idea was formed **after** seeing the result, the protocol was declared before
running anything: in-sample 2018–2022, held out from 2023-01-01, and both rules reported on
both windows regardless of which won.

| weighting | full 2018→2026 IR | held out 2023+ IR | held-out turnover |
|---|---|---|---|
| mean IC | 0.02 | **0.33** | 1336% |
| IC t-stat | 0.02 | **0.32** | 1396% |

**The hypothesis is rejected.** T-stat weighting changed nothing — 0.32 against 0.33, with
slightly higher turnover. The prediction that it "would very likely lift the number" was
wrong.

In hindsight the reason is visible: `add_alpha` normalises by the sum of weight magnitudes,
so only the *relative* ordering of the three signals matters, and momentum has both the
largest IC and the most consistent one. It wins under either rule, and rescaling the other
two barely moves a normalised blend of three signals. The t-statistic would start to matter
with many more signals, or with two of comparable mean IC and very different consistency —
which is exactly the case the unit test constructs, and where it does separate them cleanly.

### The more interesting number is the one that is not about weighting
Both rules score IR ≈ 0.02 over the full period and ≈ 0.33 over 2023 onward. That gap is a
**period effect, not skill**: these signals simply paid better in the back half of the
sample. Quoting the 0.33 alone would be picking a window after seeing the answer, which is
the same error as picking a universe after seeing the answer — the mistake this project
already made once and corrected.

So the standing result is unchanged: on an honest universe the edge is weak and
period-dependent.

### On keeping the losing code
`--weighting tstat` stays, defaulting to `mean`. It is not speculative scaffolding: it is the
apparatus that produced a documented negative result, and deleting it would make that claim
unreproducible. Delete it if the finding ever stops mattering.
