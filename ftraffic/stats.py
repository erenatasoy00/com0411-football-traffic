"""Step 6 - statistical analysis, result tables, figures and report values.

Unit of analysis = one match (window-averaged, ring-aggregated effect), which
avoids treating correlated cell-hours as independent observations.
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from . import config as cfg

ST_ORDER = ["RAMS", "SARACOGLU", "TUPRAS"]
ST_LABEL = {"RAMS": "Rams Park", "SARACOGLU": "Şükrü Saracoğlu", "TUPRAS": "Tüpraş", "ALL": "Pooled"}
WIN = ["pre", "during", "post"]
COLORS = {"RAMS": "#2a78d6", "SARACOGLU": "#eb6834", "TUPRAS": "#1baf7a", "ALL": "#0b0b0b"}  # validated categorical slots 1-3 + neutral ink for pooled


# ---------------------------------------------------------------- formatting
def f(x, d=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    s = f"{x:.{d}f}"
    return s.replace("-", "−")


def fp(p):
    if p is None or not np.isfinite(p):
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def fq(q, name="q"):
    """'q < 0.001' or 'q = 0.034' for use in running text."""
    if q is None or not np.isfinite(q):
        return f"{name} n/a"
    return f"{name} < 0.001" if q < 0.001 else f"{name} = {q:.3f}"


NICE = {"RAMS": "Rams Park", "SARACOGLU": "Şükrü Saracoğlu", "TUPRAS": "Tüpraş",
        "early_evening": "early evening", "late_evening": "late evening", "domestic_cup": "domestic cup"}


def t_ci(x, conf=0.95):
    """Mean with a t-distribution confidence interval (Lab 06, Procedure 7)."""
    x = pd.Series(x, dtype=float).dropna()
    if len(x) < 3:
        return np.nan, np.nan, np.nan
    m = x.mean()
    lo, hi = stats.t.interval(conf, len(x) - 1, loc=m, scale=stats.sem(x))
    return m, lo, hi


def paired_tests(x):
    """Tests of 'mean / median difference = 0' for match-minus-control differences.
    Returns (Shapiro-Wilk p, paired t-test p, Wilcoxon signed-rank p) - Lab 06, Procedures 2, 5 and 6."""
    x = pd.Series(x, dtype=float).dropna()
    if len(x) < 6:
        return np.nan, np.nan, np.nan
    sh = stats.shapiro(x).pvalue
    t = stats.ttest_1samp(x, 0).pvalue          # identical to ttest_rel(match, control)
    nz = x[x != 0]
    w = stats.wilcoxon(nz).pvalue if len(nz) >= 6 else np.nan
    return sh, t, w


def two_group_tests(a, b):
    """Levene -> Student or Welch t-test, plus Mann-Whitney U (Lab 06, Procedures 4 and 6)."""
    a, b = pd.Series(a, dtype=float).dropna(), pd.Series(b, dtype=float).dropna()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan, np.nan, ""
    lev = stats.levene(a, b).pvalue
    equal = lev >= cfg.ALPHA
    t = stats.ttest_ind(a, b, equal_var=equal).pvalue
    u = stats.mannwhitneyu(a, b, alternative="two-sided").pvalue
    return lev, t, u, ("" if equal else "W")


def pct_from_log(m):
    return 100 * (np.exp(m) - 1) if np.isfinite(m) else np.nan


# ---------------------------------------------------------------- main effects
def main_effects(ew: pd.DataFrame, ring="NEAR") -> pd.DataFrame:
    rows = []
    d = ew[ew.ring == ring]
    for st in ST_ORDER + ["ALL"]:
        ds = d if st == "ALL" else d[d.stadium == st]
        for w in WIN:
            x = ds[ds.window == w]
            sp, lv = x.d_speed.dropna(), x.d_lveh.dropna()
            m, lo, hi = t_ci(sp)
            vm, vlo, vhi = t_ci(lv)
            sh, pt, pw = paired_tests(sp)
            _, vpt, vpw = paired_tests(lv)
            rows.append(dict(stadium=st, window=w, n=len(sp), mean_d_speed=m, ci_lo=lo, ci_hi=hi,
                             median_d_speed=sp.median(), shapiro_p=sh, p_ttest_speed=pt,
                             p_wilcoxon_speed=pw, mean_pct_speed=x.pct_speed.mean(),
                             pct_veh=pct_from_log(vm), veh_ci_lo=pct_from_log(vlo),
                             veh_ci_hi=pct_from_log(vhi), p_ttest_veh=vpt, p_wilcoxon_veh=vpw))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- heterogeneity
COMPARISONS = [
    ("DERBY", "Derby vs other", "is_derby", True, False),
    ("WEEKEND", "Weekend vs weekday", "is_weekend", True, False),
    ("WET", "Wet vs dry", "is_wet", True, False),
    ("KO_AE", "Afternoon vs early evening", "kickoff_slot", "afternoon", "early_evening"),
    ("KO_AL", "Afternoon vs late evening", "kickoff_slot", "afternoon", "late_evening"),
    ("KO_EL", "Early vs late evening", "kickoff_slot", "early_evening", "late_evening"),
    ("COMP_LC", "League vs domestic cup", "competition_type", "league", "domestic_cup"),
    ("COMP_LE", "League vs European", "competition_type", "league", "european"),
    ("COMP_CE", "Domestic cup vs European", "competition_type", "domestic_cup", "european"),
    ("ST_RS", "Rams Park vs Şükrü Saracoğlu", "stadium", "RAMS", "SARACOGLU"),
    ("ST_RT", "Rams Park vs Tüpraş", "stadium", "RAMS", "TUPRAS"),
    ("ST_ST", "Şükrü Saracoğlu vs Tüpraş", "stadium", "SARACOGLU", "TUPRAS"),
]


def heterogeneity(ew: pd.DataFrame, ring="NEAR", window="post") -> pd.DataFrame:
    d = ew[(ew.ring == ring) & (ew.window == window)]
    rows = []
    for key, label, col, ga, gb in COMPARISONS:
        a = d.loc[d[col] == ga, "d_speed"].dropna()
        b = d.loc[d[col] == gb, "d_speed"].dropna()
        lev, t, u, kind = two_group_tests(a, b)
        rows.append(dict(key=key, comparison=label, n_a=len(a), n_b=len(b),
                         mean_a=a.mean() if len(a) else np.nan, mean_b=b.mean() if len(b) else np.nan,
                         levene_p=lev, t_p=t, welch=kind, mwu_p=u))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- correlations
CORR_VARS = [("KOHOUR", "Kick-off hour", "ko_hour"), ("TEMP", "Temperature at kick-off (°C)", "temp_ko"),
             ("DERBY", "Derby (0/1)", "is_derby"), ("WEEKEND", "Weekend (0/1)", "is_weekend"),
             ("WET", "Wet weather (0/1)", "is_wet")]


def correlations(ew: pd.DataFrame, fx: pd.DataFrame, ring="NEAR", window="post") -> pd.DataFrame:
    """Pearson, Spearman and Kendall correlation with the post-match effect (Lab 06, Procedure 6)."""
    d = ew[(ew.ring == ring) & (ew.window == window)].copy()
    ko = fx.set_index("match_id").kickoff
    d["ko_hour"] = d.match_id.map(ko).dt.hour + d.match_id.map(ko).dt.minute / 60
    rows = []
    for key, label, col in CORR_VARS:
        x = d[[col, "d_speed"]].dropna()
        a, b = x[col].astype(float), x.d_speed
        if len(x) < 5 or a.nunique() < 2:
            rows.append(dict(key=key, variable=label, n=len(x), r=np.nan, r_p=np.nan, rho=np.nan,
                             rho_p=np.nan, tau=np.nan, tau_p=np.nan))
            continue
        r, rho, tau = stats.pearsonr(a, b), stats.spearmanr(a, b), stats.kendalltau(a, b)
        rows.append(dict(key=key, variable=label, n=len(x), r=r[0], r_p=r[1], rho=rho[0], rho_p=rho[1],
                         tau=tau[0], tau_p=tau[1]))
    return pd.DataFrame(rows), d


# ---------------------------------------------------------------- robustness
def robustness(res: dict, ring="NEAR", window="post") -> pd.DataFrame:
    rows = []

    def summarise(name, x):
        x = pd.Series(x, dtype=float).dropna()
        m, lo, hi = t_ci(x)
        _, pt, pw = paired_tests(x)
        rows.append(dict(check=name, n=str(len(x)), estimate=m, ci_lo=lo, ci_hi=hi, p_t=pt, p_w=pw))

    ew = res["main"][1]
    pl = res.get("placebo_dates", (None, pd.DataFrame(), None))[1]
    cd = res.get("closed_doors", (None, pd.DataFrame(), None))[1]
    sel = lambda d, r=ring: d[(d.ring == r) & (d.window == window)] if len(d) else d
    summarise("placebo_dates", sel(pl).d_speed if len(pl) else [])
    summarise("closed_doors", sel(cd).d_speed if len(cd) else [])
    # closed-doors season vs main seasons: two independent samples
    a = sel(cd).d_speed.dropna() if len(cd) else pd.Series(dtype=float)
    b = sel(ew).d_speed.dropna()
    lev, t, u, _ = two_group_tests(a, b)
    rows.append(dict(check="cd_vs_main", n=f"{len(a)} / {len(b)}",
                     estimate=(a.mean() - b.mean()) if len(a) and len(b) else np.nan,
                     ci_lo=np.nan, ci_hi=np.nan, p_t=t, p_w=u))
    near = sel(ew).set_index("match_id").d_speed
    dist = sel(ew, "DISTAL").set_index("match_id").d_speed
    summarise("did_vs_distal", (near - dist).dropna())
    # spatial decay: paired comparisons of neighbouring rings (same match)
    piv = ew[(ew.window == window) & ew.ring.isin(["R0", "R1", "R2"])].pivot_table(
        index="match_id", columns="ring", values="d_speed")
    for a_, b_ in [("R0", "R1"), ("R1", "R2")]:
        if a_ in piv and b_ in piv:
            summarise(f"decay_{a_}{b_}".lower(), (piv[a_] - piv[b_]).dropna())
        else:
            summarise(f"decay_{a_}{b_}".lower(), [])
    ring_means = {r: piv[r].mean() if r in piv else np.nan for r in ["R0", "R1", "R2"]}
    return pd.DataFrame(rows), ring_means


# ---------------------------------------------------------------- figures
def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#dddddd", lw=0.6)
    ax.axvspan(cfg.WINDOWS["during"][0] - 0.5, cfg.WINDOWS["during"][1] + 0.5, color="#f2e6c9", zorder=0)


def fig_profiles(eh, path):
    d = eh[eh.ring == "NEAR"]
    fig, axes = plt.subplots(1, 3, figsize=(9, 4.5), sharey=False)
    for ax, st in zip(axes, ST_ORDER):
        x = d[d.stadium == st].groupby("h_rel")[["speed_match", "speed_ctrl"]].mean()
        _style(ax)
        if len(x):
            ax.plot(x.index, x.speed_ctrl, color="#52514e", lw=1.8, ls="--", label="Control days")
            ax.plot(x.index, x.speed_match, color=COLORS[st], lw=2.2, label="Match days")
        ax.set_title(ST_LABEL[st], fontsize=10)
        ax.set_xlabel("Hours relative to kick-off")
        ax.set_xticks(range(cfg.EVENT_SPAN[0], cfg.EVENT_SPAN[1] + 1, 2))
    axes[0].set_ylabel("Mean speed, R0+R1 cells (km/h)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def fig_event_study(eh, path):
    d = eh[eh.ring == "NEAR"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.5))
    for ax, col, lab in [(axes[0], "d_speed", "Δ speed vs controls (km/h)"),
                         (axes[1], "pct_veh", "Δ vehicles vs controls (%)")]:
        _style(ax)
        ax.axhline(0, color="black", lw=0.8)
        for st in ST_ORDER + ["ALL"]:
            x = d if st == "ALL" else d[d.stadium == st]
            g = x.groupby("h_rel")[col]
            m = g.mean()
            if not len(m):
                continue
            ci = g.apply(lambda s: pd.Series(t_ci(s)[1:], index=["lo", "hi"])).unstack()
            lw = 2.4 if st == "ALL" else 1.6
            ax.plot(m.index, m.values, color=COLORS[st], lw=lw, label=ST_LABEL[st])
            if st == "ALL":
                ax.fill_between(m.index, ci.lo, ci.hi, color=COLORS[st], alpha=0.12, lw=0,
                                label="Pooled 95% CI" if col == "d_speed" else None)
        ax.set_xlabel("Hours relative to kick-off")
        ax.set_ylabel(lab)
        ax.set_xticks(range(cfg.EVENT_SPAN[0], cfg.EVENT_SPAN[1] + 1, 2))
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def fig_heterogeneity(ew, path):
    d = ew[(ew.ring == "NEAR") & (ew.window == "post")].copy()
    fig, axes = plt.subplots(1, 3, figsize=(9, 4.5), sharey=True)
    specs = [("is_derby", {True: "Derby", False: "Other"}), ("kickoff_slot", None),
             ("is_wet", {True: "Wet", False: "Dry"})]
    titles = ["Derby status", "Kick-off slot", "Weather"]
    for ax, (col, lab), tt in zip(axes, specs, titles):
        ax.spines[["top", "right"]].set_visible(False)
        ax.axhline(0, color="black", lw=0.8)
        groups = [(k, g.d_speed.dropna().values) for k, g in d.groupby(col)]
        groups = [(lab.get(k, k) if lab else str(k).replace("_", " "), v) for k, v in groups if len(v)]
        if groups:
            ax.boxplot([v for _, v in groups], tick_labels=[k for k, _ in groups], widths=0.5,
                       medianprops=dict(color="#2a78d6", lw=2), flierprops=dict(markersize=3))
        ax.set_title(tt, fontsize=10)
        ax.tick_params(axis="x", labelsize=8)
    axes[0].set_ylabel("Post-match Δ speed, R0+R1 (km/h)")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def fig_normality(ew, path):
    """Histogram and Q-Q plot of the pooled post-match effect (Lab 05 / Lab 06 normality diagnostics)."""
    x = ew[(ew.ring == "NEAR") & (ew.window == "post")].d_speed.dropna()
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    axes[0].hist(x, bins=20, color=COLORS["RAMS"], edgecolor="white")
    axes[0].axvline(x.mean(), color="black", lw=1.2, label=f"mean {x.mean():.2f}")
    axes[0].axvline(x.median(), color="black", lw=1.2, ls="--", label=f"median {x.median():.2f}")
    axes[0].set_xlabel("Post-match Δ speed, NEAR ring (km/h)")
    axes[0].set_ylabel("Number of matches")
    axes[0].legend(frameon=False, fontsize=8)
    stats.probplot(x, dist="norm", plot=axes[1])
    axes[1].set_title("Normal Q-Q plot", fontsize=10)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


# ---------------------------------------------------------------- driver
def run(res: dict, clean_log: dict, fx_log: dict, panel_log: dict, eff_log: dict,
        inventory: dict | None, panel: pd.DataFrame, fx: pd.DataFrame) -> dict:
    V = {}
    eh, ew, md = res["main"]

    # --- Table 4.1 inventory & cleaning
    inv = inventory or {}
    V.update(INV_FIRST=inv.get("first_month", "n/a"), INV_LAST=inv.get("last_month", "n/a"),
             INV_NFILES=str(inv.get("n_files", "n/a")),
             INV_GAPS=(", ".join(inv.get("missing_months", [])) or "none") if inv else "n/a")
    cl = clean_log
    V.update(N_MONTHS=str(cl.get("raw_months")), N_RAW_ROWS=f"{cl['raw_rows']:,}",
             N_CELLS_DEFINED=str(cl["study_cells_defined"]), N_CELLS_DATA=str(cl["study_cells_with_data"]),
             N_CELLS_KEPT=str(cl["cells_kept"]),
             N_DUP=f"{cl['exact_duplicates_removed'] + cl['duplicate_keys_aggregated']:,}",
             N_INVALID=f"{cl['invalid_rows_set_missing']:,}",
             N_GEOMISMATCH=f"{cl['geohash_coordinate_mismatch']:,}",
             PCT_MISSING=f(100 * cl["missing_share"], 1),
             N_OUTAGE=f"{cl['outage_hours']:,}", PCT_OUTLIER=f(100 * cl["outlier_share"], 2),
             HOUR_MIN_VEH=(f"{cl['hour_of_min_mean_vehicles']:02d}:00"
                           if cl.get("hour_of_min_mean_vehicles") is not None else "n/a"),
             N_PANEL_ROWS=f"{panel_log['panel_rows_analysis']:,}",
             PCT_WEATHER_MISSING=f(100 * panel_log["weather_missing_share"], 2),
             FX_ROWS_IN=str(fx_log["rows_in"]), FX_DUP=str(fx_log["duplicates_removed"]),
             FX_MISMATCH=str(fx_log["home_club_venue_mismatch"]))

    # --- Table 4.2 matches
    fx = fx.copy()
    fx["skey"] = fx.season.map(lambda s: "S" + s[2:4] + s[5:7])
    valid = set(md.loc[md.n_controls >= cfg.CONTROL_MIN, "match_id"])
    for st in ST_ORDER + ["ALL"]:
        d = fx if st == "ALL" else fx[fx.stadium == st]
        for sk in ["S2021", "S2223", "S2324", "S2425"]:
            V[f"M_{st}_{sk}"] = str(int((d.skey == sk).sum()))
        V[f"M_{st}_TOT"] = str(len(d))
        V[f"M_{st}_DERBY"] = str(int(d.is_derby.sum()))
        V[f"M_{st}_VALID"] = str(int(d.match_id.isin(valid).sum()))
    em = eff_log["main"]
    V.update(N_MATCHES_MAIN=str(em["matches_in"]), N_MATCHES_VALID=str(em["matches_with_controls"]),
             PCT_RELAXED=f(100 * em["weather_relaxed"] / max(em["matches_in"], 1), 1),
             MEAN_CONTROLS=f(em["mean_controls"] or np.nan, 1),
             N_MATCHES_CLOSED=str(eff_log.get("closed_doors", {}).get("matches_in", 0)),
             N_MATCH_LOWCOV=str(em.get("match_day_coverage_below_80", "n/a")))

    # --- Table 4.3 main effects
    me = main_effects(ew)
    me.to_csv(cfg.OUT_TABLES / "table_4_3_main_effects.csv", index=False)
    for r in me.itertuples():
        k = f"E_{r.stadium}_{r.window}"
        V[k + "_N"] = str(r.n)
        V[k + "_DS"] = f"{f(r.mean_d_speed)} [{f(r.ci_lo)}, {f(r.ci_hi)}]"
        V[k + "_PS"] = fp(r.p_ttest_speed)
        V[k + "_QS"] = fp(r.p_wilcoxon_speed)
        V[k + "_DV"] = f"{f(r.pct_veh, 1)} [{f(r.veh_ci_lo, 1)}, {f(r.veh_ci_hi, 1)}]"
        V[k + "_QV"] = fp(r.p_wilcoxon_veh)
    V["SHAPIRO_SHARE"] = f(100 * (me.shapiro_p < 0.05).mean(), 0)
    sig = me[(me.p_ttest_speed < cfg.ALPHA) & (me.p_wilcoxon_speed < cfg.ALPHA)]
    V["N_SIG_SPEED"] = str(len(sig))
    pooled = me[(me.stadium == "ALL")].set_index("window")
    for w in WIN:
        if w in pooled.index:
            V[f"POOLED_{w.upper()}_DS"] = f(pooled.loc[w, "mean_d_speed"])
            V[f"POOLED_{w.upper()}_PCTS"] = f(pooled.loc[w, "mean_pct_speed"], 1)
            V[f"POOLED_{w.upper()}_DV"] = f(pooled.loc[w, "pct_veh"], 1)
            V[f"POOLED_{w.upper()}_Q"] = fp(pooled.loc[w, "p_wilcoxon_speed"])
            V[f"POOLED_{w.upper()}_QTXT"] = fq(pooled.loc[w, "p_wilcoxon_speed"], "p")
    # descriptive statistics of the pooled post-match effect (Lab 05)
    x = ew[(ew.ring == "NEAR") & (ew.window == "post")].d_speed.dropna()
    if len(x) > 3:
        V.update(DESC_N=str(len(x)), DESC_MEAN=f(x.mean()), DESC_MEDIAN=f(x.median()),
                 DESC_SD=f(x.std(ddof=1)), DESC_IQR=f(x.quantile(0.75) - x.quantile(0.25)),
                 DESC_SKEW=f(stats.skew(x)), DESC_KURT=f(stats.kurtosis(x)),
                 DESC_SHAPIRO=fp(stats.shapiro(x).pvalue))

    # sensitivity: only matches whose own match day has >= 80 % of the hours observed
    post = ew[(ew.ring == "NEAR") & (ew.window == "post")]
    rows = []
    for lab, dsel in [("all_matches", post), ("match_day_coverage_ok", post[post.match_day_coverage_ok])]:
        x = dsel.d_speed.dropna()
        m, lo, hi = t_ci(x)
        _, pt, pw = paired_tests(x)
        rows.append(dict(sample=lab, n=len(x), mean_d_speed=m, ci_lo=lo, ci_hi=hi, p_ttest=pt, p_wilcoxon=pw))
    sens = pd.DataFrame(rows)
    sens.to_csv(cfg.OUT_TABLES / "table_sensitivity_match_day_coverage.csv", index=False)
    r = sens.iloc[1]
    V.update(SENS_COV_N=str(int(r.n)), SENS_COV_DS=f"{f(r.mean_d_speed)} [{f(r.ci_lo)}, {f(r.ci_hi)}]",
             SENS_COV_P=fp(r.p_wilcoxon), SENS_ALL_N=str(int(sens.iloc[0].n)))
    mdm = md[md.n_controls >= cfg.CONTROL_MIN]
    V.update(N_MATCH_ZEROCOV=str(int((mdm.match_day_coverage == 0).sum())))

    # --- Table 4.4 two-group comparisons
    ht = heterogeneity(ew)
    ht.to_csv(cfg.OUT_TABLES / "table_4_4_group_comparisons.csv", index=False)
    for r in ht.itertuples():
        k = f"H_{r.key}"
        V[k + "_GROUPS"] = f"{f(r.mean_a)} (n={r.n_a}) vs {f(r.mean_b)} (n={r.n_b})"
        V[k + "_LEV"] = fp(r.levene_p)
        V[k + "_T"] = fp(r.t_p) + (" (W)" if r.welch == "W" and np.isfinite(r.t_p) else "")
        V[k + "_U"] = fp(r.mwu_p)

    # --- Table 4.5 correlations
    ct, _ = correlations(ew, fx)
    ct.to_csv(cfg.OUT_TABLES / "table_4_5_correlations.csv", index=False)
    for r in ct.itertuples():
        k = f"C_{r.key}"
        V[k + "_N"] = str(r.n)
        V[k + "_R"], V[k + "_RP"] = f(r.r), fp(r.r_p)
        V[k + "_RHO"], V[k + "_RHOP"] = f(r.rho), fp(r.rho_p)
        V[k + "_TAU"], V[k + "_TAUP"] = f(r.tau), fp(r.tau_p)

    # --- Table 4.6 robustness
    rb, ring_means = robustness(res)
    rb.to_csv(cfg.OUT_TABLES / "table_4_6_robustness.csv", index=False)
    for r in rb.itertuples():
        k = f"R_{r.check.upper()}"
        V[k + "_N"] = str(r.n)
        V[k + "_EST"] = f(r.estimate)
        V[k + "_CI"] = f"[{f(r.ci_lo)}, {f(r.ci_hi)}]" if np.isfinite(r.ci_lo) else "–"
        V[k + "_PT"] = fp(r.p_t)
        V[k + "_PW"] = fp(r.p_w)
    for ring_, m in ring_means.items():
        V[f"RING_{ring_}_MEAN"] = f(m)

    # --- Table 4.7 targets
    pk = panel[panel.cell_ok & panel.congestion_class.notna()]
    ev = pk[pk.window.isin(WIN) & (pk.season_role == "main")]
    for lab, key in [("free", "FREE"), ("moderate", "MOD"), ("congested", "CONG")]:
        V[f"T_{key}_ALL"] = f(100 * (pk.congestion_class == lab).mean(), 1)
        V[f"T_{key}_EV"] = f(100 * (ev.congestion_class == lab).mean(), 1) if len(ev) else "n/a"
    V["T_ABN_ALL"] = f(100 * pk.abnormal_slowdown.mean(), 2)
    V["T_ABN_EV"] = f(100 * ev.abnormal_slowdown.mean(), 2) if len(ev) else "n/a"

    # --- figures
    fig_profiles(eh, cfg.OUT_FIGS / "fig_4_1_profiles.png")
    fig_event_study(eh, cfg.OUT_FIGS / "fig_4_2_event_study.png")
    fig_heterogeneity(ew, cfg.OUT_FIGS / "fig_4_3_heterogeneity.png")
    fig_normality(ew, cfg.OUT_FIGS / "fig_normality_post.png")

    (cfg.OUT / "report_values.json").write_text(json.dumps(V, indent=2, ensure_ascii=False))
    return V
