# Multi-Factor Equity Trading System

Recreates the institutional **multi-factor trading architecture** described in the video
*"What Nobody Tells You About Being a Quant"* (The Quant Insider) as a solo, laptop-scale
project — a data-engineering + quant-finance portfolio piece.

**Status:** Phases 0–3 built and running. 49 tests passing, 9 dependencies.
Latest backtest: **IR 0.66**, 5.65% net annualised (2018→2026, 41 names).

## Quickstart

```bash
uv sync --all-groups
uv run qmf phase1
```

Individual steps:

```bash
uv run qmf universe --rebuild        # point-in-time tradable universe
uv run qmf ingest --start 2018-01-01 # daily prices -> Delta, with audit gate
uv run qmf match                     # tickers -> FIGI via OpenFIGI
uv run qmf status                    # every Delta table, version, row count
uv run qmf factors                   # signals -> alpha -> factor returns
uv run qmf backtest                  # construct, trade, score
uv run qmf point-in-time TWTR        # why membership needs a date
```

## Architecture

```
                    ┌─────────────┐
   Universe ───────▶│ DATA & SIGNALS│──┐ signals
   (point-in-time)  │ ingest·match │  │
                    │ ·audit·load  │  ▼
                    └─────────────┘ ┌──────┐
                                    │ ALPHA │─┐ expected return
                                    └──────┘ │
                    ┌─────────────┐          ├▶┌──────────────┐   ┌───────────────┐   ┌──────────────┐
                    │ RISK MODEL  │──────────┘ │  PORTFOLIO   │──▶│ IMPLEMENTATION│──▶│ PERFORMANCE  │
                    │ factor cov  │ risk        │ CONSTRUCTION │   │ & TRADING     │   │ ANALYSIS     │
                    └─────────────┘             │ (optimizer)  │   │ (cost model)  │   │ (attribution)│
                                                └──────────────┘   └───────────────┘   └──────┬───────┘
                                                                                              │ factors decay
  INFRASTRUCTURE: Spark / Delta Lake / cloud   STORAGE: Parquet+Delta (batch) · KDB (live) ◀──┘ feeds research
```

## What is built

| Phase | Status | Where |
|---|---|---|
| 0 — point-in-time universe | **done** | `src/qmf/universe.py` |
| 1 — data loaders | **done** | `src/qmf/data/prices.py` |
| 1b — security matching (OpenFIGI) | **done** | `src/qmf/data/security_master.py` |
| 1c — data auditing | **done** | `src/qmf/data/audit.py` |
| storage — Delta Lake + time travel | **done** | `src/qmf/storage.py` |
| 2 — signals / alpha / factor returns | **done** | `src/qmf/factors.py` |
| 3 — risk model / construction / costs / backtest | **done** | `src/qmf/portfolio.py` |
| 4 — performance attribution | planned | — |
| 5–6 — Spark, cloud, kdb+ | planned | — |

Current lake after a full `phase1` run: 87,756 price rows across 41 names (2018→today),
a 43-name universe with real membership intervals, and a 100%-matched security master.

## Docs
- [Feature plan](docs/feature-plan.md) — architecture, phased roadmap, scope, interview map
- [Tech stack](docs/tech-stack.md) — tools per block
- [Build log](docs/build-log.md) — what was built, decisions, and what real data broke
- [Reading list](docs/reading-list.md) — the books

## The one book to read first
**Active Portfolio Management** — Grinold & Kahn. The source of the whole skeleton: alpha,
the information ratio, the fundamental law, factor risk models, portfolio construction,
costs, and performance analysis. For the engineering half (Parquet, Delta, Spark, kdb+),
the companion is **Designing Data-Intensive Applications** by Kleppmann.
See [reading-list.md](docs/reading-list.md).
