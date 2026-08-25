"""Built-in structured templates for doctrinal intel products.

Each module under `products/` exports `SPEC = {...}` — a schema dict the
agent runner and exporter consume to build, render, and audit one artifact.
This is the schema counterpart to user-uploaded HTML templates living in
`uploads/<file_key>.html`. The two coexist; `handlers/product.py` is the
unified entry point that resolves either form into the prompt and rendering
pipeline.

Authoring is data-only (enum imports + a SPEC dict). All accessor logic and
prompt rendering lives in the generation engine.

WORLD-MODEL INPUT TOKENS (the reconciled input surface, 2026-07-23)
-------------------------------------------------------------------
The cougaar tool surface these SPECs were originally scoped against is
dead; inputs now declare WORLD-MODEL reads. The engine resolves each
token against the project's world model (project layer only; the
closed retrieval set it builds is the writer's citation universe).

depends_on / read tokens:
  entities:<kind>          entity rows of one registry kind (positions,
                           holdings, edges ride along) — e.g.
                           entities:key_terrain, entities:battle_position
  entities:units[:hostile|:friendly]   the unit picture (OOB)
  entities:civil           civil-kind entity group
  entities:marked          marked entities (mock-target flag)
  clauses:episodic[:kind]  fact clauses by register/kind
  documents / document:<TAG>   ingested source documents
  upstream:<Product>       the APPROVED edition of an upstream product
  map:state                everything painted on the project map
  map:config               project map config (AO bbox, attrs)
  map:render               the rendered map figure (engine render call)
  weather                  the project weather source
  anchors                  temporal anchors / phases
  <sibling_field_name>     a sibling field's emitted value (unchanged)

header/row `source` tokens:
  session / session.user / computed    engine context (unchanged)
  entity:<field>           mechanical read off the row's entity
                           (entity:id, entity:name, entity:echelon,
                           entity:location_mgrs, entity:doi, ...)
  derive:<token>           engine mechanical derivation (unchanged)
  upstream:<Product>[...]  mechanical echo/lookup from an upstream
                           approved edition (replaces ref:/lookup:)
  map:render               runner-filled from the render call
  analytical               the writer LLM authors it (unchanged)

row_source values: factor_list (unchanged), entities:units:hostile,
entities:marked.

consumes_artifacts lists upstream PRODUCT keys only (approved-edition
reads); doctrine references are documents (document:<TAG>), not
artifacts. data_source_filter survives ONLY keyed on upstream:<X>
(narrowing an edition's structured_data to named fields); read tokens
are already narrow by construction.

Guidance prose still references the old tool names in places — the
guidance refinement pass follows the engine hookup and cleans those
in place.
"""
from .common import *  # noqa: F401,F403  — surfaces enums + HEADER_* bedrock
from .products import PRODUCT_SCHEMAS, PRODUCTS

__all__ = ["PRODUCT_SCHEMAS", "PRODUCTS"]
