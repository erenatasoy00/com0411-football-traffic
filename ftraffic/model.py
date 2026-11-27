"""Phase 2, part B - prediction models (requirement (iv) of the brief).

Prediction task
---------------
Day-ahead prediction for every cell-hour around the three stadiums: a traffic
operator wants to know today what will happen tomorrow at each hour. A feature
is therefore allowed only if it is known at least 24 hours before the target
hour: traffic history (lags >= 24 h), calendar, weather (reanalysis used as a
stand-in for a forecast) and the published fixture.

Targets (defined in Phase 1, re-fitted here without leakage)
-------------------------------------------------------------
T2 congestion class (primary, 3 classes), T1 average speed (regression) and
T3 abnormal slowdown (rare binary event). Free-flow speed and the hour-of-week
baselines that define T2 and T3 are computed on the fitting period only.

Validation
----------
Forward-chaining hold-out instead of random K-fold: neighbouring hours are
almost identical, so random folds would leak. Models are selected on
train 2022-23 -> validate 2023-24, then refitted on 2022-24 and tested once on
2024-25.
"""
from __future__ import annotations

import json
import re
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (HistGradientBoostingClassifier, HistGradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score,
                             confusion_matrix, f1_score, mean_absolute_error, mean_squared_error,
                             precision_recall_fscore_support, r2_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import config as C
from .stats_extra import ISTANBUL_CLUBS, season_of

OUT_T = C.OUT_TABLES / "phase2"
OUT_F = C.OUT_FIGS / "phase2"
MODEL_RINGS = ["R0", "R1", "R2"]
SPLITS = {"selection": (["2022-23"], ["2023-24"]),
          "final": (["2022-23", "2023-24"], ["2024-25"])}
CLASSES = ["free", "moderate", "congested"]
RF_MAX_ROWS = 300_000          # random forests are trained on a random subsample (time)
SEED = C.SEED

# ----------------------------------------------------------------- feature groups
# tree models (HGB) use the 'tree' columns; linear models and random forests use one-hot 'lin' columns
GROUPS = {
    "calendar": dict(num=["is_weekend", "is_holiday", "is_holiday_eve", "hour_sin", "hour_cos"],
                     tree_num=["hour", "dow", "month"], cat=["hour_c", "dow_c", "month_c"]),
    "weather": dict(num=["temperature_2m", "precipitation", "rain", "snowfall", "relative_humidity_2m",
                         "cloud_cover", "wind_speed_10m", "wind_gusts_10m", "is_rain", "is_heavy_rain"]),
    "spatial": dict(num=["ring_k", "ff_fit"], cat=["stadium"], tree_cat=["stadium"]),
    "history": dict(num=["speed_lag24", "speed_lag48", "speed_lag168", "speed_base4w", "lveh_lag24",
                         "lveh_lag168", "ratio_lag24", "ratio_lag168", "ratio_base4w", "how_mean_fit",
                         "how_ratio_fit"]),
    "event": dict(num=["is_match_day", "any_big3_match_day", "is_derby", "is_big_match", "capacity_ev"],
                  tree_num=["h_rel"], cat=["h_rel_c", "competition_type", "kickoff_slot", "opp_group"],
                  tree_cat=["competition_type", "kickoff_slot", "opp_group"]),
}
CAT_LEVELS = {
    "stadium": list(C.STADIUMS), "competition_type": ["none", "league", "domestic_cup", "european"],
    "kickoff_slot": ["none", "afternoon", "early_evening", "late_evening"],
    "opp_group": ["none", "big_match", "istanbul", "other_domestic", "european"],
}


def cols(groups, kind):
    """Columns of the given feature groups: kind 'tree' (HGB) or 'lin' (one-hot models)."""
    num, cat = [], []
    for g in groups:
        d = GROUPS[g]
        num += d["num"]
        if kind == "tree":
            num += d.get("tree_num", [])
            cat += d.get("tree_cat", [])
        else:
            cat += d.get("cat", [])
    return num, cat


ALL_GROUPS = list(GROUPS)
NO_EVENT = [g for g in GROUPS if g != "event"]


# ----------------------------------------------------------------- data
def base_frame(pnl: pd.DataFrame) -> pd.DataFrame:
    """Cell-hours of the analysed R0-R2 cells in the main seasons, plus fit-independent features."""
    keep = ["geohash", "ts", "stadium", "ring", "ring_k", "avg_speed", "log_vehicles", "low_sample", "how",
            "hour", "dow", "month", "is_weekend", "is_holiday", "is_holiday_eve", "is_match_day",
            "any_big3_match_day", "match_id", "h_rel", "window", "competition_type", "kickoff_slot",
            "is_derby", "is_big_match", "capacity", "opponent"] + GROUPS["weather"]["num"]
    d = pnl.loc[pnl.cell_ok & pnl.ring.isin(MODEL_RINGS), keep].copy()
    d["season"] = season_of(d.ts)
    d = d[d.season.notna()].reset_index(drop=True)

    # --- traffic history: values of the same cell L hours earlier (time-indexed, so season gaps stay NaN)
    full = pd.date_range(d.ts.min(), d.ts.max(), freq="h")
    ws = d.pivot(index="ts", columns="geohash", values="avg_speed").reindex(full)
    wv = d.pivot(index="ts", columns="geohash", values="log_vehicles").reindex(full)
    lagged = {"speed_lag24": ws.shift(24), "speed_lag48": ws.shift(48), "speed_lag168": ws.shift(168),
              "lveh_lag24": wv.shift(24), "lveh_lag168": wv.shift(168)}
    stack4 = np.stack([ws.shift(168 * k).to_numpy() for k in range(1, 5)])
    with np.errstate(all="ignore"):
        cnt = np.isfinite(stack4).sum(0)
        base = np.where(cnt >= 2, np.nanmean(stack4, 0), np.nan)
    lagged["speed_base4w"] = pd.DataFrame(base, index=ws.index, columns=ws.columns)
    key = pd.MultiIndex.from_arrays([d.ts, d.geohash])
    for name, w in lagged.items():
        d[name] = w.stack(future_stack=True).reindex(key).to_numpy()

    # --- calendar encodings
    d["hour_sin"], d["hour_cos"] = np.sin(2 * np.pi * d.hour / 24), np.cos(2 * np.pi * d.hour / 24)
    for c in ["hour", "dow", "month"]:
        d[f"{c}_c"] = d[c].astype(str)

    # --- event features (published fixture -> known in advance)
    in_span = d.match_id.notna()
    d["h_rel"] = d.h_rel.where(in_span)
    d["h_rel_c"] = np.where(in_span, d.h_rel.fillna(0).astype(int).astype(str), "none")
    for c in ["is_derby", "is_big_match"]:
        d[c] = d[c].fillna(False).astype(bool)
    d["capacity_ev"] = d.capacity.where(in_span, 0).fillna(0)
    d["competition_type"] = d.competition_type.where(in_span, "none").fillna("none")
    d["kickoff_slot"] = d.kickoff_slot.where(in_span, "none").fillna("none")
    opp = d.opponent.fillna("").str.upper()
    d["opp_group"] = np.select(
        [~in_span, d.is_big_match, d.competition_type == "european", opp.str.contains(ISTANBUL_CLUBS, regex=True)],
        ["none", "big_match", "european", "istanbul"], default="other_domestic")
    for c, lev in CAT_LEVELS.items():
        d[c] = pd.Categorical(d[c], categories=lev)
    for c in ["is_weekend", "is_holiday", "is_holiday_eve", "is_match_day", "any_big3_match_day",
              "is_rain", "is_heavy_rain", "is_derby", "is_big_match"]:
        d[c] = d[c].astype(float)
    d["slice_match"] = d.window.isin(["pre", "during", "post"])
    return d


def fit_split(d: pd.DataFrame, fit_seasons: list) -> pd.DataFrame:
    """Baselines from the fitting period only -> targets and baseline-dependent features."""
    d = d.copy()
    fit = d[d.season.isin(fit_seasons) & d.avg_speed.notna() & ~d.low_sample]
    night = fit[fit.hour.between(1, 4) & (fit.is_match_day == 0)]
    ff = night.groupby("geohash").avg_speed.quantile(0.85)
    d["ff_fit"] = d.geohash.map(ff)
    how = fit.groupby(["geohash", "how"]).avg_speed.agg(["mean", "std"])
    idx = pd.MultiIndex.from_arrays([d.geohash, d.how])
    d["how_mean_fit"] = how["mean"].reindex(idx).to_numpy()
    d["how_sd_fit"] = how["std"].reindex(idx).to_numpy()
    d["how_ratio_fit"] = d.how_mean_fit / d.ff_fit
    for c in ["lag24", "lag168"]:
        d[f"ratio_{c}"] = d[f"speed_{c}"] / d.ff_fit
    d["ratio_base4w"] = d.speed_base4w / d.ff_fit
    # targets
    d["valid"] = d.avg_speed.notna() & ~d.low_sample & d.ff_fit.notna() & d.how_sd_fit.gt(0)
    ratio = d.avg_speed / d.ff_fit
    d["y_t1"] = d.avg_speed
    d["y_t2"] = pd.cut(ratio, bins=C.CONGESTION_BINS, labels=C.CONGESTION_LABELS, right=False).astype(object)
    d["y_t3"] = ((d.avg_speed - d.how_mean_fit) / d.how_sd_fit < C.ABNORMAL_Z).astype(float)
    return d


def ratio_class(r):
    return pd.cut(pd.Series(r), bins=C.CONGESTION_BINS, labels=C.CONGESTION_LABELS, right=False).astype(object).to_numpy()


# ----------------------------------------------------------------- models
def lin_pre(num, cat, scale=True):
    steps = [("imp", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        steps.append(("sc", StandardScaler()))
    return ColumnTransformer([("num", Pipeline(steps), num),
                              ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), cat)],
                             sparse_threshold=0.0)


def make_model(name, task, groups, params=None):
    params = params or {}
    if name.startswith("hgb"):
        num, cat = cols(groups, "tree")
        if task in ("clf", "bin"):
            est = HistGradientBoostingClassifier(categorical_features="from_dtype", random_state=SEED,
                                                 **{"max_iter": 300, "learning_rate": 0.1, **params})
        else:
            est = HistGradientBoostingRegressor(categorical_features="from_dtype", random_state=SEED,
                                                **{"max_iter": 300, "learning_rate": 0.1, **params})
        return est, num + cat
    num, cat = cols(groups, "lin")
    if name == "linear":
        est = (LogisticRegression(max_iter=400, class_weight="balanced", C=1.0) if task in ("clf", "bin")
               else Ridge(alpha=1.0))
        return Pipeline([("pre", lin_pre(num, cat)), ("m", est)]), num + cat
    if name == "rf":
        kw = dict(n_estimators=150, max_depth=18, min_samples_leaf=20, max_features="sqrt", n_jobs=-1,
                  random_state=SEED)
        est = (RandomForestClassifier(class_weight="balanced_subsample", **kw) if task in ("clf", "bin")
               else RandomForestRegressor(**kw))
        return Pipeline([("pre", lin_pre(num, cat, scale=False)), ("m", est)]), num + cat
    raise ValueError(name)


def fit_predict(name, task, groups, tr, te, ycol, params=None):
    est, X = make_model(name, task, groups, params)
    trv = tr[tr.valid]
    if name == "rf" and len(trv) > RF_MAX_ROWS:
        trv = trv.sample(RF_MAX_ROWS, random_state=SEED)
    y = trv[ycol]
    est.fit(trv[X], y.astype(int) if task == "bin" else y)
    if task == "bin":
        return est, X, est.predict_proba(te[X])[:, 1]
    return est, X, est.predict(te[X])


# ----------------------------------------------------------------- metrics
def clf_metrics(y, p):
    f1s = f1_score(y, p, labels=CLASSES, average=None, zero_division=0)
    return dict(n=int(len(y)), accuracy=accuracy_score(y, p), macro_f1=f1_score(y, p, labels=CLASSES, average="macro", zero_division=0),
                balanced_acc=balanced_accuracy_score(y, p), f1_free=f1s[0], f1_moderate=f1s[1], f1_congested=f1s[2])


def reg_metrics(y, p):
    return dict(n=int(len(y)), mae=mean_absolute_error(y, p), rmse=float(np.sqrt(mean_squared_error(y, p))),
                r2=r2_score(y, p))


def bin_metrics(y, s, thr):
    y = np.asarray(y).astype(int)
    out = dict(n=int(len(y)), prevalence=float(y.mean()))
    if y.min() == y.max():
        return out
    pr, rc, f1, _ = precision_recall_fscore_support(y, (s >= thr).astype(int), average="binary", zero_division=0)
    out.update(pr_auc=average_precision_score(y, s), roc_auc=roc_auc_score(y, s), precision=pr, recall=rc, f1=f1)
    return out


SLICES = {"all": lambda d: d.valid,
          "match": lambda d: d.valid & d.slice_match,
          "match_near": lambda d: d.valid & d.slice_match & d.ring.isin(["R0", "R1"]),
          "post_near": lambda d: d.valid & (d.window == "post") & d.ring.isin(["R0", "R1"])}


def evaluate(te, pred, task, thr=0.5):
    out = {}
    for s, f in SLICES.items():
        m = f(te).to_numpy()
        ycol = {"clf": "y_t2", "reg": "y_t1", "bin": "y_t3"}[task]
        y, p = te.loc[m, ycol].to_numpy(), np.asarray(pred)[m]
        out[s] = (clf_metrics(y, p) if task == "clf" else reg_metrics(y, p) if task == "reg"
                  else bin_metrics(y, p, thr))
    return out


def best_threshold(y, s):
    best = (0.5, -1)
    for t in np.quantile(s, np.linspace(0.80, 0.999, 120)):
        f = f1_score(np.asarray(y).astype(int), (s >= t).astype(int), zero_division=0)
        if f > best[1]:
            best = (float(t), f)
    return best[0]


# ----------------------------------------------------------------- experiments
def baselines(te, task):
    """B0 = same hour last week (falls back to the profile), B1 = cell hour-of-week profile of the fit period."""
    if task == "clf":
        r0 = te.ratio_lag168.fillna(te.how_ratio_fit)
        return {"b0_last_week": ratio_class(r0), "b1_profile": ratio_class(te.how_ratio_fit)}
    if task == "reg":
        return {"b0_last_week": te.speed_lag168.fillna(te.how_mean_fit).to_numpy(),
                "b1_profile": te.how_mean_fit.to_numpy()}
    z_last = (te.speed_lag168 - te.how_mean_fit) / te.how_sd_fit
    return {"b0_last_week": (-z_last).fillna(0).to_numpy()}


HGB_GRID = [dict(max_leaf_nodes=31, class_weight=None), dict(max_leaf_nodes=63, class_weight=None),
            dict(max_leaf_nodes=31, class_weight="balanced"), dict(max_leaf_nodes=63, class_weight="balanced")]


def run_split(d, split, tuned=None, log=print):
    fit_seasons, test_seasons = SPLITS[split]
    ds = fit_split(d, fit_seasons)
    tr, te = ds[ds.season.isin(fit_seasons)], ds[ds.season.isin(test_seasons) & ds.valid].reset_index(drop=True)
    R = {"rows": dict(train=int(tr.valid.sum()), test=int(len(te)), test_match=int(te.slice_match.sum())),
         "class_dist_train": (tr[tr.valid].y_t2.value_counts(normalize=True) * 100).round(1).to_dict(),
         "class_dist_test": (te.y_t2.value_counts(normalize=True) * 100).round(1).to_dict(),
         "t3_prev_train": float(tr[tr.valid].y_t3.mean()), "t3_prev_test": float(te.y_t3.mean()),
         "metrics": {}}
    preds, fitted = {}, {}
    t0 = time.time()
    # ---------------- T2 congestion class (primary)
    for b, p in baselines(te, "clf").items():
        R["metrics"][f"t2|{b}"] = evaluate(te, p, "clf")
    grid = HGB_GRID if tuned is None else [tuned["t2_hgb"]]
    best = None
    for prm in grid:
        prm2 = {k: v for k, v in prm.items()}
        est, X, p = fit_predict("hgb", "clf", ALL_GROUPS, tr, te, "y_t2", prm2)
        ev = evaluate(te, p, "clf")
        tag = f"t2|hgb leaves={prm['max_leaf_nodes']} cw={prm['class_weight']}"
        R["metrics"][tag] = ev
        log(f"  [{split}] {tag}: macroF1 all={ev['all']['macro_f1']:.3f} match={ev['match']['macro_f1']:.3f} ({time.time()-t0:.0f}s)")
        if best is None or ev["all"]["macro_f1"] > best[0]:
            best = (ev["all"]["macro_f1"], prm, est, X, p)
    R["t2_hgb_best"] = best[1]
    R["metrics"]["t2|hgb"] = evaluate(te, best[4], "clf")
    preds["t2|hgb"], fitted["t2|hgb"] = best[4], (best[2], best[3])
    est, X, p = fit_predict("hgb", "clf", NO_EVENT, tr, te, "y_t2", best[1])
    R["metrics"]["t2|hgb_no_event"], preds["t2|hgb_no_event"] = evaluate(te, p, "clf"), p
    for name in ["linear", "rf"]:
        est, X, p = fit_predict(name, "clf", ALL_GROUPS, tr, te, "y_t2")
        R["metrics"][f"t2|{name}"], preds[f"t2|{name}"] = evaluate(te, p, "clf"), p
        log(f"  [{split}] t2|{name}: macroF1 all={R['metrics'][f't2|{name}']['all']['macro_f1']:.3f} ({time.time()-t0:.0f}s)")
    # ---------------- T1 average speed (regression)
    for b, p in baselines(te, "reg").items():
        R["metrics"][f"t1|{b}"] = evaluate(te, p, "reg")
    hgb_reg = {"max_leaf_nodes": best[1]["max_leaf_nodes"]}
    for name, groups in [("hgb", ALL_GROUPS), ("hgb_no_event", NO_EVENT), ("linear", ALL_GROUPS), ("rf", ALL_GROUPS)]:
        est, X, p = fit_predict("hgb" if name.startswith("hgb") else name, "reg", groups, tr, te, "y_t1",
                                hgb_reg if name.startswith("hgb") else None)
        R["metrics"][f"t1|{name}"], preds[f"t1|{name}"] = evaluate(te, p, "reg"), p
        log(f"  [{split}] t1|{name}: MAE all={R['metrics'][f't1|{name}']['all']['mae']:.2f} ({time.time()-t0:.0f}s)")
    # ---------------- T3 abnormal slowdown (rare binary event)
    for b, s in baselines(te, "bin").items():
        thr = tuned["t3_thr"].get(b, 0.5) if tuned else best_threshold(te.y_t3, s)
        R.setdefault("t3_thr", {})[b] = thr
        R["metrics"][f"t3|{b}"] = evaluate(te, s, "bin", thr)
    for name, groups in [("hgb", ALL_GROUPS), ("hgb_no_event", NO_EVENT), ("linear", ALL_GROUPS)]:
        est, X, s = fit_predict("hgb" if name.startswith("hgb") else name, "bin", groups, tr, te, "y_t3",
                                hgb_reg if name.startswith("hgb") else None)
        # the decision threshold is chosen on the validation season and reused on the test season
        thr = tuned["t3_thr"].get(name, 0.5) if tuned else best_threshold(te.y_t3, s)
        R.setdefault("t3_thr", {})[name] = thr
        R["metrics"][f"t3|{name}"], preds[f"t3|{name}"] = evaluate(te, s, "bin", thr), s
        log(f"  [{split}] t3|{name}: PR-AUC all={R['metrics'][f't3|{name}']['all'].get('pr_auc', float('nan')):.3f} ({time.time()-t0:.0f}s)")
    return R, te, preds, fitted


# ----------------------------------------------------------------- importance
def group_importance(est, X, te, n_rep=3):
    """Permutation importance per feature group: shuffle all columns of a group together
    and measure the drop in macro-F1 (all hours and match windows)."""
    rng = np.random.default_rng(SEED)
    sub = te.sample(min(len(te), 200_000), random_state=SEED)
    sub = pd.concat([sub, te[te.slice_match]]).drop_duplicates(subset=["geohash", "ts"])
    m = sub.slice_match.to_numpy()
    base = est.predict(sub[X])
    f_all = f1_score(sub.y_t2, base, average="macro")
    f_m = f1_score(sub.y_t2[m], base[m], average="macro")
    rows = []
    for g in GROUPS:
        gcols = [c for c in X if c in sum(cols([g], "tree"), [])]
        drops_a, drops_m = [], []
        for _ in range(n_rep):
            sh = sub[X].copy()
            perm = rng.permutation(len(sh))
            sh[gcols] = sh[gcols].iloc[perm].set_axis(sh.index)
            p = est.predict(sh)
            drops_a.append(f_all - f1_score(sub.y_t2, p, average="macro"))
            drops_m.append(f_m - f1_score(sub.y_t2[m], p[m], average="macro"))
        rows.append(dict(group=g, n_features=len(gcols), drop_macro_f1_all=np.mean(drops_a),
                         drop_macro_f1_match=np.mean(drops_m)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- figures
MODEL_LABEL = {"b0_last_week": "Same hour last week", "b1_profile": "Hour-of-week profile",
               "linear": "Logistic / linear regression", "rf": "Random forest",
               "hgb_no_event": "Gradient boosting, no match features", "hgb": "Gradient boosting (all features)"}


def fig_comparison(M):
    names = ["b0_last_week", "b1_profile", "linear", "rf", "hgb_no_event", "hgb"]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    y = np.arange(len(names))
    a = [M[f"t2|{n}"]["all"]["macro_f1"] for n in names]
    b = [M[f"t2|{n}"]["match"]["macro_f1"] for n in names]
    ax.barh(y + 0.2, a, 0.38, color="#9db7d8", label="All hours")
    ax.barh(y - 0.2, b, 0.38, color="#2a78d6", label="Match windows")
    for yi, v in zip(y + 0.2, a):
        ax.text(v + 0.005, yi, f"{v:.2f}", va="center", fontsize=8)
    for yi, v in zip(y - 0.2, b):
        ax.text(v + 0.005, yi, f"{v:.2f}", va="center", fontsize=8)
    ax.set_yticks(y, [MODEL_LABEL[n] for n in names])
    ax.set_xlabel("Macro-F1, congestion class (test season 2024-25)")
    ax.set_xlim(0, max(a + b) * 1.12)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_F / "fig_model_comparison.png", dpi=200)
    plt.close(fig)


def fig_event_study(te, preds):
    m = te.slice_match | (te.window == "other")
    d = te[m & te.ring.isin(["R0", "R1"])].copy()
    d["full"] = preds["t1|hgb"][m.to_numpy() & te.ring.isin(["R0", "R1"]).to_numpy()]
    d["noev"] = preds["t1|hgb_no_event"][m.to_numpy() & te.ring.isin(["R0", "R1"]).to_numpy()]
    g = d.groupby("h_rel")[["y_t1", "full", "noev"]].mean()
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.axvspan(-0.5, 1.5, color="#eadcb5", alpha=0.6, lw=0)
    ax.plot(g.index, g.y_t1, color="#0b0b0b", lw=2.2, label="Observed")
    ax.plot(g.index, g.full, color="#2a78d6", lw=1.8, label="Predicted, with match features")
    ax.plot(g.index, g.noev, color="#eb6834", lw=1.8, ls="--", label="Predicted, without match features")
    ax.set_xlabel("Hours relative to kick-off")
    ax.set_ylabel("Mean speed, NEAR ring (km/h)")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e5e5", lw=0.6)
    fig.tight_layout()
    fig.savefig(OUT_F / "fig_event_study_predicted.png", dpi=200)
    plt.close(fig)
    return g.round(2).reset_index().to_dict("records")


def fig_confusion(te, p):
    m = te.slice_match.to_numpy()
    cm = confusion_matrix(te.y_t2[m], p[m], labels=CLASSES, normalize="true") * 100
    fig, ax = plt.subplots(figsize=(4.4, 3.6))
    ax.imshow(cm, cmap="Blues", vmin=0, vmax=100)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{cm[i, j]:.0f}%", ha="center", va="center", color="white" if cm[i, j] > 55 else "#0b0b0b")
    ax.set_xticks(range(3), CLASSES)
    ax.set_yticks(range(3), CLASSES)
    ax.set_xlabel("Predicted class")
    ax.set_ylabel("Observed class")
    fig.tight_layout()
    fig.savefig(OUT_F / "fig_confusion_match.png", dpi=200)
    plt.close(fig)
    return np.round(cm, 1).tolist()


def fig_importance(imp):
    imp = imp.sort_values("drop_macro_f1_all")
    fig, ax = plt.subplots(figsize=(7, 3.2))
    y = np.arange(len(imp))
    ax.barh(y + 0.2, imp.drop_macro_f1_all, 0.38, color="#9db7d8", label="All hours")
    ax.barh(y - 0.2, imp.drop_macro_f1_match, 0.38, color="#2a78d6", label="Match windows")
    ax.set_yticks(y, imp.group)
    ax.set_xlabel("Drop in macro-F1 when the group is shuffled")
    ax.legend(frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_F / "fig_group_importance.png", dpi=200)
    plt.close(fig)


# ----------------------------------------------------------------- calibration and error analysis
def calibration(te, preds, est_t2, X_t2):
    """Secondary metrics required by the course roadmap: probability calibration.
    T3 (binary): Brier score and reliability curve. T2: multiclass log loss and Brier score,
    reliability of the 'congested' probability."""
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import brier_score_loss, log_loss
    out, curves = {}, {}
    y3 = te.y_t3.to_numpy().astype(int)
    for name in ["hgb", "hgb_no_event", "linear"]:
        s = np.asarray(preds[f"t3|{name}"])
        out[f"t3|{name}"] = dict(brier=brier_score_loss(y3, s), brier_ref=float(y3.mean() * (1 - y3.mean())),
                                 mean_pred=float(s.mean()), prevalence=float(y3.mean()))
        pt, pp = calibration_curve(y3, s, n_bins=10, strategy="quantile")
        curves[f"T3, {MODEL_LABEL[name]}"] = (pp, pt)
    P = est_t2.predict_proba(te[X_t2])
    cls = list(est_t2.classes_)
    Y = np.stack([(te.y_t2.to_numpy() == c).astype(int) for c in cls], 1)
    out["t2|hgb"] = dict(log_loss=log_loss(te.y_t2, P, labels=cls),
                         brier_multi=float(((P - Y) ** 2).sum(1).mean()),
                         brier_multi_ref=float(((Y.mean(0) - Y) ** 2).sum(1).mean()))
    k = cls.index("congested")
    pt, pp = calibration_curve(Y[:, k], P[:, k], n_bins=10, strategy="quantile")
    curves["T2 'congested', gradient boosting"] = (pp, pt)
    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    ax.plot([0, 1], [0, 1], color="#888", lw=0.8, ls=":")
    for (lab, (pp, pt)), col in zip(curves.items(), ["#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b"]):
        ax.plot(pp, pt, marker="o", ms=3, lw=1.4, color=col, label=lab)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed frequency")
    ax.legend(frameon=False, fontsize=7, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_F / "fig_calibration.png", dpi=200)
    plt.close(fig)
    return out


def error_analysis(te, preds):
    """Where do the T1 / T2 errors occur? By stadium and window, and the matches with the
    largest post-match errors (test season, NEAR ring)."""
    d = te[["match_id", "stadium", "ring", "window", "y_t1", "y_t2", "competition_type", "is_derby"]].copy()
    d["win"] = np.where(d.window.isin(["pre", "during", "post"]), d.window, "no match")
    for n in ["hgb", "hgb_no_event"]:
        d[f"err_{n}"] = preds[f"t1|{n}"] - d.y_t1
        d[f"cls_{n}"] = preds[f"t2|{n}"]
    rows = []
    for (st, w), g in d.groupby(["stadium", "win"], observed=True):
        rows.append(dict(stadium=st, window=w, n=len(g),
                         mae_hgb=g.err_hgb.abs().mean(), bias_hgb=g.err_hgb.mean(),
                         mae_no_event=g.err_hgb_no_event.abs().mean(), bias_no_event=g.err_hgb_no_event.mean(),
                         f1_hgb=f1_score(g.y_t2, g.cls_hgb, labels=CLASSES, average="macro", zero_division=0),
                         f1_no_event=f1_score(g.y_t2, g.cls_hgb_no_event, labels=CLASSES, average="macro", zero_division=0)))
    by = pd.DataFrame(rows)
    by.to_csv(OUT_T / "model_error_by_stadium_window.csv", index=False)
    post = d[(d.window == "post") & d.ring.isin(["R0", "R1"])]
    worst = (post.groupby("match_id").agg(stadium=("stadium", "first"), competition=("competition_type", "first"),
                                          derby=("is_derby", "first"), n=("y_t1", "size"),
                                          observed=("y_t1", "mean"), bias_hgb=("err_hgb", "mean"),
                                          mae_hgb=("err_hgb", lambda e: e.abs().mean()))
             .sort_values("mae_hgb", ascending=False))
    worst.to_csv(OUT_T / "model_error_by_match_post.csv")
    return by, worst


def cluster_bootstrap(te, preds, n_boot=2000):
    """Gain from the match features in the match windows, with a bootstrap over matches
    (cell-hours of one match are not independent, so whole matches are resampled)."""
    m = te.slice_match.to_numpy()
    d = pd.DataFrame(dict(match=te.match_id.to_numpy()[m], y1=te.y_t1.to_numpy()[m], y2=te.y_t2.to_numpy()[m],
                          a1=np.asarray(preds["t1|hgb"])[m], b1=np.asarray(preds["t1|hgb_no_event"])[m],
                          a2=np.asarray(preds["t2|hgb"])[m], b2=np.asarray(preds["t2|hgb_no_event"])[m]))
    groups = {k: g for k, g in d.groupby("match")}
    keys = np.array(list(groups))
    rng = np.random.default_rng(SEED)

    def stat(dd):
        return ((dd.b1 - dd.y1).abs().mean() - (dd.a1 - dd.y1).abs().mean(),
                f1_score(dd.y2, dd.a2, labels=CLASSES, average="macro", zero_division=0)
                - f1_score(dd.y2, dd.b2, labels=CLASSES, average="macro", zero_division=0))
    est = stat(d)
    bs = np.array([stat(pd.concat([groups[k] for k in rng.choice(keys, len(keys))])) for _ in range(n_boot)])
    lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
    return dict(n_matches=int(len(keys)), d_mae=est[0], d_mae_ci=[lo[0], hi[0]], d_f1=est[1], d_f1_ci=[lo[1], hi[1]],
                share_mae_gain_positive=float((bs[:, 0] > 0).mean()), share_f1_gain_positive=float((bs[:, 1] > 0).mean()))


HYPERPARAMETERS = {
    "Logistic regression (T2, T3)": "L2 penalty, C = 1.0, class_weight = balanced, lbfgs, max_iter = 400; "
                                    "one-hot categoricals, median imputation + missing indicators, z-score scaling",
    "Ridge regression (T1)": "alpha = 1.0; same preprocessing as the logistic regression",
    "Random forest (T1, T2)": "150 trees, max_depth = 18, min_samples_leaf = 20, max_features = sqrt, "
                              "class_weight = balanced_subsample (T2); trained on 300,000 sampled rows",
    "Gradient boosting (T1, T2, T3)": "HistGradientBoosting, learning_rate = 0.1, max_iter = 300, "
                                      "max_leaf_nodes chosen from {31, 63}, class_weight from {none, balanced} "
                                      "on the validation season; native categorical and missing-value handling",
}


# ----------------------------------------------------------------- entry point
def flat_table(M, task):
    rows = []
    for k, v in M.items():
        t, name = k.split("|")
        if t != task:
            continue
        for s, mm in v.items():
            rows.append(dict(model=name, slice=s, **mm))
    return pd.DataFrame(rows)


def run(pnl: pd.DataFrame, fx: pd.DataFrame, log=print) -> dict:
    t0 = time.time()
    d = base_frame(pnl)
    log(f"[model] base frame {len(d):,} rows, {d.geohash.nunique()} cells ({time.time()-t0:.0f}s)")
    V = {"cells": int(d.geohash.nunique()), "cells_by_ring": d.groupby("ring").geohash.nunique().to_dict()}
    Rs, te_s, _, _ = run_split(d, "selection", log=log)
    tuned = {"t2_hgb": Rs["t2_hgb_best"], "t3_thr": Rs["t3_thr"]}
    V["selection"] = Rs
    Rf, te, preds, fitted = run_split(d, "final", tuned=tuned, log=log)
    V["final"] = Rf
    for task in ["t1", "t2", "t3"]:
        flat_table(Rs["metrics"], task).to_csv(OUT_T / f"model_{task}_validation_2023-24.csv", index=False)
        flat_table(Rf["metrics"], task).to_csv(OUT_T / f"model_{task}_test_2024-25.csv", index=False)
    est, X = fitted["t2|hgb"]
    imp = group_importance(est, X, te)
    imp.to_csv(OUT_T / "model_group_importance.csv", index=False)
    V["importance"] = imp.round(4).to_dict("records")
    fig_comparison(Rf["metrics"])
    fig_importance(imp)
    V["confusion_match"] = fig_confusion(te, preds["t2|hgb"])
    V["event_study_pred"] = fig_event_study(te, preds)
    # post-match congested share: observed vs predicted (NEAR ring, test season)
    m = (te.window == "post") & te.ring.isin(["R0", "R1"])
    V["post_congested_share"] = dict(observed=float((te.y_t2[m] == "congested").mean() * 100),
                                     hgb=float((preds["t2|hgb"][m.to_numpy()] == "congested").mean() * 100),
                                     hgb_no_event=float((preds["t2|hgb_no_event"][m.to_numpy()] == "congested").mean() * 100))
    V["calibration"] = calibration(te, preds, est, X)
    by, worst = error_analysis(te, preds)
    V["error_by_stadium_window"] = by.round(3).to_dict("records")
    V["error_worst_matches"] = worst.head(8).round(2).reset_index().to_dict("records")
    V["error_match_count"] = int(len(worst))
    V["bootstrap"] = cluster_bootstrap(te, preds)
    V["hyperparameters"] = HYPERPARAMETERS
    log(f"[model] finished in {time.time()-t0:.0f}s")
    return V
