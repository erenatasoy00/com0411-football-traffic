"""Short live demo for the final presentation. It only READS the saved data and results; it writes nothing.

    python demo.py                              # 5 steps, a few seconds
    python demo.py --model                      # step 5 trains the day-ahead model live (about 1 minute)
    python demo.py --match RAMS_20230604_1900   # step 2 with another match (ids: data/processed/fixtures_clean.csv)
    python demo.py --pause                      # wait for Enter after every step (for presenting)

Steps: 1 data -> 2 one match against its control days -> 3 all matches, hypothesis tests ->
4 robustness (placebo, closed doors) -> 5 prediction model on the test season 2024-25.
The functions used are the project's own (ftraffic.stats, ftraffic.model), so the numbers are the ones in the paper.
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from ftraffic import config as C
from ftraffic.stats import paired_tests, t_ci

P = C.PROCESSED
NAME = {"RAMS": "Rams Park", "SARACOGLU": "Sukru Saracoglu", "TUPRAS": "Tupras Stadyumu"}
DEFAULT_MATCH = "RAMS_20231021_1900"      # Galatasaray - Besiktas derby, Super Lig, 21 Oct 2023


def head(n, title, a):
    if a.pause and n > 1:
        input("\n  [Enter] next step ...")
    print(f"\n{'=' * 74}\n {n}/5  {title}\n{'=' * 74}")


def p_txt(p):
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def test_line(label, x):
    m, lo, hi = t_ci(x)
    sh, pt, pw = paired_tests(x)
    print(f"  {label:<22} n = {len(x):>3}   mean = {m:+6.2f} km/h   95% CI [{lo:+.2f}, {hi:+.2f}]"
          f"   Shapiro p {p_txt(sh)}   t-test p {p_txt(pt)}   Wilcoxon p {p_txt(pw)}")


def step1(pnl, a):
    head(1, "DATA: what we collected and joined", a)
    inv = pd.read_csv(C.RAW / "ibb_inventory.csv")
    fx = pd.read_csv(P / "fixtures_clean.csv")
    print(f"  IBB portal inventory : {len(inv)} monthly files, {inv.year.min()}-{inv.month.iloc[0]:02d} -> "
          f"{inv.year.max()}-{inv.month.iloc[-1]:02d}  (data/raw/ibb_inventory.csv)")
    ok = pnl[pnl.cell_ok]
    print(f"  Cell-hour panel      : {len(pnl):,} rows x {pnl.shape[1]} columns, "
          f"{pnl.ts.min():%Y-%m-%d} -> {pnl.ts.max():%Y-%m-%d}")
    print(f"  Cells kept (>= 80 % of hours observed): {ok.geohash.nunique()}  by ring: "
          f"{ok.groupby('ring').geohash.nunique().to_dict()}")
    print(f"  Matches (fixtures)   : {len(fx)} home matches at the three stadiums")
    tab = pd.crosstab(fx.season, fx.spectators_allowed.map({True: "spectators", False: "closed doors"}))
    print("  " + tab.to_string().replace("\n", "\n  "))


def step2(a):
    head(2, f"ONE MATCH against its own control days: {a.match}", a)
    fx = pd.read_csv(P / "fixtures_clean.csv").set_index("match_id")
    if a.match not in fx.index:
        sys.exit(f"unknown match id {a.match}; see data/processed/fixtures_clean.csv")
    f = fx.loc[a.match]
    ew = pd.read_parquet(P / "effects_window_main.parquet")
    eh = pd.read_parquet(P / "effects_hourly_main.parquet")
    w = ew[(ew.match_id == a.match) & (ew.ring == "NEAR")].set_index("window")
    h = eh[(eh.match_id == a.match) & (eh.ring == "NEAR")].set_index("h_rel").sort_index()
    print(f"  {f.home_team} - {f.away_team}  |  {f.competition}  |  kick-off {f.kickoff[:16]}  |  {NAME[f.stadium]}")
    if w.empty:
        print("  This match has no effect values (too few valid control days or not a main season).")
        return
    r = w.iloc[0]
    print(f"  Control days: {int(r.n_controls)} days, same weekday, weeks {r.control_weeks} "
          f"(minus = before the match){'  [weather rule relaxed]' if r.weather_relaxed else ''}")
    print("\n  hour   speed on match day   mean of controls   delta (km/h)")
    for hr, x in h.iterrows():
        if pd.isna(x.d_speed):
            continue
        bar = "#" * int(round(abs(x.d_speed))) if x.d_speed < 0 else ""
        tag = " KO" if hr == 0 else ""
        print(f"  {int(hr):+3d}{tag:<3}      {x.speed_match:6.1f}            {x.speed_ctrl:6.1f}        {x.d_speed:+6.1f}  {bar}")
    print("\n  Window averages (one value per match and window -> no pseudo-replication):")
    for win in ["pre", "during", "post"]:
        if win in w.index:
            print(f"    {win:<7} delta speed = {w.loc[win, 'd_speed']:+6.2f} km/h   vehicles {w.loc[win, 'pct_veh']:+6.1f} %")


def step3(a):
    head(3, "ALL MATCHES: post-match window, NEAR ring (H1)", a)
    ew = pd.read_parquet(P / "effects_window_main.parquet")
    x = ew[(ew.ring == "NEAR") & (ew.window == "post")]
    test_line("all three stadiums", x.d_speed.dropna())
    for st in ["RAMS", "SARACOGLU", "TUPRAS"]:
        test_line(NAME[st], x[x.stadium == st].d_speed.dropna())
    print("  -> paired comparison match day vs control days; Wilcoxon is the main test (Shapiro rejects normality)")


def step4(a):
    head(4, "ROBUSTNESS: the same pipeline where no crowd effect should exist (H4)", a)
    for label, title in [("placebo_dates", "placebo (fake matches)"), ("closed_doors", "closed doors 2020-21")]:
        ew = pd.read_parquet(P / f"effects_window_{label}.parquet")
        x = ew[(ew.ring == "NEAR") & (ew.window == "post")].d_speed.dropna()
        test_line(title, x)
    print("  -> no significant effect in either: the slowdown comes from the spectators, not from the method")


def step5(pnl, a):
    head(5, "PREDICTION: day-ahead congestion class, test season 2024-25 (H5)", a)
    if not a.model:
        t = pd.read_csv(C.OUT_TABLES / "phase2" / "model_t2_test_2024-25.csv")
        t = t.pivot(index="model", columns="slice", values="macro_f1")[["all", "match", "post_near"]]
        order = ["hgb", "hgb_no_event", "rf", "linear", "b1_profile", "b0_last_week"]
        print("  Saved results (outputs/tables/phase2/model_t2_test_2024-25.csv), macro-F1:")
        print("  " + t.reindex(order).round(3).to_string().replace("\n", "\n  "))
        print("\n  Run 'python demo.py --model' to train gradient boosting live (about 1 minute).")
        return
    from ftraffic import model as M
    t0 = time.time()
    d = M.base_frame(pnl)
    ds = M.fit_split(d, ["2022-23", "2023-24"])           # free-flow speed and baselines from training seasons only
    tr = ds[ds.season.isin(["2022-23", "2023-24"])]
    te = ds[ds.season.eq("2024-25") & ds.valid].reset_index(drop=True)
    print(f"  features built in {time.time() - t0:.0f}s: train {int(tr.valid.sum()):,} cell-hours (2022-24), "
          f"test {len(te):,} cell-hours (2024-25)")
    b0 = M.evaluate(te, M.baselines(te, "clf")["b0_last_week"], "clf")
    print(f"\n  {'model':<38} {'all hours':>9} {'match windows':>14} {'post-match near':>16}")
    print(f"  {'baseline: same hour last week':<38} {b0['all']['macro_f1']:9.3f} {b0['match']['macro_f1']:14.3f} "
          f"{b0['post_near']['macro_f1']:16.3f}")
    for label, groups in [("gradient boosting, WITHOUT fixture", M.NO_EVENT), ("gradient boosting, WITH fixture", M.ALL_GROUPS)]:
        t1 = time.time()
        _, _, p = M.fit_predict("hgb", "clf", groups, tr, te, "y_t2", dict(max_leaf_nodes=31, class_weight=None))
        ev = M.evaluate(te, p, "clf")
        print(f"  {label:<38} {ev['all']['macro_f1']:9.3f} {ev['match']['macro_f1']:14.3f} "
              f"{ev['post_near']['macro_f1']:16.3f}   ({time.time() - t1:.0f}s)")
    print("  -> the fixture barely matters over all hours but is what predicts the post-match jam")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="store_true", help="train the model live in step 5 (about 1 minute)")
    ap.add_argument("--match", default=DEFAULT_MATCH, help="match id for step 2")
    ap.add_argument("--pause", action="store_true", help="wait for Enter between steps")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    pnl = pd.read_parquet(P / "panel_cell_hour.parquet")
    step1(pnl, a)
    step2(a)
    step3(a)
    step4(a)
    step5(pnl, a)
    print()


if __name__ == "__main__":
    main()
