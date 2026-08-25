"""Deterministic ingest core: canonical ExtractedOOB → graph rows.

No LLM here. Two-pass entity resolution (create, then link parents by
ref), catalog-alias holdings resolution, registry-checked types and
relationships, MGRS→lat/lon conversion, and a full IngestReport. This
is the stable unit every extractor feeds and the DAG/agent depends on.
"""
import logging
import uuid as uuid_mod
from typing import Dict

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import (
    AFFILIATIONS, CATEGORIES, ECHELONS, ForceTemplate, GraphEdge,
    GraphHolding, GraphNode,
)
from app.models.reference import (
    EntityType, RelationshipType, WegEquipment, WegEquipmentAlias,
)
from app.services.graph_ingest.schema import ExtractedOOB, IngestReport
from app.services.graph_ingest.track import record_position
from app.utils.mgrs_utils import is_mgrs_string, mgrs_to_latlng

log = logging.getLogger(__name__)


def shape_wkt(ent) -> "str | None":
    """LINESTRING/POLYGON WKT from resolved control-measure vertices
    (polygon ring closed automatically)."""
    if getattr(ent, "line_coords", None):
        pts = ", ".join(f"{c[0]} {c[1]}" for c in ent.line_coords)
        return f"LINESTRING({pts})"
    if getattr(ent, "area_coords", None):
        ring = list(ent.area_coords)
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
        return f"POLYGON(({pts}))"
    return None


async def _record_track(db, node, ent, *, source, created_by,
                        report=None) -> int:
    """Write an entity's positions through the ONE write surface: every
    dated track observation (oldest → newest), then the current position
    when it is not already the track's newest point. A single-position
    entity gets exactly one observation — same path, no special case.
    Control-measure shapes ride the same surface as one observation.

    A REJECTED observation (unparseable stated DTG, unanchored relative
    time — track.py's time contract) occupies its own slot: it lands as
    a report note naming the entity and the raw error, and the rest of
    the track writes. The document ingest never aborts wholesale on one
    bad time; the note is the repair signal."""
    def _note(e):
        if report is not None:
            report.notes.append(f"{node.name}: position rejected — {e}")
    wkt = shape_wkt(ent)
    if wkt is not None:
        await record_position(
            db, node, geom_wkt=wkt,
            location_text=ent.location_text, activity=ent.posture,
            source=source, created_by=created_by)
        return 1
    written = 0
    last_coord = None
    for p in ent.positions:
        if p.lon is None and not p.mgrs and not p.location_text:
            continue
        # Per-observation citation wins over the bundle label — the
        # placard must name the document and entry, never "it's in
        # there somewhere" (user ruling 2026-07-17).
        try:
            await record_position(
                db, node, lon=p.lon, lat=p.lat, mgrs=p.mgrs,
                location_text=p.location_text, dtg=p.dtg,
                activity=p.activity,
                source=(getattr(p, "source", None) or source),
                created_by=created_by)
        except ValueError as e:
            _note(e)
            continue
        written += 1
        if p.lon is not None:
            last_coord = (p.lon, p.lat)
    if (ent.lon is not None and ent.lat is not None
            and (last_coord is None
                 or abs(last_coord[0] - ent.lon) > 1e-9
                 or abs(last_coord[1] - ent.lat) > 1e-9)):
        try:
            await record_position(
                db, node, lon=ent.lon, lat=ent.lat, mgrs=ent.mgrs,
                location_text=ent.location_text, activity=ent.posture,
                source=(getattr(ent, "position_source", None) or source),
                created_by=created_by)
            written += 1
        except ValueError as e:
            _note(e)
    return written


async def resolve_template(db, ref: str):
    """A template by exact key, else by NAME (fold-insensitive) — the
    name is the published handle; keys derive from names. Ambiguous name
    → (None, candidates) so the caller can say which keys collide."""
    tpl = (await db.execute(select(ForceTemplate).where(
        ForceTemplate.key == ref))).scalar_one_or_none()
    if tpl is not None:
        return tpl, []
    want = _norm_name(ref)
    rows = (await db.execute(select(ForceTemplate))).scalars().all()
    hits = [t for t in rows if _norm_name(t.name) == want]
    if len(hits) == 1:
        return hits[0], []
    return None, hits


_AGGREGATE_RE = None  # compiled below with re import


def _parse_aggregate(name):
    """'Missile Battalion (x3)' -> ('Missile Battalion', 3).
    'Missile Battalion (2)' (numbered-sibling notation for explicit
    identical rows) -> ('Missile Battalion', 1) — the index is sibling
    disambiguation, not identity, so all numbered rows share a class."""
    import re
    m = re.search(r"\s*\((?:x|\u00d7)\s*(\d+)\)\s*$", name or "",
                  re.IGNORECASE)
    base = re.sub(r"\s*\((?:x|\u00d7)\s*\d+\)\s*$", "", name or "",
                  flags=re.IGNORECASE).strip()
    count = int(m.group(1)) if m else 1
    if not m:
        base = re.sub(r"\s*\(\d+\)\s*$", "", base).strip()
    return base, count


# Battalion-equivalents and company-equivalents count as the same slot
# (a documented Squadron consumes a template Battalion node).
_ECHELON_EQUIV = {"Squadron": "Battalion", "Troop": "Company",
                  "Battery": "Company"}

# Generic structure words carry no matching signal — matching keys on
# the FUNCTION words of a template node's name (missile, tank, signal).
# Doctrinal abbreviations whose expansion a documented designation may
# use instead ("SPF Battalion" slot <- "1st Special Purpose Forces
# Battalion").
_TOKEN_ALIASES = {"spf": "special purpose", "ssm": "missile",
                  "at": "antitank", "adа": "air defense",
                  "recon": "reconnaissance"}

_GENERIC_TOKENS = {
    "battalion", "regiment", "brigade", "company", "platoon", "battery",
    "squadron", "troop", "section", "detachment", "group", "and", "of",
    "the", "task", "organized", "support", "hq", "headquarters", "staff",
}


def _merge_match(existing, tpl_child, tpl_base):
    """Does a documented child fill this template node's slot? Echelon
    must agree (with battalion/company equivalents) when both are
    stated; the FUNCTION must agree via unit_type equality or a
    function-word overlap between the template node's name and the
    documented child's name."""
    ech_e = _ECHELON_EQUIV.get(existing.echelon, existing.echelon)
    ech_t = _ECHELON_EQUIV.get(tpl_child.echelon, tpl_child.echelon)
    if ech_e and ech_t and ech_e != ech_t:
        return False
    if existing.unit_type and tpl_child.unit_type:
        if existing.unit_type == tpl_child.unit_type:
            return True
    tokens = {t for t in tpl_base.lower().replace("-", " ").replace(
        "(", " ").replace(")", " ").split() if t not in _GENERIC_TOKENS}
    if not tokens:
        # No function signal on the template node — echelon agreement
        # (checked above) is the whole test.
        return bool(ech_e and ech_t)
    name = (existing.name or "").lower()
    return any(t in name
               or (t in _TOKEN_ALIASES and _TOKEN_ALIASES[t] in name)
               for t in tokens)


async def _apply_template_holdings(db, tpl_node_id, existing_child) -> int:
    """Template equipment is the default a unit ALWAYS has: copy the
    template node's holdings onto the documented child that consumed
    its slot, except systems the child already states (source counts
    win, doctrine fills the rest). A child whose source stated its
    COMPLETE equipment table (holdings_complete) gets nothing — a full
    MTOE replaces the doctrinal defaults outright. Returns holdings
    added."""
    if getattr(existing_child, "holdings_complete", False):
        return 0
    tpl_holdings = (await db.execute(select(GraphHolding).where(
        GraphHolding.node_id == tpl_node_id))).scalars().all()
    if not tpl_holdings:
        return 0
    have = (await db.execute(select(GraphHolding).where(
        GraphHolding.node_id == existing_child.id))).scalars().all()
    have_keys = {(h.weg_id or (h.nomenclature_raw or "").lower())
                 for h in have}
    added = 0
    for h in tpl_holdings:
        key = h.weg_id or (h.nomenclature_raw or "").lower()
        if key in have_keys:
            continue
        db.add(GraphHolding(
            node_id=existing_child.id, weg_id=h.weg_id,
            nomenclature_raw=h.nomenclature_raw,
            count_authorized=h.count_authorized,
            count_current=h.count_current,
            created_by=existing_child.created_by or "_template",
        ))
        added += 1
    return added


async def apply_template(db, node, template_key: str, report: IngestReport,
                         *, created_by: str) -> bool:
    """Instantiate a force template's standard structure as the unit's
    subtree (OPORD names the unit → the template fills its TO&E).

    Documented subordinates OVERRIDE the template's generic nodes for
    the parts the source states; the template fills the REST: each
    documented child consumes a matching template slot (echelon
    equivalence + function match) and inherits that slot's default
    equipment (source-stated holdings win per system); only UNMATCHED
    template nodes are instantiated. A bare unit gets the whole
    template, exactly as before. Shared by the bulk ingest and the
    upsert_unit agent tool; takes the template NAME or key."""
    from app.api.v1.graph import _copy_subtree  # lazy: avoid import cycle
    tpl, collisions = await resolve_template(db, template_key)
    if tpl is None and collisions:
        report.notes.append(
            f"template name '{template_key}' is ambiguous for {node.name} — "
            "matching keys: " + ", ".join(t.key for t in collisions))
        return False
    if tpl is None or tpl.root_node_id is None:
        report.notes.append(f"template '{template_key}' not found for {node.name}")
        return False
    existing = (await db.execute(select(GraphNode).where(
        GraphNode.organic_parent_id == node.id))).scalars().all()
    tpl_children = (await db.execute(select(GraphNode).where(
        GraphNode.organic_parent_id == tpl.root_node_id))).scalars().all()

    if not existing:
        # Bare formation — whole-template fast path (unchanged).
        new_root = await _copy_subtree(
            db, tpl.root_node_id, project_id=node.project_id,
            affiliation=node.affiliation, created_by=created_by)
        root_copy = await db.get(GraphNode, new_root)
        for child in (await db.execute(select(GraphNode).where(
                GraphNode.organic_parent_id == new_root))).scalars().all():
            child.organic_parent_id = node.id
        await db.delete(root_copy)
        # Equipment stated on the template ROOT belongs to the anchor
        # unit itself (root-only templates carry the whole fleet there;
        # deleting the root copy must not drop it).
        await _apply_template_holdings(db, tpl.root_node_id, node)
        # Provenance: which template filled this unit's TO&E (clones
        # can't carry template_id — ck_graph_nodes_one_scope — so the
        # anchor keeps the key).
        node.template_key = tpl.key
        await _designate_instantiated(db, node)
        report.templates_filled += 1
        return True

    # PARTIAL FILL. The template is the DEFAULT: "this formation
    # usually has N of these, with this equipment." Per template child
    # class:
    #   - the source ENUMERATED units of this class -> the source's
    #     number IS the number (two documented battalions means two,
    #     never topped up to the doctrinal three); each documented unit
    #     gets the class's default equipment layered underneath its own
    #     statements (full-MTOE children get nothing).
    #   - the source said NOTHING about this class -> the template's
    #     default count instantiates in full.
    # Templates express a repeated class EITHER as one aggregate row
    # ("Missile Battalion (x3)") OR as N explicit sibling rows (three
    # "Missile Battalion" nodes) — group rows into CLASSES first, so a
    # source-enumerated class suppresses EVERY row of that class, not
    # just the first one matched.
    classes = {}
    for tc in tpl_children:
        base, count = _parse_aggregate(tc.name)
        key = (base.lower(),
               _ECHELON_EQUIV.get(tc.echelon, tc.echelon),
               tc.unit_type)
        classes.setdefault(key, {"base": base, "rows": []})
        classes[key]["rows"].append((tc, count))

    unconsumed = list(existing)
    source_stated = 0
    instantiated = 0
    holdings_applied = 0
    new_roots = []
    for cls in classes.values():
        rep, _ = cls["rows"][0]
        base = cls["base"]
        matches = [ec for ec in unconsumed if _merge_match(ec, rep, base)]
        if matches:
            # The source enumerated this class: its number IS the
            # number. Default equipment (from a representative row)
            # layers under each documented unit's own statements.
            for ec in matches:
                unconsumed.remove(ec)
                holdings_applied += await _apply_template_holdings(
                    db, rep.id, ec)
            source_stated += len(matches)
            continue
        # Class unstated by the source: full doctrinal strength.
        for tc, count in cls["rows"]:
            new_id = await _copy_subtree(
                db, tc.id, project_id=node.project_id,
                affiliation=node.affiliation, created_by=created_by)
            nc = await db.get(GraphNode, new_id)
            nc.organic_parent_id = node.id
            new_roots.append(new_id)
            instantiated += count
    # Root-level template equipment layers onto the anchor itself.
    holdings_applied += await _apply_template_holdings(
        db, tpl.root_node_id, node)
    node.template_key = tpl.key
    if new_roots:
        await _designate_instantiated(db, node, roots=new_roots)
    if new_roots or holdings_applied:
        report.templates_filled += 1
        report.notes.append(
            f"template merged into {node.name}: {source_stated} documented "
            "children kept as the source-stated strength for their "
            f"classes, {instantiated} doctrinal units instantiated for "
            f"classes the source did not mention, {holdings_applied} "
            "default holdings layered under documented children")
        return True
    report.notes.append(
        f"template '{tpl.key}' fully covered by documented children of "
        f"{node.name} — nothing instantiated")
    return False


async def _designate_instantiated(db, anchor, roots=None) -> None:
    """Make template-instantiated subordinates READABLE on a map:

    1. Aggregate rows expand — a doctrinal body row like "Combined Arms
       Battalion (x3)" becomes three sibling nodes, ordinally
       designated ("1st/2nd/3rd Combined Arms Battalion, ...").
    2. Every instantiated node gets the anchor formation's designation
       suffixed ("Cavalry Squadron, 1st Armored Brigade Combat Team") —
       a bare doctrinal noun repeated at every echelon of a real OOB is
       unreadable (user ruling 2026-07-17). Ordinals and suffixes are
       DERIVED labels for doctrinal structure the template invented;
       document-stated designators (e.g. 1-7 Cavalry) are applied by
       rename afterward and win.

    roots=None (whole-template fill): every organic descendant of the
    anchor is a clone — walk them all. roots=[ids] (partial fill): ONLY
    the newly instantiated subtrees are clones — documented children
    keep their document-stated names untouched."""
    import re
    if roots is None:
        pending = list((await db.execute(select(GraphNode).where(
            GraphNode.organic_parent_id == anchor.id))).scalars().all())
    else:
        pending = [await db.get(GraphNode, r) for r in roots]
    while pending:
        kids, pending = pending, []
        for child in kids:
            pending.extend((await db.execute(select(GraphNode).where(
                GraphNode.organic_parent_id == child.id))).scalars().all())
            m = re.search(r"\s*\((?:x|×)\s*(\d+)\)\s*$",
                          child.name or "", re.IGNORECASE)
            base = re.sub(r"\s*\((?:x|×)\s*\d+\)\s*$", "",
                          child.name or "", flags=re.IGNORECASE).strip()
            if m and int(m.group(1)) > 1:
                count = int(m.group(1))
                ordinals = ["1st", "2nd", "3rd", "4th", "5th", "6th",
                            "7th", "8th", "9th", "10th"]
                child.name = (f"{ordinals[0]} {base}, {anchor.name}")
                for i in range(1, min(count, len(ordinals))):
                    sibling = GraphNode(
                        id=uuid_mod.uuid4(), project_id=child.project_id,
                        entity_type=child.entity_type,
                        name=f"{ordinals[i]} {base}, {anchor.name}",
                        affiliation=child.affiliation,
                        echelon=child.echelon, unit_type=child.unit_type,
                        category=child.category,
                        organic_parent_id=child.organic_parent_id,
                        personnel_authorized=child.personnel_authorized,
                        personnel_current=child.personnel_current,
                        created_by=child.created_by,
                    )
                    db.add(sibling)
                    await db.flush()
                    for h in (await db.execute(select(GraphHolding).where(
                            GraphHolding.node_id == child.id))).scalars().all():
                        db.add(GraphHolding(
                            node_id=sibling.id, weg_id=h.weg_id,
                            nomenclature_raw=h.nomenclature_raw,
                            count_authorized=h.count_authorized,
                            count_current=h.count_current,
                            created_by=h.created_by,
                        ))
            else:
                sib = re.search(r"\s*\((\d+)\)\s*$", base)
                if sib:
                    idx = int(sib.group(1))
                    stem = re.sub(r"\s*\(\d+\)\s*$", "", base).strip()
                    ordn = ("1st", "2nd", "3rd")[idx - 1] if idx <= 3 \
                        else f"{idx}th"
                    child.name = f"{ordn} {stem}, {anchor.name}"
                else:
                    child.name = f"{base}, {anchor.name}"
    await db.flush()


import re as _re

# US-Army-styled ordinals ("2d", "3d", "173d") normalize to standard
# English ordinals — ONE canonical rendering per designation (decision
# spec: style variants across documents would split name-identity
# dedup, and a driver must never deliberate the style).
_ORDINAL_D = _re.compile(r"\b(\d*[23])d\b", _re.IGNORECASE)


def normalize_designation(v):
    if not v:
        return v
    return _ORDINAL_D.sub(
        lambda m: m.group(1) + ("nd" if m.group(1).endswith("2") else "rd"), v)


def _norm_name(v: str) -> str:
    """Fold a name for in-batch duplicate detection — case/space/
    punctuation-insensitive, ordinal-style-insensitive ("2d" == "2nd").
    Catches a unit restated verbatim; genuine abbreviation variants are
    consolidated upstream by the extractor."""
    v = normalize_designation(v or "")
    return _re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()


def _norm_affiliation(v: str) -> str:
    v = (v or "").strip().title()
    return v if v in AFFILIATIONS else "Unknown"


# Doctrinal-equivalent aliases into the closed echelon set — a driver
# must never have to decide that a cavalry squadron is battalion-echelon
# (trace-driven spec: scratch/docs/oob/extraction-decision-spec.md).
_ECHELON_ALIASES = {
    "Squadron": "Battalion",
    "Troop": "Company",
    "Battery": "Company",
}


def _norm_echelon(v):
    if not v:
        return None
    v = str(v).strip().title()
    v = _ECHELON_ALIASES.get(v, v)
    return v if v in ECHELONS else None


def _norm_category(v):
    if not v:
        return None
    v = str(v).strip().lower().replace(" ", "_")
    return v if v in CATEGORIES else None


def _geom(lon, lat):
    if lon is None or lat is None:
        return None
    return WKTElement(f"POINT({lon} {lat})", srid=4326)


async def _resolve_coord(ent):
    """lon/lat wins; else MGRS; else unplaced. Returns (lon, lat)."""
    if ent.lon is not None and ent.lat is not None:
        return ent.lon, ent.lat
    if ent.mgrs and is_mgrs_string(ent.mgrs):
        try:
            lat, lon = mgrs_to_latlng(ent.mgrs)
            return lon, lat
        except Exception:
            return None, None
    return None, None


_EFFECTIVENESS_FROM_STATUS = {
    "destroyed": "destroyed", "combat ineffective": "ineffective",
    "ineffective": "ineffective", "degraded": "degraded",
    "attrited": "degraded", "withdrawn": "destroyed",
}


async def ingest_oob(
    db: AsyncSession,
    project_id,
    oob: ExtractedOOB,
    *,
    created_by: str = "_ingest",
    default_entity_type: str = "unit",
) -> IngestReport:
    """CRUD `oob` into the project's graph. Commits once.

    Two document kinds (oob.document_kind):
    - "oob" (default): create new entities. Idempotency is the caller's
      concern (wipe first for a clean re-ingest).
    - "frago": UPDATE mode. Match each extracted entity against an
      existing in-project entity by name (case-insensitive) and apply
      deltas — re-task, reposition, attrition, holdings changes —
      instead of creating a duplicate. Unmatched entities are created.
    """
    report = IngestReport()

    valid_types = {t for t in (await db.execute(
        select(EntityType.type_key))).scalars().all()}
    valid_rels = {t for t in (await db.execute(
        select(RelationshipType.type_key))).scalars().all()}

    # ONE ingest path (no frago fork): every document may both enrich
    # units that already exist (matched by name, append-only semantics)
    # and deploy units that do not. document_kind is provenance only.
    existing_by_name: Dict[str, GraphNode] = {}
    for n in (await db.execute(select(GraphNode).where(
            GraphNode.project_id == project_id))).scalars().all():
        existing_by_name.setdefault((n.name or "").strip().lower(), n)

    # ── Pass 1: entities (no parents yet) ────────────────────────────
    by_ref: Dict[str, GraphNode] = {}
    seen_by_name: Dict[str, GraphNode] = {}   # dedupe key: folded name

    unknown_types = set()
    for ent in oob.entities:
        etype = ent.entity_type if ent.entity_type in valid_types else default_entity_type
        if ent.entity_type not in valid_types and ent.entity_type != "unit":
            unknown_types.add(ent.entity_type)
        lon, lat = await _resolve_coord(ent)

        # A unit restated under the same name — in this document OR an
        # earlier scenario doc — is ONE entity. Reuse the node (edges/
        # parents resolve to it) and ENRICH the fields a later doc fills
        # in; never create a duplicate.
        # In-batch restatement: the same document(s) naming a unit twice
        # is ONE entity — enrich identity gaps, append positions.
        dup = seen_by_name.get(_norm_name(ent.name))
        if dup is not None:
            if ((lon is not None and dup.geom is None) or ent.positions
                    or shape_wkt(ent)):
                report.positions_recorded += await _record_track(
                    db, dup, ent, source=oob.source_label,
                    created_by=created_by, report=report)
            if not dup.echelon and _norm_echelon(ent.echelon):
                dup.echelon = _norm_echelon(ent.echelon)
            if not dup.unit_type and ent.unit_type:
                dup.unit_type = ent.unit_type
            if dup.affiliation in (None, "Unknown") and \
                    _norm_affiliation(ent.affiliation) != "Unknown":
                dup.affiliation = _norm_affiliation(ent.affiliation)
            by_ref[ent.ref] = dup
            continue

        match = existing_by_name.get((ent.name or "").strip().lower())
        if match is not None:
            # Existing-unit enrichment (unified path, no mode): the doc's
            # statements are observations — positions APPEND to the track,
            # state attributes go through record_attribute; history is
            # never overwritten.
            if lon is not None or ent.positions or shape_wkt(ent):
                report.positions_recorded += await _record_track(
                    db, match, ent, source=oob.source_label or "FRAGO",
                    created_by=created_by, report=report)
            # APPEND-ONLY DISCIPLINE (world model, principle 6): a doc's
            # statements about an existing unit are OBSERVATIONS — they
            # land as episodic clauses (the register) and as appended
            # positions, never as silent overwrites of curated state.
            # Scalar columns FILL IF NULL only; a stated value that
            # conflicts with a curated one stays visible in the placard
            # History instead of destroying the curated value.
            # STATE attributes land as OBSERVATIONS (append-only chain,
            # column mirrors the current value): a later doc's statement
            # supersedes properly; curated values survive as history.
            from app.services.attribute_observations import (
                record_attribute,
            )
            _doc_src = oob.source_label or "document ingest"
            if ent.posture is not None:
                await record_attribute(
                    db, match, "posture", ent.posture,
                    speaker="document", source=_doc_src)
            if match.echelon is None and _norm_echelon(ent.echelon):
                match.echelon = _norm_echelon(ent.echelon)
            if ent.unit_type is not None and match.unit_type is None:
                match.unit_type = ent.unit_type
            if ent.personnel_current is not None:
                await record_attribute(
                    db, match, "personnel_current", ent.personnel_current,
                    speaker="document", source=_doc_src)
            if match.affiliation in (None, "Unknown") and \
                    ent.affiliation and \
                    _norm_affiliation(ent.affiliation) != "Unknown":
                match.affiliation = _norm_affiliation(ent.affiliation)
            if ent.significance in ("high", "medium", "low"):
                await record_attribute(
                    db, match, "significance", ent.significance,
                    speaker="document", source=_doc_src)
            if ent.status:
                eff = _EFFECTIVENESS_FROM_STATUS.get(ent.status.strip().lower())
                if eff:
                    await record_attribute(
                        db, match, "combat_effectiveness", eff,
                        speaker="document", source=_doc_src,
                        text=f"{match.name} combat effectiveness assessed "
                             f"as {eff} ({ent.status}).")
            if ent.notes:
                match.notes = ((match.notes or "") + f" [update: {ent.notes}]").strip()
            if ent.holdings_complete:
                match.holdings_complete = True
            node = match
            report.entities_updated += 1
        else:
            if lon is None and shape_wkt(ent) is None:
                report.entities_unplaced += 1
            node = GraphNode(
                id=uuid_mod.uuid4(), project_id=project_id,
                entity_type=etype, name=ent.name or "unnamed",
                affiliation=_norm_affiliation(ent.affiliation),
                category=_norm_category(ent.category),
                geom=_geom(lon, lat),
                posture=ent.posture, unit_type=ent.unit_type,
                echelon=_norm_echelon(ent.echelon),
                personnel_authorized=ent.personnel_authorized,
                personnel_current=ent.personnel_current,
                holdings_complete=ent.holdings_complete,
                significance=(ent.significance if ent.significance in ("high", "medium", "low") else None),
                significance_note=ent.significance_note,
                notes=ent.notes if not ent.location_text else
                      ((ent.notes or "") + f" [location: {ent.location_text}]").strip(),
                created_by=created_by,
            )
            if ent.status:
                eff = _EFFECTIVENESS_FROM_STATUS.get(ent.status.strip().lower())
                if eff:
                    node.combat_effectiveness = eff
            db.add(node)
            report.entities_created += 1
            seen_by_name[_norm_name(ent.name)] = node
            # Every placement is an append-only observation on the unit's
            # track (road-to-war timelines arrive as positions[]; a single
            # stated position is a one-point track). The newest mirrors to
            # node.geom — the current laydown the map paints.
            if lon is not None or ent.positions or shape_wkt(ent):
                report.positions_recorded += await _record_track(
                    db, node, ent, source=oob.source_label,
                    created_by=created_by, report=report)
        by_ref[ent.ref] = node

        # Holdings, deduped by resolved weg_id on this node (the unique
        # (node_id, weg_id) constraint + §3.3 merge). On a FRAGO match,
        # seed the merge map with the node's EXISTING resolved holdings
        # so a doc that restates a system UPDATES its counts in place.
        resolved_here: Dict[str, GraphHolding] = {}
        if match is not None and ent.holdings:
            for eh in (await db.execute(select(GraphHolding).where(
                    GraphHolding.node_id == node.id,
                    GraphHolding.weg_id.isnot(None)))).scalars().all():
                resolved_here[eh.weg_id] = eh
        for h in ent.holdings:
            weg_id = await _resolve_nomenclature(db, h.nomenclature)
            if weg_id and weg_id in resolved_here:
                prior = resolved_here[weg_id]
                # FRAGO restatement replaces counts; OOB accumulates.
                for a, b in (("count_authorized", h.count_authorized),
                             ("count_current", h.count_current)):
                    if b is None:
                        continue
                    cur = getattr(prior, a)
                    # A later doc restating a holding count states the
                    # CURRENT count (observation), never an addition.
                    setattr(prior, a, b)
                continue
            holding = GraphHolding(
                id=uuid_mod.uuid4(), node_id=node.id,
                weg_id=weg_id, nomenclature_raw=h.nomenclature,
                count_authorized=h.count_authorized,
                count_current=h.count_current, created_by=created_by)
            db.add(holding)
            if weg_id:
                resolved_here[weg_id] = holding
                report.holdings_resolved += 1
            else:
                report.holdings_unresolved += 1
            report.holdings_created += 1

    report.unknown_entity_types = sorted(unknown_types)

    # Persist nodes+holdings before edges/parents reference their ids
    # (edges and organic_parent_id FK graph_nodes.id).
    await db.flush()

    # ── Pass 2: parents ──────────────────────────────────────────────
    for ent in oob.entities:
        if not ent.parent_ref:
            continue
        parent = by_ref.get(ent.parent_ref)
        if parent is None:
            report.unresolved_parent_refs.append(ent.ref)
            continue
        by_ref[ent.ref].organic_parent_id = parent.id

    # ── Edges ────────────────────────────────────────────────────────
    unknown_rels = set()
    for e in oob.edges:
        frm, to = by_ref.get(e.from_ref), by_ref.get(e.to_ref)
        if frm is None or to is None:
            report.dropped_edges.append(f"{e.from_ref}->{e.to_ref} (endpoint missing)")
            continue
        if e.relationship_type not in valid_rels:
            unknown_rels.add(e.relationship_type)
            report.dropped_edges.append(f"{e.from_ref}->{e.to_ref} (unknown type {e.relationship_type})")
            continue
        db.add(GraphEdge(
            id=uuid_mod.uuid4(), from_id=frm.id, to_id=to.id,
            relationship_type=e.relationship_type, note=e.note,
            created_by=created_by))
        report.edges_created += 1
    report.unknown_relationship_types = sorted(unknown_rels)

    # ── Templated defaults ───────────────────────────────────────────
    # A named unit with a template_key gets the template's standard
    # structure instantiated as its subtree (OPORD names the unit → the
    # template fills its TO&E). Only when the unit has no children yet,
    # so re-ingest doesn't double-fill.
    for ent in oob.entities:
        if not ent.template_key:
            continue
        node = by_ref.get(ent.ref)
        if node is None:
            continue
        await apply_template(db, node, ent.template_key, report,
                             created_by=created_by)

    if oob.coverage_note:
        report.notes.append(oob.coverage_note)
    if oob.source_label:
        report.notes.append(f"source: {oob.source_label}")

    await db.commit()
    return report


async def _resolve_nomenclature(db: AsyncSession, raw: str):
    """raw string → catalog weg_id, tried in order: exact alias, exact
    weg_id, case-insensitive match against alias / weg_id / catalog
    NAME (VLM emits display names like "M109 Paladin" — the catalog's
    name column, not its id), then ALPHANUMERIC-FOLD matching so
    punctuation/spacing variants resolve ("R-330Zh Zhitel" ↔ "R-330 ZH";
    "Iskander-M" ↔ "Iskander-E, -M, and -K"): exact fold equality
    first, then fold containment either way (shortest matching name
    wins — most specific row), guarded to folds of 6+ characters so
    short designators can't junk-match. Unmatched → None (kept as
    nomenclature_raw, resolvable later by the alias sweep)."""
    if not raw:
        return None
    raw = raw.strip()
    hit = await db.get(WegEquipmentAlias, raw)
    if hit:
        return hit.weg_id
    if await db.get(WegEquipment, raw) is not None:
        return raw
    low = raw.lower()
    row = (await db.execute(
        select(WegEquipmentAlias.weg_id).where(
            func.lower(WegEquipmentAlias.alias) == low).limit(1))).scalar_one_or_none()
    if row:
        return row
    row = (await db.execute(
        select(WegEquipment.weg_id).where(
            (func.lower(WegEquipment.name) == low) |
            (func.lower(WegEquipment.weg_id) == low)).limit(1))).scalar_one_or_none()
    if row:
        return row
    folded = "".join(ch for ch in low if ch.isalnum())
    if len(folded) < 6:
        return None
    fold_expr = func.lower(func.regexp_replace(
        WegEquipment.name, r"[^a-zA-Z0-9]", "", "g"))
    row = (await db.execute(
        select(WegEquipment.weg_id).where(fold_expr == folded)
        .limit(1))).scalar_one_or_none()
    if row:
        return row
    # Query-contains-name anchors at the PREFIX: designators lead and
    # nicknames trail, so "r330zhzhitel" may claim the name fold
    # "r330zh", but "b2spirit" must NOT claim the UAV named "Spirit" —
    # unanchored containment bound the B-2 Spirit to a quadcopter
    # (shortest-name-wins made it worse). Name-contains-query stays
    # unanchored: the B-2's own long display name contains "b2spirit".
    row = (await db.execute(
        select(WegEquipment.weg_id).where(
            (func.strpos(fold_expr, folded) > 0) |
            ((func.length(fold_expr) >= 6)
             & (func.strpos(folded, fold_expr) == 1)))
        .order_by(func.length(WegEquipment.name))
        .limit(1))).scalar_one_or_none()
    if row:
        return row
    # A variant designation refers to its parent system (variants are
    # referable through the normalized id). Variant node keys embed the
    # root: "<root>:variant:<slug>".
    from app.models.reference import ReferenceNode
    row = (await db.execute(
        select(ReferenceNode.key)
        .where(ReferenceNode.key.like("%:variant:%"),
               func.lower(ReferenceNode.name) == low)
        .limit(1))).scalar_one_or_none()
    if row:
        root = row.split(":variant:", 1)[0]
        if await db.get(WegEquipment, root) is not None:
            return root
    return None
