"""Explanatory figure of the forward-chaining validation design."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from . import config as C

TRAIN, VALID, TEST, IDLE = "#2a78d6", "#1baf7a", "#eb6834", "#d9d9d9"


def workflow(path):
    """Whole workflow from the raw sources to the final results (Phase 1 and Phase 2)."""
    from matplotlib.patches import FancyBboxPatch
    SRC, P1, P2, OUT = "#e8f0fa", "#fbeee6", "#e6f4ee", "#f2f2f2"
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 46)
    ax.axis("off")

    def box(x, y, w, h, text, col, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.2",
                                    fc=col, ec="#555555", lw=0.9))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=7.6,
                fontweight="bold" if bold else "normal")

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color="#555555", lw=0.9, shrinkA=0, shrinkB=0))

    srcs = ["IBB hourly traffic\n(geohash-6 cells)", "TFF + UEFA fixtures\n(310 matches)",
            "Open-Meteo ERA5\nhourly weather", "Holidays, mourning\nperiod, events"]
    for i, s in enumerate(srcs):
        box(1, 36 - i * 10, 15, 7, s, SRC)
        arrow(16.4, 39.5 - i * 10, 20.6, 23)
    box(21, 18.5, 13, 9, "Inventory,\ncleaning, QC flags\n(no imputation)", P1)
    arrow(34.4, 23, 37.6, 23)
    box(38, 18.5, 14, 9, "Cell-hour panel\nR0-R2 + distal rings\nfeatures + targets", P1)
    # Phase 1 branch (top)
    arrow(45, 27.9, 55.6, 36.5)
    box(56, 32, 14, 9, "Matched control days\n(same weekday, +/-4 w,\nweather)", P1)
    arrow(70.4, 36.5, 73.6, 36.5)
    box(74, 32, 12, 9, "Tests H1-H4\nt / Wilcoxon / MWU\nANOVA / KW, Holm", P1)
    arrow(86.4, 36.5, 88.6, 36.5)
    box(89, 32, 10, 9, "Match\neffects", OUT, bold=True)
    # Phase 2 branch (bottom)
    arrow(45, 18.1, 55.6, 9.5)
    box(56, 5, 14, 9, "Day-ahead features\n(lags >= 24 h, fixture,\ncalendar, weather)", P2)
    arrow(70.4, 9.5, 73.6, 9.5)
    box(74, 5, 12, 9, "Baselines, logistic /\nridge, random forest,\ngradient boosting", P2)
    arrow(86.4, 9.5, 88.6, 9.5)
    box(89, 5, 10, 9, "Predictions\n+ evaluation", OUT, bold=True)
    ax.text(63, 43.5, "Phase 1: data preparation and statistical analysis", ha="center", fontsize=8, color="#9a4f1f")
    ax.text(63, 1.2, "Phase 2: forward-chaining validation, test season 2024-25", ha="center", fontsize=8, color="#1f6b4a")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def split_timeline(path):
    seasons = {k: (pd.Timestamp(v["start"]), pd.Timestamp(v["end"])) for k, v in C.SEASONS.items()
               if k != "2020-21"}
    rows = [("Model selection", {"2022-23": ("Train", TRAIN), "2023-24": ("Validate", VALID),
                                 "2024-25": ("not used", IDLE)}),
            ("Final evaluation", {"2022-23": ("Train", TRAIN), "2023-24": ("Train", TRAIN),
                                  "2024-25": ("Test (once)", TEST)})]
    fig, ax = plt.subplots(figsize=(8, 2.2))
    for i, (name, spec) in enumerate(rows):
        y = len(rows) - 1 - i
        for s, (lab, col) in spec.items():
            a, b = seasons[s]
            ax.barh(y, (b - a).days, left=mdates.date2num(a), height=0.55, color=col, edgecolor="white")
            ax.text(mdates.date2num(a + (b - a) / 2), y, f"{lab}\n{s}", ha="center", va="center", fontsize=8,
                    color="white" if col != IDLE else "#333333")
    ax.set_yticks(range(len(rows)), [r[0] for r in rows][::-1])
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
