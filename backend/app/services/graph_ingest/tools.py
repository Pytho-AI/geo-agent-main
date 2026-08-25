"""The READ / VERIFY tool surface over the entity graph (design:
scratch/docs/oob/extraction-decision-spec.md; write side superseded by
tool-surface-consolidation.md S17).

EVERY verb works in BATCHES: a list of flat items in, per-item echoes
out; one item's failure never sinks the batch (an error echo occupies
its slot). Names are the handle everywhere; grids are exact math and
are never moved; nearest_place echoes are read-only context.

The WRITE half of this module was REMOVED at the S17 cutover
(2026-07-28): every record write goes through the world surface's
general verbs (app/api/v1/world_repair.py — assert / update / retract /
purge), which land committed assertions chained to captured L0 and
share this module's session/nudge/echo conventions.

Exposed over MCP by app/mcp_server.py; equally callable in-process.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select

from app.db.session import async_session
from app.models.graph import (
    GraphEdge, GraphHolding, GraphNode, GraphNodePosition, ForceTemplate,
)
from app.services.geocode import geocode, reverse_geocode
from app.services.geocode.service import ascii_place
from app.utils.mgrs_utils import is_mgrs_string, latlng_to_mgrs, mgrs_to_latlng

log = logging.getLogger("app.graph_ingest.tools")

_ECHO_CONCURRENCY = 8


def _fold(v: str) -> str:
    from app.services.graph_ingest.ingest import _norm_name
    return _norm_name(v or "")


async def _nudge(project_id) -> None:
    from app.api.v1.graph import _nudge as nudge, _entity_count
    async with async_session() as db:
        await nudge(project_id, await _entity_count(db, project_id))


async def _find_node(db, project_id: UUID, name: str) -> GraphNode:
    """Resolve a NAME to its node: exact fold match, else unique
    substring. Raises ValueError listing near-misses."""
    rows = (await db.execute(select(GraphNode).where(
        GraphNode.project_id == project_id, GraphNode.layer == "project"))).scalars().all()
    want = _fold(name)
    exact = [n for n in rows if _fold(n.name) == want]
    if len(exact) == 1:
        return exact[0]
    partial = [n for n in rows if want and want in _fold(n.name)]
    if len(partial) == 1:
        return partial[0]
    pool = exact or partial
    if pool:
        raise ValueError(
            f"'{name}' matches {len(pool)} entities: "
            + "; ".join(sorted(n.name for n in pool)[:8]))
    close = [n.name for n in rows
             if any(tok in _fold(n.name) for tok in want.split()[:2])][:8]
    raise ValueError(
        f"no entity named '{name}' in this project"
        + (f" — nearest names: {'; '.join(close)}" if close else ""))


async def _graph_bbox(db, project_id: UUID, pad: float = 1.0):
    row = (await db.execute(select(
        func.ST_XMin(func.ST_Extent(GraphNode.geom)),
        func.ST_YMin(func.ST_Extent(GraphNode.geom)),
        func.ST_XMax(func.ST_Extent(GraphNode.geom)),
        func.ST_YMax(func.ST_Extent(GraphNode.geom)),
    ).where(GraphNode.project_id == project_id, GraphNode.layer == "project",
            GraphNode.geom.isnot(None)))).first()
    if not row or row[0] is None:
        return None
    return (row[0] - pad, row[1] - pad, row[2] + pad, row[3] + pad)


async def _nearest_place(lon: float, lat: float) -> Optional[dict]:
    places = await reverse_geocode(lon, lat, limit=1)
    return places[0] if places else None


async def _enrich_nearest(echoes: List[dict]) -> None:
    """Concurrently attach nearest_place to echoes carrying lat/lon
    (sequential lookups blew MCP client timeouts — observed)."""
    sem = asyncio.Semaphore(_ECHO_CONCURRENCY)

    async def one(e):
        if e.get("lat") is None or e.get("lon") is None:
            return
        async with sem:
            e["nearest_place"] = await _nearest_place(e["lon"], e["lat"])

    await asyncio.gather(*[one(e) for e in echoes])


def _dest_point(lat: float, lon: float, bearing_deg: float,
                distance_km: float):
    """Spherical destination point."""
    R = 6371.0
    br = math.radians(bearing_deg)
    la1 = math.radians(lat)
    lo1 = math.radians(lon)
    d = distance_km / R
    la2 = math.asin(math.sin(la1) * math.cos(d)
                    + math.cos(la1) * math.sin(d) * math.cos(br))
    lo2 = lo1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540.0) % 360.0 - 180.0


# ── READ / VERIFY (batched) ──────────────────────────────────────────


async def tool_mgrs_to_latlon(grids: List[str]) -> dict:
    out = []
    for g in grids:
        if not is_mgrs_string(g):
            out.append({"mgrs": g, "error": "not a valid MGRS string "
                        "(expected like '34UEE 64392 54490')"})
            continue
        try:
            lat, lon = mgrs_to_latlng(g)
            out.append({"mgrs": g, "lat": round(lat, 6), "lon": round(lon, 6)})
        except Exception as e:
            out.append({"mgrs": g, "error": f"conversion failed: {e}"})
    await _enrich_nearest(out)
    return {"results": out}


async def tool_latlon_to_mgrs(points: List[dict]) -> dict:
    out = []
    for p in points:
        try:
            out.append({"lat": p["lat"], "lon": p["lon"],
                        "mgrs": latlng_to_mgrs(p["lat"], p["lon"])})
        except Exception as e:
            out.append({**p, "error": f"conversion failed: {e}"})
    return {"results": out}


async def tool_reverse_geocode(points: List[dict]) -> dict:
    sem = asyncio.Semaphore(_ECHO_CONCURRENCY)

    async def one(p):
        try:
            async with sem:
                places = await reverse_geocode(p["lon"], p["lat"], limit=5)
            return {"lat": p["lat"], "lon": p["lon"],
                    "nearest_places": places}
        except Exception as e:
            return {**p, "error": str(e)}

    results = list(await asyncio.gather(*[one(p) for p in points]))
    # Landcover classification rides the echo (ESA WorldCover) — the
    # audit question "is this unit in water?" is answerable per point
    # without leaving the tool surface.
    try:
        from app.services.knowledge.landcover import get_land_cover_grid
        codes = await get_land_cover_grid(
            [(p["lat"], p["lon"]) for p in points])
        for r, lc in zip(results, codes):
            if lc is not None:
                r["landcover"] = lc.name
                r["is_water"] = lc.code == 80
    except Exception:
        pass                                    # echo enrichment only
    return {"results": results}


async def tool_snap_to_feature(points: List[dict]) -> dict:
    """Snap points onto the nearest OSM linear feature (railway|road).
    Each item: {lat, lon, feature: 'railway'|'road', radius_m?}. Echo
    carries the snapped lat/lon, moved_km, and the way name. For
    placing linear infrastructure (a rail segment onto the rail line, an
    MSR waypoint onto the road) precisely from an approximate point."""
    from app.services.geocode.snap import snap_to_osm_feature
    sem = asyncio.Semaphore(_ECHO_CONCURRENCY)

    async def one(p):
        try:
            async with sem:
                lat, lon, moved, way = await snap_to_osm_feature(
                    p["lat"], p["lon"], p.get("feature", "railway"),
                    int(p.get("radius_m", 3000)))
            return {"lat": lat, "lon": lon, "moved_km": moved,
                    "way_name": way, "feature": p.get("feature", "railway"),
                    "snapped": bool(moved and moved > 0)}
        except Exception as e:
            return {**p, "error": str(e)}

    return {"results": list(await asyncio.gather(*[one(p) for p in points]))}


async def tool_geocode_places(queries: List[dict],
                              project_id: Optional[str] = None) -> dict:
    default_bbox = None
    if project_id:
        async with async_session() as db:
            default_bbox = await _graph_bbox(db, UUID(project_id), pad=3.0)
    out = []
    for q in queries:
        bbox = None
        if None not in (q.get("west"), q.get("south"),
                        q.get("east"), q.get("north")):
            bbox = (q["west"], q["south"], q["east"], q["north"])
        else:
            bbox = default_bbox
        cands = await geocode(q.get("query", ""), bbox=bbox, limit=6)
        item = {"query": q.get("query"),
                "scoped_to": list(bbox) if bbox else
                "world (countries/major cities only)",
                "candidates": [ascii_place(c.as_dict()) for c in cands]}
        if not cands and bbox and (bbox[2] - bbox[0] > 8.0
                                   or bbox[3] - bbox[1] > 8.0):
            item["hint"] = ("search area is continental-scale — villages "
                            "and small towns need a tighter "
                            "west/south/east/north box (a degree or two)")
        out.append(item)
    return {"results": out}


async def tool_project_points(items: List[dict]) -> dict:
    """Offset points by bearing/distance — the DIRECTIONAL placement rung
    ('within 10 km of the border on the enemy side') without hand math."""
    out = []
    for it in items:
        try:
            la, lo = _dest_point(it["lat"], it["lon"],
                                 it["bearing_deg"], it["distance_km"])
            out.append({**it, "dest_lat": round(la, 6),
                        "dest_lon": round(lo, 6),
                        "dest_mgrs": latlng_to_mgrs(la, lo)})
        except Exception as e:
            out.append({**it, "error": str(e)})
    return {"results": out}


async def tool_list_entities(project_id: str) -> dict:
    pid = UUID(project_id)
    async with async_session() as db:
        rows = (await db.execute(select(
            GraphNode, func.ST_AsGeoJSON(GraphNode.geom),
            # Representative point for line/area entities so their
            # echoes carry lat/lon/mgrs instead of nulls (a shape IS
            # somewhere; PointOnSurface guarantees it is on the shape).
            func.ST_AsGeoJSON(func.ST_PointOnSurface(GraphNode.geom)),
        ).where(GraphNode.project_id == pid, GraphNode.layer == "project")
         .order_by(GraphNode.name))).all()
        track_counts = dict((await db.execute(
            select(GraphNodePosition.node_id, func.count())
            .join(GraphNode, GraphNode.id == GraphNodePosition.node_id)
            .where(GraphNode.project_id == pid, GraphNode.layer == "project")
            .group_by(GraphNodePosition.node_id))).all())
        by_id = {n.id: n for n, _, _ in rows}
        ents = []
        import json as _json
        for n, gj, rep_gj in rows:
            geometry = _json.loads(gj) if gj else None
            lat = lon = None
            shape = None
            if geometry:
                if geometry["type"] == "Point":
                    lon, lat = geometry["coordinates"][0], geometry["coordinates"][1]
                else:
                    shape = geometry["type"]
                    rep = _json.loads(rep_gj) if rep_gj else None
                    if rep and rep.get("coordinates"):
                        lon, lat = rep["coordinates"][0], rep["coordinates"][1]
            parent = by_id.get(n.organic_parent_id)
            ents.append({
                "name": n.name, "entity_type": n.entity_type,
                "affiliation": n.affiliation, "echelon": n.echelon,
                "lat": round(lat, 5) if lat is not None else None,
                "lon": round(lon, 5) if lon is not None else None,
                "mgrs": (latlng_to_mgrs(lat, lon)
                         if lat is not None else None),
                "shape": shape,
                "parent": parent.name if parent else None,
                "track_points": track_counts.get(n.id, 0),
                "combat_effectiveness": n.combat_effectiveness,
            })
        bbox = await _graph_bbox(db, pid, pad=0.0)
    return {"project_id": project_id, "entities": ents,
            "placed": sum(1 for e in ents
                          if e["lat"] is not None or e["shape"]),
            "bbox_of_placed": list(bbox) if bbox else None}


async def tool_get_entities(project_id: str, names: List[str]) -> dict:
    """Full per-entity detail — fields, parent, children, holdings,
    edges, and the complete position track."""
    pid = UUID(project_id)
    out = []
    async with async_session() as db:
        for name in names:
            try:
                n = await _find_node(db, pid, name)
            except ValueError as e:
                out.append({"name": name, "error": str(e)})
                continue
            parent = await db.get(GraphNode, n.organic_parent_id) \
                if n.organic_parent_id else None
            children = (await db.execute(select(GraphNode.name).where(
                GraphNode.organic_parent_id == n.id))).scalars().all()
            holdings = (await db.execute(select(GraphHolding).where(
                GraphHolding.node_id == n.id))).scalars().all()
            from app.models.reference import WegEquipment as _WE
            catalogs = ({n.weg_id: await db.get(_WE, n.weg_id)}
                        if n.weg_id else {})
            edges_out = (await db.execute(
                select(GraphEdge, GraphNode.name)
                .join(GraphNode, GraphNode.id == GraphEdge.to_id)
                .where(GraphEdge.from_id == n.id))).all()
            edges_in = (await db.execute(
                select(GraphEdge, GraphNode.name)
                .join(GraphNode, GraphNode.id == GraphEdge.from_id)
                .where(GraphEdge.to_id == n.id))).all()
            obs = (await db.execute(select(
                GraphNodePosition, func.ST_AsGeoJSON(GraphNodePosition.geom),
            ).where(GraphNodePosition.node_id == n.id)
             .order_by(GraphNodePosition.observed_at.asc().nulls_first(),
                       GraphNodePosition.created_at))).all()
            import json as _json
            track = []
            for o, gj in obs:
                g = _json.loads(gj) if gj else None
                track.append({
                    # The observation HANDLE — what add_positions'
                    # set_time_on repair override takes back. Rows
                    # with observed_at null sort FIRST: they are
                    # defects awaiting manual repair against the
                    # source documentation.
                    "observation": str(o.id),
                    "dtg": o.dtg_label,
                    "observed_at": (o.observed_at.isoformat()
                                    if o.observed_at else None),
                    "mgrs": o.mgrs, "location_text": o.location_text,
                    "geometry_type": g["type"] if g else None,
                    "lat": (round(g["coordinates"][1], 5)
                            if g and g["type"] == "Point" else None),
                    "lon": (round(g["coordinates"][0], 5)
                            if g and g["type"] == "Point" else None),
                    "activity": o.activity, "source": o.source,
                })
            out.append({
                "name": n.name, "entity_type": n.entity_type,
                "affiliation": n.affiliation, "echelon": n.echelon,
                "unit_type": n.unit_type, "category": n.category,
                "posture": n.posture, "notes": n.notes,
                "significance": n.significance,
                "combat_effectiveness": n.combat_effectiveness,
                "personnel_authorized": n.personnel_authorized,
                "personnel_current": n.personnel_current,
                "parent": parent.name if parent else None,
                "children": sorted(children),
                "holdings": [{"nomenclature": h.nomenclature_raw or h.weg_id,
                              "weg_id": h.weg_id,
                              "count_authorized": h.count_authorized,
                              "count_current": h.count_current}
                             for h in holdings],
                "edges_out": (
                    [{"to": nm, "type": e.relationship_type}
                     for e, nm in edges_out]
                    # instance_of is VIRTUAL (design decision: stored
                    # once as weg_id, surfaced as a link so traversal
                    # is uniform from a placed instance into the
                    # immutable reference layer).
                    + ([{"to": (catalogs.get(n.weg_id).name
                                if catalogs.get(n.weg_id) else n.weg_id),
                         "type": "instance_of",
                         "reference_weg_id": n.weg_id, "virtual": True}]
                       if n.weg_id else [])),
                "edges_in": [{"from": nm, "type": e.relationship_type}
                             for e, nm in edges_in],
                "track": track,
            })
    return {"results": out}


async def tool_find_templates(query: str = "",
                              echelon: Optional[str] = None) -> dict:
    async with async_session() as db:
        rows = (await db.execute(select(ForceTemplate)
                                 .order_by(ForceTemplate.key))).scalars().all()
    q_tokens = _fold(query).split()
    out = []
    for t in rows:
        if echelon and (t.echelon or "").lower() != echelon.lower():
            continue
        hay = f"{_fold(t.key)} {_fold(t.name)}"
        if q_tokens and not all(tok in hay for tok in q_tokens):
            continue
        side = ("US/NATO" if t.key.startswith("us_")
                else "China" if t.key.startswith("chn_") else "Russia/OPFOR")
        out.append({"key": t.key, "name": t.name,
                    "echelon": t.echelon, "side": side})
    return {"templates": out[:40], "total_matching": len(out)}


async def tool_get_templates(keys: List[str]) -> dict:
    from app.services.graph_ingest.ingest import resolve_template
    out = []
    async with async_session() as db:
        for key in keys:
            tpl, collisions = await resolve_template(db, key)
            if tpl is None and collisions:
                out.append({"key": key, "error": "ambiguous name",
                            "matching_keys": [t.key for t in collisions]})
                continue
            if tpl is None:
                out.append({"key": key,
                            "error": "no such template — use find_templates"})
                continue
            nodes = (await db.execute(select(GraphNode).where(
                GraphNode.template_id == tpl.id))).scalars().all()
            holds = (await db.execute(
                select(GraphHolding, GraphNode.name)
                .join(GraphNode, GraphNode.id == GraphHolding.node_id)
                .where(GraphNode.template_id == tpl.id))).all()
            out.append({
                "key": tpl.key, "name": tpl.name, "echelon": tpl.echelon,
                "units": [{"name": n.name, "echelon": n.echelon,
                           "unit_type": n.unit_type} for n in nodes][:80],
                "equipment": [{"on_unit": uname,
                               "nomenclature": h.nomenclature_raw or h.weg_id,
                               "count": h.count_authorized}
                              for h, uname in holds][:80],
            })
    return {"results": out}


def _fold_query(s: str) -> str:
    """Punctuation-fold one search term (query side of the folded
    identity match)."""
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", str(s).lower())


def _folded_identity_expr(WegEquipment):
    """The record's identity fields (name, id, designations) lowercased
    with everything but letters/digits stripped — the DB side of the
    punctuation-folded match."""
    return func.regexp_replace(
        func.lower(
            func.coalesce(WegEquipment.name, "")
            .concat(" ").concat(func.coalesce(WegEquipment.weg_id, ""))
            .concat(" ").concat(
                func.coalesce(WegEquipment.alternative_designations, ""))),
        "[^a-z0-9]+", "", "g")


def equipment_conditions(q=None, domain=None, equipment_class=None,
                         category=None, country=None, operator=None,
                         year_min=None, year_max=None, category_group=None,
                         exclude=None):
    """The catalog filter set as SQLAlchemy conditions — ONE builder for
    the REST list/facets endpoints AND the tool surface. `exclude` drops
    one dimension so faceted counting can compute each facet's options
    with every OTHER active filter applied."""
    from app.models.reference import WegEquipment, WegEquipmentAlias
    exclude = exclude or ()
    conds = []
    if q and "q" not in exclude:
        like = f"%{q}%"
        folded_q_whole = _fold_query(q)
        alias_ids = select(WegEquipmentAlias.weg_id).where(
            WegEquipmentAlias.alias.ilike(like)
            | func.regexp_replace(func.lower(WegEquipmentAlias.alias),
                                  "[^a-z0-9]+", "", "g")
            .like(f"%{folded_q_whole}%" if folded_q_whole else like))
        # Multi-term content search: every term must appear SOMEWHERE in
        # the record's full search blob (name, designations, origin,
        # operators, description, every specification value) — so
        # "thermobaric launcher" or "tandem warhead" finds systems by
        # substance, for the human search box and the agent's
        # search_equipment tool alike (one builder backs both).
        # Each term ALSO matches punctuation-folded against the identity
        # fields, because designations are written every way at once —
        # "b2" must find the B-2 Spirit, "t90" the T-90 (hyphens,
        # underscores and spaces all fold away on both sides).
        folded_identity = _folded_identity_expr(WegEquipment)
        terms = [t for t in str(q).split() if t.strip()]
        blob_hit = None
        for t in terms:
            c = WegEquipment.search_blob.ilike(f"%{t}%")
            ft = _fold_query(t)
            if ft:
                c = c | folded_identity.like(f"%{ft}%")
            blob_hit = c if blob_hit is None else (blob_hit & c)
        name_hit = (WegEquipment.name.ilike(like)
                    | WegEquipment.weg_id.ilike(like)
                    | WegEquipment.country_of_origin.ilike(like)
                    | WegEquipment.weg_id.in_(alias_ids))
        conds.append(name_hit | blob_hit if blob_hit is not None else name_hit)
    if domain and "domain" not in exclude:
        conds.append(WegEquipment.domain == domain)
    if equipment_class and "class" not in exclude:
        conds.append(WegEquipment.equipment_class == equipment_class)
    if category and "category" not in exclude:
        conds.append(WegEquipment.category == category)
    # The source's hierarchy: domain > group > category(leaf) > class.
    if category_group and "category_group" not in exclude:
        conds.append(WegEquipment.category_group == category_group)
    if country and "country" not in exclude:
        conds.append(WegEquipment.countries.contains([country]))
    if operator and "operator" not in exclude:
        conds.append(WegEquipment.operators.contains([operator]))
    if year_min is not None and "year" not in exclude:
        conds.append(WegEquipment.introduction_year >= year_min)
    if year_max is not None and "year" not in exclude:
        conds.append(WegEquipment.introduction_year <= year_max)
    return conds


# One-turn retrieval cap: how many matches per search item carry their
# FULL sheet when the caller asks for sheets inline. Enough for any
# comparison question; a broader sweep reads the summary rows and pulls
# specific sheets in a correction turn.
_INLINE_SHEETS_CAP = 8


def equipment_ranking(q: Optional[str]):
    """ORDER BY for an equipment search. A text query ranks by
    RELEVANCE, never the alphabet: systems whose NAME or id carries the
    query rank above systems that merely mention it in their content
    (the search blob reaches every spec, so 'T-90' also matches every
    sheet that compares itself to one), trigram similarity to the name
    breaks ties, and the alphabet is only the final tiebreak."""
    from sqlalchemy import case
    from app.models.reference import WegEquipment
    if not q:
        return [WegEquipment.name.asc()]
    like = f"%{q}%"
    name_hit = (WegEquipment.name.ilike(like)
                | WegEquipment.weg_id.ilike(like)
                | WegEquipment.alternative_designations.ilike(like))
    # Punctuation-folded identity carriers rank with the literal ones:
    # every query term found in the folded name/id/designations ("b2
    # bomber" against "B-2 Spirit ... Strategic Bomber") is a tier-0
    # hit, not a content mention.
    folded_identity = _folded_identity_expr(WegEquipment)
    folded_hit = None
    for t in str(q).split():
        ft = _fold_query(t)
        if not ft:
            continue
        c = folded_identity.like(f"%{ft}%")
        folded_hit = c if folded_hit is None else (folded_hit & c)
    tier0 = name_hit | folded_hit if folded_hit is not None else name_hit
    # Exact folded designation match ("t90" == fold("T-90")) outranks a
    # prefix match, which outranks containment; trigram similarity to
    # the display name breaks ties inside each tier.
    fq = _fold_query(q)
    tiers = case(
        ((folded_identity.like(f"{fq}%") if fq else name_hit), 0),
        (tier0, 1),
        else_=2,
    ).asc()
    return [tiers,
            func.similarity(func.lower(WegEquipment.name),
                            q.lower()).desc(),
            WegEquipment.name.asc()]


async def _full_sheet(db, row) -> dict:
    """Everything the catalog holds on one system — THE sheet shape,
    shared by get_equipment_sheets, search_equipment(sheets=true) and
    resolve_equipment(sheets=true), so every read path emits identical
    sheets."""
    from app.models.reference import (
        WegEquipmentEmitter, WegEquipmentRangeCandidate)
    cands = (await db.execute(
        select(WegEquipmentRangeCandidate)
        .where(WegEquipmentRangeCandidate.weg_id == row.weg_id)
        .order_by(WegEquipmentRangeCandidate.range_m))).scalars().all()
    emitters = (await db.execute(
        select(WegEquipmentEmitter)
        .where(WegEquipmentEmitter.weg_id == row.weg_id))).scalars().all()
    sheet = row.sheet_data or {}
    return {
        "weg_id": row.weg_id, "name": row.name,
        "class": row.equipment_class, "domain": row.domain,
        "category": row.category,
        "origin": row.countries or [],
        "operators": row.operators or [],
        "introduction_year": row.introduction_year,
        "crew": row.crew, "caliber": row.caliber,
        "combat_weight": row.combat_weight,
        "specifications": sheet.get("specs") or {},
        "range_candidates": [
            {"range_m": c.range_m, "label": c.label,
             "condition": c.condition, "is_default": c.is_default}
            for c in cands],
        "emitters": [e.emitter_type for e in emitters],
        "open_value_conflicts": sheet.get("open_value_conflicts") or 0,
    }


def _normalize_query_items(queries):
    """Accept the shapes models actually emit for search items: a bare
    string IS the query; a nested {"queries": [...]} echo of the wrapper
    key flattens into its entries; q/text/name/designation aliases map
    onto "query". Live trace: {"queries": [{"queries": ["B-2 Spirit"]}]}
    read as an EMPTY filter set and returned the unfiltered first page."""
    out = []
    for item in queries or []:
        if isinstance(item, str):
            out.append({"query": item})
            continue
        item = dict(item or {})
        nested = item.pop("queries", None)
        if isinstance(nested, list):
            out.extend(_normalize_query_items(nested))
            if not item:
                continue
        for alias in ("q", "text", "name", "designation", "nomenclature"):
            if alias in item and not item.get("query"):
                item["query"] = item.pop(alias)
        if item:
            out.append(item)
    return out


def _fuzzy_equipment_stmt(q: str, limit: int):
    """Last-resort recall when the strict conditions return NOTHING: a
    trigram match against the folded identity, so a typo ("abramms") or
    an unspaced mash still lands. Floor keeps noise out; ordered by
    similarity so the closest designation wins."""
    from app.models.reference import WegEquipment
    folded_identity = _folded_identity_expr(WegEquipment)
    fq = _fold_query(q) or str(q).lower()
    score = func.word_similarity(fq, folded_identity)
    return (select(WegEquipment).where(score > 0.3)
            .order_by(score.desc(), WegEquipment.name.asc()).limit(limit))


async def _facet_guidance(db, item: dict) -> Optional[str]:
    """Why a search item found nothing, in fixable terms: each provided
    facet value is checked against the catalog's real values and the
    nearest ones are named — a zero-row echo with no guidance taught
    the agent 'the catalog has no aircraft'."""
    from app.models.reference import WegEquipment
    notes = []
    for key, col in (("category", WegEquipment.category),
                     ("category_group", WegEquipment.category_group),
                     ("class", WegEquipment.equipment_class),
                     ("origin", None), ("operator", None)):
        val = item.get(key)
        if not val:
            continue
        if col is None:
            elem = func.jsonb_array_elements_text(
                WegEquipment.countries if key == "origin"
                else WegEquipment.operators).table_valued("value")
            exact = (await db.execute(
                select(func.count()).select_from(WegEquipment, elem)
                .where(elem.c.value == val))).scalar_one()
            if exact:
                continue
            near = (await db.execute(
                select(elem.c.value).select_from(WegEquipment, elem)
                .where(elem.c.value.ilike(f"%{val}%"))
                .group_by(elem.c.value).limit(5))).scalars().all()
        else:
            exact = (await db.execute(
                select(func.count()).where(col == val))).scalar_one()
            if exact:
                continue
            near = (await db.execute(
                select(col).where(col.ilike(f"%{val}%"))
                .group_by(col).limit(5))).scalars().all()
        notes.append(
            f"'{val}' is not a catalog {key}"
            + (f" — nearest real values: {', '.join(near)}" if near
               else ""))
    if not item.get("query"):
        notes.append("no free-text 'query' was given — put the system/"
                     "designation/topic words there; filters only "
                     "narrow a query")
    return "; ".join(notes) if notes else None


async def tool_search_equipment(queries: List[dict]) -> dict:
    """Batched catalog search: each item {query?, origin?, operator?,
    class?, domain?, category?, year_min?, year_max?, limit?, sheets?}
    -> matching systems. `query` matches name/weg_id/alias; origin and
    operator are canonical country names (two DISTINCT axes: who built
    it vs who fields it). `sheets: true` inlines the FULL sheet on the
    top matches so search + read is ONE call."""
    from app.models.reference import WegEquipment
    out = []
    async with async_session() as db:
        for item in _normalize_query_items(queries):
            stmt = select(WegEquipment).order_by(
                *equipment_ranking(item.get("query"))).limit(
                min(int(item.get("limit") or 12), 40))
            for cond in equipment_conditions(
                    q=item.get("query"), domain=item.get("domain"),
                    equipment_class=item.get("class"),
                    category=item.get("category"),
                    country=item.get("origin"),
                    operator=item.get("operator"),
                    year_min=item.get("year_min"),
                    year_max=item.get("year_max")):
                stmt = stmt.where(cond)
            try:
                rows = (await db.execute(stmt)).scalars().all()
                if not rows and item.get("query"):
                    rows = (await db.execute(
                        _fuzzy_equipment_stmt(item.get("query"),
                                              min(int(item.get("limit") or 12),
                                                  40)))).scalars().all()
                guidance = None
                if not rows:
                    guidance = await _facet_guidance(db, item)
                matches = []
                for i, r in enumerate(rows):
                    if item.get("sheets") and i < _INLINE_SHEETS_CAP:
                        matches.append(await _full_sheet(db, r))
                    else:
                        matches.append(
                            {"weg_id": r.weg_id, "name": r.name,
                             "class": r.equipment_class,
                             "origin": r.countries or [],
                             "introduction_year": r.introduction_year})
                echo = {"item": item, "matches": matches}
                if not matches and guidance:
                    echo["guidance"] = guidance
                out.append(echo)
            except Exception as exc:
                out.append({"item": item, "error": str(exc)})
    return {"results": out}


async def tool_get_equipment_sheets(weg_ids: List[str]) -> dict:
    """Batched full-sheet read: everything the catalog holds on each
    system — classification, origin/operators, introduction year, the
    flat specifications map, range candidates with conditions, emitters,
    and the open value-conflict count (sources that still disagree)."""
    from app.models.reference import WegEquipment
    out = []
    async with async_session() as db:
        for wid in weg_ids:
            row = await db.get(WegEquipment, wid)
            if row is None:
                out.append({"weg_id": wid,
                            "error": "unknown weg_id — resolve_equipment "
                                     "or search_equipment finds ids"})
                continue
            out.append(await _full_sheet(db, row))
    return {"results": out}


def _doctrine_api_base() -> str:
    import os
    base = os.environ.get("DOCTRINE_API_URL", "").rstrip("/")
    if not base:
        raise RuntimeError(
            "doctrine service not configured on this deployment "
            "(set DOCTRINE_API_URL to the consumer API host, e.g. "
            "https://intelapi.pytho.ai)")
    return base


# One-turn retrieval cap: how many distinct pages per search item are
# read in full when the caller asks for pages inline.
_INLINE_PAGES_CAP = 5


async def tool_search_doctrine(queries: List[dict]) -> dict:
    """Batched doctrine retrieval: each item {question, doc_ids?, k?,
    pages?} -> passage hits from the doctrine library (ES-backed on the
    consumer stack). Every hit carries its SOURCE LINK
    ('doctrine:<doc_id>:<page>' — same citation contract as the WEG
    catalog's weg: links). `pages: true` inlines the FULL page text
    (page_text) on the top hits' pages so search + read is ONE call;
    get_doctrine_pages remains for pages beyond the inlined ones."""
    import asyncio
    import httpx
    base = _doctrine_api_base()
    out = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for item in queries:
            # Tolerant shape: a bare string item IS the question.
            if isinstance(item, str):
                item = {"question": item}
            item = item or {}
            try:
                resp = await client.post(f"{base}/api/doctrine/search", json={
                    "question": str(item.get("question") or ""),
                    "selected_doc_ids": item.get("doc_ids") or [],
                    "k": min(int(item.get("k") or 8), 25),
                })
                resp.raise_for_status()
                result = {"item": item, **resp.json()}
                if item.get("pages"):
                    hits = result.get("hits") or []
                    wanted: list = []
                    for h in hits:
                        key = (h.get("doc_id"), h.get("page"))
                        if all(key) and key not in wanted:
                            wanted.append(key)
                        if len(wanted) >= _INLINE_PAGES_CAP:
                            break

                    async def _page(doc_id, page):
                        r = await client.get(
                            f"{base}/api/doctrine/page",
                            params={"doc_id": doc_id, "page": page})
                        r.raise_for_status()
                        return (doc_id, page), r.json().get("text") or ""

                    fetched = await asyncio.gather(
                        *(_page(d, p) for d, p in wanted),
                        return_exceptions=True)
                    texts = {k: v for r in fetched
                             if not isinstance(r, BaseException)
                             for k, v in [r]}
                    for h in hits:
                        text = texts.get((h.get("doc_id"), h.get("page")))
                        if text:
                            h["page_text"] = text
                out.append(result)
            except Exception as exc:
                out.append({"item": item, "error": str(exc)})
    return {"results": out}


async def tool_get_doctrine_pages(pages: List[dict]) -> dict:
    """Batched full-page doctrine reads: each item {doc_id, page} -> the
    page's verbatim indexed text with its source link — the follow-up
    read after a search hit, so citations quote the page, not the
    snippet."""
    import httpx
    base = _doctrine_api_base()
    out = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for item in pages:
            item = item or {}
            try:
                resp = await client.get(f"{base}/api/doctrine/page", params={
                    "doc_id": str(item.get("doc_id") or ""),
                    "page": int(item.get("page") or 0),
                })
                resp.raise_for_status()
                out.append(resp.json())
            except Exception as exc:
                out.append({"item": item, "error": str(exc)})
    return {"results": out}


async def tool_resolve_equipment(nomenclatures: List[str],
                                 include_sheets: bool = False) -> dict:
    from app.models.reference import WegEquipment, WegEquipmentAlias
    from app.services.graph_ingest.ingest import _resolve_nomenclature
    out = []
    async with async_session() as db:
        for raw in nomenclatures:
            weg_id = await _resolve_nomenclature(db, raw)
            if weg_id:
                row = await db.get(WegEquipment, weg_id)
                entry = {"nomenclature": raw, "resolved": True,
                         "weg_id": weg_id,
                         "name": row.name if row else None,
                         "category": row.category if row else None}
                # One-turn retrieval: a resolved system can carry its
                # full sheet so resolve + read is a single call.
                if include_sheets and row is not None:
                    entry["sheet"] = await _full_sheet(db, row)
                out.append(entry)
                continue
            # Near matches come from the RANKED search (folded identity
            # tiers + trigram fallback) — the same relevance the search
            # box uses, so "B-2 Spirit" suggests the B-2 first, never an
            # alphabetically earlier system that shares one token.
            stmt = select(WegEquipment)
            for cond in equipment_conditions(q=raw):
                stmt = stmt.where(cond)
            rows = (await db.execute(
                stmt.order_by(*equipment_ranking(raw)).limit(6)
            )).scalars().all()
            if not rows:
                rows = (await db.execute(
                    _fuzzy_equipment_stmt(raw, 6))).scalars().all()
            out.append({"nomenclature": raw, "resolved": False,
                        "near_matches": [{"weg_id": r.weg_id, "name": r.name}
                                         for r in rows],
                        "note": "no exact catalog match — the nearest "
                                "systems by relevance; use a near_match "
                                "to link or flag a catalog gap"})
    return {"results": out}


async def tool_render_projection(project_id: str, projection: str,
                                 profile_start: Optional[str] = None,
                                 profile_end: Optional[str] = None,
                                 envelope: Optional[str] = None) -> bytes:
    """The non-plan cameras (design 6.9). profile: DEM slice along the
    ray profile_start->profile_end (MGRS), project entities within 5 km
    of the line marked. envelope: altitude-vs-range chart for a catalog
    system (exact name or alias) from its range candidates."""
    from app.services.view.projections import envelope_image, profile_image
    pid = UUID(project_id)
    if projection == "profile":
        if not (profile_start and profile_end):
            raise ValueError("profile needs profile_start and profile_end "
                             "(MGRS)")
        la1, lo1 = mgrs_to_latlng(profile_start)
        la2, lo2 = mgrs_to_latlng(profile_end)
        listing = await tool_list_entities(project_id)
        ents = [{"name": x["name"], "lat": x["lat"], "lon": x["lon"]}
                for x in listing["entities"]
                if x["lat"] is not None]
        return await profile_image((la1, lo1), (la2, lo2), ents)
    if projection == "envelope":
        if not envelope:
            raise ValueError("envelope needs the system name")
        from app.models.reference import (WegEquipment, WegEquipmentAlias,
                                          WegEquipmentRangeCandidate)
        async with async_session() as db:
            weg = None
            alias = await db.get(WegEquipmentAlias, envelope)
            if alias is not None:
                weg = await db.get(WegEquipment, alias.weg_id)
            if weg is None:
                weg = (await db.execute(select(WegEquipment).where(
                    func.lower(WegEquipment.name) == envelope.lower())
                )).scalars().first()
            if weg is None:
                raise ValueError(f"no catalog system named '{envelope}'")
            cands = (await db.execute(
                select(WegEquipmentRangeCandidate).where(
                    WegEquipmentRangeCandidate.weg_id == weg.weg_id)
            )).scalars().all()
        rows = [{"label": c.label, "range_m": c.range_m,
                 "min_altitude_m": getattr(c, "min_altitude_m", None),
                 "max_altitude_m": getattr(c, "max_altitude_m", None),
                 "trajectory": getattr(c, "trajectory", None),
                 "condition": c.condition, "is_default": c.is_default}
                for c in cands]
        if not rows and weg.engagement_range_m:
            rows = [{"label": "engagement range",
                     "range_m": weg.engagement_range_m,
                     "min_altitude_m": None, "max_altitude_m": None,
                     "trajectory": None, "condition": None,
                     "is_default": True}]
        if not rows:
            raise ValueError(f"'{weg.name}' has no stated ranges to chart")
        from app.services.view.map_state import _max_elevation_deg
        return envelope_image(weg.name, rows,
                              max_elevation_deg=_max_elevation_deg(weg))
    raise ValueError(f"unknown projection '{projection}' — "
                     "plan|profile|envelope (vantage/oblique/sequence "
                     "are registered vocabulary, cameras land with their "
                     "consumers)")


async def tool_render_map(project_id: str,
                          west: Optional[float] = None,
                          south: Optional[float] = None,
                          east: Optional[float] = None,
                          north: Optional[float] = None) -> bytes:
    from app.services.render.headless import render_map_to_png, RenderOptions
    pid = UUID(project_id)
    bbox = None
    if None not in (west, south, east, north):
        bbox = [west, south, east, north]
    else:
        async with async_session() as db:
            b = await _graph_bbox(db, pid, pad=0.6)
        bbox = list(b) if b else None
    return await render_map_to_png(pid, RenderOptions(
        width=1600, height=900, bbox=bbox))



# ── WRITE SECTION REMOVED (S17 cutover, 2026-07-28) ─────────────────
# The pre-record writers (upsert_units, add_positions, set_shapes,
# add_holdings, add_edges, remove_edges, remove_holdings,
# delete_entities, place_subordinates, submit_oob, add_clauses and
# their private helpers) lived here. Every record write now goes
# through the world surface's general verbs (app/api/v1/
# world_repair.py: assert / update / retract / purge), where it lands
# as a committed assertion chained to captured L0. Reads and the
# helpers they share remain.


async def reference_lists() -> str:
    """The choice lists a driver ALWAYS needs — built into the MCP
    server INSTRUCTIONS at startup, never a tool call."""
    from app.models.graph import AFFILIATIONS, ECHELONS
    from app.models.reference import EntityType, RelationshipType, WegEquipment
    factions = (("US/NATO force templates", lambda k: k.startswith("us_")),
                ("China force templates", lambda k: k.startswith("chn_")),
                ("Russia/OPFOR force templates",
                 lambda k: not k.startswith(("us_", "chn_"))))
    async with async_session() as db:
        etypes = (await db.execute(select(EntityType.type_key)
                                   .order_by(EntityType.type_key))).scalars().all()
        rels = (await db.execute(select(RelationshipType.type_key)
                                 .order_by(RelationshipType.type_key))).scalars().all()
        tpls = (await db.execute(select(ForceTemplate)
                                 .order_by(ForceTemplate.name))).scalars().all()
        equip = (await db.execute(select(WegEquipment.name)
                                  .order_by(WegEquipment.name))).scalars().all()
    blocks = [
        "affiliations: " + ", ".join(AFFILIATIONS),
        "echelons: " + ", ".join(ECHELONS)
        + " (Squadron=Battalion-equivalent, Troop/Battery=Company-equivalent)",
        "entity_types: " + ", ".join(etypes),
        "relationship_types: " + ", ".join(rels),
    ]
    for label, match in factions:
        names = [t.name for t in tpls if match(t.key)]
        if names:
            blocks.append(label + ":\n" + "\n".join(names))
    blocks.append("equipment catalog (write holdings with one of these "
                  "exact names; unknown strings are kept as raw text, "
                  "never fuzzy-matched):\n" + "\n".join(equip))
    return "\n\n".join(blocks)


async def tool_get_entity_brief(project_id: str, names: List[dict] = None,
                                as_of: str = None) -> dict:
    """Batched entity briefs — the agent's recall read. Each item:
    {name}. Returns per-entity: attribute History chains (current +
    superseded, with speaker/source/dates), Reporting statements with
    provenance, Doctrine for the unit's template, position at the
    scrub time, and deduplicated per-kind counts."""
    from datetime import datetime as _dt
    from app.services.entity_brief import build_brief
    pid = UUID(project_id)
    t = None
    if as_of:
        try:
            t = _dt.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError:
            return {"error": f"unparseable as_of: {as_of!r}"}
    out = []
    async with async_session() as db:
        for item in (names or []):
            name = (item or {}).get("name") if isinstance(item, dict) \
                else str(item)
            if not name:
                out.append({"error": "item missing name"})
                continue
            try:
                node = await _find_node(db, pid, name)
            except Exception as e:
                out.append({"name": name, "error": str(e)})
                continue
            brief = await build_brief(db, node, as_of=t)
            brief["name"] = node.name
            out.append(brief)
    return {"briefs": out}



async def _resolve_about(db, pid, about_items):
    """ABOUT accepts entity ids AND names (user ruling 2026-07-22):
    UUIDs pass through (verified in-project), names resolve via
    external_id then fold-name matching, unresolved text is kept RAW
    so no statement is lost (F8)."""
    rows = (await db.execute(
        select(GraphNode.id, GraphNode.name, GraphNode.external_id)
        .where(GraphNode.project_id == pid, GraphNode.layer == "project"))).all()
    by_id = {str(r[0]) for r in rows}
    by_ext = {r[2]: str(r[0]) for r in rows if r[2]}
    by_name = {}
    for r in rows:
        if r[1]:
            by_name.setdefault(_fold(r[1]), str(r[0]))
    resolved, unresolved = [], []
    for a in (about_items or []):
        a = str(a).strip()
        if not a:
            continue
        if a in by_id:
            resolved.append(a)
        elif a in by_ext:
            resolved.append(by_ext[a])
        elif _fold(a) in by_name:
            resolved.append(by_name[_fold(a)])
        else:
            resolved.append(a)
            unresolved.append(a)
    return resolved, unresolved


