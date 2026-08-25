from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from typing import List, Optional, Dict, Any
from types import SimpleNamespace
from uuid import UUID
from datetime import datetime, timezone

import json

from app.constants.overlays import resolve_render_attrs
from app.models.graph import (
    ECHELONS, GRAPHIC_TYPES, GraphHolding, GraphNode, GraphNodePosition,
)
from app.models.map import Map
from app.models.reference import (
    EntityType, WegEquipment, WegEquipmentEmitter, WegEquipmentRangeCandidate,
)
from app.models.world import Assertion
from app.services.knowledge.spatial_query import get_entities, get_overlays
from app.services.knowledge.route_query import get_routes
from app.utils.graph_symbols import compose_node_sidc
from app.utils.mgrs_utils import latlng_to_mgrs

import re as _re

# Max gun elevation per system, parsed from the verbatim sheet capture
# (weapon blocks state e.g. "Elevation: -5 to +87 deg"). The AAA/gun
# envelope ceiling is DERIVED from it — h <= x*tan(theta_max) — not a
# stated altitude. Memoized per weg_id; None = no elevation stated.
_MAX_ELEV_CACHE: Dict[str, Optional[float]] = {}
_ELEV_NUM = _re.compile(r"[+-]?\d+(?:\.\d+)?")


def _max_elevation_deg(cat) -> Optional[float]:
    if cat is None or not getattr(cat, "sheet_data", None):
        return None
    hit = _MAX_ELEV_CACHE.get(cat.weg_id, "MISS")
    if hit != "MISS":
        return hit
    best = None

    def walk(obj):
        nonlocal best
        if isinstance(obj, dict):
            for k, v in obj.items():
                klow = str(k).lower()
                if ("elevation" in klow and "rate" not in klow
                        and "depression" not in klow
                        and isinstance(v, str)):
                    for m in _ELEV_NUM.findall(v):
                        try:
                            deg = float(m)
                        except ValueError:
                            continue
                        if 5.0 < deg <= 90.0 and (best is None or deg > best):
                            best = deg
                else:
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(cat.sheet_data)
    _MAX_ELEV_CACHE[cat.weg_id] = best
    return best


# Derived-centroid land-nudge memo — keyed by ~100m-rounded centroid;
# values (lon, lat, moved_km_or_None). Bounded; cleared wholesale when
# full (recomputing a page of centroids is cheap next request).
_LAND_NUDGE_CACHE: Dict[tuple, tuple] = {}


async def resolve_postures(
    db: AsyncSession, project_id: UUID, node_ids: List[UUID],
    as_of: datetime,
) -> Dict[str, Optional[str]]:
    """As-of posture per node from the RECORD (posture-timeline design
    2.2): committed, non-superseded, non-retracted property/state
    assertions with attribute='posture' on the project layer. A node
    WITH posture assertions resolves to the one with the greatest
    valid_from at or before as_of whose valid window covers it —
    explicitly None before its first (the record states no posture
    yet). A node with NO posture assertions is ABSENT from the result
    and its mirror column stands: the same timeless contract undated
    positions get (a static-laydown value must not vanish mid-scrub).
    Keys are str(node_id), matching the paint loop's handles."""
    if not node_ids:
        return {}
    if as_of.tzinfo is None:
        # An offsetless scrub instant means UTC — the same semantic the
        # position path's SQL bind applies against timestamptz rows;
        # this comparison runs in Python and must match it.
        as_of = as_of.replace(tzinfo=timezone.utc)
    rows = (await db.execute(
        select(Assertion.subject_node_id, Assertion.value_text,
               Assertion.valid_from, Assertion.valid_to)
        .where(Assertion.project_id == project_id,
               Assertion.subject_node_id.in_(node_ids),
               Assertion.kind.in_(("property", "state")),
               Assertion.attribute == "posture",
               Assertion.record_state == "committed",
               Assertion.layer == "project",
               Assertion.superseded_by.is_(None),
               Assertion.retracted_by.is_(None))
        .order_by(Assertion.subject_node_id,
                  Assertion.valid_from))).all()
    resolved: Dict[str, Optional[str]] = {}
    for node_id, value, vfrom, vto in rows:
        key = str(node_id)
        resolved.setdefault(key, None)
        if vfrom is not None and vfrom <= as_of \
                and (vto is None or vto > as_of):
            # Ascending valid_from order — the last qualifying row is
            # the greatest valid_from at or before the scrub instant.
            resolved[key] = value
    return resolved


async def _graph_features(
    db: AsyncSession, map_id: UUID, as_of: Optional[datetime] = None,
    include_draft_of: Optional[UUID] = None,
) -> List[dict]:
    """Paint features from the entity graph — the record is the unit
    source for this map (design §8). SIDC composed here, at paint
    time, never stored (decision 11). Range/detection rings emit per
    weg_id REFERENCE (aggregate holdings and instances alike, CURATED
    catalog rows only — §4).

    as_of: timeline scrub. Positions are append-only observations
    (graph_node_positions); with as_of set, each node paints at its
    latest observation at or before that time (observed_at — NEVER
    null; the record's one temporal dimension) and nodes with no
    qualifying observation do not paint — they had not been observed
    yet. Without as_of, the mirrored newest-wins node.geom paints.
    """
    # Full geometry (POINT units + LINESTRING/POLYGON control measures)
    # — the record stores every shape; ST_X/ST_Y would fail on lines.
    # ALL nodes, placed or not: an unplaced formation still paints when
    # its subordinates are placed (centroid derivation below).
    # The project layer paints for everyone; ONE record's draft rows
    # join ONLY for that record's own figure (include_draft_of — fifth
    # edition #2.2: a draft layer's only consumer is its own record's
    # artifact rendering).
    layer_filter = GraphNode.layer == "project"
    if include_draft_of is not None:
        from sqlalchemy import and_, or_
        layer_filter = or_(
            layer_filter,
            and_(GraphNode.layer == "draft",
                 GraphNode.origin_record_id == include_draft_of))
    raw = (await db.execute(
        select(GraphNode, func.ST_AsGeoJSON(GraphNode.geom))
        .where(GraphNode.project_id == map_id, layer_filter))).all()
    ring_overlays: List[dict] = []
    if not raw:
        return [], ring_overlays
    # Normalize to (node, geojson_or_None) pairs — the one shape both
    # the live path and the scrub path feed into the paint loop.
    pairs: List[tuple] = [(r.GraphNode, r[1]) for r in raw]

    etypes = {t.type_key: t for t in
              (await db.execute(select(EntityType))).scalars().all()}

    # The governing observation per node — geometry under scrub, and
    # position PROVENANCE always (which document/derivation produced
    # the location the analyst is looking at; surfaced on the unit
    # placard). One query, newest-first; first row per node wins.
    pos_query = (
        select(GraphNodePosition.node_id,
               func.ST_AsGeoJSON(GraphNodePosition.geom),
               GraphNodePosition.source,
               GraphNodePosition.dtg_label,
               GraphNodePosition.observed_at,
               GraphNodePosition.altitude_m,
               GraphNodePosition.id)
        .where(GraphNodePosition.node_id.in_([n.id for n, _ in pairs]),
               GraphNodePosition.geom.isnot(None))
        .order_by(GraphNodePosition.node_id,
                  GraphNodePosition.observed_at.desc()))
    if as_of is not None:
        # The scrub timeline is built from DATED observations only — an
        # undated row is a current-laydown statement, not a time fix.
        # observed_at is THE temporal dimension (2026-07-21 ruling):
        # the record only ever holds reports, so the scrub replays
        # where the record's observations place things. created_at is
        # ingest bookkeeping and is never replayed or surfaced.
        pos_query = pos_query.where(
            GraphNodePosition.observed_at <= as_of)
    obs_by_node: Dict[str, dict] = {}
    for node_id, gj, src, dtg, observed, alt, row_id in (
            await db.execute(pos_query)).all():
        obs_by_node.setdefault(str(node_id), {
            "geom": gj, "source": src, "dtg": dtg,
            "observed_at": observed.isoformat() if observed else None,
            "altitude_m": alt, "row_id": row_id,
        })
    # Provenance is the CHAIN, rendered at read (2026-07-28 ruling):
    # each governing row's backing assertion -> basis clause -> section
    # -> source revision composes the analyst-visible Source line. The
    # stored row string is only the fallback for unbacked rows (analyst
    # drags, disposition-engine writes) whose labels are code-composed.
    from app.services.view.provenance import provenance_for_rows
    _chain_prov = await provenance_for_rows(
        db, [o.get("row_id") for o in obs_by_node.values()])
    for o in obs_by_node.values():
        chain = _chain_prov.get(str(o.get("row_id")))
        if chain:
            o["source"] = chain
    if as_of is not None:
        # Scrub semantics (user ruling 2026-07-17): only movable FORCES
        # time-resolve. Control measures and fixed infrastructure are
        # TIMELESS — an objective or a fuel depot exists across the
        # scrub domain (its dated observations are events AT it, not
        # its birth) and must not pop into existence mid-scrub. Units
        # with a dated history re-resolve (absent before their first
        # dated fix); units with NO dated history are static laydown —
        # also timeless.
        dated_nodes = {(str(r[0])) for r in (await db.execute(
            select(GraphNodePosition.node_id)
            .where(GraphNodePosition.node_id.in_(
                       [n.id for n, _ in pairs
                        if n.entity_type not in GRAPHIC_TYPES]),
                   GraphNodePosition.observed_at.isnot(None))
            .distinct())).all()}
        scrubbed = []
        for n, gj in pairs:
            timeless = (
                n.entity_type in GRAPHIC_TYPES
                or (etypes.get(n.entity_type) is not None
                    and getattr(etypes[n.entity_type], "is_fixed", False))
                or str(n.id) not in dated_nodes)
            if timeless:
                scrubbed.append((n, gj))
            else:
                scrubbed.append(
                    (n, (obs_by_node.get(str(n.id)) or {}).get("geom")))
        pairs = scrubbed
    node_ids = [n.id for n, _ in pairs]
    # As-of posture (posture-timeline design 2.2): with a scrub time
    # set, each node's posture resolves from its assertion track — the
    # mirror column is newest-wins and would freeze every formation at
    # its latest posture across the whole scrub (positions time-travel,
    # postures did not). Empty without as_of: the live path keeps the
    # mirrored column at zero cost.
    posture_asof: Dict[str, Optional[str]] = {}
    if as_of is not None:
        posture_asof = await resolve_postures(db, map_id, node_ids, as_of)
    # OUTER join on purpose: a holding whose nomenclature never resolved
    # to a WEG id is still recorded equipment — it lists by its raw name
    # (and draws no ring). The inner join silently deleted every
    # unresolved system from the analyst's view.
    holdings = (await db.execute(
        select(GraphHolding, WegEquipment)
        .outerjoin(WegEquipment, WegEquipment.weg_id == GraphHolding.weg_id)
        .where(GraphHolding.node_id.in_(node_ids)))).all()
    # Per-feature display fields (extensible NodeField rows):
    # `smoothing` — the analyst's segments-vs-bezier choice for a line/
    # area control measure, set from the edit panel; `posture_override`
    # — the placard selector's WORKING-LAYER visual override (2026-07-28
    # ruling): it shapes the paint but never touches the record or the
    # mirror column, and clears back to the record view.
    from app.models.graph import NodeField
    smoothing_by_node: Dict[str, str] = {}
    posture_override_by_node: Dict[str, str] = {}
    for r in (await db.execute(
            select(NodeField).where(
                NodeField.node_id.in_(node_ids),
                NodeField.field_key.in_(
                    ("smoothing", "posture_override"))))).scalars().all():
        if r.field_key == "smoothing":
            smoothing_by_node[str(r.node_id)] = r.value
        elif r.value:
            posture_override_by_node[str(r.node_id)] = r.value
    inst_weg = {n.weg_id for n, _ in pairs if n.weg_id}
    catalogs = {c.weg_id: c for c in (await db.execute(
        select(WegEquipment).where(WegEquipment.weg_id.in_(inst_weg))
    )).scalars().all()} if inst_weg else {}
    emitter_weg = {e.weg_id for e in (await db.execute(
        select(WegEquipmentEmitter))).scalars().all()}

    # Range-condition resolution (decision 24 — the weather hook):
    # the map carries attrs.range_condition (mutually exclusive
    # employment toggle: night/day/extended/...). A condition-matched
    # candidate overrides the system's default range at paint time;
    # otherwise engagement_range_m (the default, or the analyst's
    # pick) draws.
    map_row = await db.get(Map, map_id)
    map_attrs = (map_row.attrs or {}) if map_row is not None else {}
    range_condition = map_attrs.get("range_condition")
    # PROJECT config layered on the immutable seed: an analyst's per-map
    # engagement-range pick lives in the MAP record (attrs), never in the
    # reference catalog. It overrides the seed default at paint time. The
    # catalog (weg_equipment.engagement_range_m) stays the authoritative
    # reference default and is rebuilt wholesale from seed.
    range_overrides = map_attrs.get("equipment_range_overrides") or {}
    # Envelope ceilings for the 3D volume paint: the DEFAULT range
    # candidate's stated max altitude per system (the 2D ring is the
    # ground slice; the volume needs the cap).
    ceilings: Dict[str, int] = {}
    # Method of propulsion per system (default candidate's trajectory:
    # direct / ballistic / cruise / loiter) — the envelope's vertical
    # FORM follows it: gun wedge, missile barrel, parabola of safety,
    # deck-hugging cruise. Emitted on the band for the volume paint.
    trajectories: Dict[str, str] = {}
    cond_ranges: Dict[str, int] = {}
    if range_condition:
        all_weg = {h.weg_id for h, _ in holdings if h.weg_id} | inst_weg
        if all_weg:
            for c in (await db.execute(
                    select(WegEquipmentRangeCandidate).where(
                        WegEquipmentRangeCandidate.weg_id.in_(all_weg),
                        WegEquipmentRangeCandidate.condition == range_condition,
                    ))).scalars().all():
                prev = cond_ranges.get(c.weg_id)
                if prev is None or c.range_m > prev:
                    cond_ranges[c.weg_id] = c.range_m

    all_ring_weg = {h.weg_id for h, _ in holdings if h.weg_id} | inst_weg
    if all_ring_weg:
        # Prefer the default candidate's ceiling/trajectory; fill
        # blanks from any candidate that states one (many sheets flag
        # no default row).
        rows = (await db.execute(
            select(WegEquipmentRangeCandidate).where(
                WegEquipmentRangeCandidate.weg_id.in_(all_ring_weg),
            ))).scalars().all()
        for c in sorted(rows, key=lambda c: not c.is_default):
            cap = getattr(c, "max_altitude_m", None)
            if cap and c.weg_id not in ceilings:
                ceilings[c.weg_id] = cap
            traj = getattr(c, "trajectory", None)
            if traj and c.weg_id not in trajectories:
                trajectories[c.weg_id] = traj

    by_node: Dict[str, list] = {}
    for h, cat in holdings:
        by_node.setdefault(str(h.node_id), []).append((h, cat))
    # Recorded organic children — needed both by the centroid derivation
    # below and by the reference walk (doctrine never doubles an extracted
    # ORBAT).
    recorded_children: Dict[str, list] = {}
    for n, _gj in pairs:
        if n.organic_parent_id:
            recorded_children.setdefault(
                str(n.organic_parent_id), []).append(n)

    # ── REFERENCE WALK. A project unit carrying a template_key has a
    # doctrinal subtree and authorized equipment table in the reference
    # scope. Those defaults are reference knowledge, not project facts
    # (they have no source basis), so they are DERIVED AT PAINT TIME and
    # never written to the project — the same rule the composed SIDC and
    # the parent centroid follow. Derived holdings key onto the real node
    # (so rollup/fans/detection rings need no special case); derived
    # subordinates paint as virtual features with the anticipated frame.
    from app.services.view.template_walk import derive_reference_walk
    derived_holdings, derived_units = await derive_reference_walk(
        db, pairs, by_node, recorded_children)
    for nid, dh in derived_holdings.items():
        by_node.setdefault(nid, []).extend(dh)
    # Derived subordinates join the rollup graph so a formation's placard
    # shows its SUBTREE's fleet (a tank regiment's T-72s live on its
    # doctrinal battalions, not on the regiment row).
    derived_children: Dict[str, list] = {}
    for du in derived_units:
        derived_children.setdefault(du["parent_ref"], []).append(
            du["virtual_id"])
        if du.get("holdings"):
            by_node[du["virtual_id"]] = du["holdings"]

    # ── Centroid derivation. A formation with no position of its own
    # paints at the centroid of its PLACED subordinate units — the
    # parent's location IS an aggregate of where its subordinates are
    # (and it is what the echelon roll-up sliders cluster into).
    # View-time only: the record never stores derived geometry, and a
    # later real observation simply out-resolves the derivation.
    placed_pts: Dict[str, tuple] = {}
    children: Dict[str, list] = recorded_children
    for n, gj in pairs:
        if gj and n.entity_type not in GRAPHIC_TYPES:
            try:
                g = json.loads(gj)
            except (TypeError, ValueError):
                continue
            if g.get("type") == "Point":
                placed_pts[str(n.id)] = tuple(g["coordinates"][:2])

    def _descendant_centroid(root_id: str):
        pts, seen = [], {root_id}
        stack = list(children.get(root_id, []))
        while stack:
            c = stack.pop()
            cid = str(c.id)
            if cid in seen:
                continue
            seen.add(cid)
            p = placed_pts.get(cid)
            if p is not None:
                pts.append(p)
            stack.extend(children.get(cid, []))
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts), len(pts))

    # Pre-derive all missing-unit centroids, then land-check them in ONE
    # batch — the aggregate position of a land formation must not fall
    # in the lake between its subordinates. Memoized module-level (~100m
    # key): map/state is hot-path and landcover rides a remote raster.
    derived: Dict[str, tuple] = {}
    _to_check, _owners = [], []
    for n, gj in pairs:
        # Centroid derivation applies to FORMATIONS ON THE ECHELON
        # LADDER only (user ruling 2026-07-17): an alliance/political
        # command with no echelon has no meaningful aggregate position
        # and plays no part in the echelon roll-up — it stays off the
        # map (the ORBAT/link view carries it).
        if (gj is None and n.entity_type not in GRAPHIC_TYPES
                and (n.echelon or "") in ECHELONS):
            c = _descendant_centroid(str(n.id))
            if c is None:
                continue
            key = (round(c[0], 3), round(c[1], 3))
            hit = _LAND_NUDGE_CACHE.get(key)
            if hit is not None:
                derived[str(n.id)] = (hit[0], hit[1], c[2], hit[2])
            else:
                _to_check.append((c[0], c[1]))
                _owners.append((str(n.id), key, c[2]))
    if _to_check:
        try:
            from app.services.graph_ingest.disposition import ensure_on_land
            checked = await ensure_on_land(_to_check)
        except Exception:
            # Landcover outage — fail open: paint raw centroids rather
            # than hide formations over a data dependency.
            checked = [(lon, lat, None) for lon, lat in _to_check]
        for (owner, key, cnt), (lon, lat, moved) in zip(_owners, checked):
            if len(_LAND_NUDGE_CACHE) > 4096:
                _LAND_NUDGE_CACHE.clear()
            _LAND_NUDGE_CACHE[key] = (lon, lat, moved)
            derived[owner] = (lon, lat, cnt, moved)

    features = []
    for n, geojson_str in pairs:
        nid = str(n.id)
        derived_from = None
        if geojson_str is None:
            # Unplaced unit: derive from subordinates or stay unpainted.
            # Graphics can't derive — a phase line has no subordinates.
            d = derived.get(nid)
            if d is None:
                continue
            geometry = {"type": "Point", "coordinates": [d[0], d[1]]}
            derived_from = d[2]
            derived_moved = d[3]
        else:
            try:
                geometry = json.loads(geojson_str)
            except (TypeError, ValueError):
                continue
        # Tactical graphics (control measures) and any non-point shape:
        # kind == entity_type, geometry passthrough — the frontend
        # tacticalLayers renderers paint these; no SIDC, no rings.
        if n.entity_type in GRAPHIC_TYPES or geometry.get("type") != "Point":
            # Stamp the renderer dispatch contract (primitive + modifiers)
            # from the overlay catalog so the frontend paints by
            # f.properties.primitive — the same contract legacy overlay
            # rows carry. Without it a NEW control-measure kind (a route/
            # MSR) reaches the frontend with no primitive and never
            # paints, even though its catalog entry defines one.
            # Geometry type rides along: the catalog resolves the
            # geometry-class form (a Point objective stamps the kidney
            # primitive, not the polygon drawer).
            render_attrs = resolve_render_attrs(
                n.entity_type, geometry.get("type"))
            features.append({
                "type": "Feature", "id": nid,
                "geometry": geometry,
                "properties": {
                    "id": nid, "kind": n.entity_type,
                    "source": "entity_graph", "name": n.name,
                    "label": n.name,
                    "affiliation": n.affiliation,
                    "primitive": render_attrs.get("primitive"),
                    "modifiers": render_attrs.get("modifiers", {}),
                    # The tactical renderers key hostile/friendly styling
                    # on the legacy lowercase `side` attr (e.g. hostile
                    # engagement areas draw red-dashed).
                    "side": ("hostile" if n.affiliation == "Hostile"
                             else "friendly" if n.affiliation == "Friend"
                             else (n.affiliation or "").lower() or None),
                    "entity_type": n.entity_type,
                    # Boundary garnish: the echelon of the units the
                    # line separates (FM 1-02.2 amplifier marks).
                    "echelon": n.echelon,
                    # Typed sub-type discriminator — the catalog's
                    # subkind_from_property paint dispatch (obstacle
                    # glyphs) reads feature properties, so the column
                    # rides the wire here.
                    "subkind": n.subkind,
                    # Analyst display choice (edit panel): segments
                    # (default) vs bezier-smoothed line/area paint.
                    "smoothing": smoothing_by_node.get(nid),
                    "significance": n.significance,
                    "notes": n.notes,
                    # Position provenance — control measures get the
                    # same analyst-visible sourcing a unit placard
                    # shows (which document put this line HERE).
                    "position_source":
                        (obs_by_node.get(nid) or {}).get("source"),
                    "position_dtg": (obs_by_node.get(nid) or {}).get("dtg"),
                    "position_observed_at":
                        (obs_by_node.get(nid) or {}).get("observed_at"),
                },
            })
            continue
        lon, lat = geometry["coordinates"][0], geometry["coordinates"][1]
        nh = by_node.get(nid, [])
        dominant = None
        resolved_nh = [hc for hc in nh if hc[1] is not None]
        if resolved_nh:
            dominant = max(
                resolved_nh,
                key=lambda hc: (hc[0].count_current or hc[0].count_authorized or 0)
            )[1].equipment_class
        # A TEMPLATED position — arrayed by the doctrinal disposition
        # or derived from subordinates — draws the doctrinal DASHED
        # frame (anticipated status); a stated position draws solid.
        anticipated = bool(derived_from) or str(
            (obs_by_node.get(nid) or {}).get("source") or ""
        ).startswith("doctrinal disposition")
        sidc = compose_node_sidc(
            n, etypes.get(n.entity_type), dominant, catalogs.get(n.weg_id),
            anticipated=anticipated)
        # Equipment rollup = the node's OWN holdings plus every organic
        # descendant's (a formation's equipment IS its subtree's — a
        # division placard with instantiated regiments shows the
        # division's fleet, not "None recorded"). Rings below stay on
        # OWN holdings only: a ring paints at its bearer's position.
        rollup: Dict[str, int] = {}
        stack = [nid]
        seen_rollup = {nid}
        while stack:
            cur = stack.pop()
            for h, cat in by_node.get(cur, []):
                key = (cat.name if cat
                       else (h.nomenclature_raw or h.weg_id
                             or "unresolved equipment"))
                rollup[key] = (rollup.get(key, 0)
                               + (h.count_current or h.count_authorized or 0))
            for c in children.get(cur, []):
                cid = str(c.id)
                if cid not in seen_rollup:
                    seen_rollup.add(cid)
                    stack.append(cid)
            for vid in derived_children.get(cur, []):
                if vid not in seen_rollup:
                    seen_rollup.add(vid)
                    stack.append(vid)
        features.append({
            "type": "Feature", "id": nid,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": nid, "kind": "mil_unit", "source": "entity_graph",
                "name": n.name, "sidc": sidc, "echelon": n.echelon,
                "affiliation": n.affiliation, "entity_type": n.entity_type,
                "significance": n.significance,
                "combat_effectiveness": n.combat_effectiveness,
                "posture": posture_asof.get(nid, n.posture),
                # The working-layer visual override, when set — display
                # state beside the record value, never in place of it.
                **({"posture_override": posture_override_by_node[nid]}
                   if nid in posture_override_by_node else {}),
                # The unit's equipment — own holdings + organic
                # descendants' (the placard's Linked Equipment section
                # reads this; a formation shows its subtree's fleet).
                "composition_rollup": rollup or None,
                "unit_type": n.unit_type,
                # The organic parent uuid (matches another feature's id):
                # the echelon roll-up sliders walk props.parent up the OOB
                # hierarchy to absorb sub-tier units into their nearest
                # placed ancestor. Without this the roll-up finds no
                # ancestor and the sliders are inert.
                "parent": str(n.organic_parent_id) if n.organic_parent_id else None,
                "location_mgrs": latlng_to_mgrs(lat, lon),
                # Position provenance — where THIS location came from,
                # analyst-visible on the unit placard: the governing
                # observation's source (parsed document, doctrinal
                # disposition, analyst drag...) or the derivation basis.
                **({"position_derived": True,
                    "position_basis":
                        f"centroid of {derived_from} placed subordinates"
                        + (", nudged to nearest land"
                           if derived_moved and derived_moved > 0 else "")
                        + (" — NO LAND IN REACH, verify subordinates"
                           if derived_moved == -1.0 else "")}
                   if derived_from else {
                    "position_source":
                        (obs_by_node.get(nid) or {}).get("source"),
                    "position_dtg": (obs_by_node.get(nid) or {}).get("dtg"),
                    "position_observed_at":
                        (obs_by_node.get(nid) or {}).get("observed_at"),
                   }),
            },
        })
        # Rings ride the EXISTING radial overlay primitive: one
        # range_fan overlay per bearer (engagement bands, one per
        # curated weg_id reference) and one detection_ring overlay
        # (emitter-carrying references). Renderer renders — bands are
        # data, the primitive comes from the overlays catalog.
        refs = [(h.weg_id, cat) for h, cat in nh] + (
            [(n.weg_id, catalogs.get(n.weg_id))] if n.weg_id else [])
        fan_bands, det_bands = [], []
        for weg_id, cat in refs:
            if cat is None:
                continue
            # Paint gates on VALUE PRESENCE (decisions 23/24). Effective
            # range resolves in layers, project config over reference:
            # the analyst's per-map override wins, else an active
            # range_condition candidate, else the seed default. Labeled
            # so the analyst sees WHICH range shows.
            override = range_overrides.get(weg_id)
            radius = override or cond_ranges.get(weg_id) or cat.engagement_range_m
            if radius:
                label = cat.name
                if not override and cond_ranges.get(weg_id):
                    label = f"{cat.name} ({range_condition})"
                fan_bands.append({"radius_m": radius, "label": label,
                                  "ceiling_m": ceilings.get(weg_id),
                                  "max_elevation_deg": _max_elevation_deg(cat),
                                  "trajectory": trajectories.get(weg_id),
                                  "_category": cat.category,
                                  "_class": cat.equipment_class,
                                  "_trajectory": trajectories.get(weg_id)})
            if weg_id in emitter_weg and cat.detection_range_m:
                # Detection is line-of-sight physics by definition.
                det_bands.append({"radius_m": cat.detection_range_m,
                                  "label": cat.name,
                                  "ceiling_m": ceilings.get(weg_id),
                                  "_category": "cema", "_class": None,
                                  "_trajectory": None})
        for kind, bands in (("range_fan", fan_bands),
                            ("detection_ring", det_bands)):
            if not bands:
                continue
            # §6.7: LOS-physics envelopes are viewsheds, but the
            # derivation NEVER runs on this hot path — bands are only
            # TAGGED here; the client fetches the persisted coverage
            # from /terrain/coverage for the SELECTED unit's bands
            # (rings are selection chrome, so that is at most a few
            # bands, not the whole laydown).
            from app.services.view.coverage import needs_los
            for b in bands:
                cat = b.pop("_category", None)
                traj = b.pop("_trajectory", None)
                cls = b.pop("_class", None)
                if needs_los(cat, traj, cls):
                    b["los"] = True
                    # Reference target height for the LOS evaluation:
                    # air-defense engagement and every detection ring
                    # look for a low-altitude AIR target (100 m
                    # reference ingress); ground direct-fire bands
                    # look for a vehicle-height target. Evaluating an
                    # air envelope against a ground-hugging target
                    # collapses every long boundary into ray whipsaw.
                    air = (cls or "").lower() in ("ada", "sam", "air_defense")                         or kind == "detection_ring"                         or (cat or "").lower() in ("cema",
                                                   "air_defense_artillery")
                    b["los_target_m"] = 100 if air else 2
            render_attrs = resolve_render_attrs(kind, "Point")
            ring_overlays.append({
                "type": "Feature", "id": f"{nid}:{kind}",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "kind": kind, "source": "entity_graph",
                    "bearer_id": nid, "name": n.name,
                    # The click-to-show-fans override joins the selected
                    # unit to its rings on THIS key (featureVisible) —
                    # without it a selected graph unit's rings never
                    # pass the default range_fan kind-hide.
                    "bearer_unit_kg_id": nid,
                    # The bearer's stated altitude from its governing
                    # position observation (model z). The volume mesh
                    # anchors here; absent -> DEM ground client-side.
                    "bearer_altitude_m":
                        (obs_by_node.get(nid) or {}).get("altitude_m"),
                    "affiliation": n.affiliation,
                    "bands": sorted(bands, key=lambda b: b["radius_m"]),
                    "primitive": render_attrs.get("primitive"),
                    "modifiers": render_attrs.get("modifiers", {}),
                },
            })

    # ── Derived subordinates (reference walk). A templated subordinate has
    # no position of its own and no record behind it: it paints as THE
    # SAME DOCTRINAL DISPOSITION the instantiate-time engine would array
    # (plan_disposition — posture-shaped, role-placed, threat-facing,
    # frontage/depth norms), with the ANTICIPATED (dashed) frame, carrying
    # its doctrinal equipment for the placard rollup. It is view-only —
    # `derived_from_template` marks it so the analyst never mistakes
    # doctrine for a recorded fact, and nothing here is ever persisted.
    # The layout is DETERMINISTIC (pure function of parent anchor +
    # posture + brood + facing), so every consumer computes the same
    # picture; stacking all subordinates on the parent point buried them
    # 16 deep under each other, and the line-abreast interim ignored
    # posture and role entirely.
    if derived_units:
        from app.services.graph_ingest.disposition import (
            plan_disposition, proximity_bearing)
        painted_at = {f["id"]: f["geometry"]["coordinates"][:2]
                      for f in features
                      if f.get("geometry", {}).get("type") == "Point"}
        node_by_id = {str(n.id): n for n, _ in pairs}
        # Facing: proximity-weighted toward the opposing force's placed
        # points — the same bearing the disposition engine uses (a flat
        # centroid let far-away home-station forces drag the axis).
        _side_pts: Dict[str, list] = {"Friend": [], "Hostile": []}
        for n, gj in pairs:
            pt = placed_pts.get(str(n.id))
            if pt is not None and n.affiliation in _side_pts:
                _side_pts[n.affiliation].append(pt)
        _OPPOSING = {"Friend": "Hostile", "Hostile": "Friend",
                     "Neutral": "Friend", "Unknown": "Friend"}

        # Per-parent groups, template order preserved — the layout needs
        # each brood together; virtual parents resolve through the
        # breadth-first order (registered before their children arrive).
        group_order: List[str] = []
        groups: Dict[str, list] = {}
        for du in derived_units:
            pr = du["parent_ref"]
            if pr not in groups:
                groups[pr] = []
                group_order.append(pr)
            groups[pr].append(du)
        du_by_vid = {du["virtual_id"]: du for du in derived_units}
        for pr in group_order:
            anchor = painted_at.get(pr)
            if anchor is None:
                # Parent itself unpainted (unplaced with no placed
                # subordinates) — a doctrinal child cannot invent a
                # location for it.
                continue
            brood = groups[pr]
            real_parent = node_by_id.get(pr)
            v_parent = du_by_vid.get(pr) or {}
            p_aff = (real_parent.affiliation if real_parent is not None
                     else v_parent.get("affiliation"))
            parent_info = {
                "lon": anchor[0], "lat": anchor[1],
                "ech": (real_parent.echelon if real_parent is not None
                        else v_parent.get("echelon")),
                "aff": p_aff,
                # A virtual intermediate has no posture of its own; the
                # engine's defense default applies (same as an unset
                # recorded formation). A real parent's posture resolves
                # as-of under scrub, so the brood reshapes through time
                # (march column -> assembly cluster -> frontage); the
                # analyst's working-layer override, when set, wins the
                # SHAPE (it is exactly the visual it overrides).
                "posture": (posture_override_by_node.get(
                                pr, posture_asof.get(
                                    pr, real_parent.posture))
                            if real_parent is not None else None),
                "template_id": None,
                "name": (real_parent.name if real_parent is not None
                         else v_parent.get("name")),
            }
            brg = proximity_bearing(
                anchor[0], anchor[1],
                _side_pts.get(_OPPOSING.get(p_aff or "", "Friend"), []))
            planned = plan_disposition(
                parent_info,
                [{"id": du["virtual_id"], "name": du["name"],
                  "ut": du["unit_type"], "ech": du["echelon"]}
                 for du in brood],
                bearing_rad=brg)
            spots = {c["id"]: (lon, lat, slot, detail)
                     for c, lon, lat, slot, detail in planned}
            for du in brood:
                dlon, dlat, slot, detail = spots[du["virtual_id"]]
                dh = du.get("holdings") or []
                dominant = None
                resolved_dh = [hc for hc in dh if hc[1] is not None]
                if resolved_dh:
                    dominant = max(
                        resolved_dh,
                        key=lambda hc: (hc[0].count_authorized
                                        or hc[0].count_current or 0)
                    )[1].equipment_class
                shim = SimpleNamespace(
                    affiliation=du["affiliation"], echelon=du["echelon"],
                    entity_type=du["entity_type"], unit_type=du["unit_type"],
                    symbol_set=du["symbol_set"],
                    symbol_entity_code=du["symbol_entity_code"],
                    symbol_mod1=du["symbol_mod1"],
                    symbol_mod2=du["symbol_mod2"],
                    weg_id=None, name=du["name"], category=du.get("category"))
                rollup = {}
                for h, cat in dh:
                    key = (cat.name if cat
                           else (h.nomenclature_raw or h.weg_id
                                 or "unresolved equipment"))
                    rollup[key] = (rollup.get(key, 0)
                                   + (h.count_authorized
                                      or h.count_current or 0))
                features.append({
                    "type": "Feature", "id": du["virtual_id"],
                    "geometry": {"type": "Point",
                                 "coordinates": [dlon, dlat]},
                    "properties": {
                        "id": du["virtual_id"], "kind": "mil_unit",
                        "source": "reference_walk", "name": du["name"],
                        "sidc": compose_node_sidc(
                            shim, etypes.get(du["entity_type"]), dominant,
                            None, anticipated=True),
                        "echelon": du["echelon"],
                        "affiliation": du["affiliation"],
                        "entity_type": du["entity_type"],
                        "unit_type": du["unit_type"],
                        "parent": du["parent_ref"],
                        "composition_rollup": rollup or None,
                        # The analyst-visible honesty marker: this unit is
                        # doctrine projected from the reference catalog, not
                        # a recorded project entity with source basis.
                        "derived_from_template": True,
                        "position_derived": True,
                        "position_basis":
                            f"doctrinal disposition — {slot} of "
                            f"{parent_info['name']}, {detail} (template "
                            "subordinate projected at paint, not recorded)",
                    },
                })
                # Register it so DEEPER template levels can anchor to it (a
                # transport company hangs off a derived materiel-support
                # battalion). derived_units is breadth-first, so an
                # intermediate is always registered before its own children
                # are reached.
                painted_at[du["virtual_id"]] = [dlon, dlat]
    return features, ring_overlays


async def get_map_state(
    db: AsyncSession,
    map_id: UUID,
    bbox: List[float] = None,
    kinds: List[str] = None,
    as_of: Optional[datetime] = None,
    include_draft_of: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Get combined map state for rendering.

    Fetches entities, overlays, and routes for a map.
    Queries run sequentially (AsyncSession is single-connection),
    but each is now a single SQL round-trip — no N+1.

    as_of scrubs graph-sourced features to their positions at that
    time (append-only track resolution); legacy entity/overlay rows
    carry no history and paint as-is regardless.
    """

    entities = await get_entities(db, map_id, None, bbox)
    overlays = await get_overlays(db, map_id, None, bbox)
    routes = await get_routes(db, map_id)  # no bbox filter — routes span long distances
    # Units + rings from the entity graph — the record is the unit
    # source; legacy mil_unit entity rows coexist only until the
    # project wipes-and-restarts (design §8).
    graph_features, graph_ring_overlays = await _graph_features(
        db, map_id, as_of=as_of, include_draft_of=include_draft_of)

    # Timeline scrub domain: the dated-observation extent across the
    # project's track. The scrubber UI only appears when there is a
    # real time dimension (2+ dated observations).
    extent_row = (await db.execute(
        select(func.min(GraphNodePosition.observed_at),
               func.max(GraphNodePosition.observed_at),
               func.count(GraphNodePosition.observed_at))
        .join(GraphNode, GraphNode.id == GraphNodePosition.node_id)
        .where(GraphNode.project_id == map_id, GraphNode.layer == "project",
               GraphNodePosition.observed_at.isnot(None)))).first()
    # Posture changes are part of the time dimension (posture-timeline
    # design 2.2): committed posture assertions' valid_froms join the
    # same min/max — and the dated count — so a posture change alone
    # extends the scrub domain (and raises the scrubber when it is the
    # only dated history the record carries).
    posture_row = (await db.execute(
        select(func.min(Assertion.valid_from),
               func.max(Assertion.valid_from),
               func.count(Assertion.valid_from))
        .where(Assertion.project_id == map_id,
               Assertion.attribute == "posture",
               Assertion.kind.in_(("property", "state")),
               Assertion.record_state == "committed",
               Assertion.layer == "project",
               Assertion.superseded_by.is_(None),
               Assertion.retracted_by.is_(None),
               Assertion.valid_from.isnot(None)))).first()
    _mins = [v for v in ((extent_row[0] if extent_row else None),
                         (posture_row[0] if posture_row else None))
             if v is not None]
    _maxs = [v for v in ((extent_row[1] if extent_row else None),
                         (posture_row[1] if posture_row else None))
             if v is not None]
    track_extent = {
        "min": min(_mins).isoformat() if _mins else None,
        "max": max(_maxs).isoformat() if _maxs else None,
        "dated_observations": ((extent_row[2] if extent_row else 0)
                               + (posture_row[2] if posture_row else 0)),
    }

    if kinds:
        entities = [e for e in entities if e.kind in kinds]
        overlays = [o for o in overlays if o.kind in kinds]

    mil_unit_count = sum(1 for e in entities if e.kind == "mil_unit")

    entity_features = []
    for e in entities:
        # Compute MGRS from geometry for mil_units that don't already carry
        # location_mgrs in attrs. live_oob-synced units already write attrs.location_mgrs;
        # analyst-NL-created and analyst-create-panel units do not. The serializer
        # backfills here so every mil_unit Feature carries properties.location_mgrs
        # on the wire, while stored attrs.location_mgrs (when present) wins.
        computed_mgrs = None
        if e.kind == "mil_unit" and not (e.attrs or {}).get("location_mgrs"):
            try:
                gt = e.geom.get("type") if e.geom else None
                c = e.geom.get("coordinates") if e.geom else None
                if gt == "Point":
                    computed_mgrs = latlng_to_mgrs(c[1], c[0])
                elif gt in ("LineString", "MultiPoint") and c:
                    computed_mgrs = latlng_to_mgrs(c[0][1], c[0][0])
                elif gt == "Polygon" and c and c[0]:
                    computed_mgrs = latlng_to_mgrs(c[0][0][1], c[0][0][0])
            except Exception:
                computed_mgrs = None

        # Promote KG uuid into properties so downstream consumers that flatten
        # properties into a dict (TIDAT, etc.) can read f.properties.id directly.
        # Feature.id (top-level) is also retained for browser-side consumers.
        props = {
            "id": str(e.id),
            "kind": e.kind,
            "confidence": e.confidence,
        }
        if computed_mgrs:
            props["location_mgrs"] = computed_mgrs
        # Stored attrs win over any computed default (e.g. producer-supplied MGRS).
        props.update(e.attrs or {})
        entity_features.append({
            "type": "Feature",
            "id": str(e.id),
            "geometry": e.geom,
            "properties": props,
        })

    # Stamp `primitive` + `modifiers` from the catalog onto each outgoing
    # overlay feature. This is the SVG renderer's dispatch contract: the
    # frontend reads `f.properties.primitive` and dispatches to the matching
    # primitive drawer — no frontend catalog needed.
    # See geo-agent/backend/app/constants/overlays.py and
    # scratch/ibl/reports/MOVEMENT_ARROW_REDESIGN.md §2.1.
    overlay_features = []
    for o in overlays:
        render_attrs = resolve_render_attrs(
            o.kind, (o.geom or {}).get("type"))
        overlay_features.append({
            "type": "Feature",
            "id": str(o.id),
            "geometry": o.geom,
            "properties": {
                "kind": o.kind,
                "name": o.name,
                "primitive": render_attrs.get("primitive"),
                "modifiers": render_attrs.get("modifiers", {}),
                **o.attrs,
            },
        })

    route_items = [
        {
            "id": str(r.id),
            "name": r.name,
            "start_geom": r.start_geom,
            "end_geom": r.end_geom,
            "route_mode": r.route_mode,
            "status": r.status,
            "attrs": r.attrs,
            "paths": [
                {
                    "id": str(p.id),
                    "rank": p.rank,
                    "label": p.label,
                    "geom": p.geom,
                    "selected": p.selected,
                    "analysis": p.analysis,
                }
                for p in r.paths
            ],
        }
        for r in routes
    ]

    if kinds:
        graph_features = [f for f in graph_features
                          if f["properties"]["kind"] in kinds]
        graph_ring_overlays = [f for f in graph_ring_overlays
                               if f["properties"]["kind"] in kinds]
    # Units (SIDC point features) ride the ENTITY collection; graph
    # control measures ride the OVERLAY collection — that is the stream
    # applyDoctrinalControlMeasures paints from (phase lines, boundaries,
    # engagement areas...). Routing them as entities leaves them to the
    # generic fallback painter: wrong treatment, no labels (observed).
    entity_features.extend(
        f for f in graph_features
        if f["properties"]["kind"] == "mil_unit")
    overlay_features.extend(
        f for f in graph_features
        if f["properties"]["kind"] != "mil_unit")
    overlay_features.extend(graph_ring_overlays)

    return {
        "entities": {
            "type": "FeatureCollection",
            "features": entity_features,
        },
        "overlays": {
            "type": "FeatureCollection",
            "features": overlay_features,
        },
        "routes": route_items,
        "meta": {
            "entity_count": len(entities),
            "overlay_count": len(overlays),
            "mil_unit_count": mil_unit_count,
            "route_count": len(routes),
            "track_extent": track_extent,
            "as_of": as_of.isoformat() if as_of else None,
        },
    }
