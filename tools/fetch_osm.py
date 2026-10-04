#!/usr/bin/env python3
"""Download candidate kart-track centrelines from OpenStreetMap.

Queries the Overpass API for raceway / karting geometry inside a bounding box
(default: Middlesbrough / Teesside) and writes every match to a GeoJSON file.
Each feature keeps its OSM id, name and length so you can pick the right one
and pass it to build_track.py with --way-id.

    python tools/fetch_osm.py                      # default Teesside bbox
    python tools/fetch_osm.py --bbox 54.56,-1.22,54.60,-1.15 -o data/osm.geojson
"""
import argparse
import json
import math
import sys
from pathlib import Path

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# south, west, north, east - covers Middlesbrough, South Bank and the Teesside
# Autodrome area. Tighten it once you know exactly where the circuit is.
DEFAULT_BBOX = (54.54, -1.28, 54.61, -1.10)


def build_query(bbox):
    s, w, n, e = bbox
    b = f"{s},{w},{n},{e}"
    return f"""
[out:json][timeout:60];
(
  way["highway"="raceway"]({b});
  way["leisure"="track"]["sport"~"karting|motor"]({b});
  way["sport"="karting"]({b});
);
out tags geom;
"""


def length_m(coords):
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
        y = math.radians(lat2 - lat1)
        total += 6371000.0 * math.hypot(x, y)
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bbox", help="south,west,north,east in degrees")
    ap.add_argument("-o", "--output", default="data/osm_raceways.geojson")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(",")) if args.bbox else DEFAULT_BBOX
    resp = requests.post(OVERPASS_URL, data={"data": build_query(bbox)},
                         headers={"User-Agent": "teesside-karting-rf2-builder"}, timeout=120)
    resp.raise_for_status()
    elements = resp.json().get("elements", [])

    features = []
    for el in elements:
        if el.get("type") != "way" or "geometry" not in el:
            continue
        coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
        tags = el.get("tags", {})
        features.append({
            "type": "Feature",
            "properties": {
                "osm_id": el["id"],
                "name": tags.get("name", ""),
                "tags": tags,
                "length_m": round(length_m(coords), 1),
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=1))

    if not features:
        print("No raceway/karting ways found in that bbox. Trace the layout in Google Earth instead "
              "(see README) or widen --bbox.", file=sys.stderr)
        return 1
    print(f"Wrote {len(features)} feature(s) to {out}:")
    for f in sorted(features, key=lambda f: -f["properties"]["length_m"]):
        p = f["properties"]
        print(f"  way {p['osm_id']:>12}  {p['length_m']:8.1f} m  {p['name'] or '(unnamed)'}  "
              f"{ {k: v for k, v in p['tags'].items() if k in ('highway', 'leisure', 'sport', 'area')} }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
