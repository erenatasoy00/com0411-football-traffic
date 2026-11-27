"""Step 1 - inventory and acquisition of the raw sources.

* IBB hourly traffic density: the CKAN API of data.ibb.gov.tr lists one
  resource per month.  We (1) write an inventory of all monthly resources to
  determine the exact temporal coverage and (2) pull only the study cells,
  first through the CKAN DataStore (server-side filter on GEOHASH) and, if the
  DataStore is not active for a month, by streaming the monthly CSV and
  filtering it in chunks.
* Open-Meteo historical weather (ERA5 reanalysis) for each stadium.
"""
from __future__ import annotations

import io
import json
import re
import time
from datetime import date

import pandas as pd
import requests

from . import config as C

MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july",
             "august", "september", "october", "november", "december"]
MONTHS_TR = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz",
             "ağustos", "eylül", "ekim", "kasım", "aralık"]
IBB_COLS = ["DATE_TIME", "LATITUDE", "LONGITUDE", "GEOHASH", "MINIMUM_SPEED",
            "MAXIMUM_SPEED", "AVERAGE_SPEED", "NUMBER_OF_VEHICLES"]

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "ftraffic-student-project/1.0"


def _get(url, **kw):
    for attempt in range(4):
        try:
            r = SESSION.get(url, timeout=120, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def _post(url, payload):
    for attempt in range(4):
        try:
            r = SESSION.post(url, json=payload, timeout=180)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def _parse_month(name: str):
    low = name.lower()
    year = re.search(r"(20\d\d)", low)
    if not year:
        return None
    for i, (en, tr) in enumerate(zip(MONTHS_EN, MONTHS_TR)):
        if en in low or tr in low:
            return int(year.group(1)), i + 1
    return None


# ---------------------------------------------------------------- inventory
def build_inventory() -> pd.DataFrame:
    """List every monthly resource of the IBB package (temporal coverage)."""
    r = _get(f"{C.IBB_API}/package_show", params={"id": C.IBB_PACKAGE})
    res = r.json()["result"]["resources"]
    rows = []
    for x in res:
        ym = _parse_month(x.get("name", "") or x.get("description", ""))
        rows.append(dict(resource_id=x["id"], name=x.get("name"),
                         year=ym[0] if ym else None, month=ym[1] if ym else None,
                         url=x.get("url"), fmt=x.get("format"), size=x.get("size"),
                         datastore_active=bool(x.get("datastore_active")),
                         last_modified=x.get("last_modified") or x.get("created")))
    inv = pd.DataFrame(rows).sort_values(["year", "month"]).reset_index(drop=True)
    inv.to_csv(C.RAW / "ibb_inventory.csv", index=False)
    return inv


def coverage_summary(inv: pd.DataFrame) -> dict:
    ok = inv.dropna(subset=["year", "month"])
    months = pd.PeriodIndex([f"{int(y)}-{int(m):02d}" for y, m in zip(ok.year, ok.month)], freq="M")
    full = pd.period_range(months.min(), months.max(), freq="M")
    missing = [str(p) for p in full if p not in set(months)]
    s = dict(first_month=str(months.min()), last_month=str(months.max()),
             n_files=int(len(months)), missing_months=missing,
             n_datastore_active=int(ok.datastore_active.sum()))
    (C.RAW / "ibb_coverage.json").write_text(json.dumps(s, indent=2))
    return s


def months_needed() -> list[tuple[int, int]]:
    out = set()
    for s in C.SEASONS.values():
        for p in pd.period_range(s["start"], s["end"], freq="M"):
            out.add((p.year, p.month))
    return sorted(out)


# ---------------------------------------------------------------- traffic pull
def _pull_datastore(resource_id: str, geohashes: list[str]) -> pd.DataFrame:
    frames, offset, limit = [], 0, 32000
    while True:
        payload = {"resource_id": resource_id, "filters": {"GEOHASH": geohashes},
                   "limit": limit, "offset": offset}
        js = _post(f"{C.IBB_API}/datastore_search", payload).json()
        if not js.get("success"):
            raise RuntimeError(js.get("error"))
        recs = js["result"]["records"]
        if not recs:
            break
        frames.append(pd.DataFrame.from_records(recs))
        offset += limit
        if offset >= js["result"].get("total", 0):
            break
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=IBB_COLS)
    return df[[c for c in IBB_COLS if c in df.columns]]


def _pull_sql(resource_id: str, geohashes: list[str]) -> pd.DataFrame:
    """Second attempt: CKAN datastore_search_sql with an IN filter."""
    cells = ",".join(f"'{g}'" for g in geohashes)
    frames, offset, limit = [], 0, 32000
    while True:
        sql = (f'SELECT * FROM "{resource_id}" WHERE "GEOHASH" IN ({cells}) '
               f"LIMIT {limit} OFFSET {offset}")
        js = _post(f"{C.IBB_API}/datastore_search_sql", {"sql": sql}).json()
        if not js.get("success"):
            raise RuntimeError(js.get("error"))
        recs = js["result"]["records"]
        if not recs:
            break
        frames.append(pd.DataFrame.from_records(recs))
        if len(recs) < limit:
            break
        offset += limit
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=IBB_COLS)
    return df[[c for c in IBB_COLS if c in df.columns]]


def _filter_table(raw, geohashes: set[str]) -> pd.DataFrame:
    """Read a CSV (plain or zipped; path or bytes) in chunks and keep the study cells."""
    head = raw.read(2) if hasattr(raw, "read") else open(raw, "rb").read(2)
    if hasattr(raw, "seek"):
        raw.seek(0)
    comp = "zip" if head == b"PK" else None
    keep = []
    for chunk in pd.read_csv(raw, chunksize=1_000_000, dtype=str, compression=comp):
        chunk.columns = [c.strip().upper().lstrip("\ufeff") for c in chunk.columns]
        keep.append(chunk[chunk["GEOHASH"].str.strip().str.lower().isin(geohashes)])
    return pd.concat(keep, ignore_index=True) if keep else pd.DataFrame(columns=IBB_COLS)


def _pull_csv(url: str, geohashes: set[str]) -> pd.DataFrame:
    """Last resort: download the full monthly file and keep only the study cells."""
    with SESSION.get(url, stream=True, timeout=900) as r:
        r.raise_for_status()
        raw = io.BytesIO(r.content)
    return _filter_table(raw, geohashes)


def import_manual_files() -> list[str]:
    """Files downloaded by hand from the portal (CSV or ZIP, any name) can be put in
    data/raw/ibb_manual/. They are filtered to the study cells and split by month."""
    files = sorted([p for p in C.RAW_MANUAL.glob("*") if p.suffix.lower() in (".csv", ".zip")])
    log_p = C.RAW_MANUAL / "_imported.json"
    done = json.loads(log_p.read_text()) if log_p.exists() else {}
    files = [f for f in files if done.get(f.name) != f.stat().st_size]   # import each file once
    if not files:
        return []
    cells = {r["geohash"] for r in C.study_cells()}
    written = []
    for f in files:
        df = _filter_table(str(f), cells)
        done[f.name] = f.stat().st_size
        if df.empty:
            print(f"[manual] {f.name}: no study cells found")
            continue
        month = pd.to_datetime(df["DATE_TIME"], errors="coerce").dt.strftime("%Y-%m")
        for ym, d in df.groupby(month):
            out = C.RAW_IBB / f"{ym}.parquet"
            d = d.copy()
            d["SOURCE_MONTH"] = ym
            if out.exists():   # several files for one month -> append
                d = pd.concat([pd.read_parquet(out), d], ignore_index=True)
            d.to_parquet(out, index=False)
            written.append(ym)
        print(f"[manual] {f.name}: {len(df):,} rows of study cells")
    log_p.write_text(json.dumps(done, indent=1))
    return sorted(set(written))


def download_traffic(force: bool = False) -> list[str]:
    inv_path = C.RAW / "ibb_inventory.csv"
    inv = pd.read_csv(inv_path) if inv_path.exists() else build_inventory()
    cells = sorted({r["geohash"] for r in C.study_cells()})
    done = []
    for (y, m) in months_needed():
        out = C.RAW_IBB / f"{y}-{m:02d}.parquet"
        if out.exists() and not force:
            done.append(out.name)
            continue
        row = inv[(inv.year == y) & (inv.month == m)]
        if row.empty:
            print(f"[download] {y}-{m:02d}: not on the portal - skipped")
            continue
        row = row.iloc[0]
        df = None
        if str(row.datastore_active).lower() == "true":
            for name, fn in [("datastore_search", _pull_datastore), ("datastore_search_sql", _pull_sql)]:
                try:
                    df = fn(row.resource_id, cells)
                    break
                except Exception as e:
                    print(f"[download] {y}-{m:02d}: {name} failed ({str(e)[:120]})")
        if df is None:
            print(f"[download] {y}-{m:02d}: downloading the full monthly file (slower)")
            try:
                df = _pull_csv(row.url, set(cells))
            except Exception as e:
                print(f"[download] {y}-{m:02d}: FAILED ({e}). Download it by hand into data/raw/ibb_manual/")
                continue
        df["SOURCE_MONTH"] = f"{y}-{m:02d}"
        df.to_parquet(out, index=False)
        print(f"[download] {y}-{m:02d}: {len(df):,} rows")
        done.append(out.name)
    return done


# ---------------------------------------------------------------- weather
def download_weather(force: bool = False) -> pd.DataFrame:
    out = C.RAW / "weather_hourly.parquet"
    if out.exists() and not force:
        return pd.read_parquet(out)
    start = min(s["start"] for s in C.SEASONS.values())
    end = min(max(s["end"] for s in C.SEASONS.values()), str(date.today()))
    frames = []
    for key, s in C.STADIUMS.items():
        params = dict(latitude=s["lat"], longitude=s["lon"], start_date=start, end_date=end,
                      hourly=",".join(C.WEATHER_VARS), timezone=C.TZ)
        js = _get(C.OPEN_METEO_ARCHIVE, params=params).json()
        w = pd.DataFrame(js["hourly"])
        w["stadium"] = key
        frames.append(w)
        time.sleep(1)
    w = pd.concat(frames, ignore_index=True).rename(columns={"time": "ts"})
    w["ts"] = pd.to_datetime(w["ts"]).dt.tz_localize(C.TZ)
    w.to_parquet(out, index=False)
    return w
