# Reference data

## `universe_seed.csv`

A **hand-seeded, approximate** membership file used to bootstrap the point-in-time universe
(Phase 0). Columns:

| column | meaning |
|---|---|
| `ticker` | exchange ticker |
| `name` | company name |
| `sector` | GICS-style sector label |
| `added` | date the name entered our tradable universe |
| `removed` | date it left (empty = still a member) |

**This is not authoritative index membership.** Most `added` dates are a `2015-01-01`
baseline rather than real S&P 500 addition dates. Three names carry real removal events
(TWTR, FRC, SBNY) so the point-in-time logic and the survivorship-bias problem are
exercised by actual data rather than only described.

Because the file has `added`/`removed` windows, `universe_as_of(date)` returns what was
tradable **on that date** — a backtest starting in 2021 will correctly include TWTR and
correctly drop it after 2022-11-08.

## Superseded

**This seed is no longer the default.** `qmf universe --rebuild` now reconstructs real
point-in-time membership from Wikipedia's *revision history* — see
`src/qmf/data/constituents.py`. It fetches the constituents page as it existed on a grid of
past dates, so the universe is evidence about who was actually in the index then, including
~200 names that have since left. That is 700 tickers instead of 43, and it removes the
selection bias this seed could never escape.

The seed is kept for offline runs and tests: `qmf universe --rebuild --source seed`. It
writes the same `ticker/added/removed` interval schema, which is why swapping the source
changed nothing downstream.
