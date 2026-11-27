"""Extension: confirm the match effect with two further open IBB sources (see ftraffic/extra_sources.py).

    python run_extra.py --download    # once: rail station counts 2021-2025 and UYM announcements (~280 MB)
    python run_extra.py               # -> outputs/extra_values.json, outputs/tables/extra/, outputs/figures/extra/

Reads the Phase 1 results; changes neither Phase 1 nor Phase 2.
"""
from __future__ import annotations

import argparse
import sys

from ftraffic import extra_sources as X


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="download the two IBB data sets first")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if a.download:
        X.download()
    if not (X.RAW_X / "uym_announcements.csv").exists() and not X.CACHE_UYM.exists():
        sys.exit("The extra IBB files are missing. Run:  python run_extra.py --download")
    X.run()
    print("-> outputs/extra_values.json")


if __name__ == "__main__":
    main()
