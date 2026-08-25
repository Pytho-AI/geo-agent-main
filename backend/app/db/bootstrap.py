"""Entity-graph schema + reference-seed bootstrap.

Called from the app lifespan. Idempotent:
- create_all for every model (checkfirst).
- ALTER TABLE maps ADD COLUMN IF NOT EXISTS graph_mode.
- *_seed_baseline tables via CREATE TABLE (LIKE ...) — always
  schema-synced with their source tables.
- Versioned seeding (design §3.4/§3.5): reference_seed_meta compares
  seed_version, never emptiness. On version bump the upgrade is
  PER-COLUMN three-way against the retained baseline: where live ==
  baseline (or live is null for a column the baseline lacked) take the
  new seed value, else keep live and log the divergence. `source` is
  row-creation provenance only, never the upgrade predicate.
- Extraction outputs (backend/app/data/*_extract.jsonl, written by the
  Sonnet VLM extractors over the WEG/ATP PDFs) load match-or-mint by
  key: existing rows are NEVER clobbered — catalog curation and user
  edits win over re-extraction.
"""
import hashlib
import json
import logging
import re
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine, async_session
from app.db import derivation
from app.models.base import Base
from app.models.graph import (ENTITY_TYPE_SEED, ECHELONS, POSTURES,
                              ForceTemplate, GraphHolding, GraphNode)
from app.models.products import ProductType
from app.models.reference import (
    EntityType, FactClause, FieldDef, ReferenceLink, ReferenceNode,
    ReferenceSeedMeta, ReferenceSpec, RelationshipType,
    WegEquipment, WegEquipmentAlias, WegEquipmentEmitter,
    WegEquipmentRangeCandidate,
)

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

REGISTRY_SEED_VERSION = "2026-07-29.1"

# Product-type catalog seed version (bump on ANY row change — the
# seeder gates on it; the 7dd5ff3 lesson applies here identically).
PRODUCT_REGISTRY_VERSION = "2026-07-27.5"

PRODUCT_TYPE_SEED = [
    # (type_key, label, category, ipoe_step, output_formats, depends_on,
    #  fanout_dimension, declared_fact_classes, writer_spec_key,
    #  dev_only)
    # The 1a mechanism stub: exercises every record/lifecycle state and
    # writes TOKEN LAYER ROWS so approve/merge/supersede integrity is
    # exercised for real. Hidden from the analyst rail; disabled once
    # 1b lands.
    ("stub_mechanism_check", "Mechanism Stub (dev)", "dev", None,
     ["txt"], [],
     None, ["clause:episodic:state", "key_terrain"],
     "stub", True),
    # 1b: the first real product — IPOE Step 1. writer_spec_key IS the
    # PRODUCT_SCHEMAS key (the copied IBL registry key) — the generic
    # writer resolves the SPEC by this key (cont 36v step 5).
    ("operational_environment_definition",
     "Operational Environment Definition", "ipoe", 1,
     ["docx"], [],
     None,
     ["unit", "key_terrain", "named_area_of_interest",
      "decision_point", "engagement_area", "assembly_area",
      "phase_line", "boundary", "objective",
      "fire_support_coord_measure",
      "clause:episodic:state", "clause:episodic:event",
      "clause:episodic:task"],
     "Operational Environment Definition", False),
    # 1c — IPOE Step 2 (fifth edition §0). writer_spec_key IS the
    # PRODUCT_SCHEMAS key. depends_on is the HARD approval ladder
    # (§2.4 — a fire against a missing upstream approval refuses):
    # STEP 1 GATES STEP 2: every step-2 product requires the APPROVED
    # Operational Environment Definition (the product that DEFINES the
    # environment step 2 describes). Then WEM → {TEM, CCM} → MCOO is
    # the intra-step sequencing the SPECs
    # themselves state (WEM supplies the weather assumption; MCOO
    # incorporates TEM and CCM as input layers). CCA and its XLSX
    # matrix sibling are independent step-2 products — their MCOO
    # reference is optional amplification, never a firing gate.
    ("weather_effects_matrix", "Weather Effects Matrix", "ipoe", 2,
     ["pptx"], ["operational_environment_definition"],
     None,
     ["weather_condition", "clause:episodic:state"],
     "WEM", False),
    ("terrain_effects_matrix", "Terrain Effects Matrix", "ipoe", 2,
     ["docx"],
     ["operational_environment_definition", "weather_effects_matrix"],
     None,
     ["mobility_corridor", "key_terrain", "river", "bridge",
      "engagement_area", "clause:episodic:state"],
     "TEM", False),
    ("cross_country_mobility", "Cross-Country Mobility", "ipoe", 2,
     ["pptx"],
     ["operational_environment_definition", "weather_effects_matrix"],
     None,
     ["mobility_corridor", "river", "main_supply_route", "unit"],
     "CCM", False),
    ("modified_combined_obstacle_overlay",
     "Modified Combined Obstacle Overlay", "ipoe", 2,
     ["pptx"],
     ["operational_environment_definition", "weather_effects_matrix",
      "terrain_effects_matrix", "cross_country_mobility"],
     None,
     ["mobility_corridor", "key_terrain", "river", "bridge",
      "obstacle", "engagement_area", "avenue_of_approach",
      "named_area"],
     "MCOO", False),
    ("civil_considerations_assessment",
     "Civil Considerations Assessment", "ipoe", 2,
     ["pptx"], ["operational_environment_definition"],
     None,
     ["infrastructure", "medical_facility", "water_treatment",
      "pol_storage", "rail_hub", "logistics_site", "garrison",
      "organization", "person", "event",
      "ascope_pmesii_join", "clause:episodic:state"],
     "CCA", False),
    ("civil_considerations_assessment_matrix",
     "Civil Considerations Assessment Matrix", "ipoe", 2,
     ["xlsx"], ["operational_environment_definition"],
     None,
     ["ascope_pmesii_join"],
     "CCA-Matrix", False),
]

# Wholesale-rebuild version for the world-model reference store (design
# weg-catalog-schema-design.md). Bumping it re-derives reference_nodes/links/
# specs/clauses and re-materializes the weg_equipment projection.
# 2026-07-29: the seed source is the UNIFIED WEG CATALOGUE (the ODIN + legacy
# seed merge, backend/app/data/weg_catalog/) via derive_unified_catalog; the
# old four-master assembly is retired.
REFERENCE_STORE_VERSION = "2026-07-29.20-sheet-sections"


RELATIONSHIP_TYPE_SEED = [
    # (type_key, label, inverse_label, is_hierarchical)
    ("attached", "attached to", "has attached", True),
    ("opcon", "under OPCON of", "has OPCON of", True),
    ("direct_support", "in direct support of", "directly supported by", False),
    ("reinforcing", "reinforcing", "reinforced by", False),
    ("general_support_reinforcing", "in general support-reinforcing of",
     "general support-reinforced by", False),
    ("general_support", "in general support of", "generally supported by", False),
    ("supplies", "supplies", "depends on", False),
    # World-model reference link types (design S6.2). Directional, each with
    # an inverse reading; is_hierarchical drives the project graph's task-org
    # cycle check only (inert on reference_links) — variant_of is the one
    # kind-of hierarchy among them.
    ("mounts", "mounts", "mounted on", False),
    ("fires", "fires", "fired by", False),
    ("equipped_with", "equipped with", "fitted to", False),
    ("variant_of", "variant of", "has variant", True),
    ("component_of", "component of", "assembles", False),
    ("associated_with", "associated with", "associated with", False),
    # Unified-catalogue lineage: a system developed from another system
    # (the merge's derived_from rulings, with their basis sentences on
    # the link).
    ("derived_from", "derived from", "basis of", False),
    # Reified-event thematic-role links (design S6.5) — registry-defined now,
    # populated when engagement/strike/resupply/BDA event data arrives.
    ("actor", "has actor", "actor in", False),
    ("target", "has target", "targeted in", False),
    ("instrument", "uses instrument", "instrument in", False),
    ("location", "at location", "location of", False),
]

FIELD_DEF_SEED = [
    # (field_key, label, value_type)
    ("capacity", "Capacity", "text"),
    # Display choice for line/area control measures (edit panel):
    # '' segments (default) | 'bezier' spline-smoothed paint.
    ("smoothing", "Line smoothing", "text"),
]

_STRUCTURAL_COLS = {"is_fixed", "is_hierarchical", "value_type"}

_BASELINE_SOURCES = (
    "entity_types", "relationship_types", "field_defs", "weg_equipment",
    "product_types",
)


def _sql_list(values: tuple) -> str:
    """Closed-set tuple -> quoted SQL IN-list (registry constants are
    plain doctrinal words; no escaping concerns)."""
    return ", ".join(f"'{v}'" for v in values)


async def ensure_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE maps ADD COLUMN IF NOT EXISTS "
            "graph_mode VARCHAR(16) DEFAULT 'authored'"))
        # Baseline tables FIRST — the migration ALTERs below reference
        # them, and on a fresh box they do not exist yet (an ALTER on a
        # missing table aborts the whole bootstrap transaction; staging
        # found this the hard way).
        for src in _BASELINE_SOURCES:
            await conn.execute(text(
                f"CREATE TABLE IF NOT EXISTS {src}_seed_baseline "
                f"(LIKE {src} INCLUDING DEFAULTS)"))
        # Idempotent migrations for tables created by earlier builds.
        for ddl in (
            # Graph geometry generalized (POINT -> GEOMETRY) so control
            # measures and linear infrastructure are first-class records
            # (phase lines, boundaries, engagement areas, LOCs). No-op
            # once applied; every point satisfies the generic type.
            "ALTER TABLE graph_nodes ALTER COLUMN geom "
            "TYPE geometry(Geometry,4326)",
            "ALTER TABLE graph_node_positions ALTER COLUMN geom "
            "TYPE geometry(Geometry,4326)",
            # Sheet characteristics get their own field — the original
            # extraction stuffed the whole sheet body into `caliber`.
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS "
            "characteristics TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN "
            "IF NOT EXISTS characteristics TEXT",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS "
            "country_of_origin VARCHAR(128)",
            # Full-MTOE flag: source stated the unit's complete
            # equipment table; template defaults do not apply.
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "holdings_complete BOOLEAN DEFAULT FALSE",
            # §6.7 third-dimension package: envelope altitude bands +
            # trajectory class; altitude/speed observables; airspace
            # floor/ceiling extrusions.
            "ALTER TABLE weg_equipment_range_candidates ADD COLUMN "
            "IF NOT EXISTS min_altitude_m INTEGER",
            "ALTER TABLE weg_equipment_range_candidates ADD COLUMN "
            "IF NOT EXISTS max_altitude_m INTEGER",
            "ALTER TABLE weg_equipment_range_candidates ADD COLUMN "
            "IF NOT EXISTS trajectory VARCHAR(16)",
            "ALTER TABLE graph_node_positions ADD COLUMN IF NOT EXISTS "
            "altitude_m DOUBLE PRECISION",
            "ALTER TABLE graph_node_positions ADD COLUMN IF NOT EXISTS "
            "speed_kph DOUBLE PRECISION",
            # Tag layers (2026-07-27 ruling): PMESII-PT facets tag the
            # STATEMENT (clause layer); ASCOPE categories tag the
            # REFERENT (entity layer, stated on the occurrence and
            # propagated at alias resolution). Stamped at ingestion,
            # backfilled through the repair surface; matrix cells join
            # across the two layers.
            "ALTER TABLE clauses ADD COLUMN IF NOT EXISTS pmesii TEXT[]",
            "ALTER TABLE entity_occurrences ADD COLUMN IF NOT EXISTS "
            "ascope TEXT[]",
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "ascope TEXT[]",
            # Analyst generation knobs on the record (config_fields).
            "ALTER TABLE product_records ADD COLUMN IF NOT EXISTS "
            "generation_config JSONB",
            # 2026-07-28 ruling: provenance is the record CHAIN, never
            # authored prose. Mechanically strip the note residue the
            # old repair machinery appended to position source strings
            # and stored in assertion conditions — display derives from
            # the chain now, and the operational narrative lives in the
            # events log. Idempotent (LIKE-guarded); no authored
            # replacement text, pure truncation/null.
            "UPDATE graph_node_positions SET source = "
            "split_part(source, ' | value repair:', 1) "
            "WHERE source LIKE '%| value repair:%'",
            "UPDATE graph_node_positions SET source = "
            "split_part(source, ' | time repair:', 1) "
            "WHERE source LIKE '%| time repair:%'",
            "UPDATE assertions SET condition = NULL "
            "WHERE condition LIKE 'repair:%'",
            # observed_at is the record's ONE temporal dimension
            # (2026-07-21 ruling) and is NEVER null. There is NO
            # mechanical backfill: a null row is scenario-derived
            # data whose observed time must be repaired BY HAND
            # against the source documentation, THROUGH THE TOOL
            # SURFACE (get_entities returns each track row's
            # `observation` handle; add_positions set_time_on sets
            # the time with a required basis citation — stamping
            # created_at over it
            # would launder ingest bookkeeping into the scenario
            # timeline). The constraints are SELF-ARMING: each boot
            # applies them only once the table is clean, and RAISEs
            # a WARNING with the dirty-row count until then — the
            # repair tools must be deployable onto a dirty box, so
            # the boot never bricks on unrepaired data. Fresh boxes
            # arm immediately (create_all builds the column
            # NOT NULL).
            """
            DO $$
            DECLARE dirty integer;
            BEGIN
                SELECT count(*) INTO dirty FROM graph_node_positions
                    WHERE observed_at IS NULL;
                IF dirty = 0 THEN
                    ALTER TABLE graph_node_positions
                        ALTER COLUMN observed_at SET NOT NULL;
                ELSE
                    RAISE WARNING 'observed_at NOT NULL not armed: % '
                        'graph_node_positions rows need manual repair '
                        '(get_entities observation handles / '
                        'add_positions set_time_on)', dirty;
                END IF;
            END $$
            """,
            # Working-layer posture override (2026-07-28 ruling: the
            # placard posture selector is a VISUAL override for now) —
            # a display NodeField per the smoothing pattern, never the
            # record and never the mirror column. Seeded here so the
            # fields surface validates it.
            "INSERT INTO field_defs (field_key, label, value_type, source) "
            "VALUES ('posture_override', 'Posture override (visual)', "
            "'text', 'bundled') ON CONFLICT (field_key) DO NOTHING",
            # Posture vocabulary closed 2026-07-28 (models/graph.py
            # POSTURES). Mechanical normalization of legacy free-text
            # column values via the SAME keyword buckets, precedence and
            # offense->attack storage word the engine's posture_mode has
            # always used (disposition.py) — a classifier the data
            # already flowed through, never authored text. Idempotent:
            # after one pass every value is in-enum and the WHERE
            # matches nothing. ASSERTION value_text is the record and
            # is NEVER rewritten — an off-enum committed posture
            # assertion keeps the CHECK unarmed (warning below) until
            # it is corrected through the tools.
            f"""
            UPDATE graph_nodes SET posture = CASE
                WHEN lower(posture) ~
                    '(assembl|staging|reserve|marshal|concentrat|bivouac)'
                    THEN 'assembly'
                WHEN lower(posture) ~ '(march|column|convoy|road move)'
                    THEN 'march'
                WHEN lower(posture) ~ '(screen|security|guard|cover)'
                    THEN 'screen'
                WHEN lower(posture) ~ '(attack|assault|advance|offen)'
                    THEN 'attack'
                ELSE 'defense' END
            WHERE posture IS NOT NULL
              AND posture NOT IN ({_sql_list(POSTURES)})
            """,
            f"""
            DO $$
            DECLARE dirty integer;
            BEGIN
                SELECT (SELECT count(*) FROM graph_nodes
                            WHERE posture IS NOT NULL
                              AND posture NOT IN ({_sql_list(POSTURES)}))
                     + (SELECT count(*) FROM assertions
                            WHERE attribute = 'posture'
                              AND record_state = 'committed'
                              AND retracted_by IS NULL
                              AND superseded_by IS NULL
                              AND value_text IS NOT NULL
                              AND value_text NOT IN
                                  ({_sql_list(POSTURES)}))
                    INTO dirty;
                IF dirty = 0 THEN
                    ALTER TABLE graph_nodes DROP CONSTRAINT IF EXISTS
                        ck_graph_nodes_posture;
                    ALTER TABLE graph_nodes ADD CONSTRAINT
                        ck_graph_nodes_posture CHECK
                        (posture IS NULL OR
                         posture IN ({_sql_list(POSTURES)}));
                ELSE
                    RAISE WARNING 'posture CHECK not armed: % off-enum '
                        'values remain (committed posture assertions '
                        'are never rewritten mechanically — correct '
                        'them through the tools)', dirty;
                END IF;
            END $$
            """,
            """
            DO $$
            DECLARE dirty integer;
            BEGIN
                SELECT count(*) INTO dirty FROM fact_clauses
                    WHERE register = 'episodic' AND observed_at IS NULL;
                IF dirty = 0 THEN
                    ALTER TABLE fact_clauses DROP CONSTRAINT IF EXISTS
                        ck_fact_clauses_episodic_observed;
                    ALTER TABLE fact_clauses ADD CONSTRAINT
                        ck_fact_clauses_episodic_observed CHECK
                        (register <> 'episodic' OR observed_at IS NOT NULL);
                ELSE
                    RAISE WARNING 'episodic observed_at CHECK not armed: '
                        '% fact_clauses rows need manual repair', dirty;
                END IF;
            END $$
            """,
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "altitude_floor_m DOUBLE PRECISION",
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "altitude_ceiling_m DOUBLE PRECISION",
            # Typed subkind discriminator (paint reads it — obstacle
            # glyph dispatch; design-decision-16 promotion).
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "subkind VARCHAR(64)",
            # Mock-target marking FIELD (2026-07-22 ruling: a marked
            # entity is an ordinary entity with a marking field; the
            # entities:marked read filters marking IS NOT NULL).
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "marking TEXT",
            # APPROVE LOCKS FOREVER (2026-07-23 lifecycle ruling):
            # survives an approval revoke; refuses revoke-to-draft on
            # any edition that was ever approved.
            "ALTER TABLE product_records ADD COLUMN IF NOT EXISTS "
            "ever_approved BOOLEAN NOT NULL DEFAULT FALSE",
            # DRAFT-LAYER MODEL (fifth edition §2.2): layer +
            # origin_record_id on every world-model table generation
            # writes. Existing rows default to 'project'; draft rows
            # are engine-written only; rows are NEVER deleted — layer
            # flags express supersession.
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "layer VARCHAR(16) NOT NULL DEFAULT 'project'",
            "ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS "
            "origin_record_id UUID",
            "ALTER TABLE graph_node_positions ADD COLUMN IF NOT EXISTS "
            "layer VARCHAR(16) NOT NULL DEFAULT 'project'",
            "ALTER TABLE graph_node_positions ADD COLUMN IF NOT EXISTS "
            "origin_record_id UUID",
            "ALTER TABLE graph_edges ADD COLUMN IF NOT EXISTS "
            "layer VARCHAR(16) NOT NULL DEFAULT 'project'",
            "ALTER TABLE graph_edges ADD COLUMN IF NOT EXISTS "
            "origin_record_id UUID",
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS "
            "layer VARCHAR(16) NOT NULL DEFAULT 'project'",
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS "
            "origin_record_id UUID",
            "ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS "
            "layer VARCHAR(16) NOT NULL DEFAULT 'project'",
            "ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS "
            "origin_record_id UUID",
            # THE STALENESS TOUCH MACHINERY (§2.7): DB triggers bump
            # one (project, fact_class) high-water row on every
            # PROJECT-LAYER mutation, deletes included. Class mapping:
            # entity -> its entity_type; position/holding -> owning
            # node's type; edge -> each endpoint's type; clause ->
            # clause:<register>:<kind>. Child triggers LEFT-JOIN the
            # owning node and no-op when it is gone (the node's own
            # delete trigger captured the mutation from its OLD row).
            """
            CREATE OR REPLACE FUNCTION product_touch_bump(
                pid UUID, fclass TEXT) RETURNS void AS $$
            BEGIN
                IF pid IS NULL OR fclass IS NULL THEN RETURN; END IF;
                INSERT INTO product_fact_touch
                    (project_id, fact_class, touched_at)
                VALUES (pid, fclass, now())
                ON CONFLICT (project_id, fact_class)
                DO UPDATE SET touched_at = now();
            END $$ LANGUAGE plpgsql
            """,
            """
            CREATE OR REPLACE FUNCTION trg_touch_nodes()
            RETURNS trigger AS $$
            DECLARE r graph_nodes%ROWTYPE;
            BEGIN
                IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
                IF (TG_OP = 'DELETE' AND OLD.layer = 'project')
                   OR (TG_OP = 'INSERT' AND NEW.layer = 'project')
                   OR (TG_OP = 'UPDATE' AND (NEW.layer = 'project'
                       OR OLD.layer = 'project')) THEN
                    PERFORM product_touch_bump(
                        r.project_id, r.entity_type);
                END IF;
                RETURN NULL;
            END $$ LANGUAGE plpgsql
            """,
            """
            CREATE OR REPLACE FUNCTION trg_touch_positions()
            RETURNS trigger AS $$
            DECLARE r graph_node_positions%ROWTYPE;
                    n graph_nodes%ROWTYPE;
            BEGIN
                IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
                IF COALESCE(r.layer, 'project') <> 'project' THEN
                    RETURN NULL;
                END IF;
                SELECT * INTO n FROM graph_nodes WHERE id = r.node_id;
                IF FOUND AND n.layer = 'project' THEN
                    PERFORM product_touch_bump(
                        n.project_id, n.entity_type);
                END IF;
                RETURN NULL;
            END $$ LANGUAGE plpgsql
            """,
            """
            CREATE OR REPLACE FUNCTION trg_touch_holdings()
            RETURNS trigger AS $$
            DECLARE r graph_holdings%ROWTYPE;
                    n graph_nodes%ROWTYPE;
            BEGIN
                IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
                SELECT * INTO n FROM graph_nodes WHERE id = r.node_id;
                IF FOUND AND n.layer = 'project' THEN
                    PERFORM product_touch_bump(
                        n.project_id, n.entity_type);
                END IF;
                RETURN NULL;
            END $$ LANGUAGE plpgsql
            """,
            """
            CREATE OR REPLACE FUNCTION trg_touch_edges()
            RETURNS trigger AS $$
            DECLARE r graph_edges%ROWTYPE;
                    n graph_nodes%ROWTYPE;
            BEGIN
                IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
                IF COALESCE(r.layer, 'project') <> 'project' THEN
                    RETURN NULL;
                END IF;
                SELECT * INTO n FROM graph_nodes WHERE id = r.from_id;
                IF FOUND AND n.layer = 'project' THEN
                    PERFORM product_touch_bump(
                        n.project_id, n.entity_type);
                END IF;
                SELECT * INTO n FROM graph_nodes WHERE id = r.to_id;
                IF FOUND AND n.layer = 'project' THEN
                    PERFORM product_touch_bump(
                        n.project_id, n.entity_type);
                END IF;
                RETURN NULL;
            END $$ LANGUAGE plpgsql
            """,
            """
            CREATE OR REPLACE FUNCTION trg_touch_clauses()
            RETURNS trigger AS $$
            DECLARE r fact_clauses%ROWTYPE;
            BEGIN
                IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
                IF r.project_id IS NULL THEN RETURN NULL; END IF;
                IF (TG_OP = 'DELETE' AND OLD.layer = 'project')
                   OR (TG_OP = 'INSERT' AND NEW.layer = 'project')
                   OR (TG_OP = 'UPDATE' AND (NEW.layer = 'project'
                       OR OLD.layer = 'project')) THEN
                    PERFORM product_touch_bump(
                        r.project_id,
                        'clause:' || r.register || ':'
                        || COALESCE(r.kind, ''));
                END IF;
                RETURN NULL;
            END $$ LANGUAGE plpgsql
            """,
            "DROP TRIGGER IF EXISTS product_touch_nodes ON graph_nodes",
            "CREATE TRIGGER product_touch_nodes AFTER INSERT OR UPDATE "
            "OR DELETE ON graph_nodes FOR EACH ROW "
            "EXECUTE FUNCTION trg_touch_nodes()",
            "DROP TRIGGER IF EXISTS product_touch_positions "
            "ON graph_node_positions",
            "CREATE TRIGGER product_touch_positions AFTER INSERT OR "
            "UPDATE OR DELETE ON graph_node_positions FOR EACH ROW "
            "EXECUTE FUNCTION trg_touch_positions()",
            "DROP TRIGGER IF EXISTS product_touch_holdings "
            "ON graph_holdings",
            "CREATE TRIGGER product_touch_holdings AFTER INSERT OR "
            "UPDATE OR DELETE ON graph_holdings FOR EACH ROW "
            "EXECUTE FUNCTION trg_touch_holdings()",
            "DROP TRIGGER IF EXISTS product_touch_edges ON graph_edges",
            "CREATE TRIGGER product_touch_edges AFTER INSERT OR UPDATE "
            "OR DELETE ON graph_edges FOR EACH ROW "
            "EXECUTE FUNCTION trg_touch_edges()",
            "DROP TRIGGER IF EXISTS product_touch_clauses "
            "ON fact_clauses",
            "CREATE TRIGGER product_touch_clauses AFTER INSERT OR "
            "UPDATE OR DELETE ON fact_clauses FOR EACH ROW "
            "EXECUTE FUNCTION trg_touch_clauses()",
            # Verbatim provenance never truncates a seed.
            "ALTER TABLE weg_equipment ALTER COLUMN country_of_origin "
            "TYPE TEXT",
            "ALTER TABLE weg_equipment ALTER COLUMN date_of_introduction "
            "TYPE TEXT",
            "ALTER TABLE weg_equipment ALTER COLUMN source_page TYPE TEXT",
            "ALTER TABLE weg_equipment ALTER COLUMN image_path TYPE TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ALTER COLUMN "
            "country_of_origin TYPE TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ALTER COLUMN "
            "date_of_introduction TYPE TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ALTER COLUMN "
            "source_page TYPE TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ALTER COLUMN "
            "image_path TYPE TEXT",
            "ALTER TABLE reference_nodes ALTER COLUMN country_of_origin "
            "TYPE TEXT",
            "ALTER TABLE reference_nodes ALTER COLUMN "
            "date_of_introduction TYPE TEXT",
            "ALTER TABLE reference_nodes ALTER COLUMN source_page "
            "TYPE TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN "
            "IF NOT EXISTS country_of_origin VARCHAR(128)",
            # Complete-seed columns (total extraction 2026-07-17): the
            # catalog now carries every field the WEG sheet states.
            # sheet_data (JSONB) is the catch-all for specs / sheet_extras
            # / raw_sheet_text so nothing is ever lost. crew widens to
            # TEXT to hold the sheet's full crew breakdown string.
            "ALTER TABLE weg_equipment ALTER COLUMN crew TYPE TEXT USING crew::text",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS "
            "alternative_designations TEXT",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS "
            "combat_weight TEXT",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS "
            "description TEXT",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS "
            "sheet_data JSONB",
            "ALTER TABLE weg_equipment_seed_baseline ALTER COLUMN crew TYPE TEXT USING crew::text",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN "
            "IF NOT EXISTS alternative_designations TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN "
            "IF NOT EXISTS combat_weight TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN "
            "IF NOT EXISTS description TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN "
            "IF NOT EXISTS sheet_data JSONB",
            # Position provenance is a full citation now (document +
            # entry, inference basis, grid/prose conflict) — TEXT, not
            # VARCHAR(255) which overflowed on control-measure writes.
            "ALTER TABLE graph_node_positions ALTER COLUMN source TYPE TEXT",
            "ALTER TABLE weg_equipment ALTER COLUMN caliber TYPE TEXT",
            # (a legacy step here re-NARROWED date_of_introduction and
            # source_page to VARCHAR(128) on every boot, undoing the
            # TEXT widening earlier in this list and skipping the whole
            # bootstrap once verbatim citations exceeded 128 — removed;
            # provenance is TEXT, full stop.)
            # TEXT, not a short varchar: extraction rows carry full
            # descriptive emitter strings; a 143-char LTAMDS description
            # overflowed VARCHAR(128) and silently dropped the system.
            "ALTER TABLE weg_equipment_emitters ALTER COLUMN emitter_type TYPE TEXT",
            "ALTER TABLE weg_equipment_emitters ALTER COLUMN frequency_band TYPE VARCHAR(255)",
            # Decision 24: no verification tier — WEG data IS verified.
            "ALTER TABLE weg_equipment DROP COLUMN IF EXISTS verification_status",
            "ALTER TABLE weg_equipment_seed_baseline DROP COLUMN IF EXISTS verification_status",
            "ALTER TABLE weg_equipment_range_candidates ADD COLUMN IF NOT EXISTS condition VARCHAR(32)",
            # Widen condition: the v2 capture carries full descriptive
            # qualifiers (up to ~400 chars), which overflowed VARCHAR(32).
            "ALTER TABLE weg_equipment_range_candidates ALTER COLUMN condition TYPE TEXT",
            "ALTER TABLE weg_equipment_range_candidates ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE",
            # Doctrinal disposition norms per force template (km) — the
            # placement engine's frontage/depth source when arraying a
            # template instance's subordinates.
            # htfs_ org-guide templates carry long page-by-page citations and
            # rich functional-role unit_type text; widen from VARCHAR(255).
            "ALTER TABLE force_templates ALTER COLUMN doctrine_source TYPE TEXT",
            "ALTER TABLE graph_nodes ALTER COLUMN unit_type TYPE TEXT",
            "ALTER TABLE force_templates ADD COLUMN IF NOT EXISTS frontage_defense_km DOUBLE PRECISION",
            "ALTER TABLE force_templates ADD COLUMN IF NOT EXISTS depth_defense_km DOUBLE PRECISION",
            "ALTER TABLE force_templates ADD COLUMN IF NOT EXISTS frontage_offense_km DOUBLE PRECISION",
            "ALTER TABLE force_templates ADD COLUMN IF NOT EXISTS depth_offense_km DOUBLE PRECISION",
            # Episodic-register columns on the clause store (world model:
            # project-scoped clauses with updatable-state slots and
            # deterministic bitemporal supersession).
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS project_id UUID",
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS slot TEXT",
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS kind VARCHAR(16)",
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS superseded_by UUID",
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()",
            # Observation payload: a state observation carries its typed
            # value so node columns can MIRROR the chain's current value
            # (the position-track pattern generalized to attributes).
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS value_text TEXT",
            "ALTER TABLE fact_clauses ADD COLUMN IF NOT EXISTS value_num DOUBLE PRECISION",
            "CREATE INDEX IF NOT EXISTS ix_fact_clauses_project ON fact_clauses (project_id)",
            # Unified-catalogue classification vocabulary: equipment_type
            # slugs run to 44 chars and category bins to 93 — wider than
            # the legacy VARCHAR(32)/VARCHAR(64) columns.
            'ALTER TABLE weg_equipment ALTER COLUMN "class" TYPE TEXT',
            "ALTER TABLE weg_equipment ALTER COLUMN category TYPE TEXT",
            'ALTER TABLE weg_equipment_seed_baseline ALTER COLUMN "class" TYPE TEXT',
            "ALTER TABLE weg_equipment_seed_baseline ALTER COLUMN category TYPE TEXT",
            # Tier is retired (merge decision in force: `tier` dropped).
            "ALTER TABLE weg_equipment DROP COLUMN IF EXISTS tier",
            "ALTER TABLE weg_equipment_seed_baseline DROP COLUMN IF EXISTS tier",
            # Canonical per-country list beside the joined display string —
            # the facet/filter machinery reads the list, never the join.
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS countries JSONB",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN IF NOT EXISTS countries JSONB",
            # Operator (proliferation) list, introduction year, and the
            # full figure list — the origin/operator split, the year-range
            # filter, and the Wikipedia-style gallery all read these.
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS operators JSONB",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN IF NOT EXISTS operators JSONB",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS introduction_year INTEGER",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN IF NOT EXISTS introduction_year INTEGER",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS images JSONB",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN IF NOT EXISTS images JSONB",
            # Full-content search: one lowercase blob per record + a
            # trigram index so multi-term substring search stays fast.
            # The SOURCE's category hierarchy (ODIN domain path), so the
            # pickers walk a real taxonomy instead of extraction shards.
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS category_group TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN IF NOT EXISTS category_group TEXT",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS category_path JSONB",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN IF NOT EXISTS category_path JSONB",
            "ALTER TABLE weg_equipment ADD COLUMN IF NOT EXISTS search_blob TEXT",
            "ALTER TABLE weg_equipment_seed_baseline ADD COLUMN IF NOT EXISTS search_blob TEXT",
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "CREATE INDEX IF NOT EXISTS ix_weg_equipment_search_blob "
            "ON weg_equipment USING gin (search_blob gin_trgm_ops)",
        ):
            await conn.execute(text(ddl))


def _checksum(rows) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]


async def _seed_registry(
    session: AsyncSession, registry: str, model, pk_name: str,
    seed_rows: list[dict], version: str,
) -> None:
    """Versioned apply: fresh -> insert all; same version -> no-op;
    version bump -> per-column three-way merge against the baseline."""
    meta = await session.get(ReferenceSeedMeta, registry)
    checksum = _checksum(seed_rows)
    if meta and meta.seed_version == version:
        return

    table = model.__table__.name
    baseline = {}
    if meta:
        rows = (await session.execute(
            text(f"SELECT * FROM {table}_seed_baseline"))).mappings().all()
        baseline = {r[pk_name]: dict(r) for r in rows}

    divergences = []
    for seed in seed_rows:
        pk = seed[pk_name]
        live = await session.get(model, pk)
        if live is None:
            session.add(model(**seed, source="bundled"))
            continue
        base_row = baseline.get(pk)
        for col, new_val in seed.items():
            if col == pk_name:
                continue
            live_val = getattr(live, col)
            base_val = base_row.get(col) if base_row else None
            if live_val == new_val:
                continue
            if base_row is None or live_val == base_val or live_val is None:
                setattr(live, col, new_val)
            else:
                divergences.append(f"{table}.{pk}.{col}: kept {live_val!r} over seed {new_val!r}")

    # Refresh the baseline to the applied seed.
    await session.execute(text(f"DELETE FROM {table}_seed_baseline"))
    cols = list(seed_rows[0].keys()) if seed_rows else []
    for seed in seed_rows:
        col_list = ", ".join(cols)
        params = ", ".join(f":{c}" for c in cols)
        # JSONB columns (list/dict seed values) must cross the raw-SQL
        # boundary as JSON text — asyncpg cannot encode a python list
        # as a query argument.
        bound = {k: (json.dumps(v) if isinstance(v, (list, dict))
                     else v)
                 for k, v in seed.items()}
        await session.execute(
            text(f"INSERT INTO {table}_seed_baseline ({col_list}) VALUES ({params})"),
            bound,
        )
    if meta:
        meta.seed_version, meta.checksum = version, checksum
    else:
        session.add(ReferenceSeedMeta(registry=registry, seed_version=version, checksum=checksum))
    for d in divergences:
        log.warning("seed divergence (kept live): %s", d)


_CATALOG_DIR_NAME = "weg_catalog"


def _catalog_dir() -> Path:
    return DATA_DIR / _CATALOG_DIR_NAME


def _catalog_checksum() -> str:
    """Byte-level checksum over every bundled catalogue file (records,
    crosswalk, images index) — cheap enough to run every boot; the JSONL is
    only parsed when a rebuild is actually due."""
    h = hashlib.sha256()
    for path in sorted(_catalog_dir().glob("*")):
        if path.is_file():
            h.update(path.name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:32]


def _load_catalog_records() -> list:
    """Parse the unified WEG catalogue (the ODIN + legacy-seed merge). Bins
    ship gzipped (~10x — the seed stays byte-complete while the repo stays
    tens of MB). A malformed line is a seed defect — surface it loudly,
    never skip."""
    import gzip
    rows = []
    paths = sorted(_catalog_dir().glob("*.jsonl")) + sorted(
        _catalog_dir().glob("*.jsonl.gz"))
    for path in paths:
        if path.suffix == ".gz":
            body = gzip.decompress(path.read_bytes()).decode("utf-8")
        else:
            body = path.read_text()
        # Split on \n only: str.splitlines() also breaks on Unicode line
        # separators (U+2028), which can legally appear RAW inside JSON
        # strings — a record containing one would be torn mid-string.
        for lineno, line in enumerate(body.split("\n"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as e:
                raise ValueError(
                    f"catalog seed {path.name} line {lineno}: {e}") from e
            if row.get("id"):
                rows.append(row)
    return rows


def _load_crosswalk() -> dict:
    """legacy weg_id -> {primary, targets, split} (the merge's crosswalk;
    every pre-merge identifier resolves to its unified record)."""
    path = _catalog_dir() / "crosswalk.json"
    if not path.exists():
        return {}
    body = json.loads(path.read_text())
    return body.get("crosswalk") or {}


def _load_images_index() -> dict:
    """record id -> {image_path, images: [...]} assembled at seed-build time
    from the ODIN live-original fetch + the legacy PDF-extraction manifest.
    Paths are relative to backend/app/data/weg_images/."""
    path = _catalog_dir() / "images_index.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


async def _load_reference_store(session: AsyncSession):
    """Versioned wholesale rebuild of the world-model reference store
    (reference_nodes/links/specs + weg_catalog fact_clauses) from the unified
    catalogue via the derivation adapter. Returns the parsed catalogue records
    when it rebuilt (so the projection materializes from them), else None.
    The store holds NO runtime state, so a rebuild is a full replace."""
    checksum = _catalog_checksum()
    meta = await session.get(ReferenceSeedMeta, "reference_store")
    if (meta and meta.seed_version == REFERENCE_STORE_VERSION
            and meta.checksum == checksum):
        return None

    records = _load_catalog_records()
    result = derivation.derive_unified_catalog(records)
    images = _load_images_index()
    for node in result["nodes"]:
        if node.get("is_catalog_root") and images.get(node["key"], {}).get("image_path"):
            node["image_path"] = images[node["key"]]["image_path"]

    # Wholesale replace the catalog-derived reference store (FK-safe order).
    await session.execute(delete(ReferenceSpec))
    await session.execute(
        delete(FactClause).where(FactClause.source_kind == "weg_catalog"))
    await session.execute(delete(ReferenceLink))
    await session.execute(delete(ReferenceNode))
    await session.flush()

    # Chunked bulk inserts: root sheet_data carries the full verbatim record
    # (F8), so one executemany over the whole corpus would stage ~240MB of
    # bound parameters in a single call.
    for model, key, chunk in ((ReferenceNode, "nodes", 300),
                              (ReferenceLink, "links", 2000),
                              (ReferenceSpec, "specs", 5000),
                              (FactClause, "clauses", 1000)):
        batch = result[key]
        for i in range(0, len(batch), chunk):
            await session.execute(model.__table__.insert(), batch[i:i + chunk])

    if meta:
        meta.seed_version, meta.checksum = REFERENCE_STORE_VERSION, checksum
    else:
        session.add(ReferenceSeedMeta(
            registry="reference_store", seed_version=REFERENCE_STORE_VERSION,
            checksum=checksum))
    log.info("reference store: %d nodes, %d links, %d specs, %d clauses",
             len(result["nodes"]), len(result["links"]),
             len(result["specs"]), len(result["clauses"]))
    return records


def _iter_structured_tuples(rec: dict, buckets=None):
    sp = rec.get("specs") or {}
    for bucket, tuples in sp.items():
        if bucket == "narrative":
            continue
        if buckets and bucket not in buckets:
            continue
        for t in tuples:
            yield bucket, t


def _to_meters(value, unit):
    if value is None:
        return None
    unit = (unit or "").lower()
    if unit in ("km", "kilometer", "kilometers"):
        return value * 1000.0
    if unit in ("m", "meter", "meters", ""):
        return value
    if unit in ("ft", "feet"):
        return value * 0.3048
    if unit in ("nmi", "nm"):
        return value * 1852.0
    if unit in ("mi", "mile", "miles"):
        return value * 1609.344
    return None


def _first_prop(rec, prop, buckets=None, stations=None):
    """First structured tuple with the given canonical property, in source
    order, optionally restricted to buckets / station keys."""
    hits = []
    for bucket, t in _iter_structured_tuples(rec, buckets):
        if t.get("property") != prop:
            continue
        if stations and t.get("station") not in stations:
            continue
        hits.append(t)
    hits.sort(key=lambda t: (t.get("source_order") or 0))
    return hits[0] if hits else None


def _tuple_display(t):
    val = t.get("raw_value") if t.get("raw_value") not in (None, "") else t.get("value_text")
    if val in (None, ""):
        return None
    unit = t.get("raw_unit") or t.get("unit")
    if unit and unit not in str(val):
        return f"{val} {unit}"
    return str(val)


def _domain_for(rec) -> str:
    """Catalog filter domain from the merge's bin taxonomy. The catch-all
    bin (space + the handful of unroutable legacy records) splits on
    whether the record is an orbital system."""
    cat = rec.get("category") or ""
    for prefix in ("land", "air", "sea"):
        if cat.startswith(prefix + "_"):
            return prefix
    if rec.get("orbit_class") or "satellite" in (rec.get("equipment_type") or ""):
        return "space"
    return "land"


def _detection_range_m(rec):
    """The is_default detection candidate when the merge produced one, else
    the record's largest stated detection range (the envelope figure a
    detection ring shows)."""
    best = None
    for bucket, t in _iter_structured_tuples(rec, ("detection_range_candidate",)):
        if t.get("is_default") and t.get("value_num") is not None:
            return int(t["value_num"])
    for bucket, t in _iter_structured_tuples(rec):
        if t.get("property") != "range_detection":
            continue
        m = _to_meters(t.get("value_num"), t.get("unit") or t.get("canonical_unit"))
        if m and (best is None or m > best):
            best = m
    return int(best) if best else None


def _road_speed_kph(rec):
    """Largest unconditioned speed_maximum stated in km/h (land mobility;
    naval knots and airspeeds stay in the spec store, not this column)."""
    best = None
    for bucket, t in _iter_structured_tuples(rec):
        if t.get("property") != "speed_maximum":
            continue
        if (t.get("unit") or "").lower() not in ("km/h", "kph", "kmh"):
            continue
        if t.get("condition"):
            continue
        v = t.get("value_num")
        if v is not None and (best is None or v > best):
            best = v
    return int(best) if best else None


def _max_altitude_m(rec):
    """Max stated ceiling/altitude-envelope figure in metres (feeds the
    range-candidate 3D envelope when the candidate itself states none)."""
    best = None
    for bucket, t in _iter_structured_tuples(rec):
        if t.get("property") not in ("service_ceiling", "altitude_envelope"):
            continue
        for v in (t.get("value_num_high"), t.get("value_num")):
            m = _to_meters(v, t.get("unit") or t.get("canonical_unit"))
            if m and 50.0 <= m <= 40000.0 and (best is None or m > best):
                best = m
    return int(best) if best else None


# Engagement-range harvest: the curated engagement_range_candidate
# bucket covers only 637 of 4,297 systems; the rest state their firing
# ranges in ordinary spec rows ("Maximum Effective Range (ATGM)" on the
# T-90's weapon station). Harvest = allowlisted range labels, distance
# units only, with a plausibility window. The label blocklist keeps
# mobility/sensor/mechanical ranges (cruising, detection, traverse,
# range finder) out of the ENGAGEMENT list — those have their own homes.
_RANGE_ALLOW = re.compile(
    r"(effective|engagement|firing|operational|maximum|launch)\s+range"
    r"|maximum\s+effective", re.I)
_RANGE_BLOCK = re.compile(
    r"cruis|ferry|flight|traverse|elevat|finder|detect|transmis"
    r"|communicat|ford|swim|endurance|service|slant|dive|depth", re.I)
_RANGE_UNIT_M = {"": 1.0, "m": 1.0, "meter": 1.0, "meters": 1.0,
                 "km": 1000.0, "nm": 1852.0, "mi": 1609.0,
                 "mile": 1609.0, "miles": 1609.0,
                 "yd": 0.9144, "yds": 0.9144, "ft": 0.3048}
# A station-less "operational/maximum range" means MOBILITY on a
# platform (a helicopter's 450 km is how far it flies) and REACH on a
# weapon (a CRBM's 300 km is what it engages at). Bare maximum/
# operational rows only harvest when the system IS the weapon.
_RANGE_EFFECTIVE = re.compile(r"effective|engagement|firing", re.I)
# Word-boundaried: "bomber" and "gunship" are PLATFORMS; "bomb" and
# "gun" are weapons.
_WEAPON_TYPE = re.compile(
    r"\b(missile|rocket|bomb|torpedo|munition|grenade|crbm|srbm|mrbm"
    r"|irbm|lacm|glcm|alcm|ascm|atgm|manpads|loitering|mortar|howitzer"
    r"|artillery|mlrs|cannon|gun|rifle|launcher)\b", re.I)


def _harvest_range_candidates(rec):
    """Engagement-range rows living OUTSIDE the curated bucket, unit-
    normalized to meters. The merge's own tuple BUCKET is the semantic
    authority — weapon_station rows are weapon-mounted reach; a range on
    a descriptive/component row of a PLATFORM (not a weapon) past 50 km
    is the vehicle's mobility or radio range wearing an engagement label
    (ODIN helicopter and bomber sheets write flight range as "Maximum
    Effective Range"), so it never harvests. A row with a non-distance
    unit (km/h, sec) is never a range; unit-less values are meters (the
    sheets' convention). Deduped on (label, meters)."""
    out = []
    seen = set()
    weapon_typed = bool(_WEAPON_TYPE.search(
        str(rec.get("equipment_type") or "")))
    for bucket, t in _iter_structured_tuples(rec):
        if bucket == "engagement_range_candidate":
            continue
        label = " ".join(str(t.get("raw_name") or t.get("label") or "").split())
        if not label or not _RANGE_ALLOW.search(label) \
                or _RANGE_BLOCK.search(label):
            continue
        weapon_row = bucket in ("weapon_station", "ammunition_option",
                                "munition")
        if not weapon_row and not weapon_typed \
                and not _RANGE_EFFECTIVE.search(label):
            continue
        if t.get("value_num") is None:
            continue
        station_raw = str(t.get("station") or "")
        unit = str(t.get("raw_unit") or "").strip().lower()
        factor = _RANGE_UNIT_M.get(unit)
        if factor is None:
            continue
        range_m = int(float(t["value_num"]) * factor)
        if range_m < 25 or range_m > 600_000:
            continue
        if not weapon_typed and not weapon_row and range_m > 50_000:
            continue
        full_label = f"{station_raw} · {label}" if station_raw else label
        key = (full_label.lower(), range_m)
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": full_label, "range_m": range_m,
                    "condition": (t.get("raw_condition")
                                  or t.get("condition") or None),
                    "raw_label": label,
                    "station": station_raw,
                    "weapon_row": weapon_row,
                    "explicit_unit": unit != ""})
    return out


def _pick_harvest_default(harvested, weapon_typed):
    """The engagement-ring default from harvested rows, doctrinally
    shaped: the MAIN weapon station outranks secondary weapons (a tank's
    ring is its main gun, never the commander's machine gun), an
    effective/engagement label outranks a bare maximum, and a top value
    more than 5x the runner-up is a mislabeled source row (a '500 km
    effective range' on a tank), dropped rather than painted."""
    def guarded_max(pool):
        # Outliers compare against the next DISTINCT value — duplicate
        # source rows must not vouch for each other.
        vals = sorted(pool, key=lambda h: -h["range_m"])
        while len(vals) >= 2:
            lower = [h for h in vals if h["range_m"] < vals[0]["range_m"]]
            if lower and vals[0]["range_m"] > 5 * lower[0]["range_m"]:
                vals = lower
            else:
                break
        return vals[0] if vals else None

    effective = re.compile(r"effective|engagement", re.I)
    confident = [h for h in harvested
                 if h["explicit_unit"] or h["range_m"] >= 1000]
    mains = [h for h in confident
             if h["station"] in ("main_gun", "main_armament")]
    weapon_rows = [h for h in confident if h["weapon_row"]]
    # Rings mint conservatively: only rows the merge classed as
    # weapon-mounted, or any confident effective row when the system
    # IS the weapon. A platform with only descriptive ranges shows
    # candidates and draws no ring.
    for pool in ([h for h in mains if effective.search(h["raw_label"])],
                 mains,
                 [h for h in weapon_rows if effective.search(h["raw_label"])],
                 weapon_rows,
                 [h for h in confident if effective.search(h["raw_label"])]
                 if weapon_typed else []):
        pick = guarded_max(pool)
        if pick:
            return pick
    return None


def _display_name(rec, weg_id):
    """The analyst-facing title for a record."""
    def slugish(v):
        return bool(v) and bool(re.fullmatch(r"[a-z0-9_]+", str(v)))

    name = (rec.get("name") or "").strip()
    if name and not slugish(name):
        return name
    full = (rec.get("full_name") or "").strip()
    if full:
        return full
    for alias in rec.get("aliases") or []:
        alias = str(alias).strip()
        if alias and not slugish(alias):
            return alias
    designation = (rec.get("designation") or "").strip()
    for candidate in (name, designation):
        if candidate:
            return " ".join(w.upper() if len(w) <= 2 else w.capitalize()
                            for w in candidate.split("_"))
    return weg_id


# ---------------------------------------------------------------------------
# The source's classification taxonomy.
#
# Every ODIN record carries domain memberships, but only SOME carry the
# ORDER: `odin_domain` (and a capture whose domainSort is null) is an
# ALPHABETIZED set — a system can sit in several taxonomy nodes (the HOT
# ATGM lives under both Air > Aircraft Armament > ... and Land >
# Infantry Weapons > ...) and the merge sorted the union, so it is NOT a
# path. The order lives in the capture's `domainSort`: the source's own
# concatenation of the PRIMARY walk, top to leaf.
#
# Resolution, strictly from the source's own data:
#   1. domainSort present -> reorder that capture's names by their
#      position in it; names outside it (a second tree's nodes) drop.
#      These ordered walks also TEACH the taxonomy: every consecutive
#      pair is a parent->child edge, every position a depth vote.
#   2. memberships without order -> thread the name set through the
#      learned tree: the longest parent->child chain inside the set is
#      the primary walk (the other names are other trees). No chain ->
#      the set's deepest known non-root node stands alone as the leaf.
#   3. no memberships at all -> the modal walk of the record's
#      equipment_type siblings (the source's taxonomy joined through
#      the source's own type field). Types with no pathed sibling stay
#      unclassified — never an invented bucket.
# ---------------------------------------------------------------------------

def _fold_domain(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _domain_membership_sets(rec):
    """[(names, sort_key), ...] per capture blob, plus the odin_domain
    union as an unordered set — captures often keep only a truncated
    domain list, so the union matters for threading."""
    out = []
    for blob in ((rec.get("capture") or {}).get("odin") or {}).values():
        if not isinstance(blob, dict):
            continue
        names = []
        for e in blob.get("domain") or []:
            if isinstance(e, dict):
                names.extend(str(v) for v in e.values() if v)
            elif e:
                names.append(str(e))
        if names:
            out.append((names, _fold_domain(blob.get("domainSort") or "")))
    od = [str(x) for x in rec.get("odin_domain") or [] if x]
    if od:
        out.append((od, ""))
    return out


def _segment_walk(sort_key, vocab):
    """domainSort -> the full ordered walk, by greedy longest-match
    segmentation against the catalogue-wide name vocabulary. Captures
    frequently truncate their `domain` list while domainSort still
    carries the WHOLE walk ('airaircraftrotarywingaircraftattack
    helicopter' with only Air + Aircraft listed), so the walk is
    recovered from the string itself, never just the listed names.
    Stops at an unrecognized chunk: the parsed prefix is still a valid
    ancestor chain."""
    walk = []
    pos = 0
    folds = vocab["folds"]
    while pos < len(sort_key):
        best = None
        for f in folds.get(sort_key[pos], ()):  # folds bucketed by first char
            if sort_key.startswith(f, pos) and (best is None or len(f) > len(best)):
                best = f
        if best is None:
            break
        walk.append(vocab["display"][best])
        pos += len(best)
    return walk


def _longest_lineage(folds, ancestor, members):
    """The longest single-ancestry chain inside one membership set —
    the set's primary walk. A set can span several trees (the HOT ATGM
    sits in both the Air and Land trees); members of the primary tree
    form a chain under the ancestor relation, the other tree's members
    do not relate to them and drop. Ordered root-first by membership
    count: an ancestor's record set strictly contains its descendants'."""
    nodes = list(dict.fromkeys(folds))
    best: list = []
    for leaf in nodes:
        chain = [n for n in nodes if n == leaf or ancestor(n, leaf)]
        if len(chain) > len(best):
            best = chain
    return sorted(best, key=lambda n: -len(members.get(n) or ()))


def _resolve_domain_walks(records):
    """record id -> the source's ordered classification walk (possibly
    empty). See the taxonomy block comment above for the rules."""
    # Catalogue-wide name vocabulary: every domain name any record
    # mentions, folded, with the most common display casing. Bucketed by
    # first character for the segmenter's prefix scans.
    display_votes: dict = {}
    sets_by_id = {}
    for rec in records:
        sets = _domain_membership_sets(rec)
        sets_by_id[rec["id"]] = sets
        for names, _ in sets:
            for n in names:
                display_votes.setdefault(_fold_domain(n), Counter())[str(n)] += 1
    vocab = {"display": {f: v.most_common(1)[0][0]
                         for f, v in display_votes.items() if f},
             "folds": {}}
    for f in vocab["display"]:
        vocab["folds"].setdefault(f[0], []).append(f)

    # Membership index + golden ancestry. Only ~900 records carry a
    # domainSort walk; the tree for everything else is INFERRED from set
    # inclusion over the whole catalogue — when (nearly) every record
    # tagged with B is also tagged with A, the source itself says A is
    # B's ancestor. The segmented walks contribute exact ancestor pairs
    # on top.
    members: dict = {}
    for rid, sets in sets_by_id.items():
        for names, _ in sets:
            for n in names:
                members.setdefault(_fold_domain(n), set()).add(rid)

    golden_pairs = set()
    ordered_by_id = {}
    root_folds = set()
    for rec in records:
        rid = rec["id"]
        best: list = []
        for _, sort_key in sets_by_id[rid]:
            if not sort_key:
                continue
            walk = _segment_walk(sort_key, vocab)
            if len(walk) > len(best):
                best = walk
        if best:
            ordered_by_id[rid] = best
            folds = [_fold_domain(n) for n in best]
            root_folds.add(folds[0])
            for i, a in enumerate(folds):
                for b in folds[i + 1:]:
                    golden_pairs.add((a, b))

    def ancestor(a, b):
        if (a, b) in golden_pairs:
            return True
        if (b, a) in golden_pairs:
            return False
        ra, rb = members.get(a) or set(), members.get(b) or set()
        if len(ra) <= len(rb) or not rb:
            return False
        return len(ra & rb) / len(rb) >= 0.9

    walks = {}
    walk_votes: dict = {}
    display = vocab["display"]
    for rec in records:
        rid = rec["id"]
        walk = ordered_by_id.get(rid) or []
        # A truncated domainSort ("airaircraft") loses to a deeper
        # lineage inferred from the record's full membership set.
        for names, _ in sets_by_id[rid]:
            lineage = _longest_lineage(
                [_fold_domain(n) for n in names], ancestor, members)
            if len(lineage) > len(walk):
                walk = [display.get(f, f) for f in lineage]
        if len(walk) == 1 and _fold_domain(walk[0]) in root_folds:
            # A bare tree root ("Land") is domain, not classification.
            walk = []
        walks[rid] = walk
        if walk:
            walk_votes.setdefault(rec.get("equipment_type"), Counter())[
                tuple(walk)] += 1
    for rec in records:
        rid = rec["id"]
        if not walks[rid]:
            votes = walk_votes.get(rec.get("equipment_type"))
            if votes:
                walks[rid] = list(votes.most_common(1)[0][0])
    return walks


def _search_blob(rec, walk=()):
    """Everything searchable about the record, lowercased, one blob: the
    q filter reaches CONTENT (descriptions, every specification label and
    value, designations, operators), not just names — for the human
    search box and the agent's search_equipment tool alike. Identity
    strings are ALSO baked in punctuation-folded ("b2spirit", "t90") so
    every hyphen/space/underscore writing of a designation matches."""
    parts = [rec.get("name"), rec.get("full_name"), rec.get("id"),
             rec.get("equipment_type"), rec.get("category")]
    parts += list(walk)
    identity = [rec.get("name"), rec.get("full_name"), rec.get("id")]
    identity += rec.get("aliases") or []
    parts += [re.sub(r"[^a-z0-9]", "", str(x).lower())
              for x in identity if x]
    parts += rec.get("aliases") or []
    parts += rec.get("legacy_weg_ids") or []
    parts += rec.get("origin") or []
    parts += rec.get("proliferation") or []
    if isinstance(rec.get("odin_notes"), str):
        parts.append(rec["odin_notes"])
    parts += [n for n in rec.get("notes") or [] if isinstance(n, str)]
    for bucket, t in _iter_structured_tuples(rec):
        for f in ("label", "raw_name", "raw_value", "value_text",
                  "condition", "station"):
            v = t.get(f)
            if v:
                parts.append(str(v))
    for v in rec.get("variants") or []:
        if isinstance(v, dict):
            parts.append(str(v.get("designation") or ""))
            parts.append(str(v.get("description") or ""))
    blob = " ".join(str(p) for p in parts if p).lower()
    return blob[:60000]


_ENTRIES_PATH = re.compile(r"entries\[\d+\]$")


def _spec_value_norm(v):
    """Value identity for dedup: '1,400 m' == '1400' == '1,400'."""
    s = " ".join(str(v).split()).lower()
    m = re.match(r"^([\d,.]+)\s*[a-z%/]*$", s)
    if m:
        try:
            return str(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return re.sub(r"[^a-z0-9]", "", s)


def _spec_qualifier(cond):
    """Condition -> a human label suffix. extremum/regime restate the
    label itself ('Maximum Effective Range') and drop; the rest read as
    '(day)', '(external load)', '(HEAT)'."""
    quals = []
    for part in str(cond or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            quals.append(part)
            continue
        k, v = (x.strip() for x in part.split("=", 1))
        if k in ("extremum", "regime") or not v:
            continue
        if k == "load_state":
            quals.append(f"{v} load")
        else:
            quals.append(v)
    return f" ({', '.join(quals)})" if quals else ""


def _catalog_ui_sheet_data(rec):
    """weg_equipment.sheet_data for the catalog UI: the source's OWN
    structure, never a flat pile. specs = ordered
    {section: {row_label: value}} — weapon stations and ammunition
    options are their own sections (the printed sheet's subsections),
    condition qualifiers ride the row label ('Maximum Effective Range
    (day)'), and duplicate source positions dedupe by numeric-normalized
    value ('1,400 m' == '1400') — the flat map numbered every collision
    (2)..(7) and read as garbage. The full verbatim record rides
    reference_nodes.sheet_data — this is the display projection."""
    # Pre-pass: split the ammunition tuples into per-OPTION runs. The
    # capture files every option's rows under ONE subsection header, so
    # the path cannot split them — but the rows run sequentially per
    # option, delimited by their 'Ammunition Type'/'Name' rows. Runs
    # merge ACROSS sources by ammunition type ('1,400 m' from the ODIN
    # run dedupes against '1400' from the seed echo), and the display
    # name combines the designation with the type ('BK-883 (HEAT)').
    def _clean_token(v):
        tok = str(v or "").strip()
        return tok if re.search(r"[A-Za-z0-9]{2}", tok) else ""

    ammo_runs = {}
    ammo_key_of = {}
    current = None
    for bucket, t in _iter_structured_tuples(rec, ("ammunition_option",)):
        label = str(t.get("label") or "")
        if label == "Ammunition Type":
            current = {"type": _clean_token(t.get("raw_value")),
                       "designation": ""}
        elif label == "Name":
            parts = [p.strip() for p in str(t.get("raw_value") or "").split(",")]
            current = {"type": _clean_token(parts[1] if len(parts) > 1 else ""),
                       "designation": _clean_token(parts[-1] if parts else "")}
        elif current is None:
            cond = str(t.get("condition") or "")
            m = re.search(r"ammunition=([^;]+)", cond)
            current = {"type": _clean_token(m.group(1)) if m else "",
                       "designation": ""}
        key = re.sub(r"[^a-z0-9]", "", (current.get("type") or
                                        current.get("designation") or
                                        "option").lower())
        run = ammo_runs.setdefault(key, {"type": "", "designation": ""})
        for f in ("type", "designation"):
            if current.get(f) and not run[f]:
                run[f] = current[f]
        ammo_key_of[id(t)] = key

    def _ammo_section(key):
        run = ammo_runs.get(key) or {}
        d, ty = run.get("designation"), run.get("type")
        if d and ty:
            return f"Ammunition — {d} ({ty})"
        return f"Ammunition — {d or ty}" if (d or ty) else "Ammunition"

    specs = {}
    seen = {}

    def add(section, label, val):
        rows = specs.setdefault(section, {})
        norm = _spec_value_norm(val)
        key = (section, label)
        if norm in seen.setdefault(key, set()):
            return
        seen[key].add(norm)
        if label in rows:
            rows[label] = f"{rows[label]} · {val}"
        else:
            rows[label] = val

    for bucket, t in _iter_structured_tuples(rec):
        label = t.get("label") or t.get("raw_name") or t.get("property")
        if not label:
            continue
        val = _tuple_display(t)
        if val is None:
            continue
        station = t.get("station")
        if bucket == "provenance_block":
            # Source-position bookkeeping, never sheet content.
            continue
        if bucket == "ammunition_option":
            if str(label) in ("Name", "Ammunition Type"):
                continue
            section = _ammo_section(ammo_key_of.get(id(t), "option"))
        elif station:
            section = str(station).replace("_", " ").title()
        elif bucket in ("descriptive_block", "engagement_range_candidate"):
            section = ""
        else:
            section = str(bucket).replace("_", " ").title()
        add(section, f"{label}{_spec_qualifier(t.get('condition'))}", val)

    # General rows first, then sections in source order.
    ordered = {}
    if "" in specs:
        ordered[""] = specs.pop("")
    ordered.update(specs)
    out = {"specs": ordered}
    open_conflicts = sum(
        1 for b in rec.get("value_conflicts") or []
        if (b.get("adjudication") or {}).get("stays_open_for_intel_agent"))
    if open_conflicts:
        out["open_value_conflicts"] = open_conflicts
    return out


# Method-of-propulsion classification for range candidates (the §6.7
# 3D package). Candidate label/condition text overrides per row when the
# source says so; otherwise the system's equipment type IS the doctrinal
# answer: tube/rocket indirect fire flies ballistic arcs, direct-fire and
# air-defense systems engage on line of sight, unmanned systems loiter.
_TRAJECTORY_TOKENS = (("ballistic", "ballistic"), ("indirect", "ballistic"),
                      ("cruise", "cruise"), ("loiter", "loiter"),
                      ("direct", "direct"))
_TRAJECTORY_TYPE_TOKENS = (
    ("ballistic_missile", "ballistic"), ("cruise_missile", "cruise"),
    ("uav", "loiter"), ("ucav", "loiter"), ("loitering", "loiter"),
    ("mortar", "ballistic"), ("howitzer", "ballistic"),
    ("artillery", "ballistic"), ("rocket", "ballistic"), ("mlrs", "ballistic"),
    ("tank", "direct"), ("ifv", "direct"), ("apc", "direct"),
    ("atgm", "direct"), ("rifle", "direct"), ("machine_gun", "direct"),
    ("air_defense", "direct"), ("sam", "direct"), ("aaa", "direct"),
)


def _derive_trajectory(equipment_type, *texts):
    for text in texts:
        low = str(text or "").lower()
        for token, traj in _TRAJECTORY_TOKENS:
            if token in low:
                return traj
    etype = str(equipment_type or "").lower()
    for token, traj in _TRAJECTORY_TYPE_TOKENS:
        if token in etype:
            return traj
    return None


async def _project_consumer_tables(session: AsyncSession, records: list) -> None:
    """Migration by projection (design S10/F3): materialize weg_equipment and
    its child tables FROM the unified catalogue records, shape-identical to
    what every current consumer reads. weg_equipment is upserted (holdings FK
    + instance references survive); the pure-reference child tables are
    rebuilt wholesale. Aliases include every legacy weg_id via the crosswalk,
    so pre-merge references keep resolving."""
    crosswalk = _load_crosswalk()
    images = _load_images_index()

    await session.execute(delete(WegEquipmentAlias))
    await session.execute(delete(WegEquipmentEmitter))
    await session.execute(delete(WegEquipmentRangeCandidate))
    await session.flush()

    record_ids = {r["id"] for r in records}
    # alias is a GLOBAL-unique PK; two systems can share a surface form.
    # First-writer-wins, mirroring the never-clobber rule.
    seen_aliases: set = set()

    def add_alias(token, weg_id):
        token = str(token)[:512].strip() if token else None
        if token and token not in seen_aliases and token not in record_ids:
            seen_aliases.add(token)
            session.add(WegEquipmentAlias(alias=token, weg_id=weg_id))

    # The source's classification walks (see the taxonomy block comment
    # on _resolve_domain_walks), resolved over the whole catalogue first
    # because unordered records thread through the tree the ordered
    # records teach.
    walk_by_id = _resolve_domain_walks(records)

    for rec in records:
        weg_id = rec["id"]
        walk = walk_by_id.get(weg_id) or []
        cls = rec.get("classification") or {}
        origin = [o for o in rec.get("origin") or [] if o]
        caliber_t = _first_prop(rec, "caliber", buckets=("weapon_station",),
                                stations=("main_gun", "main_armament")) \
            or _first_prop(rec, "caliber", buckets=("descriptive_block",))
        crew_t = _first_prop(rec, "crew", buckets=("descriptive_block",))
        weight_t = (_first_prop(rec, "combat_weight")
                    or _first_prop(rec, "weight", buckets=("descriptive_block",)))
        date = derivation._scalar_text(rec.get("date_of_introduction"))
        if not date and rec.get("year"):
            date = str(rec["year"])
        # ODIN stamps a synthetic noon time on every introduction date
        # ("1949-06-01 12:00:00.0") — display the date, not the artifact.
        # The verbatim survives in reference_nodes.sheet_data.
        if date and re.match(r"^\d{4}-\d{2}-\d{2} \d", date):
            date = date.split(" ")[0]
        notes = [n for n in rec.get("notes") or [] if isinstance(n, str)]
        m1 = rec.get("symbol_modifier_1")
        m2 = rec.get("symbol_modifier_2")
        mod1 = (rec.get("symbol_modifier_1_code")
                or (m1.get("code") if isinstance(m1, dict) else None))
        mod2 = m2.get("code") if isinstance(m2, dict) else None

        # THE engagement ring. Candidates come from the curated bucket
        # AND the spec-row harvest; the DEFAULT is screened for both,
        # because the merge itself flagged platform mobility rows as
        # engagement defaults (the Mi-24's 450 km "Maximum Effective
        # Range, load_state=standard" is how far it FLIES). On a
        # non-weapon system no ring exceeds 50 km — no platform-mounted
        # weapon reaches that; the row itself stays a visible candidate.
        # A stated (curated) default surviving the screen wins; else the
        # doctrinal ladder picks; else no ring.
        weapon_typed = bool(_WEAPON_TYPE.search(
            str(rec.get("equipment_type") or "")))
        curated_ranges = []
        for bucket, t in _iter_structured_tuples(
                rec, ("engagement_range_candidate",)):
            if t.get("value_num") is None:
                continue
            curated_ranges.append({
                "label": str(t.get("label") or t.get("raw_label")
                             or "range"),
                "range_m": int(t["value_num"]),
                "condition": (t.get("raw_condition") or t.get("condition")
                              or None),
                "raw_label": str(t.get("label") or t.get("raw_label")
                                 or ""),
                "station": str(t.get("station") or ""),
                "weapon_row": True,
                "explicit_unit": True,
                "stated_default": bool(t.get("is_default")),
            })
        harvested = _harvest_range_candidates(rec)
        ring_eligible = [c for c in curated_ranges + harvested
                         if weapon_typed or c["range_m"] <= 50_000]
        stated = [c for c in ring_eligible if c.get("stated_default")]
        chosen_range = (max(stated, key=lambda c: c["range_m"])
                        if stated else
                        _pick_harvest_default(ring_eligible, weapon_typed))
        engagement_default = (chosen_range["range_m"]
                              if chosen_range else None)

        intro_year = rec.get("year")
        if not intro_year and date and str(date)[:4].isdigit():
            intro_year = int(str(date)[:4])
        # DISPLAY NAME, never a slug: 294 records carry a lowercase
        # designation slug in `name` while `full_name` holds the real
        # title ("b_2_spirit" vs "B-2 Spirit (Stealth Bomber)"). Prefer
        # the fullest human name, then a titled alias, and only then the
        # slug de-slugged — an analyst must never read an identifier.
        fields = dict(
            name=_display_name(rec, weg_id),
            domain=_domain_for(rec),
            equipment_class=rec.get("equipment_type"),
            # The SOURCE's taxonomy, never the merge's extraction bin:
            # category is the walk's leaf ("Bomber Aircraft"), group the
            # level above it ("Fixed Wing Aircraft"), path the whole
            # ordered walk. The bin name stays internal (shard files,
            # search blob) and never surfaces as classification.
            category=(walk[-1] if walk else None),
            category_group=(walk[-2] if len(walk) >= 3 else None),
            category_path=walk,
            countries=origin,
            operators=[p for p in rec.get("proliferation") or [] if p],
            introduction_year=int(intro_year) if intro_year else None,
            images=(images.get(weg_id) or {}).get("images") or [],
            engagement_range_m=engagement_default,
            detection_range_m=_detection_range_m(rec),
            road_speed_kph=_road_speed_kph(rec),
            crew=_tuple_display(crew_t) if crew_t else None,
            caliber=_tuple_display(caliber_t) if caliber_t else None,
            characteristics="\n\n".join(notes) or None,
            country_of_origin=", ".join(origin) or None,
            alternative_designations=", ".join(rec.get("aliases") or []) or None,
            date_of_introduction=date,
            proliferation_note=", ".join(rec.get("proliferation") or []) or None,
            combat_weight=_tuple_display(weight_t) if weight_t else None,
            description=rec.get("odin_notes") or None,
            sheet_data=_catalog_ui_sheet_data(rec),
            search_blob=_search_blob(rec, walk),
            symbol_entity_code=(rec.get("symbol_entity_code")
                                or cls.get("symbol_entity_code")),
            symbol_mod1=str(mod1)[:2] if mod1 else None,
            symbol_mod2=str(mod2)[:2] if mod2 else None,
            image_path=(images.get(weg_id) or {}).get("image_path"),
            source_page=(rec.get("odin_identifier")
                         or (rec.get("odin_identifiers") or [""])[0]),
            source="weg_import",
        )
        existing = await session.get(WegEquipment, weg_id)
        if existing is None:
            session.add(WegEquipment(weg_id=weg_id, **fields))
        else:
            for key, val in fields.items():
                setattr(existing, key, val)

        ceiling = _max_altitude_m(rec)
        # is_default marks exactly the SCREENED choice — the stored
        # merge flags proved to carry mobility rows, so the flag is
        # re-derived here, never copied through.
        for c in curated_ranges + harvested:
            session.add(WegEquipmentRangeCandidate(
                weg_id=weg_id,
                label=c["label"][:255],
                range_m=c["range_m"],
                condition=c["condition"],
                is_default=c is chosen_range,
                trajectory=_derive_trajectory(
                    rec.get("equipment_type"), c["raw_label"],
                    c["condition"]),
                max_altitude_m=ceiling,
            ))

        for alias in rec.get("aliases") or []:
            add_alias(alias, weg_id)
        for legacy in rec.get("legacy_weg_ids") or []:
            add_alias(legacy, weg_id)

        for em in rec.get("emitters") or []:
            val = str(em.get("value_text") or "").strip()
            if not val or val.lower() in ("no", "none", "n/a", "na", "ina"):
                continue
            label = str(em.get("raw_name") or em.get("property")
                        or "emitter").rstrip(": ")
            session.add(WegEquipmentEmitter(
                weg_id=weg_id,
                emitter_type=f"{label}: {val}",
                frequency_band=(val[:255] if em.get("property")
                                in ("frequency_band", "frequency") else None),
            ))

    # The crosswalk is authoritative for legacy resolution — every pre-merge
    # weg_id resolves to its unified primary record, including the ids whose
    # record split (the primary carries the alias; the split note lives on
    # the records themselves).
    for legacy, info in crosswalk.items():
        primary = (info or {}).get("primary")
        if primary in record_ids:
            add_alias(legacy, primary)

    log.info("projection: %d catalog systems materialized from the unified "
             "catalogue", len(records))


async def _migrate_legacy_weg_ids(session: AsyncSession) -> None:
    """Re-point live rows that still reference pre-merge weg_ids (project
    holdings, equipment-instance nodes) at their unified primary record via
    the crosswalk, then retire the stale legacy weg_equipment rows. Runs
    every boot; a clean database matches nothing and the pass is two cheap
    selects. Counts merge when a node already holds the unified id (the same
    rule the template loader applies)."""
    crosswalk = _load_crosswalk()
    if not crosswalk:
        return
    legacy_to_primary = {k: (v or {}).get("primary")
                         for k, v in crosswalk.items() if (v or {}).get("primary")}
    legacy_ids = list(legacy_to_primary.keys())

    holdings = (await session.execute(
        select(GraphHolding).where(GraphHolding.weg_id.in_(legacy_ids))
    )).scalars().all()
    remapped = merged = 0
    for h in holdings:
        target = legacy_to_primary[h.weg_id]
        twin = (await session.execute(
            select(GraphHolding).where(GraphHolding.node_id == h.node_id,
                                       GraphHolding.weg_id == target)
        )).scalars().first()
        if twin is not None:
            for col in ("count_authorized", "count_current", "count_degraded"):
                add = getattr(h, col) or 0
                if add:
                    setattr(twin, col, (getattr(twin, col) or 0) + add)
            await session.delete(h)
            merged += 1
        else:
            h.weg_id = target
            remapped += 1

    nodes = (await session.execute(
        select(GraphNode).where(GraphNode.weg_id.in_(legacy_ids))
    )).scalars().all()
    for n in nodes:
        n.weg_id = legacy_to_primary[n.weg_id]
    await session.flush()

    stale = (await session.execute(
        select(WegEquipment).where(WegEquipment.weg_id.in_(legacy_ids))
    )).scalars().all()
    for row in stale:
        await session.delete(row)
    if remapped or merged or nodes or stale:
        log.info("legacy weg_id migration: %d holdings re-pointed, %d merged, "
                 "%d instance nodes re-pointed, %d stale catalog rows retired",
                 remapped, merged, len(nodes), len(stale))


async def _resolve_weg_id(session: AsyncSession, raw: str):
    """Template-seed resolution delegates to the ingest resolver — ONE
    resolution ladder everywhere (exact alias/id, case-insensitive name,
    alphanumeric fold, variant designation walk-up)."""
    if not raw:
        return None
    from app.services.graph_ingest.ingest import _resolve_nomenclature
    return await _resolve_nomenclature(session, raw)


# Doctrinal equivalences into the closed ladder — the same mapping the
# ingestion surface documents (Squadron=Battalion-equivalent, Troop/
# Battery=Company-equivalent). The old sanitizer NULLED these spellings,
# which silently un-ranked every cavalry troop, artillery battery, and
# squadron in the bundled templates (they vanished from the echelon
# roll-up). "Command" stays None on purpose — a command is not a ladder
# echelon.
_ECHELON_EQUIVALENTS = {
    "Troop": "Company", "Battery": "Company", "Squadron": "Battalion",
    "Crew": "Team", "Detachment": "Platoon", "Group": "Regiment",
}


def _sanitize_echelon(value):
    """Loader boundary: extraction data may carry echelon spellings
    outside the closed set ('Team/Crew', 'Troop'). Doctrinal-equivalence
    map first, then prefix-match into the enum; otherwise null — echelon
    is nullable and null is legal."""
    if not value:
        return None
    if value in ECHELONS:
        return value
    head = str(value).split("/")[0].strip().title()
    head = _ECHELON_EQUIVALENTS.get(head, head)
    return head if head in ECHELONS else None


async def _load_template_extracts(session: AsyncSession) -> None:
    """Template extract JSONLs -> ForceTemplate headers + bodies as
    template_id-scoped graph rows. Match-or-mint by template key.
    force_templates_extract = RU/CN (ATP 7-100.1/.3); us_templates_extract
    = US/NATO (armypubs FM/ATP org doctrine) — one library, both sides."""
    paths = [DATA_DIR / "force_templates_extract.jsonl",
             DATA_DIR / "us_templates_extract.jsonl",
             # Hybrid-Threat org guide (TC 7-100.4 + TC 7-100.2 figures); 55
             # htfs_ templates. Distinct keys from rus_/chn_ — an additive set
             # (the bdet/cdet/ifc names overlap concepts but are distinct keys).
             DATA_DIR / "htfs_templates_extract.jsonl"]
    content = "".join(p.read_text() for p in paths if p.exists())
    if not content.strip():
        return
    # The loader's own logic participates in the checksum: a loader fix
    # (echelon equivalences) must reseed even when the extract bytes are
    # unchanged, or every deployment keeps the mis-loaded library.
    _TEMPLATE_SEED_LOGIC_REV = "2026-07-29.2-unified-ids-ingest-resolver"
    checksum = _checksum(content + _TEMPLATE_SEED_LOGIC_REV)
    meta = await session.get(ReferenceSeedMeta, "force_templates")
    if meta and meta.checksum == checksum:
        return
    # The bundled extract changed (or a stale prior seed loaded structure
    # without its enriched equipment). The match-or-mint loop below SKIPS
    # existing keys, so an in-place update never backfills holdings — drop
    # the old BUNDLED library first so the new extract fully replaces it
    # (template_id-scoped nodes + their holdings cascade). User templates
    # (source != 'bundled') and instantiated project nodes (project_id-
    # scoped copies) are independent and untouched.
    if meta is not None:
        await session.execute(
            delete(ForceTemplate).where(ForceTemplate.source == "bundled"))
        await session.flush()
    added = 0
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tpl = json.loads(line)
        except ValueError:
            log.warning("template extract: bad line skipped")
            continue
        key = tpl.get("key")
        if not key:
            continue
        exists = (await session.execute(
            select(ForceTemplate).where(ForceTemplate.key == key))).scalar_one_or_none()
        if exists:
            continue
        # Per-template savepoint: one malformed template must never
        # poison the whole seed (an out-of-enum echelon did, once).
        # Flush BEFORE opening the savepoint so no prior template's
        # pending rows leak into this one's flush (observed live: the
        # engineer template's holdings flushed inside the helicopter
        # template's savepoint and died on its rolled-back nodes).
        await session.flush()
        savepoint = await session.begin_nested()
        try:
            header = ForceTemplate(
                id=uuid.uuid4(), key=key, name=tpl.get("name") or key,
                echelon=_sanitize_echelon(tpl.get("echelon")),
                tier=tpl.get("tier"),
                doctrine_source=tpl.get("doctrine_source"),
                as_of=tpl.get("as_of"), source="bundled",
            )
            session.add(header)
            # Default affiliation from the template (US = Friend,
            # RU/CN legacy file omits it → Hostile). Instantiation
            # can still override per placement.
            tpl_affil = tpl.get("affiliation") or "Hostile"
            by_ref: dict = {}
            pending_holdings: list = []
            nodes = tpl.get("nodes") or []
            for n in nodes:  # first pass: nodes
                node = GraphNode(
                    id=uuid.uuid4(), template_id=header.id,
                    entity_type="unit", name=n.get("name") or "unnamed",
                    affiliation=tpl_affil,
                    echelon=_sanitize_echelon(n.get("echelon")),
                    unit_type=n.get("unit_type"),
                    personnel_authorized=n.get("personnel_authorized"),
                    created_by="_seed",
                )
                session.add(node)
                by_ref[n.get("ref")] = node
                # Merge-aware per node: two source rows can resolve to
                # ONE catalog system (BTR-D and its BTR-ZD variant both
                # -> btr_d) and (node, weg) is unique — counts sum, the
                # first raw string survives (same rule as the alias
                # sweep). Unresolved rows key by their raw string.
                merged: dict = {}
                for h in n.get("holdings") or []:
                    raw = h.get("nomenclature_raw")
                    # Seeded templates ship RESOLVED: the extract file
                    # carries weg_id decided at curation time — runtime
                    # resolution is only the fallback for rows the
                    # curation has not covered yet.
                    weg = (h.get("weg_id")
                           or await _resolve_weg_id(session, raw))
                    mk = weg or f"raw:{raw}"
                    if mk in merged:
                        prev = merged[mk]
                        if h.get("count_authorized"):
                            prev["count_authorized"] = (
                                (prev.get("count_authorized") or 0)
                                + h["count_authorized"])
                    else:
                        merged[mk] = {"weg_id": weg, "raw": raw,
                                      "count_authorized":
                                      h.get("count_authorized")}
                pending_holdings.append((node, merged))
            # Nodes flush BEFORE any holding exists in the session —
            # application-enforced order, no reliance on unit-of-work
            # topology (the airborne template's root-with-holdings
            # flushed its holdings first and FK-failed).
            await session.flush()
            for node, merged in pending_holdings:
                for m in merged.values():
                    session.add(GraphHolding(
                        node_id=node.id,
                        weg_id=m["weg_id"],
                        nomenclature_raw=m["raw"],
                        count_authorized=m["count_authorized"],
                        created_by="_seed",
                    ))
            # Flush nodes + holdings BEFORE linking the template's
            # root: template.root_node_id -> node -> template is a
            # dependency cycle, and with the link pending SQLAlchemy
            # defers the ROOT node's insert past its own holdings —
            # fatal exactly when a root carries equipment (the VDV
            # brigade fleet).
            await session.flush()
            for n in nodes:  # second pass: parents + root link
                pref = n.get("parent_ref")
                if pref and pref in by_ref and n.get("ref") in by_ref:
                    by_ref[n["ref"]].organic_parent_id = by_ref[pref].id
                elif not pref and header.root_node_id is None and n.get("ref") in by_ref:
                    header.root_node_id = by_ref[n["ref"]].id
            await session.flush()
            await savepoint.commit()
            added += 1
        except Exception as tpl_err:
            await savepoint.rollback()
            log.warning("template extract: %s skipped: %s", key, tpl_err)
    if meta:
        meta.seed_version, meta.checksum = REGISTRY_SEED_VERSION, checksum
    else:
        session.add(ReferenceSeedMeta(
            registry="force_templates", seed_version=REGISTRY_SEED_VERSION, checksum=checksum))
    log.info("template extract: %d templates added", added)


# Concept tokens too generic to disambiguate a htfs_ template — never used as
# an about-key trigger on their own (they map to most of the library).
_DOCTRINE_STOPTOKENS = {
    "example", "generic", "taskorg", "possible", "organization", "command",
    "structure", "force", "components", "staff", "typical", "level", "in",
    "battalion", "company", "brigade", "division", "platoon", "squad",
    "battery", "section", "hq", "headquarters", "of", "and", "the",
}


def _htfs_token_index(keys: list[str]) -> dict:
    """token -> set(htfs_ keys). Only distinctive tokens (mapping to a small
    set of keys) drive clause->template attribution, so 'battalion' never
    binds a clause but 'btg' / 'spf' / 'guerrilla' do."""
    index: dict = {}
    for key in keys:
        for token in key.replace("htfs_", "").split("_"):
            if len(token) < 2 or token in _DOCTRINE_STOPTOKENS:
                continue
            index.setdefault(token, set()).add(key)
    return {t: ks for t, ks in index.items() if 1 <= len(ks) <= 8}


def _derive_doctrine_clauses(md_text: str, htfs_keys: list[str]) -> list[dict]:
    """Parse the TC 7-100.2 employment notes into gnomic clauses (statements
    about force-template TYPES). Each clause's `about` is the htfs_ template
    keys whose distinctive concept tokens appear in the clause (design S4.6/
    S6.5 — doctrine is the gnomic register keyed to the types it governs)."""
    token_index = _htfs_token_index(htfs_keys)
    section = None
    clauses = []
    for raw in md_text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if line.startswith("#"):
            continue
        text = line.lstrip("-* ").strip()
        if len(text) < 25:
            continue
        tokens = set(re.findall(r"[a-z]+", text.lower()))
        about = set()
        for token in tokens:
            about |= token_index.get(token, set())
        clauses.append(dict(
            id=uuid.uuid4(), text=text, register="gnomic", speaker="TC 7-100.2",
            source_kind="doctrine",
            source_locus=f"tc71002_employment_notes.md :: {section or 'preamble'}",
            about=sorted(about), valid_from=None, valid_to=None,
            observed_at=None, embedding=None))
    return clauses


async def _load_doctrine_clauses(session: AsyncSession) -> None:
    """OPFOR doctrine (TC 7-100.2 employment notes) -> gnomic fact_clauses
    about the htfs_ templates they govern. Versioned wholesale replace of the
    doctrine-sourced clauses only; the weg_catalog clauses are untouched."""
    md_path = DATA_DIR / "tc71002_employment_notes.md"
    tpl_path = DATA_DIR / "htfs_templates_extract.jsonl"
    if not md_path.exists() or not tpl_path.exists():
        return
    md_text = md_path.read_text()
    htfs_keys = []
    for line in tpl_path.read_text().splitlines():
        line = line.strip()
        if line:
            key = json.loads(line).get("key")
            if key:
                htfs_keys.append(key)
    checksum = _checksum(md_text + "\x00" + "\x00".join(sorted(htfs_keys)))
    meta = await session.get(ReferenceSeedMeta, "doctrine_clauses")
    if meta and meta.seed_version == REFERENCE_STORE_VERSION and meta.checksum == checksum:
        return
    await session.execute(delete(FactClause).where(FactClause.source_kind == "doctrine"))
    await session.flush()
    clauses = _derive_doctrine_clauses(md_text, htfs_keys)
    if clauses:
        await session.execute(FactClause.__table__.insert(), clauses)
    if meta:
        meta.seed_version, meta.checksum = REFERENCE_STORE_VERSION, checksum
    else:
        session.add(ReferenceSeedMeta(
            registry="doctrine_clauses", seed_version=REFERENCE_STORE_VERSION,
            checksum=checksum))
    with_keys = sum(1 for c in clauses if c["about"])
    log.info("doctrine clauses: %d gnomic clauses (%d with template about-keys)",
             len(clauses), with_keys)


async def bootstrap_entity_graph() -> None:
    await ensure_schema()
    async with async_session() as session:
        await _seed_registry(
            session, "entity_types", EntityType, "type_key",
            [dict(type_key=k, label=l, is_fixed=f, symbol_set=ss,
                  symbol_entity_code=se, default_category=c)
             for k, l, f, ss, se, c in ENTITY_TYPE_SEED],
            REGISTRY_SEED_VERSION)
        await _seed_registry(
            session, "relationship_types", RelationshipType, "type_key",
            [dict(type_key=k, label=l, inverse_label=i, is_hierarchical=h)
             for k, l, i, h in RELATIONSHIP_TYPE_SEED],
            REGISTRY_SEED_VERSION)
        await _seed_registry(
            session, "field_defs", FieldDef, "field_key",
            [dict(field_key=k, label=l, value_type=v)
             for k, l, v in FIELD_DEF_SEED],
            REGISTRY_SEED_VERSION)
        await _seed_registry(
            session, "product_types", ProductType, "type_key",
            [dict(type_key=k, label=l, category=c, ipoe_step=st,
                  output_formats=of, depends_on=dep,
                  fanout_dimension=fd, declared_fact_classes=fc,
                  writer_spec_key=ws, dev_only=dv)
             for k, l, c, st, of, dep, fd, fc, ws, dv
             in PRODUCT_TYPE_SEED],
            PRODUCT_REGISTRY_VERSION)
        # World-model reference store: derive it wholesale from the unified
        # catalogue, then materialize the existing consumer tables FROM the
        # same records (migration by projection, F3).
        records = await _load_reference_store(session)
        if records is not None:
            await _project_consumer_tables(session, records)
            await session.flush()
        # Re-point any live rows still carrying pre-merge weg_ids (cheap
        # no-op once clean; repairs restored/older databases every boot).
        await _migrate_legacy_weg_ids(session)
        await _load_template_extracts(session)
        await _load_doctrine_clauses(session)
        await session.commit()
