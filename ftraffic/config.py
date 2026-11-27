"""Central configuration: paths, stadiums, seasons, windows and thresholds.

Every analytical choice that the report describes is set here, so that a
reviewer can change one value and rebuild the whole dataset.
"""
from __future__ import annotations

from pathlib import Path

from . import geo

# ----------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_IBB = RAW / "ibb"
RAW_MANUAL = RAW / "ibb_manual"        # optional: monthly files downloaded by hand
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
OUT = ROOT / "outputs"
OUT_TABLES = OUT / "tables"
OUT_FIGS = OUT / "figures"
for _p in (RAW_IBB, RAW_MANUAL, INTERIM, PROCESSED, OUT_TABLES, OUT_FIGS):
    _p.mkdir(parents=True, exist_ok=True)

FIXTURES_CSV = RAW / "fixtures_tff.csv"          # filled in by the team from tff.org
OTHER_EVENTS_CSV = RAW / "other_events.csv"      # optional: concerts etc. at the stadiums

# ----------------------------------------------------------------- sources
IBB_API = "https://data.ibb.gov.tr/api/3/action"
IBB_PACKAGE = "hourly-traffic-density-data-set"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
TZ = "Europe/Istanbul"   # Turkey uses UTC+3 all year (no DST since 2016)

WEATHER_VARS = [
    "temperature_2m", "relative_humidity_2m", "precipitation", "rain", "snowfall",
    "cloud_cover", "wind_speed_10m", "wind_gusts_10m", "weather_code",
]

# ----------------------------------------------------------------- stadiums
# Coordinates: Wikipedia infoboxes (accessed Nov 2026). Capacities are the
# values valid during the study period and are only used as a crowd proxy.
STADIUMS = {
    "RAMS": dict(name="Rams Park (Ali Sami Yen Spor Kompleksi)", club="Galatasaray",
                 lat=41.10278, lon=28.99056, district="Sarıyer (Seyrantepe)", capacity=52280),
    "SARACOGLU": dict(name="Şükrü Saracoğlu Stadium", club="Fenerbahçe",
                      lat=40.98778, lon=29.03694, district="Kadıköy", capacity=47911),
    "TUPRAS": dict(name="Tüpraş Stadyumu", club="Beşiktaş",
                   lat=41.03917, lon=28.99472, district="Beşiktaş", capacity=42590),
}
for _k, _s in STADIUMS.items():
    _s["geohash"] = geo.encode(_s["lat"], _s["lon"], 6)

CLUB_PATTERNS = {   # regex used to recognise the clubs in TFF team names
    "Galatasaray": r"GALATASARAY",
    "Fenerbahçe": r"FENERBAH[CÇ]E",
    "Beşiktaş": r"BE[SŞ][İI]KTA[SŞ]",
    "Trabzonspor": r"TRABZONSPOR",
}
BIG3 = ["Galatasaray", "Fenerbahçe", "Beşiktaş"]
CLUB_TO_STADIUM = {s["club"]: k for k, s in STADIUMS.items()}

# ----------------------------------------------------------------- spatial rings
RINGS = {"R0": 0, "R1": 1, "R2": 2}   # Chebyshev rings of geohash-6 cells
DISTAL_RING = 5                        # reference ring for difference-in-differences


def study_cells() -> list[dict]:
    rows = []
    for key, s in STADIUMS.items():
        for label, k in list(RINGS.items()) + [("DISTAL", DISTAL_RING)]:
            for c in geo.ring(s["geohash"], k):
                lat, lon = geo.decode(c)
                rows.append(dict(geohash=c, stadium=key, ring=label, ring_k=k,
                                 cell_lat=lat, cell_lon=lon))
    return rows


# ----------------------------------------------------------------- seasons
# role: 'main' = spectators present; 'placebo' = played behind closed doors.
SEASONS = {
    "2020-21": dict(start="2020-09-01", end="2021-05-31", role="placebo", spectators=False),
    "2022-23": dict(start="2022-08-01", end="2023-06-15", role="main", spectators=True),
    "2023-24": dict(start="2023-08-01", end="2024-06-15", role="main", spectators=True),
    "2024-25": dict(start="2024-08-01", end="2025-01-31", role="main", spectators=True),
}

# ----------------------------------------------------------------- event windows
# hours relative to the kick-off hour (hour-start convention of the IBB data)
EVENT_SPAN = (-6, 6)
WINDOWS = {"pre": (-3, -1), "during": (0, 1), "post": (2, 4)}
KICKOFF_SLOTS = [(0, 17, "afternoon"), (17, 20, "early_evening"), (20, 24, "late_evening")]

# ----------------------------------------------------------------- control days
CONTROL_MAX_WEEKS = 4          # same weekday, up to +/- 4 weeks
CONTROL_MAX = 4                # keep the 4 nearest valid control days
CONTROL_MIN = 2                # matches with fewer controls are dropped
CONTROL_MAX_DTEMP = 5.0        # deg C at kick-off hour
RAIN_MM_THRESHOLD = 0.5        # window precipitation that makes a day "wet"
# periods never used as control days (national mourning after the 6 Feb 2023 earthquakes)
EXCLUDED_CONTROL_PERIODS = [("2023-02-06", "2023-02-12")]


def excluded_days() -> set:
    import pandas as _pd
    out = set()
    for a, b in EXCLUDED_CONTROL_PERIODS:
        out |= set(_pd.date_range(a, b, freq="D").date)
    return out

# ----------------------------------------------------------------- cleaning
SPEED_RANGE = (0, 200)         # km/h, physically plausible range
MIN_CELL_COVERAGE = 0.80       # share of hours observed for a cell to be kept
OUTAGE_SHARE = 0.50            # hour is a system outage if >50% study cells missing
LOW_SAMPLE_VEHICLES = 5        # speeds from <5 vehicles are flagged as unreliable
IQR_K = 1.5                    # IQR rule: outside [Q1 - 1.5 IQR, Q3 + 1.5 IQR] -> outlier flag (kept)

# ----------------------------------------------------------------- targets
CONGESTION_BINS = [0.0, 0.50, 0.75, 10.0]   # speed / free-flow speed
CONGESTION_LABELS = ["congested", "moderate", "free"]
ABNORMAL_Z = -2.0              # z-score of speed vs the cell's hour-of-week mean and SD

ALPHA = 0.05
N_TEMP_BINS = 5               # equal-width bins of temperature (discretisation)
SEED = 42
