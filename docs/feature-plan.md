# Feature Plan — Multi-Factor Equity Trading System

## Source
Video: *What Nobody Tells You About Being a Quant* — The Quant Insider (~38 min)
<https://www.youtube.com/watch?v=tzTftCzmr7k>. The speaker walks through the systems
design of an institutional multi-factor trading system and notes it is "great for
implementing in your personal projects, and in turn a great talking point in interviews."

## What you're building
A research-to-production pipeline that takes raw + alternative data, turns it into
independent trading factors, combines them into a risk-aware portfolio, backtests it with
realistic costs, and reports skill vs. luck — mirroring the institutional architecture,
one block at a time. Scoped for one person, free/realistic substitutes for hedge-fund tooling.

## Target architecture (the "skeleton")

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

## Phased roadmap

> **Status (2026-09-05):** Phases 0 and 1 are built and running — see
> [build-log.md](build-log.md). Phase 2 is next.

| Phase | Goal | Key features | Maps to video |
|---|---|---|---|
| **0 — Foundation** | Scaffolding | Repo + module layout; **point-in-time universe** (e.g. S&P 500 historical membership, survivorship-bias-free); data-lake layout on Parquet/Delta | "define your universe first" |
| **1 — Data & Signals** | The block "the whole machine stands or falls on" | Per-source **data loaders**; **security matching** (ticker/URL → ISIN/CUSIP/FIGI, point-in-time valid); **data auditing** (coverage %, outlier/schema checks, threshold alerts); land in Delta partitioned by date | Security matching, data scrubbing, auditing |
| **2 — Factor model core** | Decompose returns into common + specific | Signal library (value, momentum, size, quality + 1 alt-data signal); **alpha refinement** (volatility × IC/skill × signal score); **factor returns** via cross-sectional regression; **risk model** (factor covariance + specific risk) | Multi-factor model, alpha, risk model |
| **3 — Construction & backtest** | Turn forecasts into trades | **Optimizer**: max return − risk penalty − tcost, s.t. constraints (sector-neutral, turnover, leverage, position limits); **transaction-cost model** (commission, spread, market impact); event-driven **backtester** | Portfolio construction, "subtract as little value as possible" |
| **4 — Performance analysis** | Separate skill from luck | Return **attribution** (factor vs. specific vs. cost); **information ratio**; **implementation shortfall**; fundamental-law check (IR ≈ skill × √breadth) | Performance analysis, the two key numbers |
| **5 — Infra & scale** | Make historical runs finish on time | **PySpark + Delta Lake** distributed historical run (5–15 yrs); broadcast-join for security matching (no shuffle); **time-travel** for point-in-time; scheduling | Cloud, Spark, Delta Lake |
| **6 — Live/time-series (stretch)** | High-speed time-series path | **KDB+** (free Personal Edition) or DuckDB/ArcticDB for tick storage + **as-of joins**; a daily "update window" job | KDB+, as-of join, HTCondor grid |

## Cross-cutting requirements (stressed in the video)
- **Point-in-time everything** — no look-ahead bias; use Delta time-travel so a backtest sees data *as it was known then*, not as restated.
- **Documentation as a first-class artifact** — one methodology doc per factor (the "central note"); also your interview script.
- **Auditing upstream** — fail fast: if a loader/audit breaks, halt the factor rather than trade on bad data.

## Non-goals (deliberate scope cuts)
Real-money trading / live broker connection · sub-millisecond HFT · 1,400-name universe
(start with ~100–500) · neural nets (video notes most real factors are regression /
gradient-boosted trees) · true distributed grid (single machine + Spark is plenty).

## First milestone (2–3 weekends)
Phases 0→1 end-to-end on ~50 tickers: pull daily prices, build a security master with
OpenFIGI matching, write a point-in-time Delta table, add a coverage audit. That slice
alone demonstrates DE fundamentals (idempotent loaders, schema enforcement, point-in-time,
data quality) and is a working talking point before the modeling starts.

## Interview talking-point map
| Concept you can speak to | Where it lives in the project |
|---|---|
| Look-ahead bias & point-in-time data | Security matching + Delta time-travel (Phases 1, 5) |
| Why factors, not stock-to-stock covariance (~1M → ~2k numbers) | Risk model (Phase 2) |
| Diversifiable vs. systematic risk, CAPM/APT | Risk model (Phase 2) |
| Fundamental law: IR ≈ skill × √breadth | Performance analysis (Phase 4) |
| Implementation shortfall & market impact | Cost model + backtest (Phase 3) |
| Spark partitions / shuffle / broadcast join | Distributed run (Phase 5) |
| Columnar storage, Parquet, Delta ACID & time-travel | Storage layer (Phases 1, 5) |
| KDB as-of join for tick data | Live path (Phase 6) |
