"""Append-only position track — the ONE write surface for entity positions.

A road to war narrates a unit moving through positions over time; every
placement in this system is a dated OBSERVATION appended to the unit's
track (graph_node_positions), never an overwrite. The unit's CURRENT
position — what the map paints — is the newest observation, mirrored to
graph_nodes.geom. Timeline scrub/replay reads the latest observation
with observed_at <= the scrub time.

Everything that places an entity routes through record_position: the
bulk ingest (single positions and road-to-war tracks alike), the FRAGO
reposition path, and the add_position agent tool. There is deliberately
no second way to set a unit's position.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import GraphNode, GraphNodePosition

log = logging.getLogger("app.graph_ingest.track")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "141200Z JAN 26" / "141200ZJAN26" / "170600L JUL 2026" — day+time DTG with a
# military zone designator (Z=Zulu and any single zone letter, incl. an order's
# declared-Local "L"), month, and year. The stated wall-clock numbers are
# preserved and stamped UTC (no per-letter offset shift — same as the original
# Zulu-only behavior); an order declaring one local zone throughout keeps every
# intra-order time mutually consistent. A trailing "." after the month abbrev is
# tolerated.
_DTG_FULL = re.compile(
    r"^\s*(\d{1,2})(\d{2})(\d{2})\s*[A-Za-z]?\s*([A-Za-z]{3})[A-Za-z]*\.?\s*(\d{2,4})\s*$")
# "14 JAN 26" / "14 JAN 2026" / "6 April 2026" — date with year.
_DATE_Y = re.compile(
    r"^\s*(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{2,4})\s*$")
# "2026-01-14" (optionally with time).
_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?\s*Z?\s*$")


def _year(v: str) -> int:
    y = int(v)
    return y + 2000 if y < 100 else y


def parse_dtg(raw: Optional[str]) -> Optional[datetime]:
    """Best-effort DTG → timezone-aware datetime. Only fully-dated forms
    parse; a partial DTG ("06 APR", "D+30") returns None — the raw string
    is preserved as dtg_label and document order carries the sequence.
    Nothing is ever fabricated to fill the gap."""
    if not raw:
        return None
    m = _DTG_FULL.match(raw)
    if m:
        day, hh, mm, mon, yy = m.groups()
        month = _MONTHS.get(mon.lower())
        if month:
            try:
                return datetime(_year(yy), month, int(day), int(hh), int(mm),
                                tzinfo=timezone.utc)
            except ValueError:
                return None
    m = _DATE_Y.match(raw)
    if m:
        day, mon, yy = m.groups()
        month = _MONTHS.get(mon.lower())
        if month:
            try:
                return datetime(_year(yy), month, int(day), tzinfo=timezone.utc)
            except ValueError:
                return None
    m = _ISO.match(raw)
    if m:
        y, mo, d, hh, mm = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0),
                            tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# -- Relative temporal coordinates (design 6.8 up-projection) --------
# H+36 / D+2 / "D-1 0600" resolve only against a stored datum. Anchors
# are PROJECT facts riding map.attrs.temporal_anchors -- exactly like
# the range overrides -- e.g. {"h_hour": "2026-08-11T00:00:00Z",
# "d_day": "2026-08-11"}. The up-projection REJECTS a relative time
# with no anchor rather than guessing one.
_REL_DTG = re.compile(
    r"^\s*([HD])\s*([+-])\s*(\d+)(?:\s+(\d{2})(\d{2}))?\s*$",
    re.IGNORECASE)


class UnanchoredRelativeTime(ValueError):
    """A relative DTG (H+36, D+2) arrived with no stored anchor."""


def parse_relative_dtg(raw, anchors):
    """H+/D+ offsets against project temporal anchors. Returns None when
    `raw` is not a relative form (the absolute parser owns it); raises
    UnanchoredRelativeTime when it IS relative and no anchor exists."""
    if not raw:
        return None
    m = _REL_DTG.match(raw)
    if not m:
        return None
    datum_key = "h_hour" if m.group(1).upper() == "H" else "d_day"
    datum_raw = (anchors or {}).get(datum_key)
    if not datum_raw:
        raise UnanchoredRelativeTime(
            f"relative time '{raw.strip()}' needs the project anchor "
            f"'{datum_key}' (set map attrs.temporal_anchors."
            f"{datum_key}); refusing to guess a datum")
    datum = parse_dtg(datum_raw)
    if datum is None:
        datum = datetime.fromisoformat(datum_raw.replace("Z", "+00:00"))
    if datum.tzinfo is None:
        datum = datum.replace(tzinfo=timezone.utc)
    sign = 1 if m.group(2) == "+" else -1
    if m.group(1).upper() == "H":
        base = datum + timedelta(hours=sign * int(m.group(3)))
    else:
        base = datum + timedelta(days=sign * int(m.group(3)))
    if m.group(4):
        base = base.replace(hour=int(m.group(4)), minute=int(m.group(5)))
    return base


async def _newest_observed(db: AsyncSession, node_id) -> Optional[datetime]:
    return (await db.execute(
        select(func.max(GraphNodePosition.observed_at)).where(
            GraphNodePosition.node_id == node_id))).scalar_one_or_none()


# Route control measures are ROAD paths — an MSR drawn as straight
# waypoint legs reads like an air corridor. At write time each leg is
# routed on the actual road network (the internal on_road planner);
# the waypoints remain the analyst's statement, the geometry becomes
# the road alignment. Fails open leg-by-leg.
_ROUTE_KINDS = {"main_supply_route", "alternate_supply_route", "route",
                "asr_one_way", "asr_two_way", "asr_alternating"}
_LINESTRING = re.compile(r"^\s*LINESTRING\s*\((.+)\)\s*$", re.IGNORECASE)


async def _route_line_along_roads(
    db: AsyncSession, node: GraphNode, geom_wkt: str,
    source: Optional[str],
) -> Tuple[str, Optional[str]]:
    m = _LINESTRING.match(geom_wkt or "")
    if not m or node.project_id is None:
        return geom_wkt, source
    try:
        pts = [tuple(map(float, p.split())) for p in m.group(1).split(",")]
    except ValueError:
        return geom_wkt, source
    # Waypoint lines only — a shape that already carries a dense
    # alignment (a previous routing pass, an imported trace) passes
    # through untouched.
    if len(pts) < 2 or len(pts) > 12:
        return geom_wkt, source
    import asyncio
    import math
    from app.services.knowledge.routing.models import PlanRequest
    from app.services.knowledge.routing.planner import plan_routes

    # HARD guards: the write path must NEVER become a denial of
    # service (staging outage, 2026-07-17: a corridor leg fed to the
    # dense Overpass+A* engine pinned the box). Long legs now dispatch
    # to the planet-tile hierarchy router inside plan_routes — bounded
    # tile caps, real awaits (so the timeout actually cancels), no
    # external fetches. The leg cap is a sanity ceiling, not a memory
    # guard anymore.
    MAX_LEG_KM = 700.0
    LEG_TIMEOUT_S = 90.0

    def _km(lat1, lon1, lat2, lon2):
        x = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
        y = (lat2 - lat1) * 110.57
        return math.hypot(x, y)

    out = [pts[0]]
    routed = 0
    capped = 0
    for (lon1, lat1), (lon2, lat2) in zip(pts, pts[1:]):
        leg = None
        if _km(lat1, lon1, lat2, lon2) > MAX_LEG_KM:
            capped += 1
        else:
            try:
                results, _diag = await asyncio.wait_for(
                    plan_routes(db, PlanRequest(
                        start_lat=lat1, start_lon=lon1,
                        end_lat=lat2, end_lon=lon2,
                        route_mode="on_road", map_id=node.project_id)),
                    timeout=LEG_TIMEOUT_S)
                if results and results[0].coords and len(results[0].coords) >= 2:
                    leg = results[0].coords          # (lon, lat) pairs
            except Exception as exc:                 # fail open per leg
                log.warning("route leg (%s,%s)->(%s,%s) not road-routed: %s",
                            lat1, lon1, lat2, lon2, exc)
        if leg:
            out.extend([(c[0], c[1]) for c in leg[1:]])
            routed += 1
        else:
            out.append((lon2, lat2))
    if not routed:
        return geom_wkt, source
    note = f"routed along the road network ({routed}/{len(pts) - 1} legs"
    if capped:
        note += (f"; {capped} leg(s) beyond the {MAX_LEG_KM:g} km "
                 "road-routing cap kept as stated")
    note += ")"
    source = f"{source}; {note}" if source else note
    wkt = "LINESTRING(" + ", ".join(
        f"{lon:.6f} {lat:.6f}" for lon, lat in out) + ")"
    return wkt, source


async def record_position(
    db: AsyncSession,
    node: GraphNode,
    *,
    lon: Optional[float] = None,
    lat: Optional[float] = None,
    geom_wkt: Optional[str] = None,
    mgrs: Optional[str] = None,
    location_text: Optional[str] = None,
    dtg: Optional[str] = None,
    activity: Optional[str] = None,
    source: Optional[str] = None,
    created_by: str = "_ingest",
    land_checked: bool = False,
) -> Tuple[GraphNodePosition, bool]:
    """Append one position observation; mirror it to node.geom when it is
    the unit's newest. Returns (row, became_current).

    geom_wkt carries a non-point shape (a phase line's LINESTRING, an
    engagement area's POLYGON) — a FRAGO redrawing a control measure is
    an append-only observation exactly like a unit reposition.

    Time contract (2026-07-21 ruling — observed_at is never null): a
    stated DTG carries the source's time; a stated-but-UNPARSEABLE DTG
    REJECTS the item (ValueError -> the batched tool's per-item error
    echo, raw DTG in the message for the extraction repair — never
    silently stamped, which would launder the bad parse); an
    observation with no stated time is an assertion being made now and
    is stamped at the assertion moment. Newest-wins: the observation
    with the greatest observed_at is current.

    LAND SNAP (user ruling 2026-07-17): a POINT position for a land
    entity that falls in permanent water snaps to the nearest landmass
    at WRITE time — even when a stated grid put it there. The raw
    coordinates stay in the note; maritime entities (carrier groups,
    coast guard...) and non-point shapes are exempt.
    """
    observed_at = parse_dtg(dtg)
    if observed_at is None and dtg:
        # Relative form? Resolve against the project temporal anchors
        # (map.attrs.temporal_anchors). Raises UnanchoredRelativeTime
        # -- surfaced in the tool echo -- when the datum is missing.
        try:
            from app.models.map import Map as _Map
            _mrow = await db.get(_Map, node.project_id)
            _anchors = ((_mrow.attrs or {}).get("temporal_anchors")
                        if _mrow is not None else None)
        except Exception:
            _anchors = None
        observed_at = parse_relative_dtg(dtg, _anchors)
    if (geom_wkt is not None
            and getattr(node, "entity_type", None) in _ROUTE_KINDS):
        try:
            geom_wkt, source = await _route_line_along_roads(
                db, node, geom_wkt, source)
        except Exception:
            log.warning("road-routing failed open for %s", node.name)
    if geom_wkt is None and lon is not None and lat is not None:
        from app.services.graph_ingest.landcheck import (
            is_maritime, snap_point_to_land,
        )
        etype = getattr(node, "entity_type", None)
        # Linear-feature infrastructure snaps ONTO its feature (a rail
        # segment onto the railway, not the town center). Overpass-
        # backed; fails open.
        _RAIL = {"rail_hub"}
        _ROAD = {"main_supply_route", "alternate_supply_route", "route",
                 "bridge"}
        if etype in _RAIL or etype in _ROAD:
            from app.services.geocode.snap import snap_to_osm_feature
            kind = "railway" if etype in _RAIL else "road"
            try:
                s_lat, s_lon, moved, way = await snap_to_osm_feature(
                    lat, lon, kind)
            except Exception:
                s_lat, s_lon, moved, way = lat, lon, None, None
            if moved and moved > 0:
                note = (f"snapped {moved:g} km onto the nearest {kind}"
                        + (f" ({way})" if way else ""))
                source = f"{source}; {note}" if source else note
                lon, lat = s_lon, s_lat
        elif not land_checked and not is_maritime(node.name, node.unit_type):
            # land_checked=True means the CALLER already ran the point
            # through the land classifier (the disposition engine
            # land-checks every synthesized point in batch) — running
            # the write-time snap again doubles the raster sampling for
            # no new information.
            try:
                s_lon, s_lat, moved = await snap_point_to_land(lon, lat)
            except Exception:
                s_lon, s_lat, moved = lon, lat, None   # fail open
            if moved and moved > 0:
                note = (f"stated position ({lat:.4f}, {lon:.4f}) in water"
                        f" — snapped {moved:g} km to nearest land")
                source = f"{source}; {note}" if source else note
                lon, lat = s_lon, s_lat
        geom_wkt = f"POINT({lon} {lat})"
    # observed_at is the record's ONE temporal dimension and is NEVER
    # null (2026-07-21 ruling). Three cases, none guessed:
    # stated time, parsed -> the source's time (above); stated time,
    # UNPARSEABLE -> REJECT the item — stamping the ingest moment
    # would launder a bad parse into a legitimate-looking observation
    # and destroy the repair signal, so the raw DTG rides the error
    # for the extraction fix; no stated time -> the assertion is
    # being made NOW (an analyst/agent act) and the assertion moment
    # is its observation time.
    if observed_at is None and dtg:
        raise ValueError(
            f"unparseable DTG '{dtg.strip()}' — the observation keeps "
            f"its stated time or is rejected; fix the extraction (or "
            f"the anchor) and resubmit")
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)
    row = GraphNodePosition(
        node_id=node.id,
        geom=WKTElement(geom_wkt, srid=4326) if geom_wkt else None,
        mgrs=mgrs, location_text=location_text,
        observed_at=observed_at, dtg_label=dtg, activity=activity,
        source=source, created_by=created_by,
    )
    db.add(row)
    # Flush so the newest-check sees every observation appended so far in
    # this transaction (a track ingested oldest-to-newest in one batch).
    await db.flush()

    became_current = False
    if geom_wkt:
        newest = await _newest_observed(db, node.id)
        if newest is None or observed_at >= newest:
            node.geom = WKTElement(geom_wkt, srid=4326)
            if activity and not node.current_activity:
                node.current_activity = activity
            became_current = True
    return row, became_current
