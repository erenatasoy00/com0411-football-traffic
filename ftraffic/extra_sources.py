"""Extension - two further open sources that confirm the match effect and reach past January 2025.

The IBB hourly traffic data set ends in January 2025 (checked on the portal in November 2026), and no
other open source gives cell-level speeds for Istanbul. Two other open IBB data sets do cover the
stadiums and continue after January 2025:

  rail   Rail-system station passenger counts: daily entries per station, 2021 - December 2025.
         Stations next to the stadiums: Seyrantepe (M2, has a 'Stad Girisi' exit) for Rams Park,
         Sogutlucesme (Marmaray, ~400 m) for Sukru Saracoglu, Kabatas (T1 + F1) for Tupras.
  uym    Traffic announcements of the Transport Management Centre (UYM): every announcement with time,
         type, title and coordinates, 2013 - October 2026. Some announce road closures or congestion
         caused by a match.

Matches after January 2025 come from the same official sources as before: tff.org (tools/tff_scraper.js,
2025-26 and 2026-27 seasons) and the Wikipedia season articles for UEFA home matches.

The comparison design is the Phase 1 design: each match day against up to four control days on the
same weekday 1-4 weeks away, with no home match of the three clubs and no holiday; one value per match.

    python run_extra.py --download    # once: the IBB files (~280 MB) -> data/raw/extra/
    python run_extra.py               # tables, figures and outputs/extra_values.json
"""
from __future__ import annotations

import json
import re

import holidays
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from . import config as C

RAW_X = C.RAW / "extra"
SRC = C.RAW / "sources"
OUT_T = C.OUT_TABLES / "extra"
OUT_F = C.OUT_FIGS / "extra"
VENUE = {"R": "RAMS", "S": "SARACOGLU", "T": "TUPRAS"}
ST_LABEL = {"RAMS": "Rams Park", "SARACOGLU": "Şükrü Saracoğlu", "TUPRAS": "Tüpraş"}
COLORS = {"RAMS": "#2a78d6", "SARACOGLU": "#eb6834", "TUPRAS": "#1baf7a"}
# station names in the files vary in spelling and case between years
STATIONS = {"RAMS": (r"YENIKAPI-HACIOSMAN", r"^seyrantepe"),
            "SARACOGLU": (r"TCDD", r"^s[öo][ğg][üu]tl[üu][çc]e[şs]me"),
            "TUPRAS": (r"KABATAS-BAGCILAR|TAKSIM-KABATAS", r"^kabata[şs]")}
UYM_TYPES = ["Kaza Bildirimi", "Araç Arızası", "Yoğun Trafik", "Yolun Trafiğe Kapanması"]
FOOTBALL = r"futbol|maç|müsabaka|stadyum|stad[ıi]"
RADIUS_KM = 2.0
UYM_ROWS_SINCE_2020 = 148_530   # announcements from July 2020 in the file of 1 Nov 2026 (the extract keeps those near the stadiums)
WIN_H = (-3, 4)                       # announcement window around kick-off, as the Phase 1 windows
IBB_END = pd.Timestamp("2025-01-31")
CACHE_RAIL = C.PROCESSED / "extra_rail_daily.csv"          # small extracts kept in the code package:
CACHE_UYM = C.PROCESSED / "extra_uym_near_stadiums.csv"     # the full files (~280 MB) are not
PACKAGES = {"rail": "rayli-sistemler-istasyon-bazli-yolcu-ve-yolculuk-sayilari",
            "uym": "ulasim-yonetim-merkezi-trafik-duyurulari-verisi"}


# ----------------------------------------------------------------- download
def download():
    import requests
    RAW_X.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, pkg in PACKAGES.items():
        res = requests.get(f"{C.IBB_API}/package_show", params={"id": pkg}, timeout=60).json()["result"]["resources"]
        for r in res:
            if key == "rail":
                y = re.search(r"(20\d\d)", r["name"]).group(1)
                if not 2021 <= int(y) <= 2025:
                    continue
                name = f"rail_stations_{y}.csv"
            else:
                name = "uym_announcements.csv"
            print(f"  downloading {name} ...")
            with requests.get(r["url"], stream=True, timeout=600) as g:
                g.raise_for_status()
                with open(RAW_X / name, "wb") as f:
                    for chunk in g.iter_content(1 << 20):
                        f.write(chunk)
            lines.append(r["url"])
    (RAW_X / "sources.txt").write_text("\n".join(lines) + "\n")


# ----------------------------------------------------------------- fixtures 2020-2027
def season_of(ts):
    y = ts.year if ts.month >= 7 else ts.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def regime(ts):
    """Crowd regime of a date: closed doors 2020-21, capped 2021-22, spectators from 2022-23."""
    if pd.Timestamp("2020-08-01") <= ts < pd.Timestamp("2021-07-01"):
        return "closed_doors"
    if pd.Timestamp("2021-07-01") <= ts < pd.Timestamp("2022-07-01"):
        return "capped"
    return "spectators"


def fixtures_extended() -> pd.DataFrame:
    """Home matches of the three clubs from the TFF and UEFA source extracts, 2020-21 to 2026-27."""
    rows = []
    comp = {"L": "league", "C": "domestic_cup", "S": "super_cup"}
    for f in ["tff_home_matches_compact.txt", "tff_home_matches_2025_2027_compact.txt"]:
        for ln in (SRC / f).read_text(encoding="utf-8").splitlines():
            mac, dt, vk, ck, rnd, club, away, score = ln.split("|")
            rows.append(dict(source="TFF", ref=mac, kickoff=None if dt == "-" else dt, venue=vk,
                             competition_type=comp[ck], club=club, opponent=away,
                             played=bool(re.match(r"\d+-\d+", score)), time_known=True))
    for f in ["uefa_home_matches_compact.txt", "uefa_home_matches_2025_2027_compact.txt"]:
        for ln in (SRC / f).read_text(encoding="utf-8").splitlines():
            club, date, ko, vk, cmp_, rnd, away, score, att, flag = ln.split("|")
            rows.append(dict(source="UEFA", ref=f"{club}_{date}", kickoff=f"{date} {ko or '20:00'}", venue=vk,
                             competition_type="european", club=club, opponent=away,
                             played=bool(re.search(r"\d", score)), time_known=bool(ko) and flag != "time_uncertain",
                             attendance=att))
    fx = pd.DataFrame(rows)
    fx = fx[fx.kickoff.notna()].copy()
    fx["kickoff"] = pd.to_datetime(fx.kickoff)
    fx["date"] = fx.kickoff.dt.normalize()
    fx["stadium"] = fx.venue.map(VENUE)
    fx["season"] = fx.kickoff.map(season_of)
    fx["regime"] = fx.kickoff.map(regime)
    fx.loc[fx.attendance.eq("0"), "regime"] = "closed_doors"
    fx["is_derby"] = fx.opponent.str.upper().str.contains(r"GALATASARAY|FENERBAH|BE[ŞS][İI]KTA[ŞS]", regex=True)
    fx["period"] = np.where(fx.kickoff <= IBB_END + pd.Timedelta(days=1), "study", "after")
    fx["match_id"] = fx.stadium.fillna("X") + "_" + fx.kickoff.dt.strftime("%Y%m%d_%H%M")
    return fx.sort_values("kickoff").reset_index(drop=True)


def blocked_days(fx) -> set:
    """Days that may not be control days: any home match day of the three clubs, holidays and eves, mourning week."""
    days = set(fx.date.dt.date)
    yrs = list(range(2020, 2028))
    tr = holidays.Turkey(years=yrs)
    days |= set(tr.keys())
    days |= {d - pd.Timedelta(days=1).to_pytimedelta() for d, n in tr.items() if "Ramazan" in n or "Kurban" in n}
    days |= {pd.Timestamp(f"{y}-10-28").date() for y in yrs}
    days |= C.excluded_days()
    return days


def control_dates(day, blocked, available):
    """Same weekday, 1-4 weeks before or after, nearest first; up to 4, at least 2."""
    cands = []
    for k in range(1, C.CONTROL_MAX_WEEKS + 1):
        for sgn in (-1, 1):
            d = (day + pd.Timedelta(weeks=sgn * k)).date()
            if d not in blocked and d in available:
                cands.append(d)
    return cands[: C.CONTROL_MAX]


# ----------------------------------------------------------------- rail
def load_rail() -> pd.DataFrame:
    frames = []
    for f in sorted(RAW_X.glob("rail_stations_*.csv")):
        raw = f.read_bytes()[:4000]
        try:
            raw.decode("utf-8")
            enc = "utf-8-sig"
        except UnicodeDecodeError:
            enc = "cp1254"
        head = raw.decode(enc, errors="replace").splitlines()[0]
        sep = ";" if head.count(";") > head.count(",") else ","
        d = pd.read_csv(f, sep=sep, encoding=enc, low_memory=False,
                        usecols=lambda c: c.strip().strip('"').replace("﻿", "") in
                        {"transaction_year", "transaction_month", "transaction_day", "line", "station_name", "passage_cnt"})
        d.columns = [c.strip().strip('"').replace("﻿", "") for c in d.columns]
        frames.append(d)
    r = pd.concat(frames, ignore_index=True)
    r["date"] = pd.to_datetime(dict(year=r.transaction_year, month=r.transaction_month, day=r.transaction_day), errors="coerce")
    r["passage_cnt"] = pd.to_numeric(r.passage_cnt, errors="coerce")
    out = []
    for st, (line_re, name_re) in STATIONS.items():
        m = (r.line.astype(str).str.contains(line_re, case=False, regex=True)
             & r.station_name.astype(str).str.strip().str.contains(name_re, case=False, regex=True))
        g = r[m].groupby("date").passage_cnt.sum()
        out.append(pd.DataFrame({"stadium": st, "date": g.index, "entries": g.values}))
    daily = pd.concat(out, ignore_index=True)
    return daily[daily.entries > 0]


def rail_effects(fx, daily) -> pd.DataFrame:
    blocked = blocked_days(fx)
    rows = []
    for st, g in daily.groupby("stadium"):
        s = g.set_index(g.date.dt.date).entries
        avail = set(s.index)
        for m in fx[(fx.stadium == st) & fx.played].itertuples():
            day = m.date.date()
            if day not in avail:
                continue
            ctl = control_dates(m.date, blocked, avail)
            if len(ctl) < C.CONTROL_MIN:
                continue
            base = float(np.mean([s[d] for d in ctl]))
            rows.append(dict(match_id=m.match_id, stadium=st, date=day, kickoff=m.kickoff, season=m.season,
                             regime=m.regime, period=m.period, competition_type=m.competition_type,
                             is_derby=m.is_derby, entries_match=float(s[day]), entries_ctrl=base, n_controls=len(ctl),
                             pct=100 * (s[day] / base - 1), log_ratio=np.log(s[day] / base)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- UYM announcements
def load_uym() -> pd.DataFrame:
    u = pd.read_csv(RAW_X / "uym_announcements.csv", encoding="utf-8-sig")
    u["t0"] = pd.to_datetime(u.announcement_starting_datetime, errors="coerce")
    u = u[u.t0 >= "2020-07-01"].copy()
    for st, s in C.STADIUMS.items():
        dx = (u.longitude - s["lon"]) * np.cos(np.radians(s["lat"])) * 111.32
        dy = (u.latitude - s["lat"]) * 110.57
        u[f"d_{st}"] = np.hypot(dx, dy)
    title = u.announcement_title.fillna("")
    u["football"] = title.str.contains(FOOTBALL, case=False, regex=True)
    up = title.str.upper()
    u["named"] = np.select(
        [up.str.contains(r"RAMS|ALİ SAMİ|ALI SAMI|NEF STAD|TÜRK TELEKOM|SEYRANTEPE"),
         up.str.contains(r"SARAÇO|SARACO|ÜLKER STAD|CHOBANI|FENERBAHÇE STAD|FENERBAHÇE ŞÜKRÜ"),
         up.str.contains(r"TÜPRAŞ|TUPRAS|VODAFONE|BEŞİKTAŞ PARK|DOLMABAHÇE|İNÖNÜ")],
        ["RAMS", "SARACOGLU", "TUPRAS"], default="")
    u["kind"] = np.select(
        [u.announcement_type_desc.eq("Yolun Trafiğe Kapanması") | title.str.contains("kapat", case=False),
         title.str.contains("yoğun|yoğunlaş", case=False) | u.announcement_type_desc.eq("Yoğun Trafik")],
        ["closure", "congestion"], default="other")
    return u


def uym_football(fx, u) -> pd.DataFrame:
    """Football-related announcements matched to a home match at the stadium named in the text (or within 2 km)."""
    fb = u[u.football].copy()
    rows = []
    for m in fx[fx.stadium.notna() & fx.played & fx.time_known].itertuples():
        lo, hi = m.kickoff - pd.Timedelta(hours=12), m.kickoff + pd.Timedelta(hours=6)
        near = (fb.named == m.stadium) | ((fb.named == "") & (fb[f"d_{m.stadium}"] <= RADIUS_KM))
        hit = fb[near & fb.t0.between(lo, hi)]
        for a in hit.itertuples():
            rows.append(dict(match_id=m.match_id, stadium=m.stadium, season=m.season, regime=m.regime, period=m.period,
                             h_rel=(a.t0 - m.kickoff).total_seconds() / 3600, kind=a.kind,
                             type=a.announcement_type_desc, title=a.announcement_title))
    ann = pd.DataFrame(rows)
    cov = (fx[fx.stadium.notna() & fx.played & fx.time_known & (fx.kickoff <= u.t0.max())]
           .assign(has=lambda d: d.match_id.isin(set(ann.match_id) if len(ann) else set()))
           .groupby(["season", "stadium"]).agg(matches=("match_id", "size"), with_announcement=("has", "sum")).reset_index())
    return ann, cov


def uym_incidents(fx, u) -> pd.DataFrame:
    """Ordinary incident announcements (not about football) within 2 km in the window around kick-off,
    match day against the same clock window on the control days."""
    inc = u[~u.football & u.announcement_type_desc.isin(UYM_TYPES)]
    blocked = blocked_days(fx)
    days_all = set(pd.date_range("2020-07-01", u.t0.max().normalize(), freq="D").date)
    rows = []
    for m in fx[fx.stadium.notna() & fx.played & fx.time_known & (fx.kickoff <= u.t0.max())].itertuples():
        near = inc[inc[f"d_{m.stadium}"] <= RADIUS_KM]
        tt = near.t0.to_numpy()
        ko_time = m.kickoff - m.date

        def count(day):
            a = pd.Timestamp(day) + ko_time + pd.Timedelta(hours=WIN_H[0])
            b = pd.Timestamp(day) + ko_time + pd.Timedelta(hours=WIN_H[1])
            return int(((tt >= np.datetime64(a)) & (tt < np.datetime64(b))).sum())

        ctl = control_dates(m.date, blocked, days_all)
        if len(ctl) < C.CONTROL_MIN:
            continue
        rows.append(dict(match_id=m.match_id, stadium=m.stadium, season=m.season, regime=m.regime, period=m.period,
                         n_match=count(m.date.date()), n_ctrl=float(np.mean([count(d) for d in ctl])), n_controls=len(ctl)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- statistics
def summarise_pct(x):
    x = pd.Series(x, dtype=float).dropna()
    if len(x) < 6:
        return dict(n=int(len(x)), mean=np.nan, lo=np.nan, hi=np.nan, median=np.nan, p_wilcoxon=np.nan)
    m = x.mean()
    lo, hi = stats.t.interval(0.95, len(x) - 1, loc=m, scale=stats.sem(x))
    return dict(n=int(len(x)), mean=float(m), lo=float(lo), hi=float(hi), median=float(x.median()),
                p_wilcoxon=float(stats.wilcoxon(x).pvalue))


def rate_ratio(d, n_boot=2000, seed=C.SEED):
    if d.empty:
        return dict(n=0)
    rr = d.n_match.sum() / d.n_ctrl.sum() if d.n_ctrl.sum() > 0 else np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), (n_boot, len(d)))
    a, b = d.n_match.to_numpy()[idx].sum(1), d.n_ctrl.to_numpy()[idx].sum(1)
    boot = np.where(b > 0, a / np.maximum(b, 1e-9), np.nan)
    # counts are mostly zero, so inference rests on the cluster bootstrap over matches, not on a rank test
    return dict(n=int(len(d)), per_match=float(d.n_match.mean()), per_control=float(d.n_ctrl.mean()), rate_ratio=float(rr),
                lo=float(np.nanpercentile(boot, 2.5)), hi=float(np.nanpercentile(boot, 97.5)))


def speed_link(re_):
    """Matches that are both in the rail data and in Phase 1: does a larger crowd go with a larger slowdown?"""
    ew = pd.read_parquet(C.PROCESSED / "effects_window_main.parquet")
    post = ew[(ew.ring == "NEAR") & (ew.window == "post")][["match_id", "d_speed"]]
    j = re_.merge(post, on="match_id").dropna(subset=["d_speed", "pct"])
    if len(j) < 10:
        return dict(n=int(len(j)))
    rho, p = stats.spearmanr(j.pct, j.d_speed)
    return dict(n=int(len(j)), spearman=float(rho), p=float(p))


# ----------------------------------------------------------------- figures
def fig_rail(re_, path):
    groups = [("closed_doors", "study", "2020-21\nclosed doors"), ("spectators", "study", "Aug 2022 – Jan 2025\nIBB study period"),
              ("spectators", "after", "Feb – Dec 2025\nafter the IBB data")]
    fig, ax = plt.subplots(figsize=(7.6, 3.5))
    w = 0.26
    for i, st in enumerate(["RAMS", "SARACOGLU", "TUPRAS"]):
        for j, (rg, per, _) in enumerate(groups):
            x = re_[(re_.stadium == st) & (re_.regime == rg) & (re_.period == per)].pct
            s = summarise_pct(x)
            if s["n"] < 6:
                continue
            ax.bar(j + (i - 1) * w, s["mean"], w * 0.9, color=COLORS[st], label=ST_LABEL[st] if j == 1 else None)
            ax.errorbar(j + (i - 1) * w, s["mean"], yerr=[[s["mean"] - s["lo"]], [s["hi"] - s["mean"]]], color="#333", lw=1, capsize=2)
            ax.text(j + (i - 1) * w, max(s["hi"], 0) + 4, f"n={s['n']}", ha="center", fontsize=7, color="#555")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(3), [g[2] for g in groups], fontsize=8.5)
    ax.set_ylabel("Station entries on match day\nvs control days (%)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e5e5", lw=0.6)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def fig_uym(ann, path):
    fig, ax = plt.subplots(figsize=(7.6, 3.2))
    bins = np.arange(-12, 6.5, 1)
    sub = ann[ann.regime == "spectators"]
    data = [sub[sub.kind == k].h_rel for k in ["closure", "congestion", "other"]]
    ax.hist(data, bins=bins, stacked=True, color=["#d64a1f", "#e8a33d", "#a3adbd"],
            label=["road closure", "congestion", "other notice"])
    ax.axvspan(0, 2, color="#eadcb5", alpha=0.6, lw=0, zorder=0)
    ax.set_xlabel("Hours relative to kick-off (announcement start)")
    ax.set_ylabel("Announcements")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


# ----------------------------------------------------------------- run
def run(log=print) -> dict:
    OUT_T.mkdir(parents=True, exist_ok=True)
    OUT_F.mkdir(parents=True, exist_ok=True)
    fx = fixtures_extended()
    fx.to_csv(OUT_T / "fixtures_extended.csv", index=False)
    log(f"[extra] fixtures {len(fx)} home matches, {fx.kickoff.min():%Y-%m} .. {fx.kickoff.max():%Y-%m}")

    if (RAW_X / "uym_announcements.csv").exists():
        daily = load_rail()
        daily.to_csv(CACHE_RAIL, index=False)
        u = load_uym()
        near = u[["d_RAMS", "d_SARACOGLU", "d_TUPRAS"]].min(axis=1).le(5) | u.football
        u[near].to_csv(CACHE_UYM, index=False)
    else:                                                    # offline: the extracts written by an earlier run
        daily = pd.read_csv(CACHE_RAIL, parse_dates=["date"])
        u = pd.read_csv(CACHE_UYM, parse_dates=["t0"])
        u["named"] = u.named.fillna("")
    re_ = rail_effects(fx, daily)
    re_.to_csv(OUT_T / "rail_match_effects.csv", index=False)
    log(f"[extra] rail: {len(daily):,} station-days {daily.date.min():%Y-%m-%d} .. {daily.date.max():%Y-%m-%d}, {len(re_)} matches")

    ann, cov = uym_football(fx, u)
    ann.to_csv(OUT_T / "uym_football_announcements.csv", index=False)
    cov.to_csv(OUT_T / "uym_coverage_by_season.csv", index=False)
    inc = uym_incidents(fx, u)
    inc.to_csv(OUT_T / "uym_incident_counts.csv", index=False)
    log(f"[extra] uym: {len(u):,} announcements used, to {u.t0.max():%Y-%m-%d}, {len(ann)} football-related at matches, {len(inc)} matches")

    V = dict(fixtures=dict(n=int(len(fx)), n_after=int(((fx.period == "after") & fx.played & fx.stadium.notna()).sum()),
                           first=str(fx.kickoff.min())[:10], last_played=str(fx[fx.played].kickoff.max())[:10]),
             rail=dict(first=str(daily.date.min())[:10], last=str(daily.date.max())[:10], groups={}),
             uym=dict(rows=UYM_ROWS_SINCE_2020, last=str(u.t0.max())[:10], football_total=int(u.football.sum())))
    sp = re_[re_.regime == "spectators"]
    for key, d in {"spectators_all": sp, "study": sp[sp.period == "study"], "after": sp[sp.period == "after"],
                   "closed_doors": re_[re_.regime == "closed_doors"]}.items():
        V["rail"]["groups"][key] = summarise_pct(d.pct)
        for st in ["RAMS", "SARACOGLU", "TUPRAS"]:
            V["rail"]["groups"][f"{key}|{st}"] = summarise_pct(d[d.stadium == st].pct)
    V["rail"]["speed_link"] = speed_link(sp)
    V["rail"]["derby_vs_other"] = dict(
        derby=summarise_pct(sp[sp.is_derby].pct), other=summarise_pct(sp[~sp.is_derby].pct),
        p_mannwhitney=float(stats.mannwhitneyu(sp[sp.is_derby].pct, sp[~sp.is_derby].pct).pvalue) if sp.is_derby.sum() >= 3 else None)

    spa = ann[ann.regime == "spectators"]
    covs = cov[cov.season.isin(["2022-23", "2023-24", "2024-25", "2025-26", "2026-27"])]
    V["uym"]["football"] = dict(
        n=int(len(spa)), matches_with=int(spa.match_id.nunique()), matches=int(covs.matches.sum()),
        share_closure=float((spa.kind == "closure").mean()) if len(spa) else None,
        share_before_ko=float((spa.h_rel < 0).mean()) if len(spa) else None,
        median_h_rel=float(spa.h_rel.median()) if len(spa) else None,
        by_stadium={st: dict(matches=int(covs[covs.stadium == st].matches.sum()),
                             with_announcement=int(covs[covs.stadium == st].with_announcement.sum()))
                    for st in ["RAMS", "SARACOGLU", "TUPRAS"]},
        after=dict(n=int((spa.period == "after").sum()), matches_with=int(spa[spa.period == "after"].match_id.nunique())),
        closed_doors=dict(matches=int(cov[cov.season == "2020-21"].matches.sum()),
                          with_announcement=int(cov[cov.season == "2020-21"].with_announcement.sum())))
    isp = inc[inc.regime == "spectators"]
    V["uym"]["incidents"] = dict(all=rate_ratio(isp), study=rate_ratio(isp[isp.period == "study"]),
                                 after=rate_ratio(isp[isp.period == "after"]),
                                 closed_doors=rate_ratio(inc[inc.regime == "closed_doors"]),
                                 **{st: rate_ratio(isp[isp.stadium == st]) for st in ["RAMS", "SARACOGLU", "TUPRAS"]})
    fig_rail(re_, OUT_F / "fig_extra_rail.png")
    fig_uym(ann, OUT_F / "fig_extra_uym.png")
    (C.OUT / "extra_values.json").write_text(json.dumps(V, indent=2, default=float))
    return V
