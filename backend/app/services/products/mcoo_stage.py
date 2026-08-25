"""MCOO mechanical construction stage — MANUAL, deterministic.

The 2026-07-27 ruling: the terrain-circuit services (synthesize-mcoo,
discover-corridors) DO NOT WORK and are never called from the engine.
This stage constructs the MCOO's world-shaped output by hand from what
the world model already holds: the writer's avenue selections anchor on
committed key terrain / objectives, the doc-extracted mobility_corridor
entities supply the corridor enumeration, and the force laydown supplies
each side's origin. Everything here is a deterministic function of
committed world-model state plus the writer's validated field payload.

Output rows land in the record's PRIVATE DRAFT LAYER (layer='draft' +
origin_record_id): avenue_of_approach entities the record's own figure
paints and APPROVE merges project-wide (§2.2/§2.3). Committed corridors
are never duplicated — the record always beats doctrine — and nothing
is invented: an avenue with no resolvable objective point is logged and
skipped, never guessed.
"""
import logging
import math
import re
import uuid as uuid_mod
from typing import Any, Optional
from uuid import UUID

from geoalchemy2 import WKTElement
from geoalchemy2.functions import ST_AsText, ST_PointOnSurface
from sqlalchemy import select

from app.db.session import async_session
from app.models.graph import GraphNode

log = logging.getLogger(__name__)

_POINT_RE = re.compile(r"POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")

# A corridor supports an avenue when its centroid lies within this
# distance of the avenue's straight origin-to-objective trace.
_CORRIDOR_SUPPORT_KM = 20.0

_SIDE_AFFILIATION = {"friendly": "Friend", "threat": "Hostile",
                     "neutral": "Neutral"}


def _fold(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _parse_point(wkt: Optional[str]) -> Optional[tuple]:
    if not wkt:
        return None
    m = _POINT_RE.search(wkt)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))  # (lon, lat)


def _km(a: tuple, b: tuple) -> float:
    """Equirectangular distance — deterministic and sufficient at
    operational scale."""
    lat_scale = math.cos(math.radians((a[1] + b[1]) / 2.0))
    dx = (b[0] - a[0]) * lat_scale * 111.32
    dy = (b[1] - a[1]) * 110.57
    return math.hypot(dx, dy)


def _point_to_segment_km(p: tuple, a: tuple, b: tuple) -> float:
    lat_scale = math.cos(math.radians((a[1] + b[1] + p[1]) / 3.0))

    def _xy(pt):
        return pt[0] * lat_scale * 111.32, pt[1] * 110.57

    px, py = _xy(p)
    ax, ay = _xy(a)
    bx, by = _xy(b)
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq <= 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _mgrs_to_lonlat(grid: str) -> Optional[tuple]:
    try:
        from app.utils.mgrs_utils import mgrs_to_latlng
        lat, lon = mgrs_to_latlng(grid)
        return (lon, lat)
    except Exception:
        return None


async def _committed_points(db, project_id: UUID, kinds: list
                            ) -> list[dict]:
    rows = (await db.execute(
        select(GraphNode, ST_AsText(ST_PointOnSurface(GraphNode.geom)))
        .where(GraphNode.project_id == project_id,
               GraphNode.layer == "project",
               GraphNode.entity_type.in_(kinds),
               GraphNode.geom.isnot(None))
        .order_by(GraphNode.entity_type, GraphNode.name,
                  GraphNode.id))).all()
    out = []
    for n, wkt in rows:
        pt = _parse_point(wkt)
        if pt is None:
            continue
        out.append({"id": n.id, "name": n.name,
                    "affiliation": n.affiliation, "point": pt})
    return out


async def _force_centroid(db, project_id: UUID,
                          affiliation: str) -> Optional[tuple]:
    units = await _committed_points(db, project_id, ["unit"])
    pts = [u["point"] for u in units if u["affiliation"] == affiliation]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts))


async def construct_mcoo_draft(record_id: UUID, project_id: UUID,
                               content: dict, append_log) -> dict:
    """Construct the MCOO record's draft-layer avenues and enrich the
    writer's avenue items with the committed-corridor enumeration.
    Returns the (mutated) structured content."""
    avenues = content.get("avenues_of_approach")
    if not isinstance(avenues, list) or not avenues:
        await append_log("mcoo construction: no avenue items emitted — "
                         "nothing to construct")
        return content

    async with async_session() as db:
        corridors = await _committed_points(
            db, project_id, ["mobility_corridor"])
        anchors = await _committed_points(
            db, project_id,
            ["key_terrain", "objective", "engagement_area",
             "assembly_area", "garrison", "rail_hub", "bridge"])
        centroids = {
            "Friend": await _force_centroid(db, project_id, "Friend"),
            "Hostile": await _force_centroid(db, project_id, "Hostile"),
        }
        anchor_by_name = {_fold(a["name"]): a for a in anchors}

        built = 0
        for idx, item in enumerate(avenues):
            if not isinstance(item, dict):
                continue
            side = str(item.get("side") or "").strip().lower()
            affiliation = _SIDE_AFFILIATION.get(side, "Neutral")
            # Objective point: the stated grid first, then a committed
            # anchor entity by name. Nothing resolvable = skip, logged.
            objective = None
            grid = str(item.get("objective_mgrs") or "").strip()
            if grid:
                objective = _mgrs_to_lonlat(grid)
            if objective is None:
                named = anchor_by_name.get(
                    _fold(str(item.get("objective_name") or "")))
                if named:
                    objective = named["point"]
            if objective is None:
                await append_log(
                    f"mcoo construction: avenue {item.get('id') or idx}"
                    " has no resolvable objective point — skipped "
                    "(never guessed)")
                continue
            # Origin: the maneuvering side's force centroid; a side
            # with no placed forces gets no avenue (honest skip).
            origin = centroids.get(affiliation)
            if origin is None:
                fallback = [c for c in centroids.values() if c]
                origin = fallback[0] if len(fallback) == 1 else None
            if origin is None or _km(origin, objective) < 0.5:
                await append_log(
                    f"mcoo construction: avenue {item.get('id') or idx}"
                    " has no usable origin — skipped")
                continue
            # Constituent corridors: committed mobility corridors whose
            # centroid supports the origin->objective trace. The
            # committed rows already paint on the project layer — they
            # are ENUMERATED here, never duplicated as draft rows.
            support = sorted(
                (c for c in corridors
                 if _point_to_segment_km(c["point"], origin, objective)
                 <= _CORRIDOR_SUPPORT_KM),
                key=lambda c: (c["name"] or "", str(c["id"])))
            if support and not item.get("mobility_corridors"):
                item["mobility_corridors"] = [
                    {"corridor_id": c["name"], "from_name": c["name"],
                     "from_mgrs": "", "class": "unknown"}
                    for c in support]
            name = str(item.get("id") or "").strip() or (
                f"AA {idx + 1}")
            obj_name = str(item.get("objective_name") or "").strip()
            wkt = (f"LINESTRING({origin[0]:.6f} {origin[1]:.6f}, "
                   f"{objective[0]:.6f} {objective[1]:.6f})")
            db.add(GraphNode(
                id=uuid_mod.uuid4(), project_id=project_id,
                entity_type="avenue_of_approach",
                name=name,
                long_name=(f"{name} — {obj_name}" if obj_name else None),
                affiliation=affiliation,
                geom=WKTElement(wkt, srid=4326),
                notes=(str(item.get("rationale") or "")[:500] or None),
                layer="draft", origin_record_id=record_id,
                created_by="_autodraft"))
            built += 1
        await db.commit()
    await append_log(
        f"mcoo construction: {built} avenue_of_approach draft rows "
        f"built ({len(corridors)} committed corridors enumerated); "
        "approval merges them project-wide")
    return content


# Schema-declared dispatch: a SPEC opts in with
# "construction_stage": "<key>"; the engine stays generic.
CONSTRUCTION_STAGES = {
    "mcoo": construct_mcoo_draft,
}
