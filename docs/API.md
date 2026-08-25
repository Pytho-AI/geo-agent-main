# Geo-Spatial Agent — full API

Generated from the FastAPI OpenAPI spec — do not hand-edit.
Regenerate with `scripts/generate_api_docs.py` (see its
docstring). All paths are under the backend's single public
surface, port 9845; through a consumer's nginx they appear
with the `/geo-api` prefix in place of `/api`.

The EXTERNAL integration surface is deliberately tiny — see
README.md "External API". Everything else here is the
embedded map UI's internal API, documented for people working
ON geo-agent.

## artifacts

### `POST /api/v1/artifacts`

Upload File

Upload a geo file (shapefile, geojson, geotiff)

Parameters:
- `map_id` (query) — string (uuid), required
- `user_id` (query) — string, required

Request body (`multipart/form-data`, Body_upload_file_api_v1_artifacts_post):
  - `file` — string, required

Response (`ArtifactResponse`):
  - `id` — string (uuid), required
  - `filename` — string, required
  - `file_type` — string, required
  - `status` — string, required

### `GET /api/v1/artifacts/{artifact_id}`

Get Artifact

Get artifact status

Parameters:
- `artifact_id` (path) — string (uuid), required

Response (`ArtifactResponse`):
  - `id` — string (uuid), required
  - `filename` — string, required
  - `file_type` — string, required
  - `status` — string, required

### `POST /api/v1/artifacts/{artifact_id}/ingest`

Ingest Artifact

Trigger ingestion of an uploaded artifact

Parameters:
- `artifact_id` (path) — string (uuid), required

Response (`IngestResponse`):
  - `artifact_id` — string (uuid), required
  - `status` — string, required
  - `entities_created` — integer, optional, default `0`
  - `overlays_created` — integer, optional, default `0`

## config

### `GET /api/v1/basemaps`

Get Basemaps

Basemap catalog for the analyst-facing map surface.

Returns the four server-rendered basemap raster tiles (default,
terrain, topo, satellite) + the English label PNG overlay. Frontend
populates its LayerSwitcher from this response and points MapLibre
raster sources at the returned tile_urls. Zero tile bytes flow
through this endpoint — metadata only.

Basemap sources (server-side):
  - default + terrain + topo: tileserver-gl renders JPGs from
    Protomaps' public planet PMTiles (basemaps schema) with
    hillshade baked in from Mapterhorn's Terrarium DEM tile
    endpoint. topo additionally gets CLIENT-side contour lines
    (frontend utils/contours.js) — they are not in the raster.
  - satellite: nginx caches ESRI World Imagery tiles at
    server.arcgisonline.com; no local render.

Response (`object (free-form)`):

### `GET /api/v1/config`

Get Config

Get application configuration including all type definitions.

Returns all SIDC codes, overlay types, entity types, and keyword mappings
that the frontend needs to render military symbols and validate input.

In offline mode, also includes `region` with tile bounds and max zoom.

Note: For symbols, use /config/symbols endpoints to avoid large payload.

Response (`object (free-form)`):

### `GET /api/v1/config/sidc`

Get Sidc Config

Get SIDC-related configuration only.

Response (`object (free-form)`):

### `GET /api/v1/config/overlays`

Get Overlay Config

Get overlay types configuration only.

Response (`object (free-form)`):

### `GET /api/v1/config/entities`

Get Entity Config

Get entity types configuration only.

Response (`object (free-form)`):

### `GET /api/v1/config/symbols`

Get Symbols Config

Get all MIL-STD-2525D symbols.

Optionally filter by symbol set code:
- 01: Air
- 02: Air Missile
- 05: Space
- 06: Space Missile
- 10: Land Unit
- 11: Land Civilian
- 15: Land Equipment
- 20: Land Installation
- 25: Control Measure
- 30: Sea Surface
- 35: Sea Subsurface
- 36: Mine Warfare
- 40: Activities
- 50: Signals Intelligence
- 60: Cyberspace

Parameters:
- `symbol_set` (query) — string, optional. Filter by symbol set code (e.g., '10' for Land Unit)

Response (`object (free-form)`):

### `GET /api/v1/config/symbols/search`

Search Symbols Endpoint

Search symbols by name or keywords.

Returns symbols matching the query, sorted by relevance.
The first result is the best match across all symbol sets.

Use limit=1 to get just the best match (for auto-detection).

Parameters:
- `q` (query) — string, required. Search query
- `symbol_set` (query) — string, optional. Filter by symbol set code
- `limit` (query) — integer, optional. Maximum results to return

Response (`object (free-form)`):

### `GET /api/v1/config/symbols/sets`

Get Symbol Sets

Get list of all available symbol sets.

Response (`array of object (free-form)`):

### `GET /api/v1/config/cache`

Get Cache Stats

Get spatial data cache statistics.

Response (`object (free-form)`):

### `DELETE /api/v1/config/cache`

Clear Cache

Clear the spatial data cache.

Parameters:
- `map_id` (query) — string, optional. Clear cache for a specific map, or all if omitted
- `namespace` (query) — string, optional. Clear a specific namespace (viewport_roads, viewport_elevation, viewport_landcover, location_context)

Response (`object (free-form)`):

## cop

### `POST /api/v1/cop/generate`

Generate Cop Endpoint

Generate a Common Operational Picture from a world state narrative.

Creates a new map, extracts all military entities, overlays, and
routes from the narrative via LLM, and returns the structured COP.

Request body (`application/json`, COPGenerateRequest):
  - `world_state` — string, required
  - `user_id` — string, optional, default `"coa-engine"`
  - `forces` — array of ForceEntry, optional
  - `ipoe_products` — string, optional
  - `mission_analysis` — string, optional

Response (`COPGenerateResponse`):
  - `map_id` — string (uuid), required
  - `bbox` — array of number, required
  - `entities` — object (free-form), required
  - `overlays` — object (free-form), required
  - `routes` — array of object (free-form), optional
  - `terrain` — COPTerrainSummary, optional
  - `meta` — object (free-form), required
  - `generation_summary` — string, required

### `GET /api/v1/cop/{map_id}`

Get Cop

Get the current COP for an existing map.

Parameters:
- `map_id` (path) — string (uuid), required

Response (`COPGetResponse`):
  - `map_id` — string (uuid), required
  - `bbox` — array of number, optional
  - `entities` — object (free-form), required
  - `overlays` — object (free-form), required
  - `routes` — array of object (free-form), optional
  - `meta` — object (free-form), required

### `POST /api/v1/cop/generate-coa-map`

Generate Coa Map Endpoint

Generate a COA-specific map from a COP base map.

Clones all entities from the source COP map into a new map, then
extracts tactical overlays (phase lines, avenues of approach,
objectives, etc.) from the COA brief content via LLM.

Request body (`application/json`, COAMapRequest):
  - `source_map_id` — string (uuid), required
  - `coa_number` — integer, required
  - `coa_title` — string, optional
  - `brief_content` — string, required
  - `user_id` — string, optional, default `"coa-engine"`
  - `cop_screenshot_b64` — string, optional

Response (`COAMapResponse`):
  - `map_id` — string (uuid), required
  - `bbox` — array of number, required
  - `entities` — object (free-form), required
  - `overlays` — object (free-form), required
  - `routes` — array of object (free-form), optional
  - `meta` — object (free-form), required

## custom-symbols

### `POST /api/v1/custom-symbols`

Upload Custom Symbol

Parameters:
- `user_id` (query) — string, optional

Request body (`multipart/form-data`, Body_upload_custom_symbol_api_v1_custom_symbols_post):
  - `file` — string, required

Response (`CustomSymbolOut`):
  - `id` — string (uuid), required
  - `name` — string, required
  - `file_format` — string, required
  - `mime_type` — string, required
  - `width` — integer, optional
  - `height` — integer, optional
  - `url` — string, required

### `GET /api/v1/custom-symbols`

List Custom Symbols

Response (`array of CustomSymbolOut`):

### `GET /api/v1/custom-symbols/{symbol_id}/file`

Get Custom Symbol File

Parameters:
- `symbol_id` (path) — string (uuid), required

### `DELETE /api/v1/custom-symbols/{symbol_id}`

Delete Custom Symbol

Parameters:
- `symbol_id` (path) — string (uuid), required

## entities

### `GET /api/v1/entities/{entity_id}`

Get Entity

Get a single entity by ID

Parameters:
- `entity_id` (path) — string (uuid), required

Response (`EntityResponse`):
  - `kind` — string, required
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional
  - `confidence` — number, optional, default `1.0`
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `created_by` — string, required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `PUT /api/v1/entities/{entity_id}`

Update Existing Entity

Update an existing entity (geometry, attrs, or confidence)

Parameters:
- `entity_id` (path) — string (uuid), required

Request body (`application/json`, EntityUpdate):
  - `geom` — GeoJSON, optional
  - `attrs` — object (free-form), optional
  - `confidence` — number, optional

Response (`EntityResponse`):
  - `kind` — string, required
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional
  - `confidence` — number, optional, default `1.0`
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `created_by` — string, required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `DELETE /api/v1/entities/{entity_id}`

Delete Existing Entity

Delete an entity by ID

Parameters:
- `entity_id` (path) — string (uuid), required

### `POST /api/v1/entities`

Create New Entity

Create a new entity

Parameters:
- `map_id` (query) — string (uuid), required
- `user_id` (query) — string, required

Request body (`application/json`, EntityCreate):
  - `kind` — string, required
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional
  - `confidence` — number, optional, default `1.0`

Response (`EntityResponse`):
  - `kind` — string, required
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional
  - `confidence` — number, optional, default `1.0`
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `created_by` — string, required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

## entity-graph

### `GET /api/v1/graph/templates`

List Templates

### `GET /api/v1/graph/postures`

List Postures

The posture values the disposition engine supports — the
placard's posture selector reads this list, never a hardcoded
copy (registered before /graph/{project_id} so 'postures' never
parses as a project UUID).

### `POST /api/v1/graph/nodes/{node_id}/rearray`

Rearray Formation

Re-run the doctrinal disposition for ONE formation's subtree —
the placard's posture selector calls this after setting posture so
the subordinates re-array at the selected posture's spacing.
Document-stated placements are never touched; only positions whose
newest observation came from a doctrinal-disposition pass move.

Parameters:
- `node_id` (path) — string (uuid), required

### `GET /api/v1/graph/{project_id}`

Bulk Read

Parameters:
- `project_id` (path) — string (uuid), required

### `GET /api/v1/graph/nodes/{node_id}/card`

Node Card

Placard-shaped read for ONE node: the unit, its organic parent,
its organic children (each with a composed SIDC + position so the
placard can draw the symbol and fly the camera to it), equipment
rolled up across the organic subtree, and the governing position
observation (provenance). One fetch per placard open.

Parameters:
- `node_id` (path) — string (uuid), required

### `GET /api/v1/graph/nodes/{node_id}/brief`

Node Brief

The as-of resolver — the world model's placard read: the node's
updatable attributes as supersession CHAINS (History), every
statement's provenance (Sources), the doctrine clauses governing its
template (Doctrine), and the position resolved at the scrub time
(observed_at — the record's one temporal dimension). One shape
serves the placard now and the timeline scrub at any t.

Parameters:
- `node_id` (path) — string (uuid), required
- `as_of` (query) — string (date-time), optional. resolve state at this instant; omitted = now

### `GET /api/v1/oob/{project_id}`

Oob Read

The ORDER OF BATTLE read — the movable-force subset. Pruning
contract: parents elide through fixed ancestors to the nearest
MOVABLE ancestor (parent_elided: true); fixed children are pruned;
no dangling parent uuids, ever.

Parameters:
- `project_id` (path) — string (uuid), required

### `POST /api/v1/graph/{project_id}/nodes`

Create Node

Parameters:
- `project_id` (path) — string (uuid), required

Request body (`application/json`, NodeCreate):
  - `entity_type` — string, required
  - `name` — string, required
  - `long_name` — string, optional
  - `affiliation` — string, optional, default `"Unknown"`
  - `category` — string, optional
  - `lon` — number, optional
  - `lat` — number, optional
  - `posture` — string, optional
  - `organic_parent_id` — string (uuid), optional
  - `weg_id` — string, optional
  - `unit_type` — string, optional
  - `echelon` — string, optional
  - `personnel_authorized` — integer, optional
  - `personnel_current` — integer, optional
  - `significance` — string, optional
  - `significance_note` — string, optional
  - `current_activity` — string, optional
  - `notes` — string, optional
  - `created_by` — string, optional

### `PATCH /api/v1/graph/nodes/{node_id}`

Update Node

Parameters:
- `node_id` (path) — string (uuid), required

Request body (`application/json`, NodeUpdate):
  - `entity_type` — string, optional
  - `name` — string, optional
  - `long_name` — string, optional
  - `affiliation` — string, optional
  - `category` — string, optional
  - `lon` — number, optional
  - `lat` — number, optional
  - `posture` — string, optional
  - `organic_parent_id` — string (uuid), optional
  - `clear_organic_parent` — boolean, optional, default `false`
  - `weg_id` — string, optional
  - `unit_type` — string, optional
  - `echelon` — string, optional
  - `personnel_authorized` — integer, optional
  - `personnel_current` — integer, optional
  - `personnel_killed` — integer, optional
  - `personnel_wounded` — integer, optional
  - `personnel_captured` — integer, optional
  - `combat_effectiveness` — string, optional
  - `assessment_basis` — string, optional
  - `significance` — string, optional
  - `significance_note` — string, optional
  - `current_activity` — string, optional
  - `notes` — string, optional
  - `symbol_set` — string, optional
  - `symbol_entity_code` — string, optional
  - `symbol_mod1` — string, optional
  - `symbol_mod2` — string, optional
  - `updated_by` — string, optional

### `DELETE /api/v1/graph/nodes/{node_id}`

Delete Node

Parameters:
- `node_id` (path) — string (uuid), required

### `POST /api/v1/graph/{project_id}/edges`

Create Edge

Parameters:
- `project_id` (path) — string (uuid), required

Request body (`application/json`, EdgeCreate):
  - `from_id` — string (uuid), required
  - `to_id` — string (uuid), required
  - `relationship_type` — string, required
  - `note` — string, optional
  - `close_prior` — boolean, optional, default `false`
  - `created_by` — string, optional

### `PATCH /api/v1/graph/edges/{edge_id}`

Update Edge

Parameters:
- `edge_id` (path) — string (uuid), required

Request body (`application/json`, EdgeUpdate):
  - `effective_to` — string (date-time), optional
  - `note` — string, optional

### `DELETE /api/v1/graph/edges/{edge_id}`

Delete Edge

Parameters:
- `edge_id` (path) — string (uuid), required

### `POST /api/v1/graph/nodes/{node_id}/holdings`

Create Holding

Parameters:
- `node_id` (path) — string (uuid), required

Request body (`application/json`, HoldingCreate):
  - `weg_id` — string, optional
  - `nomenclature_raw` — string, optional
  - `count_authorized` — integer, optional
  - `count_current` — integer, optional
  - `created_by` — string, optional

### `PATCH /api/v1/graph/holdings/{holding_id}`

Update Holding

Parameters:
- `holding_id` (path) — string (uuid), required

Request body (`application/json`, HoldingUpdate):
  - `weg_id` — string, optional
  - `count_authorized` — integer, optional
  - `count_current` — integer, optional
  - `count_degraded` — integer, optional
  - `count_neutralized` — integer, optional
  - `count_destroyed` — integer, optional
  - `count_captured_abandoned` — integer, optional
  - `teach_alias` — boolean, optional, default `false`
  - `updated_by` — string, optional

### `DELETE /api/v1/graph/holdings/{holding_id}`

Delete Holding

Parameters:
- `holding_id` (path) — string (uuid), required

### `PUT /api/v1/graph/nodes/{node_id}/fields/{field_key}`

Put Node Field

Parameters:
- `node_id` (path) — string (uuid), required
- `field_key` (path) — string, required

Request body (`application/json`, FieldValuePut):
  - `value` — string, required
  - `updated_by` — string, optional

### `DELETE /api/v1/graph/nodes/{node_id}/fields/{field_key}`

Delete Node Field

Parameters:
- `node_id` (path) — string (uuid), required
- `field_key` (path) — string, required

### `GET /api/v1/graph-registries`

List Registries

The registries' READ side. The tabs only ever had POST/DELETE —
they rendered empty against fully seeded registries.

### `POST /api/v1/graph-registries/entity-types`

Upsert Entity Type

Request body (`application/json`, EntityTypeUpsert):
  - `type_key` — string, required
  - `label` — string, required
  - `color` — string, optional
  - `is_fixed` — boolean, optional
  - `symbol_set` — string, optional
  - `symbol_entity_code` — string, optional
  - `default_category` — string, optional
  - `updated_by` — string, optional

### `DELETE /api/v1/graph-registries/entity-types/{type_key}`

Delete Entity Type

Parameters:
- `type_key` (path) — string, required

### `POST /api/v1/graph-registries/relationship-types`

Upsert Relationship Type

Request body (`application/json`, RelationshipTypeUpsert):
  - `type_key` — string, required
  - `label` — string, required
  - `inverse_label` — string, required
  - `color` — string, optional
  - `is_hierarchical` — boolean, optional
  - `updated_by` — string, optional

### `DELETE /api/v1/graph-registries/relationship-types/{type_key}`

Delete Relationship Type

Parameters:
- `type_key` (path) — string, required

### `POST /api/v1/graph-registries/field-defs`

Upsert Field Def

Request body (`application/json`, FieldDefUpsert):
  - `field_key` — string, required
  - `label` — string, required
  - `value_type` — string, optional
  - `updated_by` — string, optional

### `DELETE /api/v1/graph-registries/field-defs/{field_key}`

Delete Field Def

Parameters:
- `field_key` (path) — string, required

### `GET /api/v1/equipment`

List Equipment

Paginated, filterable catalog read: {total, rows}. Search also
matches taught aliases (a query for a reporting name like DOG EAR
must find its system).

Parameters:
- `q` (query) — string, optional
- `domain` (query) — string, optional
- `class` (query) — string, optional
- `category` (query) — string, optional
- `tier` (query) — integer, optional
- `country` (query) — string, optional
- `offset` (query) — integer, optional
- `limit` (query) — integer, optional

### `POST /api/v1/equipment`

Upsert Equipment

Request body (`application/json`, EquipmentUpsert):
  - `weg_id` — string, required
  - `name` — string, required
  - `domain` — string, optional
  - `class` — string, optional
  - `category` — string, optional
  - `tier` — integer, optional
  - `engagement_range_m` — integer, optional
  - `detection_range_m` — integer, optional
  - `road_speed_kph` — integer, optional
  - `crew` — integer, optional
  - `caliber` — string, optional
  - `date_of_introduction` — string, optional
  - `proliferation_note` — string, optional
  - `symbol_entity_code` — string, optional
  - `symbol_mod1` — string, optional
  - `symbol_mod2` — string, optional
  - `updated_by` — string, optional

### `GET /api/v1/equipment/facets`

Equipment Facets

Distinct filter values + counts for the catalog filter bar.

### `GET /api/v1/equipment/tokens`

Equipment Tokens

Lightweight full-catalog token feed for the WEG-sheet cross-link
matcher: every system's id, name, and taught aliases — never
paginated, so a late-alphabet system can always be linked.

### `GET /api/v1/equipment/{weg_id}/image`

Equipment Image

The system's photograph, bulk-extracted from the WEG PDF's
embedded images (decision 24) — the picker doubles as a searchable
illustrated catalog.

Parameters:
- `weg_id` (path) — string, required

### `POST /api/v1/equipment/{weg_id}/aliases`

Add Alias

Parameters:
- `weg_id` (path) — string, required
- `alias` (query) — string, required

### `POST /api/v1/graph/templates/{key}/instantiate`

Instantiate Template

Parameters:
- `key` (path) — string, required

Request body (`application/json`, TemplateInstantiate):
  - `project_id` — string (uuid), required
  - `parent_id` — string (uuid), optional
  - `lon` — number, optional
  - `lat` — number, optional
  - `affiliation` — string, optional
  - `created_by` — string, optional

### `POST /api/v1/graph/{project_id}/templates`

Save As Template

Parameters:
- `project_id` (path) — string (uuid), required

Request body (`application/json`, TemplateSave):
  - `key` — string, required
  - `name` — string, required
  - `root_node_id` — string (uuid), required
  - `capture` — string, optional, default `"organic"`
  - `created_by` — string, optional

### `POST /api/v1/graph/{project_id}/ingest-oob`

Ingest Oob Endpoint

CRUD a canonical ExtractedOOB payload into the project's graph.
Any extractor (this service's VLM, a Sonnet agent, a fixture) can
call this. wipe_first clears the project graph for a clean
re-ingest. Returns the IngestReport.

Parameters:
- `project_id` (path) — string (uuid), required
- `wipe_first` (query) — boolean, optional
- `created_by` (query) — string, optional

Request body (`application/json`, object (free-form)):
  - (see schema)

### `POST /api/v1/graph/{project_id}/snapshot`

Snapshot Project

Capture a full-project graph snapshot on demand (nodes, edges,
holdings, positions, fields, episodic clauses).

Parameters:
- `project_id` (path) — string (uuid), required
- `label` (query) — string, optional
- `created_by` (query) — string, optional

### `GET /api/v1/graph/{project_id}/snapshots`

List Snapshots

Parameters:
- `project_id` (path) — string (uuid), required

### `POST /api/v1/graph/snapshots/{snapshot_id}/restore`

Restore Snapshot

Restore a project's graph to a snapshot. The current state is
snapshot itself (pre_restore) first, so restore is undoable.

Parameters:
- `snapshot_id` (path) — string (uuid), required

### `GET /api/v1/graph/{project_id}/source-documents`

List Source Documents

L0 reads: the verbatim ingested documents (the provenance roots
the register's clauses cite). include_text=true returns the full
text for the Sources quote view.

Parameters:
- `project_id` (path) — string (uuid), required
- `include_text` (query) — boolean, optional

### `POST /api/v1/graph/{project_id}/attributes/backfill`

Backfill Attributes

Seed observation-chain roots from curated column state: every
state-attribute value with no existing chain becomes the initial
observation (speaker curation), so hand-set state survives all
future ingests as history instead of being overwritable.

Parameters:
- `project_id` (path) — string (uuid), required

### `POST /api/v1/graph/{project_id}/register/recompute`

Recompute Register

Re-run the episodic register's deterministic supersession pass
over the project's existing clauses (idempotent, append-only —
no extraction, no LLM). The operational trigger for applying a
supersession-semantics fix to already-registered clauses.

Parameters:
- `project_id` (path) — string (uuid), required

### `POST /api/v1/graph/{project_id}/ingest-doc`

Ingest Doc Endpoint

Run the staged document→graph pipeline for ONE OR MANY project
documents at once (define AO → extract OOB → geocode placements inside
the AO → CRUD into the graph → visually confirm ambiguous placements).
Passing all of a scenario's documents together yields ONE consolidated
order of battle (no sequential per-doc merge). `document_kind=frago`
applies an incremental update against the existing graph. Returns the
IngestReport, the AO, the placement summary, and extracted counts.

Parameters:
- `project_id` (path) — string (uuid), required
- `wipe_first` (query) — boolean, optional
- `document_kind` (query) — string, optional
- `created_by` (query) — string, optional

Request body (`multipart/form-data`, Body_ingest_doc_endpoint_api_v1_graph__project_id__ingest_doc_post):
  - `files` — array of string, required

### `POST /api/v1/graph/{project_id}/wipe`

Wipe Project Graph

Deletes EVERY graph row in the project — entities, edges,
holdings, field values, analyst edits included. The UI fronts this
with a styled confirm modal that says exactly that. A pre_wipe
snapshot is captured first, so even a wipe is one restore away.

Parameters:
- `project_id` (path) — string (uuid), required

## events

### `POST /api/v1/events`

Ingest Events

Request body (`application/json`, object (free-form)):
  - (see schema)

Response (`object (free-form)`):

### `GET /api/v1/events`

Query Events

Parameters:
- `map_id` (query) — string, optional
- `user_id` (query) — string, optional
- `event_type` (query) — string, optional. Exact type, or a prefix ending in '*' (e.g. client_log.*)
- `since_ms` (query) — integer, optional
- `until_ms` (query) — integer, optional
- `limit` (query) — integer, optional

Response (`object (free-form)`):

### `POST /api/v1/events/client-log`

Ingest Client Log

Request body (`application/json`, ClientLogIn):
  - `level` — string, optional, default `"info"`
  - `label` — string, optional
  - `message` — string, optional
  - `url` — string, optional
  - `user_agent` — string, optional
  - `stack` — string, optional
  - `context` — object (free-form), optional
  - `user_id` — string, optional
  - `map_id` — string, optional

Response (`object (free-form)`):

## geocode

### `GET /api/v1/geocode`

Geocode Endpoint

Parameters:
- `q` (query) — string, required. place name to resolve
- `bbox` (query) — string, optional. AO bbox w,s,e,n — candidates are drawn only from inside it
- `near` (query) — string, optional. lon,lat bias point
- `limit` (query) — integer, optional

Response (`object (free-form)`):

## geoops

### `POST /api/v1/geoops`

Execute Operations

Execute a batch of geo operations (create, move, update, delete)

Request body (`application/json`, GeoOpsRequest):
  - `map_id` — string (uuid), required
  - `user_id` — string, required
  - `ops` — array of CreateEntity | MoveEntity | UpdateEntity | DeleteEntity | CreateOverlay | DeleteOverlay | CreateRoute | DeleteRoute, required

Response (`GeoOpsResponse`):
  - `results` — array of GeoOpsResult, required

## map

### `GET /api/v1/map/state`

Get State

Get combined map state (entities + overlays) for rendering

Parameters:
- `map_id` (query) — string (uuid), required
- `bbox` (query) — string, optional. min_lon,min_lat,max_lon,max_lat
- `kinds` (query) — string, optional. Comma-separated list of kinds
- `as_of` (query) — string (date-time), optional. Timeline scrub: paint graph features at their latest observation at or before this time (ISO 8601). Omit for the live newest-wins state.

Response (`object (free-form)`):

### `GET /api/v1/map/state/track-frames`

Get Track Frames

DATED point observations per MOVABLE unit, oldest-first — the
client-side data for the timeline scrubber. Dragging resolves each
unit's position locally per tick (a scrubber must track the thumb,
not a network round trip); the authoritative as_of fetch reconciles
on release. Timeless features (control measures, fixed sites, units
with no dated history) are absent — the client leaves them be.

Parameters:
- `map_id` (query) — string (uuid), required

Response (`object (free-form)`):

## maps

### `GET /api/v1/maps`

List Maps

List all maps, optionally filtered by user_id

Parameters:
- `user_id` (query) — string, optional

Response (`MapListResponse`):
  - `maps` — array of MapResponse, required
  - `total` — integer, required

### `POST /api/v1/maps`

Create Map

Create a new map

Request body (`application/json`, MapCreate):
  - `name` — string, required
  - `user_id` — string, required
  - `bbox_west` — number, optional
  - `bbox_south` — number, optional
  - `bbox_east` — number, optional
  - `bbox_north` — number, optional
  - `center_lng` — number, optional
  - `center_lat` — number, optional
  - `zoom` — number, optional, default `8`
  - `attrs` — object (free-form), optional

Response (`MapResponse`):
  - `id` — string (uuid), required
  - `name` — string, required
  - `user_id` — string, required
  - `bbox_west` — number, required
  - `bbox_south` — number, required
  - `bbox_east` — number, required
  - `bbox_north` — number, required
  - `center_lng` — number, required
  - `center_lat` — number, required
  - `zoom` — number, required
  - `attrs` — object (free-form), required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `GET /api/v1/maps/{map_id}`

Get Map

Get a map by ID, creating a blank one if it doesn't exist.

Maps are scoped per project/event and the map id IS the projectId
(consumer contract), so the first open of a new project's map
materializes the blank record right here — no consumer needs a
separate "create the project map" step and the frontend carries no
default-map fallback. Viewport columns stay NULL so the client
resolves its normal chain (saved viewport → offline region →
/config defaultView → neutral world view) until the first viewport
save or producer push supplies one.

Parameters:
- `map_id` (path) — string (uuid), required

Response (`MapResponse`):
  - `id` — string (uuid), required
  - `name` — string, required
  - `user_id` — string, required
  - `bbox_west` — number, required
  - `bbox_south` — number, required
  - `bbox_east` — number, required
  - `bbox_north` — number, required
  - `center_lng` — number, required
  - `center_lat` — number, required
  - `zoom` — number, required
  - `attrs` — object (free-form), required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `PUT /api/v1/maps/{map_id}`

Update Or Create Map

Update an existing map or create it if it doesn't exist (upsert)

Parameters:
- `map_id` (path) — string (uuid), required
- `user_id` (query) — string, optional

Request body (`application/json`, MapUpdate):
  - `name` — string, optional
  - `bbox_west` — number, optional
  - `bbox_south` — number, optional
  - `bbox_east` — number, optional
  - `bbox_north` — number, optional
  - `center_lng` — number, optional
  - `center_lat` — number, optional
  - `zoom` — number, optional
  - `attrs` — object (free-form), optional

Response (`MapResponse`):
  - `id` — string (uuid), required
  - `name` — string, required
  - `user_id` — string, required
  - `bbox_west` — number, required
  - `bbox_south` — number, required
  - `bbox_east` — number, required
  - `bbox_north` — number, required
  - `center_lng` — number, required
  - `center_lat` — number, required
  - `zoom` — number, required
  - `attrs` — object (free-form), required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `DELETE /api/v1/maps/{map_id}`

Delete Map

Delete a map and all its entities/overlays

Parameters:
- `map_id` (path) — string (uuid), required

### `POST /api/v1/maps/{map_id}/clear`

Clear Map

Clear all entities, overlays, and routes from a map (keeps the map itself)

Parameters:
- `map_id` (path) — string (uuid), required

### `POST /api/v1/maps/{map_id}/sync`

Sync Map Layer

Atomic replace of one tagged layer on a map.

One live operating picture per AOR: pytho-app's producers (the
live_oob order-of-battle push, scenario ingest, per-product writer
mirrors) POST full source-tagged snapshots here. Delete-by-source +
insert run in a single transaction; partial-success states aren't
observable.

Request body:
    {
      "overlays": [
        {"kind": "<str>", "name": "<str?>", "geom": <GeoJSON>,
         "attrs": {"source": "<source tag>", "source_kbid": "...", ...}},
        ...
      ],
      "entities": [
        {"kind": "<str>", "name": "<str?>", "geom": <GeoJSON>,
         "attrs": {...}, "confidence": <float?>},
        ...
      ]
    }

Returns:
    {
      "map_id": "<uuid>", "source": "<tag>",
      "overlays_deleted": N, "overlays_inserted": M,
      "entities_deleted": N, "entities_inserted": M,
      "duration_ms": <int>
    }

Validation: every row must have a `kind` recognized by
get_overlay_kinds() (for overlays) or get_entity_kinds() (for entities),
and a non-null `geom`. Rejected rows return 422 with offending indices —
the transaction is NOT committed if any row fails validation, so the
map keeps its previous state.

The `attrs.source` field on incoming rows is REPLACED with the query-
param `source` value before insert so the tag is always authoritative
(a buggy caller can't smuggle in rows tagged as a different source).

Parameters:
- `map_id` (path) — string (uuid), required
- `source` (query) — string, optional. Tag matched against attrs.source. The endpoint deletes every overlay+entity on this map whose attrs.source equals this value, then inserts the payload rows. Non-matching rows (e.g. roads seeded from OSM with attrs.source='osm') are untouched. Every production caller passes this explicitly (live_oob, scenario_terrain, opord, writer, or a product key).
- `user_id` (query) — string, optional

Request body (`application/json`, object (free-form)):
  - (see schema)

## natural-language

### `POST /api/v1/nl/query`

Nl Query

Natural language query over geo data

Request body (`application/json`, NLQueryRequest):
  - `text` — string, required
  - `map_id` — string (uuid), required
  - `user_id` — string, required
  - `bbox` — array of number, optional

Response (`NLQueryResponse`):
  - `answer` — string, required
  - `entities` — array of object (free-form), optional
  - `overlays` — array of object (free-form), optional
  - `suggested_filters` — object (free-form), optional

### `POST /api/v1/nl/update`

Nl Update

Natural language update (create, move, modify entities/overlays)

Request body (`application/json`, NLUpdateRequest):
  - `text` — string, required
  - `map_id` — string (uuid), required
  - `user_id` — string, required

Response (`NLUpdateResponse`):
  - `success` — boolean, required
  - `message` — string, required
  - `ops_executed` — array of object (free-form), optional

### `POST /api/v1/nl/chat`

Nl Chat

Natural language chat for map operations.

This endpoint parses user intent and returns proposed operations
for approval before execution. The actual execution happens via
the /geoops endpoint after user confirmation.

Returns:
    - message: Human-readable description of proposed action
    - proposed_ops: List of GeoOps to execute if approved
    - requires_approval: True if operations need user confirmation
    - clarification_needed: If set, indicates more info is needed

Request body (`application/json`, NLChatRequest):
  - `text` — string, required
  - `map_id` — string (uuid), required
  - `user_id` — string, required
  - `bbox` — array of number, optional
  - `conversation_history` — array of ChatMessage, optional

Response (`NLChatResponse`):
  - `message` — string, required
  - `proposed_ops` — array of object (free-form), required
  - `requires_approval` — boolean, required
  - `clarification_needed` — string, optional

## overlays

### `GET /api/v1/overlays/kinds`

List Overlay Kinds

Get all available overlay kinds

Response (`array of string`):

### `GET /api/v1/overlays/{overlay_id}`

Get Overlay

Get a single overlay by ID

Parameters:
- `overlay_id` (path) — string (uuid), required

Response (`OverlayResponse`):
  - `kind` — string, required
  - `name` — string, optional
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `created_by` — string, required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `PUT /api/v1/overlays/{overlay_id}`

Update Existing Overlay

Update an existing overlay

Parameters:
- `overlay_id` (path) — string (uuid), required

Request body (`application/json`, OverlayUpdate):
  - `kind` — string, optional
  - `name` — string, optional
  - `geom` — GeoJSON, optional
  - `attrs` — object (free-form), optional

Response (`OverlayResponse`):
  - `kind` — string, required
  - `name` — string, optional
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `created_by` — string, required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `DELETE /api/v1/overlays/{overlay_id}`

Delete Existing Overlay

Delete an overlay by ID

Parameters:
- `overlay_id` (path) — string (uuid), required

### `POST /api/v1/overlays`

Create New Overlay

Create a new overlay

Parameters:
- `map_id` (query) — string (uuid), required
- `user_id` (query) — string, required

Request body (`application/json`, OverlayCreate):
  - `kind` — string, required
  - `name` — string, optional
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional

Response (`OverlayResponse`):
  - `kind` — string, required
  - `name` — string, optional
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `attrs` — object (free-form), optional
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `created_by` — string, required
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

## render

### `POST /api/v1/render`

Render Map

Request body (`application/json`, RenderRequest):
  - `product_type` — string, optional
  - `map_uuid` — string, optional
  - `artifact_id` — string, optional
  - `basemap` — string, optional
  - `width` — integer, optional, default `1920`
  - `height` — integer, optional, default `1080`
  - `pixel_ratio` — number, optional, default `1.5`
  - `wait_ms` — integer, optional, default `60000`
  - `bbox` — array of number, optional
  - `layers` — array of string, optional
  - `allowed_kinds` — array of string, optional
  - `basemap_layer_visibility` — array of string, optional
  - `doctrinal_layer_visibility` — array of string, optional
  - `show_topographic_contours` — boolean, optional
  - `cluster_mil_units` — boolean, optional
  - `compact_aa_labels` — boolean, optional
  - `compact_legend_labels` — boolean, optional
  - `fast` — boolean, optional, default `false`
  - `params` — object (free-form), optional
  - `persist` — boolean, optional, default `false`
  - `replay` — boolean, optional, default `false`

### `GET /api/v1/render/spec/{map_uuid}`

Render Spec

Last render spec stashed for a map (the replay base) — INTERNAL.

The live/edit map surface reads this to inherit the product's
render primitives without any consumer forwarding them: the
product-generation render stashes its spec (basemap, layer
visibility, show_topographic_contours, …), and the analyst-facing
OperationsMap then paints to the same primitives the exported
artifact will use (today: the contour overlay gate). Product-
agnostic by construction — geo-agent never maps product_type to
behavior client-side; the stashed spec IS the product's declared
configuration. 404 when the map has never been product-rendered
(e.g. a project master map) — callers treat that as "no product
presets".

Parameters:
- `map_uuid` (path) — string, required

Response (`object (free-form)`):

### `GET /api/v1/render/latest/{map_uuid}.jpg`

Latest Render

Most recent persisted render for a map (written by POST /render
with persist=true). The edit-session done hook hands consumers this
URL; their document-refresh downloads it instead of re-rendering.

Parameters:
- `map_uuid` (path) — string, required

## routes

### `GET /api/v1/routes/options`

List Route Options

Get available route modes.

### `GET /api/v1/routes`

List Routes

Get routes for a map, optionally filtered by status or bounding box.

Parameters:
- `map_id` (query) — string (uuid), required
- `status` (query) — string, optional
- `bbox` (query) — string, optional. min_lon,min_lat,max_lon,max_lat

Response (`array of RouteResponse`):

### `POST /api/v1/routes`

Create New Route

Create a new route (optionally with initial paths).

Parameters:
- `map_id` (query) — string (uuid), required

Request body (`application/json`, RouteCreate):
  - `name` — string, optional
  - `start_geom` — GeoJSON, required. GeoJSON geometry
  - `end_geom` — GeoJSON, required. GeoJSON geometry
  - `route_mode` — RouteMode, optional, default `"mixed"`
  - `attrs` — object (free-form), optional
  - `paths` — array of RoutePathCreate, optional

Response (`RouteResponse`):
  - `name` — string, optional
  - `start_geom` — GeoJSON, required. GeoJSON geometry
  - `end_geom` — GeoJSON, required. GeoJSON geometry
  - `route_mode` — RouteMode, optional, default `"mixed"`
  - `attrs` — object (free-form), optional
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `status` — RouteStatus, required
  - `paths` — array of RoutePathResponse, optional
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `POST /api/v1/routes/discover-corridors`

Discover Corridors

Discover doctrinal mobility corridors in a bounding box via
connected-component analysis on the cost-surface canalization mask.

Per ATP 2-01.3 §4-24, mobility corridors are "areas relatively free
of obstacles where a force will be canalized." Each returned corridor
is one connected region of passable terrain bounded by obstacles;
corridors are GEOGRAPHICALLY NON-OVERLAPPING by construction (each
tile belongs to exactly one corridor). Per §4-27 + Table 4-2 each
corridor is classified by its medial-axis perpendicular width.

Used by pytho-app MCOO enrichment to build the doctrinal AA list
(groups of corridors sharing an objective) and to render each
corridor as a `mobility_corridor` overlay alongside the AA chevrons.

bbox query string: "W,S,E,N" (e.g. "24.238,57.092,28.614,58.634").

Parameters:
- `bbox` (query) — string, required. W,S,E,N bbox (lon/lat decimal degrees)
- `force_type` (query) — string, optional
- `min_class` (query) — string, optional
- `map_id` (query) — string (uuid), required

### `POST /api/v1/routes/synthesize-mcoo`

Synthesize Mcoo Endpoint

Synthesize the full Modified Combined Obstacle Overlay product set
for an AO using the doctrinal GVD + circuit-theory pipeline.

Body shape:
    {
      "bbox": [W, S, E, N],
      "force_type": "mechanized" | "dismounted",
      "primary_echelon": "division" | "brigade" | "battalion",
      "cell_m": 100,                      # optional, default 100
      "terminal_pairs": [
         {
           "origin":    {"name": "Cimza",   "lon": 24.83, "lat": 57.55, "side": "friendly"},
           "objective": {"name": "Kopu",    "lon": 24.83, "lat": 58.27, "side": "threat"}
         },
         ...
      ]
    }

Returns the full MCOO product set:
    - mobility_corridors: GVD edge LineStrings with width/class
    - avenues_of_approach: per terminal-pair multi-tail bundles with
      central axis, tail corridor ids, envelope polygon
    - engagement_areas: GVD-vertex-derived disruption points
    - defensible_terrain: flanked GVD vertices
    - nogo_obstacles: extracted NO-GO polygons (for renderer context)

Every record carries GEOMETRY + STRUCTURED FACTS only (counts,
distances, scores). No prose: analyst-facing Rationale text is
composed by the consuming product layer (pytho-app MCOO enrichment),
never authored here — geo-agent is the map service, not a document
writer.

Parameters:
- `map_id` (query) — string (uuid), required

Request body (`application/json`, object (free-form)):
  - (see schema)

### `POST /api/v1/routes/analyze-edit`

Analyze Edit

Analyze user-edited route coordinates using the off-road code path.
Returns terrain analysis without saving anything to the DB.

Parameters:
- `map_id` (query) — string (uuid), required

Request body (`application/json`, AnalyzeEditRequest):
  - `coordinates` — array of array of number, required

### `GET /api/v1/routes/{route_id}`

Get Route

Get a single route with all its paths.

Parameters:
- `route_id` (path) — string (uuid), required

Response (`RouteResponse`):
  - `name` — string, optional
  - `start_geom` — GeoJSON, required. GeoJSON geometry
  - `end_geom` — GeoJSON, required. GeoJSON geometry
  - `route_mode` — RouteMode, optional, default `"mixed"`
  - `attrs` — object (free-form), optional
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `status` — RouteStatus, required
  - `paths` — array of RoutePathResponse, optional
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `PUT /api/v1/routes/{route_id}`

Update Existing Route

Update route metadata (start, end, mode, etc.).

Parameters:
- `route_id` (path) — string (uuid), required

Request body (`application/json`, RouteUpdate):
  - `name` — string, optional
  - `start_geom` — GeoJSON, optional
  - `end_geom` — GeoJSON, optional
  - `route_mode` — RouteMode, optional
  - `status` — RouteStatus, optional
  - `attrs` — object (free-form), optional

Response (`RouteResponse`):
  - `name` — string, optional
  - `start_geom` — GeoJSON, required. GeoJSON geometry
  - `end_geom` — GeoJSON, required. GeoJSON geometry
  - `route_mode` — RouteMode, optional, default `"mixed"`
  - `attrs` — object (free-form), optional
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `status` — RouteStatus, required
  - `paths` — array of RoutePathResponse, optional
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `DELETE /api/v1/routes/{route_id}`

Delete Existing Route

Delete a route and all its paths.

Parameters:
- `route_id` (path) — string (uuid), required

### `POST /api/v1/routes/plan`

Plan New Route

Plan a route: runs the planner first, only saves to DB on success.

Parameters:
- `map_id` (query) — string (uuid), required

Request body (`application/json`, RouteCreate):
  - `name` — string, optional
  - `start_geom` — GeoJSON, required. GeoJSON geometry
  - `end_geom` — GeoJSON, required. GeoJSON geometry
  - `route_mode` — RouteMode, optional, default `"mixed"`
  - `attrs` — object (free-form), optional
  - `paths` — array of RoutePathCreate, optional

Response (`RouteResponse`):
  - `name` — string, optional
  - `start_geom` — GeoJSON, required. GeoJSON geometry
  - `end_geom` — GeoJSON, required. GeoJSON geometry
  - `route_mode` — RouteMode, optional, default `"mixed"`
  - `attrs` — object (free-form), optional
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `status` — RouteStatus, required
  - `paths` — array of RoutePathResponse, optional
  - `created_at` — string (date-time), required
  - `updated_at` — string (date-time), required

### `GET /api/v1/routes/{route_id}/paths`

List Route Paths

Get all paths for a route.

Parameters:
- `route_id` (path) — string (uuid), required

Response (`array of RoutePathResponse`):

### `POST /api/v1/routes/{route_id}/paths`

Add New Path

Add a new alternative path to an existing route.

Parameters:
- `route_id` (path) — string (uuid), required

Request body (`application/json`, RoutePathCreate):
  - `rank` — integer, optional, default `1`
  - `label` — string, optional
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `selected` — integer, optional, default `0`
  - `analysis` — object (free-form), optional

Response (`RoutePathResponse`):
  - `rank` — integer, optional, default `1`
  - `label` — string, optional
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `selected` — integer, optional, default `0`
  - `analysis` — object (free-form), optional
  - `id` — string (uuid), required
  - `route_id` — string (uuid), required

### `PUT /api/v1/routes/{route_id}/paths/{path_id}`

Update Existing Path

Update a route path (geometry, analysis, etc.).

Parameters:
- `route_id` (path) — string (uuid), required
- `path_id` (path) — string (uuid), required

Request body (`application/json`, RoutePathUpdate):
  - `label` — string, optional
  - `geom` — GeoJSON, optional
  - `selected` — integer, optional
  - `analysis` — object (free-form), optional

Response (`RoutePathResponse`):
  - `rank` — integer, optional, default `1`
  - `label` — string, optional
  - `geom` — GeoJSON, required. GeoJSON geometry
  - `selected` — integer, optional, default `0`
  - `analysis` — object (free-form), optional
  - `id` — string (uuid), required
  - `route_id` — string (uuid), required

### `DELETE /api/v1/routes/{route_id}/paths/{path_id}`

Delete Existing Path

Delete a single path from a route.

Parameters:
- `route_id` (path) — string (uuid), required
- `path_id` (path) — string (uuid), required

### `POST /api/v1/routes/{route_id}/paths/{path_id}/select`

Select Route Path

Select a path as the chosen route (deselects all others).

Parameters:
- `route_id` (path) — string (uuid), required
- `path_id` (path) — string (uuid), required

## snapshots

### `POST /api/v1/maps/{map_id}/snapshots`

Create Snapshot

Create a snapshot of the current map state

Parameters:
- `map_id` (path) — string (uuid), required

Request body (`application/json`, SnapshotCreate):
  - `label` — string, optional
  - `created_by` — string, optional

Response (`SnapshotResponse`):
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `version` — integer, required
  - `label` — string, optional
  - `map_snapshot` — object (free-form), required
  - `entities_snapshot` — array of object (free-form), required
  - `overlays_snapshot` — array of object (free-form), required
  - `artifacts_snapshot` — array of object (free-form), required
  - `routes_snapshot` — array of object (free-form), optional
  - `created_at` — string (date-time), required
  - `created_by` — string, optional

### `GET /api/v1/maps/{map_id}/snapshots`

List Snapshots

List snapshots for a map, scoped to one analyst when user_id is given

Parameters:
- `map_id` (path) — string (uuid), required
- `user_id` (query) — string, optional. Snapshots are PERSONAL save points of the shared event map: pass the analyst id to list only that analyst's snapshots (created_by match). Restoring one still applies to the shared map — the snapshot LIST is per-user, the map is not. No user_id returns every snapshot on the map (backend tooling).

Response (`SnapshotListResponse`):
  - `snapshots` — array of SnapshotListItem, required
  - `total` — integer, required

### `GET /api/v1/maps/{map_id}/snapshots/{snapshot_id}`

Get Snapshot

Get a specific snapshot by ID

Parameters:
- `map_id` (path) — string (uuid), required
- `snapshot_id` (path) — string (uuid), required

Response (`SnapshotResponse`):
  - `id` — string (uuid), required
  - `map_id` — string (uuid), required
  - `version` — integer, required
  - `label` — string, optional
  - `map_snapshot` — object (free-form), required
  - `entities_snapshot` — array of object (free-form), required
  - `overlays_snapshot` — array of object (free-form), required
  - `artifacts_snapshot` — array of object (free-form), required
  - `routes_snapshot` — array of object (free-form), optional
  - `created_at` — string (date-time), required
  - `created_by` — string, optional

### `POST /api/v1/maps/{map_id}/snapshots/{snapshot_id}/restore`

Restore Snapshot

Restore a map to a previous snapshot state

Parameters:
- `map_id` (path) — string (uuid), required
- `snapshot_id` (path) — string (uuid), required

## terrain

### `GET /api/v1/terrain/coverage`

Terrain Coverage

Terrain-derived LOS coverage boundary for one envelope band —
the ring is the flat-earth slice; this is the viewshed (design doc
§6.7). Derived once per (position, range), persisted; the client
fetches it for the SELECTED unit's bands only.

Parameters:
- `lat` (query) — number, required
- `lon` (query) — number, required
- `radius_m` (query) — number, required
- `target_h` (query) — number, optional

Response (`object (free-form)`):

### `GET /api/v1/terrain/peaks`

Peaks In Bbox

Parameters:
- `bbox` (query) — string, required. w,s,e,n (lon/lat)

Response (`object (free-form)`):

## tiles

### `GET /api/v1/tiles/basemap/satellite/{z}/{x}/{y}.jpg`

Satellite Tile

Parameters:
- `z` (path) — integer, required
- `x` (path) — integer, required
- `y` (path) — integer, required

### `GET /api/v1/tiles/basemap/{style}/{z}/{x}/{y}.jpg`

Basemap Tile

Parameters:
- `style` (path) — string, required
- `z` (path) — integer, required
- `x` (path) — integer, required
- `y` (path) — integer, required

### `GET /api/v1/tiles/vector/basemap/{z}/{x}/{y}.pbf`

Vector Tile

Parameters:
- `z` (path) — integer, required
- `x` (path) — integer, required
- `y` (path) — integer, required

### `GET /api/v1/tiles/dem/{z}/{x}/{y}.webp`

Dem Tile

Parameters:
- `z` (path) — integer, required
- `x` (path) — integer, required
- `y` (path) — integer, required

### `GET /api/v1/tiles/labels/{z}/{x}/{y}.png`

Labels Tile

Parameters:
- `z` (path) — integer, required
- `x` (path) — integer, required
- `y` (path) — integer, required

### `GET /api/v1/fonts/{fontstack}/{range}.pbf`

Glyphs

Parameters:
- `fontstack` (path) — string, required
- `range` (path) — string, required

### `GET /api/v1/tiles/weather/{layer}/{z}/{x}/{y}`

Weather Tile

Proxy weather raster tiles (OpenWeatherMap Weather Maps 2.0
upstream), optional forecast timestamp (unix seconds) for the
0-72h scrub.

Rides the SAME tile plane as every other tile shape: this route
validates + appends the server-side API key, then proxies the
tilecache's /weather/ location (infra/tilecache/nginx.conf), which
owns the upstream TLS hop and the on-disk cache — identical
structure to the ESRI satellite proxy.

Parameters:
- `layer` (path) — string, required
- `z` (path) — integer, required
- `x` (path) — integer, required
- `y` (path) — integer, required
- `date` (query) — integer, optional

## untagged

### `GET /health`

Health
