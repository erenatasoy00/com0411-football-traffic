"""Add-on: long-horizon match forecast for the panel (see ftraffic/scenario.py).

    python run_scenario.py     # ~3 min: forward-chaining validation, final model -> outputs/models/scenario_bundle.joblib
    python panel.py            # then open the local web panel

Reads the Phase 1 data and the Phase 2 results; changes neither.
"""
from __future__ import annotations

import sys

import pandas as pd

from ftraffic import config as C
from ftraffic import scenario


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    pnl = pd.read_parquet(C.PROCESSED / "panel_cell_hour.parquet")
    scenario.build(pnl)


if __name__ == "__main__":
    main()
