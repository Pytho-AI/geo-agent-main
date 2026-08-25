"""Hierarchical on-road routing over the stack's OWN planet tiles.

The production-routing principle (what Google Maps does): do the heavy
work ONCE in preprocessing, answer queries against a precomputed
hierarchy. This stack already ships that hierarchy — the Protomaps
planet PMTiles pyramid. Coarse zooms carry ONLY the major road network
(kind: highway / major_road), so a long-distance query needs a handful
of coarse tiles across a clipped corridor plus a few fine tiles to
connect the endpoints onto that network. Memory and time are bounded
BY CONSTRUCTION (hard tile caps), every byte comes from the internal
tile plane (tilecache -> planet.pmtiles), and the same code works on an
air-gapped box — no external services, no downloads, no new containers.

This exists because the legacy planner (Overpass fetch + dense A*)
loads the FULL road graph for the query bbox: fine for the tactical
routes it was built for, an out-of-memory machine kill for corridor
legs (staging outage, 2026-07-17). plan_routes dispatches here for
long on_road legs and keeps the legacy engine for short ones.
"""
import gzip
import logging
import math
from heapq import heappop, heappush
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("app.routing.tile_router")

# Corridor-graph road classes per zoom band. The Protomaps `roads`
# layer generalizes by zoom on its own; the kind filter keeps the
# corridor graph to the through-network.
_CORRIDOR_KINDS = ("highway", "major_road")
_CONNECT_KINDS = ("highway", "major_road", "medium_road", "minor_road")
# Local gaps additionally ride tracks: a training area's interior —
# where objectives live — is carried in the tiles almost entirely as
# `path` (998 path features vs 56 minor-road fragments within 5 km of
# OBJ JACKSON), so without tracks the objective's road island can
# never reach the through network. Track speed keeps paths a last
# resort the cost model only picks when nothing better exists.
_LOCAL_CONNECT_KINDS = _CONNECT_KINDS + ("path",)

# Assumed speeds (km/h) per road kind — edge weights are travel time.
_SPEED = {"highway": 90.0, "major_road": 70.0,
          "medium_road": 55.0, "minor_road": 40.0, "path": 15.0}

# Hard resource caps: the router REFUSES rather than degrades the box.
_MAX_CORRIDOR_TILES = 80
_MAX_ENDPOINT_TILES = 25
_MAX_GRAPH_EDGES = 250_000

# ── Cost model (rev "cm2" — the tag rides the CH signature so persisted
# hierarchies built under an older model are never reused).
#
# Static edge shaping at graph build:
#  - a way tagged as a bridge pays a flat toll on its first edge — a
#    river crossing must EARN its place in the path, so the endpoint
#    connect stops jumping water to reach a nominally-nearer node;
#  - a way carrying a route ref (a numbered highway) gets a small
#    discount, so a named route stays on its own ref through a town
#    (the bypass) instead of diving into the street grid.
# Path-level shaping at endpoint connect (route candidates are scored,
# not just the single nearest node taken):
#  - heading reversals against the running bearing pay heavily (kills
#    the terminal double-back);
#  - water crossings in the terminal windows pay per crossing (ESA
#    WorldCover sample along the path — bridge tags in the tiles are
#    advisory; the water raster is ground truth);
#  - a connect leg (true endpoint -> corridor node) that itself crosses
#    water pays the heaviest penalty — that leg is drawn straight.
_COST_MODEL_REV = "cm2"
_BRIDGE_TOLL_H = 8.0 / 90.0          # one bridge ~ 8 highway-km
_REF_DISCOUNT = 0.92
_REVERSAL_PENALTY_H = 0.5            # one reversal ~ 45 highway-km
_REVERSAL_DEG = 120.0                # bearing delta that counts
_REVERSAL_MIN_SEG_KM = 0.15          # ignore vertex noise
_WATER_CROSSING_PENALTY_H = 0.35
_CONNECT_WATER_PENALTY_H = 1.0
_TERMINAL_WINDOW_KM = 25.0           # water-sampled portion at each end
_WATER_SAMPLE_STEP_KM = 0.2
_CONNECT_CANDIDATES = 6              # nearest corridor nodes tried/end
_SCORE_SHORTLIST = 8                 # geometry-scored, then water-scored

# Node snap: coarse-zoom geometry is simplified, so junctions from
# adjacent tiles land within ~50-100 m of each other. 8e-4 deg ~ 90 m.
_SNAP = 8e-4


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _tile_xy(lon: float, lat: float, z: int) -> Tuple[int, int]:
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    r = math.radians(max(-85.06, min(85.06, lat)))
    y = int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _tile_center(x: int, y: int, z: int) -> Tuple[float, float]:
    n = 2 ** z
    lon = (x + 0.5) / n * 360.0 - 180.0
    yf = (y + 0.5) / n
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yf))))
    return lon, lat


def _seg_dist_km(lat, lon, lat1, lon1, lat2, lon2) -> float:
    """Distance from a point to the start-end segment, equirectangular
    (good enough for corridor membership tests)."""
    kx = 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    ky = 110.57
    px, py = (lon - lon1) * kx, (lat - lat1) * ky
    vx, vy = (lon2 - lon1) * kx, (lat2 - lat1) * ky
    vv = vx * vx + vy * vy
    t = 0.0 if vv == 0 else max(0.0, min(1.0, (px * vx + py * vy) / vv))
    dx, dy = px - t * vx, py - t * vy
    return math.hypot(dx, dy)


def _bearing_deg(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Initial bearing a->b, degrees, points as (lon, lat)."""
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    x = math.sin(dl) * math.cos(la2)
    y = (math.cos(la1) * math.sin(la2)
         - math.sin(la1) * math.cos(la2) * math.cos(dl))
    return math.degrees(math.atan2(x, y)) % 360.0


def _count_reversals(path: List[Tuple[float, float]]) -> Tuple[int, float]:
    """(count, worst_delta_deg) of heading reversals along the path:
    segments >= _REVERSAL_MIN_SEG_KM whose bearing swings more than
    _REVERSAL_DEG against the previous qualifying segment."""
    prev_brg = None
    count, worst = 0, 0.0
    for a, b in zip(path, path[1:]):
        if _haversine_km(a[1], a[0], b[1], b[0]) < _REVERSAL_MIN_SEG_KM:
            continue
        brg = _bearing_deg(a, b)
        if prev_brg is not None:
            delta = abs((brg - prev_brg + 180.0) % 360.0 - 180.0)
            if delta > _REVERSAL_DEG:
                count += 1
                worst = max(worst, delta)
        prev_brg = brg
    return count, worst


def _resample(path: List[Tuple[float, float]],
              step_km: float) -> List[Tuple[float, float]]:
    """Points every step_km along the polyline (endpoints included)."""
    if len(path) < 2:
        return list(path)
    out = [path[0]]
    carried = 0.0
    for a, b in zip(path, path[1:]):
        seg = _haversine_km(a[1], a[0], b[1], b[0])
        if seg <= 0:
            continue
        d = step_km - carried
        while d < seg:
            t = d / seg
            out.append((a[0] + (b[0] - a[0]) * t,
                        a[1] + (b[1] - a[1]) * t))
            d += step_km
        carried = (carried + seg) % step_km
    out.append(path[-1])
    return out


def _terminal_windows(path: List[Tuple[float, float]],
                      window_km: float
                      ) -> Tuple[List[Tuple[float, float]],
                                 List[Tuple[float, float]]]:
    """(head, tail): the first and last window_km of the path, kept as
    SEPARATE lists — concatenating them would manufacture a phantom
    land-to-water transition at the seam."""
    def prefix(pts):
        acc, out = 0.0, [pts[0]]
        for a, b in zip(pts, pts[1:]):
            acc += _haversine_km(a[1], a[0], b[1], b[0])
            out.append(b)
            if acc >= window_km:
                break
        return out
    return prefix(path), prefix(list(reversed(path)))


# ESA WorldCover permanent-water memo (~100 m key resolution) — route
# candidates overlap heavily, so repeated scoring is nearly free.
_WATER_MEMO: dict = {}
_WATER_MEMO_MAX = 65536


async def _water_hits(pts: List[Tuple[float, float]]) -> int:
    """Count land->water TRANSITIONS along an ordered (lon, lat) point
    sequence (each transition is one crossing of permanent water)."""
    from app.services.knowledge.landcover import get_land_cover_grid
    keys = [(round(lon, 3), round(lat, 3)) for lon, lat in pts]
    missing = [k for k in dict.fromkeys(keys) if k not in _WATER_MEMO]
    if missing:
        codes = await get_land_cover_grid(
            [(lat, lon) for lon, lat in missing])
        if len(_WATER_MEMO) >= _WATER_MEMO_MAX:
            _WATER_MEMO.clear()
        for k, lc in zip(missing, codes):
            _WATER_MEMO[k] = bool(lc is not None and lc.code == 80)
    crossings = 0
    prev_wet = False
    for k in keys:
        wet = _WATER_MEMO.get(k, False)
        if wet and not prev_wet:
            crossings += 1
        prev_wet = wet
    return crossings


def _corridor_zoom(dist_km: float) -> int:
    # z8 is the FLOOR: the Protomaps basemap has no `roads` layer below
    # z8 (a z7 corridor graph decodes empty and refuses every leg). At
    # z8 even a 1000 km corridor stays ~30 tiles — inside the cap.
    if dist_km > 90:
        return 8
    return 9


class _Graph:
    def __init__(self):
        self.nodes: Dict[Tuple[int, int], Tuple[float, float]] = {}
        self.adj: Dict[Tuple[int, int], List[Tuple[Tuple[int, int], float]]] = {}
        self.edges = 0

    def _key(self, lon: float, lat: float) -> Tuple[int, int]:
        return (int(round(lon / _SNAP)), int(round(lat / _SNAP)))

    def add_way(self, coords: List[Tuple[float, float]], kind: str,
                props: Optional[dict] = None,
                flat: bool = False) -> None:
        # flat=True prices every class identically (pure distance):
        # local endpoint connects take the DIRECT road — a time-optimal
        # cost model happily trades a 9 km track connect for a 60 km
        # asphalt loop, which is never what a terminal connect means.
        speed = 50.0 if flat else _SPEED.get(kind, 40.0)
        props = props or {}
        is_bridge = bool(props.get("is_bridge") or props.get("bridge"))
        has_ref = (not flat) and bool(props.get("ref")
                                      or props.get("network"))
        toll_pending = 0.0 if flat else (_BRIDGE_TOLL_H if is_bridge
                                         else 0.0)
        prev_key = None
        prev_pt = None
        for lon, lat in coords:
            key = self._key(lon, lat)
            if key not in self.nodes:
                self.nodes[key] = (lon, lat)
            if prev_key is not None and key != prev_key:
                if self.edges >= _MAX_GRAPH_EDGES:
                    return
                cost = _haversine_km(prev_pt[1], prev_pt[0], lat, lon) / speed
                if has_ref:
                    cost *= _REF_DISCOUNT
                if toll_pending:
                    cost += toll_pending    # once per way, on its first edge
                    toll_pending = 0.0
                self.adj.setdefault(prev_key, []).append((key, cost))
                self.adj.setdefault(key, []).append((prev_key, cost))
                self.edges += 2
            prev_key, prev_pt = key, (lon, lat)

    def nearest(self, lon: float, lat: float,
                max_km: float = 8.0) -> Optional[Tuple[int, int]]:
        best, best_d = None, max_km
        for key, (nlon, nlat) in self.nodes.items():
            d = _haversine_km(lat, lon, nlat, nlon)
            if d < best_d:
                best, best_d = key, d
        return best

    def astar(self, start, goal) -> Optional[List[Tuple[float, float]]]:
        glon, glat = self.nodes[goal]
        open_q = [(0.0, start)]
        g = {start: 0.0}
        came = {}
        seen = set()
        while open_q:
            _f, cur = heappop(open_q)
            if cur == goal:
                path = [cur]
                while cur in came:
                    cur = came[cur]
                    path.append(cur)
                return [self.nodes[k] for k in reversed(path)]
            if cur in seen:
                continue
            seen.add(cur)
            for nxt, cost in self.adj.get(cur, []):
                ng = g[cur] + cost
                if ng < g.get(nxt, float("inf")):
                    g[nxt] = ng
                    came[nxt] = cur
                    nlon, nlat = self.nodes[nxt]
                    h = _haversine_km(nlat, nlon, glat, glon) / 90.0
                    heappush(open_q, (ng + h, nxt))
        return None


# Roads do not move. Decoded road tiles persist to the data volume
# (roads_store.sqlite) exactly like the peaks store: a tile of ground
# is fetched and decoded ONCE per deployment; restarts read it back.
# The in-memory dict is the hot layer. Table v2: each way carries its
# COMPLETE tile props bag (kind, ref, name, is_bridge, everything the
# tile states) — v1 rows kept only `kind` and are left behind; the v2
# table lazily refills on first touch.
_ROAD_TILE_CACHE: dict = {}
_ROAD_TILE_CACHE_MAX = 8192
_ROAD_STORE = None


def _road_store():
    global _ROAD_STORE
    if _ROAD_STORE is None:
        import os
        import sqlite3
        try:
            base = os.environ.get("GEO_DATA_DIR", "/app/data")
            os.makedirs(base, exist_ok=True)
            conn = sqlite3.connect(
                os.path.join(base, "roads_store.sqlite"),
                check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS road_tiles_v2 ("
                "z INTEGER, x INTEGER, y INTEGER, ways TEXT, "
                "PRIMARY KEY (z, x, y))")
            conn.commit()
            _ROAD_STORE = conn
        except Exception as exc:
            log.warning("roads store unavailable (%s)", exc)
            _ROAD_STORE = False
    return _ROAD_STORE or None


async def _road_tile_all(client, z: int, x: int, y: int) -> List:
    """ALL road ways of one tile [(kind, [(lon,lat)...], props), ...] —
    memory -> disk -> decode-once (with one retry on upstream error)."""
    key = (z, x, y)
    hit = _ROAD_TILE_CACHE.get(key)
    if hit is not None:
        return hit
    conn = _road_store()
    if conn is not None:
        try:
            import json as _json
            row = conn.execute(
                "SELECT ways FROM road_tiles_v2 WHERE z=? AND x=? AND y=?",
                (z, x, y)).fetchone()
            if row:
                ways = _json.loads(row[0])
                if len(_ROAD_TILE_CACHE) >= _ROAD_TILE_CACHE_MAX:
                    _ROAD_TILE_CACHE.clear()
                _ROAD_TILE_CACHE[key] = ways
                return ways
        except Exception:
            pass
    ways = await _decode_road_tile(client, z, x, y)
    if ways is None:
        return []  # transient failure — not cached, retried next call
    if conn is not None:
        try:
            import json as _json
            conn.execute(
                "INSERT OR REPLACE INTO road_tiles_v2 (z, x, y, ways) "
                "VALUES (?, ?, ?, ?)", (z, x, y, _json.dumps(ways)))
            conn.commit()
        except Exception:
            pass
    if len(_ROAD_TILE_CACHE) >= _ROAD_TILE_CACHE_MAX:
        _ROAD_TILE_CACHE.clear()
    _ROAD_TILE_CACHE[key] = ways
    return ways


async def _roads_from_tile(client, z: int, x: int, y: int,
                           kinds: Tuple[str, ...]) -> List[Tuple]:
    """One tile's (kind, line, props) ways filtered to `kinds` — served
    from the decode-once store."""
    return [w for w in await _road_tile_all(client, z, x, y)
            if w[0] in kinds]


async def _decode_road_tile(client, z: int, x: int, y: int):
    """Fetch + decode one planet tile's `roads` layer (ALL kinds).
    Returns None on transient failure (so it is not cached)."""
    import asyncio as _asyncio

    import mapbox_vector_tile
    out: List = []
    try:
        resp = await client.get(f"/data/basemap/{z}/{x}/{y}.pbf")
        if resp.status_code >= 500:
            await _asyncio.sleep(0.5)
            resp = await client.get(f"/data/basemap/{z}/{x}/{y}.pbf")
        if resp.status_code >= 500:
            return None
        if resp.status_code != 200 or not resp.content:
            return out
        data = resp.content
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        # CPU decode off the event loop — a route build must never
        # stall the map's tile serving.
        decoded = await _asyncio.to_thread(mapbox_vector_tile.decode,
                                           data)
        roads = decoded.get("roads")
        if not roads:
            return out
        extent = roads.get("extent", 4096)
        n = 2 ** z

        def to_lonlat(px, py):
            lon = (x + px / extent) / n * 360.0 - 180.0
            yf = (y + (1.0 - py / extent)) / n
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yf))))
            return (lon, lat)

        for f in roads.get("features", []):
            props = f.get("properties") or {}
            kind = props.get("kind")
            if not kind:
                continue
            geom = f.get("geometry") or {}
            gtype = geom.get("type")
            if gtype == "LineString":
                lines = [geom.get("coordinates") or []]
            elif gtype == "MultiLineString":
                lines = geom.get("coordinates") or []
            else:
                continue
            # The COMPLETE props bag rides the store (JSON-safe values
            # only) — never trimmed to what today's cost model reads.
            clean = {k: v for k, v in props.items()
                     if isinstance(v, (str, int, float, bool)) and v != ""}
            for line in lines:
                if len(line) >= 2:
                    out.append((kind,
                                [to_lonlat(px, py) for px, py in line],
                                clean))
    except Exception as exc:
        log.debug("road tile %s/%s/%s decode failed: %s", z, x, y, exc)
        return None
    return out


# Local-gap routing bounds: connect zoom carries every road class the
# tiles state; the tile set is clipped to the gap's corridor, so the
# graph is bounded BY CONSTRUCTION — the dense Overpass engine (the
# 2026-07-17 outage) is never touched.
_LOCAL_GAP_MAX_KM = 45.0
_LOCAL_BUFFER_KM = 4.0
_LOCAL_ENDPOINT_SNAP_KM = 8.0
# Straight connect tails (waypoint to chosen node) cost this multiple
# of road distance in pair selection — a tail is off-road fiction. At
# weight 3 a 7 km chord still edged out 19 km of real road on the TAA
# BRAVO to PAA DIVARTY terminal (the west range road is absent from
# the tiles, so the true road path runs east-about); weight 6 makes
# road win any time one exists inside the snap disks.
_TAIL_WEIGHT = 6.0
# Local tile sets may run larger than corridor sets — the tiles are
# small, decode-once cached, and the edge cap still bounds the graph.
_LOCAL_MAX_TILES = 160


def _local_gap_zooms(dist_km: float) -> Tuple[int, ...]:
    # Finest tiles first: generalization DROPS road sections at coarse
    # zooms (the west range road into TAA BRAVO exists at z13 but its
    # middle section vanishes at z12; the Pisz fuel-depot road north
    # exists only from z14). Fall back coarser when a set busts the
    # cap or stays disconnected.
    if dist_km <= 10.0:
        return (14, 13, 12, 11)
    if dist_km <= 15.0:
        return (13, 12, 11)
    if dist_km <= 30.0:
        return (12, 11)
    return (11,)


async def route_local_gap(
    start_lat: float, start_lon: float,
    end_lat: float, end_lon: float,
) -> Optional[List[Tuple[float, float]]]:
    """Route ONE corridor bridge gap over the local road network:
    connect-zoom tiles clipped to the gap corridor, ALL road classes,
    through the SAME contraction-hierarchy machinery as the corridor
    graphs — the gap's hierarchy is preprocessed once, persisted on the
    data volume keyed by its tile signature, and every later redraw of
    the same gap is a bidirectional upward search (roads do not move).
    Returns (lon, lat) vertices or None (caller keeps the straight
    statement)."""
    from app.api.v1.tiles import _get_client

    dist = _haversine_km(start_lat, start_lon, end_lat, end_lon)
    if dist > _LOCAL_GAP_MAX_KM:
        return None
    client = _get_client()
    import asyncio as _asyncio
    sem = _asyncio.Semaphore(16)

    async def _fetch(t):
        async with sem:
            return await _roads_from_tile(client, *t, _LOCAL_CONNECT_KINDS)

    # The buffer scales with the gap AND keeps a wide floor: lake and
    # range country forces the real road far off the straight segment
    # precisely on SHORT gaps (the Pisz connect detours ~15 km east via
    # Biala Piska for a 16 km gap). A corridor clipped too tight leaves
    # the connecting roads outside the tile set — the graph decodes as
    # two disconnected islands and the gap stays straight.
    buffer_km = max(12.0, dist * 0.6)
    # An endpoint's ONLY road access can come from a compass direction
    # the segment corridor never covers (OBJ JACKSON's range roads
    # connect northward via Orzysz; the Pisz approach runs southwest) —
    # so tiles within a disk of EITHER endpoint are members too.
    endpoint_r_km = max(10.0, dist * 0.5)
    zooms = _local_gap_zooms(dist)
    core = None
    tiles: List = []
    for z in zooms:
        if z == 14:
            # z14 fires only on short gaps; a tight corridor keeps the
            # small tiles inside the cap.
            z_buffer = max(3.0, dist * 0.4)
            z_endpoint_r = max(3.0, dist * 0.3)
        else:
            z_buffer = buffer_km
            z_endpoint_r = endpoint_r_km
        x0, y0 = _tile_xy(min(start_lon, end_lon),
                          max(start_lat, end_lat), z)
        x1, y1 = _tile_xy(max(start_lon, end_lon),
                          min(start_lat, end_lat), z)
        # The scan pad must reach the full membership radius past the
        # endpoint bbox, or the endpoint disks get silently clipped.
        tile_km = (40075.0
                   * math.cos(math.radians((start_lat + end_lat) / 2.0))
                   / (2 ** z))
        pad = int((max(z_buffer, z_endpoint_r) + 4.0)
                  / max(tile_km, 1.0)) + 1
        tiles = []
        for tx in range(x0 - pad, x1 + pad + 1):
            for ty in range(y0 - pad, y1 + pad + 1):
                clon, clat = _tile_center(tx, ty, z)
                in_corridor = _seg_dist_km(
                    clat, clon, start_lat, start_lon,
                    end_lat, end_lon) <= z_buffer + 4.0
                near_end = min(
                    _haversine_km(clat, clon, start_lat, start_lon),
                    _haversine_km(clat, clon, end_lat, end_lon),
                ) <= z_endpoint_r + 4.0
                if in_corridor or near_end:
                    tiles.append((z, tx, ty))
        if not tiles or len(tiles) > _LOCAL_MAX_TILES:
            log.info("local gap: %d z%d tiles busts the cap — trying "
                     "the next zoom", len(tiles), z)
            continue
        # EXACT bounded search, not the contraction hierarchy: on dense
        # connect-zoom graphs the CH query returned a 52 km path where
        # the raw graph carries a 12 km direct road (Pisz to TAA BRAVO,
        # 2026-07-21 — verified by offline Dijkstra on the identical
        # tile set). Until that is root-caused the corridors keep their
        # hierarchies and local gaps run _Graph.astar — the same tile
        # graph, milliseconds at this size, exact by construction. The
        # whole build-and-route runs OFF the event loop so a route
        # never stalls tile serving.
        ways = await _asyncio.gather(*[_fetch(t) for t in tiles])

        def _route_sync():
            graph = _Graph()
            for tile_ways in ways:
                for kind, line, props in tile_ways:
                    graph.add_way(line, kind, props, flat=True)
            if not graph.nodes:
                return None, "no roads decoded"

            def _near_candidates(lon, lat, k=8):
                cands = []
                for key, (nlon, nlat) in graph.nodes.items():
                    d = _haversine_km(lat, lon, nlat, nlon)
                    if d < _LOCAL_ENDPOINT_SNAP_KM:
                        cands.append((d, key))
                cands.sort()
                # Nearest per 1-km band, then overall nearest: an
                # endpoint's absolute-nearest cluster can sit on a road
                # island whose only connection is a huge loop (the TAA
                # BRAVO center nodes reach the network 52 km east-about
                # while the through road passes 2 km west) — a
                # band-spread candidate on the through road is the
                # right connect.
                by_band = {}
                for d, key in cands:
                    b = int(d)
                    if b not in by_band:
                        by_band[b] = (d, key)
                spread = sorted(by_band.values())
                seen = set(k for _, k in spread)
                rest = [c for c in cands if c[1] not in seen]
                return (spread + rest)[:k]

            s_cands = _near_candidates(start_lon, start_lat)
            e_cands = _near_candidates(end_lon, end_lat)
            if not s_cands or not e_cands:
                return None, ("no road node within snap of the "
                              + ("start" if not s_cands else "end")
                              + " endpoint")
            # Best PAIR by total ground distance (tail + path + tail)
            # across EVERY band-spread pair — pre-trimming pairs by
            # tail sum hands the whole budget to the island nodes
            # hugging the endpoint (their tails are tiny, their paths
            # are 60 km loops) and the through-road pair two bands out
            # never gets searched. The searches are exact, bounded,
            # and off the event loop; run them all and take the
            # minimum.
            pairs = sorted(((_TAIL_WEIGHT * (sd + ed), sd, s_key,
                             ed, e_key)
                            for sd, s_key in s_cands
                            for ed, e_key in e_cands
                            if s_key != e_key))
            found = []
            for _wtails, sd, s_key, ed, e_key in pairs:
                path_core = graph.astar(s_key, e_key)
                if not path_core or len(path_core) < 2:
                    continue
                path_km = sum(
                    _haversine_km(a[1], a[0], b[1], b[0])
                    for a, b in zip(path_core, path_core[1:]))
                found.append((path_km + _wtails, path_core))
            if not found:
                return None, "graph disconnected between the endpoints"
            found.sort(key=lambda x: x[0])
            # Routing must BEAT the direct statement: when the only
            # road connection doubles back and finishes on a long
            # straight tail anyway (weighted cost above the whole leg
            # drawn direct), the honest answer is the short direct
            # line, not drive-back-and-beeline.
            if found[0][0] > dist * _TAIL_WEIGHT:
                return None, ("best road path costs more than the "
                              "direct statement")
            return found[:5], None

        cands, reason = await _asyncio.to_thread(_route_sync)
        if cands:
            # Water pass on the shortlist: a connect tail over a lake
            # never beats a land option — the tail is drawn straight,
            # so a crossing there paints a chord across open water.
            best_eff = None
            for total, path_core in cands:
                s_tail = [(start_lon, start_lat), path_core[0]]
                e_tail = [path_core[-1], (end_lon, end_lat)]
                crossings = (await _water_hits(
                                 _resample(s_tail, _WATER_SAMPLE_STEP_KM))
                             + await _water_hits(
                                 _resample(e_tail, _WATER_SAMPLE_STEP_KM)))
                eff = total + 50.0 * crossings
                if best_eff is None or eff < best_eff[0]:
                    best_eff = (eff, path_core)
            core = best_eff[1]
        if core and len(core) >= 2:
            break
        core = None
        log.info("local gap at z%d over %d tiles: %s", z, len(tiles),
                 reason)
    if not core or len(core) < 2:
        log.info("local gap refused at every zoom — keeping the "
                 "straight statement")
        return None
    path = [(start_lon, start_lat)] + core + [(end_lon, end_lat)]
    total = sum(_haversine_km(a[1], a[0], b[1], b[0])
                for a, b in zip(path, path[1:]))
    if total > max(dist * 2.5, dist + 15.0):
        log.info("local gap route %.0f km vs %.0f km straight — keeping "
                 "the straight statement", total, dist)
        return None
    log.info("local gap routed: %.0f km over %d z%d tiles (exact "
             "bounded search)", total, len(tiles), z)
    return path


async def route_on_road_hierarchical(
    start_lat: float, start_lon: float,
    end_lat: float, end_lon: float,
) -> Optional[List[Tuple[float, float]]]:
    """Corridor route along the major road network. Returns (lon, lat)
    vertices or None (caller falls open to the straight statement)."""
    from app.api.v1.tiles import _get_client

    dist = _haversine_km(start_lat, start_lon, end_lat, end_lon)
    zc = _corridor_zoom(dist)
    buffer_km = max(15.0, dist * 0.22)

    # Corridor tile set at the coarse zoom: tiles whose center lies
    # within the buffered start-end segment.
    x0, y0 = _tile_xy(min(start_lon, end_lon), max(start_lat, end_lat), zc)
    x1, y1 = _tile_xy(max(start_lon, end_lon), min(start_lat, end_lat), zc)
    pad = 1
    corridor_tiles = []
    for tx in range(x0 - pad, x1 + pad + 1):
        for ty in range(y0 - pad, y1 + pad + 1):
            clon, clat = _tile_center(tx, ty, zc)
            if _seg_dist_km(clat, clon, start_lat, start_lon,
                            end_lat, end_lon) <= buffer_km + 30.0:
                corridor_tiles.append((zc, tx, ty))
    if not corridor_tiles or len(corridor_tiles) > _MAX_CORRIDOR_TILES:
        log.warning("corridor tile set unusable (%d tiles at z%d) — refusing",
                    len(corridor_tiles), zc)
        return None

    # Endpoint connect tiles: fine zoom 3x3 around each endpoint.
    ze = min(11, zc + 3)
    endpoint_tiles = set()
    for lat, lon in ((start_lat, start_lon), (end_lat, end_lon)):
        ex, ey = _tile_xy(lon, lat, ze)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                endpoint_tiles.add((ze, ex + dx, ey + dy))
    if len(endpoint_tiles) > _MAX_ENDPOINT_TILES:
        return None

    client = _get_client()
    import asyncio as _asyncio
    import hashlib as _hashlib
    from app.services.knowledge.routing.contraction_hierarchy import (
        ContractionHierarchy, load_hierarchy, store_hierarchy)
    sem = _asyncio.Semaphore(16)

    async def _fetch(t, kinds):
        async with sem:
            return await _roads_from_tile(client, *t, kinds)

    corridor_ways = await _asyncio.gather(
        *[_fetch(t, _CORRIDOR_KINDS) for t in corridor_tiles])

    def _nearest_candidates(nodes: dict, lon: float, lat: float,
                            max_km: float = 40.0):
        """The _CONNECT_CANDIDATES nearest corridor nodes, nearest
        first — the connect step SCORES resulting routes instead of
        trusting the single nearest node (whose street-grid neighbor
        across a river is exactly the terminal-detour bug)."""
        cands = []
        for key, (nlon, nlat) in nodes.items():
            d = _haversine_km(lat, lon, nlat, nlon)
            if d < max_km:
                cands.append((d, key))
        cands.sort()
        return cands[:_CONNECT_CANDIDATES]

    # THE HIGHWAY FIRST, as far as it goes — smaller corridor classes
    # join only when the motorway network cannot serve the leg. Each
    # class-set's corridor graph is preprocessed ONCE into a
    # CONTRACTION HIERARCHY persisted on the data volume (roads do not
    # move); queries are a bidirectional upward search. Endpoint
    # connects are CANDIDATE-SCORED (cost model cm2): every candidate
    # pair's full route is scored on travel time + heading reversals,
    # the geometric shortlist is water-sampled at its terminal windows
    # and connect legs, and the cheapest route wins.
    for corridor_classes in (("highway",), _CORRIDOR_KINDS):
        sig = _hashlib.md5((_COST_MODEL_REV + "|" + repr(corridor_classes)
                            + "|" + repr(sorted(corridor_tiles))
                            ).encode()).hexdigest()
        ch = load_hierarchy(sig)
        if ch is None:
            graph = _Graph()
            for ways in corridor_ways:
                for kind, line, props in ways:
                    if kind in corridor_classes:
                        graph.add_way(line, kind, props)
            if graph.edges >= _MAX_GRAPH_EDGES:
                log.warning("corridor graph hit the %d edge cap at "
                            "classes %s", _MAX_GRAPH_EDGES,
                            corridor_classes)
            if not graph.nodes:
                continue
            # Preprocessing off the event loop — tile serving never
            # waits on a hierarchy build.
            ch = await _asyncio.to_thread(
                ContractionHierarchy.build, graph.nodes, graph.adj)
            store_hierarchy(sig, ch)
            log.info("CH built + stored for corridor %s (%d nodes, "
                     "classes %s)", sig[:8], len(ch.nodes),
                     corridor_classes)
        s_cands = _nearest_candidates(ch.nodes, start_lon, start_lat)
        e_cands = _nearest_candidates(ch.nodes, end_lon, end_lat)
        if not s_cands or not e_cands:
            continue

        # Geometry pass: score every candidate pair's full route. CPU
        # work off the event loop — tile serving never waits on it.
        def _score_pairs():
            out = []
            for s_d, s_key in s_cands:
                for e_d, e_key in e_cands:
                    if s_key == e_key:
                        continue
                    core = ch.query(s_key, e_key)
                    if not core or len(core) < 2:
                        continue
                    path = ([(start_lon, start_lat)] + core
                            + [(end_lon, end_lat)])
                    core_km = sum(_haversine_km(a[1], a[0], b[1], b[0])
                                  for a, b in zip(core, core[1:]))
                    # Corridor legs at a nominal mixed speed; the
                    # straight connect legs at minor-road speed (they
                    # are off-graph).
                    travel_h = core_km / 75.0 + (s_d + e_d) / 40.0
                    reversals, worst = _count_reversals(path)
                    gscore = travel_h + reversals * _REVERSAL_PENALTY_H
                    out.append((gscore, reversals, worst, s_d, e_d,
                                path))
            return out

        scored = await _asyncio.to_thread(_score_pairs)
        if not scored:
            continue
        scored.sort(key=lambda r: r[0])

        # Water pass on the geometric shortlist: terminal windows of
        # the route plus the two straight connect legs.
        best = None
        for gscore, reversals, worst, s_d, e_d, path in \
                scored[:_SCORE_SHORTLIST]:
            head, tail = _terminal_windows(path, _TERMINAL_WINDOW_KM)
            route_crossings = (
                await _water_hits(_resample(head, _WATER_SAMPLE_STEP_KM))
                + await _water_hits(_resample(tail, _WATER_SAMPLE_STEP_KM)))
            connect_crossings = await _water_hits(
                _resample(path[:2], _WATER_SAMPLE_STEP_KM)
            ) + await _water_hits(
                _resample(path[-2:], _WATER_SAMPLE_STEP_KM))
            score = (gscore
                     + route_crossings * _WATER_CROSSING_PENALTY_H
                     + connect_crossings * _CONNECT_WATER_PENALTY_H)
            if best is None or score < best[0]:
                best = (score, reversals, worst,
                        route_crossings, connect_crossings, path)
        if best is None:
            continue
        score, reversals, worst, route_x, connect_x, path = best

        # Route sanity: a corridor path detouring beyond 2.2x the
        # straight distance means the coarse graph was disconnected
        # somewhere — try the broader class set; the straight statement
        # is more honest than a wild detour.
        total = sum(_haversine_km(a[1], a[0], b[1], b[0])
                    for a, b in zip(path, path[1:]))
        if total > max(dist * 2.2, dist + 60.0):
            log.warning("corridor route %.0f km vs %.0f km straight at "
                        "classes %s — trying broader classes",
                        total, dist, corridor_classes)
            continue
        log.info("corridor route: %.0f km over %d corridor tiles "
                 "(%d candidates scored, %d reversals worst %.0f deg, "
                 "%d water crossings + %d on connect legs)",
                 total, len(corridor_tiles), len(scored), reversals,
                 worst, route_x, connect_x)
        return path
    return None
