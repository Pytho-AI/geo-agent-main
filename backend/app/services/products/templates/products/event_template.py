"""Event Template — ATP 2-01.3 Step 4 paras 6-64 to 6-71 + Figs 6-11/6-12/6-13.

5: "An event template is a guide for collection planning that depicts
the named areas of interest where activity, or lack of activity, will indicate
which course of action the enemy and/or adversary has adopted (JP 2-0). It is a
graphic overlay used during the COA analysis step of the MDMP to confirm or deny
threat COAs throughout war gaming."

6: the event template comprises three components — time-phase lines,
NAIs (with decision points), and the differentiating events that distinguish
between threat COAs. 7 the analyst compares NAIs/indicators across
the multiple SITEMP-derived COAs and identifies the differences that provide
the most reliable indications of COA adoption (Fig 6-11 construction; Fig 6-12
completed example).

The Event Template carries an associated Event Matrix 0 — a
cross-referenced description of indicators and activity expected at each NAI
(Fig 6-13). The matrix lives as a paragraph_field on this same product so the
graphic + matrix render together 3.

The Event Template + Matrix are the consolidation layer between the per-COA
SITEMPs (which carry standalone NAIs/DPs) and the downstream Decision Support
Template + Information Collection Matrix (paras 6-71 – 6-72).

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    HEADER_SPATIAL_OVERLAY_BBOX,
    HEADER_SPATIAL_OVERLAY_MAP_ID,
    HEADER_SPATIAL_OVERLAY_URL,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "Event Template",
    # Graphic-heavy product (Fig 6-12 / Fig 6-13). PPTX for the analyst-facing
    # graphic overlay (NAIs / DPs / time-phase lines drawn over the AO base);
    # DOCX for the matrix-form variant where the event matrix paragraph_field
    # carries the indicator × NAI × time-window cross-reference 3.
    "output_format": "pptx",
    "shape": "structured",
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines exactly how the
    # Event Template map should look. Per ATP 2-01.3 fig 6-12 / 6-13.
    # Frontend has zero TEM-specific branches.
    # ------------------------------------------------------------------

    "map_basemap": "default",

    # Per-product overlay gate. Event Template = NAI + TAI + DP + time-
    # phase line overlaid on AO. AAs and axes shown as context anchors
    # because NAIs are sited along the templated AAs.
    "map_overlay_kinds": [
        "named_area_of_interest", "targeted_area_of_interest",
        "decision_point", "phase_line",
        "avenue_of_approach", "axis_of_advance",  # for context
        "objective", "engagement_area",
        "boundary",
    ],

    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: urban + boundary framework, phase lines, NAI/TAI
    # (the core graphic), points-hit-target. No battle positions (TEM
    # is collection planning, not enemy disposition).
    "map_doctrinal_layer_visibility": [
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-pl-line",
        "mcoo-nai-line", "mcoo-tai-line",
        "mcoo-points-hit-target",
    ],

    "map_show_topographic_contours": False,

    # TEM rolls up NAI/DP planning across all SITEMP COAs; individual
    # threat units are NOT rendered (each SITEMP carries them per COA).
    # Cluster=False because we typically don't render mil_units at all
    # on TEM.
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": True,
    "map_compact_legend_labels": True,
    "doctrine": {
        "purpose": (
            "Step-4 IPOE consolidation product: graphic overlay that depicts "
            "the NAIs where activity (or lack of activity) confirms or denies "
            "which threat COA the enemy has adopted. Unifies the per-COA "
            "SITEMP NAIs / DPs into a single collection-planning guide. Used "
            "during MDMP COA analysis and during execution to trigger DST "
            "entries. Carries an associated event matrix (indicator × NAI × "
            "time window) — rendered together with the graphic." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "NAIs ordered by time-phase line (earliest expected activity "
            "first). Decision points anchor to the NAIs that trigger them."
        ),
    },
    # Builds off the per-COA SITEMPs (NAIs / DPs per COA) and the Threat COA Statement COA
    # enumeration (7 — compare COAs to find differentiating events).
    "consumes_artifacts": ["SITEMP", "Threat COA Statement", "DonovianDoctrine"],
    # SLA narrowing — Event Template consolidates NAI/DP/TPL across all
    # per-COA SITEMPs; the writer needs SITEMP NAIs + Threat COA Statement
    # coas[] + doctrinal indicators only.
    "default_data_source_filter": {
        "upstream:SITEMP":              ["coas", "named_areas_of_interest",
                                          "decision_points", "time_phase_lines",
                                          "header"],
        "upstream:Threat COA Statement":["coas", "header"],
        "document:DonovianDoctrine":    ["sections"],
    },
    "header_fields": {
        # Event Template is a MULTI-PHASE product per IDX 26 SOP — the
        # event_matrix carries one row per (phase × COA × NAI) tuple, so
        # the header doesn't pin to a single phase. Optional + defaulted
        # to the OPORD phase span.
        "phase":              {**HEADER_PHASE, "required": False,
                                "default": "Phase I–IV (full OPORD span)",
                                "guidance": (
                                    "Event Template covers ALL phases by "
                                    "doctrine — per-row phase tagging lives "
                                    "in event_matrix.phase. Header default "
                                    "names the span; analyst can override "
                                    "to pin to a specific phase window."
                                )},
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        # Same logic: ET is built to differentiate between ALL ECOAs per
        # ATP 2-01.3 (7) construction step 7. Optional + defaulted to the
        # full COA set.
        "threat_coa":         {"source": "session", "view": "header",
                                "required": False,
                                "default": "COA-1 / COA-2 / COA-3 (all ECOAs — see Threat COA Statement reference)",
                                "render_label": "Threat COAs Differentiated",
                                "depends_on": ["upstream:Threat COA Statement"],
                                "guidance": (
                                    "Event Template differentiates between "
                                    "ALL ECOAs per ATP 2-01.3 (7) — per-row "
                                    "COA tagging lives in event_matrix."
                                    "coa_confirmed. Header default names "
                                    "the full set; analyst can override to "
                                    "scope to a specific COA."
                                )},
        "sitemp_artifact_ids": {"source": "upstream:SITEMP", "view": "internal",
                                  "required": False,
                                  "render_label": "SITEMP References",
                                  "depends_on": ["upstream:SITEMP"],
                                  "guidance": (
                                      "Comma-separated SITEMP artifact_ids "
                                      "whose NAIs feed this event template per "
                                      "construction step 'evaluate "
                                      "each COA to identify associated NAIs'."
                                  )},
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal",
                                "required": False,
                                "render_label": "Threat COA Statement Reference",
                                "depends_on": ["upstream:Threat COA Statement"],
                                "guidance": (
                                    "Parent Threat COA Statement artifact whose COA set this "
                                    "event template differentiates between "
                                    "."
                                )},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Map embed fields — Event Template is map-bearing. Populated by
        # handlers/intel_agent.py:_build_skeleton from render_map() output.
        # Hidden from the header k/v table; rendered as <figure> map embed
        # below the header per the SITEMP / MCOO pattern.
        "spatial_overlay_url":    HEADER_SPATIAL_OVERLAY_URL,
        "spatial_overlay_map_id": HEADER_SPATIAL_OVERLAY_MAP_ID,
        "spatial_overlay_bbox":   HEADER_SPATIAL_OVERLAY_BBOX,
    },
    "paragraph_fields": [
        # ATP 2-01.3 Step 4: event template is the graphic plot of NAIs +
        # TAIs + decision points overlaid on terrain. Map IS the centerpiece.
        {"name": "event_template_map",
         "view": "published",
         "shape": "map",
         "render_label": "Event Template",
         "required": True,
         "provenance_required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Live data — NAIs/TAIs/DPs/phase lines/boundaries/axes
             # from OPORD-derived overlay; phased timeline for
             # event-cycle anchoring.
             "map:state",
             "anchors",
             # Upstream products (consumes_artifacts).
             "upstream:SITEMP", "upstream:Threat COA Statement",
         ]},
        {"name": "named_areas_of_interest",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Named Areas of Interest",
         "required": True,
         "provenance_required": True,
         "depends_on": ["document:DonovianDoctrine", "upstream:SITEMP", "upstream:Threat COA Statement"],
         "guidance": (
             "Consolidated NAI set6 across all per-COA SITEMPs. "
             "Each NAI = an area where activity (or lack of activity) "
             "confirms / denies the threat's adoption of a particular "
             "COA5. NAIs may be in the AO or in the AOI (NAIs in "
             "AOI may be in another commander's AO and require coordination"
             "6). NAI selection driven by focusing on differences "
             "between COAs that provide the most reliable indications of "
             "COA adoption.\n\n"
             "PICK FROM THE SEEDED CATALOG — NEVER INVENT POSITIONS. The "
             "scenario publishes a NAI catalog (scenario.TERRAIN.nai_catalog) "
             "with doctrinally-vetted positions covering every COA branch. "
             "Each row selects ONE catalog entry by id; the backend reads "
             "the MGRS / polygon from the catalog so positions are always "
             "doctrinally correct. Writer-invented MGRS coords were "
             "producing NAIs in the wrong places (NAI-PIKASILLA at extreme "
             "west edge etc.).\n\n"
             "CATALOG (use id verbatim, NEVER invent a new id):\n"
             "  Static-defense baseline (any COA may reference):\n"
             "    NAI-VALGA, NAI-KOPU, NAI-PIKASILLA, NAI-RONGU,\n"
             "    NAI-OSULA, NAI-VORU, NAI-TARTU, NAI-ADA-FWD\n"
             "  COA-2 (Counter-Attack from Depth) lateral-reserve NAIs:\n"
             "    NAI-KOPU-RONGU-LATERAL, NAI-RONGU-OSULA-LATERAL,\n"
             "    NAI-TARTU-DEPLOY\n"
             "  COA-3 (Pre-emptive Offensive South) target / staging NAIs:\n"
             "    NAI-CIMZA-ASSY, NAI-SMILTENE-ASSY, NAI-GRUNDZALE-ASSY,\n"
             "    NAI-LD-CROSSING-W, NAI-LD-CROSSING-C, NAI-LD-CROSSING-E\n\n"
             "EVENT TEMPLATE consolidates ACROSS COAs — emit the UNION of "
             "NAIs referenced by the per-COA SITEMPs. The optional "
             "watching_for override is per-(event template) refinement of "
             "the catalog default — use it when the consolidation reframes "
             "the indicator (e.g., NAI-VALGA's COA-1 indicator is "
             "engineer reinforcement, but the consolidated ET watching_for "
             "may be 'engineer reinforcement (COA-1) OR bridging equipment "
             "forward (COA-3) — observe to differentiate').\n\n"
             "watching_for overrides MUST reflect the signature OPFOR "
             "behaviors in DonovianDoctrine section 8: forward AT battery "
             "emplacement, TANK BDE forward movement = counter-attack commit "
             "window 4-6h after breach, 62 CBT AVN BDE rotary deep attack = "
             "most-dangerous COA execution indicator, 6 IFC ARMY counter-"
             "preparation fires = pre-emptive disruption COA, 600 CBT ENG "
             "BDE obstacle thickening at the Valga crossing site."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "NAI ID",
              "enum": [
                  "NAI-VALGA", "NAI-KOPU", "NAI-PIKASILLA", "NAI-RONGU",
                  "NAI-OSULA", "NAI-VORU", "NAI-TARTU", "NAI-ADA-FWD",
                  "NAI-KOPU-RONGU-LATERAL", "NAI-RONGU-OSULA-LATERAL",
                  "NAI-TARTU-DEPLOY",
                  "NAI-CIMZA-ASSY", "NAI-SMILTENE-ASSY", "NAI-GRUNDZALE-ASSY",
                  "NAI-LD-CROSSING-W", "NAI-LD-CROSSING-C", "NAI-LD-CROSSING-E",
              ],
              "guidance": "MUST be one of the catalog ids above. Backend reads MGRS / polygon from scenario.TERRAIN.nai_catalog using this id — writer NEVER emits positions."},
             {"name": "watching_for", "render_label": "Watching For",
              "provenance_required": True,
              "required": False,
              "guidance": (
                 "Optional Event-Template-level override of the catalog's "
                 "default watching_for prose. Use when the consolidated ET "
                 "indicator reframes the per-COA SITEMP indicators "
                 "(e.g., 'engineer reinforcement (COA-1) OR bridging "
                 "equipment forward (COA-3) — observe to differentiate'). "
                 "Cite the SITEMP / Threat COA Statement / OPORD basis in _provenance. "
                 "Doctrinal indicators come from ATP 2-01.3 Tables 6-1 / "
                 "6-2 where applicable."
              )},
         ]},
        {"name": "time_phase_lines",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Time Phase Lines",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Linear geographic areas depicting when threat activity may "
             "occur6. Used to establish expected times in the "
             "event matrix 0."
         ),
         "item_subfields": [
             {"name": "label", "render_label": "Label",
              "guidance": "H-hour-relative label, e.g. 'H-48', 'H-24', 'H+0', 'H+12'."},
             {"name": "geometry", "render_label": "Geometry",
              "provenance_required": True,
              "guidance": "Phase-line geometry (MGRS line or GeoJSON)."},
             {"name": "description", "render_label": "Description",
              "guidance": (
                 "What threat element is expected at this TPL "
                 "(e.g., 'lead element 1/11 MRB closure on PL RED')."
              )},
         ]},
        {"name": "decision_points",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Decision Points",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Friendly commander decision points6: "
             "'a point in space and the latest time when the commander or "
             "staff anticipates making a key decision concerning a specific "
             "course of action'. Each DP links to the NAI(s) whose "
             "observation triggers it.\n\n"
             "PICK FROM THE SEEDED CATALOG — NEVER INVENT POSITIONS / "
             "FRIENDLY DECISIONS. The scenario publishes a DP catalog "
             "(scenario.TERRAIN.dp_catalog) with the OPORD-implied friendly "
             "commander decision points (DP-1 through DP-5), each carrying "
             "the canonical friendly_decision text, owning_commander, "
             "phase, latest-time (ltiov), triggering_indicator, linked NAIs, "
             "and options. Each row selects ONE catalog entry by id; the "
             "backend reads the canonical fields from the catalog and "
             "synthesizes the DP point overlay from the catalog anchor. "
             "Writer-invented DPs were producing enemy-decision text in "
             "the friendly-DP column ('Commit 604 TANK BDE to "
             "counterattack'), which is doctrinally wrong — DPs are "
             "FRIENDLY-commander decisions triggered BY enemy activity.\n\n"
             "CATALOG (use id verbatim, NEVER invent a new id):\n"
             "  DP-1 — Commit 1st ID main effort to Valga penetration\n"
             "  DP-2 — Commit 1st AD supporting attack on Rongu axis\n"
             "  DP-3 — Commit Corps reserve vs Donovian armored "
             "counter-attack\n"
             "  DP-4 — Branch: envelop vs frontal penetration of "
             "defensive band\n"
             "  DP-5 — Transition to consolidation and stabilization\n\n"
             "context_override is OPTIONAL — use when the consolidated "
             "Event Template refines the catalog's friendly_decision / "
             "triggering_indicator prose for this specific event-template "
             "instance (e.g., scoping a multi-COA decision to a single "
             "branch). Leave blank to inherit the catalog defaults."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "DP ID",
              "enum": ["DP-1", "DP-2", "DP-3", "DP-4", "DP-5"],
              "guidance": (
                  "MUST be one of the catalog ids above. Backend reads "
                  "friendly_decision / owning_commander / phase / ltiov / "
                  "triggering_indicator / linked_nais / options + anchor "
                  "MGRS from scenario.TERRAIN.dp_catalog using this id — "
                  "writer NEVER emits coordinates or decision text."
              )},
             {"name": "context_override", "render_label": "Context Override",
              "provenance_required": True,
              "required": False,
              "guidance": (
                  "Optional Event-Template-level override / refinement of "
                  "the catalog's friendly_decision + triggering_indicator "
                  "prose. Use when the consolidated ET reframes the DP "
                  "(e.g., 'scoped to COA-2 branch — DP-3 fires only if "
                  "NAI-KOPU observes 604 TANK BDE displacement before "
                  "D+5'). Cite the SITEMP / Threat COA Statement / OPORD basis in "
                  "_provenance. Leave blank to inherit the catalog "
                  "defaults — backend will surface the catalog values."
              )},
         ]},
        {"name": "event_matrix",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Event Matrix",
         "required": True,
         "provenance_required": True,
         "group_by": "phase",
         "order_by": [{"field": "phase", "direction": "asc"},
                      {"field": "coa_confirmed", "direction": "asc"},
                      {"field": "nai_id", "direction": "asc"}],
         "guidance": (
             "FULL PHASE × Threat COA Statement × NAI BREAKDOWN — emit ONE row PER (phase × "
             "COA × NAI) tuple where the NAI has a meaningful indicator. "
             "Do NOT collapse to one row per NAI; each NAI fires DIFFERENT "
             "indicators in different phases against different Threat COA Statement branches "
             "and each combination is a separate matrix row.\n"
             "\n"
             "For IDX 26 the grid is 4 phases × 3 ECOAs × 8 NAIs = 96 max "
             "cells. The realistic populated set is ~24-40 rows (most NAIs "
             "are only active in 1-2 phases; not every NAI distinguishes "
             "every COA). Build the grid by walking phase → COA → NAI in "
             "that order:\n"
             "  - For each phase in the OPORD phase concept (Phase I "
             "Penetration / Phase II Advance to Contact / Phase III "
             "Decisive Operations / Phase IV Stabilization):\n"
             "    - For each Threat COA Statement in the upstream Threat COA Statement artifact's coas list "
             "(COA-1 most-likely / COA-2 intermediate / COA-3 most-dangerous):\n"
             "      - For each NAI in the scenario fixture NAI catalog:\n"
             "        - If the NAI has a meaningful threat-indicator for "
             "this (phase, COA) combination, emit a row\n"
             "        - The indicator phrasing changes per COA — under "
             "COA-1 (defensive) NAI-VALGA shows engineer reinforcement; "
             "under COA-3 (counterattack) the SAME NAI shows bridging "
             "equipment forward + ADA repositioning forward of PL ALPHA\n"
             "        - Use `coa_confirmed` to tag which COA the indicator "
             "supports: `MLCOA` (confirms), `!MLCOA` (denies/inverts), "
             "or the explicit COA ID like 'COA-1' / 'COA-2' / 'COA-3'\n"
             "\n"
             "ATP 2-01.3 (7) construction algorithm: (1) start from SITEMP, "
             "(2) evaluate each COA to identify associated NAIs, (3) find "
             "where events DIFFERENTIATE between COAs, (4) determine "
             "confirm/deny indicators per NAI per COA, (5) determine "
             "specific hour, (6) compare NAIs across COAs, (7) focus on "
             "differences providing the most reliable disambiguation. The "
             "per-(phase × COA × NAI) row structure is how that algorithm "
             "lands as data."
         ),
         "item_subfields": [
             {"name": "phase", "render_label": "Phase",
              "enum": ["Phase I (Penetration)",
                       "Phase II (Advance to Contact)",
                       "Phase III (Decisive Operations)",
                       "Phase IV (Stabilization)"],
              "guidance": (
                 "OPORD phase the indicator is expected to manifest in. "
                 "Drives group_by on the rendered matrix — rows section "
                 "into per-phase sub-tables. Phase concept comes from "
                 "the OPORD body excerpt in the scenario fixture (§3.b)."
              )},
             {"name": "nai_id", "render_label": "NAI",
              "guidance": "NAI ID from the scenario fixture NAI catalog (NAI-VALGA, NAI-KOPU, NAI-PIKASILLA, NAI-RONGU, NAI-OSULA, NAI-VORU, NAI-TARTU, NAI-ADA-FWD). NEVER invent a NAI ID."},
             {"name": "coa_confirmed", "render_label": "COA",
              "depends_on": ["upstream:Threat COA Statement"],
              "guidance": (
                 "Which Threat COA Statement branch this row supports. Use the COA ID from "
                 "the upstream Threat COA Statement artifact (COA-1 / COA-2 / COA-3) — or "
                 "the doctrinal alias `MLCOA` for COA-1, `MDCOA` for the "
                 "COA tagged most_dangerous=True. Prefix `!` to flag the "
                 "indicator INVERTS / DENIES the COA (absence of expected "
                 "activity = denial). Each row is ONE COA — emit separate "
                 "rows for the same NAI under different COAs."
              )},
             {"name": "indicator", "render_label": "Indicator",
              "provenance_required": True,
              "guidance": (
                 "Restated indicator per ATP 2-01.3 (0) 'examine events "
                 "associated with each NAI and restate the events as "
                 "indicators'. Phrasing CHANGES per COA — the same NAI's "
                 "indicator under COA-1 differs from the indicator under "
                 "COA-3 because each COA predicts different enemy activity "
                 "at that NAI. Use Tables 6-1 / 6-2 doctrinal phrasing "
                 "where applicable; otherwise specific scenario unit IDs "
                 "+ MGRS + observable signature (thermal / radar / comms / "
                 "vehicle count)."
              )},
             {"name": "no_later_than", "render_label": "NLT",
              "guidance": (
                 "Latest time the indicator is expected (H-hour relative "
                 "or DTG). Tie to the phase windows: Phase I = D-Day..D+3, "
                 "Phase II = D+4..D+10, Phase III = D+11..D+20, Phase IV "
                 "= D+21+. NLT typically sits at the end of the phase."
              )},
             {"name": "no_earlier_than", "render_label": "NET",
              "guidance": (
                 "Earliest time the indicator is expected (H-hour relative "
                 "or DTG). NET sits at the start of the phase, or earlier "
                 "for indicators that warm up before the phase opens."
              )},
             {"name": "associated_dp", "render_label": "DP",
              "guidance": (
                 "DP ID(s) from the scenario fixture DP catalog (DP-1 "
                 "through DP-5) — the FRIENDLY commander decision point(s) "
                 "this indicator informs. Mapping for IDX 26: NAI-VALGA → "
                 "DP-1, NAI-PIKASILLA → DP-1, NAI-ADA-FWD → DP-1/DP-4, "
                 "NAI-RONGU → DP-2, NAI-VORU → DP-2, NAI-KOPU → DP-3, "
                 "NAI-OSULA → DP-3, NAI-TARTU → DP-4/DP-5. Comma-"
                 "separated string when multiple."
              )},
         ]},
        # Map IS the `event_template_map` shape:"map" field above; the
        # exporter auto-renders + auto-captions it from map_overlays[].
        # Redundant string field dropped — writer had no handle on the
        # runner-assigned map UUID.
    ],
    "subtleties": [
        "4: event templates are 'normally developed before COA analysis, refined during COA analysis, and further refined during execution as the situation changes' — not a one-shot product.",
        "The event template is used to develop the information collection overlay and/or matrix AND the DST during COA analysis. This product is therefore upstream of both DST and ICM.",
        "6 NAIs may be in the AO or in the AOI — NAIs in another commander's AO require coordination for collection and cueing. Flag cross-AO NAIs in _provenance.",
        "6 threat decision points predict where the THREAT commander must decide on a particular COA — this is doctrinally distinct from friendly DPs and helps friendly forces drive when/where the threat must decide.",
        "7 construction algorithm: (1) begin with the situation template, (2) evaluate each COA to identify associated NAIs, (3) determine where events differentiate between COAs, (4) determine what action confirms/denies (indicators), (5) determine specific hour, (6) compare NAIs/indicators across COAs, (7) focus on differences providing the most reliable indications.",
        "0 event-matrix construction: use the time phase lines from the event template to establish the expected times in the event matrix; list the threat decision points from the template in the matrix.",
        "1 the completed event template + matrix form the basis for the DST + matrix and the information collection matrix downstream — they are the consolidation layer between per-COA SITEMPs and Annex L collection tasking.",
        "Per IDX 26: every NAI location, indicator, and time window cites source in _provenance (SITEMP / Threat COA Statement / OPORD / collection-asset basis).",
    ],
    "hard_rules": [
        "NAIs MUST cite the SITEMP / Threat COA Statement basis in _provenance — they are not invented; they are aggregated from per-COA SITEMP NAI sets7.",
        "Every NAI's threat_indicator MUST be a doctrinal indicator (Tables 6-1 / 6-2 form or analyst-named OE-specific indicator with provenance). Generic 'enemy activity' is not an indicator.",
        "Every NAI MUST link to at least one Threat COA Statement via associated_coas (7 — NAIs are COA-differentiating).",
        "Every event_matrix row MUST reference a NAI ID present in named_areas_of_interest.",
        "Every decision_points row MUST link to at least one NAI via associated_nais (6 — DPs anchor to NAI observations).",
        "Time-phase lines are mandatory6 — at least one TPL must appear even for static-defense scenarios (use H+0 as the baseline).",
        "Per IDX 26: every analytical claim cites source in _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Per-COA SITEMPs: list_project_docs(filter={type:'SITEMP'}) then get_project_doc(tag=<each>)",
        "Parent Threat COA Statement: list_project_docs(filter={type:'Threat COA Statement'}) then get_project_doc(tag=<latest>)",
        "Threat doctrine (REQUIRED — drives NAI indicators per OPFOR doctrinal signature behaviors): get_project_doc(tag='DonovianDoctrine'). NAI watching_for indicators MUST reflect the OPFOR signatures in section 8 (e.g., 'forward AT battery emplacement', 'TANK BDE forward movement = counter-attack commit window 4-6h after breach', '62 CBT AVN BDE rotary deep attack = most-dangerous COA execution indicator', '6 IFC ARMY counter-preparation fires = pre-emptive disruption COA').",
        "OPORD context (PIRs, friendly DPs): get_project_doc(tag='OPORD') §3.d, §4",
        "MCOO + Threat Overlay for terrain / threat references: list_project_docs(filter={type:'MCOO'}), list_project_docs(filter={type:'Threat Overlay'})",
        "Phased concept of operations (PRIMARY — NAIs tied to phase windows; TPLs align to phase boundaries): get_phases() — ordered phase concept (id/name/start_dtg/end_dtg/concept/decisive_point/phase_objectives)",
        "Operations overlay control measures (NAIs anchor to AO / boundaries / phase lines / axes / OBJ / EAs from the overlay): get_spatial_overlay()",
        "Map render: render_map(layers=['terrain','nais','time_phase_lines','decision_points','spatial_overlay'], format='both')",
    ],
    "post_emit_summary": "artifact_id, NAI count, DP count, COAs differentiated, key indicators",
}
