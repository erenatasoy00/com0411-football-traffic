#!/usr/bin/env bash
# One command for macOS / Linux:   bash run.sh            (full run)
#                                   bash run.sh --seasons 2023-24   (quick mode)
#                                   bash run.sh --skip-download     (use files in data/raw/ibb_manual)
# Creates a private Python environment (.venv) the first time, installs the packages,
# runs Phase 1 and Phase 2 and writes the paper tables (Final_Paper_Overleaf.zip).
set -e
cd "$(dirname "$0")"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 bulunamadı. https://www.python.org/downloads/ adresinden kurun." ; exit 1
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 veya üstü gerekli (sizde: $("$PY" --version 2>&1)). https://www.python.org/downloads/" ; exit 1
fi

if [ ! -d .venv ]; then
  echo "[setup] creating .venv ..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q

python run_all.py "$@"
python fill_report.py
python run_phase2.py
python run_scenario.py
python run_extra.py
python tools/build_paper.py
python tools/build_final_report.py
echo "Bitti: Final_Paper_Overleaf.zip (Overleaf: New Project > Upload Project). Panel: python panel.py"
