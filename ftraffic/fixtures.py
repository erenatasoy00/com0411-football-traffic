"""Step 2 - clean and enrich the match calendar collected from tff.org.

Expected input: data/raw/fixtures_tff.csv with the columns of
FIXTURE_COLUMNS (one row per match played at one of the three stadiums,
copied from the TFF fixture / match-detail pages).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import config as C

FIXTURE_COLUMNS = ["season", "competition", "round", "date", "kickoff_local",
                   "home_team", "away_team", "venue", "spectators_allowed",
                   "attendance", "source_url", "notes"]

COMPETITION_TYPES = {  # substring (lower case) -> type
    "süper lig": "league", "super lig": "league", "trendyol": "league",
    "türkiye kupası": "domestic_cup", "turkiye kupasi": "domestic_cup", "ziraat": "domestic_cup",
    "süper kupa": "domestic_cup", "super cup": "domestic_cup",
    "champions": "european", "şampiyonlar": "european", "europa": "european",
    "avrupa": "european", "conference": "european", "konferans": "european", "uefa": "european",
}


def write_template():
    p = C.RAW / "fixtures_tff_TEMPLATE.csv"
    pd.DataFrame(columns=FIXTURE_COLUMNS).to_csv(p, index=False)
    return p


def _club(name: str):
    up = str(name).upper()
    for club, pat in C.CLUB_PATTERNS.items():
        if re.search(pat, up):
            return club
    return None


def _comp_type(s: str) -> str:
    low = str(s).lower()
    for k, v in COMPETITION_TYPES.items():
        if k in low:
            return v
    return "other"


def _venue_to_stadium(venue: str, home_club):
    v = str(venue).upper()
    if re.search(r"RAMS|ALİ SAMİ|ALI SAMI|NEF|TÜRK TELEKOM|TURK TELEKOM", v):
        return "RAMS"
    if re.search(r"SARACO|ÜLKER|ULKER|CHOBANI|KADIK", v):
        return "SARACOGLU"
    if re.search(r"TÜPRAŞ|TUPRAS|VODAFONE|BEŞİKTAŞ STAD|BESIKTAS STAD|BEŞİKTAŞ PARK|BESIKTAS PARK|DOLMABAH", v):
        return "TUPRAS"
    if v in ("", "NAN"):  # venue not given -> home club's stadium
        return C.CLUB_TO_STADIUM.get(home_club)
    return None  # neutral / other venue -> not part of the study


def season_of(ts: pd.Timestamp):
    for name, s in C.SEASONS.items():
        if pd.Timestamp(s["start"]).date() <= ts.date() <= pd.Timestamp(s["end"]).date():
            return name
    return None


def clean_fixtures(path=None) -> tuple[pd.DataFrame, dict]:
    path = path or C.FIXTURES_CSV
    if not path.exists():
        write_template()
        raise FileNotFoundError(
            f"{path} not found. Fill data/raw/fixtures_tff_TEMPLATE.csv with the matches from tff.org "
            "and save it as data/raw/fixtures_tff.csv (see the report, Section 3.1.4).")
    raw = pd.read_csv(path, dtype=str).fillna("")
    log = {"rows_in": int(len(raw))}
    df = raw.copy()
    df["home_club"] = df["home_team"].map(_club)
    df["away_club"] = df["away_team"].map(_club)
    df["stadium"] = [_venue_to_stadium(v, h) for v, h in zip(df["venue"], df["home_club"])]
    log["dropped_not_study_venue"] = int(df["stadium"].isna().sum())
    df = df[df["stadium"].notna()].copy()

    # rows without a reliable kick-off time (e.g. time zone not stated in the source) are not
    # analysed, but their dates are still excluded from the control-day pools
    no_time = df["kickoff_local"].str.strip().eq("") & df["date"].str.strip().ne("")
    blk = df.loc[no_time, ["stadium", "date"]].copy()
    blk.to_csv(C.PROCESSED / "block_only_days.csv", index=False)
    log["block_only_rows"] = int(len(blk))
    t = df["kickoff_local"].str.strip().str.replace(".", ":", regex=False)
    df["kickoff"] = pd.to_datetime(df["date"].str.strip() + " " + t, errors="coerce",
                                   dayfirst=False).dt.tz_localize(C.TZ)
    log["bad_datetime"] = int(df["kickoff"].isna().sum())
    df = df[df["kickoff"].notna()].copy()

    before = len(df)
    df = df.drop_duplicates(subset=["stadium", "kickoff"])
    log["duplicates_removed"] = int(before - len(df))

    df["season"] = df["kickoff"].map(season_of)
    log["outside_study_seasons"] = int(df["season"].isna().sum())
    df = df[df["season"].notna()].copy()

    k = df["kickoff"]
    mins = k.dt.hour * 60 + k.dt.minute
    df["kickoff_hour_rounded"] = ((mins + 30) // 60).clip(upper=23)
    df["ko_ref"] = k.dt.floor("D") + pd.to_timedelta(df["kickoff_hour_rounded"], unit="h")
    df["kickoff_time"] = k.dt.strftime("%H:%M")
    df["kickoff_slot"] = pd.cut(k.dt.hour + k.dt.minute / 60,
                                bins=[s[0] for s in C.KICKOFF_SLOTS] + [24],
                                labels=[s[2] for s in C.KICKOFF_SLOTS], right=False).astype(str)
    df["weekday"] = k.dt.day_name()
    df["is_weekend"] = k.dt.dayofweek >= 5
    df["competition_type"] = df["competition"].map(_comp_type)
    df["is_derby"] = df["home_club"].isin(C.BIG3) & df["away_club"].isin(C.BIG3)
    df["is_big_match"] = df["is_derby"] | df["away_club"].eq("Trabzonspor")
    df["opponent"] = df["away_team"].str.strip()
    sp = df["spectators_allowed"].str.strip().str.lower()
    default_sp = df["season"].map(lambda s: C.SEASONS[s]["spectators"])
    df["spectators_allowed"] = np.where(sp.isin(["1", "true", "yes", "evet"]), True,
                                        np.where(sp.isin(["0", "false", "no", "hayır", "hayir"]),
                                                 False, default_sp)).astype(bool)
    df["attendance"] = pd.to_numeric(df["attendance"].str.replace(r"[.,\s]", "", regex=True),
                                     errors="coerce")
    df["capacity"] = df["stadium"].map(lambda s: C.STADIUMS[s]["capacity"])
    df["season_role"] = df["season"].map(lambda s: C.SEASONS[s]["role"])
    df = df.sort_values("kickoff").reset_index(drop=True)
    df["match_id"] = [f"{s}_{k:%Y%m%d_%H%M}" for s, k in zip(df["stadium"], df["kickoff"])]

    # --- consistency checks (reported, not silently fixed)
    log["kickoff_outside_11_24h"] = int(((k.dt.hour < 11)).sum())
    same_day = df.groupby([df["stadium"], df["kickoff"].dt.date]).size()
    log["stadium_days_with_2plus_matches"] = int((same_day > 1).sum())
    hv = df.dropna(subset=["home_club"])
    log["home_club_venue_mismatch"] = int((hv["home_club"].map(C.CLUB_TO_STADIUM) != hv["stadium"]).sum())
    log["rows_out"] = int(len(df))
    keep = ["match_id", "season", "season_role", "competition", "competition_type", "round",
            "stadium", "home_team", "away_team", "home_club", "away_club", "opponent",
            "kickoff", "kickoff_time", "ko_ref", "kickoff_slot", "weekday", "is_weekend",
            "is_derby", "is_big_match", "spectators_allowed", "attendance", "capacity",
            "source_url", "notes"]
    df = df[keep]
    df.to_csv(C.PROCESSED / "fixtures_clean.csv", index=False)
    return df, log


def load_other_events() -> pd.DataFrame:
    """Optional non-football events (concerts...) at the stadiums: date, stadium, start_local."""
    p = C.OTHER_EVENTS_CSV
    if not p.exists():
        return pd.DataFrame(columns=["date", "stadium"])
    ev = pd.read_csv(p, dtype=str)
    ev["date"] = pd.to_datetime(ev["date"]).dt.date
    return ev
