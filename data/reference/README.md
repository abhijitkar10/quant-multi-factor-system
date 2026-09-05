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

**Phase 5 upgrade:** replace this seed with a real point-in-time constituent source
(e.g. a licensed index membership file or a scraped, dated Wikipedia revision history)
and keep the same schema — nothing downstream needs to change.
