"""Step 4 - integrate traffic, cells, calendar, weather and matches into the
analysis-ready cell-hour panel and engineer features and targets.
"""
from __future__ import annotations

import json

import holidays
import numpy as np
import pandas as pd

from . import config as C


def calendar_table(ts: pd.Series) -> pd.DataFrame:
    years = range(ts.dt.year.min() - 1, ts.dt.year.max() + 2)
    tr = holidays.Turkey(years=list(years))
    hol = {pd.Timestamp(d).date() for d in tr}
    # religious-holiday eves (arife) and 28 October are half working days
    eves = {(pd.Timestamp(d) - pd.Timedelta(days=1)).date() for d, n in tr.items()
            if ("Bayram" in n and "Ramazan" in n) or "Kurban" in n}
    eves |= {pd.Timestamp(f"{y}-10-28").date() for y in years}
    eves -= hol
    d = pd.DataFrame({"ts": ts.unique()})
    d["date"] = d.ts.dt.date
    d["hour"] = d.ts.dt.hour
    d["dow"] = d.ts.dt.dayofweek
    d["is_weekend"] = d.dow >= 5
    d["month"] = d.ts.dt.month
    d["is_holiday"] = d.date.isin(hol)
    d["is_holiday_eve"] = d.date.isin(eves)
    return d


def event_rows(fx: pd.DataFrame) -> pd.DataFrame:
    """One row per (match, relative hour) inside the event span."""
    rows = []
    lo, hi = C.EVENT_SPAN
    for m in fx.itertuples():
        for h in range(lo, hi + 1):
            rows.append((m.match_id, m.stadium, m.ko_ref + pd.Timedelta(hours=h), h))
    ev = pd.DataFrame(rows, columns=["match_id", "stadium", "ts", "h_rel"])
    ev["window"] = "other"
    for name, (a, b) in C.WINDOWS.items():
        ev.loc[ev.h_rel.between(a, b), "window"] = name
    # if two matches overlap at one stadium keep the closer one
    ev = ev.reindex(ev.h_rel.abs().sort_values().index).drop_duplicates(["stadium", "ts"])
    return ev


def build_panel(traffic: pd.DataFrame, fx: pd.DataFrame, weather: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    log = {}
    cells = pd.read_csv(C.PROCESSED / "cells.csv")
    p = traffic.merge(cells[["geohash", "stadium", "ring", "ring_k", "cell_lat", "cell_lon"]],
                      on="geohash", how="left")
    cal = calendar_table(p.ts)
    p = p.merge(cal, on="ts", how="left")

    # weather (hourly, per stadium) ------------------------------------------
    w = weather.copy()
    w["ts"] = pd.to_datetime(w["ts"])
    if getattr(w["ts"].dt, "tz", None) is None:
        w["ts"] = w["ts"].dt.tz_localize(C.TZ)
    w["is_rain"] = w["precipitation"] >= 0.1
    w["is_heavy_rain"] = w["precipitation"] >= 2.5
    p = p.merge(w, on=["stadium", "ts"], how="left")
    log["weather_missing_share"] = float(p["temperature_2m"].isna().mean())

    # match features -----------------------------------------------------
    ev = event_rows(fx)
    mcols = ["match_id", "season", "season_role", "competition_type", "kickoff_slot",
             "is_derby", "is_big_match", "spectators_allowed", "capacity", "opponent", "kickoff"]
    ev = ev.merge(fx[mcols], on="match_id", how="left")
    p = p.merge(ev, on=["stadium", "ts"], how="left")
    p["in_event_span"] = p.match_id.notna()
    p["window"] = p["window"].fillna("none")
    match_days = set(zip(fx.stadium, fx.kickoff.dt.date))
    p["is_match_day"] = [(s, d) in match_days for s, d in zip(p.stadium, p.date)]
    any_match_days = set(fx.kickoff.dt.date)
    p["any_big3_match_day"] = p.date.isin(any_match_days)

    # free-flow speed per cell: 85th percentile of night hours (01-04) on non-event days
    night = p[(p.hour.between(1, 4)) & (~p.is_match_day) & p.cell_ok]
    ff = night.groupby("geohash")["avg_speed"].quantile(0.85).rename("ff_speed")
    p = p.merge(ff, on="geohash", how="left")
    p["speed_ratio"] = p.avg_speed / p.ff_speed

    # targets ---------------------------------------------------------------
    p["congestion_class"] = pd.cut(p.speed_ratio, bins=C.CONGESTION_BINS,
                                   labels=C.CONGESTION_LABELS, right=False)
    # T3: z-score of speed relative to the cell's hour-of-week mean and standard deviation
    grp = p.groupby(["geohash", "how"])["avg_speed"]
    p["speed_z_how"] = (p.avg_speed - grp.transform("mean")) / grp.transform("std")
    # label is missing (NA), not False, when the hour has no speed or no hour-of-week baseline
    p["abnormal_slowdown"] = (p.speed_z_how < C.ABNORMAL_Z).astype("boolean").mask(p.speed_z_how.isna())

    # feature engineering (Lab 04): log transform, normalisation, standardisation,
    # discretisation and dummy variables ----------------------------------------
    p["log_vehicles"] = np.log1p(p.vehicles)
    gc = p.groupby("geohash")
    p["speed_z_cell"] = (p.avg_speed - gc["avg_speed"].transform("mean")) / gc["avg_speed"].transform("std")
    vmin, vmax = gc["vehicles"].transform("min"), gc["vehicles"].transform("max")
    p["vehicles_minmax"] = (p.vehicles - vmin) / (vmax - vmin)
    p["temp_bin"] = pd.cut(p.temperature_2m, bins=C.N_TEMP_BINS, labels=False)          # equal width
    p["vehicles_qbin"] = pd.qcut(p.vehicles, q=5, labels=False, duplicates="drop")       # equal frequency
    dummies = pd.get_dummies(p["window"], prefix="win")
    for col in ["win_pre", "win_during", "win_post"]:
        p[col] = dummies[col] if col in dummies else False

    p = p.sort_values(["stadium", "geohash", "ts"]).reset_index(drop=True)
    log["panel_rows"] = int(len(p))
    log["panel_rows_analysis"] = int(p.cell_ok.sum())
    log["matches"] = int(fx.match_id.nunique())
    p.to_parquet(C.PROCESSED / "panel_cell_hour.parquet", index=False)
    (C.INTERIM / "panel_log.json").write_text(json.dumps(log, indent=2))
    return p, log


DATA_DICTIONARY = [
    # name, group, type, description
    ("geohash", "key", "str", "6-character geohash of the IBB cell (~0.92 km x 0.61 km)"),
    ("ts", "key", "datetime[tz]", "Start of the hourly interval, Europe/Istanbul (UTC+3)"),
    ("stadium", "key", "str", "Stadium the cell is assigned to (RAMS, SARACOGLU, TUPRAS)"),
    ("ring / ring_k", "spatial", "str/int", "Geohash ring around the stadium cell: R0 (k=0), R1 (k=1), R2 (k=2), DISTAL (k=5)"),
    ("cell_lat, cell_lon", "spatial", "float", "Cell centre coordinates (decoded geohash)"),
    ("avg_speed, min_speed, max_speed", "traffic", "float", "Hourly speeds in the cell (km/h), IBB"),
    ("vehicles / log_vehicles", "traffic", "float", "Distinct observed vehicles (relative intensity, not volume) and log(1+x)"),
    ("is_missing, outage_hour", "quality", "bool", "Hour without a valid observation (not imputed); system-wide outage hour"),
    ("low_sample, outlier, iqr_low, iqr_high", "quality", "bool/float", "<5 vehicles; outside Q1-1.5 IQR / Q3+1.5 IQR of the cell hour-of-week; the limits"),
    ("cell_ok", "quality", "bool", "Cell has >=80 % hourly coverage; only these cells are analysed"),
    ("hour, dow, month, is_weekend", "calendar", "int/bool", "Calendar features"),
    ("is_holiday, is_holiday_eve", "calendar", "bool", "Official Turkish holiday; religious-holiday eve or 28 October"),
    ("temperature_2m ... weather_code", "weather", "float/int", "Open-Meteo ERA5 hourly weather at the stadium"),
    ("is_rain, is_heavy_rain", "weather", "bool", "Precipitation >=0.1 mm/h and >=2.5 mm/h"),
    ("match_id, h_rel, window", "event", "str/int/str", "Match in the +/-6 h span, hour relative to rounded kick-off, pre/during/post/other/none"),
    ("is_match_day, any_big3_match_day", "event", "bool", "Match at this stadium on this date; match at any of the three stadiums"),
    ("kickoff_slot, competition_type, is_derby, is_big_match, opponent", "event", "cat/bool", "Match attributes from the TFF fixture"),
    ("spectators_allowed, capacity, season, season_role", "event", "bool/int/str", "Crowd proxy and season (main or closed-doors placebo)"),
    ("speed_z_cell, vehicles_minmax", "transformed", "float", "z-score standardisation of speed and min-max normalisation of vehicles within each cell"),
    ("temp_bin, vehicles_qbin", "transformed", "int", "Temperature in 5 equal-width bins; vehicles in 5 equal-frequency bins"),
    ("win_pre, win_during, win_post", "transformed", "bool", "Dummy variables of the event window"),
    ("ff_speed, speed_ratio", "target support", "float", "Cell free-flow speed (85th pct, 01-04 h, non-match days) and avg_speed / ff_speed"),
    ("congestion_class", "target", "cat", "free (>=0.75), moderate (0.50-0.75), congested (<0.50) of speed_ratio"),
    ("abnormal_slowdown, speed_z_how", "target", "bool/float", "z-score of speed vs the cell hour-of-week mean and SD < -2"),
]


def write_data_dictionary():
    pd.DataFrame(DATA_DICTIONARY, columns=["column", "group", "type", "description"]).to_csv(
        C.PROCESSED / "data_dictionary.csv", index=False)
