"""Doctrinal disposition — arraying a formation's unplaced subordinates.

The engine places what the documents did not state: subordinates of a
placed formation array across the formation's doctrinal frontage FACING
the opposing force, echeloned in depth by role. A stated position is
never touched — parsed grids outrank everything (the ingest ladder), and
this engine only fills true gaps.

Frontage/depth norms resolve in precedence order:
 1. the unit's force-template row (frontage_*/depth_* columns, values
    extracted from the doctrine library; provenance rides the
    template's doctrine_source field),
 2. per-echelon defaults (_ECHELON_NORMS — doctrine-extraction sourced,
    see scratch/docs/oob/doctrinal-frontages.md),
 3. the legacy echelon table (_LEGACY_FRONTAGE_M) as a last resort so a
    formation never silently fails to array.

Every synthesized point is land-checked against ESA WorldCover: a land
formation never paints in permanent water. A wet candidate walks a ring
search for the nearest dry ground; if none is reachable inside the
search budget the subordinate is SKIPPED AND REPORTED — placed wrong is
worse than visibly unplaced.

Writes go through record_position (the ONE write surface) with an
explicit source string, so the unit placard shows exactly where the
location came from and the append-only track stays the record.
"""

import math
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import POSTURES, ForceTemplate, GraphNode
from app.services.graph_ingest.track import record_position
from app.services.graph_ingest.landcheck import ensure_on_land


def _offset(lon, lat, bearing_rad, dist_m):
    lat_m = 111320.0
    lon_m = 111320.0 * max(0.2, math.cos(math.radians(lat)))
    return (lon + dist_m * math.sin(bearing_rad) / lon_m,
            lat + dist_m * math.cos(bearing_rad) / lat_m)


# Sunflower angle for deterministic 2D dispersion (assembly clusters).
_GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))


def _clamp_into(poly, lon, lat, center):
    """(lon, lat, clamped) — a point outside the polygon is pulled to
    the nearest interior point (boundary nearest point nudged toward
    the cluster center so it sits inside, not on the line)."""
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    pt = Point(lon, lat)
    if poly.contains(pt):
        return lon, lat, False
    b = nearest_points(poly, pt)[0]
    lon2 = b.x + 0.05 * (center[0] - b.x)
    lat2 = b.y + 0.05 * (center[1] - b.y)
    if poly.contains(Point(lon2, lat2)):
        return lon2, lat2, True
    return b.x, b.y, True


# ── Role classification (moved verbatim from graph_ingest.__init__ —
# the engine owns it now; __init__ re-imports for compatibility).
_ROLE_KEYWORDS = [
    ("recon", ("cavalry", "reconnaissance", "recon", "scout", "isr")),
    ("artillery", ("field artillery", "artillery", "howitzer", "rocket", "mlrs", "fires")),
    ("air_defense", ("air defense", "air defence", "anti-aircraft", "antiaircraft", " sam", "surface-to-air")),
    ("missile", ("missile", "ssm", "iskander", "ballistic")),
    ("aviation", ("aviation", "helicopter", "rotary")),
    ("antitank", ("anti-tank", "antitank", "antiarmor", "anti-armor")),
    ("engineer", ("engineer", "sapper")),
    ("signal", ("signal", "communications", "electronic warfare")),
    ("sustainment", ("sustainment", "logistics", "transport", "supply", "support", "maintenance", "medical", "quartermaster")),
    ("airborne", ("airborne", "air assault", "parachute")),
    ("armor", ("tank", "armor", "armour")),
    ("combined_arms", ("combined arms", "mechanized", "mechanised", "motorized", "motorised", "stryker")),
    ("infantry", ("infantry", "rifle", "grenadier")),
]


def role_class(name, unit_type=None):
    t = f"{name or ''} {unit_type or ''}".lower()
    for cls, kws in _ROLE_KEYWORDS:
        if any(k in t for k in kws):
            return cls
    return None


_MANEUVER_ROLES = {"infantry", "armor", "combined_arms", "airborne", None}

# Per-echelon doctrinal norms, kilometers: (frontage_defense,
# depth_defense, frontage_offense, depth_offense). Values from the
# doctrine-library extraction (scratch/docs/oob/doctrinal-frontages.md,
# verbatim-cited); "up to X" doctrinal ceilings are used as X; where a
# document states a range the midpoint is used and the full range rides
# the comment. TWO maps — threat-model doctrine and US/friendly
# doctrine differ materially — selected by the formation's affiliation;
# a friendly echelon absent from the friendly map (BCT/battalion — the
# US manuals deliberately state no value; documented gaps) falls
# through to the threat map, then the legacy table.
_THREAT_ECHELON_NORMS: Dict[str, Tuple[float, float, float, float]] = {
    # ATP 7-100.1 (current Russian, preferred over the legacy-Soviet
    # B-10 band per the extraction's own flag): brigade main defensive
    # zone "up to 15 km wide and up to 20 km deep" (para 6-9); attack
    # from hasty defense frontage up to 20 km, depth 30 km (para 3-75).
    # Brigade and regiment are used interchangeably (para 6-14).
    "Brigade": (15.0, 20.0, 20.0, 30.0),
    "Regiment": (15.0, 20.0, 20.0, 30.0),
    # ATP 7-100.1 para 6-67: battalion defensive area up to 5 km front,
    # 3 km depth. No battalion offense value stated (BTG gap) — defense
    # values carried rather than an invented number.
    "Battalion": (5.0, 3.0, 5.0, 3.0),
    "Squadron": (5.0, 3.0, 5.0, 3.0),
    # ATP 2-01.3 Table B-10: company/team defense frontage 0.5-1 km
    # (midpoint 0.75), depth 0.5 km. Offense not stated at company —
    # defense values carried.
    "Company": (0.75, 0.5, 0.75, 0.5),
    "Troop": (0.75, 0.5, 0.75, 0.5),
    "Battery": (0.75, 0.5, 0.75, 0.5),
    # ATP 2-01.3 Table B-10: division defense frontage 20-30 km
    # (midpoint 25), depth 15-20 km (17.5). Table B-11 offense: zone of
    # attack 15-25 km (20), immediate objective depth 20-30 km (25).
    "Division": (25.0, 17.5, 20.0, 25.0),
    # T2COM RUS LSCO Figure 10 defense: CAA total width 120-150 km
    # (135), total depth 100-200 km (150). Offense: ATP 2-01.3 Table
    # B-11 army zone of attack 60-100 km (80); depth from T2COM Figure
    # 11 echelon zones 30-40 + 60-80 km (~105).
    "Army": (135.0, 150.0, 80.0, 105.0),
    # No threat corps value stated anywhere in the library — US corps
    # band carried as the only doctrinal corps figure (FM 3-0 Fig 6-1).
    "Corps": (70.0, 45.0, 70.0, 45.0),
}

_FRIENDLY_ECHELON_NORMS: Dict[str, Tuple[float, float, float, float]] = {
    # FM 3-0 Figure 6-1 / FM 3-94 para C-40: division AO width 18-28 km
    # (midpoint 23), depth 24 km (close area 15 km + deep to 24).
    "Division": (23.0, 24.0, 23.0, 24.0),
    # FM 3-0 Figure 6-1 / FM 3-94: corps AO width 55-85 km (70), depth
    # 45 km.
    "Corps": (70.0, 45.0, 70.0, 45.0),
    # FM 3-0 Figure 6-1 / FM 3-94: field army frontage 110-250 km
    # (180), AO depth 200 km.
    "Army": (180.0, 200.0, 180.0, 200.0),
    # US BCT/battalion/company frontage-depth: the echelon manuals
    # deliberately state NO value (documented gaps in the extraction —
    # FM 3-96/ATP 3-90.x/3-21.x swept in full). Friendly formations
    # never take threat-doctrine values; below division they fall to
    # the neutral planning defaults, labeled as such.
}

# Doctrine-stated ABSOLUTE security/support offsets from the FLOT for a
# brigade-or-larger formation, kilometers (ATP 7-100.1): forward
# positions/security elements 6-8 km forward (para 6-35 → 7), ATGM
# battery up to 2 km and antitank battalion up to 5 km from the front
# (para 6-50 → 3.5 mid-band), battalion COP ~2 km behind the FEBA
# (para 6-53). Applied at Brigade+ where they outrank the fractional
# topology; smaller echelons scale by fraction.
_SECURITY_OFFSETS_KM = {
    "recon": +7.0,
    "antitank": -3.5,
}

# Last-resort legacy values (pre-doctrine-extraction). Superseded by
# template rows and _ECHELON_NORMS as those populate; kept so the
# engine never leaves a formation unarrayed for want of a number.
_LEGACY_FRONTAGE_M = {
    "Army": 100000, "Corps": 60000, "Division": 30000, "Regiment": 15000,
    "Brigade": 15000, "Squadron": 9000, "Battalion": 6000, "Battery": 3000,
    "Company": 2500, "Troop": 2500, "Platoon": 800, "Section": 300,
    "Squad": 150, "Team": 100,
}

# ── Posture axis ─────────────────────────────────────────────────────
# A formation's posture selects the ARRAY SHAPE, not just the frontage
# number: combat postures array across a frontage; an assembly/staging
# posture disperses in a 2D concentration area; a march posture strings
# a column along the axis of movement; a screen stretches a single thin
# echelon across a security frontage. Combat has not started for a unit
# sitting in an assembly area — spreading it across its combat frontage
# was the bug (2CR Week 1).

def posture_mode(posture: str) -> str:
    """assembly | march | screen | offense | defense (default)."""
    p = (posture or "").lower()
    if any(w in p for w in ("assembl", "staging", "reserve", "marshal",
                            "concentrat", "bivouac")):
        return "assembly"
    if any(w in p for w in ("march", "column", "convoy", "road move")):
        return "march"
    if any(w in p for w in ("screen", "security", "guard", "cover")):
        return "screen"
    if any(w in p for w in ("attack", "assault", "advance", "offen")):
        return "offense"
    return "defense"


# The posture values the placard selector offers — every mode the
# engine supports, by its canonical analyst-facing word. The closed set
# lives in the model registry (models/graph.py POSTURES, enforced by
# _MIRROR_COLUMNS validation + ck_graph_nodes_posture); this is the
# engine-side alias, kept so existing callers keep their import.
SUPPORTED_POSTURES = POSTURES

# Concentration/marshaling-area dispersion, km²  (ATP 7-100.1 para
# 7-171: battalion 10 sq km or more, maneuver brigade 100 sq km;
# regiment carried at the brigade figure — the ATP uses brigade and
# regiment interchangeably, para 6-14). Echelons the doctrine does not
# state are DERIVED at runtime from their subordinates' stated areas
# (sum x 1.5 packing) and labeled as derived, never presented as
# stated doctrine. US assembly-area sizing is a documented gap across
# the US manual set (FM 3-90/ATP 3-90.5/FM 3-96 swept — qualitative
# only), so friendly formations take a planning default, labeled.
_THREAT_CONCENTRATION_KM2 = {
    "Battalion": 10.0, "Squadron": 10.0,
    "Brigade": 100.0, "Regiment": 100.0,
    # Division assembly area 300-600 sq km (FM 100-2-1 The Soviet Army:
    # Operations and Tactics, 1984, p. 6-16 — archive sweep 2026-07-21;
    # legacy-Soviet edition, the only division-echelon figure stated
    # anywhere in the library; midpoint per the library convention).
    "Division": 450.0,
}
_MARSHAL_COMPANY_SPACING_M = 1500.0   # >= 1.5 km between companies
                                      # in the marshaling area
                                      # (ATP 7-100.1 para 7-171, fig 7-14)
_ASSEMBLY_PACKING = 1.5               # derived-area packing factor
_FRIENDLY_ASSEMBLY_RADIUS_FRAC = 0.30  # planning default: radius as a
                                       # fraction of legacy frontage

# March column: an infantry company occupies ~1 km of road (FM 3-90
# para 14-27, open column 50-100 m / 15-20 veh per km); >= 1 km between
# battalion march columns and logistics trailing 1-2 km behind the main
# body (ATP 7-100.1 para 7-173, H-10). Column lengths above company are
# derived from the open-column density and labeled derived.
_COLUMN_LENGTH_KM = {
    "Team": 0.1, "Squad": 0.15, "Section": 0.25, "Platoon": 0.35,
    "Company": 1.0, "Troop": 1.0, "Battery": 1.0,
    "Battalion": 2.5, "Squadron": 2.5,
    "Regiment": 12.0, "Brigade": 12.0, "Division": 40.0,
}
_COLUMN_STATED_ECHELONS = {"Company", "Troop", "Battery"}
_COLUMN_GAP_MAJOR_KM = 1.0            # between battalion+ columns
_COLUMN_GAP_MINOR_KM = 0.1            # between company-and-below slots
_COLUMN_TRAIL_GAP_KM = 2.0            # extra gap before the log tail
# March order by role, head to tail (reconnaissance leads, antitank at
# the head of the artillery, artillery between the advance guard and
# the main body, sustainment trails — ATP 7-100.1 paras 5-63, 7-173).
_MARCH_ORDER = ("recon", "antitank", "artillery", None, "armor",
                "combined_arms", "infantry", "airborne", "air_defense",
                "engineer", "signal", "missile", "aviation",
                "sustainment")

# Screen frontages, km. US cavalry planning distances: platoon 3-5,
# troop 10-12, squadron 15-45 (ATP 3-20.96 para 2-91, midpoints);
# depth = width / 2 (ATP 3-20.97 Table A-1 formula family). Threat
# reconnaissance zones: battalion detachment up to 10 km wide, company
# 5 km (ATP 7-100.1 para 3-83).
_FRIENDLY_SCREEN_KM = {"Platoon": 4.0, "Troop": 11.0, "Company": 11.0,
                       "Squadron": 30.0, "Battalion": 30.0}
_THREAT_SCREEN_KM = {"Battalion": 10.0, "Squadron": 10.0,
                     "Company": 5.0, "Troop": 5.0}

# Role placement relative to the formation: fwd = offset ALONG the
# threat axis as a fraction of formation depth measured from the FLOT
# (positive = toward the enemy), spread = how much of the frontage the
# role's members array across. The TOPOLOGY is doctrine-generic (recon
# screens forward of the FLOT; first-echelon maneuver holds it; fires
# range from behind the first echelon; sustainment sits deep);
# absolute distances scale off the doctrine-sourced frontage/depth.
_ROLE_OFFSETS = {
    "recon":        (+0.25, 1.00),
    "antitank":     (-0.15, 0.80),
    "artillery":    (-0.35, 0.70),
    "air_defense":  (-0.25, 0.90),
    "engineer":     (-0.50, 0.60),
    "missile":      (-0.80, 0.40),
    "aviation":     (-0.90, 0.50),
    "signal":       (-0.70, 0.30),
    "sustainment":  (-0.85, 0.60),
}

def _assembly_norms_for(node_info: dict,
                        child_echelons: List[str]) -> Tuple[float, float, str]:
    """(radius_m, spacing_floor_m, provenance) for a concentration-area
    dispersion. Stated threat figures where the doctrine states them;
    derived (and labeled derived) from subordinate norms elsewhere;
    friendly formations take a labeled planning default (US assembly
    sizing is a documented doctrine gap)."""
    ech = node_info.get("ech") or ""
    friendly = node_info.get("aff") == "Friend"
    # The company-spacing floor is a threat doctrine figure — friendly
    # formations never take threat values (user ruling 2026-07-17), so
    # the floor applies to the threat side only.
    floor = (_MARSHAL_COMPANY_SPACING_M
             if not friendly and any(c in ("Company", "Troop", "Battery")
                                     for c in child_echelons) else 0.0)
    if friendly:
        f = _LEGACY_FRONTAGE_M.get(ech, 10000)
        return (f * _FRIENDLY_ASSEMBLY_RADIUS_FRAC, floor,
                f"{ech or 'formation'} assembly dispersion, US planning "
                "default (no doctrinal value stated)")
    area = _THREAT_CONCENTRATION_KM2.get(ech)
    if area is not None:
        return (math.sqrt(area / math.pi) * 1000.0, floor,
                f"{ech} concentration-area dispersion "
                f"{area:g} km2, threat doctrine norm")
    child_areas = [_THREAT_CONCENTRATION_KM2.get(c) for c in child_echelons]
    known = [a for a in child_areas if a]
    if known:
        total = sum(a if a else min(known)
                    for a in child_areas) * _ASSEMBLY_PACKING
        return (math.sqrt(total / math.pi) * 1000.0, floor,
                f"{ech or 'formation'} concentration area "
                f"{total:g} km2, derived from subordinate dispersion norms")
    f = _LEGACY_FRONTAGE_M.get(ech, 10000)
    return (f * 0.35, floor,
            f"{ech or 'unknown echelon'} assembly dispersion, "
            "planning default")


def _screen_norms_for(node_info: dict) -> Optional[Tuple[float, float, str]]:
    """(frontage_m, depth_m, provenance) for a screen/security posture,
    or None when no screen norm is stated for the echelon (caller
    carries the defense frontage instead, labeled)."""
    ech = node_info.get("ech") or ""
    friendly = node_info.get("aff") == "Friend"
    table, tag = ((_FRIENDLY_SCREEN_KM, "US cavalry screen planning norm")
                  if friendly
                  else (_THREAT_SCREEN_KM,
                        "threat reconnaissance-zone norm"))
    w = table.get(ech)
    if w is None:
        return None
    return w * 1000.0, w * 500.0, f"{ech} screen {tag}"


def proximity_bearing(lon: float, lat: float,
                      opposing_pts: List[Tuple[float, float]]) -> float:
    """Threat bearing (radians) from a formation toward the opposing
    force, PROXIMITY-WEIGHTED: the enemy a formation orients on is the
    one in front of it, not the average of every opposing element in
    theater (a flat centroid let home-station units a thousand km away
    drag a front-line formation's threat axis off the actual contact).
    Empty opposing set -> face east."""
    if not opposing_pts:
        return math.pi / 2
    coslat = max(0.2, math.cos(math.radians(lat)))
    wsum = wx = wy = 0.0
    for plon, plat in opposing_pts:
        dx = (plon - lon) * coslat
        dy = plat - lat
        d = math.hypot(dx, dy)
        if d < 1e-6:
            continue
        w = 1.0 / max(d, 0.1) ** 2       # near force dominates
        wsum += w
        wx += w * plon
        wy += w * plat
    if wsum == 0.0:
        return math.pi / 2
    ox, oy = wx / wsum, wy / wsum
    if abs(ox - lon) < 1e-6 and abs(oy - lat) < 1e-6:
        return math.pi / 2
    return math.atan2(ox - lon, oy - lat)


def _unit_frac(seed) -> float:
    """Deterministic per-unit dispersion in [-1, 1] — hash of the node
    id (or any stable seed), never randomness (reproducible arrays,
    identical on every consumer)."""
    import hashlib
    h = int(hashlib.md5(str(seed).encode()).hexdigest()[:8], 16)
    return (h % 1000) / 500.0 - 1.0


def plan_disposition(parent: dict, children: List[dict], *,
                     bearing_rad: float,
                     template_by_id: Optional[dict] = None,
                     assembly_poly: Optional[tuple] = None,
                     ) -> List[Tuple[dict, float, float, str, str]]:
    """THE pure layout core — one formation's subordinates arrayed as a
    doctrinal, threat-facing disposition. Shared verbatim by the
    instantiate-time engine (array_subordinates, which adds the land
    check and record writes) and the paint-time reference walk (which
    projects the same layout for derived subordinates without ever
    writing it) — one dialect of doctrine, never two.

    parent:   {"lon","lat","ech","aff","posture","template_id","name"}
    children: [{"id","name","ut","ech"}] — id is any stable hashable
              (node uuid or the walk's virtual id).
    assembly_poly: optional (name, shapely_polygon) clamping an
              assembly-posture dispersion to a drawn area.

    Returns [(child, lon, lat, slot_label, provenance_detail)].
    """
    template_by_id = template_by_id or {}
    mode = posture_mode(parent.get("posture"))
    brg = bearing_rad
    brg_deg = int(math.degrees(brg)) % 360

    by_role: Dict = {}
    for c in children:
        by_role.setdefault(role_class(c.get("name"), c.get("ut")),
                           []).append(c)

    candidates: List[Tuple[dict, float, float, str, str]] = []

    if mode == "assembly":
        # Concentration-area dispersion: a 2D cluster, NOT a frontage
        # line — combat has not started for a formation in an assembly
        # area. Maneuver inner, enablers middle, sustainment on the
        # outer ring; deterministic sunflower.
        child_echs = [c.get("ech") or "" for c in children]
        radius_m, floor_m, norm_src = _assembly_norms_for(parent, child_echs)
        n = len(children)
        if floor_m and n > 1:
            # Grow the ring before violating the stated minimum spacing
            # between companies in a marshaling area.
            radius_m = max(radius_m, floor_m * math.sqrt(n / math.pi))
        poly = poly_name = None
        if assembly_poly is not None:
            poly_name, poly = assembly_poly
        center = (parent["lon"], parent["lat"])
        if poly is not None:
            rp = poly.representative_point()
            center = (rp.x, rp.y)
            cc = poly.centroid
            coslat = max(0.2, math.cos(math.radians(cc.y)))
            poly_km2 = poly.area * 111.32 * coslat * 110.574
            poly_r = math.sqrt(max(poly_km2, 0.01) / math.pi) * 1000.0
            # The drawn area wins when smaller than doctrine.
            radius_m = min(radius_m, poly_r * 0.9)
        inner = [c for role, ms in by_role.items()
                 if role in _MANEUVER_ROLES for c in ms]
        middle = [c for role, ms in by_role.items()
                  if role not in _MANEUVER_ROLES
                  and role != "sustainment" for c in ms]
        ordered = inner + middle + by_role.get("sustainment", [])
        for j, c in enumerate(ordered):
            theta = j * _GOLDEN_ANGLE + 0.35 * _unit_frac(c["id"])
            r = radius_m * math.sqrt((j + 0.7) / max(1, len(ordered)))
            lon, lat = _offset(center[0], center[1], theta, r)
            clamp_note = ""
            if poly is not None:
                lon, lat, clamped = _clamp_into(poly, lon, lat, center)
                if clamped:
                    clamp_note = ", pulled inside the drawn area"
            detail = (f"dispersion radius {radius_m / 1000:.1f} km "
                      f"({norm_src})"
                      + (f", within {poly_name}" if poly_name else "")
                      + clamp_note)
            candidates.append((c, lon, lat,
                               f"assembly dispersion {j + 1} of "
                               f"{len(ordered)}", detail))

    elif mode == "march":
        # Column of march along the axis toward the threat, strung
        # rearward from the head at the parent's stated point.
        ordered: List[dict] = []
        for role in _MARCH_ORDER:
            ordered.extend(by_role.get(role, []))
        for role, ms in by_role.items():
            if role not in _MARCH_ORDER:
                ordered.extend(ms)
        n = len(ordered)
        cum_km = 0.0
        tail_started = False
        for j, c in enumerate(ordered):
            ech = c.get("ech") or ""
            length = _COLUMN_LENGTH_KM.get(ech, 0.5)
            if (not tail_started
                    and role_class(c.get("name"), c.get("ut"))
                    == "sustainment"):
                cum_km += _COLUMN_TRAIL_GAP_KM
                tail_started = True
            cum_km += length / 2.0
            lon, lat = _offset(parent["lon"], parent["lat"],
                               brg + math.pi, cum_km * 1000.0)
            lon, lat = _offset(lon, lat, brg + math.pi / 2,
                               40.0 * _unit_frac(c["id"]))
            derived = ("" if ech in _COLUMN_STATED_ECHELONS
                       else ", column length derived from "
                            "open-column density")
            detail = (f"march column, axis {brg_deg:03d} deg, "
                      f"doctrine column spacing{derived}")
            candidates.append((c, lon, lat,
                               f"march column slot {j + 1} of {n}",
                               detail))
            gap = (_COLUMN_GAP_MAJOR_KM
                   if ech in ("Battalion", "Squadron", "Regiment",
                              "Brigade", "Division", "Corps", "Army")
                   else _COLUMN_GAP_MINOR_KM)
            cum_km += length / 2.0 + gap

    else:
        # Frontage family: offense / defense / screen. A screen is the
        # same geometry stretched to the security frontage with ONE
        # thin echelon (the screen line) and recon ON the line.
        frontage_m, depth_m, norm_src = _norms_for(parent, template_by_id)
        if mode == "screen":
            sn = _screen_norms_for(parent)
            if sn is not None:
                frontage_m, depth_m, norm_src = sn
            else:
                norm_src += (" (no screen norm stated - defense "
                             "frontage carried)")
        # The parent's stated point is its CP, doctrinally in the rear
        # third — the FLOT trace sits forward of it toward the threat.
        flot = _offset(parent["lon"], parent["lat"], brg, depth_m * 0.35)

        def across(base, count, j, spread, c=None, depth_frac=0.0):
            # A frontage is an AREA, not a line: members slot across
            # the frontage AND disperse in depth — staggered alternates
            # plus a deterministic per-unit offset (doctrinal
            # dispersion; a straight file of icons is the tell that
            # depth collapsed).
            lat_off = (frontage_m * spread) * ((j - (count - 1) / 2.0) / max(1, count))
            lon0 = (base[0] + lat_off * math.sin(brg + math.pi / 2)
                    / (111320.0 * max(0.2, math.cos(math.radians(base[1])))))
            lat0 = base[1] + lat_off * math.cos(brg + math.pi / 2) / 111320.0
            if depth_frac and c is not None:
                stagger = 0.5 if (j % 2) else 0.0
                d_off = (stagger + 0.5 * _unit_frac(c["id"])) \
                    * depth_frac * depth_m
                lon0, lat0 = _offset(lon0, lat0, brg + math.pi, d_off)
                # A touch of frontage jitter so no two points are ever
                # collinear even within one stagger rank.
                f_off = 0.06 * frontage_m * _unit_frac((str(c["id"]), "f"))
                lon0 = (lon0 + f_off * math.sin(brg + math.pi / 2)
                        / (111320.0 * max(0.2, math.cos(math.radians(lat0)))))
                lat0 = lat0 + f_off * math.cos(brg + math.pi / 2) / 111320.0
            return (lon0, lat0)

        detail_common = (f"frontage {frontage_m / 1000:g} km / depth "
                         f"{depth_m / 1000:g} km ({norm_src}), threat "
                         f"axis {brg_deg:03d} deg")
        line_roles = set(_MANEUVER_ROLES)
        if mode == "screen":
            line_roles.add("recon")

        # Maneuver: two echelons — first echelon abreast ON the FLOT in
        # equal frontage sectors, second echelon behind at half depth.
        # A screen keeps everything on the one line.
        maneuver = [c for role, members in by_role.items()
                    if role in line_roles for c in members]
        if maneuver:
            if mode == "screen":
                first_n = len(maneuver)
            else:
                first_n = len(maneuver) if len(maneuver) <= 2 else (
                    2 if len(maneuver) <= 4 else 3)
            first, second = maneuver[:first_n], maneuver[first_n:]
            for j, c in enumerate(first):
                lon, lat = across(flot, len(first), j, 1.0, c, 0.12)
                candidates.append(
                    (c, lon, lat,
                     f"first echelon {j + 1} of {len(first)}",
                     detail_common))
            base2 = _offset(flot[0], flot[1], brg + math.pi,
                            depth_m * 0.5)
            for j, c in enumerate(second):
                lon, lat = across(base2, len(second), j, 0.6, c, 0.16)
                candidates.append(
                    (c, lon, lat,
                     f"second echelon {j + 1} of {len(second)}",
                     detail_common))

        for role, members in by_role.items():
            if role in line_roles:
                continue
            fwd, spread = _ROLE_OFFSETS.get(role, (-0.70, 0.60))
            base = _offset(flot[0], flot[1],
                           brg if fwd >= 0 else brg + math.pi,
                           abs(fwd) * depth_m)
            for j, c in enumerate(members):
                lon, lat = across(base, len(members), j, spread, c, 0.28)
                candidates.append((c, lon, lat,
                                   role or "general support",
                                   detail_common))

    return candidates


def _norms_for(node_info: dict, template_by_id: dict) -> Tuple[float, float, str]:
    """(frontage_m, depth_m, provenance) for a formation, by precedence:
    template row → force-appropriate echelon norms (friendly map for
    Friend, threat map otherwise, friendly falling through to threat
    where US doctrine states no value) → legacy table."""
    posture = (node_info.get("posture") or "").lower()
    offense = posture_mode(posture) == "offense"
    t = template_by_id.get(node_info.get("template_id"))
    if t is not None:
        f = (t.frontage_offense_km if offense else t.frontage_defense_km) \
            or t.frontage_defense_km or t.frontage_offense_km
        d = (t.depth_offense_km if offense else t.depth_defense_km) \
            or t.depth_defense_km or t.depth_offense_km
        if f:
            return (f * 1000.0, (d or f * 0.7) * 1000.0,
                    f"template {t.key}"
                    + (f" ({t.doctrine_source})" if t.doctrine_source else ""))
    ech = node_info.get("ech") or ""
    friendly = node_info.get("aff") == "Friend"
    # A friendly formation NEVER takes threat-doctrine values (user
    # ruling 2026-07-17): where US doctrine states no figure (BCT and
    # below — documented gaps), the neutral planning defaults apply,
    # labeled as such. The threat map serves Hostile/Unknown/Neutral.
    norms, tag = ((_FRIENDLY_ECHELON_NORMS, "US doctrine norm") if friendly
                  else (_THREAT_ECHELON_NORMS, "threat doctrine norm"))
    if ech in norms:
        fd, dd, fo, do = norms[ech]
        f, d = (fo, do) if offense else (fd, dd)
        return f * 1000.0, d * 1000.0, f"{ech} {tag}"
    f = _LEGACY_FRONTAGE_M.get(ech, 10000)
    label = ("US planning default (no doctrinal value stated)"
             if friendly else "planning default")
    return float(f), f * 0.7, f"{ech or 'unknown echelon'} {label}"


async def array_subordinates(
    db: AsyncSession, project_id: UUID, re_array: bool = False,
    root_node_id: Optional[UUID] = None,
) -> dict:
    """Array every unplaced subordinate of every placed formation as a
    doctrinal, threat-facing, land-checked disposition. Recurses down
    the hierarchy (a first-echelon brigade placed this pass anchors its
    own battalions next). Only fills units with NO stated position.
    The formation's POSTURE selects the array shape: combat postures
    array across the doctrinal frontage; assembly/staging postures
    disperse in a concentration area (clamped to a drawn assembly-area
    polygon when the parent sits inside one); march postures string a
    column along the axis of movement; screen postures stretch a thin
    single echelon across the security frontage.

    re_array=True additionally re-synthesizes units whose CURRENT
    position came from a previous doctrinal-disposition pass (their
    governing observation's source says so) — norms/engine updates
    re-apply without ever touching a document-stated placement.

    root_node_id scopes the pass to ONE formation's subtree (the
    placard's posture selector re-arrays just that formation); the
    root's own position is never cleared — it anchors the array."""
    rows = (await db.execute(select(
        GraphNode.id, GraphNode.organic_parent_id, GraphNode.echelon,
        GraphNode.affiliation, GraphNode.name, GraphNode.unit_type,
        GraphNode.template_id, GraphNode.posture, GraphNode.entity_type,
        func.ST_X(func.ST_Centroid(GraphNode.geom)),
        func.ST_Y(func.ST_Centroid(GraphNode.geom)),
    ).where(GraphNode.project_id == project_id))).all()
    info = {r[0]: {"parent": r[1], "ech": r[2], "aff": r[3], "name": r[4],
                   "ut": r[5], "template_id": r[6], "posture": r[7],
                   "etype": r[8], "lon": r[9], "lat": r[10]}
            for r in rows}
    kids: Dict = {}
    for r in rows:
        if r[1] is not None:
            kids.setdefault(r[1], []).append(r[0])

    scope = None
    if root_node_id is not None:
        if root_node_id not in info:
            return {"synthesized_positions": 0, "skipped_water": [],
                    "error": "root node not in project"}
        scope = set()
        stack = [root_node_id]
        while stack:
            nid = stack.pop()
            if nid in scope:
                continue
            scope.add(nid)
            stack.extend(kids.get(nid, []))

    if re_array:
        from app.models.graph import GraphNodePosition
        eff = func.coalesce(GraphNodePosition.observed_at,
                            GraphNodePosition.created_at)
        newest_src = (await db.execute(
            select(GraphNodePosition.node_id, GraphNodePosition.source)
            .where(GraphNodePosition.node_id.in_(
                list(scope if scope is not None else info)))
            .order_by(GraphNodePosition.node_id, eff.desc()))).all()
        seen = set()
        for nid, src in newest_src:
            if nid in seen:
                continue
            seen.add(nid)
            if nid == root_node_id:
                continue                     # the root anchors the array
            if (src or "").startswith("doctrinal disposition"):
                info[nid]["lon"] = None
                info[nid]["lat"] = None

    template_ids = {v["template_id"] for v in info.values() if v["template_id"]}
    template_by_id = {}
    if template_ids:
        template_by_id = {t.id: t for t in (await db.execute(
            select(ForceTemplate).where(ForceTemplate.id.in_(template_ids))
        )).scalars().all()}

    # Drawn assembly-area polygons — an assembly-posture formation whose
    # parent point sits inside one gets its dispersion CLAMPED to the
    # drawn area (the drawn area wins over the doctrinal figure when
    # smaller; dispersed points never spill outside the ring).
    assembly_polys: List[Tuple[str, object]] = []
    try:
        import json as _json
        from shapely.geometry import shape as _shape
        poly_rows = (await db.execute(select(
            GraphNode.name, func.ST_AsGeoJSON(GraphNode.geom))
            .where(GraphNode.project_id == project_id,
                   GraphNode.entity_type == "assembly_area",
                   GraphNode.geom.isnot(None)))).all()
        for pname, gj in poly_rows:
            if not gj:
                continue
            g = _shape(_json.loads(gj))
            if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty:
                assembly_polys.append((pname, g))
    except Exception:                       # fail open: no clamp, arrays land
        assembly_polys = []

    # Each side faces the opposing force — proximity_bearing (the pure
    # core) does the weighting; this just gathers each side's points.
    opp_pts: Dict = {}
    for aff in ("Friend", "Hostile"):
        opp_pts[aff] = [(v["lon"], v["lat"]) for v in info.values()
                        if v["aff"] == aff and v["lon"] is not None]

    def threat_bearing(lon, lat, aff):
        return proximity_bearing(
            lon, lat, opp_pts.get("Hostile" if aff == "Friend" else "Friend")
            or [])

    placed_count = 0
    skipped_water: List[str] = []
    order: List[UUID] = []                            # BFS from placed roots

    if root_node_id is not None:
        if info[root_node_id]["lon"] is not None:
            order.append(root_node_id)
    else:
        for r in rows:
            # Seed: every PLACED node whose parent cannot anchor it — no
            # parent, parent outside the project, or parent UNPLACED (an
            # army under an unplaced alliance/political node must still
            # anchor its own subtree; seeding only true roots left every
            # formation under an unplaced coalition un-arrayed).
            parent_placed = (r[1] is not None and r[1] in info
                             and info[r[1]]["lon"] is not None)
            if not parent_placed and info[r[0]]["lon"] is not None:
                order.append(r[0])
    qi = 0
    while qi < len(order):
        pid = order[qi]; qi += 1
        p = info[pid]
        ch = kids.get(pid, [])
        # Units only — a battle position's "children" are not a formation.
        unplaced = [k for k in ch
                    if info[k]["lon"] is None and info[k]["etype"] == "unit"]
        order.extend(ch)
        if p["lon"] is None or not unplaced:
            continue

        mode = posture_mode(p["posture"])
        brg = threat_bearing(p["lon"], p["lat"], p["aff"])

        # Assembly-posture clamp: the drawn area the parent sits inside.
        assembly_clamp = None
        if mode == "assembly":
            try:
                from shapely.geometry import Point as _Point
                for nm, g in assembly_polys:
                    if g.contains(_Point(p["lon"], p["lat"])):
                        assembly_clamp = (nm, g)
                        break
            except Exception:
                assembly_clamp = None

        children = [{"id": k, "name": info[k]["name"], "ut": info[k]["ut"],
                     "ech": info[k]["ech"]} for k in unplaced]
        planned = plan_disposition(
            p, children, bearing_rad=brg, template_by_id=template_by_id,
            assembly_poly=assembly_clamp)
        # (node id, lon, lat, slot label, provenance detail)
        candidates = [(c["id"], lon, lat, slot, detail)
                      for c, lon, lat, slot, detail in planned]

        checked = await ensure_on_land(
            [(lon, lat) for _, lon, lat, _, _ in candidates])
        placed_for_parent = 0
        for (k, _, _, slot, detail), (lon, lat, moved) in zip(candidates,
                                                              checked):
            if moved == -1.0:
                skipped_water.append(info[k]["name"])
                continue
            nudge_note = (f", nudged {moved:g} km to nearest land"
                          if moved else "")
            node = await db.get(GraphNode, k)
            if node is None:
                continue
            await record_position(
                db, node, lon=lon, lat=lat,
                activity=f"doctrinal disposition - {slot} of {p['name']}",
                source=(f"doctrinal disposition: {slot} of {p['name']}, "
                        f"{detail}, land-checked{nudge_note}"),
                created_by="_autodraft", land_checked=True)
            info[k]["lon"], info[k]["lat"] = lon, lat
            placed_count += 1
            placed_for_parent += 1

        # The EFFECTIVE posture is a fact about the formation the moment
        # its array is drawn at that posture's shape — posture_mode's
        # fallback made a null-posture formation array at defense while
        # its record (and placard) claimed no posture existed. Persist
        # the posture the engine actually used whenever it arrayed this
        # formation and the node carried none.
        if placed_for_parent and not (p["posture"] or "").strip():
            parent_node = await db.get(GraphNode, pid)
            if parent_node is not None and not (
                    parent_node.posture or "").strip():
                parent_node.posture = ("attack" if mode == "offense"
                                       else mode)
                info[pid]["posture"] = parent_node.posture

    if placed_count:
        await db.commit()
    return {"synthesized_positions": placed_count,
            "skipped_water": skipped_water}
