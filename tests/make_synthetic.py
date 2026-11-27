"""Generate SYNTHETIC raw files with the exact IBB / Open-Meteo / fixture
schemas so the whole pipeline can be smoke-tested offline.

!!! The numbers produced from these files are NOT research results. !!!
Usage:  python3 tests/make_synthetic.py   (writes into data/raw)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ftraffic import config as C  # noqa: E402
from ftraffic import geo  # noqa: E402
from ftraffic.download import months_needed  # noqa: E402
from ftraffic.fixtures import _club  # noqa: E402

rng = np.random.default_rng(0)


def fixtures():
    rows = []
    opp = ["Trabzonspor", "Konyaspor", "Antalyaspor", "Kasımpaşa", "Sivasspor", "Alanyaspor"]
    for sname, s in C.SEASONS.items():
        for i, (key, st) in enumerate(C.STADIUMS.items()):
            d = pd.Timestamp(s["start"]) + pd.Timedelta(days=10 + 3 * i)
            while d < pd.Timestamp(s["end"]):
                others = [c for c in C.BIG3 if c != st["club"]]
                away = others[rng.integers(2)] if rng.random() < 0.08 else opp[rng.integers(len(opp))]
                ko = ["20:00", "19:00", "17:00", "14:30", "21:45"][rng.integers(5)]
                comp = "Trendyol Süper Lig" if rng.random() < 0.8 else (
                    "UEFA Europa League" if rng.random() < 0.5 else "Ziraat Türkiye Kupası")
                rows.append(dict(season=sname, competition=comp, round="", date=d.strftime("%Y-%m-%d"),
                                 kickoff_local=ko, home_team=st["club"].upper() + " A.Ş.", away_team=away,
                                 venue=st["name"], spectators_allowed="", attendance="", source_url="synthetic",
                                 notes="SYNTHETIC"))
                d += pd.Timedelta(days=int(rng.integers(12, 18)))
    fx = pd.DataFrame(rows)
    fx.to_csv(C.FIXTURES_CSV, index=False)
    return fx


def traffic(fx):
    cells = pd.DataFrame(C.study_cells()).drop_duplicates("geohash")
    cells = cells[rng.random(len(cells)) > 0.3]                    # 'water' cells have no data
    fx = fx.copy()
    fx["ko"] = pd.to_datetime(fx.date + " " + fx.kickoff_local)
    fx["stadium"] = fx.home_team.map(lambda h: C.CLUB_TO_STADIUM[_club(h)])
    inv = []
    for (y, m) in months_needed():
        hrs = pd.date_range(f"{y}-{m:02d}-01", periods=pd.Period(f"{y}-{m:02d}").days_in_month * 24, freq="h")
        h = hrs.hour.values
        base_v = 40 + 160 * np.exp(-((h - 8.5) ** 2) / 6) + 180 * np.exp(-((h - 18) ** 2) / 8) + 30
        frames = []
        for c in cells.itertuples():
            ff = rng.uniform(45, 75)
            v = base_v * rng.uniform(0.4, 2.0) * rng.lognormal(0, 0.15, len(hrs))
            sp = ff * (1 - 0.45 * (v / v.max())) * rng.normal(1, 0.05, len(hrs))
            # match effect in R0/R1 (synthetic only)
            if c.ring in ("R0", "R1"):
                for k in fx.loc[fx.stadium == c.stadium, "ko"]:
                    dt = (hrs - k) / pd.Timedelta(hours=1)
                    eff = np.where((dt > -3) & (dt < 4), np.exp(-((dt - 2.2) ** 2) / 3), 0)
                    sp = sp * (1 - 0.25 * eff)
                    v = v * (1 + 0.35 * eff)
            lat, lon = geo.decode(c.geohash)
            d = pd.DataFrame({"DATE_TIME": hrs.strftime("%Y-%m-%d %H:%M:%S"), "LATITUDE": lat, "LONGITUDE": lon,
                              "GEOHASH": c.geohash, "AVERAGE_SPEED": np.round(sp).astype(int),
                              "NUMBER_OF_VEHICLES": np.maximum(1, np.round(v)).astype(int)})
            d["MINIMUM_SPEED"] = (d.AVERAGE_SPEED * rng.uniform(0.2, 0.6, len(d))).astype(int)
            d["MAXIMUM_SPEED"] = (d.AVERAGE_SPEED * rng.uniform(1.3, 2.2, len(d))).astype(int) + 1
            d = d[rng.random(len(d)) > 0.03]                                  # random gaps
            frames.append(d)
        df = pd.concat(frames, ignore_index=True)
        df = pd.concat([df, df.sample(50, random_state=1)])                    # duplicates
        bad = df.sample(20, random_state=2).index
        df.loc[bad, "AVERAGE_SPEED"] = 999                                    # invalid rows
        df["SOURCE_MONTH"] = f"{y}-{m:02d}"
        df.to_parquet(C.RAW_IBB / f"{y}-{m:02d}.parquet", index=False)
        inv.append(dict(resource_id=f"synthetic-{y}{m:02d}", name=f"Traffic Density Data for {y}-{m:02d}",
                        year=y, month=m, url="", fmt="CSV", size=None, datastore_active=False, last_modified=""))
        print("traffic", y, m, len(df))
    pd.DataFrame(inv).to_csv(C.RAW / "ibb_inventory.csv", index=False)
    (C.RAW / "ibb_coverage.json").write_text(json.dumps(dict(first_month="SYNTH", last_month="SYNTH",
                                                             n_files=len(inv), missing_months=[],
                                                             n_datastore_active=0)))


def weather():
    hrs = pd.date_range("2020-09-01", "2025-01-31 23:00", freq="h")
    frames = []
    for k in C.STADIUMS:
        doy = hrs.dayofyear.values
        t = 15 + 9 * np.sin(2 * np.pi * (doy - 110) / 365) + 4 * np.sin(2 * np.pi * (hrs.hour - 9) / 24)
        p = np.where(rng.random(len(hrs)) < 0.07, rng.gamma(1.2, 1.5, len(hrs)), 0)
        frames.append(pd.DataFrame({"ts": hrs.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": t + rng.normal(0, 1, len(hrs)),
                                    "relative_humidity_2m": 70.0, "precipitation": p, "rain": p, "snowfall": 0.0,
                                    "cloud_cover": 50.0, "wind_speed_10m": 12.0, "wind_gusts_10m": 25.0,
                                    "weather_code": np.where(p > 0, 61, 1), "stadium": k}))
    w = pd.concat(frames)
    w["ts"] = pd.to_datetime(w.ts).dt.tz_localize(C.TZ)
    w.to_parquet(C.RAW / "weather_hourly.parquet", index=False)


if __name__ == "__main__":
    if "--keep-fixtures" in sys.argv and C.FIXTURES_CSV.exists():   # use the real match list
        fx = pd.read_csv(C.FIXTURES_CSV, dtype=str).fillna("")
        fx = fx[(fx.kickoff_local != "") & fx.home_team.map(lambda h: _club(h) is not None)]
        fx = fx[fx.venue.str.contains("RAMS|SARACO|BEŞİKTAŞ PARK")]
    else:
        fx = fixtures()
    weather()
    traffic(fx)
    print("SYNTHETIC test data written - do not use for the report.")
