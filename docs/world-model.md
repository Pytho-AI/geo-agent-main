# The world model

Geo-agent's data layer is a world-model ontology: a typed graph an agent
and an analyst both read, built from three layers with language as the
organizing principle. Design of record (history, rationale, benchmark
evidence): `scratch/docs/oob/weg_schema/weg-catalog-schema-design.md` in
the parent workspace. This doc describes what is IN THIS REPO and how to
read and extend it.

## The three layers

- **L0 — capture.** Verbatim source: `reference_nodes.sheet_data`
  (datasheet/narrative rows exactly as extracted), document text at
  ingest time. Immutable; nothing is ever trimmed to fit the schema.
- **L1 — clauses.** `fact_clauses`: atomic natural-language assertions
  carrying the keys they are ABOUT, speaker/source provenance, temporal
  bounds, and a register:
  - `gnomic` — statements about TYPES: the equipment catalog's derived
    statements (`source_kind='weg_catalog'`) and OPFOR doctrine keyed to
    force-template keys (`source_kind='doctrine'`).
  - `episodic` — statements about PROJECT entities, written by the
    document-ingest register stage (`source_kind='document_ingest'`,
    `project_id` set). Updatable states carry a `slot`
    (`<node-uuid>.<attribute>`); a deterministic pass computes
    bitemporal supersession per slot (`valid_to` + `superseded_by`),
    append-only.
  - `predictive` — future valid time with an assessed basis.
- **L2 — the typed graph.** Reference store (`reference_nodes` /
  `reference_links` / `reference_specs`: equipment, weapons, munitions,
  components; mounts/fires/equipped_with/variant_of links; spec tuples
  with 3D envelope columns) plus the project graph (`graph_nodes`,
  `graph_edges`, `graph_holdings`, `graph_node_positions`). The legacy
  consumer tables (`weg_equipment` + aliases/emitters/range_candidates)
  are DERIVED PROJECTIONS materialized from the reference store at seed
  time — existing consumers read them unchanged.

## Bitemporality — the two replays

observed_at is THE temporal dimension (2026-07-21 ruling): the world
model only ever holds REPORTS — there is no ground truth in it, and
there is no axis. A stated DTG carries the source's time; an assertion
made without a stated time is stamped at the assertion moment; a
stated-but-unparseable DTG REJECTS the write (per-item error echo with
the raw DTG — never silently stamped, which would launder the bad
parse). `created_at` is ingest bookkeeping only: never resolved,
replayed, or surfaced. The timeline scrub replays the record's
observations at any time. Exercise ground truth is Crucible event
design's concern, outside this system entirely.

## Read surfaces

- `GET /api/v1/graph/nodes/{id}/card` — the placard-shaped read
  (unit, parent, children, holdings rollup, governing position).
- `GET /api/v1/graph/nodes/{id}/brief?as_of=<iso>` — the as-of
  resolver: updatable attributes as supersession chains (History),
  unslotted statements with provenance (Reporting/Sources), doctrine
  clauses for the unit's template (Doctrine), and the position at the
  scrub time. Omit `as_of` for now/live.
- `GET /api/v1/map/state?...&as_of=<iso>` — the paint read; positions
  resolve to the latest observation at or before the scrub time.

Frontend: `UnitMetadataPanel` renders the brief (As-of banner, History
with CURRENT/SUPERSEDED badges, Reporting, Doctrine) and re-fetches on
every scrub commit; `TimelineScrubber` is LIVE plus the slider.

## Write paths

There is exactly one write path per layer, and reads never mutate:

- Reference layer: versioned seed in `db/bootstrap.py` (wholesale
  rebuild from `backend/app/data/*_extract.jsonl` via
  `db/derivation.py`; projections rematerialized after). Runtime writes
  are forbidden — project config layers on top (`map.attrs`).
- Project graph: the graph CRUD/geoops endpoints and the document
  ingest pipeline (`services/graph_ingest/`).
- Episodic register: `services/graph_ingest/clauses.py`, a stage of
  `ingest_documents` — extraction into clauses, then deterministic slot
  supersession. Re-runnable; never deletes.

## Extending

New object/link kinds are REGISTRY ROWS (`entity_types` /
`relationship_types`), never code branches. The entity-type registry
has ONE authority: `ENTITY_TYPE_SEED` in `models/graph.py` (the DB
table seeds from it; `GRAPHIC_TYPES`, `EXTRACTABLE_ENTITY_TYPES`, the
extraction prompt enum, and the MCP shape-kind enum all DERIVE from
it — never hand-mirror a type list). A kind paints as a tactical
graphic exactly when `constants/overlays.py` defines its renderer
contract, so a new graphic kind is one seed row plus one catalog
entry — the catalog entry is also what gives it its overlay-selector
chip. New updatable attributes
need no schema change — they are slots. New projections of the store
(profile views, envelope charts, coverage) are read-time derivations;
renderers render what derivations produce. When adding a consumer of
clause data, read the register and time-contract semantics above and
never bypass the supersession chain — a superseded value is history,
not an error.
