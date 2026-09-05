# Reading list — to understand this system

## The one book (start here)
**Active Portfolio Management: A Quantitative Approach for Producing Superior Returns and
Controlling Risk** — Richard C. Grinold & Ronald N. Kahn, 2nd ed., McGraw-Hill (1999).

This is the book the video explicitly recommends ("the one book I'd point any new hire to
before anything else"). Nearly every idea in the architecture comes straight from it:
alpha, the information ratio, the fundamental law, factor risk models, portfolio
construction, transaction costs, and performance analysis. A free PDF was linked in the
video description (hosted at cms.dm.uba.ar).

### Chapter → block reading map
Read these chapters in this order; each maps to a block in [feature-plan.md](feature-plan.md):

| Read about… | Maps to block |
|---|---|
| **Risk** (decomposition, factor vs. specific, why √time) | Risk model |
| **Residual Risk & Return → the Information Ratio** | Performance analysis |
| **The Fundamental Law of Active Management** (IR ≈ skill × √breadth) | Performance analysis |
| **Expected Returns / Arbitrage Pricing Theory** | Multi-factor foundation |
| **Forecasting** (basic + advanced — refining raw signals into alphas) | Alpha block |
| **Portfolio Construction** (the optimizer's objective & constraints) | Portfolio construction |
| **Transactions Costs, Turnover & Trading** | Implementation & trading |
| **Performance Analysis** | Performance analysis |

(Chapter numbers vary slightly by edition; navigate by the titles above.)

There is also a 2019 follow-up, **Advances in Active Portfolio Management** (Grinold & Kahn),
with updates and a Q&A format — read it *after* the original.

## Companion for implementation (more code-oriented quant)
**Quantitative Equity Portfolio Management** — Qian, Hua & Sorensen. A more modern,
hands-on take on building multifactor models; good bridge from theory to code.

## The engineering / data side (what Grinold & Kahn does *not* cover)
The video's second half is pure data engineering — storage, distributed compute, databases.
For that:

- **Designing Data-Intensive Applications** — Martin Kleppmann. The canonical book for
  columnar storage (Parquet), partitioning, distributed processing, fault tolerance, and
  ACID — i.e. the Spark / Delta Lake concepts in the video. **Most important DE book here.**
- **Spark: The Definitive Guide** — Chambers & Zaharia (or *Learning Spark, 2nd ed.*) for
  the Spark internals (lazy evaluation, Catalyst, shuffle).
- **Q for Mortals** — Jeffry Borror. The standard kdb+/q text (free online) for the
  time-series / as-of-join path.

## Market microstructure (transaction costs depth, optional)
- **Trading and Exchanges** — Larry Harris. Market structure, spreads, and market impact —
  the mechanics behind the cost model.

## Suggested order
1. Grinold & Kahn — Risk → Information Ratio → Fundamental Law (understand the *why*).
2. Kleppmann — storage & distributed chapters (understand the *how it runs*).
3. Grinold & Kahn — Forecasting → Portfolio Construction → Costs → Performance (the pipeline).
4. Spark / Q books — only when you reach Phases 5–6.
