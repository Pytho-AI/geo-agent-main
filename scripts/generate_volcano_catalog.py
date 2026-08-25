#!/usr/bin/env python3
"""Generate the global volcano-summit catalog for spot heights.

The Protomaps pois schema ingests `natural` only for peak and beach,
so volcano-tagged summits (Mount Fuji, Rainier, Etna, ...) never enter
the planet tiles. A per-request Overpass supplement proved flaky
(mirrors 504 / time out from cloud egress IPs), and the set is small
and near-static — so the catalog is fetched ONCE here, reduced, and
CHECKED IN at backend/app/data/volcanoes.json. /terrain/peaks filters
it locally: zero per-request third-party calls, air-gap-correct.

Rerun (and commit the diff) to refresh:

    python3 scripts/generate_volcano_catalog.py
"""

import json
import os
import urllib.parse
import urllib.request

QUERY = '[out:json][timeout:180];node["natural"="volcano"]["name"];out body;'
MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
HEADERS = {"User-Agent": "pytho-geo-agent/1.0 (+https://pytho.ai; allen@pytho.ai)"}

OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backend", "app", "data", "volcanoes.json",
)


def fetch() -> list[dict]:
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    last_err = None
    for url in MIRRORS:
        try:
            req = urllib.request.Request(url, data=body, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=300) as resp:
                doc = json.load(resp)
            out = []
            for el in doc.get("elements", []):
                tags = el.get("tags") or {}
                name = tags.get("name:en") or tags.get("name")
                lon, lat = el.get("lon"), el.get("lat")
                if not name or lon is None or lat is None:
                    continue
                ele = None
                raw = str(tags.get("ele", "")).replace("m", "").strip()
                if raw:
                    try:
                        ele = round(float(raw), 1)
                    except ValueError:
                        ele = None
                out.append({
                    "name": str(name),
                    "lon": round(float(lon), 6),
                    "lat": round(float(lat), 6),
                    "ele": ele,
                })
            return out
        except Exception as e:  # try the next mirror
            last_err = e
            print(f"{url} failed: {e}")
    raise SystemExit(f"all mirrors failed: {last_err}")


if __name__ == "__main__":
    volcanoes = fetch()
    volcanoes.sort(key=lambda v: (v["name"], v["lon"]))
    with open(OUT, "w") as f:
        json.dump(volcanoes, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"wrote {OUT}: {len(volcanoes)} volcano summits")
