"""Phase 2: completes the statistics and trains / evaluates the prediction models.

    python3 run_all.py --offline     # Phase 1 dataset (needed once; already included in the package)
    python3 run_phase2.py            # Phase 2: extra statistics + models -> outputs/phase2_values.json

Phase 1 results are not changed: this script only reads the Phase 1 outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import pandas as pd

from ftraffic import config as C
from ftraffic import fixtures, stats_extra


def load_effects() -> dict:
    res = {}
    for label in ["main", "closed_doors", "placebo_dates"]:
        eh = pd.read_parquet(C.PROCESSED / f"effects_hourly_{label}.parquet")
        ew = pd.read_parquet(C.PROCESSED / f"effects_window_{label}.parquet")
        md = pd.read_csv(C.PROCESSED / f"controls_{label}.csv")
        res[label] = (eh, ew, md)
    return res


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if hasattr(o, "item"):
        return o.item()
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="stats,model", help="stats, model or both")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    t0 = time.time()
    out_p = C.OUT / "phase2_values.json"
    V = json.loads(out_p.read_text()) if out_p.exists() else {}
    pnl = pd.read_parquet(C.PROCESSED / "panel_cell_hour.parquet")
    fx, _ = fixtures.clean_fixtures()
    if "stats" in a.part:
        V["stats"] = stats_extra.run(load_effects(), pnl, fx)
        print(f"[stats] done ({time.time() - t0:.0f}s)")
    if "model" in a.part:
        from ftraffic import figures_phase2, model
        V["model"] = model.run(pnl, fx)
        figures_phase2.split_timeline(C.OUT_FIGS / "phase2" / "fig_split_timeline.png")
        figures_phase2.workflow(C.OUT_FIGS / "phase2" / "fig_workflow.png")
        print(f"[model] done ({time.time() - t0:.0f}s)")
    out_p.write_text(json.dumps(jsonable(V), indent=2, ensure_ascii=False))
    print(f"-> {out_p}")


if __name__ == "__main__":
    main()
