# Tech Stack — by block

Primary pick (what to actually use), alternatives, and why. Everything is free or has a free tier.

## Foundation (every block uses these)
| Concern | Primary | Alternatives | Why |
|---|---|---|---|
| Language | **Python 3.11+** | q/kdb (live path only) | One language research→prod; most factors are regression/GBM |
| Env/packaging | **uv** | Poetry, pip-tools | Fastest; reproducible lockfile |
| DataFrame engine | **Polars** | Pandas (ecosystem compat) | Columnar, multi-threaded, lazy — same ideas as Spark on one machine |
| SQL-on-files | **DuckDB** | — | Reads Parquet/Delta directly; native **ASOF JOIN** (KDB as-of join, free) |
| Config | **pydantic-settings + YAML** | Hydra | Typed config, env overrides |
| Dev tooling | **ruff + mypy + pytest** | — | Lint/format/types/tests |
| Property tests | **hypothesis** | — | Point-in-time invariants & stats-style problems |
| CI | **GitHub Actions** | — | Free for public repos |

## Block 1 — Data & Signals
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Market/fundamental data | **yfinance** | Tiingo, Alpha Vantage, `pandas-datareader` | Daily OHLCV + basic fundamentals |
| Macro data | **fredapi** | — | Rates, CPI for factor controls |
| Filings / alt-data text | **edgartools** | `sec-edgar-downloader`, GDELT, Reddit (PRAW) | Your one "alternative data" signal |
| Factor reference | **Ken French data library** (via `pandas-datareader`) | — | Validate value/momentum vs. canonical factors |
| Data loaders | **plain Python + httpx** | — | One idempotent loader per source |

## Block 1b — Security matching
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| ID mapping | **OpenFIGI API** | — | Real, free Bloomberg FIGI ↔ ISIN/CUSIP/ticker |
| Fuzzy name/URL match | **rapidfuzz** | `recordlinkage` | Messy vendor name → entity |
| Point-in-time store | **Delta Lake** | — | Validity windows; query "as of date" |

## Block 1c — Data auditing
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Data contracts/validation | **Pandera** | Great Expectations, soda-core | Lighter than GE for solo; schema + coverage + outlier checks |

## Storage layer
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Batch warehouse | **Delta Lake via `deltalake` (delta-rs)** | `delta-spark` | ACID + schema + **time-travel** = point-in-time, no Spark needed |
| File format | **Parquet** (Delta sits on it) | — | Columnar; partition by date |
| Object store | local FS (dev) → **S3 via boto3** | MinIO, LocalStack | Cheap, parallel reads |
| Time-series/live (Ph6) | **DuckDB ASOF** or **ArcticDB** | **kdb+ Personal + PyKX** | ArcticDB (Man Group, free, S3-backed) = Pythonic KDB substitute |

## Compute / processing engine
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Light path (default) | **Polars / DuckDB** | — | 100–500 names × 15 yrs on a laptop |
| Distributed story (Ph5) | **PySpark** on **Databricks Community Edition** (free) | local Spark | Demonstrate partitions/shuffle/broadcast-join |

## Block 2 — Factor model core
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Numerics | **NumPy / SciPy** | — | Vectorized |
| Cross-sectional regression (factor returns) | **statsmodels** (OLS/WLS) | `linearmodels` (panel) | Decompose returns → factor + specific |
| Optional ML signals | **LightGBM / XGBoost** | scikit-learn | Gradient-boosted trees — what's actually used |
| Risk model / covariance | **scikit-learn `LedoitWolf`** (shrinkage) | `riskfolio-lib`, PyPortfolioOpt | Shrinkage fixes "can't estimate ~1M covariances" |

## Block 3 — Portfolio construction & trading
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Optimizer | **cvxpy** (+ OSQP/ECOS solver) | **PyPortfolioOpt**, riskfolio-lib | max return − risk − tcost, s.t. constraints |
| Transaction-cost model | **custom** (commission + spread + √-impact) | — | Square-root market-impact = the "Heisenberg" point |
| Backtester | **custom event-driven (pandas/polars)** | **vectorbt**, zipline-reloaded, backtrader | Cross-sectional daily rebalance; implementation shortfall |

## Block 4 — Performance analysis
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Metrics & tear sheets | **quantstats** | empyrical-reloaded, pyfolio-reloaded | Sharpe, IR, drawdowns out of the box |
| Attribution | **custom (Brinson-style)** | — | Factor vs. specific vs. cost; fundamental-law check |
| Reporting UI | **Streamlit + Plotly** | Jupyter/marimo report | Dashboard = nice interview demo |

## Infra / orchestration (Phase 5)
| Part | Primary | Alternatives | Note |
|---|---|---|---|
| Orchestrator | **Dagster** | Airflow, Prefect, Databricks Workflows | Asset/lineage model maps to data→signal→factor + point-in-time |
| Scheduling window | Dagster schedules | cron | Models "NY close → run → Tokyo open" window |
| Cloud | **AWS S3 + EC2 (boto3)** | LocalStack to emulate | Mirrors on-prem→cloud migration story |

---

## Minimal viable stack (Phases 0→4, no Spark/cloud/KDB)
`python` · **uv** · **polars** · **duckdb** · **deltalake** · **pandera** · **yfinance** + OpenFIGI ·
**statsmodels** · **scikit-learn** · **cvxpy** · **quantstats** · **dagster**

That's the whole pipeline on a laptop. Add PySpark/Databricks (Phase 5) and ArcticDB/kdb+ (Phase 6)
only when you want the distributed and time-series stories for interviews — don't start there.
