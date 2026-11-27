"""Add-on - long-horizon forecast for a future match (used by panel.py).

Why a second model?
-------------------
The Phase 2 model is a day-ahead model: its strongest inputs are the traffic of the same cell 24, 48
and 168 hours earlier. For a match weeks or months ahead those values do not exist yet, and the IBB
data end in January 2025. This module therefore trains a "scenario" model that uses only what is
known as soon as the fixture is published:

    calendar  hour, weekday, month, weekend, holiday and holiday eve
    location  stadium, ring, the cell's free-flow speed
    profile   the cell's usual speed for that hour of the week (training data only)
    fixture   match day, hours to kick-off, competition, kick-off slot, opponent group, derby, capacity

Weather is left out: weeks ahead there is no forecast, and Phase 1 and the permutation importance of
Phase 2 showed that weather does not change the match effect.

Validation is the same forward chaining as Phase 2 (select on 2022-23 -> 2023-24, test once on
2024-25), so the numbers can be compared with the day-ahead model. The model used by the panel is
then refitted on all three seasons with spectators.

    python run_scenario.py     # validate, train the final model, save outputs/models/scenario_bundle.joblib
    python panel.py            # local web panel
"""
from __future__ import annotations

import json
import re
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from . import config as C
from . import model as M
from .panel import calendar_table
from .stats_extra import ISTANBUL_CLUBS

BUNDLE = C.OUT / "models" / "scenario_bundle.joblib"
SEASONS_ALL = ["2022-23", "2023-24", "2024-25"]
HOURS = list(range(C.EVENT_SPAN[0], C.EVENT_SPAN[1] + 1))
NEAR = ["R0", "R1"]

GROUPS = {
    "calendar": M.GROUPS["calendar"],
    "spatial": M.GROUPS["spatial"],
    "profile": dict(num=["how_mean_fit", "how_ratio_fit"]),
    "event": M.GROUPS["event"],
}
ALL = list(GROUPS)
NO_EVENT = [g for g in ALL if g != "event"]
LEAF_GRID = [31, 63]


def feature_cols(groups):
    num, cat = [], []
    for g in groups:
        d = GROUPS[g]
        num += d["num"] + d.get("tree_num", [])
        cat += d.get("tree_cat", [])
    return num + cat


def make(task, leaves):
    kw = dict(categorical_features="from_dtype", random_state=M.SEED, max_iter=300, learning_rate=0.1,
              max_leaf_nodes=leaves)
    return HistGradientBoostingClassifier(**kw) if task == "clf" else HistGradientBoostingRegressor(**kw)


def fit(task, groups, tr, leaves):
    X = feature_cols(groups)
    y = tr.y_t2 if task == "clf" else tr.y_t1
    return make(task, leaves).fit(tr[X], y), X


# ----------------------------------------------------------------- validation
def validate(d, log=print):
    """Forward chaining exactly as in Phase 2. Returns metrics per split and the chosen number of leaves."""
    out, leaves = {}, None
    for split, (fit_s, test_s) in M.SPLITS.items():
        ds = M.fit_split(d, fit_s)
        tr = ds[ds.season.isin(fit_s) & ds.valid]
        te = ds[ds.season.isin(test_s) & ds.valid].reset_index(drop=True)
        R, t0 = {}, time.time()
        R["profile_baseline|t2"] = M.evaluate(te, M.baselines(te, "clf")["b1_profile"], "clf")
        R["profile_baseline|t1"] = M.evaluate(te, te.how_mean_fit.to_numpy(), "reg")
        grid = LEAF_GRID if leaves is None else [leaves]
        best = None
        for lv in grid:
            clf, X = fit("clf", ALL, tr, lv)
            ev = M.evaluate(te, clf.predict(te[X]), "clf")
            log(f"  [{split}] scenario t2 leaves={lv}: macroF1 all={ev['all']['macro_f1']:.3f} "
                f"match={ev['match']['macro_f1']:.3f} ({time.time() - t0:.0f}s)")
            if best is None or ev["all"]["macro_f1"] > best[0]:
                best = (ev["all"]["macro_f1"], lv, ev)
        leaves = best[1]
        R["scenario|t2"] = best[2]
        clf, X = fit("clf", NO_EVENT, tr, leaves)
        R["scenario_no_event|t2"] = M.evaluate(te, clf.predict(te[X]), "clf")
        for name, groups in [("scenario", ALL), ("scenario_no_event", NO_EVENT)]:
            reg, X = fit("reg", groups, tr, leaves)
            R[f"{name}|t1"] = M.evaluate(te, reg.predict(te[X]), "reg")
        log(f"  [{split}] done: t1 MAE all={R['scenario|t1']['all']['mae']:.2f} "
            f"post_near={R['scenario|t1']['post_near']['mae']:.2f} ({time.time() - t0:.0f}s)")
        out[split] = {"rows": dict(train=int(len(tr)), test=int(len(te))), "metrics": R}
    return out, leaves


def metrics_table(R):
    rows = []
    for key, ev in R.items():
        name, task = key.split("|")
        for s, m in ev.items():
            rows.append(dict(model=name, task=task, slice=s, **m))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- reference data from the past
def past_matches():
    """Observed effects of every past match (Phase 1 output), for the panel's 'previous data' part."""
    fx = pd.read_csv(C.PROCESSED / "fixtures_clean.csv")
    ew = pd.read_parquet(C.PROCESSED / "effects_window_main.parquet")
    eh = pd.read_parquet(C.PROCESSED / "effects_hourly_main.parquet")
    post = ew[(ew.ring == "NEAR") & (ew.window == "post")][["match_id", "d_speed", "pct_veh"]]
    m = fx[fx.season_role == "main"][["match_id", "stadium", "kickoff", "kickoff_slot", "opponent",
                                      "competition", "competition_type", "is_derby", "is_big_match"]]
    m = m.merge(post, on="match_id", how="left")
    m["date"] = m.kickoff.str[:10]
    m["time"] = m.kickoff.str[11:16]
    h = eh[eh.ring == "NEAR"][["match_id", "h_rel", "speed_match", "speed_ctrl"]]
    hourly = {mid: g.set_index("h_rel")[["speed_match", "speed_ctrl"]].round(2).reindex(HOURS)
              for mid, g in h.groupby("match_id")}
    h = h.merge(m[["match_id", "stadium", "kickoff_slot"]], on="match_id")
    profile = (h.groupby(["stadium", "kickoff_slot", "h_rel"])[["speed_match", "speed_ctrl"]].mean().round(2)
               .reset_index())
    n = h.groupby(["stadium", "kickoff_slot"]).match_id.nunique().rename("n").reset_index()
    return m.drop(columns="kickoff"), hourly, profile, n


# ----------------------------------------------------------------- final model
def train_final(d, leaves, log=print):
    t0 = time.time()
    ds = M.fit_split(d, SEASONS_ALL)
    tr = ds[ds.season.isin(SEASONS_ALL) & ds.valid]
    clf, X = fit("clf", ALL, tr, leaves)
    reg, _ = fit("reg", ALL, tr, leaves)
    log(f"  final model on {len(tr):,} cell-hours (2022-23 to 2024-25), leaves={leaves} ({time.time() - t0:.0f}s)")
    return dict(clf=clf, reg=reg, X=X, leaves=leaves, **cells_profile(ds),
                data_end=str(ds.ts.max())[:10], train_rows=int(len(tr)))


def cells_profile(ds):
    """Static cell table and the hour-of-week profile of the fitting period (what a forecast may use)."""
    cells_xy = pd.read_csv(C.PROCESSED / "cells.csv")[["geohash", "cell_lat", "cell_lon"]]
    cells = (ds.groupby("geohash")[["stadium", "ring", "ring_k", "ff_fit"]].first().reset_index()
             .merge(cells_xy, on="geohash", how="left"))
    cells["stadium"] = cells.stadium.astype(str)
    prof = ds.groupby(["geohash", "how"])[["how_mean_fit", "how_ratio_fit"]].first().reset_index()
    return dict(cells=cells, profile=prof)


# ----------------------------------------------------------------- how much does the error grow with the gap?
HORIZON_BINS = [(0, 6), (6, 12), (12, 24)]           # months between the end of the training data and the match


def near_curves(B, stadium, kickoff, competition, attrs):
    """Mean forecast speed of the R0+R1 cells for hours -6..+6, with and without the match."""
    out = {}
    for label, is_match in [("match", True), ("normal", False)]:
        d, _, _ = scenario_rows(B, stadium, kickoff, competition, attrs, is_match)
        d["speed"] = B["reg"].predict(d[B["X"]])
        out[label] = d[d.ring.isin(NEAR)].groupby("h_rel_out").speed.mean()
    return out["match"], out["normal"]


def horizon_backtest(d, leaves, log=print):
    """Train as if the data ended one or two seasons earlier and forecast the later matches.
    Compares, per match and hour, (a) the absolute speed next to the stadium and (b) the change against a
    normal day with what was observed (Phase 1: match day and the mean of its control days)."""
    fx = pd.read_csv(C.PROCESSED / "fixtures_clean.csv")
    fx = fx[fx.season_role == "main"].copy()
    fx["ko"] = pd.to_datetime(fx.kickoff.str[:16])
    eh = pd.read_parquet(C.PROCESSED / "effects_hourly_main.parquet")
    obs = eh[eh.ring == "NEAR"].set_index(["match_id", "h_rel"])[["speed_match", "speed_ctrl", "d_speed"]]
    have = set(obs.index.get_level_values(0))
    rows, t0, curves = [], time.time(), []
    for fit_s, test_s in [(["2022-23"], ["2023-24", "2024-25"]), (["2022-23", "2023-24"], ["2024-25"])]:
        ds = M.fit_split(d, fit_s)
        tr = ds[ds.season.isin(fit_s) & ds.valid]
        reg, X = fit("reg", ALL, tr, leaves)
        Bt = dict(reg=reg, X=X, **cells_profile(ds))
        end = pd.Timestamp(tr.ts.max()).tz_localize(None) if pd.Timestamp(tr.ts.max()).tzinfo else pd.Timestamp(tr.ts.max())
        for m in fx[fx.season.isin(test_s) & fx.match_id.isin(have)].itertuples():
            attrs = describe_match(m.stadium, m.opponent, m.competition_type)
            pm, pn = near_curves(Bt, m.stadium, m.ko, m.competition_type, attrs)
            o = obs.loc[m.match_id]
            if fit_s == ["2022-23", "2023-24"]:            # the Phase 2 test season: kept for the panel
                ob = o.reindex(HOURS)
                curves.append(dict(match_id=m.match_id, date=m.kickoff[:10], time=m.kickoff[11:16], stadium=m.stadium,
                                   opponent=m.opponent, competition_type=m.competition_type,
                                   pred_match=[round(float(pm[h]), 2) for h in HOURS], pred_normal=[round(float(pn[h]), 2) for h in HOURS],
                                   obs_match=[None if pd.isna(v) else round(float(v), 2) for v in ob.speed_match],
                                   obs_ctrl=[None if pd.isna(v) else round(float(v), 2) for v in ob.speed_ctrl]))
            for h in HOURS:
                if h not in o.index or pd.isna(o.loc[h, "speed_match"]):
                    continue
                rows.append(dict(trained_on="+".join(fit_s), match_id=m.match_id, stadium=m.stadium,
                                 horizon=(m.ko - end).days / 30.44, h_rel=h,
                                 err_abs=pm[h] - o.loc[h, "speed_match"],
                                 err_eff=(pm[h] - pn[h]) - o.loc[h, "d_speed"]))
        log(f"  [horizon] trained on {'+'.join(fit_s)}: {len({r['match_id'] for r in rows if r['trained_on'] == '+'.join(fit_s)})} matches ({time.time() - t0:.0f}s)")
    r = pd.DataFrame(rows)
    r.to_csv(M.OUT_T / "scenario_horizon_backtest.csv", index=False)
    post = (r[r.h_rel.between(*C.WINDOWS["post"])].groupby(["trained_on", "match_id"])
            .agg(horizon=("horizon", "first"), err_abs=("err_abs", "mean"), err_eff=("err_eff", "mean")).reset_index())
    bins = []
    for lo, hi in HORIZON_BINS:
        rh, ph = r[r.horizon.between(lo, hi, inclusive="left")], post[post.horizon.between(lo, hi, inclusive="left")]
        if rh.empty:
            continue
        q = lambda x, k: float(np.nanquantile(x, k))
        bins.append(dict(lo=lo, hi=hi, n_matches=int(ph.match_id.nunique()) if len(ph) else 0, max_tested=float(rh.horizon.max()),
                         mae_abs=float(rh.err_abs.abs().mean()), mae_eff=float(rh.err_eff.abs().mean()),
                         abs_q10=q(rh.err_abs, 0.1), abs_q90=q(rh.err_abs, 0.9),
                         eff_q10=q(rh.err_eff.dropna(), 0.1), eff_q90=q(rh.err_eff.dropna(), 0.9),
                         post_mae_abs=float(ph.err_abs.abs().mean()), post_mae_eff=float(ph.err_eff.abs().mean()),
                         post_abs_q10=q(ph.err_abs, 0.1), post_abs_q90=q(ph.err_abs, 0.9),
                         post_eff_q10=q(ph.err_eff.dropna(), 0.1), post_eff_q90=q(ph.err_eff.dropna(), 0.9)))
    for b in bins:
        log(f"  [horizon] {b['lo']:>2}-{b['hi']:<2} months, {b['n_matches']} matches: after the match |error| "
            f"absolute {b['post_mae_abs']:.2f} km/h, change vs normal day {b['post_mae_eff']:.2f} km/h")
    return dict(bins=bins, max_tested=float(r.horizon.max())), test_eval(curves)


def test_eval(curves):
    """Out-of-sample check for the panel: model trained on 2022-24, matches of the 2024-25 test season."""
    post = [i for i, h in enumerate(HOURS) if C.WINDOWS["post"][0] <= h <= C.WINDOWS["post"][1]]
    rows = []
    for c in curves:
        om = [c["obs_match"][i] for i in post if c["obs_match"][i] is not None]
        oc = [c["obs_ctrl"][i] for i in post if c["obs_ctrl"][i] is not None]
        if not om or not oc:
            continue
        pm, pn = np.mean([c["pred_match"][i] for i in post]), np.mean([c["pred_normal"][i] for i in post])
        c.update(post_pred=round(float(pm), 2), post_obs=round(float(np.mean(om)), 2),
                 post_pred_delta=round(float(pm - pn), 2), post_obs_delta=round(float(np.mean(om) - np.mean(oc)), 2))
        rows.append(c)
    d = pd.DataFrame(rows)
    summ = dict(n=int(len(d)), mae_post=float((d.post_pred - d.post_obs).abs().mean()),
                mae_delta=float((d.post_pred_delta - d.post_obs_delta).abs().mean()),
                r_delta=float(np.corrcoef(d.post_pred_delta, d.post_obs_delta)[0, 1]),
                share_slowdown_both=float(((d.post_pred_delta < -1) == (d.post_obs_delta < -1)).mean()))
    return dict(summary=summ, matches=sorted(rows, key=lambda c: c["date"]))


def build(pnl, log=print):
    t0 = time.time()
    d = M.base_frame(pnl)
    log(f"[scenario] base frame {len(d):,} rows ({time.time() - t0:.0f}s)")
    val, leaves = validate(d, log)
    B = train_final(d, leaves, log)
    B["horizon"], B["test_eval"] = horizon_backtest(d, leaves, log)
    te = B["test_eval"]["summary"]
    log(f"  [test 2024-25] {te['n']} matches: post-match |error| {te['mae_post']:.2f} km/h, change |error| {te['mae_delta']:.2f} km/h, r = {te['r_delta']:.2f}")
    m, hourly, prof, n = past_matches()
    B.update(past=m, past_hourly=hourly, past_profile=prof, past_n=n, validation=val,
             day_ahead=day_ahead_metrics(), built=time.strftime("%Y-%m-%d %H:%M"))
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(B, BUNDLE, compress=3)
    for split, name in [("selection", "validation_2023-24"), ("final", "test_2024-25")]:
        metrics_table(val[split]["metrics"]).to_csv(M.OUT_T / f"scenario_{name}.csv", index=False)
    summary = {s: {k: {sl: {mk: round(mv, 4) for mk, mv in v.items()} for sl, v in ev.items()}
                   for k, ev in val[s]["metrics"].items()} for s in val}
    (C.OUT / "scenario_values.json").write_text(json.dumps(dict(leaves=leaves, validation=summary, horizon=B["horizon"]), indent=2))
    log(f"[scenario] saved {BUNDLE} ({time.time() - t0:.0f}s)")
    return B


def day_ahead_metrics():
    p = C.OUT / "phase2_values.json"
    if not p.exists():
        return {}
    f = json.loads(p.read_text())["model"]["final"]["metrics"]
    return {"t2": {s: f["t2|hgb"][s]["macro_f1"] for s in ["all", "match", "post_near"]},
            "t1": {s: f["t1|hgb"][s]["mae"] for s in ["all", "match", "post_near"]}}


# ----------------------------------------------------------------- prediction for one future match
def tr_upper(s: str) -> str:
    return str(s).replace("i", "İ").replace("ı", "I").upper()


def describe_match(stadium, opponent, competition):
    """Fixture attributes exactly as fixtures.py and model.base_frame define them."""
    home = C.STADIUMS[stadium]["club"]
    opp = tr_upper(opponent)
    away = next((club for club, pat in C.CLUB_PATTERNS.items() if re.search(pat, opp)), None)
    is_derby = away in C.BIG3 and away != home
    is_big = is_derby or away == "Trabzonspor"
    if is_big:
        group = "big_match"
    elif competition == "european":
        group = "european"
    elif re.search(ISTANBUL_CLUBS, opp):
        group = "istanbul"
    else:
        group = "other_domestic"
    return dict(home_club=home, is_derby=is_derby, is_big_match=is_big, opp_group=group)


def kickoff_ref(kickoff: pd.Timestamp):
    mins = kickoff.hour * 60 + kickoff.minute
    ko_ref = kickoff.floor("D") + pd.Timedelta(hours=min((mins + 30) // 60, 23))
    x = kickoff.hour + kickoff.minute / 60
    slot = next(name for lo, hi, name in C.KICKOFF_SLOTS if lo <= x < hi)
    return ko_ref, slot


def scenario_rows(B, stadium, kickoff, competition, attrs, match=True):
    ko_ref, slot = kickoff_ref(kickoff)
    ts = pd.DatetimeIndex([ko_ref + pd.Timedelta(hours=h) for h in HOURS])
    cal = calendar_table(pd.Series(ts)).set_index("ts")
    cells = B["cells"][B["cells"].stadium == stadium]
    rows = []
    for h, t in zip(HOURS, ts):
        c = cal.loc[t]
        same_day = float(t.date() == kickoff.date()) if match else 0.0
        for cell in cells.itertuples():
            rows.append(dict(
                geohash=cell.geohash, ring=cell.ring, h_rel_out=h, ts=t,
                hour=t.hour, dow=t.dayofweek, month=t.month, is_weekend=float(t.dayofweek >= 5),
                is_holiday=float(c.is_holiday), is_holiday_eve=float(c.is_holiday_eve),
                hour_sin=np.sin(2 * np.pi * t.hour / 24), hour_cos=np.cos(2 * np.pi * t.hour / 24),
                ring_k=cell.ring_k, ff_fit=cell.ff_fit, stadium=stadium, how=t.dayofweek * 24 + t.hour,
                is_match_day=same_day, any_big3_match_day=same_day,
                is_derby=float(attrs["is_derby"]) if match else 0.0,
                is_big_match=float(attrs["is_big_match"]) if match else 0.0,
                capacity_ev=float(C.STADIUMS[stadium]["capacity"]) if match else 0.0,
                h_rel=float(h) if match else np.nan,
                competition_type=competition if match else "none",
                kickoff_slot=slot if match else "none",
                opp_group=attrs["opp_group"] if match else "none"))
    d = pd.DataFrame(rows).merge(B["profile"], on=["geohash", "how"], how="left")
    for col, lev in M.CAT_LEVELS.items():
        d[col] = pd.Categorical(d[col], categories=lev)
    return d, ko_ref, slot


def predict_match(B, date: str, time_: str, stadium: str, opponent: str, competition: str) -> dict:
    kickoff = pd.Timestamp(f"{date} {time_}")
    attrs = describe_match(stadium, opponent, competition)
    res = {}
    for label, is_match in [("match", True), ("normal", False)]:
        d, ko_ref, slot = scenario_rows(B, stadium, kickoff, competition, attrs, is_match)
        X = d[B["X"]]
        proba = B["clf"].predict_proba(X)
        cls = list(B["clf"].classes_)
        for k, c in enumerate(cls):
            d[f"p_{c}"] = proba[:, k]
        d["cls"] = np.array(cls)[proba.argmax(1)]
        d["speed"] = B["reg"].predict(X)
        d["ratio"] = d.speed / d.ff_fit
        res[label] = d
    m, n = res["match"], res["normal"]
    near_m, near_n = m[m.ring.isin(NEAR)], n[n.ring.isin(NEAR)]

    def curve(dd):
        g = dd.groupby("h_rel_out")
        return dict(speed=g.speed.mean().round(2).tolist(),
                    p_congested=g.p_congested.mean().round(3).tolist(),
                    p_moderate=g.p_moderate.mean().round(3).tolist(),
                    p_free=g.p_free.mean().round(3).tolist(),
                    share_congested=g.cls.apply(lambda s: float((s == "congested").mean())).round(3).tolist())

    rings = {r: {"match": m[m.ring == r].groupby("h_rel_out").speed.mean().round(2).tolist(),
                 "normal": n[n.ring == r].groupby("h_rel_out").speed.mean().round(2).tolist()}
             for r in ["R0", "R1", "R2"]}
    per_cell = {}
    for gh, g in m.groupby("geohash"):
        g = g.sort_values("h_rel_out")
        gn = n[n.geohash == gh].sort_values("h_rel_out")
        per_cell[gh] = dict(ring=g.ring.iloc[0], speed=g.speed.round(1).tolist(), normal=gn.speed.round(1).tolist(),
                            ratio=g.ratio.round(3).tolist(), cls=g.cls.tolist(),
                            p_congested=g.p_congested.round(3).tolist())
    cm, cn = curve(near_m), curve(near_n)
    post = [i for i, h in enumerate(HOURS) if C.WINDOWS["post"][0] <= h <= C.WINDOWS["post"][1]]
    sp_m, sp_n = np.mean([cm["speed"][i] for i in post]), np.mean([cn["speed"][i] for i in post])
    peak = int(np.argmin(np.array(cm["speed"]) - np.array(cn["speed"])))

    # previous data: same stadium and kick-off slot, and earlier meetings with the same opponent
    past = B["past"]
    prof = B["past_profile"]
    pr = prof[(prof.stadium == stadium) & (prof.kickoff_slot == slot)].set_index("h_rel").reindex(HOURS)
    n_slot = B["past_n"]
    n_slot = n_slot[(n_slot.stadium == stadium) & (n_slot.kickoff_slot == slot)].n.sum()
    opp_up = tr_upper(opponent)
    key = re.sub(r"[^A-ZÇĞİÖŞÜ]", "", opp_up)[:6]
    same = past[(past.stadium == stadium) & past.opponent.map(tr_upper).str.contains(key, regex=False)] if key else past.iloc[:0]
    same = same.sort_values("date", ascending=False).head(6)
    observed = None
    hit = past[(past.stadium == stadium) & (past.date == date)]
    if len(hit) and hit.match_id.iloc[0] in B["past_hourly"]:
        ob = B["past_hourly"][hit.match_id.iloc[0]]
        observed = dict(match_id=hit.match_id.iloc[0], opponent=hit.opponent.iloc[0],
                        speed=[None if pd.isna(v) else float(v) for v in ob.speed_match])
    ko_ref, slot = kickoff_ref(kickoff)
    unc = uncertainty(B, kickoff, cm["speed"], sp_m, sp_n)
    return dict(
        input=dict(date=date, time=time_, stadium=stadium, opponent=opponent, competition=competition),
        match=dict(**{k: (bool(v) if isinstance(v, (bool, np.bool_)) else v) for k, v in attrs.items()},
                   kickoff_slot=slot, ko_ref=str(ko_ref)[:16], weekday=kickoff.day_name(),
                   holiday=bool(calendar_table(pd.Series([kickoff.floor("h")])).is_holiday.iloc[0])),
        hours=HOURS, clock=[str((ko_ref + pd.Timedelta(hours=h)).time())[:5] for h in HOURS],
        near=dict(match=cm, normal=cn), rings=rings, cells=per_cell,
        summary=dict(post_speed_match=round(float(sp_m), 2), post_speed_normal=round(float(sp_n), 2),
                     post_delta=round(float(sp_m - sp_n), 2), post_pct=round(float(100 * (sp_m - sp_n) / sp_n), 1),
                     peak_h=HOURS[peak], peak_clock=str((ko_ref + pd.Timedelta(hours=HOURS[peak])).time())[:5],
                     peak_speed=cm["speed"][peak], peak_normal=cn["speed"][peak],
                     peak_share_congested=cm["share_congested"][peak]),
        history=dict(slot_n=int(n_slot),
                     slot_match=[None if pd.isna(v) else float(v) for v in pr.speed_match],
                     slot_ctrl=[None if pd.isna(v) else float(v) for v in pr.speed_ctrl],
                     same_opponent=[dict(date=r.date, time=r.time, opponent=r.opponent, competition=r.competition,
                                         post_delta=None if pd.isna(r.d_speed) else round(float(r.d_speed), 2),
                                         pct_veh=None if pd.isna(r.pct_veh) else round(float(r.pct_veh), 1))
                                    for r in same.itertuples()],
                     observed=observed),
        months_after_data=int(round((kickoff - pd.Timestamp(B["data_end"])).days / 30.4)),
        uncertainty=unc,
    )


def uncertainty(B, kickoff, speed_match, sp_m, sp_n):
    """Error range from the back-test with the same gap between the data and the match (80 % of the errors)."""
    H = B.get("horizon")
    if not H or not H.get("bins"):
        return None
    months = (kickoff - pd.Timestamp(B["data_end"])).days / 30.44
    b = next((x for x in reversed(H["bins"]) if months >= x["lo"]), H["bins"][0])
    d = sp_m - sp_n
    return dict(months=round(months, 1), lo=b["lo"], hi=b["hi"], n_matches=b["n_matches"],
                max_tested=round(H["max_tested"], 1), beyond=bool(months > H["max_tested"]),
                post_mae_abs=round(b["post_mae_abs"], 2), post_mae_eff=round(b["post_mae_eff"], 2),
                band_lo=[round(v - b["abs_q90"], 2) for v in speed_match],
                band_hi=[round(v - b["abs_q10"], 2) for v in speed_match],
                post_speed_range=[round(sp_m - b["post_abs_q90"], 1), round(sp_m - b["post_abs_q10"], 1)],
                post_delta_range=[round(d - b["post_eff_q90"], 1), round(d - b["post_eff_q10"], 1)],
                bins=[dict(lo=x["lo"], hi=x["hi"], n_matches=x["n_matches"], post_mae_abs=round(x["post_mae_abs"], 2),
                           post_mae_eff=round(x["post_mae_eff"], 2)) for x in H["bins"]])
