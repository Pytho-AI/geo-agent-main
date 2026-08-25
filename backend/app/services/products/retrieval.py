"""Writer-context retrieval — the CLOSED set, per-token world-model
readers (fifth edition §2.8/§2.10; build-log cont 36v step 2).

Every SPEC read token resolves HERE against the project world model
(project-layer rows only, at generation time). Every member carries an
id the writer can cite; the engine validates cited ids against the
union of these members (writer_invalid outside the set); the renderer
resolves ids into the Sources footer from the quote stored ON the
clause (source_locus at mint — no L0 dereference at render time).

Deterministic: total ordering with explicit tiebreakers, stated
per-token caps, truncation reported to the caller for the record log.
NO fallback ladders — a read returns what the world model holds,
including honestly-empty.

Token dispatch (templates/__init__.py grammar):
  entities:units[:hostile|:friendly]  the unit picture (ORBAT +
                                      holdings rollups + parents)
  entities:civil                      CIVIL_KINDS infrastructure
  entities:marked                     marking IS NOT NULL
  entities:<kind>                     one registry kind
  clauses:episodic[:kind]             the project clause set
  documents / document:<TAG>          a document's CLAUSE SET (writers
                                      never load raw text; L0 serves
                                      humans and the audit)
  map:state                           the painted control-measure
                                      picture (graphics kinds, geometry
                                      summarized)
  map:config                          project map attrs (anchors knob,
                                      weather knob, bbox)
  weather                             the two-branch weather read
                                      (knob-resolved; live branch fails
                                      VISIBLY when unreachable)
  anchors                             temporal anchors + phase/decision
                                      control measures
  map:render                          NOT a retrieval read — the
                                      post-merge render owns it (the
                                      IBL double-render lesson)

upstream:<Name> deps are NOT resolved here — the executor pre-seeds
them from the consumed APPROVED editions' structured_content.
"""
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import or_, select

from app.db.session import async_session
from app.models.graph import (
    CIVIL_KINDS, GRAPHIC_TYPES, GraphEdge, GraphHolding, GraphNode,
    GraphNodePosition,
)
from app.models.reference import WegEquipment
from app.models.world import (
    Clause, ClauseAbout, EntityOccurrence, Section, SectionSourceView,
    Source, SourceRevision, SourceView,
)

# Caps sized against the writer prompt budget (44K-token prompts were
# observed to trip gateway throttling on burst). Clauses carry the
# analytical weight; entity rows stay slim. Sections carry VERBATIM
# passages, so their cap is tighter than the clause cap.
CLAUSE_CAP = 120
ENTITY_CAP = 150
SECTION_CAP = 60
DOC_SECTION_CAP = 80
GRAPHIC_CAP = 120

_ECHELON_FLOOR = ("Battalion", "Squadron", "Regiment", "Brigade",
                  "Division", "Corps", "Army")


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


async def _entity_rows(db, project_id: UUID, *, kinds=None,
                       affiliation=None, marked_only=False,
                       unit_echelon_floor=False) -> tuple[list[dict], bool]:
    """Project-layer entity rows of the requested kinds, with holdings
    rollups, latest-position MGRS, and open hierarchical parent. Total
    order: entity_type, name, id. Returns (rows, truncated)."""
    stmt = (select(GraphNode)
            .where(GraphNode.project_id == project_id,
                   GraphNode.layer == "project"))
    if kinds is not None:
        stmt = stmt.where(GraphNode.entity_type.in_(list(kinds)))
    if affiliation is not None:
        stmt = stmt.where(GraphNode.affiliation == affiliation)
    if marked_only:
        stmt = stmt.where(GraphNode.marking.isnot(None))
    if unit_echelon_floor:
        # The writer's prose lives at battalion-and-above (the IBL
        # org-chart lesson: sub-BN template rows are noise); sub-floor
        # units with stated significance survive.
        stmt = stmt.where(or_(GraphNode.echelon.in_(_ECHELON_FLOOR),
                              GraphNode.significance.isnot(None)))
    stmt = stmt.order_by(GraphNode.entity_type, GraphNode.name,
                         GraphNode.id).limit(ENTITY_CAP + 1)
    nodes = (await db.execute(stmt)).scalars().all()
    truncated = len(nodes) > ENTITY_CAP
    nodes = nodes[:ENTITY_CAP]
    if not nodes:
        return [], truncated
    ids = [n.id for n in nodes]

    # Latest position per node (mgrs + observed time), one query.
    pos_rows = (await db.execute(
        select(GraphNodePosition)
        .where(GraphNodePosition.node_id.in_(ids),
               GraphNodePosition.layer == "project")
        .order_by(GraphNodePosition.node_id,
                  GraphNodePosition.observed_at.desc(),
                  GraphNodePosition.id.desc()))).scalars().all()
    latest_pos: dict = {}
    for p in pos_rows:
        if p.node_id not in latest_pos:
            latest_pos[p.node_id] = p

    # Holdings rollup per node: nomenclature x count (catalog names).
    hold_rows = (await db.execute(
        select(GraphHolding, WegEquipment.name)
        .join(WegEquipment, WegEquipment.weg_id == GraphHolding.weg_id,
              isouter=True)
        .where(GraphHolding.node_id.in_(ids)))).all()
    holdings_by_node: dict = {}
    for h, weg_name in hold_rows:
        label = weg_name or h.nomenclature_raw or h.weg_id or "unresolved"
        cnt = h.count_current if h.count_current is not None else h.count_authorized
        holdings_by_node.setdefault(h.node_id, []).append(
            (label, cnt))

    # Open hierarchical parent per node (the task-org read).
    edge_rows = (await db.execute(
        select(GraphEdge)
        .where(GraphEdge.from_id.in_(ids),
               GraphEdge.effective_to.is_(None),
               GraphEdge.layer == "project"))).scalars().all()
    name_by_id = {n.id: n.name for n in nodes}
    parent_by_node: dict = {}
    for e in edge_rows:
        # Any open edge upward; hierarchical filtering rides the
        # relationship registry at write time (one-open-parent), so the
        # first open edge to a named node is the parent reading.
        if e.from_id not in parent_by_node:
            parent_by_node[e.from_id] = (e.to_id, e.relationship_type)
    # Resolve parent names outside the node cap too.
    missing_parents = {pid for pid, _ in parent_by_node.values()
                       if pid not in name_by_id}
    if missing_parents:
        for n in (await db.execute(
                select(GraphNode.id, GraphNode.name)
                .where(GraphNode.id.in_(list(missing_parents))))).all():
            name_by_id[n.id] = n.name

    rows: list[dict] = []
    for n in nodes:
        p = latest_pos.get(n.id)
        row: dict[str, Any] = {
            "id": str(n.id),
            "kind": n.entity_type,
            "name": n.name,
            "affiliation": n.affiliation,
        }
        if n.echelon:
            row["echelon"] = n.echelon
        if n.unit_type:
            row["unit_type"] = n.unit_type
        if n.subkind:
            row["subkind"] = n.subkind
        if n.significance:
            row["significance"] = n.significance
        if n.significance_note:
            row["significance_note"] = n.significance_note
        if n.posture:
            row["posture"] = n.posture
        if n.combat_effectiveness:
            row["combat_effectiveness"] = n.combat_effectiveness
        if n.personnel_current is not None:
            row["personnel_current"] = n.personnel_current
        if n.current_activity:
            row["current_activity"] = n.current_activity
        if n.marking:
            row["marking"] = n.marking
        if n.template_key:
            row["template_key"] = n.template_key
        if p is not None:
            if p.mgrs:
                row["location_mgrs"] = p.mgrs
            if p.location_text:
                row["location_text"] = p.location_text
            row["position_observed_at"] = _iso(p.observed_at)
            if p.activity:
                row["position_activity"] = p.activity
        parent = parent_by_node.get(n.id)
        if parent is not None:
            pid, rel = parent
            row["parent"] = name_by_id.get(pid, str(pid))
            row["parent_relationship"] = rel
        holdings = holdings_by_node.get(n.id)
        if holdings:
            row["holdings"] = " / ".join(
                (f"{label} x {cnt}" if cnt is not None else label)
                for label, cnt in sorted(
                    holdings, key=lambda t: (-(t[1] or 0), t[0]))[:12])
        rows.append(row)
    return rows, truncated


# ---------------------------------------------------------------------------
# World-model readers (the L0/L1 rewrite; 2026-07-27 ruling): SECTIONS
# carry the VERBATIM source passages — the writer's grounding text —
# and the clause table carries atomic interpretations. The old
# fact_clauses reads served the L0/L1 collapse (sections mis-parsed as
# clauses) and are dead. Citations ride the section -> source_view ->
# source_revision chain, built mechanically at read time.
# ---------------------------------------------------------------------------

def _doc_label(rev: Optional[SourceRevision]) -> str:
    if rev is None:
        return "source"
    return (rev.title or rev.filename or "source").strip() or "source"


def _heading_locus(headings) -> str:
    hs = [h for h in (headings or []) if h]
    if not hs:
        return ""
    return " > ".join(hs[-2:]) if len(hs) > 1 else hs[0]


async def _section_page_labels(db, section_ids: list) -> dict:
    """{section_id: [page labels]} via section_source_views."""
    if not section_ids:
        return {}
    rows = (await db.execute(
        select(SectionSourceView.section_id, SourceView.label,
               SourceView.ordinal)
        .join(SourceView, SourceView.id == SectionSourceView.source_view_id)
        .where(SectionSourceView.section_id.in_(section_ids))
        .order_by(SectionSourceView.section_id, SourceView.ordinal))).all()
    out: dict = {}
    for sid, label, ordinal in rows:
        out.setdefault(sid, []).append(label or f"View {ordinal + 1}")
    return out


def _section_row(s: Section, rev: Optional[SourceRevision],
                 pages: list) -> dict:
    doc = _doc_label(rev)
    locus = _heading_locus(s.headings)
    cite = doc + (f", {locus}" if locus else "")
    if pages:
        cite += f" ({', '.join(pages[:4])})"
    return {
        "id": str(s.id),
        "headings": list(s.headings or []),
        "text": s.body_text or "",
        "document": doc,
        "citation": cite,
    }


async def _sections(db, project_id: UUID, *, tag=None, query=None,
                    cap=SECTION_CAP) -> tuple[list[dict], bool]:
    """Committed project-layer sections in DOCUMENT ORDER (revision,
    then origin_sequence) — the deterministic passage read."""
    stmt = (select(Section, SourceRevision)
            .join(SourceRevision,
                  SourceRevision.id == Section.source_revision_id,
                  isouter=True)
            .where(Section.project_id == project_id,
                   Section.record_state == "committed",
                   Section.layer == "project"))
    if tag:
        stmt = stmt.where(or_(
            SourceRevision.filename.ilike(f"%{tag}%"),
            SourceRevision.title.ilike(f"%{tag}%")))
    if query:
        stmt = stmt.where(Section.body_text.ilike(f"%{query}%"))
    stmt = stmt.order_by(Section.source_revision_id,
                         Section.origin_sequence,
                         Section.id).limit(cap + 1)
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > cap
    rows = rows[:cap]
    pages = await _section_page_labels(db, [s.id for s, _ in rows])
    return [_section_row(s, rev, pages.get(s.id, []))
            for s, rev in rows], truncated


def _clause_row(c: Clause, section: Optional[Section],
                rev: Optional[SourceRevision],
                about: Optional[list] = None) -> dict:
    doc = _doc_label(rev)
    locus = _heading_locus(section.headings if section is not None else None)
    out = {
        "id": str(c.id),
        "register": c.register,
        "text": c.text,
        "citation": doc + (f", {locus}" if locus else ""),
    }
    if c.attribution:
        out["attribution"] = c.attribution
    if about:
        out["about"] = about[:6]
    if c.valid_from or c.valid_to:
        out["valid_from"] = _iso(c.valid_from)
        out["valid_to"] = _iso(c.valid_to)
    return out


async def _clause_about_designations(db, clause_ids: list) -> dict:
    """{clause_id: [occurrence designations]} — the ABOUT read."""
    if not clause_ids:
        return {}
    rows = (await db.execute(
        select(ClauseAbout.clause_id, EntityOccurrence.designation)
        .join(EntityOccurrence,
              EntityOccurrence.id == ClauseAbout.occurrence_id)
        .where(ClauseAbout.clause_id.in_(clause_ids))
        .order_by(ClauseAbout.clause_id,
                  EntityOccurrence.designation))).all()
    out: dict = {}
    for cid, designation in rows:
        out.setdefault(cid, []).append(designation)
    return out


async def _clauses(db, project_id: UUID, *, query=None,
                   about_contains=None,
                   cap=CLAUSE_CAP) -> tuple[list[dict], bool]:
    stmt = (select(Clause, Section, SourceRevision)
            .join(Section, Section.id == Clause.section_id, isouter=True)
            .join(SourceRevision,
                  SourceRevision.id == Section.source_revision_id,
                  isouter=True)
            .where(Clause.project_id == project_id,
                   Clause.record_state == "committed",
                   Clause.layer == "project"))
    if query is not None:
        stmt = stmt.where(Clause.text.ilike(f"%{query}%"))
    if about_contains is not None:
        about_sub = (select(ClauseAbout.clause_id)
                     .join(EntityOccurrence,
                           EntityOccurrence.id == ClauseAbout.occurrence_id)
                     .where(EntityOccurrence.designation.ilike(
                         f"%{about_contains}%")))
        stmt = stmt.where(or_(
            Clause.id.in_(about_sub),
            Clause.text.ilike(f"%{about_contains}%")))
    stmt = stmt.order_by(Clause.valid_from.desc().nulls_last(),
                         Clause.id.desc()).limit(cap + 1)
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > cap
    rows = rows[:cap]
    about = await _clause_about_designations(db, [c.id for c, _, _ in rows])
    return [_clause_row(c, s, rev, about.get(c.id))
            for c, s, rev in rows], truncated


async def _ascope_pmesii_join(db, project_id: UUID) -> dict:
    """The mechanical ASCOPE x PMESII-PT survey join (2026-07-27
    ruling): a matrix cell is the entities tagged with the cell's
    COLUMN category that are subjects of clauses tagged with the
    cell's ROW facet, through the occurrence chain (clause_about ->
    entity_occurrences.canonical_node_id). Tags are stamped at
    ingestion (repair-backfilled for pre-contract records); nothing
    here enumerates kinds, no cap games, no model downstream — the
    join IS the cell content. Payload: citable entities + clauses
    (marked like any member) plus flat join records referencing them
    by id."""
    rows = (await db.execute(
        select(GraphNode, Clause, Section, SourceRevision)
        .join(EntityOccurrence,
              EntityOccurrence.canonical_node_id == GraphNode.id)
        .join(ClauseAbout,
              ClauseAbout.occurrence_id == EntityOccurrence.id)
        .join(Clause, Clause.id == ClauseAbout.clause_id)
        .join(Section, Section.id == Clause.section_id, isouter=True)
        .join(SourceRevision,
              SourceRevision.id == Section.source_revision_id,
              isouter=True)
        .where(GraphNode.project_id == project_id,
               GraphNode.layer == "project",
               GraphNode.ascope.isnot(None),
               Clause.project_id == project_id,
               Clause.record_state == "committed",
               Clause.layer == "project",
               Clause.pmesii.isnot(None))
        .order_by(GraphNode.name, GraphNode.id, Clause.id))).all()
    entities: dict[str, dict] = {}
    clauses: dict[str, dict] = {}
    cells: dict[tuple, dict[str, set]] = {}
    for node, clause, section, rev in rows:
        nid, cid = str(node.id), str(clause.id)
        if nid not in entities:
            entities[nid] = {"id": nid, "kind": node.entity_type,
                             "name": node.name,
                             "ascope": list(node.ascope or [])}
        if cid not in clauses:
            clauses[cid] = _clause_row(clause, section, rev)
        for facet in clause.pmesii or []:
            for category in node.ascope or []:
                cell = cells.setdefault((facet, category), {})
                cell.setdefault(nid, set()).add(cid)
    join = [{"facet": f, "category": c, "entity_id": nid,
             "clause_ids": sorted(cids)}
            for (f, c), members in sorted(cells.items())
            for nid, cids in members.items()]
    return {"entities": list(entities.values()),
            "clauses": list(clauses.values()),
            "join": join}


async def _documents(db, project_id: UUID) -> list[dict]:
    rows = (await db.execute(
        select(SourceRevision, Source)
        .join(Source, Source.id == SourceRevision.source_id)
        .where(Source.project_id == project_id)
        .order_by(SourceRevision.capture_time, SourceRevision.id))).all()
    return [{"id": str(rev.id),
             "filename": rev.filename,
             "title": rev.title or src.title,
             "ingested_at": _iso(rev.capture_time)}
            for rev, src in rows]


async def _map_config(db, project_id: UUID) -> dict:
    from app.models.map import Map as _Map
    m = await db.get(_Map, project_id)
    attrs = (m.attrs or {}) if m is not None else {}
    out = {
        "project_name": m.name if m is not None else str(project_id),
        "temporal_anchors": attrs.get("temporal_anchors"),
        "weather_source": attrs.get("weather_source"),
    }
    if m is not None and m.bbox_west is not None:
        out["bbox"] = [m.bbox_west, m.bbox_south, m.bbox_east, m.bbox_north]
    return out


async def _map_state_summary(db, project_id: UUID) -> tuple[dict, bool]:
    """The painted control-measure picture, writer-slim: graphics-kind
    entities with names + geometry summarized (centroid), never raw
    FeatureCollections (the 1.44M-token get_terrain lesson)."""
    from geoalchemy2.functions import ST_AsText, ST_PointOnSurface
    stmt = (select(GraphNode,
                   ST_AsText(ST_PointOnSurface(GraphNode.geom)))
            .where(GraphNode.project_id == project_id,
                   GraphNode.layer == "project",
                   GraphNode.entity_type.in_(list(GRAPHIC_TYPES)),
                   GraphNode.geom.isnot(None))
            .order_by(GraphNode.entity_type, GraphNode.name, GraphNode.id)
            .limit(GRAPHIC_CAP + 1))
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > GRAPHIC_CAP
    graphics = []
    for n, centroid_wkt in rows[:GRAPHIC_CAP]:
        g = {"id": str(n.id), "kind": n.entity_type, "name": n.name,
             "affiliation": n.affiliation}
        if n.subkind:
            g["subkind"] = n.subkind
        if centroid_wkt:
            g["centroid"] = centroid_wkt
        if n.notes:
            g["notes"] = (n.notes[:200] + "...") if len(n.notes) > 200 else n.notes
        graphics.append(g)
    return {"graphics": graphics, "count": len(graphics)}, truncated


async def _persist_live_weather_snapshot(db, project_id: UUID,
                                         record_id: UUID,
                                         live: dict) -> dict:
    """The live-branch SNAPSHOT (design §0 step 5, lands with the WEM):
    the generate-time fetch lands as RECORD-LAYER content — an L0
    capture + a draft Section carrying the verbatim payload — so the
    record cites STORED data. Draft rows carry origin_record_id and
    NEVER merge (approval's merge list does not include the world
    section/clause tables — snapshot content merges nowhere by design).
    Returns a citable section row for the retrieval payload."""
    import hashlib
    import json as _json
    import uuid as _uuid
    from datetime import datetime, timezone as _tz

    now = datetime.now(_tz.utc)
    stamp = now.strftime("%d%H%MZ %b %Y").upper()
    body = _json.dumps(live, indent=2, sort_keys=True, default=str)
    src = Source(id=_uuid.uuid4(), project_id=project_id,
                 title="Live weather forecast snapshot",
                 issuer="OpenWeatherMap / Open-Meteo",
                 created_by="_autodraft")
    db.add(src)
    await db.flush()
    rev = SourceRevision(
        id=_uuid.uuid4(), source_id=src.id,
        object_ref=f"weather://forecast/{project_id}",
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        media_type="application/json",
        filename=f"weather-forecast-{now.strftime('%Y%m%dT%H%MZ')}.json",
        title=f"Live weather forecast {stamp}",
        issuer="OpenWeatherMap / Open-Meteo", capture_time=now,
        capture_actor="_autodraft")
    db.add(rev)
    await db.flush()
    section = Section(
        id=_uuid.uuid4(), origin_kind="external_source",
        source_revision_id=rev.id, project_id=project_id,
        headings=["Live weather forecast snapshot", stamp],
        body_text=body,
        text_hash=hashlib.sha256(body.encode()).hexdigest(),
        origin_sequence=0, record_state="committed",
        layer="draft", origin_record_id=record_id,
        created_by="_autodraft")
    db.add(section)
    await db.commit()
    return _section_row(section, rev, [])


async def _weather(db, project_id: UUID,
                   record_id: Optional[UUID] = None) -> dict:
    """The two-branch weather read. authored = the world model's stated
    weather (weather_condition entities + weather clauses + the stated
    weather sections); live = the connected weather service (fails
    VISIBLY — upstream_failed naming the weather read; never a silent
    fall-through to authored). The live fetch is PERSISTED as record
    draft-layer content so the record cites stored data."""
    cfg = await _map_config(db, project_id)
    knob = (cfg.get("weather_source") or "authored").strip().lower()
    out: dict[str, Any] = {"source": knob}
    if knob == "live":
        try:
            # The one OpenWeatherMap client in the stack (route weather
            # service) — its per-point forecast fetch, aimed at the
            # project bbox center. No parallel client.
            from app.services.knowledge.routing.weather import (
                _extract_point_weather, _fetch_owm_forecast,
                _pick_closest_forecast)
            from datetime import datetime, timezone as _tz
            bbox = cfg.get("bbox")
            if not bbox:
                raise RuntimeError("project has no bbox for the "
                                   "live weather read")
            lat = (bbox[1] + bbox[3]) / 2.0
            lon = (bbox[0] + bbox[2]) / 2.0
            forecast_list = await _fetch_owm_forecast(lat, lon)
            if not forecast_list:
                raise RuntimeError("OpenWeatherMap returned no forecast "
                                   "(missing API key or offline mode)")
            now_ts = datetime.now(_tz.utc).timestamp()
            forecast = _pick_closest_forecast(forecast_list, now_ts)
            live = _extract_point_weather(forecast) if forecast else {}
            live["lat"] = lat
            live["lon"] = lon
            out["live"] = live
            # The exemplar forecast grid (2026-07-27 ruling): Open-Meteo
            # supplies the 5-day x 12-hour element grid — including the
            # cloud_base ceiling OpenWeatherMap's free tier lacks. Part
            # of the live branch's visible-failure contract.
            from app.services.products.wem_grid import (
                build_forecast_grid, fetch_open_meteo)
            om_raw = await fetch_open_meteo(lat, lon)
            out["forecast_grid"] = build_forecast_grid(om_raw)
            if record_id is not None:
                snapshot = await _persist_live_weather_snapshot(
                    db, project_id, record_id,
                    {"openweathermap": live,
                     "open_meteo_forecast_grid": out["forecast_grid"]})
                out["snapshot"] = snapshot
            return out
        except Exception as e:
            raise RuntimeError(
                f"weather read (live branch) failed: {e} — the "
                "weather_source knob is 'live' and the service is "
                "unreachable; flip the knob to 'authored' or restore "
                "connectivity") from e
    # AUTHORED: the stated weather in the world model — the
    # weather_condition entities, ALL weather-related clauses (about
    # links to the weather entities plus term-matched statements —
    # 2026-07-27 ruling: tag and pass all of them), and the stated
    # weather passages (sections). Plus the exemplar-grid skeleton:
    # periods anchored on the STATED exercise H-hour, climatology
    # baseline from historical averages, stated overlay downstream —
    # nothing invented; uncovered cells render NOT STATED.
    entities, _trunc = await _entity_rows(
        db, project_id, kinds=["weather_condition"])
    out["conditions"] = entities
    weather_rows: dict[str, dict] = {}
    truncated = False
    for term in ("weather", "fog", "thunderstorm", "rain", "wind",
                 "visibility", "precipitation", "ceiling", "cloud",
                 "heat", "temperature", "daylight", "illumination"):
        rows, trunc = await _clauses(
            db, project_id, about_contains=term, cap=30)
        truncated = truncated or trunc
        for r in rows:
            weather_rows.setdefault(r["id"], r)
    out["clauses"] = list(weather_rows.values())[:60]
    sections, _s_trunc = await _sections(
        db, project_id, query="weather", cap=8)
    if sections:
        out["sections"] = sections
    if truncated:
        out["_truncated"] = True
    anchors = (cfg.get("temporal_anchors") or {})
    h_hour = anchors.get("h_hour") or anchors.get("d_day")
    from app.services.products.wem_grid import (
        build_authored_skeleton, fetch_historical_periods,
        parse_anchor_date)
    baseline = None
    bbox = cfg.get("bbox")
    if not bbox:
        out["climatology_unavailable"] = (
            "project has no bbox — no location for the historical-"
            "averages fetch")
    else:
        try:
            baseline = await fetch_historical_periods(
                (bbox[1] + bbox[3]) / 2.0, (bbox[0] + bbox[2]) / 2.0,
                parse_anchor_date(h_hour))
        except Exception as e:
            # Air-gapped or archive-down: the baseline stays absent —
            # LOGGED here and VISIBLE in the artifact (cells say NOT
            # STATED; the source line says no historical averages).
            out["climatology_unavailable"] = str(e)[:200]
    out["forecast_grid_skeleton"] = build_authored_skeleton(
        h_hour, baseline)
    return out


async def _anchors(db, project_id: UUID) -> dict:
    cfg = await _map_config(db, project_id)
    out: dict[str, Any] = {
        "temporal_anchors": cfg.get("temporal_anchors"),
    }
    phases = (await db.execute(
        select(GraphNode)
        .where(GraphNode.project_id == project_id,
               GraphNode.layer == "project",
               GraphNode.entity_type.in_(["phase_line", "decision_point"]))
        .order_by(GraphNode.entity_type, GraphNode.name, GraphNode.id)
        .limit(40))).scalars().all()
    out["control_measures"] = [
        {"id": str(n.id), "kind": n.entity_type, "name": n.name,
         **({"notes": n.notes[:200]} if n.notes else {})}
        for n in phases]
    return out


async def read_token(db, project_id: UUID, token: str,
                     record_id: Optional[UUID] = None
                     ) -> tuple[Any, list[str]]:
    """Resolve ONE read token. Returns (payload, truncation_notes)."""
    notes: list[str] = []

    if token == "matrix:ascope_pmesii":
        return await _ascope_pmesii_join(db, project_id), notes
    if token.startswith("entities:"):
        rest = token[len("entities:"):]
        if rest == "units" or rest.startswith("units:"):
            affiliation = None
            if rest == "units:hostile":
                affiliation = "Hostile"
            elif rest == "units:friendly":
                affiliation = "Friend"
            rows, trunc = await _entity_rows(
                db, project_id, kinds=["unit"], affiliation=affiliation,
                unit_echelon_floor=True)
            if trunc:
                notes.append(f"{token} capped at {ENTITY_CAP}")
            return {"units": rows, "count": len(rows)}, notes
        if rest == "civil":
            rows, trunc = await _entity_rows(
                db, project_id, kinds=list(CIVIL_KINDS))
            if trunc:
                notes.append(f"{token} capped at {ENTITY_CAP}")
            return {"entities": rows, "count": len(rows)}, notes
        if rest == "marked":
            rows, trunc = await _entity_rows(
                db, project_id, marked_only=True)
            if trunc:
                notes.append(f"{token} capped at {ENTITY_CAP}")
            return {"entities": rows, "count": len(rows)}, notes
        # entities:<kind> — one registry kind.
        rows, trunc = await _entity_rows(db, project_id, kinds=[rest])
        if trunc:
            notes.append(f"{token} capped at {ENTITY_CAP}")
        return {"entities": rows, "count": len(rows)}, notes

    if token.startswith("clauses:"):
        # The new clause layer carries no sub-kind column — every
        # clauses:episodic[:kind] token resolves the committed episodic
        # set; per-field clause_scope narrows further only where rows
        # carry a kind (legacy data).
        rows, trunc = await _clauses(db, project_id)
        if trunc:
            notes.append(f"{token} capped at {CLAUSE_CAP}")
        return {"clauses": rows, "count": len(rows)}, notes

    if token == "documents":
        # The source inventory PLUS the SECTIONS — the VERBATIM
        # passages (2026-07-27 ruling: sections are the writer's
        # grounding text; the old clause read served the L0/L1
        # collapse). A missing passage is an ingest gap.
        docs = await _documents(db, project_id)
        rows, trunc = await _sections(db, project_id)
        if trunc:
            notes.append(f"{token} sections capped at {SECTION_CAP}")
        return {"documents": docs, "sections": rows,
                "count": len(docs)}, notes

    if token.startswith("document:"):
        tag = token[len("document:"):].strip()
        docs = await _documents(db, project_id)
        match = [d for d in docs
                 if tag.lower() in ((d.get("filename") or "")
                                    + (d.get("title") or "")).lower()]
        rows, trunc = await _sections(
            db, project_id, tag=tag, cap=DOC_SECTION_CAP)
        if trunc:
            notes.append(f"{token} sections capped at {DOC_SECTION_CAP}")
        return {"tag": tag, "documents": match, "sections": rows,
                "count": len(rows)}, notes

    if token == "map:state":
        payload, trunc = await _map_state_summary(db, project_id)
        if trunc:
            notes.append(f"map:state graphics capped at {GRAPHIC_CAP}")
        return payload, notes

    if token == "map:config":
        return await _map_config(db, project_id), notes

    if token == "map:render":
        # Deliberate deferral — the post-merge render owns the figure
        # (the IBL double-render / CDP-saturation lesson). The dep
        # exists for wave ordering only.
        return {"deferred": "map:render is the post-merge render"}, notes

    if token == "weather":
        return await _weather(db, project_id, record_id=record_id), notes

    if token == "anchors":
        return await _anchors(db, project_id), notes

    raise ValueError(f"unknown read token: {token!r}")


async def build_retrieval(project_id: UUID,
                          tokens: list[str],
                          record_id: Optional[UUID] = None) -> dict:
    """Resolve every read token; return the members keyed by token +
    truncation notes. The union of member ids IS the citation
    universe (closed set). record_id scopes record-layer capture
    (the live weather snapshot)."""
    out: dict[str, Any] = {"members": {}, "truncated": []}
    async with async_session() as db:
        for token in tokens:
            payload, notes = await read_token(db, project_id, token,
                                              record_id=record_id)
            out["members"][token] = payload
            out["truncated"].extend(notes)
    return out


async def fetch_clause(project_id: UUID, kind: Optional[str],
                       query: str) -> Optional[dict]:
    """Deterministic single-clause pull for the mechanical
    clause:<kind>:<query> source (the writer-involvement law —
    verbatim fields are engine-resolved). The new clause layer has no
    sub-kind column, so <kind> is advisory; the query does the work.
    Rank: text prefix match beats contains; then valid_from desc, id
    desc. Returns the clause row dict or None (None = ingest gap, the
    caller fails visibly)."""
    q = (query or "").strip()
    if not q:
        return None
    async with async_session() as db:
        stmt = (select(Clause, Section, SourceRevision)
                .join(Section, Section.id == Clause.section_id,
                      isouter=True)
                .join(SourceRevision,
                      SourceRevision.id == Section.source_revision_id,
                      isouter=True)
                .where(Clause.project_id == project_id,
                       Clause.record_state == "committed",
                       Clause.layer == "project",
                       Clause.text.ilike(f"%{q}%")))
        stmt = stmt.order_by(Clause.valid_from.desc().nulls_last(),
                             Clause.id.desc()).limit(8)
        rows = (await db.execute(stmt)).all()
        if not rows:
            return None
        prefix = [t for t in rows
                  if (t[0].text or "").lower().startswith(q.lower())]
        c, s, rev = (prefix or rows)[0]
        return _clause_row(c, s, rev)


async def fetch_graphic(project_id: UUID, kind: str) -> Optional[dict]:
    """Deterministic single-graphic pull for the mechanical
    graphic:<kind>:<field> source. Where the project carries SEVERAL
    graphics of the kind (a corps order assigns several sectors), the
    relevant one is the OPERATIONALLY CENTRAL instance — the one with
    the most typed links in the project graph (the world model's own
    structure says which area the operation is about: forces located
    in it, control measures supporting it) — a mechanical,
    project-derived reading, never a name-order accident. Tiebreak
    (degree desc, name, id); kinds with one instance are unchanged."""
    from sqlalchemy import func as _func
    async with async_session() as db:
        rows = (await db.execute(
            select(GraphNode)
            .where(GraphNode.project_id == project_id,
                   GraphNode.layer == "project",
                   GraphNode.entity_type == kind)
            .order_by(GraphNode.name, GraphNode.id))).scalars().all()
        if len(rows) > 1:
            ids = [n.id for n in rows]
            degree: dict = {}
            for col in (GraphEdge.from_id, GraphEdge.to_id):
                for nid, cnt in (await db.execute(
                        select(col, _func.count())
                        .where(col.in_(ids),
                               GraphEdge.layer == "project")
                        .group_by(col))).all():
                    degree[nid] = degree.get(nid, 0) + cnt
            rows = sorted(rows, key=lambda n: (-degree.get(n.id, 0),
                                               n.name or "", str(n.id)))
        row = rows[0] if rows else None
    if row is None:
        return None
    out = {"id": str(row.id), "kind": row.entity_type,
           "name": row.name, "affiliation": row.affiliation}
    if row.subkind:
        out["subkind"] = row.subkind
    if row.notes:
        out["notes"] = row.notes[:300]
    return out
