"""Phase 2, part A - completes the Phase 1 statistics.

What is added and why
---------------------
1. Opponent (required by the brief, missing in Phase 1): every match gets an
   opponent group (big match = derby or Trabzonspor, other Istanbul club,
   other domestic club, European club). Istanbul opponents bring few
   travelling fans, so they are a natural traffic-related split.
2. Omnibus tests for factors with three or more groups (Chapter 08):
   one-way ANOVA and its rank-based version, the Kruskal-Wallis test, with
   eta squared as effect size. Pairwise tests alone do not answer "does the
   factor matter at all?".
3. Multiple comparisons: Holm-Bonferroni adjusted p-values for every test
   family (H1, H2, H3/H4). Holm keeps the family-wise error rate at 5 % and
   is uniformly more powerful than plain Bonferroni.
4. Chi-square test of independence between the congestion class (target T2)
   and the match window, with Cramer's V - shows that the Phase 2 target
   carries a match signal.
"""
from __future__ import annotations

import json
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as ss

from . import config as cfg
from . import stats as s1

OUT_T = cfg.OUT_TABLES / "phase2"
OUT_F = cfg.OUT_FIGS / "phase2"
OUT_T.mkdir(parents=True, exist_ok=True)
OUT_F.mkdir(parents=True, exist_ok=True)

ISTANBUL_CLUBS = r"KASIMPA|İSTANBULSPOR|KARAG[ÜU]MR[ÜU]K|BA[ŞS]AK[ŞS]EH[İI]R|[ÜU]MRAN[İI]YE|PEND[İI]K|EY[ÜU]P"
OPP_ORDER = ["big_match", "istanbul", "other_domestic", "european"]
OPP_LABEL = {"big_match": "Big match", "istanbul": "Other Istanbul club",
             "other_domestic": "Other domestic club", "european": "European club"}


# ---------------------------------------------------------------- helpers
def season_of(ts: pd.Series) -> pd.Series:
    """Season label of every time stamp (NaN outside the study seasons)."""
    out = pd.Series(np.nan, index=ts.index, dtype=object)
    for name, s in cfg.SEASONS.items():
        a = pd.Timestamp(s["start"], tz=cfg.TZ)
        b = pd.Timestamp(s["end"], tz=cfg.TZ) + pd.Timedelta(days=1)
        out[(ts >= a) & (ts < b)] = name
    return out


def holm(p) -> np.ndarray:
    """Holm-Bonferroni step-down adjustment (NaN values are left out)."""
    p = np.asarray(p, dtype=float)
    out = np.full_like(p, np.nan)
    ok = np.isfinite(p)
    q = p[ok]
    m = len(q)
    if m == 0:
        return out
    order = np.argsort(q)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * q[i])
        adj[i] = min(1.0, running)
    out[ok] = adj
    return out


def opponent_group(row) -> str:
    opp = str(row.opponent).upper()
    if row.is_big_match:
        return "big_match"
    if row.competition_type == "european":
        return "european"
    if re.search(ISTANBUL_CLUBS, opp):
        return "istanbul"
    return "other_domestic"


def omnibus(groups: dict) -> dict:
    """One-way ANOVA + Kruskal-Wallis + Levene for k >= 3 groups, eta squared as effect size."""
    g = {k: pd.Series(v, dtype=float).dropna() for k, v in groups.items()}
    g = {k: v for k, v in g.items() if len(v) >= 3}
    if len(g) < 3:
        return dict(k=len(g), anova_p=np.nan, kw_p=np.nan, levene_p=np.nan, eta2=np.nan)
    allv = pd.concat(g.values())
    ss_between = sum(len(v) * (v.mean() - allv.mean()) ** 2 for v in g.values())
    ss_total = ((allv - allv.mean()) ** 2).sum()
    return dict(k=len(g), anova_p=ss.f_oneway(*g.values()).pvalue, kw_p=ss.kruskal(*g.values()).pvalue,
                levene_p=ss.levene(*g.values()).pvalue, eta2=ss_between / ss_total,
                sizes=" / ".join(f"{k}={len(v)}" for k, v in g.items()))


# ---------------------------------------------------------------- main
def run(res: dict, pnl: pd.DataFrame, fx: pd.DataFrame) -> dict:
    V = {}
    ew = res["main"][1]
    post = ew[(ew.ring == "NEAR") & (ew.window == "post")].copy()
    post["opp_group"] = post.apply(opponent_group, axis=1)
    V["OPP_N"] = post.opp_group.value_counts().to_dict()

    # ---- H2 pairwise: Phase 1 comparisons + two new opponent comparisons
    h2 = s1.heterogeneity(ew)
    dom = post[post.competition_type != "european"]
    new_pairs = [
        ("BIG", "Big match vs other", post[post.is_big_match].d_speed, post[~post.is_big_match].d_speed),
        ("OPP_IST", "Istanbul vs non-Istanbul opponent (domestic, no big match)",
         dom[dom.opp_group == "istanbul"].d_speed, dom[dom.opp_group == "other_domestic"].d_speed),
    ]
    rows = []
    for key, label, a, b in new_pairs:
        lev, t, u, kind = s1.two_group_tests(a, b)
        rows.append(dict(key=key, comparison=label, n_a=a.notna().sum(), n_b=b.notna().sum(),
                         mean_a=a.mean(), mean_b=b.mean(), levene_p=lev, t_p=t, welch=kind, mwu_p=u))
    h2 = pd.concat([h2, pd.DataFrame(rows)], ignore_index=True)
    h2["test_type"] = "two groups"

    # ---- H2 omnibus tests for factors with >= 3 groups
    om_rows = []
    for key, label, col in [("OM_ST", "Stadium (3 groups)", "stadium"),
                            ("OM_COMP", "Competition (3 groups)", "competition_type"),
                            ("OM_KO", "Kick-off slot (3 groups)", "kickoff_slot"),
                            ("OM_OPP", "Opponent group (4 groups)", "opp_group")]:
        r = omnibus({k: v.d_speed for k, v in post.groupby(col)})
        om_rows.append(dict(key=key, comparison=label, t_p=r["anova_p"], mwu_p=r["kw_p"],
                            levene_p=r["levene_p"], eta2=r["eta2"], sizes=r.get("sizes", ""),
                            test_type="ANOVA / Kruskal-Wallis"))
    h2 = pd.concat([h2, pd.DataFrame(om_rows)], ignore_index=True)

    # ---- correlations belong to the same H2 family
    corr, _ = s1.correlations(ew, fx)
    corr_rows = pd.DataFrame(dict(key="CORR_" + corr.key, comparison="Correlation: " + corr.variable,
                                  t_p=corr.r_p, mwu_p=corr.rho_p, test_type="Pearson / Spearman"))
    h2 = pd.concat([h2, corr_rows], ignore_index=True)

    h2["t_p_holm"] = holm(h2.t_p)
    h2["mwu_p_holm"] = holm(h2.mwu_p)
    h2.to_csv(OUT_T / "table_h2_extended_holm.csv", index=False)
    V["H2_N_TESTS"] = int(h2.t_p.notna().sum())
    V["H2_SIG_RAW_PARAM"] = int((h2.t_p < cfg.ALPHA).sum())
    V["H2_SIG_RAW_NONPAR"] = int((h2.mwu_p < cfg.ALPHA).sum())
    V["H2_SIG_HOLM_PARAM"] = int((h2.t_p_holm < cfg.ALPHA).sum())
    V["H2_SIG_HOLM_NONPAR"] = int((h2.mwu_p_holm < cfg.ALPHA).sum())
    V["H2_SIG_HOLM_LIST"] = h2.loc[(h2.mwu_p_holm < cfg.ALPHA) | (h2.t_p_holm < cfg.ALPHA), "comparison"].tolist()
    for _, r in h2.iterrows():
        V[f"H2_{r.key}"] = {k: (None if (isinstance(v, float) and not np.isfinite(v)) else
                                (float(v) if isinstance(v, (float, np.floating)) else
                                 (int(v) if isinstance(v, (np.integer,)) else v)))
                            for k, v in r.items()}
    V["OPP_GROUP_MEANS"] = post.groupby("opp_group").d_speed.agg(["mean", "count"]).round(2).to_dict("index")

    # ---- H1 and H3/H4 families with Holm
    me = s1.main_effects(ew)
    me = me[me.stadium != "ALL"]                     # 9 stadium x window cells form the family
    fam1 = pd.concat([me.p_ttest_speed, me.p_wilcoxon_speed, me.p_ttest_veh, me.p_wilcoxon_veh])
    V["H1_N_TESTS"] = int(fam1.notna().sum())
    V["H1_SIG_RAW"] = int((fam1 < cfg.ALPHA).sum())
    V["H1_SIG_HOLM"] = int((holm(fam1) < cfg.ALPHA).sum())
    me_h = me.assign(p_t_speed_holm=holm(me.p_ttest_speed), p_w_speed_holm=holm(me.p_wilcoxon_speed),
                     p_w_veh_holm=holm(me.p_wilcoxon_veh))
    me_h.to_csv(OUT_T / "table_h1_holm.csv", index=False)
    V["H1_SPEED_SIG_HOLM"] = int(((me_h.p_t_speed_holm < cfg.ALPHA) & (me_h.p_w_speed_holm < cfg.ALPHA)).sum())
    rb, _ = s1.robustness(res)
    rb["p_t_holm"], rb["p_w_holm"] = holm(rb.p_t), holm(rb.p_w)
    rb.to_csv(OUT_T / "table_h34_holm.csv", index=False)
    V["H34_HOLM"] = rb[["check", "p_t", "p_w", "p_t_holm", "p_w_holm"]].round(4).to_dict("records")

    # ---- sensitivity analysis promised in the Phase 1 report: drop matches whose control days
    # needed the relaxed weather rule (and, separately, matches with low match-day coverage)
    sens = []
    for name, mask in [("all matches", post.d_speed.notna()),
                       ("strict weather matching only", ~post.weather_relaxed.astype(bool)),
                       ("strict weather and >=80 % match-day coverage",
                        ~post.weather_relaxed.astype(bool) & post.match_day_coverage_ok.astype(bool))]:
        for st in s1.ST_ORDER + ["ALL"]:
            x = post.loc[mask & ((post.stadium == st) if st != "ALL" else True), "d_speed"].dropna()
            m, lo, hi = s1.t_ci(x)
            _, pt, pw = s1.paired_tests(x)
            sens.append(dict(sample=name, stadium=st, n=len(x), mean=m, ci_lo=lo, ci_hi=hi, p_t=pt, p_w=pw))
    sens = pd.DataFrame(sens)
    sens.to_csv(OUT_T / "table_sensitivity_weather_relaxed.csv", index=False)
    V["SENS"] = sens.round(4).to_dict("records")

    # ---- chi-square: congestion class vs match window (evening hours, NEAR cells, main seasons)
    # note: the panel's 'season' column is filled only inside match spans, so the season is
    # derived from the time stamp here
    sea = season_of(pnl.ts)
    p = pnl[pnl.cell_ok & pnl.ring.isin(["R0", "R1"]) & sea.notna() & (sea != "2020-21")
            & pnl.congestion_class.notna() & pnl.ts.dt.hour.between(15, 23)]
    in_win = p.window.isin(["pre", "during", "post"])
    tab = pd.crosstab(np.where(in_win, "match window", "other evening hours"), p.congestion_class)
    tab = tab[[c for c in ["free", "moderate", "congested"] if c in tab.columns]]
    chi2, chi_p, dof, _ = ss.chi2_contingency(tab)
    n = tab.values.sum()
    cramer = np.sqrt(chi2 / (n * (min(tab.shape) - 1)))
    (tab.div(tab.sum(1), axis=0) * 100).round(1).to_csv(OUT_T / "table_chi2_class_by_window_pct.csv")
    V["CHI2"] = dict(chi2=round(float(chi2), 1), dof=int(dof), p=float(chi_p), cramers_v=round(float(cramer), 3),
                     n=int(n), pct=(tab.div(tab.sum(1), axis=0) * 100).round(1).to_dict("index"))

    # ---- figure: post-match effect by opponent group
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    data = [post.loc[post.opp_group == g, "d_speed"].dropna() for g in OPP_ORDER]
    ax.boxplot(data, widths=0.5, showmeans=True, medianprops=dict(color="#0b0b0b"),
               meanprops=dict(marker="D", markerfacecolor="#2a78d6", markeredgecolor="#2a78d6", markersize=5))
    ax.set_xticks(range(1, 5), [f"{OPP_LABEL[g]}\n(n={len(d)})" for g, d in zip(OPP_ORDER, data)])
    ax.axhline(0, color="#888", lw=0.8)
    ax.set_ylabel("Post-match Δ speed (km/h)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e5e5", lw=0.6)
    fig.tight_layout()
    fig.savefig(OUT_F / "fig_opponent_groups.png", dpi=200)
    plt.close(fig)
    return V
