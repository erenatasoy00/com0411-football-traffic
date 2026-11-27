"""Step 7 - automated quality checks on the final dataset (qc_report.json/csv)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as C


def run_qc(traffic, panel, fx, weather, clean_log, fx_log, eff_log, inventory=None) -> pd.DataFrame:
    rows = []

    def check(cid, name, value, threshold, passed):
        rows.append(dict(id=cid, check=name, value=value, threshold=threshold, passed=bool(passed)))

    if inventory:
        from .download import months_needed
        have = set()
        inv = pd.read_csv(C.RAW / "ibb_inventory.csv").dropna(subset=["year", "month"])
        have = {(int(y), int(m)) for y, m in zip(inv.year, inv.month)}
        miss = [f"{y}-{m:02d}" for y, m in months_needed() if (y, m) not in have]
        check("QC01", "Study months available on the IBB portal", ", ".join(miss) or "all", "all", not miss)
    dup = int(traffic.duplicated(["geohash", "ts"]).sum())
    check("QC02", "Unique (geohash, hour) keys", dup, "0 duplicates", dup == 0)
    t = traffic.dropna(subset=["avg_speed"])
    bad = int((~t.avg_speed.between(*C.SPEED_RANGE)).sum() +
              (~((t.min_speed <= t.avg_speed + 1e-9) & (t.avg_speed <= t.max_speed + 1e-9))).sum())
    check("QC03", "Speed range and min<=avg<=max after cleaning", bad, "0 violations", bad == 0)
    ok = traffic[traffic.cell_ok]
    ms = float(ok.avg_speed.isna().mean())
    check("QC04", "Remaining missing share in kept cells", round(ms, 4), "<= 0.20", ms <= 0.20)
    out = float(clean_log["outlier_share"])
    check("QC05", "IQR-rule outlier share of cell-hours", round(out, 4), "<= 0.10", out <= 0.10)
    gm = clean_log["geohash_coordinate_mismatch"] / max(clean_log["raw_rows"], 1)
    check("QC06", "Geohash/coordinate mismatch share", round(gm, 5), "<= 0.01", gm <= 0.01)
    hm = clean_log.get("hour_of_min_mean_vehicles")
    check("QC07", "Time-zone sanity: hour with fewest vehicles", hm, "01-06 local", hm is not None and 1 <= hm <= 6)
    wm = float(panel.loc[panel.cell_ok, "temperature_2m"].isna().mean())
    check("QC08", "Weather join completeness (missing share)", round(wm, 4), "<= 0.01", wm <= 0.01)
    fd = int(fx.duplicated(["stadium", "kickoff"]).sum())
    check("QC09", "Duplicate fixtures (stadium, kick-off)", fd, "0", fd == 0)
    hrs = fx.kickoff.dt.hour
    bad_ko = int(((hrs < 11) | (hrs > 23)).sum())
    check("QC10", "Kick-off times in 11:00-23:59", bad_ko, "0 outside", bad_ko == 0)
    mm = fx_log["home_club_venue_mismatch"]
    check("QC11", "Home club / stadium consistency", mm, "0 (or documented)", mm == 0)
    em = eff_log["main"]
    share = em["matches_with_controls"] / max(em["matches_in"], 1)
    check("QC12", "Main-season matches with >=2 control days", round(share, 3), ">= 0.90", share >= 0.90)
    z = panel[panel.cell_ok].groupby("geohash")["speed_z_cell"].agg(["mean", "std"])
    z_ok = bool((z["mean"].abs() < 1e-6).all() and ((z["std"] - 1).abs() < 1e-6).all())
    check("QC13", "Standardised speed: mean 0 and SD 1 in every cell", "verified" if z_ok else "mismatch",
          "|mean| and |SD-1| < 1e-6", z_ok)
    cells_kept = panel.loc[panel.cell_ok, ["stadium", "geohash"]].drop_duplicates()
    per_cell = panel[panel.cell_ok].groupby(["stadium", "geohash"]).size()
    check("QC14", "Complete hourly grid (rows per cell identical)", int(per_cell.nunique()), "1 distinct count",
          per_cell.nunique() == 1)
    qc = pd.DataFrame(rows)
    qc.to_csv(C.OUT_TABLES / "qc_report.csv", index=False)
    (C.PROCESSED / "qc_report.json").write_text(json.dumps(rows, indent=2, default=str))
    return qc
