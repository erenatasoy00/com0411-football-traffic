"""Writes the numbers and result tables of the final paper from the pipeline outputs.

    python tools/build_paper.py

Inputs : outputs/report_values.json (Phase 1), outputs/phase2_values.json (Phase 2),
         outputs/tables/phase2/*.csv, outputs/figures/**.png
Outputs: paper/generated/values.tex (one LaTeX macro per number used in the text),
         paper/generated/tab_*.tex (result tables), paper/figures/*.png,
         Final_Paper_Overleaf.zip (upload to Overleaf: New Project -> Upload Project)

No number in paper/main.tex is typed by hand; every result comes from these files.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PAPER = ROOT / "paper"
GEN = PAPER / "generated"
FIG = PAPER / "figures"
GEN.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

V1 = json.loads((OUT / "report_values.json").read_text())
V2 = json.loads((OUT / "phase2_values.json").read_text())
S, M = V2["stats"], V2["model"]
TP2 = OUT / "tables" / "phase2"


# ----------------------------------------------------------------- formatting
def tex(s) -> str:
    return (str(s).replace("−", "\\ensuremath{-}").replace("%", "\\%").replace("&", "\\&")
            .replace("<", "\\ensuremath{<}"))


def num(x, d=2, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s.replace("-", "\\ensuremath{-}")


def pv(p):
    if p is None or (isinstance(p, float) and not np.isfinite(p)):
        return "--"
    return "\\ensuremath{<}0.001" if p < 0.001 else f"{p:.3f}"


def thousands(n):
    return f"{int(n):,}"


MACROS = {}


def macro(name, value):
    assert name.isalpha(), name
    MACROS[name] = value


# ----------------------------------------------------------------- Phase 1 numbers
for k, name in [("N_RAW_ROWS", "RawRows"), ("N_CELLS_DEFINED", "CellsDefined"), ("N_CELLS_DATA", "CellsData"),
                ("N_CELLS_KEPT", "CellsKept"), ("PCT_MISSING", "PctMissing"), ("PCT_OUTLIER", "PctOutlier"),
                ("N_INVALID", "NInvalid"), ("N_OUTAGE", "NOutage"), ("N_PANEL_ROWS", "PanelRows"),
                ("INV_NFILES", "InvFiles"), ("N_MONTHS", "StudyMonths"), ("FX_ROWS_IN", "FixtureRows"),
                ("M_ALL_TOT", "MatchesTotal"), ("N_MATCHES_MAIN", "MatchesMain"), ("N_MATCHES_VALID", "MatchesValid"),
                ("N_MATCHES_CLOSED", "MatchesClosed"), ("PCT_RELAXED", "PctRelaxed"), ("MEAN_CONTROLS", "MeanControls"),
                ("POOLED_PRE_DS", "PreDS"), ("POOLED_DURING_DS", "DuringDS"), ("POOLED_POST_DS", "PostDS"),
                ("POOLED_POST_PCTS", "PostPct"), ("POOLED_POST_DV", "PostDV"), ("DESC_MEDIAN", "PostMedian"),
                ("DESC_SKEW", "PostSkew"), ("RING_R0_MEAN", "RingZero"), ("RING_R1_MEAN", "RingOne"),
                ("RING_R2_MEAN", "RingTwo"), ("R_DID_VS_DISTAL_EST", "DiD"), ("R_PLACEBO_DATES_EST", "Placebo"),
                ("R_PLACEBO_DATES_PT", "PlaceboP"), ("R_CLOSED_DOORS_EST", "ClosedDoors"),
                ("R_CLOSED_DOORS_PT", "ClosedDoorsP"), ("QC_PASSED", "QCPassed"), ("SHAPIRO_SHARE", "ShapiroShare")]:
    macro(name, tex(V1[k]))
macro("PostCI", tex(V1["E_ALL_post_DS"].split(" ", 1)[1]))
for st, nm in [("RAMS", "Rams"), ("SARACOGLU", "Saracoglu"), ("TUPRAS", "Tupras")]:
    macro(f"Post{nm}", tex(V1[f"E_{st}_post_DS"].split(" ")[0]))

# ----------------------------------------------------------------- Phase 2 statistics
h2 = pd.read_csv(TP2 / "table_h2_extended_holm.csv")
macro("HTwoTests", str(S["H2_N_TESTS"]))
macro("HTwoSigRaw", str(S["H2_SIG_RAW_NONPAR"]))
macro("HTwoSigHolm", str(S["H2_SIG_HOLM_NONPAR"]))
macro("HTwoSigRawParam", str(S["H2_SIG_RAW_PARAM"]))
macro("HTwoSigHolmParam", str(S["H2_SIG_HOLM_PARAM"]))
macro("HOneTests", str(S["H1_N_TESTS"]))
macro("HOneSigHolm", str(S["H1_SIG_HOLM"]))
macro("HOneSpeedSigHolm", str(S["H1_SPEED_SIG_HOLM"]))
r = h2.set_index("key")
macro("BigMean", num(r.loc["BIG", "mean_a"])); macro("BigOther", num(r.loc["BIG", "mean_b"]))
macro("BigN", str(int(r.loc["BIG", "n_a"]))); macro("BigP", pv(r.loc["BIG", "t_p"]))
macro("BigPU", pv(r.loc["BIG", "mwu_p"])); macro("BigPHolm", pv(r.loc["BIG", "t_p_holm"]))
macro("IstMean", num(r.loc["OPP_IST", "mean_a"])); macro("IstOther", num(r.loc["OPP_IST", "mean_b"]))
macro("IstP", pv(r.loc["OPP_IST", "mwu_p"]))
macro("OppAnovaP", pv(r.loc["OM_OPP", "t_p"])); macro("OppKwP", pv(r.loc["OM_OPP", "mwu_p"]))
macro("OppEta", num(r.loc["OM_OPP", "eta2"], 3))
macro("StEta", num(r.loc["OM_ST", "eta2"], 2))
macro("CompKwP", pv(r.loc["OM_COMP", "mwu_p"])); macro("CompKwPHolm", pv(r.loc["OM_COMP", "mwu_p_holm"]))
chi = S["CHI2"]
macro("ChiSq", f"{chi['chi2']:.0f}"); macro("CramerV", f"{chi['cramers_v']:.3f}")
macro("ChiN", thousands(chi["n"]))
macro("CongWin", f"{chi['pct']['match window']['congested']:.1f}")
macro("CongOther", f"{chi['pct']['other evening hours']['congested']:.1f}")
sens = pd.DataFrame(S["SENS"]).set_index(["sample", "stadium"])
s_strict = sens.loc[("strict weather matching only", "ALL")]
macro("SensN", str(int(s_strict["n"]))); macro("SensMean", num(s_strict["mean"]))
macro("SensCI", f"[{num(s_strict['ci_lo'])}, {num(s_strict['ci_hi'])}]")

# ----------------------------------------------------------------- Phase 2 models
F, Sel = M["final"], M["selection"]
macro("Cells", str(M["cells"]))
macro("TestMatches", str(V1["M_ALL_S2425"]))
macro("NFeatures", str(int(sum(r["n_features"] for r in M["importance"]))))
macro("TrainRows", thousands(F["rows"]["train"])); macro("TestRows", thousands(F["rows"]["test"]))
macro("TestMatchRows", thousands(F["rows"]["test_match"]))
macro("SelTrainRows", thousands(Sel["rows"]["train"])); macro("SelValRows", thousands(Sel["rows"]["test"]))
for c, nm in [("free", "Free"), ("moderate", "Moderate"), ("congested", "Congested")]:
    macro(f"Train{nm}", f"{F['class_dist_train'][c]:.1f}"); macro(f"Test{nm}", f"{F['class_dist_test'][c]:.1f}")
macro("TThreePrevTrain", f"{100 * F['t3_prev_train']:.1f}"); macro("TThreePrevTest", f"{100 * F['t3_prev_test']:.1f}")
macro("TThreePrevSelTrain", f"{100 * Sel['t3_prev_train']:.1f}"); macro("TThreePrevSelVal", f"{100 * Sel['t3_prev_test']:.1f}")
best = Sel["t2_hgb_best"]
macro("BestLeaves", str(best["max_leaf_nodes"]))
macro("BestCW", "none" if best["class_weight"] is None else str(best["class_weight"]))
FM = F["metrics"]


def g(model, task, sl, key, d=3):
    return num(FM[f"{task}|{model}"][sl][key], d)


for mdl, nm in [("hgb", "Hgb"), ("hgb_no_event", "NoEv"), ("rf", "Rf"), ("linear", "Lin"),
                ("b0_last_week", "BZero"), ("b1_profile", "BOne")]:
    macro(f"FOne{nm}All", g(mdl, "t2", "all", "macro_f1")); macro(f"FOne{nm}Match", g(mdl, "t2", "match", "macro_f1"))
    macro(f"FCong{nm}Post", g(mdl, "t2", "post_near", "f1_congested"))
    macro(f"Mae{nm}All", g(mdl, "t1", "all", "mae", 2)); macro(f"Mae{nm}Match", g(mdl, "t1", "match", "mae", 2))
    macro(f"Mae{nm}Post", g(mdl, "t1", "post_near", "mae", 2))
for mdl, nm in [("hgb", "Hgb"), ("hgb_no_event", "NoEv"), ("linear", "Lin"), ("b0_last_week", "BZero")]:
    macro(f"Pr{nm}All", g(mdl, "t3", "all", "pr_auc")); macro(f"Pr{nm}Match", g(mdl, "t3", "match", "pr_auc"))
mae_gain = 100 * (1 - FM["t1|hgb"]["post_near"]["mae"] / FM["t1|hgb_no_event"]["post_near"]["mae"])
macro("MaeGainPost", f"{mae_gain:.0f}")
macro("RTwoHgbAll", g("hgb", "t1", "all", "r2"))
imp = pd.DataFrame(M["importance"]).set_index("group")
for gname, nm in [("history", "History"), ("event", "Event"), ("spatial", "Spatial"), ("calendar", "Calendar"),
                  ("weather", "Weather")]:
    macro(f"Imp{nm}All", num(imp.loc[gname, "drop_macro_f1_all"], 3))
    macro(f"Imp{nm}Match", num(imp.loc[gname, "drop_macro_f1_match"], 3))
cm = M["confusion_match"]
macro("CongRecall", f"{cm[2][2]:.0f}"); macro("CongAsModerate", f"{cm[2][1]:.0f}")
macro("FreeRecall", f"{cm[0][0]:.0f}"); macro("ModRecall", f"{cm[1][1]:.0f}")
pc = M["post_congested_share"]
macro("PostCongObs", f"{pc['observed']:.1f}"); macro("PostCongHgb", f"{pc['hgb']:.1f}")
macro("PostCongNoEv", f"{pc['hgb_no_event']:.1f}")
es = pd.DataFrame(M["event_study_pred"]).set_index("h_rel")
macro("PeakObs", num(es.loc[2.0, "y_t1"], 1)); macro("PeakHgb", num(es.loc[2.0, "full"], 1))
macro("PeakNoEv", num(es.loc[2.0, "noev"], 1))
cal = M["calibration"]
macro("BrierHgb", num(cal["t3|hgb"]["brier"], 4)); macro("BrierRef", num(cal["t3|hgb"]["brier_ref"], 4))
macro("BrierNoEv", num(cal["t3|hgb_no_event"]["brier"], 4)); macro("BrierLin", num(cal["t3|linear"]["brier"], 4))
macro("TThreeMeanPred", f"{100 * cal['t3|hgb']['mean_pred']:.1f}")
macro("LogLossTTwo", num(cal["t2|hgb"]["log_loss"], 3))
macro("BrierTTwo", num(cal["t2|hgb"]["brier_multi"], 3)); macro("BrierTTwoRef", num(cal["t2|hgb"]["brier_multi_ref"], 3))
bs = M["bootstrap"]
macro("BootMatches", str(bs["n_matches"]))
macro("BootMae", num(bs["d_mae"], 2)); macro("BootMaeCI", f"[{num(bs['d_mae_ci'][0])}, {num(bs['d_mae_ci'][1])}]")
macro("BootFOne", num(bs["d_f1"], 3)); macro("BootFOneCI", f"[{num(bs['d_f1_ci'][0], 3)}, {num(bs['d_f1_ci'][1], 3)}]")

# ----------------------------------------------------------------- extension: two further open sources
XP = OUT / "extra_values.json"
if XP.exists():
    E = json.loads(XP.read_text())
    G = E["rail"]["groups"]
    pct = lambda x: num(x, 0)
    month = lambda s: pd.Timestamp(s).strftime("%B %Y")
    macro("ExtRailFirst", month(E["rail"]["first"])); macro("ExtRailLast", month(E["rail"]["last"]))
    macro("ExtRailN", str(G["spectators_all"]["n"])); macro("ExtRailMean", pct(G["spectators_all"]["mean"]))
    macro("ExtRailMedian", pct(G["spectators_all"]["median"]))
    macro("ExtRailCI", f"[{pct(G['spectators_all']['lo'])}, {pct(G['spectators_all']['hi'])}]")
    for key, nm in [("RAMS", "Rams"), ("SARACOGLU", "Sar"), ("TUPRAS", "Tup")]:
        macro(f"ExtRail{nm}", pct(G[f"spectators_all|{key}"]["mean"]))
        macro(f"ExtRail{nm}Med", pct(G[f"spectators_all|{key}"]["median"]))
    macro("ExtRailStudy", pct(G["study"]["mean"])); macro("ExtRailStudyN", str(G["study"]["n"]))
    macro("ExtRailAfter", pct(G["after"]["mean"])); macro("ExtRailAfterN", str(G["after"]["n"]))
    macro("ExtRailAfterCI", f"[{pct(G['after']['lo'])}, {pct(G['after']['hi'])}]")
    macro("ExtRailAfterMed", pct(G["after"]["median"]))
    macro("ExtRailClosed", pct(G["closed_doors"]["mean"])); macro("ExtRailClosedMed", pct(G["closed_doors"]["median"]))
    macro("ExtRailClosedN", str(G["closed_doors"]["n"])); macro("ExtRailClosedP", pv(G["closed_doors"]["p_wilcoxon"]))
    lk = E["rail"]["speed_link"]
    macro("ExtLinkRho", num(lk["spearman"], 2)); macro("ExtLinkN", str(lk["n"]))
    dv = E["rail"]["derby_vs_other"]
    macro("ExtDerby", pct(dv["derby"]["mean"])); macro("ExtNonDerby", pct(dv["other"]["mean"]))
    macro("ExtDerbyP", pv(dv["p_mannwhitney"]))
    U = E["uym"]; F = U["football"]
    macro("ExtUymRows", thousands(U["rows"])); macro("ExtUymLast", pd.Timestamp(U["last"]).strftime("%-d %B %Y"))
    macro("ExtUymFootball", str(F["n"])); macro("ExtUymWith", str(F["matches_with"])); macro("ExtUymMatches", str(F["matches"]))
    macro("ExtUymShare", pct(100 * F["matches_with"] / F["matches"]))
    macro("ExtUymClosure", pct(100 * F["share_closure"])); macro("ExtUymBefore", pct(100 * F["share_before_ko"]))
    macro("ExtUymMedianH", num(-F["median_h_rel"], 1)); macro("ExtUymAfterWith", str(F["after"]["matches_with"]))
    macro("ExtUymClosedWith", str(F["closed_doors"]["with_announcement"]))
    macro("ExtUymClosedMatches", str(F["closed_doors"]["matches"]))
    inc = U["incidents"]["all"]
    macro("ExtIncRR", num(inc["rate_ratio"], 2)); macro("ExtIncCI", f"[{num(inc['lo'], 2)}, {num(inc['hi'], 2)}]")
    macro("ExtFixAfter", str(E["fixtures"]["n_after"]))

with open(GEN / "values.tex", "w", encoding="utf-8") as fh:
    fh.write("% generated by tools/build_paper.py - do not edit\n")
    for k, v in MACROS.items():
        fh.write(f"\\newcommand{{\\v{k}}}{{{v}\\xspace}}\n")


# ----------------------------------------------------------------- tables
def write_table(name, body):
    (GEN / name).write_text("% generated by tools/build_paper.py - do not edit\n" + body, encoding="utf-8")


# H1: match effects (Phase 1)
rows = []
for st, lab in [("RAMS", "Rams Park"), ("SARACOGLU", "{\\c{S}}. Saraco{\\u{g}}lu"), ("TUPRAS", "T{\\\"u}pra{\\c{s}}"),
                ("ALL", "Pooled")]:
    for i, w in enumerate(["pre", "during", "post"]):
        ds = V1[f"E_{st}_{w}_DS"]
        dv = V1[f"E_{st}_{w}_DV"]
        rows.append(f"{lab if i == 0 else ''} & {w} & {V1[f'E_{st}_{w}_N']} & {tex(ds)} & {tex(dv)} & "
                    f"{tex(V1[f'E_{st}_{w}_QS'])} \\\\")
    if st != "ALL":
        rows.append("\\midrule")
write_table("tab_h1.tex", "\n".join([
    "\\begin{tabular}{@{}llrccc@{}}", "\\toprule",
    "Stadium & Window & $n$ & $\\Delta$ speed, km/h [95\\% CI] & $\\Delta$ vehicles, \\% [95\\% CI] & $p_W$ \\\\",
    "\\midrule", *rows, "\\bottomrule", "\\end{tabular}"]))

# H2 with Holm
sel = [("DERBY", "Derby vs other"), ("BIG", "Big match vs other"), ("OPP_IST", "Istanbul vs other domestic opponent"),
       ("OM_OPP", "Opponent group (4 groups)"), ("WEEKEND", "Weekend vs weekday"), ("WET", "Wet vs dry"),
       ("OM_KO", "Kick-off slot (3 groups)"), ("OM_COMP", "Competition (3 groups)"),
       ("COMP_LC", "League vs domestic cup"), ("OM_ST", "Stadium (3 groups)")]
rows = []
for key, lab in sel:
    x = r.loc[key]
    if str(x["test_type"]).startswith("ANOVA"):
        grp = "$\\eta^2 < 0.001$" if x["eta2"] < 0.0005 else f"$\\eta^2$ = {num(x['eta2'], 3)}"
    else:
        grp = f"{num(x['mean_a'])} ({int(x['n_a'])}) vs {num(x['mean_b'])} ({int(x['n_b'])})"
    rows.append(f"{lab} & {grp} & {pv(x['t_p'])} & {pv(x['mwu_p'])} & {pv(x['t_p_holm'])} & {pv(x['mwu_p_holm'])} \\\\")
write_table("tab_h2.tex", "\n".join([
    "\\begin{tabular}{@{}lcrrrr@{}}", "\\toprule",
    " & Group means, km/h ($n$) & \\multicolumn{2}{c}{Raw $p$} & \\multicolumn{2}{c}{Holm $p$} \\\\",
    "\\cmidrule(lr){3-4}\\cmidrule(lr){5-6}",
    "Comparison & or effect size & param. & rank & param. & rank \\\\", "\\midrule", *rows,
    "\\bottomrule", "\\end{tabular}"]))

# Robustness and sensitivity
rob = [("Placebo dates (pseudo-events)", "PLACEBO_DATES"), ("Closed-doors season 2020-21", "CLOSED_DOORS"),
       ("Difference-in-differences, NEAR $-$ distal", "DID_VS_DISTAL"), ("Spatial decay R0 $-$ R1", "DECAY_R0R1"),
       ("Spatial decay R1 $-$ R2", "DECAY_R1R2")]
rows = [f"{lab} & {V1[f'R_{k}_N']} & {tex(V1[f'R_{k}_EST'])} & {tex(V1[f'R_{k}_CI'])} & {tex(V1[f'R_{k}_PT'])} & "
        f"{tex(V1[f'R_{k}_PW'])} \\\\" for lab, k in rob]
rows.append(f"Strict weather matching only & {int(s_strict['n'])} & {num(s_strict['mean'])} & "
            f"[{num(s_strict['ci_lo'])}, {num(s_strict['ci_hi'])}] & {pv(s_strict['p_t'])} & {pv(s_strict['p_w'])} \\\\")
write_table("tab_robust.tex", "\n".join([
    "\\begin{tabular}{@{}lrrcrr@{}}", "\\toprule",
    "Check (post-match window) & $n$ & Mean & 95\\% CI & $p_t$ & $p_W$ \\\\", "\\midrule", *rows,
    "\\bottomrule", "\\end{tabular}"]))

# Model comparison on the test season
names = [("b0_last_week", "Baseline: same hour last week"), ("b1_profile", "Baseline: hour-of-week profile"),
         ("linear", "Logistic / ridge regression"), ("rf", "Random forest"),
         ("hgb_no_event", "Gradient boosting, no match features"), ("hgb", "Gradient boosting, all features")]


def cell(task, mdl, sl, key, d=3, best=None):
    k = f"{task}|{mdl}"
    if k not in FM or key not in FM[k][sl]:
        return "--"
    v = FM[k][sl][key]
    s = num(v, d)
    return f"\\textbf{{{s}}}" if best is not None and abs(v - best) < 1e-12 else s


def best_of(task, sl, key, minimize=False):
    vals = [FM[f"{task}|{m}"][sl][key] for m, _ in names if f"{task}|{m}" in FM and key in FM[f"{task}|{m}"][sl]]
    return min(vals) if minimize else max(vals)


cols = [("t2", "all", "macro_f1", 3, False), ("t2", "match", "macro_f1", 3, False),
        ("t2", "post_near", "f1_congested", 3, False), ("t1", "all", "mae", 2, True),
        ("t1", "match", "mae", 2, True), ("t1", "post_near", "mae", 2, True),
        ("t3", "all", "pr_auc", 3, False), ("t3", "match", "pr_auc", 3, False)]
rows = []
for mdl, lab in names:
    cells = [cell(t, mdl, sl, k, d, best_of(t, sl, k, mn)) for t, sl, k, d, mn in cols]
    rows.append(f"{lab} & " + " & ".join(cells) + " \\\\")
write_table("tab_models.tex", "\n".join([
    "\\begin{tabular}{@{}lcccccccc@{}}", "\\toprule",
    " & \\multicolumn{3}{c}{T2 congestion class} & \\multicolumn{3}{c}{T1 average speed, MAE (km/h)} & "
    "\\multicolumn{2}{c}{T3 abnormal slowdown} \\\\",
    "\\cmidrule(lr){2-4}\\cmidrule(lr){5-7}\\cmidrule(lr){8-9}",
    " & macro-F1 & macro-F1 & F1 congested & all & match & post-match & PR-AUC & PR-AUC \\\\",
    "Model & all hours & match windows & post, NEAR & hours & windows & NEAR & all hours & match windows \\\\",
    "\\midrule", *rows, "\\bottomrule", "\\end{tabular}"]))

# Validation (model selection) table: HGB grid and the other models, T2
vm = Sel["metrics"]
rows = []
for k in [k for k in vm if k.startswith("t2|hgb leaves")] + ["t2|linear", "t2|rf", "t2|b1_profile"]:
    lab = k.split("|")[1]
    if lab.startswith("hgb"):
        parts = dict(p.split("=") for p in lab.split()[1:])
        lab = f"Gradient boosting, {parts['leaves']} leaves, weights: {parts['cw'].replace('None', 'none')}"
    else:
        lab = {"linear": "Logistic regression", "rf": "Random forest", "b1_profile": "Baseline: hour-of-week profile"}[lab]
    rows.append(f"{lab} & {num(vm[k]['all']['macro_f1'], 3)} & {num(vm[k]['match']['macro_f1'], 3)} & "
                f"{num(vm[k]['all']['f1_congested'], 3)} \\\\")
write_table("tab_selection.tex", "\n".join([
    "\\begin{tabular}{@{}lccc@{}}", "\\toprule",
    "Model (validation season 2023-24) & macro-F1, all & macro-F1, match & F1 congested \\\\", "\\midrule",
    *rows, "\\bottomrule", "\\end{tabular}"]))

# Error analysis: MAE by stadium and window
eb = pd.DataFrame(M["error_by_stadium_window"])
lab = {"RAMS": "Rams Park", "SARACOGLU": "{\\c{S}}. Saraco{\\u{g}}lu", "TUPRAS": "T{\\\"u}pra{\\c{s}}"}
rows = []
for st in ["RAMS", "SARACOGLU", "TUPRAS"]:
    cells = []
    for w in ["pre", "during", "post", "no match"]:
        x = eb[(eb.stadium == st) & (eb.window == w)]
        cells.append("--" if x.empty else f"{num(x.mae_hgb.iloc[0], 2)} / {num(x.mae_no_event.iloc[0], 2)}")
    rows.append(f"{lab[st]} & " + " & ".join(cells) + " \\\\")
write_table("tab_error.tex", "\n".join([
    "\\begin{tabular}{@{}lcccc@{}}", "\\toprule",
    "Stadium & pre & during & post & no match \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}"]))

# ----------------------------------------------------------------- figures
copy = {
    OUT / "figures" / "fig_4_2_event_study.png": "fig_event_study_observed.png",
    OUT / "figures" / "phase2" / "fig_workflow.png": "fig_workflow.png",
    OUT / "figures" / "phase2" / "fig_split_timeline.png": "fig_split_timeline.png",
    OUT / "figures" / "phase2" / "fig_model_comparison.png": "fig_model_comparison.png",
    OUT / "figures" / "phase2" / "fig_event_study_predicted.png": "fig_event_study_predicted.png",
    OUT / "figures" / "phase2" / "fig_group_importance.png": "fig_group_importance.png",
    OUT / "figures" / "phase2" / "fig_calibration.png": "fig_calibration.png",
    OUT / "figures" / "phase2" / "fig_confusion_match.png": "fig_confusion_match.png",
    OUT / "figures" / "phase2" / "fig_opponent_groups.png": "fig_opponent_groups.png",
}
if (OUT / "figures" / "extra" / "fig_extra_rail.png").exists():
    copy[OUT / "figures" / "extra" / "fig_extra_rail.png"] = "fig_extra_rail.png"
for src, dst in copy.items():
    shutil.copyfile(src, FIG / dst)

# ----------------------------------------------------------------- Overleaf package
zpath = ROOT / "Final_Paper_Overleaf.zip"
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(PAPER.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and p.suffix not in {".aux", ".log", ".pdf", ".bbl", ".blg", ".out"}:
            z.write(p, p.relative_to(PAPER))
print(f"{len(MACROS)} macros, tables and figures written; Overleaf package: {zpath.name}")
