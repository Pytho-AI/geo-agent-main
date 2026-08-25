"""Geospatial resolution stages of the ingest pipeline.

  build_ao_from_anchors — geocode the theater/countries/key-locations the
      read stage named, and return the AREA OF OPERATIONS bbox.
  resolve_placements    — for every entity: MGRS grid → coordinates
      (deterministic); else place name → geocode SCOPED TO THE AO. A name
      that resolves nowhere in the AO stays unplaced — the bbox rejects
      out-of-area matches with no model call. Records the genuinely
      ambiguous cases (two strong in-AO candidates) for the visual pass.
  confirm_visually      — render the AO with the laydown on it and let the
      VLM adjudicate ONLY the ambiguous placements against the map + the
      document geography. Out-of-AO was already impossible, so the model
      is never asked about it.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from uuid import UUID

from app.services.geocode import geocode
from app.services.graph_ingest.schema import AreaOfOperations, ExtractedOOB
from app.services.graph_ingest.extract import _vlm_json, _image_block
from app.utils.mgrs_utils import is_mgrs_string, mgrs_to_latlng

log = logging.getLogger("app.graph_ingest.resolve")

_MAX_AO_SPAN_DEG = 26.0    # clamp a runaway anchor set to a sane theater
_MIN_AO_SPAN_DEG = 0.8
_AMBIG_SCORE_GAP = 0.08    # 2nd candidate this close in score = ambiguous
_AMBIG_MIN_SEP_DEG = 0.25  # ...and this far apart in space


def _bbox_of(points: List[dict], pad_frac: float = 0.0,
             pad_deg: float = 0.0) -> Optional[Tuple[float, float, float, float]]:
    pts = [(p["lon"], p["lat"]) for p in points
           if p.get("lon") is not None and p.get("lat") is not None]
    if not pts:
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    w, e = min(lons), max(lons)
    s, n = min(lats), max(lats)
    px = max(pad_deg, (e - w) * pad_frac)
    py = max(pad_deg, (n - s) * pad_frac)
    return (w - px, s - py, e + px, n + py)


def _clamp_span(box: Tuple[float, float, float, float]):
    w, s, e, n = box
    cx, cy = (w + e) / 2, (s + n) / 2
    dx, dy = e - w, n - s
    dx = min(max(dx, _MIN_AO_SPAN_DEG), _MAX_AO_SPAN_DEG)
    dy = min(max(dy, _MIN_AO_SPAN_DEG), _MAX_AO_SPAN_DEG)
    return (max(-180, cx - dx / 2), max(-85, cy - dy / 2),
            min(180, cx + dx / 2), min(85, cy + dy / 2))


def _plausible_bbox(b) -> bool:
    try:
        w, s, e, n = (float(v) for v in b)
    except (TypeError, ValueError):
        return False
    return -180 <= w < e <= 180 and -85 <= s < n <= 85


async def build_ao_from_anchors(*, theater, countries, key_locations,
                                bbox_hint, note, source_label) -> AreaOfOperations:
    """Geocode the named anchors and derive the AO bbox. Countries fix a
    coarse region (world sweep); key locations are then resolved INSIDE
    that region and tighten it."""
    anchors: List[dict] = []
    for cty in (countries or [])[:8]:
        cands = await geocode(cty, bbox=None, limit=1)
        if cands:
            c = cands[0]
            anchors.append({"name": c.name, "lon": c.lon, "lat": c.lat,
                            "kind": c.kind or "country"})

    seed = _bbox_of(anchors, pad_deg=3.0)
    seed = _clamp_span(seed) if seed else None
    near = ((seed[0] + seed[2]) / 2, (seed[1] + seed[3]) / 2) if seed else None

    for loc in (key_locations or [])[:24]:
        cands = await geocode(loc, bbox=seed, near=near, limit=1)
        if cands:
            c = cands[0]
            anchors.append({"name": c.name, "lon": c.lon, "lat": c.lat,
                            "kind": c.kind_detail or c.kind or "place"})

    box = _bbox_of(anchors, pad_frac=0.25, pad_deg=0.5)
    if bbox_hint and _plausible_bbox(bbox_hint):
        hint = tuple(float(v) for v in bbox_hint)
        box = (min(box[0], hint[0]), min(box[1], hint[1]),
               max(box[2], hint[2]), max(box[3], hint[3])) if box else hint
    resolved = box is not None and len(anchors) > 0
    if box is None:
        box = tuple(float(v) for v in bbox_hint) if _plausible_bbox(bbox_hint) \
            else (-180.0, -85.0, 180.0, 85.0)
    box = _clamp_span(box)
    return AreaOfOperations(
        theater=theater, countries=list(countries or []),
        west=box[0], south=box[1], east=box[2], north=box[3],
        anchors=anchors, note=note, resolved=resolved)


@dataclass
class PlacementResult:
    placed: int = 0
    from_grid: int = 0
    from_name: int = 0
    track_points: int = 0                                    # dated observations resolved
    unresolved: List[dict] = field(default_factory=list)   # {name, text}
    ambiguous: List[dict] = field(default_factory=list)     # {name, text, candidates:[...]}


# A UNIT or installation is a POINT — it is never located at a country or
# region centroid. When the model gives a unit a country/region as its
# "location_text" ("Poland", "Lithuania"), the geocoder returns that
# polity's centroid (Poland → 19.13,52.22), which plots the unit in the
# middle of the country — worse than leaving it unplaced. Drop those kinds
# from placement candidates (AO anchoring still uses countries, upstream).
_NON_POINT_KINDS = {"country", "region", "macroregion", "disputed"}


def _point_places(cands: list) -> list:
    return [c for c in cands if (c.kind or "").lower() not in _NON_POINT_KINDS]


def _sep(a, b) -> float:
    return math.hypot(a.lon - b.lon, a.lat - b.lat)


def _pad_bbox(bbox, deg: float):
    w, s, e, n = bbox
    return (max(-180, w - deg), max(-85, s - deg),
            min(180, e + deg), min(85, n + deg))


async def resolve_placements(oob: ExtractedOOB, ao: AreaOfOperations) -> PlacementResult:
    """Set lon/lat on each entity from its grid or its place name (AO
    scoped). Mutates the entities in place; returns a placement summary."""
    res = PlacementResult()
    near = ao.center

    async def _resolve_point(mgrs_str, place_text):
        """(lon, lat, how) from a grid (deterministic) or a place name
        (AO-scoped strict geocode). The GRID IS AUTHORITATIVE and is never
        overridden or "reconciled" from the geocoder: a road to war
        legitimately reports the same unit at different grids on different
        dates — those are TRACK POINTS, not typos to average away. A
        genuinely suspect grid surfaces in the placement report's
        nearest-place echo for the agent (or the analyst) to judge with
        the document in hand."""
        if mgrs_str and is_mgrs_string(mgrs_str):
            try:
                la, lo = mgrs_to_latlng(mgrs_str)
                return lo, la, "grid"
            except Exception:
                pass
        if place_text:
            cands = _point_places(
                await geocode(place_text, bbox=ao.bbox, near=near, limit=6))
            if not cands:
                cands = _point_places(await geocode(
                    place_text, bbox=_pad_bbox(ao.bbox, 6.0), near=near, limit=6))
            if cands:
                return cands[0].lon, cands[0].lat, "name"
        return None, None, None

    def _grids_to_coords(grids):
        coords = []
        for g in grids:
            if g and is_mgrs_string(g):
                try:
                    la, lo = mgrs_to_latlng(g)
                    coords.append([lo, la])
                except Exception:
                    continue
        return coords if len(coords) >= 2 else None

    def _circle_ring(mgrs, radius_m, n=24):
        try:
            la, lo = mgrs_to_latlng(mgrs)
        except Exception:
            return None
        ring = []
        for i in range(n):
            th = 2.0 * math.pi * i / n
            dla = (radius_m * math.cos(th)) / 111320.0
            dlo = ((radius_m * math.sin(th))
                   / (111320.0 * math.cos(math.radians(la))))
            ring.append([lo + dlo, la + dla])
        return ring

    from app.services.graph_ingest.area_synthesis import (
        synthesize_area, TERRAIN_SHAPED_KINDS)

    for ent in oob.entities:
        # Center + radius notation. The order states center and radius;
        # the SYSTEM draws the doctrinal graphic — terrain-shaped for
        # area features (on land, water excluded, cover-weighted), the
        # stated circle only where a circle IS the doctrinal form (an
        # NFA radius around a point target) or terrain is unreadable.
        if ent.circle and not ent.area:
            mgrs = ent.circle.get("mgrs")
            radius = float(ent.circle.get("radius_m") or 0) or 1.0
            ring = None
            if ent.entity_type in TERRAIN_SHAPED_KINDS:
                try:
                    la, lo = mgrs_to_latlng(mgrs)
                    ring = await synthesize_area(
                        la, lo, radius, ent.entity_type)
                except Exception:
                    ring = None
            if ring is None:
                ring = _circle_ring(mgrs, radius)
            if ring:
                ent.area_coords = ring
                res.placed += 1
                res.from_grid += 1
                continue
        # Control-measure vertex sequences (deterministic grid math).
        if ent.line:
            ent.line_coords = _grids_to_coords(ent.line)
            if ent.line_coords:
                from app.services.graph_ingest.route_geometry import (
                    ROAD_FOLLOWED_KINDS, road_follow)
                if ent.entity_type in ROAD_FOLLOWED_KINDS:
                    ent.line_coords = await road_follow(
                        ent.line_coords, ent.entity_type)
                res.placed += 1
                res.from_grid += 1
                continue
        if ent.area:
            ent.area_coords = _grids_to_coords(ent.area)
            if ent.area_coords:
                res.placed += 1
                res.from_grid += 1
                continue
        # The position TRACK first: resolve every dated observation the
        # document gave this unit (oldest → newest, as extracted).
        for p in ent.positions:
            plon, plat, _how = await _resolve_point(p.mgrs, p.location_text)
            if plon is not None:
                p.lon, p.lat = plon, plat
                res.track_points += 1
        # The unit's CURRENT position: an explicit lon/lat or grid wins;
        # otherwise the newest resolved track point IS the laydown.
        if ent.lon is not None and ent.lat is not None:
            res.placed += 1
            continue

        # grid → point (deterministic, precise)
        grid_pt: Optional[Tuple[float, float]] = None
        if ent.mgrs and is_mgrs_string(ent.mgrs):
            try:
                lat, lon = mgrs_to_latlng(ent.mgrs)
                grid_pt = (lon, lat)
            except Exception:
                grid_pt = None
        if grid_pt is None:
            placed_track = [p for p in ent.positions if p.lon is not None]
            if placed_track:
                newest = placed_track[-1]
                ent.lon, ent.lat = newest.lon, newest.lat
                res.placed += 1
                res.from_grid += 1
                continue

        cands = []
        if grid_pt is None and ent.location_text:
            cands = _point_places(
                await geocode(ent.location_text, bbox=ao.bbox, near=near, limit=6))
            if not cands:
                cands = _point_places(await geocode(
                    ent.location_text, bbox=_pad_bbox(ao.bbox, 6.0), near=near, limit=6))

        if grid_pt is not None:
            ent.lon, ent.lat = grid_pt
            res.placed += 1
            res.from_grid += 1
            continue

        if cands:
            # Tight AO first (fast, cached, disambiguates common names);
            # then widen — a unit the document explicitly locates can sit
            # in the operational rear just outside the tactical box
            # (Elbląg, ~3° west of the Suwałki-gap AO). Strict matching +
            # the AO-center bias keep the widened search from false-
            # positiving; near ranks the right one when a name repeats.
            ent.lon, ent.lat = cands[0].lon, cands[0].lat
            res.placed += 1
            res.from_name += 1
            if (len(cands) > 1 and cands[1].score >= cands[0].score - _AMBIG_SCORE_GAP
                    and _sep(cands[0], cands[1]) >= _AMBIG_MIN_SEP_DEG):
                res.ambiguous.append({
                    "name": ent.name, "text": ent.location_text,
                    "candidates": [c.as_dict() for c in cands]})
        elif ent.location_text:
            res.unresolved.append({"name": ent.name, "text": ent.location_text})
    return res


def _render_dims(ao: AreaOfOperations, longest: int = 1024) -> Tuple[int, int]:
    w, s, e, n = ao.bbox
    # web-mercator vertical compression at the AO's mid-latitude
    latf = max(0.1, math.cos(math.radians((s + n) / 2)))
    dx = max(0.01, (e - w) * latf)
    dy = max(0.01, (n - s))
    if dx >= dy:
        return longest, max(360, int(longest * dy / dx))
    return max(360, int(longest * dx / dy)), longest


_CONFIRM_SYSTEM = (
    "You are the placement-check stage of a military training-simulation "
    "ingest. You are shown the area-of-operations map with the extracted "
    "force plotted, and a few places whose name matched more than one spot "
    "inside the area. You pick the plotting that fits the operational "
    "geography the document describes. You never place anything off-map."
)


async def confirm_visually(project_id: UUID, ao: AreaOfOperations,
                           ambiguous: List[dict]) -> List[dict]:
    """Render the AO with the laydown and let the VLM resolve the
    ambiguous placements. Returns [{name, lon, lat}] corrections. No
    ambiguity → no render, no model call."""
    if not ambiguous:
        return []
    import asyncio
    from app.services.render.headless import render_map_to_png, RenderOptions
    try:
        w, h = _render_dims(ao)
        # HARD timeout — a headless-render stall must never hang an
        # ingest. If the confirmation render is slow or unavailable we
        # keep the top geocode picks rather than block.
        jpg = await asyncio.wait_for(
            render_map_to_png(project_id, RenderOptions(
                width=w, height=h, bbox=list(ao.bbox), timeout_ms=30000)),
            timeout=90)
    except Exception as exc:
        log.warning("AO confirmation render unavailable (%s) — keeping top geocode picks", exc)
        return []

    summary = [{"place": a["name"], "referenced_as": a["text"],
                "candidates": [{"i": i, "name": c["name"],
                                "lon": c["lon"], "lat": c["lat"],
                                "detail": c.get("kind_detail")}
                               for i, c in enumerate(a["candidates"])]}
               for a in ambiguous]
    instruction = (
        "The image is the area of operations with the extracted force plotted. "
        "Each place below matched more than one location inside the area. For "
        "each, choose the candidate index whose position best fits where the "
        "document places that unit; use -1 only if none fit.\n"
        + json.dumps(summary)
        + '\nOutput ONLY JSON: {"choices":[{"place":"...","index":<int>}]}')
    raw = await _vlm_json(_CONFIRM_SYSTEM, instruction, [_image_block(jpg)], max_tokens=512)

    corrections: List[dict] = []
    by_place = {a["name"]: a["candidates"] for a in ambiguous}
    for ch in (raw or {}).get("choices", []) if isinstance(raw, dict) else []:
        place, idx = ch.get("place"), ch.get("index")
        cands = by_place.get(place)
        if cands and isinstance(idx, int) and 0 <= idx < len(cands):
            c = cands[idx]
            corrections.append({"name": place, "lon": c["lon"], "lat": c["lat"]})
    return corrections
