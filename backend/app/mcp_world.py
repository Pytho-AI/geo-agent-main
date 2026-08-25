"""Second MCP server — the world-model INGESTION tool surface (milestone 4).

Design of record: scratch/docs/oob/tool-surface-consolidation.md — S7 (agent-
facing tool surface), S7.1 (bound context), S8 (steering). This is the "another
MCP server" of the build plan: it stands alongside the existing geo-agent OOB
server (app/mcp_server.py) and exposes ONLY the ingestion agent's surface. Every
tool binds its context from the ONE active ingestion run (the model never names
a run, project, branch, or destination — design S7.1) and returns the recomputed
ingestion_context + steering. Handlers live in app/services/world/tools.py; this
module only adapts them to MCP.

Run creation, activation, phase barriers, and commit are CONTROL-PLANE
operations (design S7.13) — they are not tools here; the operator / API / product
engine drives them via services.world.tools control functions.
"""
from typing import List, Optional

from mcp.server.mcpserver import MCPServer, Image

from app.mcp_transport import TRANSPORT_SECURITY, stateless_sse_app

from app.services.world import tools as w
from app.services.graph_ingest import tools as t

_INSTRUCTIONS = (
    "World-model INGESTION surface (military training simulation). You are the "
    "ingestion agent driving ONE active run bound by the server; you never name "
    "a run, project, source, branch, or destination. Every response carries an "
    "ingestion_context block and a steering message — READ THEM and do exactly "
    "the next call steering names. Flow: read_source in order; for each section "
    "whose successor is visible, assert_section ONCE with its complete "
    "outermost-to-innermost heading path, verbatim text, and source_refs, plus "
    "its section-local entities and atomic clauses (with entity_values and "
    "links); hold the trailing section on the final visible view until the next "
    "view establishes its end. When the source is exhausted and the last section "
    "is asserted, resolve_entity_aliases: group the server-returned occurrence "
    "refs that name the same entity, binding each group with entity_ref (an "
    "existing entity from search_world/read_world) or new_entity (a distinct "
    "identity). Section text is the VERBATIM passage; a clause is an atomic "
    "interpretation and is never the passage. Every occurrence binding is YOUR "
    "decision — a matching name or identifier is only a candidate. Ids are "
    "server-issued; never invent one. Relative DTGs resolve against the "
    "project temporal anchors or the item is rejected."
)

# SDK v2: transport parameters moved off the constructor onto the app
# builders below.
mcp = MCPServer("world-model-ingestion", instructions=_INSTRUCTIONS)


# ── Reads ────────────────────────────────────────────────────────────

@mcp.tool()
async def read_source(cursor: Optional[str] = None,
                      source_refs: Optional[List[str]] = None):
    """Present ONE source page at the cursor as its rendered IMAGE (design S7.3).
    Returns the single view's ref/kind/label/ordinal, next_cursor, source_end,
    and total_views, followed by that page's rendered image. Process ONE page
    per call: assert every section whose successor is visible on this page, HOLD
    the section running off the bottom of the page, then call again with
    next_cursor for the next page. A window is never returned, so you cannot read
    ahead — the held trailing section resolves when its successor appears on the
    next page. Omit cursor to start at page one; source_end true means this was
    the last page (assert the held section)."""
    result = await w.read_source(cursor=cursor, source_refs=source_refs)
    meta, img = result if isinstance(result, tuple) else (result, None)
    if img is None:
        return meta
    return [meta, Image(data=img, format="jpeg")]


@mcp.tool()
async def search_world(text: Optional[str] = None,
                       kinds: Optional[List[str]] = None,
                       affiliation: Optional[str] = None, limit: int = 20) -> dict:
    """Candidate search over the project world model for occurrence resolution
    (design S7.4). Matches committed canonical entities by name / type /
    affiliation. Results are CANDIDATES — binding is your decision."""
    return await w.search_world(text=text, kinds=kinds, affiliation=affiliation,
                                limit=limit)


@mcp.tool()
async def read_world(refs: List[str], include_basis: bool = False) -> dict:
    """Exact, side-effect-free read of world-model records by ref (design S7.5);
    up to 100. include_basis returns the committed assertions about each entity."""
    return await w.read_world(refs, include_basis=include_basis)


# ── Writes ───────────────────────────────────────────────────────────

@mcp.tool()
async def assert_section(headings: List[str], text: str,
                         source_refs: Optional[List[str]] = None,
                         entities: Optional[List[dict]] = None,
                         clauses: Optional[List[dict]] = None) -> dict:
    """Assert ONE complete external-source section and its semantic extraction
    (design S7.6). headings: every containing heading, outermost -> innermost
    (empty for an unheaded passage). text: the complete verbatim passage.
    source_refs: every view the section appears on. entities: [{name,
    entity_type, identifiers?, ascope?}] declared once each, unique per
    section — ascope states what the referent IS in civil-considerations
    terms: a list from the closed set areas|structures|capabilities|
    organizations|people|events (an entity may be several: a nation is its
    territory AND its state actor -> ["areas", "organizations"]). clauses:
    [{text, attribution?, pmesii?, valid_from?, valid_to?, entity_values?:
    [{entity, values, valid_from?, valid_to?}], links?: [{from, relation, to,
    properties?, valid_from?, valid_to?}], positions?: [{entity, mgrs?, lat?,
    lon?, mgrs_line?, mgrs_polygon?, geom_wkt?, valid_from?, valid_to?}]}] —
    pmesii states the STATEMENT's PMESII-PT facets, a list from the closed
    set political|military|economic|social|information|infrastructure|
    physical_environment|time (a statement often carries more than one:
    "Murinus maintains 375,000 active forces" is political AND military).
    Tag every clause and every entity you can — an untagged record joins no
    facet read downstream; an unknown tag rejects the section. A position
    gives an entity a located observation: a POINT (an MGRS grid e.g.
    "34U FE 13198 65979", or lat/lon), a LINESTRING (mgrs_line: [grid, ...] — a
    linear control measure: FSCL, phase line, boundary), a POLYGON (mgrs_polygon:
    [grid, ...] — an area: engagement area, AO), or a verbatim geom_wkt; its
    valid_from is the observation time (defaults to the clause's). Extract
    EXHAUSTIVELY: every subject the passage names is an entity and every
    predicate it states is a typed link — nothing meaningful goes into free
    text. A link's relation is any predicate; an existing registry type
    matches as-is and an unseen predicate MINTS a new relationship type on
    first use (the same freedom new_entity gives), so an unfamiliar predicate
    is never a reason to collapse a relationship into a note. No ids, keys,
    parents, order, quotes, or offsets — the server assigns them. A validation
    error rejects the WHOLE section with its payload path."""
    return await w.assert_section(headings=headings, text=text,
                                  source_refs=source_refs, entities=entities,
                                  clauses=clauses)


@mcp.tool()
async def assert_section_semantics(section_id: str,
                                   entities: Optional[List[dict]] = None,
                                   clauses: Optional[List[dict]] = None) -> dict:
    """Attach semantics to the current bound system-created Section (design
    S7.7). section_id is the ref from ingestion_context.current_stored_section.
    Supply ONLY entities + clauses (same shape as assert_section) — the section's
    text, headings, and references are already stored and are not accepted here."""
    return await w.assert_section_semantics(section_id=section_id,
                                            entities=entities, clauses=clauses)


@mcp.tool()
async def resolve_entity_aliases(decisions: List[dict]) -> dict:
    """Bind section-local occurrences to canonical entities (design S7.8).
    decisions: [{occurrence_refs: [ref], entity_ref} | {occurrence_refs: [ref],
    new_entity: {canonical_name, entity_type, ascope?}}]. Grouping refs states
    they name the same entity. new_entity.ascope (closed set, same as
    assert_section) outranks the occurrences' stated ascope; otherwise the
    first stated occurrence value propagates to the canonical entity. Every
    binding is your decision."""
    return await w.resolve_entity_aliases(decisions)


@mcp.tool()
async def supersede(items: List[dict]) -> dict:
    """Stage explicit basis-backed replacements (design S7.10). Item: {old,
    replacement, basis}. Use only when the source states a prior claim is
    replaced."""
    return await w.supersede(items)


@mcp.tool()
async def retract(items: List[dict]) -> dict:
    """Stage a basis-backed logical retraction of destination-visible content
    (design S7.11). Item: {ref, basis}. Use only when the source states a prior
    claim is withdrawn; history is preserved."""
    return await w.retract(items)


@mcp.tool()
async def advance() -> dict:
    """Declare the current phase complete and advance the run. Call it when: you
    have asserted the FINAL section of the source (advances to entity
    resolution); you have bound EVERY occurrence with resolve_entity_aliases
    (advances to duplicate review); and after review (commits this source,
    publishes it, and admits the next queued source). After a commit, call
    read_source again — it serves the next source's first page, or reports no
    active run once every source is done. YOU decide when each phase is finished;
    advance is your declaration."""
    return await w.advance()


# ── Spatial utilities (design S7.12) — deterministic, return candidates ──

@mcp.tool()
async def geocode(queries: List[dict]) -> dict:
    """Resolve place names or coordinates to equivalent forms plus nearby named
    places, batched (design S7.12). Item: {query, west?, south?, east?, north?}.
    Returns candidates, not assertions."""
    return await t.tool_geocode_places(queries, None)


@mcp.tool()
async def snap_to_feature(points: List[dict]) -> dict:
    """Snap points onto the nearest OSM linear feature, batched (design S7.12).
    Item: {lat, lon, feature: 'railway'|'road', radius_m?}. Returns candidates."""
    return await t.tool_snap_to_feature(points)


@mcp.tool()
async def project_points(items: List[dict]) -> dict:
    """Offset points by bearing/distance, batched (design S7.12). Item: {lat,
    lon, bearing_deg, distance_km} -> destination point in lat/lon/MGRS."""
    return await t.tool_project_points(items)


# Control-plane operations are NOT agent tools (design S7.13): source capture,
# run creation, activation, the phase barriers (resolution/review), and commit
# involve no model judgment and are the OPERATOR / API / product engine's job,
# not the ingestion agent's. They are HTTP endpoints, not MCP tools —
# POST /api/v1/sources (capture) and POST /api/v1/runs/{source,product,activate,
# resolve,review,commit} + GET /api/v1/runs/active (app/api/v1/world_sources.py
# + app/api/v1/world_runs.py, over services/world/tools.py). The MCP surface
# above is EXACTLY the ingestion agent's tools.


def mcp_world_asgi_app():
    """Streamable-HTTP ASGI app for the ingestion surface (serves /mcp at its
    root; mounted by main.py at its own path)."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TRANSPORT_SECURITY,
    )


def mcp_world_sse_app():
    """SSE ASGI app, born-ready sessions matching mcp_server.mcp_sse_app
    — the auto-reconnect contract and its SDK v2 mechanics live in
    app/mcp_transport.py."""
    return stateless_sse_app(mcp)
