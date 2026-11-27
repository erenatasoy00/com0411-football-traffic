"""Fetch the main roads around the three stadiums from OpenStreetMap once, for the panel's map.

    python tools/fetch_osm_roads.py     # -> data/processed/osm_roads_stadiums.json (needs internet once)

Only motorways, trunk, primary and secondary roads inside the R0-R2 area (plus a small margin) are kept.
Map data (c) OpenStreetMap contributors, ODbL 1.0 - https://www.openstreetmap.org/copyright
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ftraffic import config as C  # noqa: E402

URLS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"]          # public Overpass mirrors, tried in turn
OUT = C.PROCESSED / "osm_roads_stadiums.json"
DLAT, DLON = 180 / 2 ** 15, 360 / 2 ** 15        # size of a geohash-6 cell in degrees
KINDS = "motorway|trunk|primary|secondary"


def bbox(stadium):
    from ftraffic import geo
    lat, lon = geo.decode(C.STADIUMS[stadium]["geohash"])
    return lat - 2.7 * DLAT, lon - 2.7 * DLON, lat + 2.7 * DLAT, lon + 2.7 * DLON


def main():
    out = {"attribution": "© OpenStreetMap contributors (ODbL)", "fetched": time.strftime("%Y-%m-%d"), "roads": {}}
    if OUT.exists():                                              # resume: keep stadiums already fetched
        out["roads"] = json.loads(OUT.read_text(encoding="utf-8")).get("roads", {})
    for st in C.STADIUMS:
        if out["roads"].get(st):
            print(f"  {st}: already fetched")
            continue
        s, w, n, e = bbox(st)
        q = f'[out:json][timeout:60];way["highway"~"^({KINDS})$"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});out geom;'
        data = None
        for attempt in range(6):
            url = URLS[attempt % len(URLS)]
            try:
                r = requests.post(url, data={"data": q}, timeout=150, headers={"User-Agent": "student-course-project/1.0"})
                r.raise_for_status()
                data = r.json()
                break
            except Exception as ex:                                  # busy mirror: try the next one
                print(f"  {st}: {url} failed ({ex.__class__.__name__}), retrying")
                time.sleep(15 * (attempt + 1))
        if data is None:
            sys.exit("Overpass is not reachable now; try again later.")
        ways = []
        for el in data.get("elements", []):
            pts = [[round(g["lat"], 5), round(g["lon"], 5)] for g in el.get("geometry", [])]
            if len(pts) >= 2:
                t = el.get("tags", {})
                ways.append(dict(hw=t.get("highway"), name=t.get("name", ""), ref=t.get("ref", ""), pts=pts))
        out["roads"][st] = ways
        OUT.write_text(json.dumps(out, ensure_ascii=False))
        print(f"  {st}: {len(ways)} road segments")
        time.sleep(20)
    print(f"-> {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
