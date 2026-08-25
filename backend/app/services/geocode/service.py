"""Place-name geocoding by decoding the planet `places` vector layer.

`geocode(q, bbox=...)` decodes the `places` features in the tiles
covering `bbox` (the AO), folds diacritics, fuzzy-matches the query
against `name` and `name:en`, and ranks by match quality then the tile's
own importance signals (`min_zoom` ascending, `population` descending),
biased toward `near` when given. Decoded tiles are cached in-process
(the raw pbf is already disk-cached by the tilecache; this skips the
protobuf decode on warm sweeps), mirroring api/v1/terrain.py.

No bbox → a coarse whole-world sweep that only surfaces countries and
major cities (they alone carry a low enough `min_zoom` to appear in the
shallow tiles a world sweep can afford). That is exactly what AO
definition needs to anchor a theater/country to a point.
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from app.utils.tilemath import (
    mvt_point_to_lonlat,
    pick_zoom_for_bbox,
    tile_range,
)

log = logging.getLogger("app.geocode")

# Tile-decode budget per geocode call. A tight AO saturates to a deep
# zoom (villages); a continental bbox falls back to a shallow one.
_TILE_BUDGET = 260
# Whole-world fallback zoom (no bbox): 4 => 256 tiles, enough for every
# country and every city with min_zoom<=4 without a planetary decode.
_WORLD_ZOOM = 4
# Minimum match score. Deliberately HIGH: real name variants (diacritics
# like Suwałki→suwalki, native/English like Lietuva/Lithuania) fold to an
# EXACT 1.0, so loose character-ratio matches are almost always wrong
# (the classic failure: "poland"↔"portland" ≈ 0.86). We accept exact,
# token-subset, and prefix matches; a bare edit-ratio must clear this bar.
_MIN_SCORE = 0.9

# Decoded places per (z,x,y). Static per planet build.
_TILE_PLACES_CACHE: dict[Tuple[int, int, int], List[dict]] = {}
_TILE_PLACES_CACHE_MAX = 16384


@dataclass
class GeocodeCandidate:
    name: str
    name_en: Optional[str]
    kind: Optional[str]          # country | locality | region ...
    kind_detail: Optional[str]   # country | city | town | village ...
    lon: float
    lat: float
    population: Optional[int]
    min_zoom: Optional[int]
    score: float                 # 0..1 name-match quality

    def as_dict(self) -> dict:
        d = asdict(self)
        d["lon"] = round(self.lon, 6)
        d["lat"] = round(self.lat, 6)
        d["score"] = round(self.score, 3)
        return d


def _fold(s: str) -> str:
    """Lowercase, strip diacritics, reduce to alnum tokens joined by one
    space. 'Grafenwöhr' -> 'grafenwohr'; 'Suwałki' -> 'suwalki'."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # ł, ø and friends have no combining decomposition — map the common ones.
    s = (s.replace("ł", "l").replace("Ł", "l")
           .replace("ø", "o").replace("Ø", "o")
           .replace("ß", "ss").replace("đ", "d"))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def _primary(q: str) -> str:
    """The place part of a 'Town, Region, Country' query — the leading
    comma segment. The trailing admin words are hints the AO already
    encodes, and would otherwise dilute the token match."""
    return q.split(",")[0]


def _score(qf: str, name: str, name_en: Optional[str]) -> float:
    """Match score of the folded query against name / name:en.

    Ordered strongest-first: an exact fold wins outright; every query
    token appearing in the name ("frankfurt" ⊆ "frankfurt am main") or a
    clean prefix is a strong match; only then does a bare edit-ratio
    count, and it must be high to survive the threshold — this is what
    stops 'poland'→'portland' (ratio ~0.86) and codewords→real-towns."""
    best = 0.0
    for cand in (name, name_en):
        cf = _fold(cand or "")
        if not cf:
            continue
        if qf == cf:
            return 1.0
        qtok, ctok = qf.split(), cf.split()
        if qtok and set(qtok) <= set(ctok):
            best = max(best, 0.93)      # all query words present in the name
        elif cf.startswith(qf) or qf.startswith(cf):
            best = max(best, 0.9)       # one is a prefix of the other
        best = max(best, SequenceMatcher(None, qf, cf).ratio())
    return best


async def _places_in_tile(client, z: int, x: int, y: int) -> List[dict]:
    key = (z, x, y)
    cached = _TILE_PLACES_CACHE.get(key)
    if cached is not None:
        return cached
    import mapbox_vector_tile as mvt
    out: List[dict] = []
    try:
        resp = await client.get(f"/data/basemap/{z}/{x}/{y}.pbf")
        if resp.status_code == 200 and resp.content:
            data = resp.content
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            layer = mvt.decode(data).get("places")
            if layer:
                extent = layer.get("extent", 4096)
                for f in layer.get("features", []):
                    p = f.get("properties") or {}
                    name = p.get("name") or p.get("name:en")
                    if not name:
                        continue
                    g = f.get("geometry") or {}
                    if g.get("type") != "Point":
                        continue
                    px, py = (g.get("coordinates") or (None, None))[:2]
                    if px is None:
                        continue
                    lon, lat = mvt_point_to_lonlat(px, py, x, y, z, extent)
                    out.append({
                        "name": str(name),
                        "name_en": p.get("name:en"),
                        "kind": p.get("kind"),
                        "kind_detail": p.get("kind_detail"),
                        "population": p.get("population"),
                        "min_zoom": p.get("min_zoom"),
                        "lon": lon, "lat": lat,
                    })
    except Exception as exc:  # transient fetch/decode — don't cache
        log.debug("places tile %s/%s/%s decode failed: %s", z, x, y, exc)
        return out
    if len(_TILE_PLACES_CACHE) >= _TILE_PLACES_CACHE_MAX:
        _TILE_PLACES_CACHE.clear()
    _TILE_PLACES_CACHE[key] = out
    return out


def _dedup_key(place: dict) -> Tuple[str, float, float]:
    return (_fold(place["name"]), round(place["lon"], 3), round(place["lat"], 3))


async def geocode(
    q: str,
    *,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    near: Optional[Tuple[float, float]] = None,
    limit: int = 6,
    min_score: float = _MIN_SCORE,
) -> List[GeocodeCandidate]:
    """Resolve a place name to ranked candidates inside `bbox` (the AO).

    bbox = (west, south, east, north). Candidates are drawn ONLY from
    tiles inside bbox, so out-of-AO matches never appear. Without bbox,
    a coarse world sweep resolves countries and major cities.
    """
    from app.api.v1.tiles import _get_client

    qf = _fold(_primary(q or ""))
    if not qf:
        return []

    if bbox is not None:
        w, s, e, n = bbox
        z = pick_zoom_for_bbox(w, s, e, n, _TILE_BUDGET)
        x0, x1, y0, y1 = tile_range(w, s, e, n, z)
        tiles = [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        if len(tiles) > _TILE_BUDGET:
            tiles = tiles[:_TILE_BUDGET]
    else:
        z = _WORLD_ZOOM
        span = 2 ** z
        tiles = [(z, x, y) for x in range(span) for y in range(span)]

    client = _get_client()
    # Fetch/decode the tiles CONCURRENTLY — a cold AO sweep is hundreds
    # of tiles and a sequential await-loop times out. Bounded so we don't
    # exceed the tilecache client's connection pool.
    sem = asyncio.Semaphore(24)

    async def _one(t):
        async with sem:
            return await _places_in_tile(client, *t)

    tile_results = await asyncio.gather(*[_one(t) for t in tiles])

    seen: set = set()
    scored: List[GeocodeCandidate] = []
    for places in tile_results:
        for place in places:
            lon, lat = place["lon"], place["lat"]
            if bbox is not None and not (w <= lon <= e and s <= lat <= n):
                continue
            k = _dedup_key(place)
            if k in seen:
                continue
            seen.add(k)
            sc = _score(qf, place["name"], place.get("name_en"))
            if sc < min_score:
                continue
            scored.append(GeocodeCandidate(
                name=place["name"], name_en=place.get("name_en"),
                kind=place.get("kind"), kind_detail=place.get("kind_detail"),
                lon=lon, lat=lat,
                population=place.get("population"),
                min_zoom=place.get("min_zoom"), score=sc))

    def _rank(c: GeocodeCandidate):
        dist = 0.0
        if near is not None:
            dist = math.hypot(c.lon - near[0], c.lat - near[1])
        return (
            -round(c.score, 3),
            (c.min_zoom if c.min_zoom is not None else 15),
            -(c.population or 0),
            dist,
        )

    scored.sort(key=_rank)
    return scored[:limit]


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial compass bearing FROM point 1 TO point 2, degrees 0-360."""
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


# Widening rings for reverse lookup: a populated area answers inside the
# first ring; a remote training area may need the second.
_REVERSE_SPANS_DEG = (0.35, 0.9)


# ── Romanization (ASCII-only tool surface) ───────────────────────────
# Every name leaving the geocode/echo surface is ASCII: name_en when the
# source carries it, else a transliteration of the native name. The
# native spelling rides along as name_native so nothing is lost.
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # Belarusian / Ukrainian extras
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}
_LAT_SPECIAL = {
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
    "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ß": "ss", "þ": "th",
    "Þ": "Th", "ð": "d", "Ð": "D",
}


def romanize(text):
    """Best-effort ASCII transliteration (Cyrillic + Latin diacritics)."""
    if not text:
        return text
    import unicodedata
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
            continue
        if ch in _LAT_SPECIAL:
            out.append(_LAT_SPECIAL[ch])
            continue
        low = ch.lower()
        if low in _CYR:
            t = _CYR[low]
            out.append(t.capitalize() if ch.isupper() else t)
            continue
        d = unicodedata.normalize("NFKD", ch)
        d = "".join(c for c in d if not unicodedata.combining(c))
        out.append(d if all(ord(c) < 128 for c in d) else "?")
    return "".join(out)


def ascii_place(p):
    """Normalize a place dict to the ASCII contract: `name` is always
    ASCII (name_en, else transliteration), `name_native` keeps the
    original spelling when it differed."""
    if not p or not p.get("name"):
        return p
    native = p["name"]
    best = p.get("name_en") or romanize(native)
    if best != native:
        p["name_native"] = native
    p["name"] = best
    if not p.get("name_en"):
        p["name_en"] = best
    return p


async def reverse_geocode(lon: float, lat: float, *, limit: int = 5) -> List[dict]:
    """Nearest NAMED places to a point, from the same planet `places`
    layer — the verification echo for a placement ("this grid falls 4 km
    northeast of Bemowo Piskie"). Returns nearest-first dicts with
    distance and compass bearing FROM the place TO the point, so a
    narrative like "15 km east of Ełk" can be checked directly."""
    from app.api.v1.tiles import _get_client

    client = _get_client()
    for span in _REVERSE_SPANS_DEG:
        w, s, e, n = (lon - span, lat - span, lon + span, lat + span)
        z = pick_zoom_for_bbox(w, s, e, n, 24)
        x0, x1, y0, y1 = tile_range(w, s, e, n, z)
        tiles = [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        sem = asyncio.Semaphore(24)

        async def _one(t):
            async with sem:
                return await _places_in_tile(client, *t)

        tile_results = await asyncio.gather(*[_one(t) for t in tiles])
        seen: set = set()
        places: List[dict] = []
        for chunk in tile_results:
            for p in chunk:
                k = _dedup_key(p)
                if k in seen:
                    continue
                seen.add(k)
                places.append(p)
        if not places:
            continue
        places.sort(key=lambda p: haversine_km(lon, lat, p["lon"], p["lat"]))
        out = []
        for p in places[:limit]:
            out.append(ascii_place({
                "name": p["name"], "name_en": p.get("name_en"),
                "kind": p.get("kind"), "kind_detail": p.get("kind_detail"),
                "lon": round(p["lon"], 6), "lat": round(p["lat"], 6),
                "distance_km": round(haversine_km(lon, lat, p["lon"], p["lat"]), 1),
                "bearing_from_place_deg": round(
                    _bearing_deg(p["lon"], p["lat"], lon, lat)),
            }))
        return out
    return []
