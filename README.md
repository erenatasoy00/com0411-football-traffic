# The Impact of Football Matches on Local Traffic Patterns in Istanbul

Reproducible pipeline of the COM0411 Fundamentals of Data Science term project
(İstanbul Kültür University, 2026–2027 Fall). It covers both phases of the project:

* **Phase 1** – data preparation and statistical analysis (`run_all.py`)
* **Phase 2** – completion of the statistics and the prediction models (`run_phase2.py`)
* **Add-on** – long-horizon forecast for a future match and a local web panel (`run_scenario.py`, `panel.py`)
* **Extension** – validation with two further open IBB sources that continue after January 2025: rail-station entries and traffic-control announcements (`run_extra.py`)

Two reports belong to the final submission. The **complete project report** (submitted as `Project_Report.pdf`) continues
the Phase 1 report on its template: `python tools/build_final_report.py` builds it from the submitted Phase 1 report, keeps the
Phase 1 text, tables and figures and adds the Phase 2 sections in the same format, with every number taken from the pipeline
outputs (output `teslim/Final_Report.docx` / `.pdf`; Microsoft Word on macOS fills in the page numbers of the contents and
exports the PDF). The **research paper** in IEEE conference format (submitted as `Research_Paper_IEEE.pdf`, 10 pages) is in
`paper/`; to rebuild it, upload `Final_Paper_Overleaf.zip` to Overleaf (*New Project → Upload Project*, pdfLaTeX) or run
`tectonic -X compile paper/main.tex` locally. The links to every dataset are listed in `Dataset_Links.txt`.
`docs/Phase1_Report_submitted.docx` is the Phase 1 report as it was submitted.

## 1. Quick start

```bash
bash run.sh --offline        # macOS / Linux; Windows: run.bat --offline
```

`run.sh` creates a private Python environment (`.venv`), installs `requirements.txt`,
rebuilds the Phase 1 dataset from the raw files in `data/raw/`, runs Phase 2 and writes the
numbers, tables and figures of the paper. Without `--offline` the IBB traffic data and the weather are downloaded again.
Python 3.9 or newer is required. A full run takes about 10 minutes on a laptop (most of it
is model training).

Step by step:

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_all.py --offline        # Phase 1: dataset, tests, figures   (~1 min)
python run_phase2.py               # Phase 2: extra tests + models        (~8 min)
python tools/build_paper.py        # paper numbers, tables, figures + Overleaf zip
python tools/build_final_report.py # final report on the Phase 1 template -> teslim/Final_Report.docx (+ .pdf with Word)
```

`python run_phase2.py --part stats` runs only the statistical part (seconds),
`--part model` only the models.

Short demo for the presentation (reads the saved results, writes nothing):

```bash
python demo.py --pause             # data -> one match -> all matches -> robustness -> model results (seconds)
python demo.py --pause --model     # step 5 retrains gradient boosting live, with and without the fixture (~40 s)
```

## 2. What each step does

| Step | Module | Output |
|---|---|---|
| IBB inventory and download | `ftraffic/download.py` | `data/raw/ibb_inventory.csv`, `ibb_coverage.json`, `data/raw/ibb/YYYY-MM.parquet`, `weather_hourly.parquet` |
| Fixtures | `ftraffic/fixtures.py` | `data/processed/fixtures_clean.csv` |
| Cleaning | `ftraffic/clean.py` | `data/interim/traffic_clean.parquet`, `cleaning_log.json`, `data/processed/cells.csv` |
| Integration and features | `ftraffic/panel.py` | `data/processed/panel_cell_hour.parquet`, `data_dictionary.csv` |
| Control days and match effects | `ftraffic/effects.py` | `effects_*_{main,closed_doors,placebo_dates}.parquet`, `controls_*.csv` |
| Phase 1 statistics and figures | `ftraffic/stats.py` | `outputs/tables/*.csv`, `outputs/figures/*.png`, `outputs/report_values.json` |
| Quality checks | `ftraffic/qc.py` | `outputs/tables/qc_report.csv`, `data/processed/qc_report.json` |
| Phase 2 statistics | `ftraffic/stats_extra.py` | opponent analysis, ANOVA / Kruskal–Wallis, Holm-adjusted p-values, chi-square test, sensitivity analysis → `outputs/tables/phase2/` |
| Phase 2 models | `ftraffic/model.py` | model tables in `outputs/tables/phase2/`, figures in `outputs/figures/phase2/`, `outputs/phase2_values.json` |
| Paper | `tools/build_paper.py` | `paper/generated/values.tex` (every number in the text), `paper/generated/tab_*.tex`, `paper/figures/`, `Final_Paper_Overleaf.zip` |

All analytical choices (stadiums, rings, seasons, windows, control-day rules, cleaning limits,
congestion bins) are set in `ftraffic/config.py`.

## 3. Prediction task (Phase 2)

* **Unit:** one cell-hour in the analysed R0–R2 cells around the three stadiums.
* **Horizon:** day-ahead. A feature is used only if it is known at least 24 hours before the
  target hour: traffic history (lags of 24 h, 48 h and 168 h, mean of the same hour in the last
  four weeks), calendar, weather (reanalysis as a stand-in for a forecast) and the published
  fixture. Same-hour traffic values are never used as features.
* **Targets:** T2 congestion class (primary; free / moderate / congested), T1 average speed,
  T3 abnormal slowdown. Free-flow speeds and hour-of-week baselines are fitted on the training
  period only.
* **Validation:** forward-chaining hold-out. Model selection: train 2022-23 → validate 2023-24.
  Final evaluation: refit on 2022-24 → test once on 2024-25. Random K-fold is not used because
  neighbouring hours are nearly identical and would leak.
* **Models:** two baselines (same hour last week; hour-of-week profile), logistic / ridge
  regression, random forest, histogram gradient boosting with and without match features.

## 4. Add-on: forecast panel for a future match

The day-ahead model of Phase 2 needs the traffic of the day before, so it cannot forecast a match
weeks ahead, and the IBB data end in January 2025. `ftraffic/scenario.py` therefore trains a
**long-horizon model** that uses only what is known when the fixture is published: calendar,
location, each cell's usual speed at that hour of the week (training data only) and the fixture.
Weather is not used (no forecast weeks ahead; no measurable effect in Phase 1 or in the permutation
importance). Validation is the same forward chaining as Phase 2; test season 2024-25:

| Model | Macro-F1 all hours | Macro-F1 match windows | MAE after the match, R0+R1 (km/h) |
|---|---|---|---|
| Hour-of-week profile | 0.746 | 0.608 | 6.80 |
| Long-horizon model without the fixture | 0.765 | 0.611 | 6.64 |
| **Long-horizon model** | 0.768 | 0.711 | 3.56 |
| Day-ahead model (Phase 2, needs yesterday's traffic) | 0.797 | 0.702 | 3.68 |

The panel uses the same model refitted on 2022-23 to 2024-25 (`outputs/models/scenario_bundle.joblib`).

**Gap to the data.** The traffic data end in January 2025, so a forecast for a match in 2026 reaches about two
years past the data. `run_scenario.py` measures what such a gap costs: the model is retrained as if the data had
ended one or two seasons earlier and the later matches are forecast. After the match, next to the stadium, the speed
was off by 1.7 km/h on average 0–6 months ahead, 1.9 km/h 6–12 months ahead and
1.9 km/h 12–19 months ahead (change against a normal day: 1.5, 2.0 and
1.5 km/h; `outputs/tables/phase2/scenario_horizon_backtest.csv`). The panel shows 80 % of these errors as a
band, puts the change against a normal day first, and lists the road works that the traffic control centre (UYM)
announced near the stadium after January 2025.

```bash
python run_scenario.py    # ~2 min: validation + final model (also part of run.sh)
python panel.py           # http://127.0.0.1:8050 - enter date, kick-off, stadium, opponent, competition
```

The panel shows the forecast speed and congestion around the stadium from 6 h before to 6 h after
kick-off, the same hours on a normal day (same model, no match), the observed
average of earlier matches with the same kick-off slot, and earlier home matches against the same
opponent. It uses only the Python standard library and the project's packages and runs offline. Further:

* **Upcoming matches**: the scheduled home matches from the TFF and UEFA lists (`data/raw/sources/*_2025_2027_compact.txt`); one click fills in the form.
* **"How did it do?"** tab: the 34 matches of the 2024-25 test season, forecast by a model trained only on 2022-24,
  next to what was observed (post-match change: correlation r = 0.76, slowdown called right in 94 % of matches).
* **Map** tab: a large map of the R0-R2 cells with an hour slider and play button, stadium pin, north arrow and
  1 km bar; next to it a summary of the selected hour, the hourly curve of the selected cell and a list of all
  cells ranked by slowdown (click a cell on the map or in the list). On this tab **Download CSV** exports every cell and hour.
* **Back to normal**: when the post-match slowdown starts, peaks and ends.
* **English / Turkish** switch, **CSV download** and a print layout (**Print / PDF**).
* **Glass design with light and dark mode**: translucent, blurred panels in the project palette; the mode follows the
  system appearance until the moon/sun button is used, and the choice is remembered.
* **Main roads** on the map from OpenStreetMap (© OpenStreetMap contributors, ODbL), fetched once with
  `python tools/fetch_osm_roads.py` into `data/processed/osm_roads_stadiums.json`.

## 5. Extension: two further open sources

The IBB traffic series ends in January 2025 and no other open source gives cell-level speeds, so the
findings were checked with two further open IBB data sets that continue after that date (`ftraffic/extra_sources.py`):
daily entries at the rail stations next to the stadiums (Seyrantepe, Söğütlüçeşme, Kabataş; 2021–2025) and the
announcements of the Transport Management Centre (UYM; July 2020 – October 2026). Fixtures of 2025-26 and 2026-27
come from tff.org and the Wikipedia season articles (`data/raw/sources/*_2025_2027_compact.txt`). Same matched-control
design as Phase 1, one value per match.

```bash
python run_extra.py --download   # once: raw IBB files (~280 MB) -> data/raw/extra/ (not in the package)
python run_extra.py              # works offline from the small extracts in data/processed/extra_*.csv
```

Station entries rise by about 80 % on match days (also in 2025, after the traffic data end; no rise in the
closed-doors season), the rise correlates with the slowdown of the same match, and UYM announced closures or
match congestion for three quarters of the matches, almost always before kick-off. See the paper, Section V-D.

## 6. Using the dataset

```python
import pandas as pd
p = pd.read_parquet("data/processed/panel_cell_hour.parquet")
p = p[p.cell_ok]                    # analysed cells only
```

* Missing hours are not imputed; drop them in each analysis.
* `vehicles` is a relative intensity indicator, never a traffic volume.
* The `season` column of the panel is filled only inside match spans; use
  `ftraffic.stats_extra.season_of(p.ts)` for the season of any hour.
* Time stamps are time-zone aware (Europe/Istanbul) and mark the start of the hour.

## 7. Tests

`python tests/make_synthetic.py && python run_all.py --skip-download` runs the Phase 1
pipeline on synthetic files with an injected match effect (code test only; use a separate copy
of the folder, because it overwrites `data/raw`). Turkish quick guide: `KURULUM_TR.md`.
