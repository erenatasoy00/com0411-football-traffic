"""Step 3 - clean the IBB cell-hour records of the study cells.

Rules (all counts are written to data/interim/cleaning_log.json):
 1. schema / type coercion, timestamp parsing (Europe/Istanbul)
 2. exact duplicates removed; duplicate (cell, hour) keys aggregated
 3. range & consistency rules: 0<=speed<=200, min<=avg<=max, vehicles>=1
 4. coordinate / geohash consistency
 5. complete hourly grid per cell (missing hours become explicit rows)
 6. system-outage hours (more than half of the study cells missing)
 7. missing values are NOT imputed; analyses drop them (pairwise deletion)
 8. low-sample hours (<5 vehicles) and IQR-rule outliers flagged (kept)
 9. cells with coverage below 80 % excluded from the analysis
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as C
from . import geo

NUM = ["min_speed", "max_speed", "avg_speed", "vehicles"]


def load_raw() -> pd.DataFrame:
    files = sorted(C.RAW_IBB.glob("*.parquet"))
    if not files:
        raise FileNotFoundError("no monthly files in data/raw/ibb - run the download step")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df.columns = [c.strip().upper() for c in df.columns]
    return df.rename(columns={"DATE_TIME": "ts", "LATITUDE": "lat", "LONGITUDE": "lon",
                              "GEOHASH": "geohash", "MINIMUM_SPEED": "min_speed",
                              "MAXIMUM_SPEED": "max_speed", "AVERAGE_SPEED": "avg_speed",
                              "NUMBER_OF_VEHICLES": "vehicles"})


def clean(save: bool = True) -> tuple[pd.DataFrame, dict]:
    df = load_raw()
    log = {"raw_rows": int(len(df)), "raw_months": int(df["SOURCE_MONTH"].nunique())
           if "SOURCE_MONTH" in df else None}

    # 1. types ------------------------------------------------------------
    # the monthly files use two formats ("2020-09-01 00:00:00" and "2020-10-01T00:00:00");
    # parsing the combined column with one inferred format would turn whole months into NaT
    raw_ts = df["ts"].astype(str).str.strip().str.replace("T", " ", regex=False)
    ts = pd.to_datetime(raw_ts, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    rest = ts.isna() & df["ts"].notna()
    if rest.any():                                   # any other format: parse element by element
        ts[rest] = pd.to_datetime(raw_ts[rest], format="mixed", errors="coerce")
    df["ts"] = ts
    if getattr(df["ts"].dt, "tz", None) is None:
        df["ts"] = df["ts"].dt.tz_localize(C.TZ, nonexistent="NaT", ambiguous="NaT")
    else:
        df["ts"] = df["ts"].dt.tz_convert(C.TZ)
    for c in NUM + ["lat", "lon"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["geohash"] = df["geohash"].astype(str).str.strip().str.lower()
    # rows without a time stamp are dropped; missing or non-numeric speeds / vehicle counts are only
    # counted here - the row is kept and the value becomes a gap of the hourly grid
    log["rows_without_timestamp_dropped"] = int(df["ts"].isna().sum())
    log["rows_with_missing_or_nonnumeric_speed_or_vehicles_kept_as_gaps"] = int(
        df[["avg_speed", "vehicles"]].isna().any(axis=1).sum())
    df = df.dropna(subset=["ts", "geohash"])

    # 2. duplicates --------------------------------------------------------
    n0 = len(df)
    df = df.drop_duplicates()
    log["exact_duplicates_removed"] = int(n0 - len(df))
    dup_keys = df.duplicated(["geohash", "ts"], keep=False)
    log["duplicate_keys_aggregated"] = int(dup_keys.sum())
    if dup_keys.any():
        agg = {"min_speed": "min", "max_speed": "max", "avg_speed": "mean", "vehicles": "max",
               "lat": "first", "lon": "first"}
        df = df.groupby(["geohash", "ts"], as_index=False).agg(agg)

    # 3. range and consistency rules ----------------------------------------
    lo, hi = C.SPEED_RANGE
    bad_range = ~df[["min_speed", "max_speed", "avg_speed"]].apply(lambda s: s.between(lo, hi)).all(axis=1)
    bad_order = ~((df.min_speed <= df.avg_speed) & (df.avg_speed <= df.max_speed))
    bad_veh = ~(df.vehicles >= 1)
    log["rule_speed_out_of_range"] = int(bad_range.sum())
    log["rule_min_avg_max_violated"] = int((bad_order & ~bad_range).sum())
    log["rule_vehicles_lt_1"] = int(bad_veh.sum())
    invalid = bad_range | bad_order | bad_veh
    df.loc[invalid, NUM] = np.nan      # value removed, row kept -> becomes a gap
    log["invalid_rows_set_missing"] = int(invalid.sum())

    # 4. coordinate/geohash consistency ---------------------------------------
    ok_coord = df[["lat", "lon"]].notna().all(axis=1)
    enc = pd.Series(index=df.index, dtype=object)
    enc[ok_coord] = [geo.encode(a, b, 6) for a, b in zip(df.lat[ok_coord], df.lon[ok_coord])]
    log["geohash_coordinate_mismatch"] = int((ok_coord & (enc != df.geohash)).sum())

    # 5. complete grid ----------------------------------------------------
    cells = pd.DataFrame(C.study_cells())
    cells = cells[cells.geohash.isin(df.geohash.unique())]
    log["study_cells_defined"] = int(len({r["geohash"] for r in C.study_cells()}))
    log["study_cells_with_data"] = int(cells.geohash.nunique())
    frames = []
    for s in C.SEASONS.values():
        rng = pd.date_range(s["start"], pd.Timestamp(s["end"]) + pd.Timedelta(hours=23),
                            freq="h", tz=C.TZ)
        frames.append(rng)
    hours = frames[0].append(frames[1:]).unique()
    hours = hours[(hours >= df.ts.min()) & (hours <= df.ts.max())]
    grid = pd.MultiIndex.from_product([sorted(cells.geohash.unique()), hours], names=["geohash", "ts"])
    df = df.set_index(["geohash", "ts"])[NUM].reindex(grid).reset_index()
    df["is_missing"] = df["avg_speed"].isna()
    log["grid_cell_hours"] = int(len(df))
    log["missing_cell_hours"] = int(df.is_missing.sum())
    log["missing_share"] = float(df.is_missing.mean())

    # 6. outage hours --------------------------------------------------------
    share = df.groupby("ts")["is_missing"].mean()
    outage = share[share > C.OUTAGE_SHARE].index
    df["outage_hour"] = df.ts.isin(outage)
    log["outage_hours"] = int(len(outage))

    # 7. missing values: no imputation ---------------------------------------
    # gaps stay missing; every analysis drops missing hours (dropna / pairwise deletion)
    df = df.sort_values(["geohash", "ts"]).reset_index(drop=True)

    # 8. flags ----------------------------------------------------------
    df["low_sample"] = df.vehicles < C.LOW_SAMPLE_VEHICLES
    df["how"] = df.ts.dt.dayofweek * 24 + df.ts.dt.hour          # hour of week
    # IQR rule within each cell and hour-of-week: Q1 - 1.5 IQR, Q3 + 1.5 IQR
    qs = df.groupby(["geohash", "how"])["avg_speed"].quantile([0.25, 0.75]).unstack()
    qs.columns = ["q1", "q3"]
    qs["iqr_low"] = qs.q1 - C.IQR_K * (qs.q3 - qs.q1)
    qs["iqr_high"] = qs.q3 + C.IQR_K * (qs.q3 - qs.q1)
    df = df.merge(qs[["iqr_low", "iqr_high"]].reset_index(), on=["geohash", "how"], how="left")
    df["outlier"] = (df.avg_speed < df.iqr_low) | (df.avg_speed > df.iqr_high)
    log["low_sample_cell_hours"] = int(df.low_sample.sum())
    log["outlier_cell_hours"] = int(df.outlier.sum())
    log["outlier_share"] = float(df.outlier.mean())

    # 9. coverage -------------------------------------------------------
    cov = 1 - df.groupby("geohash")["avg_speed"].apply(lambda s: s.isna().mean())
    good = cov[cov >= C.MIN_CELL_COVERAGE].index
    df["cell_ok"] = df.geohash.isin(good)
    log["cells_excluded_low_coverage"] = int((cov < C.MIN_CELL_COVERAGE).sum())
    log["cells_kept"] = int(len(good))
    cells["coverage"] = cells.geohash.map(cov)
    cells["cell_ok"] = cells.geohash.isin(good)

    # diurnal sanity check for the time-zone assumption
    prof = df[df.cell_ok].groupby(df.ts.dt.hour)["vehicles"].mean()
    log["hour_of_min_mean_vehicles"] = int(prof.idxmin()) if len(prof) else None

    if save:
        df.to_parquet(C.INTERIM / "traffic_clean.parquet", index=False)
        cells.to_csv(C.PROCESSED / "cells.csv", index=False)
        (C.INTERIM / "cleaning_log.json").write_text(json.dumps(log, indent=2, default=str))
    return df, log
