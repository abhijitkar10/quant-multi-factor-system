"""Delta Lake storage.

Time travel is the point: ``read_delta(name, version=v)`` returns the table as it was,
which is what keeps a backtest free of look-ahead bias.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from deltalake import DeltaTable

from qmf.config import LAKE


def table_path(name: str) -> Path:
    return LAKE / name


def table_exists(name: str) -> bool:
    return DeltaTable.is_deltatable(str(table_path(name)))


def write_delta(
    df: pl.DataFrame,
    name: str,
    *,
    mode: str = "overwrite",
    partition_by: list[str] | None = None,
) -> Path:
    path = table_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    options: dict = {}
    if partition_by:
        options["partition_by"] = partition_by
    if mode == "overwrite":
        # A deliberate overwrite may migrate the schema; appends stay strict.
        options["schema_mode"] = "overwrite"
    df.write_delta(str(path), mode=mode, delta_write_options=options)
    return path


def read_delta(name: str, *, version: int | None = None) -> pl.DataFrame:
    if not table_exists(name):
        raise FileNotFoundError(f"delta table {name!r} does not exist at {table_path(name)}")
    return pl.read_delta(str(table_path(name)), version=version)


def latest_version(name: str) -> int:
    return DeltaTable(str(table_path(name))).version()


def list_tables() -> list[str]:
    if not LAKE.exists():
        return []
    return sorted(p.name for p in LAKE.iterdir() if (p / "_delta_log").exists())
