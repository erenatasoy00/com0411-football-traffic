"""Step 5 - matched control days and match-level traffic effects.

For every match we compare the ring-level traffic of the match day with the
same clock hours on up to four control days that
  * fall on the same weekday within +/-4 weeks,
  * have no match at any of the three stadiums on that day or the day before,
  * are not official holidays / holiday eves and have no other stadium event,
  * have similar weather at kick-off (|dT| <= 5 C and the same wet/dry state),
  * have at least 80 % of the event-span hours observed.
If fewer than two controls satisfy the weather rule it is relaxed (flagged).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as C
from .fixtures import load_other_events
from .panel import calendar_table

RINGS_OUT = ["R0", "R1", "R2", "NEAR", "DISTAL"]   # NEAR = R0 + R1


def ring_series(panel: pd.DataFrame) -> dict:
    p = panel[panel.cell_ok]
    near = p[p.ring.isin(["R0", "R1"])].assign(ring="NEAR")
    p = pd.concat([p, near], ignore_index=True)
    agg = p.groupby(["stadium", "ring", "ts"]).agg(speed=("avg_speed", "mean"),
                                                   lveh=("log_vehicles", "mean"),
                                                   n_cells=("avg_speed", "count")).reset_index()
    return {(s, r): d.set_index("ts")[["speed", "lveh", "n_cells"]] for (s, r), d in agg.groupby(["stadium", "ring"])}


def _weather_index(weather: pd.DataFrame) -> dict:
    w = weather.copy()
    w["ts"] = pd.to_datetime(w["ts"])
    if getattr(w["ts"].dt, "tz", None) is None:
        w["ts"] = w["ts"].dt.tz_localize(C.TZ)
    return {s: d.set_index("ts") for s, d in w.groupby("stadium")}


def _day_weather(widx, stadium, ko):
    w = widx[stadium]
    t = w["temperature_2m"].get(ko, np.nan)
    a, b = C.WINDOWS["pre"][0], C.WINDOWS["post"][1]
    win = w.loc[ko + pd.Timedelta(hours=a): ko + pd.Timedelta(hours=b), "precipitation"]
    return t, bool(win.sum() >= C.RAIN_MM_THRESHOLD)


def _coverage(series, hours):
    return series.reindex(hours)["speed"].notna().mean()


def select_controls(m, ko, rs, widx, blocked_days, hol_days, extra_exclude=()):
    hours = [ko + pd.Timedelta(hours=h) for h in range(C.EVENT_SPAN[0], C.EVENT_SPAN[1] + 1)]
    base = rs.get((m.stadium, "NEAR"))
    t0, wet0 = _day_weather(widx, m.stadium, ko)
    cands = []
    for k in sorted([k for k in range(-C.CONTROL_MAX_WEEKS, C.CONTROL_MAX_WEEKS + 1) if k],
                    key=lambda x: (abs(x), x)):
        kc = ko + pd.Timedelta(days=7 * k)
        d = kc.date()
        if d in blocked_days or (kc - pd.Timedelta(days=1)).date() in blocked_days:
            continue
        if d in hol_days or d in extra_exclude:
            continue
        hc = [h + pd.Timedelta(days=7 * k) for h in hours]
        if base is None or _coverage(base, hc) < 0.8:
            continue
        t, wet = _day_weather(widx, m.stadium, kc)
        ok_w = (abs(t - t0) <= C.CONTROL_MAX_DTEMP) and (wet == wet0)
        cands.append((k, ok_w))
    strict = [k for k, ok in cands if ok][:C.CONTROL_MAX]
    if len(strict) >= C.CONTROL_MIN:
        return strict, False
    relaxed = [k for k, _ in cands][:C.CONTROL_MAX]
    return relaxed, True


def compute_effects(panel, fx, weather, rs=None, label="main", event_dates=None, blocked=None):
    """Return hourly and window-level effects for the fixtures in `fx`.
    `event_dates` lets the placebo routine pass pseudo kick-offs."""
    rs = rs or ring_series(panel)
    widx = _weather_index(weather)
    cal = calendar_table(pd.Series(pd.date_range("2020-01-01", "2025-12-31", freq="D", tz=C.TZ)))
    hol_days = set(cal.loc[cal.is_holiday | cal.is_holiday_eve, "date"]) | C.excluded_days()
    blocked = blocked if blocked is not None else set(fx.kickoff.dt.date)
    other = load_other_events()
    rows, meta = [], []
    for m in fx.itertuples():
        ko = m.ko_ref if event_dates is None else event_dates[m.match_id]
        ex = set(other.loc[other.stadium == m.stadium, "date"]) if len(other) else set()
        ks, relaxed = select_controls(m, ko, rs, widx, blocked, hol_days, ex)
        span = [ko + pd.Timedelta(hours=h) for h in range(C.EVENT_SPAN[0], C.EVENT_SPAN[1] + 1)]
        base = rs.get((m.stadium, "NEAR"))
        mcov = _coverage(base, span) if base is not None else np.nan      # same 80 % rule as controls
        meta.append(dict(match_id=m.match_id, n_controls=len(ks), weather_relaxed=relaxed,
                         control_weeks=",".join(map(str, ks)), match_day_coverage=round(float(mcov), 3),
                         match_day_coverage_ok=bool(mcov >= 0.8)))
        if len(ks) < C.CONTROL_MIN:
            continue
        for ring in RINGS_OUT:
            s = rs.get((m.stadium, ring))
            if s is None:
                continue
            for h in range(C.EVENT_SPAN[0], C.EVENT_SPAN[1] + 1):
                t = ko + pd.Timedelta(hours=h)
                if t not in s.index:
                    continue
                y = s.loc[t]
                ctrl = s.reindex([t + pd.Timedelta(days=7 * k) for k in ks])
                rows.append(dict(match_id=m.match_id, stadium=m.stadium, ring=ring, h_rel=h,
                                 speed_match=y.speed, speed_ctrl=ctrl.speed.mean(),
                                 lveh_match=y.lveh, lveh_ctrl=ctrl.lveh.mean(),
                                 n_ctrl_obs=int(ctrl.speed.notna().sum()),
                                 n_cells_match=y.n_cells, n_cells_ctrl=ctrl.n_cells.mean()))
    eh = pd.DataFrame(rows)
    md = pd.DataFrame(meta)
    if eh.empty:
        return eh, pd.DataFrame(), md
    eh["d_speed"] = eh.speed_match - eh.speed_ctrl
    eh["pct_speed"] = 100 * eh.d_speed / eh.speed_ctrl
    eh["d_lveh"] = eh.lveh_match - eh.lveh_ctrl
    eh["pct_veh"] = 100 * (np.exp(eh.d_lveh) - 1)
    eh["window"] = "other"
    for name, (a, b) in C.WINDOWS.items():
        eh.loc[eh.h_rel.between(a, b), "window"] = name
    ew = (eh[eh.window != "other"].groupby(["match_id", "stadium", "ring", "window"])
          .agg(d_speed=("d_speed", "mean"), pct_speed=("pct_speed", "mean"),
               d_lveh=("d_lveh", "mean"), n_hours=("d_speed", "count")).reset_index())
    ew["pct_veh"] = 100 * (np.exp(ew.d_lveh) - 1)
    ew = ew.merge(md, on="match_id", how="left")
    fcols = ["match_id", "season", "season_role", "competition_type", "kickoff_slot", "is_derby",
             "is_big_match", "is_weekend", "spectators_allowed", "opponent", "weekday"]
    ew = ew.merge(fx[[c for c in fcols if c in fx.columns]], on="match_id", how="left")
    wx = []
    for m in fx.itertuples():
        ko = m.ko_ref if event_dates is None else event_dates[m.match_id]
        t, wet = _day_weather(widx, m.stadium, ko)
        wx.append(dict(match_id=m.match_id, temp_ko=t, is_wet=wet))
    ew = ew.merge(pd.DataFrame(wx), on="match_id", how="left")
    eh.to_parquet(C.PROCESSED / f"effects_hourly_{label}.parquet", index=False)
    ew.to_parquet(C.PROCESSED / f"effects_window_{label}.parquet", index=False)
    md.to_csv(C.PROCESSED / f"controls_{label}.csv", index=False)
    return eh, ew, md


def placebo_dates(fx, panel, seed=C.SEED, blocked=None):
    """Pseudo kick-offs: same weekday & clock time, 5-10 weeks away, on days without
    any match at the three stadiums and without holidays."""
    rng = np.random.default_rng(seed)
    match_days = set(fx.kickoff.dt.date) | set(blocked or ())
    cal = calendar_table(pd.Series(pd.date_range("2020-01-01", "2025-12-31", freq="D", tz=C.TZ)))
    hol = set(cal.loc[cal.is_holiday | cal.is_holiday_eve, "date"]) | C.excluded_days()
    tmin, tmax = panel.ts.min(), panel.ts.max()
    out = {}
    for m in fx.itertuples():
        opts = []
        for k in list(range(-10, -4)) + list(range(5, 11)):
            t = m.ko_ref + pd.Timedelta(days=7 * k)
            d = t.date()
            if tmin <= t <= tmax and d not in match_days and d not in hol and \
                    (t - pd.Timedelta(days=1)).date() not in match_days:
                opts.append(t)
        if opts:
            out[m.match_id] = opts[rng.integers(len(opts))]
    return out


def run_all_effects(panel, fx, weather):
    rs = ring_series(panel)
    blocked = set(fx.kickoff.dt.date)          # match days at any of the three stadiums
    bo = C.PROCESSED / "block_only_days.csv"     # matches without a reliable kick-off time
    if bo.exists():
        blocked |= set(pd.to_datetime(pd.read_csv(bo)["date"], errors="coerce").dropna().dt.date)
    main = fx[fx.season_role == "main"]
    plac_season = fx[fx.season_role == "placebo"]
    eh, ew, md = compute_effects(panel, main, weather, rs, label="main", blocked=blocked)
    res = {"main": (eh, ew, md)}
    if len(plac_season):
        res["closed_doors"] = compute_effects(panel, plac_season, weather, rs, label="closed_doors",
                                                blocked=blocked)
    pd_dates = placebo_dates(main, panel, blocked=blocked)
    fx_p = main[main.match_id.isin(pd_dates)]
    res["placebo_dates"] = compute_effects(panel, fx_p, weather, rs, label="placebo_dates",
                                           event_dates=pd_dates, blocked=blocked)
    log = {k: dict(matches_in=int(len(v[2])),
                   matches_with_controls=int((v[2].n_controls >= C.CONTROL_MIN).sum()) if len(v[2]) else 0,
                   match_day_coverage_below_80=int(((v[2].n_controls >= C.CONTROL_MIN)
                                                    & ~v[2].match_day_coverage_ok).sum()) if len(v[2]) else 0,
                   weather_relaxed=int(v[2].weather_relaxed.sum()) if len(v[2]) else 0,
                   mean_controls=float(v[2].n_controls.mean()) if len(v[2]) else None)
           for k, v in res.items()}
    (C.INTERIM / "effects_log.json").write_text(json.dumps(log, indent=2))
    return res, log
