"""Build data/raw/fixtures_tff.csv from the two verified source extracts.

Sources (collected 07.11.2026 with tools/tff_scraper.js in a browser):
  data/raw/sources/tff_home_matches_compact.txt
      tff.org club pages (pageId=28, season filter) + match pages (pageID=29&macID=...):
      macID|YYYY-MM-DD HH:MM|venue key|competition key|round|home club|away team|score
      venue key: R = Ali Sami Yen/Rams Park, S = Şükrü Saracoğlu, T = Vodafone/Beşiktaş Park, X = other
      competition key: L = Süper Lig, C = Ziraat Türkiye Kupası, S = Süper Kupa
  data/raw/sources/uefa_home_matches_compact.txt
      UEFA home matches (not on tff.org) from the English Wikipedia season articles:
      club|date|kick-off (TRT)|venue key|competition|round|opponent|score|attendance|flag
      flag 'time_uncertain' = time zone not stated -> date is only excluded from control days

    python3 tools/build_fixtures.py
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "sources"
OUT = ROOT / "data" / "raw" / "fixtures_tff.csv"

HOME = {"GS": "GALATASARAY A.Ş.", "FB": "FENERBAHÇE A.Ş.", "BJK": "BEŞİKTAŞ A.Ş."}
VENUE = {"R": "ALİ SAMİ YEN SPOR KOMPLEKSİ (RAMS PARK) - İSTANBUL",
         "S": "ÜLKER STADYUMU FB ŞÜKRÜ SARACOĞLU SPOR KOMPLEKSİ - İSTANBUL",
         "T": "BEŞİKTAŞ PARK / VODAFONE PARK - İSTANBUL",
         "X": "NEUTRAL VENUE"}
COMP = {"L": "Süper Lig", "C": "Ziraat Türkiye Kupası", "S": "Turkcell Süper Kupa"}
WIKI = {"GS": "Galatasaray_S.K.", "FB": "Fenerbah%C3%A7e_S.K.", "BJK": "Be%C5%9Fikta%C5%9F_J.K."}
COLS = ["season", "competition", "round", "date", "kickoff_local", "home_team", "away_team", "venue",
        "spectators_allowed", "attendance", "source_url", "notes"]


def season_label(date: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def main():
    rows = []
    for ln in (SRC / "tff_home_matches_compact.txt").read_text(encoding="utf-8").splitlines():
        mac, dt, vk, ck, rnd, club, away, score = ln.split("|")
        date, ko = (dt.split(" ") + [""])[:2] if dt != "-" else ("", "")
        rows.append(dict(season=season_label(date) if date else "", competition=COMP[ck],
                         round=(f"Hafta {rnd}" if ck == "L" else rnd), date=date, kickoff_local=ko,
                         home_team=HOME[club], away_team=away, venue=VENUE[vk], spectators_allowed="",
                         attendance="", source_url=f"https://www.tff.org/Default.aspx?pageID=29&macID={mac}",
                         notes=f"TFF; score {score}" + ("; forfeit/no date" if not date else "")))
    for ln in (SRC / "uefa_home_matches_compact.txt").read_text(encoding="utf-8").splitlines():
        club, date, ko, vk, comp, rnd, away, score, att, flag = ln.split("|")
        s = season_label(date)
        url = f"https://en.wikipedia.org/wiki/{s[:4]}%E2%80%93{s[5:]}_{WIKI[club]}_season"
        rows.append(dict(season=s, competition=comp, round=rnd, date=date, kickoff_local=ko,
                         home_team=HOME[club], away_team=away, venue=VENUE[vk],
                         spectators_allowed=("0" if att == "0" else ""), attendance=att, source_url=url,
                         notes=f"Wikipedia season article; score {score}" + (f"; {flag}" if flag else "")))
    rows.sort(key=lambda r: (r["date"] or "9999", r["home_team"]))
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"written {OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
