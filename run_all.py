"""Rebuild the Phase-1 dataset and all statistical results with one command.

    python3 run_all.py                    # download (if needed) + full pipeline
    python3 run_all.py --skip-download    # no IBB API calls; use data/raw/ibb + data/raw/ibb_manual
                                          # (weather is still downloaded once if it is not cached)
    python3 run_all.py --offline          # no network access at all; needs cached IBB and weather files
    python3 run_all.py --seasons 2023-24  # quick mode: one season only
    python3 run_all.py --steps panel      # rebuild only the panel from the cleaned data

--steps selects the data-building steps that are (re)run: download, clean, panel. A step that is not
selected is loaded from its saved output. Fixtures, effects, statistics and quality checks always run,
because every result of the report depends on them.

Afterwards:  python3 fill_report.py  -> Phase1_Report_filled.docx
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import pandas as pd

from ftraffic import config as C
from ftraffic import clean, download, effects, fixtures, panel, qc, stats

BUILD_STEPS = ["download", "clean", "panel"]          # optional, selectable with --steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true",
                    help="no IBB API calls (weather is still downloaded once if not cached)")
    ap.add_argument("--offline", action="store_true",
                    help="no network access at all; requires cached IBB and weather files")
    ap.add_argument("--steps", default=",".join(BUILD_STEPS),
                    help="data-building steps to (re)run: download, clean, panel")
    ap.add_argument("--seasons", default="",
                    help="quick mode, e.g. --seasons 2023-24 or --seasons 2020-21,2023-24")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows consoles
    except Exception:
        pass
    if a.seasons:
        keep = [x.strip() for x in a.seasons.split(",") if x.strip()]
        for k in list(C.SEASONS):
            if k not in keep:
                del C.SEASONS[k]
        print(f"[seasons] {list(C.SEASONS)}")
    steps = [x.strip() for x in a.steps.split(",") if x.strip()]
    bad = [x for x in steps if x not in BUILD_STEPS]
    if bad:
        ap.error(f"unknown step(s) {bad}; choose from {BUILD_STEPS} "
                 "(fixtures, effects, stats and qc always run)")
    if a.skip_download or a.offline:
        steps = [x for x in steps if x != "download"]
    print(f"[steps] rebuilt: {steps or 'none'}; always run: fixtures, effects, stats, qc")
    t0 = time.time()
    inventory = None
    cov_p = C.RAW / "ibb_coverage.json"

    manual = download.import_manual_files()          # files put in data/raw/ibb_manual/
    if manual:
        print(f"[manual] months imported: {manual}")
    if "download" in steps:
        inv = download.build_inventory()
        inventory = download.coverage_summary(inv)
        print("[inventory]", inventory)
        download.download_traffic()
    weather_file = C.RAW / "weather_hourly.parquet"
    if weather_file.exists():
        print("[weather] using cached data/raw/weather_hourly.parquet (no download)")
    elif a.offline:
        sys.exit("[weather] data/raw/weather_hourly.parquet is missing; run once without --offline")
    else:
        print("[weather] downloading from the Open-Meteo archive")
        download.download_weather()
    if inventory is None and cov_p.exists():
        inventory = json.loads(cov_p.read_text())

    fixtures.write_template()
    fx, fx_log = fixtures.clean_fixtures()
    print(f"[fixtures] {fx_log}")

    if "clean" in steps:
        traffic, clean_log = clean.clean()
    else:
        traffic = pd.read_parquet(C.INTERIM / "traffic_clean.parquet")
        clean_log = json.loads((C.INTERIM / "cleaning_log.json").read_text())
    print(f"[clean] rows={len(traffic):,} kept cells={clean_log['cells_kept']}")

    weather = pd.read_parquet(C.RAW / "weather_hourly.parquet")
    if "panel" in steps:
        pnl, panel_log = panel.build_panel(traffic, fx, weather)
        panel.write_data_dictionary()
    else:
        pnl = pd.read_parquet(C.PROCESSED / "panel_cell_hour.parquet")
        panel_log = json.loads((C.INTERIM / "panel_log.json").read_text())
    print(f"[panel] {panel_log}")

    res, eff_log = effects.run_all_effects(pnl, fx, weather)
    print(f"[effects] {eff_log}")

    V = stats.run(res, clean_log, fx_log, panel_log, eff_log, inventory, pnl, fx)
    q = qc.run_qc(traffic, pnl, fx, weather, clean_log, fx_log, eff_log, inventory)
    for r in q.itertuples():
        V[f"{r.id}_V"] = str(r.value)
        V[f"{r.id}_R"] = "Pass" if r.passed else "Fail"
    V["QC_PASSED"] = f"{int(q.passed.sum())}/{len(q)}"
    (C.OUT / "report_values.json").write_text(json.dumps(V, indent=2, ensure_ascii=False))
    print(q.to_string(index=False))
    print(f"done in {time.time() - t0:.0f}s -> outputs/report_values.json, outputs/figures, outputs/tables")


if __name__ == "__main__":
    main()
