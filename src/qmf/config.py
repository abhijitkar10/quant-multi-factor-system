"""Paths and settings. Override with QMF_* env vars."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("QMF_DATA_ROOT") or REPO_ROOT / "data")
LAKE = DATA_ROOT / "lake"
REFERENCE = DATA_ROOT / "reference"

START_DATE = date(2018, 1, 1)
OPENFIGI_API_KEY = os.environ.get("QMF_OPENFIGI_API_KEY")


def ensure_dirs() -> None:
    LAKE.mkdir(parents=True, exist_ok=True)
    REFERENCE.mkdir(parents=True, exist_ok=True)
