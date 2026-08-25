"""MCP wrapper over the extraction/curation tool surface.

TWO transports, one server, one tool registry:

- Streamable HTTP (stateless JSON) at /api/v1/mcp — the modern
  transport for programmatic clients (pytho-agent, headless drivers).
- SSE at /api/v1/mcp-sse/sse — for interactive Claude Code sessions:
  Claude Code AUTO-RECONNECTS dropped SSE connections, so every backend
  restart (deploy) forces a fresh initialize and the session picks up
  new/changed tool schemas and instructions WITHOUT a manual /mcp
  reconnect. main.py mounts this more-specific path BEFORE the /api/v1
  streamable mount (Starlette matches mounts in order).

EVERY tool works in BATCHES (lists in, per-item echoes out; one item's
failure never sinks the batch). Tools live in
app/services/graph_ingest/tools.py; this module only adapts them to MCP.
Design: scratch/docs/oob/extraction-decision-spec.md.
"""
from typing import List, Optional

from mcp.server.mcpserver import MCPServer, Image

from app.mcp_transport import TRANSPORT_SECURITY, stateless_sse_app
from app.services.graph_ingest import tools as t

_BASE_INSTRUCTIONS = (
    "World-record tool surface for the geo-agent entity graph "
    "(military training simulation). ALL tools are BATCHED: pass a "
    "list of flat items, get per-item echoes (an item's error occupies "
    "its slot; the rest of the batch lands). THE RECORD IS THE ONLY "
    "WRITE PATH (S17 cutover): every write is a committed assertion "
    "chained to captured L0 — assert (statement citing a committed "
    "clause, or authoring a NEW clause under an existing committed "
    "section), update (correction / change / create / merge / "
    "occurrence re-bind through the record's own mechanics), retract, "
    "purge — with the finders find_clauses / find_entities / "
    "find_assertions / find_positions. The actor is never a source: "
    "new information enters only by capturing its source first (a "
    "FRAGO, however short, is a captured revision, then cited like any "
    "other source); an action citing no source is not a record write. "
    "The pre-record writers (submit_oob, upsert_units, add_positions, "
    "add_holdings, add_edges, set_shapes, delete_entities, "
    "place_subordinates, add_clauses) are REMOVED — entity removal is "
    "not an operation (correct attributes in place, merge duplicates, "
    "or fix the misread occurrence at L1). Typical pass: find_clauses "
    "for the stating basis → assert/update → render_map and LOOK → "
    "spot-check with reverse_geocode. Grids resolve by exact MGRS math "
    "and are never moved; nearest_place echoes are read-only context. "
    "project_id is the event's map UUID. Reference templates and "
    "equipment BY NAME, exactly as listed below. The graph IS an "
    "ontology: object types and link types are the registries below, "
    "properties are typed columns + spec tuples, action types are "
    "these tools, interfaces carry capability (Locatable/Rangeable/"
    "Sensor/Emitter/Expendable/Holder); placed entities walk to the "
    "immutable reference catalog over the virtual instance_of link. "
    "Relative DTGs (H+36, D+2) resolve against map "
    "attrs.temporal_anchors {h_hour, d_day} and are REJECTED when "
    "unanchored."
)

# SDK v2: transport parameters moved off the constructor onto the app
# builders (mcp_asgi_app / mcp_sse_app below).
mcp = MCPServer("geo-agent", instructions=_BASE_INSTRUCTIONS)


async def refresh_instructions() -> None:
    """Rebuild instructions WITH the choice lists (registries,
    faction-grouped template names, equipment names) after DB
    bootstrap — drivers get them in their system context at connect,
    never via a tool call."""
    lists = await t.reference_lists()
    mcp._lowlevel_server.instructions = _BASE_INSTRUCTIONS + "\n\n" + lists


# ── READ / VERIFY ────────────────────────────────────────────────────


@mcp.tool()
async def mgrs_to_latlon(grids: List[str]) -> dict:
    """Convert MGRS grid references (e.g. '34UEE 64392 54490') to WGS84
    lat/lon, batched. Each result echoes the nearest named place for
    cross-checking the narrative."""
    return await t.tool_mgrs_to_latlon(grids)


@mcp.tool()
async def latlon_to_mgrs(points: List[dict]) -> dict:
    """Convert WGS84 points to MGRS, batched. Item: {lat, lon}."""
    return await t.tool_latlon_to_mgrs(points)


@mcp.tool()
async def reverse_geocode(points: List[dict]) -> dict:
    """Nearest named places to each point with distance (km) and
    compass bearing FROM the place TO the point, batched. Item:
    {lat, lon} — verify grids against narrative like '15 km east of
    Elk'."""
    return await t.tool_reverse_geocode(points)


@mcp.tool()
async def geocode_places(queries: List[dict],
                         project_id: Optional[str] = None) -> dict:
    """Resolve place NAMES to candidate coordinates, batched. Item:
    {query, west?, south?, east?, north?} — per-item bbox wins; else
    project graph extent (pass project_id); else a world sweep that
    only sees countries and major cities. Villages need a tight bbox
    (a degree or two)."""
    return await t.tool_geocode_places(queries, project_id)


@mcp.tool()
async def snap_to_feature(points: List[dict]) -> dict:
    """Snap points onto the nearest OSM linear feature, batched. Item:
    {lat, lon, feature: 'railway'|'road', radius_m?}. Echo: snapped
    lat/lon, moved_km, way_name. Use to place linear infrastructure
    precisely (a rail segment onto the rail line, an MSR waypoint onto
    the road) from an approximate point. rail_hub / route / MSR /
    bridge entities also snap automatically at write time."""
    return await t.tool_snap_to_feature(points)


@mcp.tool()
async def project_points(items: List[dict]) -> dict:
    """Offset points by bearing/distance, batched. Item: {lat, lon,
    bearing_deg, distance_km} → dest_lat/dest_lon/dest_mgrs. The
    DIRECTIONAL placement rung: 'within 10 km of the border on the
    enemy side' computes as a reference point offset toward the
    owning side."""
    return await t.tool_project_points(items)


@mcp.tool()
async def list_entities(project_id: str) -> dict:
    """Every entity in the project: name, type, affiliation, echelon,
    current position (or shape type for control measures), parent,
    track length. The project-wide summary read."""
    return await t.tool_list_entities(project_id)


@mcp.tool()
async def get_entities(project_id: str, names: List[str]) -> dict:
    """Full per-entity detail, batched by name: all fields, parent,
    children, holdings, edges in/out, and the complete append-only
    position track. Each track row carries its `observation` handle
    (rows missing observed_at sort FIRST — defects awaiting manual
    time repair via add_positions' set_time_on override, against the
    source documentation their `source` citation names)."""
    return await t.tool_get_entities(project_id, names)


@mcp.tool()
async def find_templates(query: str = "",
                         echelon: Optional[str] = None) -> dict:
    """Search the force-template library (token-wise: 'motor rifle'
    finds 'Motorized Rifle Regiment')."""
    return await t.tool_find_templates(query, echelon)


@mcp.tool()
async def get_templates(keys: List[str]) -> dict:
    """Template subtrees (units + standard equipment), batched by NAME
    or key."""
    return await t.tool_get_templates(keys)


@mcp.tool()
async def resolve_equipment(nomenclatures: List[str]) -> dict:
    """Resolve equipment strings against the catalog, batched. Misses
    return near_matches (write-time matching is exact, never fuzzy) —
    flag unresolvable systems as catalog gaps."""
    return await t.tool_resolve_equipment(nomenclatures)


@mcp.tool()
async def search_equipment(queries: List[dict]) -> dict:
    """Batched catalog search: each item {query?, origin?, operator?,
    class?, domain?, category?, year_min?, year_max?, limit?} -> matching
    systems. origin = who built it, operator = who fields it
    (proliferation) — two distinct canonical-country axes."""
    return await t.tool_search_equipment(queries)


@mcp.tool()
async def get_equipment_sheets(weg_ids: List[str]) -> dict:
    """Batched full WEG sheet read: classification, origin/operators,
    introduction year, the flat specifications map, range candidates
    with conditions, emitters, and the open value-conflict count."""
    return await t.tool_get_equipment_sheets(weg_ids)


@mcp.tool()
async def search_doctrine(queries: List[dict]) -> dict:
    """Batched doctrine retrieval: each item {question, doc_ids?, k?} ->
    passage hits from the doctrine library. Every hit carries its source
    link ('doctrine:<doc_id>:<page>') — cite it in any product or answer,
    exactly like the catalog's weg: links."""
    return await t.tool_search_doctrine(queries)


@mcp.tool()
async def get_doctrine_pages(pages: List[dict]) -> dict:
    """Batched full-page doctrine reads: each item {doc_id, page} -> the
    page's verbatim text with its source link — quote the page, cite the
    link."""
    return await t.tool_get_doctrine_pages(pages)


@mcp.tool()
async def render_map(project_id: str,
                     west: Optional[float] = None,
                     south: Optional[float] = None,
                     east: Optional[float] = None,
                     north: Optional[float] = None,
                     projection: str = "plan",
                     profile_start: Optional[str] = None,
                     profile_end: Optional[str] = None,
                     envelope: Optional[str] = None) -> Image:
    """The render is a CAMERA over the world model; `projection` picks
    which one. plan (default): the operational map (SIDC symbols +
    doctrinal graphics; bbox to zoom; tens of seconds). profile: the
    vertical terrain slice along profile_start->profile_end (MGRS) —
    the line-of-sight / crest-clearance diagram, entities near the ray
    marked. envelope: altitude-vs-range chart for a catalog system
    (`envelope` = exact name or alias) from its stated range/altitude
    candidates. vantage/oblique/sequence are registered vocabulary;
    their cameras land with their consumers. LOOK at what comes back."""
    if projection != "plan":
        png = await t.tool_render_projection(
            project_id, projection, profile_start, profile_end, envelope)
        return Image(data=png, format="png")
    jpg = await t.tool_render_map(project_id, west, south, east, north)
    return Image(data=jpg, format="jpeg")


# ── RECALL ───────────────────────────────────────────────────────────


@mcp.tool()
async def get_entity_brief(project_id: str, names: List[dict],
                           as_of: str = None) -> dict:
    """Batched entity briefs — the world model's recall read. Item:
    {name}. Per entity: attribute History as supersession chains (the
    line marked current is that attribute's authoritative latest — the
    chain's grouping outranks wording similarity), Reporting statements
    with speaker/source/date provenance, Doctrine for the unit's
    template, position, and deduplicated per-kind counts (use the counts
    for how-many questions; counting is computed, never estimated).
    as_of (ISO) resolves state at that instant (observed_at — the
    record's one temporal dimension)."""
    return await t.tool_get_entity_brief(project_id, names, as_of)


# Pre-record writers REMOVED here at the S17 cutover (2026-07-28):
# submit_oob, upsert_units, add_positions, add_holdings, add_edges,
# remove_edges, remove_holdings, delete_entities, set_shapes,
# place_subordinates, add_clauses. Their capabilities live in the
# general verbs below: bulk builds are ingestion runs (L0 entry on the
# world server); observations/holdings/relationships/server-drawn
# shapes are assert payloads; corrections/merges/occurrence re-binds
# are update; entity removal is NOT an operation. Arraying is
# paint-time plan_disposition — nothing instantiates arrays anymore.


# ── WORLD RECORD (the general verbs, design S17) ─────────────────────
# One write path, every entry layer: these adapt the world surface's
# general verbs (app/api/v1/world_repair.py — the SAME handlers the
# REST routes serve) to MCP so agents reach the record without curl.
# Names follow the existing plain-verb convention (S17.2); `assert` is
# a Python keyword, so the registration carries the tool name.


@mcp.tool(name="assert")
async def world_assert(project_id: str, items: List[dict]) -> dict:
    """Create committed record assertions from captured L0 — clause
    basis REQUIRED (an unsupported value is rejected, never
    fabricated). Batched. Item: {entity (UUID or name), kind
    (property|state|relationship|holding|position), basis_clause
    (committed clause UUID from find_clauses) OR new_clause {section
    (committed section UUID), text} (the L1 entry: author a NEW atomic
    reading of already-captured text — it lands committed under that
    section, about-linked to the entity, and becomes this item's
    basis; requires the item's stated dtg), dtg?, valid_to?,
    attribute?, value?, count? (holding — nomenclature in value,
    catalog-resolved at materialization), relation?+to? (relationship),
    properties?, position payload: mgrs?|lat+lon?|mgrs_line?|
    mgrs_polygon?|circle_mgrs?+radius_m?|rect_mgrs? (two opposite
    corners)|ellipse_mgrs?+semi_major_m?+semi_minor_m?+orientation_deg?
    (the server generates every ring — never hand-extrapolate
    vertices), note? (lands in the events log, never on the record)}.
    valid_from = the stated dtg, else the basis clause's valid_from; an
    item with neither is rejected — a write never invents an
    observation time. Position echoes carry the resolved point +
    nearest named place. Materializes through the one write path."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_assert(project_id, items)


@mcp.tool()
async def update(project_id: str, items: List[dict]) -> dict:
    """Record correction through the record's OWN mechanics — never
    in-place mutation, never annotation prose. Batched items by target.
    {target: "assertion", ref, valid_from?|valid_to?|value?|count?|
    mgrs?|lat+lon?|mgrs_line?|mgrs_polygon?, note?} — a mis-read TIME
    or VALUE: a new assertion with the corrected fields and the SAME
    basis SUPERSEDES the old; the old projection row is removed and the
    correction materializes fresh.
    {target: "entity", ref (UUID or name), <fields>, change?,
    basis_clause?, basis?, dtg?, create?, merge_into?, ascope?, note?}
    — record-bearing attributes (echelon, affiliation, posture,
    unit_type, combat_effectiveness, significance, category,
    current_activity, long_name, notes) REQUIRE basis_clause, or basis:
    "designation" when the entity's own recorded designation states the
    value; they land as property assertions. Correction (default) =
    the prior was wrong ab initio and is superseded. change: true = the
    value CHANGED at the stated time — the prior stays true for its
    interval, its valid_to closes at the new valid_from, nothing is
    superseded; a change predating the newest assertion is rejected.
    Addressing/structure fields (name, template_key, organic_parent,
    entity_type — registry-validated) stay direct and audited.
    create: true mints an entity the basis clause names (node +
    occurrence bound in the clause's section). merge_into: <canonical>
    repoints everything a duplicate anchors (occurrences, assertions,
    track, holdings, edges, children) onto the canonical entity and
    drops the empty duplicate row.
    {target: "clause", ref, pmesii, note?} — the clause's PMESII facet
    tags (closed vocabulary; the statement itself is immutable).
    {target: "occurrence", ref (occurrence UUID), bind_to (entity ref,
    or null to clear), note?} — the L1 occurrence correction: an
    identity the source never actually named is fixed at L1 by
    re-binding (or clearing) the misread occurrence; cleared
    occurrences surface in find_entities unbound=true. Entity removal
    is NOT an operation — an entity left with no bindings and no live
    assertions is an empty projection row.
    Every echo (priors included) lands in the events log."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_update(project_id, items)


@mcp.tool()
async def retract(project_id: str, items: List[dict]) -> dict:
    """Logical, history-preserving retraction of a committed assertion.
    Batched. Item: {assertion (UUID), reason (required)}. The assertion
    and retraction records remain; the materialized projection row is
    removed so paint re-derives from the surviving record."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_retract(project_id, items)


@mcp.tool()
async def purge(project_id: str, items: List[dict]) -> dict:
    """Delete an UNBACKED projection row (bypass-writer corruption
    cleanup). Batched. Item: {kind: position|edge|holding, row (UUID)}.
    A row backed by any assertion is REFUSED — that correction is
    retract."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_purge(project_id, items)


@mcp.tool()
async def find_clauses(project_id: str, q: Optional[str] = None,
                       untagged: bool = False, limit: int = 10) -> dict:
    """Committed-clause finder — the basis candidates for every record
    write. ILIKE search over clause text when q is given; without q it
    enumerates. untagged=true narrows to clauses with no PMESII facets.
    Echo: id, text, pmesii, valid_from, section heading path."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_find_clauses(project_id, q, untagged, limit)


@mcp.tool()
async def find_entities(project_id: str, kind: Optional[str] = None,
                        untagged: bool = False, unbound: bool = False,
                        limit: int = 400) -> dict:
    """Project-layer entity listing (id, name, entity_type, ascope).
    Names duplicate across kinds and regions — corrections address rows
    by UUID. kind filters by entity_type; untagged=true narrows to
    entities with no ASCOPE categories. unbound=true switches to the
    UNRESOLVED-OCCURRENCE listing (committed occurrences with no
    canonical entity — the review queue occurrence corrections feed)."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_find_entities(project_id, kind, untagged, limit,
                                       unbound=unbound)


@mcp.tool()
async def find_assertions(project_id: str, entity: str,
                          kind: Optional[str] = None,
                          attribute: Optional[str] = None) -> dict:
    """Every committed assertion whose subject/from/to is the entity
    (UUID or name). Optional kind/attribute filters. Echo per
    assertion: id, kind, attribute, value, relation, endpoints, valid
    window, retracted/superseded flags, materialized row ids."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_find_assertions(project_id, entity, kind,
                                         attribute)


@mcp.tool()
async def find_positions(project_id: str, entity: str) -> dict:
    """The entity's full position track, each row with the assertion
    backing it (unbacked = bypass-writer row, purgeable). Echo: row id,
    mgrs, observed_at, dtg_label, source, backed_by."""
    from app.api.v1 import world_repair as wr
    return await wr.tool_find_positions(project_id, entity)


def mcp_asgi_app():
    """Streamable-HTTP ASGI app (serves /mcp at its root; mounted at
    /api/v1). The session manager runs in the FastAPI lifespan."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TRANSPORT_SECURITY,
    )


def mcp_sse_app():
    """SSE ASGI app (serves /sse + /messages/ at its root; mounted at
    /api/v1/mcp-sse BEFORE the /api/v1 mount). Sessions are born ready
    so Claude Code's reconnect-without-reinitialize flow keeps working
    across backend deploys — the contract, and the SDK v2 mechanics
    that satisfy it, live in app/mcp_transport.py."""
    return stateless_sse_app(mcp)
