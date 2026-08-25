"""SITEMP — Situational Template — ATP 2-01.3 Step 4.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
# INPUT RECONCILIATION (2026-07-23): the IBL edition read the active
# project's scenario document (`from utils import scenario` lazy
# proxy). In the intel engine the avenue catalog lives in the WORLD
# MODEL — the engine binds a provider callable at generation time.
# The lazy-per-access contract is preserved verbatim: an import-time
# snapshot would bake one project's avenues into every project's
# schema (IBL commit 8b5ba46).
AVENUE_ID_PROVIDER = None  # callable -> list[str]; bound by the engine


# Closed enum of valid avenue-of-approach ids — derived from the
# active project's avenue catalog so the writer's
# axis_role_assignments rows are validated against the canonical
# catalog. Hallucinated axis_ids fail schema validation before the
# runtime extractor ever sees them. The id set resolves LAZILY
# against the ACTIVE project's catalog at every access.
class _LazyAvenueEnum(list):
    """list subclass whose contents refresh from the active project's
    avenue catalog on every read. Display contexts with no active
    project (e.g. a schema catalog endpoint) see an empty enum;
    generation contexts always have the project bound, so validation
    stays closed against the right project's catalog."""

    def _refresh(self):
        try:
            ids = sorted(AVENUE_ID_PROVIDER()) if AVENUE_ID_PROVIDER else []
        except LookupError:
            ids = []
        super().clear()
        super().extend(ids)

    def __iter__(self):
        self._refresh()
        return super().__iter__()

    def __contains__(self, item):
        self._refresh()
        return super().__contains__(item)

    def __len__(self):
        self._refresh()
        return super().__len__()

    def __bool__(self):
        self._refresh()
        return super().__len__() > 0


_AVENUE_OF_APPROACH_IDS = _LazyAvenueEnum()

from ..common import (
    ECHELON_ENUM,
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    HEADER_SPATIAL_OVERLAY_BBOX,
    HEADER_SPATIAL_OVERLAY_MAP_ID,
    HEADER_SPATIAL_OVERLAY_URL,
    OBSTACLE_EFFECT_ENUM,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "SITEMP",
    "output_format": "pptx",
    "shape": "structured",
    # ------------------------------------------------------------------
    # Map render configuration — doctrinally defines exactly how the
    # SITEMP map should look. Every field is read by backend tool_render_map
    # and forwarded as a URL primitive to OperationsMapHeadless; the
    # frontend has zero SITEMP-specific branches. Per ATP 2-01.3 §6 / fig 6-3.
    # ------------------------------------------------------------------

    # Tileserver style id for the basemap raster. omt-sitemp strips
    # tertiary/residential/service/path roads + hides the doctrinal water
    # cross-hatch (water rendered as pale blue, not terrain obstacle —
    # SITEMP is threat COA, not terrain analysis) + light cream background
    # so the threat graphics dominate.
    "map_basemap": "default",

    # Per-product overlay gate. SITEMP = threat disposition over light
    # terrain context. Threat unit symbols come via the mil-units source,
    # not here. The terrain layers listed are explicit context anchors
    # (the AAs the threat is templated against, the urban areas the
    # threat is dug into, the intervisibility lines that shape their
    # fields of fire); MCOO-style mobility hatches are NOT included —
    # SITEMP is threat-on-terrain, not terrain-as-product.
    "map_overlay_kinds": [
        # Terrain context (lighter than MCOO)
        "avenue_of_approach", "key_terrain", "intervisibility_line",
        "urban_area",
        # Threat depiction — mil_unit is the primary SITEMP content
        # (templated/known threat formations as SIDC symbols per
        # ATP 2-01.3 Fig 6-3); without it the SITEMP shows EAs/BPs
        # but no units.
        "mil_unit",
        "threat_objective", "range_fan",
        "battle_position", "engagement_area",
        # Per-COA THREAT scheme of maneuver — the dominant visual
        # signal in the reference Threat COAs exhibit (IPSR03_B_16_
        # Exh_03D01). Each writer-emitted axis_role_assignments row
        # (see paragraph field below) emits an axis_of_advance
        # overlay with attrs.role + side=hostile so drawAxisOfAdvance
        # paints it in the doctrinal amplifier convention
        # (main_effort 'ME' amplifier, feint dummy-indicator overlay,
        # counter_attack dashed body + 'CATK' amplifier,
        # demonstration 'DEM' amplifier). Without this kind in the
        # allowed list the geo-agent /map/state endpoint strips the
        # writer's per-COA axes before they reach the frontend and
        # all COA maps look identical.
        "axis_of_advance",
        "phase_line", "boundary", "objective",
        # IPB Step 4 layers
        "named_area_of_interest", "decision_point",
    ],

    # OMT vector basemap layers visible on SITEMP. omt-sitemp raster
    # carries water + roads already — we only enable major-road label
    # vectors here so duplicate town labels don't appear (the desat
    # raster baselayer has them washed-out; the vector layer would be
    # solid on top → double labels). Minor/service/path road vector
    # layers stay off per Fig 6-3.
    "map_basemap_layer_visibility": [
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
    ],

    # Doctrinal-MCOO layers used on SITEMP: threat framework polygons,
    # NAI/TAI, boundary, phase lines. NO terrain hatches (MCOO carries
    # those); NO mobility corridors (MCOO concept); NO hydrology
    # casing (would dominate the threat graphics).
    "map_doctrinal_layer_visibility": [
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-pl-line",
        "mcoo-bp-fill", "mcoo-bp-line",
        "mcoo-ea-fill", "mcoo-ea-line", "mcoo-ea-line-hostile",
        "mcoo-obj-line",
        "mcoo-nai-line", "mcoo-tai-line",
        "mcoo-points-hit-target",
    ],

    # SITEMP per ATP 2-01.3 Fig 6-3 wants a clean topo-contour backdrop
    # so the analyst can read terrain context behind the threat graphics.
    # Contour overlay is zoom-tiered (100m index at z>=11, 50m at z>=12,
    # 20m at z>=13, 10m at z>=14) so it doesn't compete with the threat
    # framework at operational scale but adds detail at tactical zooms.
    "map_show_topographic_contours": True,

    # Individual threat unit symbols, not clustered — SITEMP doctrine
    # requires templating every threat unit two-levels-down so the
    # analyst can see each contact, not an echelon roll-up.
    "map_cluster_mil_units": False,

    # Compact AA labels along the chevron. SITEMP often has 3-5 AAs
    # crowding the same operational area; the full doctrinal label
    # would crowd them off the map.
    "map_compact_aa_labels": True,

    # Compact legend — SITEMP needs room for many threat unit symbols +
    # their identification tags. Packed legend leaves more map area.
    "map_compact_legend_labels": True,

    # Scenario-terrain AA source per ATP 2-01.3 §6 / fig 6-3. The SITEMP
    # depicts ONE specific threat COA — the threat's scheme of maneuver
    # is carried by the writer-emitted axis_role_assignments rows
    # (hostile axis_of_advance overlays painted by drawAxisOfAdvance
    # with doctrinal amplifier conventions). The avenue chevron is the
    # TERRAIN-analysis layer's depiction of the corridor — it belongs
    # on the MCOO. On the SITEMP it is redundant with the hostile
    # axis-of-advance arrow painted on top of the same polyline, AND
    # for COAs that use direction=reverse against a friendly-native
    # corridor the chevron paints with its fixture-canonical
    # arrowhead — directly contradicting the threat maneuver arrow
    # painted on top of it.
    #
    # SITEMP therefore pushes NO avenue chevrons at all; the hostile
    # axis-of-advance arrows from axis_role_assignments are the COA's
    # maneuver depiction.
    "map_avenue_of_approach_source": "none",

    # Friendly axes of advance from scenario.OPERATIONS.axes_of_approach.
    # SITEMP is the THREAT's plan, not the friendly plan; the friendly
    # maneuver scheme does NOT appear on the SITEMP. The writer-
    # emitted axis_role_assignments rows still push their hostile-
    # side per-COA threat maneuver arrows via
    # _extract_writer_axis_role_assignments — those are not affected
    # by this gate.
    "map_show_friendly_axis_of_advance": False,

    # Engagement-area perspective per ATP 2-01.3 §6 / FM 3-90 — the
    # SITEMP depicts the THREAT's fires plan, so only side=threat EAs
    # from scenario.TERRAIN.engagement_areas_catalog paint here. Blue
    # prospective EAs (US fires plan centered on threat formations)
    # belong on the friendly DSM / OPORD overlay, NOT on the SITEMP.
    # The renderer-side filter is in _push_scenario_terrain_to_geo_agent;
    # writer-emitted COA-specific additions (the `engagement_areas`
    # field below) are not affected — those are per-COA threat EAs the
    # writer authors for kill zones not in the canonical catalog.
    "map_engagement_area_perspective": "threat",

    # Friendly phase lines (PL ALPHA = friendly LD, PL BRAVO = Phase 2
    # objective from scenario.OPERATIONS.phase_lines) are FRIENDLY OPORD
    # control measures. They belong on the friendly DSM / OPORD overlay,
    # NOT on a threat-perspective SITEMP. Threat time-phase lines are
    # DERIVED at render time from axis_role_assignments + catalog avenue
    # polylines + doctrinal mechanized rate per ATP 2-01.3 Fig 6-3 (see
    # _derive_threat_time_phase_lines in handlers/intel_agent.py).
    "map_show_friendly_phase_lines": False,

    # Friendly division boundaries (1ID / 1AD / 1CAV vertical PL BDRY
    # lines from scenario.OPERATIONS.boundaries) are FRIENDLY C2 control
    # graphics. They belong on the friendly DSM / OPORD overlay, NOT on
    # a threat-perspective SITEMP.
    "map_show_friendly_boundaries": False,

    # ------------------------------------------------------------------
    # Product-config knobs — variability that belongs at the product
    # level (not scenario data). Read by the writer / renderer to drive
    # product-level decisions (cap on emissions, optional vs required
    # fields per COA type). Scenario-specific values (which named units
    # fill which role, which catalog ids each COA picks) come from the
    # upstream Threat COA Statement — these knobs are scenario-agnostic.
    #
    # Nested under `product_config` to match the schema-as-config-surface
    # convention established by the Threat COA Statement schema (whose
    # `product_config.coa_set` block carries the count / ranks / role
    # bindings). Guidance strings reference these knobs as
    # `product_config.axis_role_assignment_count_per_coa` /
    # `product_config.battle_position_required_for_defense_coas`.
    # ------------------------------------------------------------------
    "product_config": {
        # Soft cap on axis_role_assignments rows per COA. A typical
        # defensive COA emits 0-1 (counter-attack axis only); a typical
        # offensive COA emits 2-4 (one per division-sector); a deception
        # COA may emit 4-6 (real + spoofed axes, with disambiguation in
        # narrative_basis). 0 = unbounded.
        "axis_role_assignment_count_per_coa": 6,

        # When True, the battle_positions paragraph_field is REQUIRED for
        # any COA whose upstream Threat COA Statement coa_type is
        # "defense" or "hybrid"; OPTIONAL for "offense". When False,
        # battle_positions is always optional. Default True (BP belt is
        # a load-bearing doctrinal layer for defensive SITEMPs per
        # FM 1-02.2 Ch 5).
        "battle_position_required_for_defense_coas": True,
    },
    # Per-paragraph upstream dep filter — applies to EVERY paragraph_field
    # that doesn't override its own data_source_filter. Prevents the
    # SITEMP wave-1 prompts from blowing up to 200k+ chars by dumping the
    # entire upstream Threat Overlay (288 templated units + every
    # _provenance citation), the entire Threat COA Statement (header +
    # provenance + 4 COAs when each paragraph only needs ITS COA), and
    # the entire MCOO (header + every map_overlay).
    #
    # Keys here are what gets KEPT from each dep payload (everything else
    # is dropped before the writer sees it). Per-paragraph
    # data_source_filter still wins per the merge rule in
    # dag_executor._apply_field_filters.
    "default_data_source_filter": {
        # Threat Overlay carries: header, rows (288 templated units),
        # forward_bp_belt, collection_nais, map_overlays, threat_template_map,
        # _provenance. SITEMP paragraphs need rows (unit dispositions) +
        # forward_bp_belt (doctrinal BP belt) + collection_nais (analyst
        # NAIs). Header + map_overlays + threat_template_map + _provenance
        # are noise to the writer.
        "upstream:Threat Overlay": ["rows", "forward_bp_belt", "collection_nais"],
        # Threat COA Statement carries: header, coas (the 4 COAs),
        # map_overlays, _provenance. SITEMP paragraphs need the coas (and
        # specifically this COA's row); header + provenance is noise.
        "upstream:Threat COA Statement": ["coas"],
        # MCOO carries: header, map_overlays, mobility_classifications,
        # avenues_of_approach, key_terrain, obstacles,
        # combined_obstacle_overlay_map. SITEMP paragraphs that need
        # terrain (battle_positions, obstacles, named_areas_of_interest,
        # engagement_areas) only consume the terrain primitives, not the
        # header / map.
        "upstream:MCOO": ["mobility_classifications", "avenues_of_approach",
                          "key_terrain", "obstacles"],
    },
    "doctrine": {
        "purpose": (
            "Step-4 IPOE: graphical overlay depicting one threat COA "
            "(assumed threat dispositions adjusted for OE effects). "
            "Variants per ATP 2-01.3 §6 — threat in offense, threat "
            "in defense, irregular forces, hybrid. Two-levels-down "
            "resolution; the Step-3 DOCTEMP applies the same two-"
            "levels rule upstream."
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Snapshot per critical point (initial array / contact / branch / sequel / vulnerability).",
    },
    # Per ATP 2-01.3 Ch. 6 Step 4 the chain is Threat COA Statement →
    # SITEMP: the staff FIRST develops the Threat COA Statement
    # (most-likely + most-dangerous + any configured extras), THEN
    # templates threat units per each Threat COA Statement. SITEMP is
    # one-per-COA.
    "consumes_artifacts": ["MCOO", "Threat Overlay", "WEM", "TEM", "CCA", "Threat COA Statement", "DonovianDoctrine"],
    "header_fields": {
        "coa_id":             {"source": "session", "view": "header", "required": True,
                                 "render_label": "COA ID"},
        "coa_label":          {"source": "session", "view": "header", "required": True,
                                 "render_label": "COA Label"},
        "most_dangerous":     {"source": "session", "view": "header", "required": True,
                                 "render_label": "Most Dangerous"},
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "coa_type":           {"source": "session", "view": "header", "required": True,
                                 "render_label": "COA Type",
                                 "enum": ["offense", "defense", "irregular", "hybrid"]},
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal", "required": False,
                                 "render_label": "Threat COA Statement Reference",
                                 "depends_on": ["upstream:Threat COA Statement"],
                                 "guidance": "parent Threat COA Statement artifact_id when SITEMP is built off an enumerated COA set; optional for standalone SITEMP"},
        "mcoo_artifact_id":   {"source": "upstream:MCOO", "view": "internal", "required": False,
                                 "render_label": "MCOO Reference",
                                 "depends_on": ["upstream:MCOO"],
                                 "guidance": "MCOO base the SITEMP is drawn over; required in practice but soft-required here so SITEMP can render without a pre-existing MCOO"},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay", "view": "internal", "required": False,
                                          "render_label": "Threat Overlay Reference",
                                          "depends_on": ["upstream:Threat Overlay"],
                                          "guidance": "current threat overlay providing the unit positions adjusted into SITEMP"},
        "wem_artifact_id":    {"source": "upstream:WEM", "view": "internal", "required": False,
                                 "render_label": "WEM Reference",
                                 "depends_on": ["upstream:WEM"],
                                 "guidance": "WEM modifier for time-phase-line rate-of-march adjustments"},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Map embed fields — populated by handlers/intel_agent.py:_build_skeleton
        # from render_map() output. Hidden from the header k/v table; surface as
        # the <figure> map embed below the header.
        "spatial_overlay_url":    HEADER_SPATIAL_OVERLAY_URL,
        "spatial_overlay_map_id": HEADER_SPATIAL_OVERLAY_MAP_ID,
        "spatial_overlay_bbox":   HEADER_SPATIAL_OVERLAY_BBOX,
    },
    "paragraph_fields": [
        # BLUF — commander-readable bottom line, rendered FIRST so the
        # SITEMP leads with the analytical judgment before the map and the
        # templated-unit tables. Per ATP 2-01.3 §6 the SITEMP depicts ONE
        # threat COA; the BLUF states which COA this is, what the threat is
        # most likely to do, and the single fact the friendly commander
        # must act on — not a re-narration of the unit list below.
        {"name": "bluf",
         "view": "published",
         "shape": "string",
         "render_label": "Bottom Line Up Front (BLUF)",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "upstream:Threat COA Statement",
             "upstream:Threat Overlay",
         ],
         "data_source_filter": {
             "upstream:Threat COA Statement": ["coas"],
             "upstream:Threat Overlay": ["forward_bp_belt"],
         },
         "guidance": (
             "Commander-readable bottom line of THIS SITEMP, stated UP FRONT "
             "before the map and the templated-unit detail. Two to four "
             "sentences. Lead with the COA identity (header.coa_label / "
             "coa_type and whether it is the most-dangerous COA), then the "
             "decisive threat action this template depicts (the main effort's "
             "objective and the axis it runs), and close with the single "
             "indicator / decision point the friendly commander must watch "
             "to confirm or deny this COA.\n\n"
             "Derive from the upstream Threat COA Statement coa entry for "
             "THIS coa_id (mission_statement / scheme_of_maneuver / "
             "distinguishing_characteristics) — do NOT re-derive it from the "
             "templated_units rows. This is the commander's bottom-line "
             "judgment, not a staff product or a restatement of the unit "
             "table. Cite the upstream COA phrasing in _provenance."
         )},
        # SITEMP is map-centric — the situation overlay IS the product.
        # ATP 2-01.3 §6 / §B-21: templated threat units adjusted onto the
        # terrain in their doctrinal positions for the named threat COA.
        {"name": "situation_overlay_map",
         "view": "published",
         "shape": "map",
         "render_label": "Situation Overlay",
         "required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Live data — threat unit positions, fires/targets, control
             # measures, terrain context (key terrain / intervisibility /
             # urban), phased time-line. Direct cougaar.* so the render
             # fires in parallel with sibling writer LLM calls.
             "entities:units",
             "entities:marked",
             "map:state",
             "map:state",
             "anchors",
             "entities:civil",
             # Upstream products (consumes_artifacts).
             "upstream:MCOO", "upstream:Threat Overlay",
             "upstream:WEM", "upstream:TEM",
             "upstream:CCA", "upstream:Threat COA Statement",
         ]},
        {"name": "templated_units",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Templated Units",
         "required": True,
         # producer:"auto" — this paragraph is NOT writer-emitted. The DAG
         # executor's _run_field_node short-circuits the LLM call (mirrors the
         # shape:"map" skip pattern). The canonical producer is the SITEMP
         # post-merge enrichment in dag_executor.run_dag, which lifts every
         # row mechanically from cougaar.get_oob (one row per IDXEnemyOrderOfBattleReport
         # vertex). Reason: 200+ OOB units × 10 keys/row blew through the
         # 3k-token paragraph_field output budget, truncated mid-JSON, and the
         # parser dropped the whole array. The mechanical backfill produces
         # the same data deterministically with zero LLM cost.
         #
         # depends_on is retained so the DAG planner places this node downstream
         # of cougaar.get_oob (the data source) and the upstream artifacts that
         # SHARE the cougaar deps — keeps the wave ordering coherent.
         "producer": "auto",
         "depends_on": [
             "entities:units",
             "upstream:Threat Overlay",
             "upstream:MCOO",
             "upstream:Threat COA Statement",
         ],
         "guidance": (
             "Threat units adjusted onto the terrain. Produced mechanically "
             "from cougaar.get_oob by the SITEMP post-merge enrichment — one row "
             "per IDXEnemyOrderOfBattleReport vertex. Identity, echelon, and "
             "location_mgrs lift from the OOB row; the OOB.kbID becomes "
             "`_provenance` for identity + location_mgrs. Doctrinal-template "
             "fields (frontage_km / depth_km / TPME) are left blank — they "
             "require the upstream DOCTEMP basis the mechanical lift does not "
             "carry."
         ),
         "item_subfields": [
             # `id` is workpaper-only — used by shaping_operations[].unit_id
             # to link back to a templated unit row. The doctrinal "Unit ID"
             # column that appears on the published SITEMP is the unit
             # designation (e.g. "164 SSM BDE") which lives in `identity`.
             # Tag view:"internal" so the renderer hides the kg_id UUID from
             # the published table while keeping the field available for
             # cross-row linkage in the structured_data.
             {"name": "id", "render_label": "Internal Row ID",
              "view": "internal",
              "depends_on": ["entities:units"],
              "guidance": "internal row id used by shaping_operations[].unit_id to back-link; kg_id from the OOB data is acceptable. NOT rendered in the published SITEMP — the visible Unit ID column is the designation in `identity`"},
             {"name": "identity", "render_label": "Unit ID",
              "provenance_required": True,
              "depends_on": ["entities:units"],
              "guidance": (
                  "Doctrinal unit designator STRING — the short name written on the published "
                  "SITEMP per ATP 2-01.3 (e.g., '164 SSM BDE', '1st BTG/25th MRR', 'Tank Bn', "
                  "'1 MR Bn Coy 2'). This value MUST be the `enemy_unit` text from the "
                  "IDXEnemyOrderOfBattleReport vertex in the OOB payload (or the unit "
                  "designation from the OOB units[*].name / enemy_unit / unit_name — whichever "
                  "the payload carries). NEVER emit a single character, a backtick, the literal "
                  "string '`', a markdown code fence, JSON syntax, or any placeholder — those "
                  "are writer bugs. If the OOB payload has no designator for the row, emit the "
                  "echelon-derived nominal (e.g., 'Tank Bn Coy 3') rather than a character "
                  "token. Provenance: cite IDXEnemyOrderOfBattleReport.kbID=<uuid> for the "
                  "OOB vertex this row was lifted from."
              )},
             {"name": "echelon", "render_label": "Echelon",
              "enum": ECHELON_ENUM,
              "guidance": "doctrinal echelon ordinal — drives the two-levels-down rule"},
             # location_mgrs reads from cougaar/OOB row's location_mgrs field;
             # writer does not author MGRS coordinates. If the OOB row has
             # no location, leave the field empty — the row is presumably
             # a higher-echelon HQ whose location is implicit in its child
             # units. The LLM hallucinating MGRS strings ('35VME12345678')
             # is a regression class we explicitly forbid.
             {"name": "location_mgrs", "render_label": "Location (MGRS)",
              "source": "entity:location_mgrs",
              "provenance_required": True,
              "depends_on": ["entities:units"],
              "guidance": "Mechanical lookup from the OOB row's location_mgrs field via kg:location_mgrs. NEVER LLM-authored; the writer must not invent MGRS strings."},
             {"name": "frontage_km", "render_label": "Frontage (km)",
              "required": False,
              "guidance": "doctrinal frontage from threat template (DOCTEMP). SITEMP value is the OE-adjusted deviation; leave blank when not depicting"},
             {"name": "depth_km", "render_label": "Depth (km)",
              "required": False,
              "guidance": "doctrinal depth from threat template. Optional — only when the DOCTEMP basis carries it"},
             {"name": "task", "render_label": "Task",
              "required": False,
              "guidance": "subordinate task (e.g., 'fix friendly main effort'). Optional — SITEMP *may* show task organization"},
             {"name": "purpose", "render_label": "Purpose",
              "required": False,
              "guidance": "subordinate purpose. Optional — paired with task when shown"},
             {"name": "method", "render_label": "Method",
              "required": False,
              "guidance": "OPTIONAL and rarely populated per-unit — method is a COA-level construct, carried in enemy_commanders_intent"},
             {"name": "end_state", "render_label": "End State",
              "required": False,
              "guidance": "OPTIONAL and rarely populated per-unit — end-state is a COA-level construct, carried in enemy_commanders_intent"},
             {"name": "weapon_range_km", "render_label": "Weapon Range (km)",
              "required": False,
              "guidance": "max engagement range of unit's primary system; useful for EA/NAI placement"}]},
        {"name": "axis_role_assignments",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Threat Scheme of Maneuver — Axis Role Assignments",
         "required": False,
         "depends_on": [
             "upstream:MCOO",
             "upstream:Threat Overlay",
             "upstream:Threat COA Statement",
             "entities:avenue_of_approach",
         ],
         # Per-field filter override the schema-level default. This
         # paragraph only needs the AA catalog from MCOO and this coa's
         # narrative from Threat COA Statement. The full Threat-Overlay
         # OOB dump (200+ units × 10 kg-keys each = ~145k tokens) and
         # MCOO's key_terrain / obstacles / mobility_classifications
         # are unrelated — axis picks come from the catalog AAs alone.
         "data_source_filter": {
             "upstream:MCOO": ["avenues_of_approach"],
             "upstream:Threat Overlay": ["forward_bp_belt"],
             "upstream:Threat COA Statement": ["coas"],
         },
         "guidance": (
             "Per ATP 2-01.3 §6 / Fig 6-3: the per-COA threat scheme of "
             "maneuver rendered as role-styled arrows on the SITEMP map. Each "
             "row TAGS ONE doctrinal axis with the role THIS specific COA "
             "assigns it. The renderer paints role-styled arrows on top of "
             "the baseline terrain AA chevrons per FM 1-02.2 Table 5-9 (axis "
             "of advance) / Table 5-15 (feint/dummy indicator).\n\n"

             "PER-COA SOURCING — the row set is derived, not picked from a "
             "menu.\n"
             "For THIS COA (header.coa_id), read the upstream Threat COA "
             "Statement artifact (consumed via consumes_artifacts) and "
             "extract:\n"
             "  - coa.mission_statement / coa.scheme_of_maneuver — names the "
             "    decisive axis, supporting axes, deception axes (if any), "
             "    and the direction of movement along each.\n"
             "  - coa.functional_allocation — names the unit per role (action "
             "    force, enabling force(s), reserve, fires C2).\n"
             "  - coa.objectives — names the threat objective the COA seizes / "
             "    holds / denies; each axis terminates at one of these.\n"
             "For each axis the COA commits, emit ONE row that:\n"
             "  (1) picks the catalog axis_id from "
             "    scenario.TERRAIN.avenues_of_approach (see CATALOG section "
             "    below) that geographically matches the COA's narrative "
             "    axis description;\n"
             "  (2) tags it with the DOCTRINAL role the COA assigns "
             "    (main_effort / supporting / feint / demonstration / "
             "    counter_attack);\n"
             "  (3) sets direction = forward when the COA uses the axis in "
             "    its published polyline direction; reverse when the COA "
             "    uses the axis in the inverted direction (typically when a "
             "    friendly-native corridor is re-tasked as the threat's "
             "    south-bound axis, or a threat-native corridor is "
             "    re-tasked as a counter-attack-into-flank);\n"
             "  (4) names the committing formation in unit_designation, "
             "    cited from OOB in _provenance.\n\n"

             "DO NOT pattern-match on the COA label or mission_statement "
             "phrasing. Decision-tree templates that pre-bake per-pattern "
             "axis sets are answer-key contamination and are forbidden. The "
             "writer is the picker; the upstream Threat COA Statement is the "
             "source of truth.\n\n"

             "ROLE SEMANTICS per FM 1-02.2 + FM 3-90 (May 2023):\n"
             "  - main_effort — the decisive task force on the decisive "
             "    axis. Paint amplifier is 'ME' next to the unit "
             "    designation (per FM 1-02.2 unit amplifier fields); the "
             "    geometry is the same open broad-arrow as supporting "
             "    (NOT a thicker stroke and NOT a filled corridor; the "
             "    differentiator is the text amplifier, not a shape "
             "    variant — that was a prior painter bug).\n"
             "  - supporting — an axis that fixes / suppresses / screens "
             "    in support of the main effort. No special amplifier.\n"
             "  - feint — an attack that MAKES CONTACT to deceive the "
             "    friendly commander about the location of the main effort "
             "    (FM 3-90 May 2023). Geometry is the same as supporting; "
             "    the renderer overlays the FM 1-02.2 Table 5-15 / APP-6 "
             "    field AB dashed inverted-V dummy indicator centered above "
             "    the arrow midpoint. The indicator glyph is the doctrinal "
             "    differentiator.\n"
             "  - demonstration — a show of force that does NOT make "
             "    contact (FM 3-90 May 2023). Same geometry as supporting; "
             "    amplifier 'DEM'; tip stops short of the enemy frontage.\n"
             "  - counter_attack — a formed attack from a defensive "
             "    posture, typically by a reserve formation against the "
             "    flank of a friendly penetration into the forward BP belt. "
             "    Per FM 1-02.2 §5-6 always rendered DASHED regardless of "
             "    status (the dashed treatment is intrinsic to the control "
             "    measure, not a planned-status indicator). Amplifier "
             "    'CATK'.\n\n"

             "CARDINALITY — exactly one row per COA may carry "
             "role=main_effort (or zero if the COA emits no axes at all, "
             "e.g. a positional-defense COA with no counter-attack "
             "scheme). Other roles have no cross-axis cardinality cap. "
             "The product_config knob `axis_role_assignment_count_per_coa` "
             "(default 6) caps total rows per COA; a typical defensive "
             "COA emits 0-1 (counter-attack axis only); a typical "
             "offensive COA emits 2-4 (one per division-sector); a "
             "deception COA may emit 4-6 (real plus spoofed axes, with "
             "role disambiguation in the narrative_basis text). Emit "
             "ZERO rows when the COA's scheme of maneuver has no "
             "maneuvering threat units.\n\n"

             "CATALOG REFERENCE — axis_id values come from "
             "scenario.TERRAIN.avenues_of_approach[].id (the canonical AA "
             "catalog). The catalog publishes BOTH friendly-native corridors "
             "(used as friendly axes; reversed when re-tasked as threat "
             "south-offensive axes) AND threat-native corridors (used as "
             "threat counter-attack-from-depth axes). The writer NEVER "
             "invents a new axis_id — every emission resolves to a catalog "
             "entry."
         ),
         "item_subfields": [
             {"name": "axis_id", "render_label": "Axis ID",
              "enum": _AVENUE_OF_APPROACH_IDS,
              "depends_on": ["map:state"],
              "guidance": (
                  "MUST be one of the avenue ids published in "
                  "scenario.TERRAIN.avenues_of_approach (closed enum, "
                  "validated at schema-emit time). The catalog is the source "
                  "of truth — backend reads the polyline geometry from the "
                  "catalog using this id; the writer NEVER authors polylines "
                  "and NEVER invents a new id. A hallucinated id (e.g. "
                  "AA-THR-601MECHIFVBDE for COA-3's main effort) fails schema "
                  "validation and the row is rejected before render time. "
                  "If the COA's scheme of maneuver names a corridor not in "
                  "the catalog, that is a scenario-fixture gap to escalate, "
                  "not a writer-time invention."
              )},
             # NOTE: no `direction` subfield. The writer picks an axis_id
             # only; the runtime determines polyline orientation
             # automatically from the catalog avenue's `side` field — a
             # friendly-side corridor re-used by the threat is reversed
             # on push; a threat-side corridor is left as-is. The
             # writer must not make directional choices.
             {"name": "role", "render_label": "Role",
              "enum": ["main_effort", "supporting", "feint", "demonstration", "counter_attack"],
              "guidance": (
                  "Doctrinal tactical-mission task this axis carries for "
                  "THIS COA. Pick the value from the enum that matches the "
                  "role assigned to the unit moving along this axis in the "
                  "upstream Threat COA Statement's coa.functional_allocation "
                  "block and the COA's mission_statement / scheme of "
                  "maneuver.\n\n"
                  "Per-value selection rules:\n"
                  "  - main_effort — single axis carrying the unit named as "
                  "    functional_allocation.main_effort (or action_force "
                  "    when it is the COA's decisive maneuver element). "
                  "    Cardinality: exactly one per COA (or zero if the "
                  "    COA emits no axes).\n"
                  "  - supporting — axes whose unit appears in "
                  "    functional_allocation.supporting_effort / "
                  "    .reinforcing_effort / .enabling_force / .action_force "
                  "    (non-decisive), AND the role is conventional "
                  "    offensive maneuver (not deception).\n"
                  "  - feint — tactical-deception axis where the unit "
                  "    doctrinally MAKES CONTACT with the enemy for "
                  "    deceptive purposes (FM 3-90 May 2023). Sources: "
                  "    functional_allocation.deception with contact-making "
                  "    language ('fix', 'engage', 'limited-objective "
                  "    attack to draw reserves') OR mission_statement / "
                  "    phased_actions naming feint / fixing attack with "
                  "    deceptive intent.\n"
                  "  - demonstration — tactical-deception axis where the "
                  "    unit doctrinally AVOIDS CONTACT while presenting a "
                  "    credible threat (show of force) (FM 3-90 May "
                  "    2023). Sources: functional_allocation.deception "
                  "    with posture-only language ('show of force', "
                  "    'visible movement without commitment', "
                  "    'demonstrate intent without closing'). Doctrinal "
                  "    disambiguator with feint: contact = feint, no "
                  "    contact = demonstration.\n"
                  "  - counter_attack — reserve commitment from depth in "
                  "    response to a friendly action. Sources: "
                  "    functional_allocation.reserve with conditional "
                  "    commitment language ('counter-attack on order', "
                  "    'commit reserve when friendly penetrates to "
                  "    <depth>'). Originates at threat reserve locations "
                  "    and runs forward to the threatened sector."
              )},
             {"name": "unit_designation", "render_label": "Unit",
              "provenance_required": True,
              "depends_on": ["entities:units", "upstream:Threat COA Statement"],
              "guidance": (
                  "Threat formation moving along this axis for THIS COA. "
                  "Resolved from upstream Threat COA Statement "
                  "coa.functional_allocation by role, then to the OOB row by "
                  "designation. Cite both in _provenance (which "
                  "functional_allocation entry, which OOB row)."
              )},
             {"name": "narrative_basis", "render_label": "Narrative Basis",
              "guidance": (
                  "Brief reference to the upstream Threat COA Statement "
                  "phrasing that motivates this row (which sentence of "
                  "coa.mission_statement / coa.scheme_of_maneuver names this "
                  "axis and this unit's role on it). Genuine vs spoofed "
                  "annotation goes here when this COA carries "
                  "most_deceptive=True — state per-axis whether the row is a "
                  "real-action axis or a deception-action axis per the "
                  "upstream COA's signature_disambiguation."
              )},
         ]},
        {"name": "engagement_areas",
         "batch_group": "catalog_terrain_only",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Engagement Areas",
         "required": False,
         "depends_on": [
             "entities:engagement_area",
             "entities:avenue_of_approach",
             "upstream:Threat COA Statement",
         ],
         "guidance": (
             "Per ATP 3-21.18 / FM 3-90 + Table 9-2: kill zone where the "
             "threat commander intends to mass fires on attacking friendly "
             "forces.\n\n"

             "PICK FROM THE SEEDED CATALOG — NEVER INVENT EAs. The scenario "
             "publishes scenario.TERRAIN.engagement_areas_catalog with every "
             "kill zone the scenario defines (each entry carries id + name + "
             "polygon + linked_avenue_id + linked_unit + firing_formation + "
             "default_intent + linked_phase_line + rationale). Unlike "
             "scenario-canonical layers that are pre-pushed for every COA, "
             "engagement areas are PER-COA RELEVANT — different COAs employ "
             "different kill zones based on their scheme of maneuver. The "
             "writer's job is to pick the catalog ids THIS COA actually "
             "engages at (same per-COA filtering pattern as "
             "avenues_of_approach picks axis ids from "
             "scenario.TERRAIN.avenues_of_approach). The backend renders "
             "ONLY the catalog rows whose ids appear in the SITEMP's "
             "engagement_areas list for that COA.\n\n"

             "Selection rule — read the upstream Threat COA Statement "
             "coa.fires + coa.scheme_of_maneuver and pick the catalog EAs "
             "the COA's firing formations actually engage at. Defensive "
             "COAs typically engage at all catalog EAs along the threat's "
             "primary firing axes; offensive / deception COAs pick a "
             "narrower set anchored on the friendly target the COA is "
             "striking. NEVER author a new EA — if a needed kill zone is "
             "absent from the catalog, that is a scenario-catalog gap to "
             "escalate, NOT a writer-time fabrication. Inventing ids "
             "outside the catalog will fail schema validation."
         ),
         "item_subfields": [
             # The writer ONLY references existing
             # scenario.TERRAIN.engagement_areas_catalog ids — never
             # invents an EA, never emits coordinates. The catalog already
             # carries id + polygon + linked_avenue_id + linked_unit +
             # firing_formation + default_intent + linked_phase_line +
             # rationale for every kill zone the scenario defines; the
             # writer's job here is to PICK the catalog EAs relevant to
             # THIS COA's scheme of maneuver. If a kill zone is needed
             # for a COA but missing from the catalog, the fix is to add
             # it to scenario.TERRAIN.engagement_areas_catalog upstream —
             # not to ask the LLM to author geometry it cannot reliably
             # produce.
             {"name": "id", "render_label": "EA ID",
              "guidance": (
                  "MUST be an existing id from "
                  "scenario.TERRAIN.engagement_areas_catalog. The "
                  "catalog enumerates every kill zone the scenario "
                  "defines; pick the ids that THIS COA's scheme of "
                  "maneuver actually employs (defensive COAs typically "
                  "engage at every catalog EA along the threat's primary "
                  "axes; offensive / deception COAs typically engage at "
                  "the catalog EAs they're targeting). NEVER invent a "
                  "new id — if a needed EA isn't in the catalog, that's "
                  "a scenario-catalog gap to file upstream, not a "
                  "writer-time fabrication."
              )},
             {"name": "intent_override", "render_label": "COA Intent Override",
              "required": False,
              "guidance": (
                  "Optional per-COA override of the catalog's "
                  "default_intent (e.g., 'engage' vs 'deny' vs 'screen'). "
                  "Leave blank to inherit the catalog default. The "
                  "polygon, linked_avenue_id, linked_unit, "
                  "firing_formation, and linked_phase_line all come from "
                  "the catalog row keyed by id — the writer does NOT "
                  "re-emit them."
              )}]},
        {"name": "obstacles",
         "batch_group": "narrative_deps_free",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Obstacles (Reinforcing + Natural)",
         "required": False,
         "guidance": (
             "Tactical obstacles reinforcing the SITEMP scheme of maneuver. "
             "Natural obstacles inherited from MCOO need not be re-listed.\n\n"

             "PICK FROM THE SEEDED CATALOG — NEVER INVENT GEOMETRY. The "
             "scenario publishes scenario.TERRAIN.obstacles with every "
             "obstacle the scenario defines (each entry carries id + name + "
             "geometry + obstacle_type + linked_avenue_id). The writer "
             "references catalog ids only; the backend reads geometry "
             "from the catalog row at render time. Same pattern as "
             "engagement_areas / battle_positions / NAIs."
         ),
         "item_subfields": [
             # location subfield REMOVED. The LLM has no business emitting
             # MGRS coordinates. Obstacle reference by catalog id; backend
             # derives geometry.
             {"name": "id", "render_label": "Obstacle ID",
              "depends_on": ["map:state"],
              "guidance": (
                  "MUST be an existing id from "
                  "scenario.TERRAIN.obstacles. NEVER invent a new id or "
                  "emit raw MGRS — if a needed obstacle isn't in the "
                  "catalog, escalate the scenario-catalog gap."
              )},
             {"name": "tactical_effect", "render_label": "Tactical Effect",
              "enum": OBSTACLE_EFFECT_ENUM,
              "guidance": "tactical effect (disrupt / turn / fix / block)"}]},
        {"name": "battle_positions",
         "batch_group": "catalog_with_oob",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Battle Positions",
         # Required for defense / hybrid COAs (driven by product_config
         # knob battle_position_required_for_defense_coas) and the
         # upstream Threat COA Statement coa.coa_type. Optional for
         # offense COAs. The writer reads header.coa_type to determine
         # whether this field is required for THIS COA.
         "required": False,
         "depends_on": [
             "entities:battle_position",
             "upstream:Threat COA Statement",
             "entities:units",
         ],
         "guidance": (
             "Per ATP 2-01.3 §6-19 + FM 1-02.2 Ch 5 / Table 5-5: the threat's "
             "battle positions (BPs) — the prepared defensive positions where "
             "the threat's first-echelon BDEs / BNs intend to fight from. "
             "BPs are a doctrinal control measure (FM 1-02.2) rendered per "
             "their occupancy state.\n\n"

             "PICK FROM THE SEEDED CATALOG — NEVER INVENT POLYGONS. The "
             "scenario publishes a BP catalog "
             "(scenario.TERRAIN.battle_positions) with doctrinally-vetted "
             "centerlines + envelope polygons for each first-echelon BDE BP. "
             "Each row of this field selects ONE catalog entry by id; the "
             "backend reads geometry from the catalog so positions are "
             "always doctrinally correct.\n\n"

             "PER-COA OCCUPANCY RENDERING per FM 1-02.2 Table 5-5:\n"
             "  - OCCUPIED — the unit IS in the BP and IS fighting from it. "
             "    Standard occupied symbology (solid outline + filled "
             "    occupancy chevron). Use when this COA's scheme of "
             "    maneuver has the BP-owning unit in a defensive posture "
             "    AT this BP.\n"
             "  - PREPARED_UNOCCUPIED — the BP is prepared (obstacles "
             "    emplaced, fighting positions dug, range cards built) but "
             "    the unit has vacated. Solid outline + 'prepared but not "
             "    occupied' amplifier per FM 1-02.2 Table 5-5. Use when "
             "    the COA's scheme of maneuver has the BP-owning unit "
             "    ATTACKING OUT FROM the BP (e.g., a pre-emptive offensive "
             "    leaves the forward BPs prepared-but-vacated as the "
             "    defending DIVs cross the LD).\n"
             "  - PLANNED_NOT_PREPARED — the BP is in the doctrinal plan "
             "    but engineer effort has not yet completed (no obstacles, "
             "    no fighting positions yet). Dashed outline + 'planned "
             "    but not prepared' amplifier per FM 1-02.2 Table 5-5. "
             "    Use when a COA introduces a NEW BP not in the original "
             "    defense plan (e.g., a counter-attack-launch BP added "
             "    when reserves commit forward).\n\n"

             "PER-COA FILTERING — REQUIRED, ENFORCED. emit ONLY BPs whose "
             "occupying formation OR its parent division appears in THIS "
             "COA's upstream Threat COA Statement coa.functional_allocation. "
             "Step-by-step:\n"
             "  (a) Read the upstream coa.functional_allocation for this "
             "      coa_id. Extract the set of unit_ids it cites (e.g., "
             "      {U-DN-60MECHIFVDIV, U-DN-601MECHIFVBDE, U-DN-62MTZDINFDIV, "
             "      U-DN-604TANKBDE}).\n"
             "  (b) Expand each cited DIV to ALL its subordinate brigades "
             "      (60 MECH IFV DIV → 601, 602, 603 MECH IFV BDE; "
             "      62 MTZD INF DIV → 621, 622, 627 MTZD INF BDE; "
             "      66 MTZD INF DIV → 661, 662, 667 MTZD INF BDE). The "
             "      DIV's BPs are its subordinates' BPs.\n"
             "  (c) For each catalog BP, ask: is its occupying_unit_id "
             "      in the expanded set from step (b)? If YES, eligible. "
             "      If NO, OMIT — do NOT emit it for this COA.\n"
             "  (d) Example: COA-1 functional_allocation cites 60 MECH IFV "
             "      DIV + 62 MTZD INF DIV. Expanded set = {601, 602, 603, "
             "      621, 622, 627}. BPs of 66 MTZD INF DIV's brigades "
             "      (661, 662, 667) MUST NOT be emitted — 66 DIV is not "
             "      committed to THIS COA. Emitting them is a writer "
             "      error; the catalog publishes BPs for ALL Donovian "
             "      formations; the per-COA SUBSET is determined by "
             "      functional_allocation, not by writer discretion.\n\n"

             "DRIVE OCCUPANCY FROM UPSTREAM. For each emitted BP, read "
             "the upstream Threat COA Statement coa.scheme_of_maneuver / "
             "coa.statement for THIS coa_id and decide:\n"
             "  - Does the COA have the BP-owning unit OCCUPYING this BP? "
             "    → occupancy_override = 'occupied'.\n"
             "  - Does the COA have the BP-owning unit VACATING this BP "
             "    (attacking, withdrawing, counter-attacking from a "
             "    different BP)? → occupancy_override = "
             "    'prepared_unoccupied'.\n"
             "  - Is the BP NEW for THIS COA (added by the COA's reserve "
             "    commitment / counter-attack scheme)? → "
             "    occupancy_override = 'planned_not_prepared'.\n"
             "Cite the upstream sentence motivating each pick in "
             "_provenance.\n\n"

             "OCCUPANCY_OVERRIDE IS REQUIRED. Every emitted BP MUST carry "
             "an occupancy_override value — leaving it null defeats the "
             "per-COA render (every COA's SITEMP map looks identical). "
             "For pure defensive COAs where the entire main_defense_force "
             "holds, emit 'occupied' on every BP. For maneuver/hybrid "
             "COAs where the action force vacates forward BPs, emit "
             "'prepared_unoccupied' on those. The renderer relies on this "
             "field to vary FM 1-02.2 Table 5-5 symbology per COA.\n\n"

             "Per product_config.battle_position_required_for_defense_coas "
             "(default True): required for COAs whose header.coa_type is "
             "'defense' or 'hybrid'; optional for 'offense' and "
             "'irregular'."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "BP ID",
              "depends_on": ["map:state"],
              "guidance": (
                  "MUST be one of the ids in "
                  "scenario.TERRAIN.battle_positions. Backend reads "
                  "centerline + envelope polygon from the catalog using "
                  "this id — writer NEVER authors geometry."
              )},
             {"name": "occupancy_override", "render_label": "Occupancy",
              "enum": ["occupied", "prepared_unoccupied", "planned_not_prepared"],
              "required": False,
              "guidance": (
                  "Per-COA occupancy override of the catalog's "
                  "default_occupancy. Set per the COA's scheme of maneuver "
                  "(see parent guidance). Omit when the catalog default "
                  "is correct for this COA."
              )},
             {"name": "occupying_unit_id", "render_label": "Occupying Unit",
              "provenance_required": True,
              "depends_on": ["entities:units", "upstream:Threat COA Statement"],
              "guidance": (
                  "Threat formation that owns this BP for THIS COA. "
                  "Resolved from upstream Threat COA Statement "
                  "coa.functional_allocation by location, then to the OOB "
                  "row by designation. For prepared_unoccupied / "
                  "planned_not_prepared, this is the unit that WOULD "
                  "occupy the BP if not for the COA's scheme of maneuver "
                  "(vacating, withdrawing, not-yet-committed). Cite OOB "
                  "in _provenance."
              )},
         ]},
        {"name": "named_areas_of_interest",
         "batch_group": "catalog_terrain_only",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Named Areas of Interest (NAIs)",
         "required": True,
         "depends_on": [
             "entities:named_area_of_interest",
             "upstream:Threat COA Statement",
         ],
         "guidance": (
             "Per ATP 2-01.3 ¶6-20: small collection areas where the analyst "
             "EXPECTS to observe an indicator confirming or denying THIS "
             "COA. Each NAI ties 1:1 to an indicator (watching_for) that "
             "drives a PIR or DP.\n\n"

             "PICK FROM THE SEEDED CATALOG — NEVER INVENT POSITIONS. The "
             "scenario publishes a NAI catalog "
             "(scenario.TERRAIN.nai_catalog) with doctrinally-vetted "
             "positions covering every COA branch in the scenario. Each row "
             "of this field selects ONE catalog entry by id; the backend "
             "reads MGRS / polygon from the catalog so positions are "
             "always doctrinally correct.\n\n"

             "PER-COA PICKING — derive from upstream, not from a label.\n"
             "For THIS COA (header.coa_id), read the upstream Threat COA "
             "Statement artifact (consumed via consumes_artifacts) and "
             "extract:\n"
             "  - coa.distinguishing_characteristics — names the observable "
             "    signatures that disambiguate THIS COA from the others.\n"
             "  - coa.scheme_of_maneuver / coa.objectives — names the "
             "    geographic features (assembly areas, crossings, "
             "    objectives) the COA acts at.\n"
             "For each indicator the COA's distinguishing_characteristics "
             "names, pick the catalog NAI id whose location and "
             "watching_for default match the indicator. Cite the upstream "
             "phrasing motivating each pick in _provenance.\n\n"

             "Do NOT pattern-match on the COA label; do NOT pick a "
             "pre-prescribed per-COA subset. The catalog publishes NAIs "
             "covering ALL the COAs in the scenario; the per-COA SUBSET is "
             "derived per-COA from upstream Threat COA Statement.\n\n"

             "DISTINCT WATCHING_FOR — each NAI's watching_for MUST observe "
             "a DIFFERENT indicator from every other NAI in the same SITEMP. "
             "Two NAIs both watching '600 CBT ENG BDE in disruption zone' "
             "is a writer error — pick one NAI per indicator. If the COA's "
             "distinguishing_characteristics names 5 indicators, emit 5 "
             "NAIs each watching a distinct indicator; if 3, emit 3."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "NAI ID",
              "depends_on": ["map:state"],
              "guidance": (
                  "MUST be one of the ids in scenario.TERRAIN.nai_catalog. "
                  "Backend reads MGRS / polygon from the catalog using "
                  "this id — writer NEVER authors positions."
              )},
             {"name": "watching_for", "render_label": "Watching For",
              "provenance_required": True,
              "required": False,
              "guidance": (
                  "Optional per-COA override of the catalog's default "
                  "watching_for prose. Use when THIS COA's indicator is "
                  "narrower / wider / different from the catalog default "
                  "(catalog defaults are scenario-level; per-COA overrides "
                  "tighten the indicator to the COA's distinguishing "
                  "signatures). Cite the upstream PIR / DP / "
                  "distinguishing_characteristic in _provenance."
              )}]},
        {"name": "decision_points",
         "batch_group": "narrative_deps_free",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Decision Points (Threat)",
         "required": False,
         "guidance": (
             "THREAT-commander decision points, NOT friendly DPs. SITEMP is "
             "a threat product; every DP here is a decision the THREAT "
             "commander faces, observable to the friendly analyst via the "
             "indicator(s) that trigger it.\n\n"

             "Examples of valid THREAT DPs:\n"
             "  - Commit / withhold the counterattack force (trigger: "
             "    friendly penetration of the main defensive belt at "
             "    specified depth)\n"
             "  - Shift main effort between sectors (trigger: shift in "
             "    friendly main effort axis indicated by NAI hits)\n"
             "  - Begin maneuver-defense withdrawal from disruption zone "
             "    (trigger: friendly force reaches phase line X)\n"
             "  - Commit reserve to a sector (trigger: friendly bridging "
             "    capability identified at NAI-VALGA)\n\n"

             "DO NOT emit DPs that name friendly formations as the "
             "decider (1st Infantry Division, 1st Armored Division, V Corps "
             "Artillery, V Corps Combat Aviation Brigade, etc.) or describe "
             "friendly actions as consequences (commit 1st ID main effort, "
             "reinforce with corps assets, etc.) — those belong on the "
             "FRIENDLY DSM/DST, not the SITEMP. The DSM/DST reads the "
             "SITEMP's threat DPs and converts them into friendly response "
             "DPs at a separate doctrinal step.\n\n"

             "Not every SITEMP carries DPs — leave empty if this COA has no "
             "branch / sequel commitment criteria beyond the baseline COA "
             "scheme of maneuver."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "DP ID"},
             {"name": "trigger", "render_label": "Trigger",
              "provenance_required": True,
              "guidance": (
                  "Observable indicator (NAI sighting, threshold) that "
                  "fires THIS THREAT DP. The trigger MUST be something "
                  "observable to the THREAT commander or his recon: "
                  "friendly force position, friendly main-effort axis, "
                  "friendly engineer activity. Cite the upstream NAI id "
                  "from named_areas_of_interest."
              )},
             {"name": "consequence", "render_label": "Consequence",
              "guidance": (
                  "The THREAT action committed when the trigger fires. "
                  "Examples: 'commit 604 TANK BDE counterattack force', "
                  "'withdraw 602 MECH IFV BDE from disruption zone', "
                  "'shift 62 MTZD INF DIV main effort east'. NEVER a "
                  "friendly action (commit 1st ID, etc.) — those are "
                  "DSM/DST output."
              )}]},
        # NOTE: time_phase_lines is NO LONGER a writer-emitted field. The
        # writer (Gemma) has no spatial awareness and was emitting AO-
        # spanning horizontal lines at arbitrary latitudes regardless of
        # which axes were actually engaged. Threat time-phase lines per
        # ATP 2-01.3 Fig 6-3 are DERIVED at SITEMP render time from
        # axis_role_assignments + catalog avenue polylines + a doctrinal
        # mechanized rate (6 km/h × weather modulator). See
        # _derive_threat_time_phase_lines in handlers/intel_agent.py.
        # One phase line per H+N connects the leading-edge points across
        # all engaged movement axes — not one line per axis.
        {"name": "objectives",
         "batch_group": "catalog_terrain_only",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Objectives",
         "required": True,
         "depends_on": [
             "entities:threat_objective",
             "upstream:Threat COA Statement",
         ],
         "guidance": (
             "Per ATP 2-01.3 / ADP 3-0 / FM 3-90: terrain the threat intends "
             "to HOLD / DENY (defense COAs) or SEIZE (offense COAs).\n\n"

             "PICK FROM THE SEEDED CATALOG — NEVER INVENT POSITIONS. The "
             "scenario publishes a threat-objective catalog "
             "(scenario.TERRAIN.threat_objectives) with doctrinally-vetted "
             "positions for both defensive and offensive COAs. Each row of "
             "this field selects ONE catalog entry by id; the backend reads "
             "MGRS / polygon from the catalog so positions are always "
             "doctrinally correct.\n\n"

             "PER-COA PICKING — derive from upstream, not from a label.\n"
             "For THIS COA (header.coa_id), read the upstream Threat COA "
             "Statement artifact (consumed via consumes_artifacts) and "
             "extract coa.objectives.immediate + coa.objectives.subsequent. "
             "Each upstream objective entry names terrain and intent "
             "(hold / deny / seize / retain); project each onto the "
             "catalog by matching name / location to a catalog entry. Pick "
             "the catalog id; set intent_override only when the upstream "
             "intent differs from the catalog's default_intent. Cite the "
             "upstream phrasing in _provenance.\n\n"

             "Do NOT pattern-match on the COA label; do NOT pick a "
             "pre-prescribed per-COA subset. The catalog publishes both "
             "defensive (HOLD/DENY) and offensive (SEIZE) entries; the "
             "per-COA SUBSET is derived per-COA from upstream Threat COA "
             "Statement."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "OBJ ID",
              "depends_on": ["map:state"],
              "guidance": (
                  "MUST be one of the ids in "
                  "scenario.TERRAIN.threat_objectives. Backend reads MGRS / "
                  "polygon + default intent from the catalog using this "
                  "id — writer NEVER authors positions."
              )},
             {"name": "intent_override", "render_label": "Intent Override",
              "enum": ["hold", "deny", "seize", "retain"],
              "required": True,
              "guidance": (
                  "Per-COA threat intent for THIS objective. REQUIRED — "
                  "every emitted objective row MUST carry an intent_override "
                  "value (leaving it blank defeats the per-COA render; "
                  "every COA's SITEMP looks identical otherwise).\n\n"

                  "MAPPING by upstream coa_type:\n"
                  "  - defense (area/positional): intent_override = "
                  "    'hold' on every objective the COA defends\n"
                  "  - defense (maneuver): 'hold' on the main_defense "
                  "    objectives; 'deny' on disruption-zone objectives "
                  "    the action force trades for time\n"
                  "  - hybrid: 'hold' on battle-zone objectives; 'deny' "
                  "    on disruption-zone objectives\n"
                  "  - offense / spoiling attack: 'seize' on the "
                  "    objective the action_force takes; 'retain' on the "
                  "    objective the exploitation_force consolidates\n"
                  "  - deception: 'hold' on real-mass objectives; 'deny' "
                  "    or omit on the spoofed-axis objectives\n\n"

                  "Cite the upstream Threat COA Statement coa.objectives "
                  "entry + coa.scheme_of_maneuver in _provenance."
              )}]},
        {"name": "main_effort",
         "batch_group": "narrative_deps_free",
         "view": "published",
         "shape": "string",
         "render_label": "Main Effort",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "The THREAT main effort for THIS COA. MUST match the unit_id "
             "from the upstream Threat COA Statement "
             "coa.functional_allocation for THIS coa_id EXACTLY — same "
             "id, same echelon, no substitution.\n\n"

             "INCLUDE THE U-DN- ID VERBATIM in the prose. The published "
             "main_effort string MUST contain the FULL U-DN-<...> id from "
             "functional_allocation (e.g., 'U-DN-60MECHIFVDIV (60 MECH "
             "IFV DIV) conducts...'), not just the short designation. "
             "Analysts cross-link by U-DN- id to OOB; bare designations "
             "break the trace. The format is: '<U-DN-id> (<short "
             "designation>) <task verb> <purpose>'.\n\n"

             "STRICT ECHELON RULE: if functional_allocation.action_force = "
             "U-DN-60MECHIFVDIV, main_effort cites U-DN-60MECHIFVDIV "
             "(the DIV) — do NOT pattern-match to a subordinate brigade "
             "(U-DN-601MECHIFVBDE). Conversely, if functional_allocation "
             ".action_force = U-DN-601MECHIFVBDE, cite U-DN-601MECHIFVBDE "
             "(the BDE) — do NOT walk up to the parent. The published "
             "main_effort string MUST contain the EXACT unit id from "
             "functional_allocation. A renderer post-check verifies "
             "main_effort.contains(action_force_unit_id); mismatch is a "
             "writer error.\n\n"

             "Describe the task / purpose / method of the main effort per "
             "TC 7-100.2 doctrine for THIS coa_type:\n"
             "  - defense (area/positional): main_effort = main_defense_force\n"
             "  - defense (maneuver): main_effort = action_force "
             "    (the maneuver formation, NOT the counterattack force)\n"
             "  - hybrid: main_effort = action_force "
             "    (the maneuver formation in the disruption zone)\n"
             "  - offense / spoiling attack: main_effort = action_force "
             "    (the lead offensive formation)\n"
             "  - deception: main_effort = the GENUINE mass action_force, "
             "    NOT the deception_force (which is the spoof)\n\n"

             "Cite the upstream Threat COA Statement "
             "coa.functional_allocation entry in _provenance — the unit_id "
             "stated here MUST equal the unit_id at the canonical role-bin "
             "for this coa_type."
         )},
        {"name": "shaping_operations",
         "batch_group": "narrative_deps_free",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Shaping Operations",
         "required": False,
         "guidance": (
             "Threat shaping operations supporting the main effort. Each "
             "row names a SHAPING formation (NOT the main effort itself) "
             "and the task / purpose it performs per TC 7-100.2.\n\n"

             "UNIT ID FORMAT: use the U-DN-<NUMBER><TYPE> form from "
             "templated_units[].id (e.g., 'U-DN-167ADABDE', "
             "'U-DN-600CBTENGBDE', 'U-DN-362FABDE'). NEVER author "
             "designations without the U-DN- prefix — analyst-facing "
             "identifier hygiene matches the OOB.\n\n"

             "TASK VERB DOCTRINE (FM 3-90 / ATP 3-21.18):\n"
             "  - Field Artillery / MRL formations: 'suppress', 'destroy', "
             "    'neutralize' — targets are GROUND formations.\n"
             "  - Air Defense (ADA) formations: 'deny', 'defeat', 'protect' "
             "    — targets are AIR (CAB, ISR, deep strike); NEVER "
             "    'suppress' (that's an artillery task verb).\n"
             "  - Combat Engineer (CBT ENG) formations: 'block', 'fix', "
             "    'turn', 'disrupt' (the four tactical obstacle effects); "
             "    'breach' for offensive obstacle reduction.\n"
             "  - Reconnaissance (RECON) formations: 'screen', 'cover', "
             "    'observe', 'identify'.\n"
             "  - SIG / EW formations: 'jam', 'monitor', 'locate'.\n\n"

             "Optional — not every SITEMP separates shaping from main."
         ),
         "item_subfields": [
             {"name": "unit_id", "render_label": "Unit ID",
              "guidance": (
                  "U-DN-<NUMBER><TYPE> id from templated_units[].id of the "
                  "shaping formation. NEVER a bare designation like '167 "
                  "ADA BDE' — use 'U-DN-167ADABDE' so the renderer can "
                  "cross-link to OOB."
              )},
             {"name": "task", "render_label": "Task",
              "guidance": (
                  "Doctrinal task verb appropriate to the unit's "
                  "warfighting function (see parent guidance for the "
                  "verb-to-function mapping)."
              )},
             {"name": "purpose", "render_label": "Purpose"}]},
        {"name": "movement_and_maneuver",
         "batch_group": "doctrine_heavy",
         "view": "published",
         "shape": "dict",
         "render_label": "Movement & Maneuver (per Zone)",
         "required": False,
         "depends_on": [
             "document:DonovianDoctrine",
             "upstream:Threat COA Statement",
             "entities:units",
         ],
         # DonovianDoctrine.body is a single 67k-byte verbatim doctrine
         # prose blob. Drop it for this paragraph — the Threat COA
         # Statement coa.scheme_of_maneuver / functional_allocation
         # already encodes the doctrinal application THIS COA picked
         # from the doctrine. The system prompt also references the
         # zone-construct vocabulary in its product context. Re-shoving
         # the full doctrine in adds 17k tokens per call without
         # adding signal.
         "data_source_filter": {
             "document:DonovianDoctrine": [],
             "upstream:Threat COA Statement": ["coas"],
         },
         "guidance": (
             "Per-zone M&M descriptions using the threat-doctrine zone "
             "construct from the consumed doctrine artifact (see "
             "consumes_artifacts). The zone vocabulary (disruption / battle "
             "/ support, or the doctrine artifact's equivalent — TC 7-100.2 "
             "uses these names; ATP 7-100.1 uses security / "
             "combat-security / main-defensive / rear) comes from the "
             "doctrine artifact; the COA's per-zone unit assignment comes "
             "from the upstream Threat COA Statement coa.functional_allocation "
             "joined with OOB.\n\n"

             "COMPLETENESS RULE: EVERY non-null role-bin in the upstream "
             "Threat COA Statement coa.functional_allocation MUST appear in "
             "at least one zone. Specifically:\n"
             "  - action_force → typically disruption_zone OR battle_zone "
             "    depending on coa_type (offense → action force in disruption "
             "    pushing into battle; defense maneuver → action force in "
             "    disruption performing the maneuver defense; hybrid → "
             "    action force in disruption zone)\n"
             "  - disruption_force → disruption_zone\n"
             "  - main_defense_force → battle_zone\n"
             "  - counterattack_force → battle_zone (held in depth, "
             "    commits forward against penetrations)\n"
             "  - exploitation_force (offense only) → battle_zone or "
             "    support_zone (passing through action force)\n"
             "  - deception_force (deception COAs) → wherever the spoof "
             "    signature is being projected\n"
             "  - reserve → support_zone (uncommitted depth)\n"
             "  If a role-bin is unmentioned in any zone, the paragraph is "
             "  doctrinally incomplete.\n\n"

             "For each zone, describe (a) the doctrinal MISSION of the zone "
             "per the doctrine artifact's zone-construct section, (b) the "
             "formations THIS COA commits to that zone (cite by U-DN- id "
             "AND short designation; cite OOB rows and upstream Threat COA "
             "Statement allocation in _provenance), and (c) how THIS COA's "
             "scheme of maneuver shifts the zone's behavior from the "
             "doctrinal default (e.g., reserves committed forward into the "
             "battle zone for a counter-attack COA; disruption zone forces "
             "withdraw through battle zone for a maneuver-defense COA)."
         ),
         "subfields": ["disruption_zone", "battle_zone", "support_zone"]},
        {"name": "fires",
         "batch_group": "doctrine_heavy",
         "view": "published",
         "shape": "dict",
         "render_label": "Fires (per Zone)",
         "required": False,
         "depends_on": [
             "document:DonovianDoctrine",
             "upstream:Threat COA Statement",
             "upstream:WEM",
             "entities:units",
         ],
         # Same as movement_and_maneuver: drop the 67k DonovianDoctrine
         # prose; Threat COA Statement coa.fires + system prompt cover
         # the doctrinal grounding.
         "data_source_filter": {
             "document:DonovianDoctrine": [],
             "upstream:Threat COA Statement": ["coas"],
         },
         "guidance": (
             "Per-zone fires plan describing (a) the threat fires C2 "
             "architecture per the consumed doctrine artifact's "
             "fires-doctrine section (centralized vs decentralized, "
             "reconnaissance-fires-complex if applicable, integrated "
             "long-range fires at the corps echelon), (b) the fires assets "
             "THIS COA commits per zone (cite OOB rows + upstream Threat "
             "COA Statement allocation in _provenance), and (c) WEM "
             "modulation on observed-fire and CAS feasibility (cite WEM "
             "Cloud Cover / Visibility / Precipitation rows).\n\n"

             "UNIT CITATION REQUIRED: every zone narrative MUST name the "
             "FA / MRL / IFC formations providing fires for that zone by "
             "U-DN-<NUMBER><TYPE> id (e.g., 'U-DN-605FABDE', "
             "'U-DN-362FABDE', 'U-DN-6IFCARMY'). 'Divisional FA brigades' "
             "and 'corps-level IFC' as abstract references are WRONG — "
             "the analyst can't verify which formations are providing "
             "fires without the specific U-DN- ids. Pull the FA brigade "
             "ids from cougaar.get_oob (rows with category="
             "'precision_fire_systems' or echelon=FA BDE / MRL BDE).\n\n"

             "POSTURE — counter-preparation vs preparation vs on-call is "
             "COA-dependent and derives from upstream Threat COA Statement "
             "coa.fires; the schema does NOT prescribe which posture this "
             "COA takes. For a most-deceptive COA, fires posture may also "
             "be split — preparation fires on the spoofed axis (drawing "
             "friendly fires C2 attention to the wrong place) vs the real "
             "fires laydown elsewhere."
         ),
         "subfields": ["disruption_zone", "battle_zone", "support_zone"]},
        {"name": "sustainment",
         "batch_group": "doctrine_light",
         "view": "published",
         "shape": "dict",
         "render_label": "Sustainment",
         "required": False,
         "depends_on": [
             "document:DonovianDoctrine",
             "upstream:Threat COA Statement",
         ],
         # Drop the verbatim doctrine prose (Threat COA Statement coa's
         # sustainment narrative already encodes the doctrinal pick).
         "data_source_filter": {
             "document:DonovianDoctrine": [],
             "upstream:Threat COA Statement": ["coas"],
         },
         "guidance": (
             "THIS IS THE THREAT'S SUSTAINMENT. Describe the threat's "
             "logistics scheme for THIS COA (forward refuel, ammunition "
             "supply points, casualty evacuation, repair facilities, "
             "carried days of supply, advance caches if applicable). "
             "Ground the doctrinal vocabulary in the consumed doctrine "
             "artifact's sustainment-doctrine section (decentralized "
             "logistics, sustainment driving culmination, etc.). Cite the "
             "upstream Threat COA Statement coa.functional_allocation "
             "sustainment role in _provenance.\n\n"

             "UNIT CITATION REQUIRED: the task / purpose / method / "
             "end_state narrative MUST name the specific SUSTAINMENT "
             "formations providing logistics for THIS COA by exact OOB "
             "id (the `id` field on a unit row in cougaar.get_oob's "
             "units list). Generic 'decentralized logistics' is not "
             "enough — the analyst needs the formations.\n\n"

             "FORMAT: cite EVERY formation as `U-DN-<...> (<short "
             "designation>)`, e.g. 'U-DN-60SPTBDE (60 SPT BDE)'. The "
             "U-DN- prefix is REQUIRED — bare designations like "
             "'60 SPT BDE' or '60 MECH IFV DIV' break the analyst's "
             "OOB cross-link.\n\n"

             "PER-COA FILTERING REQUIRED. Cite ONLY the sustainment "
             "formations belonging to divisions in THIS COA's upstream "
             "Threat COA Statement coa.functional_allocation. If "
             "functional_allocation commits 60 MECH IFV DIV + 62 MTZD "
             "INF DIV, cite U-DN-60SPTBDE + U-DN-62SPTBDE only. NEVER "
             "mention 66 MTZD INF DIV's sustainment if 66 isn't in this "
             "COA's functional_allocation — including out-of-COA "
             "formations adds noise the analyst must filter.\n\n"

             "NEVER construct or shorten unit ids. Pick them VERBATIM "
             "from cougaar.get_oob units[*].id. Donovian sustainment "
             "formations are named 'NNN SPT BDE' or 'NNN SPT BN' in OOB "
             "with ids like U-DN-<NUMBER>SPTBDE — the actual ids in "
             "this scenario are 'U-DN-60SPTBDE' (the 60 MECH IFV DIV "
             "sustainment brigade), 'U-DN-62SPTBDE' (62 MTZD INF DIV), "
             "'U-DN-66SPTBDE' (66 MTZD INF DIV); per-brigade SPT BNs are "
             "'U-DN-601SPTBN', 'U-DN-602SPTBN', 'U-DN-621SPTBN', etc. "
             "DO NOT invent shortened forms like 'U-DN-60SPT' (missing "
             "BDE suffix), 'U-DN-60MECHIFVSUSTAINMENTBDE' (wrong "
             "convention), or any other compaction. If the OOB id you "
             "want isn't already visible in the upstream UPSTREAM "
             "DEPENDENCY PAYLOADS, fall back to plain English ('the 60 "
             "MECH IFV DIV's sustainment brigade') without inventing an "
             "id — the validator REJECTS the entire paragraph on any "
             "fabricated id.\n\n"

             "NEVER describe friendly sustainment — that belongs on "
             "friendly products. COA-level sustainment scheme in task / "
             "purpose / method / end-state form."
         ),
         "subfields": ["task", "purpose", "method", "end_state"]},
        {"name": "reconnaissance",
         "batch_group": "narrative_deps_free",
         "view": "published",
         "shape": "dict",
         "render_label": "Reconnaissance (per Zone)",
         "required": False,
         "guidance": (
             "THREAT reconnaissance / counterrecon by zone. Names which "
             "THREAT formations conduct recon in each zone, what they "
             "observe, and which friendly NAIs they cross.\n\n"

             "UNIT TYPE DOCTRINE — recon is performed by RECON formations, "
             "NOT by maneuver formations:\n"
             "  - 644 RECON BDE (U-DN-644RECONBDE) — corps-level "
             "    long-range recon, screening, target acquisition\n"
             "  - Divisional / brigade ORGANIC recon battalions if "
             "    present in the OOB\n"
             "  - SIG / EW formations (U-DN-676SIGBDE) — SIGINT, EW, "
             "    direction-finding (NOT visual recon)\n"
             "  - UAV / drone units if present in OOB\n\n"

             "NEVER assign reconnaissance tasks to:\n"
             "  - TANK brigades (counterattack / exploitation, not recon)\n"
             "  - MECH IFV brigades (maneuver formations, not recon — even "
             "    though their organic recon battalion might recon, the "
             "    BRIGADE itself does not)\n"
             "  - MTZ INF brigades (static defense, not recon)\n"
             "  - FA brigades (fires, not recon)\n\n"

             "UNIT CITATION: every formation in a zone narrative MUST be "
             "cited by U-DN-<NUMBER><TYPE> id (e.g., 'U-DN-644RECONBDE'), "
             "not bare designations like '644 RECON BDE'.\n\n"

             "Per-zone narrative shape: who, where, what they're looking "
             "for (tied to upstream NAI hits when applicable)."
         ),
         "subfields": ["disruption_zone", "battle_zone", "support_zone"]},
        {"name": "enemy_commanders_intent",
         "batch_group": "doctrine_light",
         "view": "published",
         "shape": "string",
         "render_label": "Enemy Commander's Intent",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "upstream:Threat COA Statement",
             "document:DonovianDoctrine",
         ],
         # Drop the verbatim doctrine prose. coa.statement (six-basic-
         # questions form) in Threat COA Statement already encodes the
         # doctrinally-grounded commander's intent for THIS coa.
         "data_source_filter": {
             "document:DonovianDoctrine": [],
             "upstream:Threat COA Statement": ["coas"],
         },
         "guidance": (
             "Threat commander's intent for THIS COA — purpose, key tasks, "
             "end state — at the COA level (not per-unit; per-unit task / "
             "purpose / method / end-state live in templated_units only "
             "when the COA's task organization explicitly carries them).\n\n"

             "SOURCE FROM UPSTREAM. The upstream Threat COA Statement "
             "(consumed via consumes_artifacts) for THIS coa_id carries "
             "coa.statement (the six-basic-questions form: who, what, "
             "where, when, how, why) and coa.objectives.desired_end_state. "
             "Synthesize a single intent paragraph that reflows those "
             "upstream fields into the doctrinal purpose / key-tasks / "
             "end-state structure — do NOT re-author the substance. "
             "Disagreement with the upstream substance is a writer bug.\n\n"

             "Ground the doctrinal vocabulary in the consumed doctrine "
             "artifact (e.g., for a positional-defense COA, intent reads "
             "in the doctrine artifact's area-defense vocabulary; for a "
             "deception COA, intent includes the false-read and "
             "commitment-trigger elements per the deception worksheet)."
         )},
        # Map IS the shape:"map" field above; runner auto-renders + auto-captions.
        # Redundant string field dropped — writer had no handle on the runner UUID.
    ],
    "subtleties": [
        "SITEMP ≠ threat template — SITEMP is the threat template "
        "(DOCTEMP) ADJUSTED for OE (terrain/weather/civil). Doctrinal "
        "frontages / depths come from the DOCTEMP / Step-3 threat "
        "template; SITEMP shows the OE-adjusted deviation.",

        "Multiple snapshots per COA allowed — initial array, contact, "
        "branch/sequel, vulnerability. Each snapshot is one SITEMP "
        "artifact.",

        "Two-levels-down rule: brigade SITEMP depicts CO / PLT; the "
        "same rule applies upstream to the Step-3 threat template.",

        "Variants per ATP 2-01.3 §6: threat in offense, threat in "
        "defense, irregular, hybrid. Header.coa_type drives which "
        "variant is rendered, and several paragraph_fields' required-"
        "ness depends on coa_type (e.g., battle_positions required "
        "for defense/hybrid via "
        "product_config.battle_position_required_for_defense_coas).",

        "Time phase lines based on standard rates of march modulated "
        "by WEM Precipitation row. For defense COAs where the threat "
        "doesn't advance, TPLs reflect FRIENDLY advance positions "
        "(where the lead friendly element will be at H+N); for "
        "offensive threat COAs, TPLs reflect THREAT advance "
        "positions.",

        "SITEMP *may* show possible task organization for subordinate "
        "units — so templated_units[*].task / purpose / method / "
        "end_state are OPTIONAL, not required. COA-level intent "
        "(purpose / key tasks / end state) lives in "
        "enemy_commanders_intent, sourced from upstream Threat COA "
        "Statement coa.statement + coa.objectives.desired_end_state.",

        "Every templated position cites threat model + threat overlay + "
        "MCOO; every TPL cites its rate basis + WEM modulation; every "
        "catalog-picker cites the upstream Threat COA Statement field "
        "motivating the pick.",

        "SITEMP carries unit positions; MCOO does NOT. The MCOO base "
        "shows terrain / AAs / key terrain / obstacles only; SITEMP "
        "overlays templated units, BPs, EAs, NAIs, OBJs, TPLs, and "
        "the per-COA threat scheme of maneuver on that base.",

        "Catalog-by-id is the canonical consumption pattern for "
        "every geometry primitive (NAI / threat objective / battle "
        "position / engagement area / axis). Writer NEVER authors "
        "polygons / centerlines for catalog primitives; backend "
        "reads geometry from scenario.TERRAIN by id.",

        "BP rendering per FM 1-02.2 Table 5-5 differs by occupancy — "
        "occupied (solid + chevron), prepared_unoccupied (solid + "
        "'prepared but not occupied' amplifier), planned_not_prepared "
        "(dashed + 'planned but not prepared' amplifier). Per-COA "
        "pick driven by upstream Threat COA Statement "
        "coa.scheme_of_maneuver — see the battle_positions "
        "paragraph_field guidance.",
    ],
    "hard_rules": [
        # ---- Provenance / grounding ----
        "Never invent templated positions without threat-model basis. "
        "templated_units[*].identity and location_mgrs cite OOB / the "
        "order-of-battle data / Threat Overlay in _provenance.",

        # ---- TPL grounding ----
        "TPL rate_basis MUST cite a rate-of-march source and the WEM "
        "Precipitation row that modulates it. The geometry MUST be "
        "computed at runtime from the AO bbox + LD coordinate read "
        "from cougaar.get_terrain() and scenario.TERRAIN; the schema "
        "does NOT prescribe AO bounds or LD position.",

        # ---- Header artifact citations ----
        "Cite MCOO + (when available) WEM artifact_ids in header. "
        "Both are soft-required so SITEMP can render with degraded "
        "inputs, but the analyst-level expectation is that MCOO is "
        "present.",

        # ---- Two-levels-down rule ----
        "Two-levels-down: templated_units MAY go two-levels-down "
        "(e.g., brigade SITEMP showing CO / PLT level rows), BUT for "
        "corps-scale SITEMP the practical echelon is BDE / BN — a "
        "corps SITEMP at CO/PLT level becomes unmanageable. "
        "preparing_unit_echelon at division/below: strict two-levels-"
        "down; at corps: BDE/BN is doctrinally acceptable.",

        # ---- Zone construct (principle, not answer key) ----
        "Use the threat-doctrine zone construct from the consumed "
        "doctrine artifact (see consumes_artifacts) for per-zone "
        "M&M / fires / reconnaissance descriptions. The zone "
        "vocabulary (disruption / battle / support, or the doctrine "
        "artifact's equivalent — TC 7-100.2 disruption/battle/"
        "support; ATP 7-100.1 security/combat-security/main-defensive"
        "/rear) comes from the doctrine artifact; the per-COA "
        "per-zone unit assignment comes from the upstream Threat COA "
        "Statement coa.functional_allocation joined with OOB. The "
        "schema does NOT name which units fill which zone — that is "
        "per-COA scenario data.",

        # ---- BP rendering rule (per FM 1-02.2 Table 5-5) ----
        "Battle position rendering across COAs follows FM 1-02.2 "
        "Table 5-5: occupied (solid outline + occupancy chevron); "
        "prepared_unoccupied (solid outline + 'prepared but not "
        "occupied' amplifier); planned_not_prepared (dashed outline "
        "+ 'planned but not prepared' amplifier). The writer sets "
        "the per-BP occupancy_override per the upstream Threat COA "
        "Statement coa.scheme_of_maneuver — does the COA have the "
        "BP-owning unit occupying, vacating, or has the BP not yet "
        "been built?",

        # ---- Catalog-by-id rule ----
        "Catalog-by-id is the canonical consumption pattern for "
        "scenario.TERRAIN data. NAI / threat objective / battle "
        "position / engagement area / axis pickers all read by id "
        "from scenario.TERRAIN.{nai_catalog, threat_objectives, "
        "battle_positions, engagement_areas_catalog, "
        "avenues_of_approach}. The writer NEVER authors geometry "
        "for any of these primitives; geometry comes from the "
        "catalog. Writer-emitted COA-specific additions (e.g., a "
        "new EA on a friendly assembly area for a deception COA) "
        "carry full polygon authorship and provenance per the "
        "per-paragraph_field guidance.",

        # ---- Provenance per-row ----
        PROVENANCE_HARD_RULE],
    "data_sources": [
        "Threat COA Statement parent (the per-COA picker output — "
        "drives every paragraph_field that varies per COA): "
        "list_project_docs(filter={type:'Threat COA Statement'}) "
        "then get_project_doc",
        "Threat dispositions (OPORD-derived threat-disposition rows "
        "+ Road-to-War vectors): get_oob(), list_targets()",
        "Threat doctrine (anchors per-zone descriptions, templated-"
        "unit role typing, zone construct vocabulary): "
        "get_project_doc(tag='DonovianDoctrine')",
        "MCOO base (terrain context the SITEMP overlays the threat "
        "scheme onto): list_project_docs(filter={type:'MCOO'})",
        "WEM modifiers (TPL rate-of-march modulation; fires CAS / "
        "observed-fire feasibility): "
        "list_project_docs(filter={type:'WEM'})",
        "Operations overlay control measures (AO / boundaries / "
        "phase lines / axes / NAIs / TAIs / EAs / OBJ — SITEMP "
        "base geometry; catalog-by-id pickers key off the overlay): "
        "get_spatial_overlay()",
        "Phased concept of operations (TPLs align to phase "
        "boundaries; per-COA TPL set may differ): get_phases()",
        "Scenario catalog pickers (NAI / threat objective / battle "
        "position / engagement area / avenue of approach — read by "
        "id from scenario.TERRAIN, not authored in this artifact): "
        "map:state",
        "Map render: render_map(layers=['terrain','units','spatial_overlay'], format='both')"],
    "post_emit_summary": "artifact_id, COA, key NAIs/DPs identified",
}
