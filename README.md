# Multi-Factor Equity Trading System

Recreates the institutional **multi-factor trading architecture** described in the video
*"What Nobody Tells You About Being a Quant"* (The Quant Insider) as a solo, laptop-scale
project — a data-engineering + quant-finance portfolio piece.

**Status:** Phases 0–4 built and running. 59 tests passing, 9 dependencies.

Universe is real point-in-time index membership reconstructed from Wikipedia revision
history — 700 tickers, 503 current and 200 departed — so the backtest is not run on names
selected with hindsight. Latest backtest over 604 names with price history:
**IR 0.02, +0.15% net annualised.**

That number was **0.66 on a hand-picked 41-name universe**. The difference was survivorship
bias, and finding it is the point: see [docs/build-log.md](docs/build-log.md).

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
| 0 — point-in-time universe | **done** | `src/qmf/universe.py`, `src/qmf/data/constituents.py` |
| 1 — data loaders | **done** | `src/qmf/data/prices.py` |
| 1b — security matching (OpenFIGI) | **done** | `src/qmf/data/security_master.py` |
| 1c — data auditing | **done** | `src/qmf/data/audit.py` |
| storage — Delta Lake + time travel | **done** | `src/qmf/storage.py` |
| 2 — signals / alpha / factor returns | **done** | `src/qmf/factors.py` |
| 3 — risk model / construction / costs / backtest | **done** | `src/qmf/portfolio.py` |
| 4 — performance attribution | **done** | `src/qmf/portfolio.py` |
| 5–6 — Spark, cloud, kdb+ | planned | — |

Current lake: 1,239,426 price rows across 604 names (2018→today), a 700-ticker
point-in-time universe, and a security master matched via OpenFIGI.

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
