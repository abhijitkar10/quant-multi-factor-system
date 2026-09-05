"""Security matching: vendor tickers -> FIGI.

Every vendor describes the same company differently, so entities must resolve to a stable
internal identifier before anything can be joined. Two properties matter more than the
matching itself:

* **Stability.** A ticker is not an identity — tickers get reused and reassigned, FIGI does
  not. FIGI is the key; the ticker is an attribute.
* **Point-in-time.** A mapping is only valid for a window, so the table is SCD-2 shaped
  (``valid_from``/``valid_to``) and read as of a date, never "what is true today".
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from itertools import batched

import httpx
import polars as pl

from qmf.config import OPENFIGI_API_KEY
from qmf.storage import write_delta

TABLE = "security_master"
URL = "https://api.openfigi.com/v3/mapping"
TIMEOUT = 30.0

# OpenFIGI allows 25 requests/min and 10 jobs/request anonymously; a key raises both.
_BATCH_ANON, _BATCH_KEYED = 10, 100
_SLEEP_ANON, _SLEEP_KEYED = 2.6, 0.3

_SCHEMA = {
    "ticker": pl.Utf8,
    "vendor_ticker": pl.Utf8,
    "exch_code": pl.Utf8,
    "figi": pl.Utf8,
    "composite_figi": pl.Utf8,
    "share_class_figi": pl.Utf8,
    "security_name": pl.Utf8,
    "security_type": pl.Utf8,
    "market_sector": pl.Utf8,
    "match_status": pl.Utf8,
    "message": pl.Utf8,
}


def to_openfigi_ticker(ticker: str) -> str:
    """yfinance writes share classes as ``BRK-B``; OpenFIGI/Bloomberg write ``BRK/B``.

    Neither is wrong — they are different conventions for the same security, which is why
    matching needs a translation layer instead of a plain string join.
    """
    return ticker.replace("-", "/")


def _row(ticker: str, vendor_ticker: str, exch: str, result: dict) -> dict:
    base = dict.fromkeys(_SCHEMA)
    base |= {"ticker": ticker, "vendor_ticker": vendor_ticker, "exch_code": exch}

    data = (result or {}).get("data") or []
    if data:
        d = data[0]
        base |= {
            "figi": d.get("figi"),
            "composite_figi": d.get("compositeFIGI"),
            "share_class_figi": d.get("shareClassFIGI"),
            "security_name": d.get("name"),
            "security_type": d.get("securityType"),
            "market_sector": d.get("marketSector"),
            "match_status": "matched",
        }
    else:
        base |= {
            "match_status": "unmatched",
            "message": (result or {}).get("warning") or (result or {}).get("error"),
        }
    return base


def map_tickers(
    tickers: list[str], *, exch_code: str = "US", transform=to_openfigi_ticker
) -> pl.DataFrame:
    """Resolve tickers to FIGIs.

    Network failures degrade to ``match_status="error"`` rows rather than raising, so a
    transient vendor outage shows up in the data instead of killing the pipeline.
    """
    size = _BATCH_KEYED if OPENFIGI_API_KEY else _BATCH_ANON
    pause = _SLEEP_KEYED if OPENFIGI_API_KEY else _SLEEP_ANON
    headers = {"Content-Type": "application/json"}
    if OPENFIGI_API_KEY:
        headers["X-OPENFIGI-APIKEY"] = OPENFIGI_API_KEY

    rows: list[dict] = []
    with httpx.Client(timeout=TIMEOUT) as client:
        for i, batch in enumerate(batched(tickers, size)):
            if i:
                time.sleep(pause)
            jobs = [
                {"idType": "TICKER", "idValue": transform(t), "exchCode": exch_code} for t in batch
            ]
            try:
                resp = client.post(URL, headers=headers, json=jobs)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[:200]
                for t in batch:
                    row = dict.fromkeys(_SCHEMA)
                    row |= {
                        "ticker": t,
                        "vendor_ticker": transform(t),
                        "exch_code": exch_code,
                        "match_status": "error",
                        "message": message,
                    }
                    rows.append(row)
            else:
                rows.extend(
                    _row(t, transform(t), exch_code, r)
                    for t, r in zip(batch, payload, strict=False)
                )

    return pl.DataFrame(rows, schema=_SCHEMA)


def build(tickers: list[str], *, valid_from: date | None = None) -> pl.DataFrame:
    """Resolve and publish the security master.

    Two passes: OpenFIGI's share-class convention first, then anything unresolved retried
    with the ticker exactly as we hold it. Real matching is a cascade of conventions.
    """
    mapped = map_tickers(tickers)
    unresolved = mapped.filter(pl.col("match_status") != "matched")["ticker"].to_list()
    if unresolved:
        retry = map_tickers(unresolved, transform=str)
        mapped = pl.concat([mapped.filter(pl.col("match_status") == "matched"), retry]).sort(
            "ticker"
        )

    master = mapped.with_columns(
        pl.lit(valid_from or date.today()).cast(pl.Date).alias("valid_from"),
        pl.lit(None).cast(pl.Date).alias("valid_to"),
        pl.lit("openfigi").alias("source"),
        pl.lit(datetime.now(UTC).replace(tzinfo=None)).cast(pl.Datetime("us")).alias("matched_at"),
    )
    write_delta(master, TABLE, mode="overwrite")
    return master


def match_rate(master: pl.DataFrame) -> float:
    if master.height == 0:
        return 0.0
    return master.filter(pl.col("match_status") == "matched").height / master.height
