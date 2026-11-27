"""Local web panel: traffic forecast around a stadium for a future match.

    python run_scenario.py        # once: trains and saves the long-horizon model (~2 min)
    python panel.py               # starts http://127.0.0.1:8050 and opens it in the browser

Enter a date, kick-off time, stadium, opponent and competition. The panel shows the predicted hourly
speed and congestion around the stadium from 6 hours before to 6 hours after kick-off, the same hours
on a normal day without a match, a map of the cells, and what happened at earlier matches.
Only the Python standard library and the project's packages are used; nothing is sent to the internet.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import joblib
import pandas as pd

from ftraffic import config as C
from ftraffic import scenario as S

HTML = Path(__file__).resolve().parent / "panel" / "index.html"
COMPETITIONS = {"league": "Süper Lig", "domestic_cup": "Turkish Cup", "european": "European competition"}
B = None
WORKS = None                       # UYM road-work announcements after the traffic data end (from run_extra.py)
WORK_TYPES = {"Bakım-Onarım Çalışması": "maintenance", "Yol Yapım Çalışması": "road construction",
              "Alt Yapı Çalışması": "utility works", "Yolun Trafiğe Kapanması": "road closure",
              "İmalat Çalışması": "construction", "Çevre Düzenlemesi": "landscaping",
              "Kontrollü Kapama (Protokol)": "controlled closure"}
WORKS_FROM = "2025-02-01"
WORKS_KM = 2.0
ROADS = C.PROCESSED / "osm_roads_stadiums.json"          # tools/fetch_osm_roads.py


def upcoming_fixtures(limit=30):
    """Scheduled home matches of the three clubs from the TFF and UEFA lists (data/raw/sources)."""
    try:
        from ftraffic.extra_sources import fixtures_extended
        fx = fixtures_extended()
    except Exception:
        return []
    now = pd.Timestamp.now().normalize()
    f = fx[(fx.kickoff >= now) & fx.stadium.notna() & fx.time_known & ~fx.played].sort_values("kickoff").head(limit)
    comp = {"league": "league", "domestic_cup": "domestic_cup", "super_cup": "domestic_cup", "european": "european"}
    return [dict(date=k.strftime("%Y-%m-%d"), time=k.strftime("%H:%M"), stadium=st, club=C.STADIUMS[st]["club"],
                 opponent=str(o), competition=comp.get(c, "league"), source=src)
            for k, st, o, c, src in zip(f.kickoff, f.stadium, f.opponent, f.competition_type, f.source)]


def roads():
    if not ROADS.exists():
        return None
    return json.loads(ROADS.read_text(encoding="utf-8"))


def load_works():
    p = C.PROCESSED / "extra_uym_near_stadiums.csv"
    if not p.exists():
        return None
    u = pd.read_csv(p, parse_dates=["t0"])
    u = u[~u.football.astype(bool) & u.announcement_type_desc.isin(WORK_TYPES) & (u.t0 >= WORKS_FROM)].copy()
    u["end"] = pd.to_datetime(u.announcement_ending_datetime, errors="coerce")
    u["dur_h"] = (u.end - u.t0).dt.total_seconds() / 3600
    return u


def works_for(stadium):
    if WORKS is None:
        return None
    w = WORKS[WORKS[f"d_{stadium}"] <= WORKS_KM]
    long_ = w[w.dur_h > 24].sort_values("t0", ascending=False).head(4)
    recent = w[~w.index.isin(long_.index)].sort_values("t0", ascending=False).head(3)
    items = [dict(date=str(r.t0)[:10], days=None if pd.isna(r.dur_h) else round(r.dur_h / 24, 1),
                  type=WORK_TYPES[r.announcement_type_desc], title=str(r.announcement_title).strip()[:150],
                  km=round(float(r[f"d_{stadium}"]), 1)) for _, r in pd.concat([long_, recent]).iterrows()]
    return dict(n=int(len(w)), n_long=int((w.dur_h > 24).sum()), since=WORKS_FROM, last=str(w.t0.max())[:10] if len(w) else None,
                km=WORKS_KM, by_type={WORK_TYPES[k]: int(v) for k, v in w.announcement_type_desc.value_counts().items()},
                items=items)


def clean(o):
    """JSON-safe: numpy -> python, NaN -> null."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "item"):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def meta():
    cells = B["cells"]
    past = B["past"]
    st = []
    for key, s in C.STADIUMS.items():
        cs = cells[cells.stadium == key]
        opp = sorted(set(past[past.stadium == key].opponent.dropna()))
        st.append(dict(key=key, name=s["name"], club=s["club"], district=s["district"], lat=s["lat"],
                       lon=s["lon"], capacity=s["capacity"],
                       cells=cs[["geohash", "ring", "cell_lat", "cell_lon"]].to_dict("records"),
                       opponents=opp))
    fin = B["validation"]["final"]["metrics"]
    q = dict(scenario_t2={s: fin["scenario|t2"][s]["macro_f1"] for s in ["all", "match", "post_near"]},
             scenario_t1={s: fin["scenario|t1"][s]["mae"] for s in ["all", "match", "post_near"]},
             profile_t2={s: fin["profile_baseline|t2"][s]["macro_f1"] for s in ["all", "match", "post_near"]},
             no_event_t2={s: fin["scenario_no_event|t2"][s]["macro_f1"] for s in ["all", "match", "post_near"]},
             day_ahead=B.get("day_ahead", {}))
    return clean(dict(stadiums=st, competitions=COMPETITIONS, quality=q, data_end=B["data_end"],
                      train_rows=B["train_rows"], built=B["built"], n_cells=int(len(cells)), horizon=B.get("horizon"),
                      upcoming=upcoming_fixtures(), test_eval=B.get("test_eval"), roads=roads(),
                      big_clubs=["Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor"]))


def predict(q):
    date = q.get("date", [""])[0]
    time_ = q.get("time", [""])[0]
    stadium = q.get("stadium", [""])[0]
    opponent = q.get("opponent", [""])[0].strip()[:60]
    comp = q.get("competition", ["league"])[0]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("Please enter a date.")
    if not re.fullmatch(r"\d{2}:\d{2}", time_):
        raise ValueError("Please enter a kick-off time (HH:MM).")
    pd.Timestamp(f"{date} {time_}")                       # raises on an impossible date
    if stadium not in C.STADIUMS:
        raise ValueError("Unknown stadium.")
    if comp not in COMPETITIONS:
        raise ValueError("Unknown competition.")
    if not opponent:
        raise ValueError("Please enter the opponent.")
    home = C.STADIUMS[stadium]["club"]
    if re.search(C.CLUB_PATTERNS[home], S.tr_upper(opponent)):
        raise ValueError(f"{home} plays at home here; choose another opponent.")
    r = S.predict_match(B, date, time_, stadium, opponent, comp)
    r["works"] = works_for(stadium)
    return r


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path in ("/", "/index.html"):
                self.send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/meta":
                self.send(200, json.dumps(meta(), ensure_ascii=False), "application/json; charset=utf-8")
            elif u.path == "/api/predict":
                r = clean(predict(parse_qs(u.query)))
                self.send(200, json.dumps(r, ensure_ascii=False), "application/json; charset=utf-8")
            else:
                self.send(404, "not found", "text/plain")
        except ValueError as e:
            self.send(400, json.dumps({"error": str(e)}), "application/json")
        except Exception as e:                                  # keep the panel alive and show the error
            self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}), "application/json")

    def log_message(self, *args):
        pass


def main():
    global B, WORKS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not S.BUNDLE.exists():
        sys.exit("The model is not trained yet. Run:  python run_scenario.py")
    B = joblib.load(S.BUNDLE)
    WORKS = load_works()
    url = f"http://127.0.0.1:{a.port}"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError:
        # usually the panel is already running in another terminal: open that one instead
        print(f"Port {a.port} is already in use - the panel is probably already running: {url}\n"
              f"Opening it in the browser. To start a second panel use:  python panel.py --port {a.port + 1}")
        if not a.no_browser:
            webbrowser.open(url)
        return
    print(f"Panel: {url}   (model built {B['built']}, data until {B['data_end']})   Ctrl+C to stop")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
