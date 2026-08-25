"""Threat COA Statement — ATP 2-01.3 Step 4.

User-facing name: "Threat COA Statement" (renamed from the legacy
"Enemy Course of Action" tag on 2026-05-30 — the artifact's purpose
is the per-COA threat statement, and "threat" aligns with the rest of
the IPOE Step-3/4 vocabulary). The PRODUCT_SCHEMAS key stays
`Threat COA Statement` because consumers reference it everywhere as
`ref:Threat COA Statement` and as a filename prefix on disk — renaming
the key would break artifact lookup across the registry, depends_on
edges, and the autodraft directory layout. Display strings (SPEC["name"],
PRODUCT_LONG_NAMES["Threat COA Statement"], the writer's system prompt)
carry the new name.

Doctrinally a "course of action" is singular even when the artifact
enumerates multiple COAs (per ATP 2-01.3 para 6-35: minimum
most-likely + most-dangerous). The product type uses the singular form.

Schema architecture: the COA-set configuration (count, per-rank roles,
per-rank narrative-doctrine bindings, doctrinal invariants) lives in
`SPEC["product_config"]["coa_set"]`. The block is the per-exercise /
per-commander knob; it is the surface a runtime config UI binds to.
The schema's hard_rules + guidance reference the config block by name,
never by value — no count, no rank-to-flag mapping, no unit name is
hard-coded into the rules.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "Threat COA Statement",
    "output_format": "docx",
    "shape": "structured",

    # Analyst-configurable knobs surfaced via the gear button next to
    # Generate on the dashboard. Mirrors HVTL's hvt_worthy_categories
    # pattern — frontend reads via GET /api/products/config_fields/
    # {product_type}, persists via POST /api/products/config/{type},
    # and threads through /api/products/generate?config_json=... at
    # request time. Backend reads in main._generate_with_config and
    # sets the matching contextvar so the renderer / writer picks it up.
    "config_fields": {
        # COA role badges ([MOST LIKELY] / [MOST DANGEROUS] /
        # [MOST DECEPTIVE] inline after the COA-N heading). Default
        # False — analyst sees COA-1 / COA-2 / COA-3 / COA-4 as bare
        # numbered alternatives without editorial pre-labeling. The
        # rank / most_dangerous / most_deceptive schema fields remain
        # so probability_rationale narrative + downstream products can
        # reference them; only the heading badge is suppressed.
        # Backend reads in main._generate_with_config and sets
        # equipment_doctrine.SHOW_COA_ROLE_BADGES_OVERRIDE. Renderer
        # checks the contextvar at the badge-emission site in
        # exporter.py (TCOAS docx heading + Threat COAs PPTX title bar).
        "show_coa_role_badges": {
            "type": "bool",
            "render_label": "Show [MOST LIKELY] / [MOST DANGEROUS] / [MOST DECEPTIVE] badges on COA headings",
            "default": False,
        },
    },

    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines the Threat COA
    # Statement map per ATP 2-01.3 §5-72: per-COA threat scheme of
    # maneuver — axes, objectives, battle positions over terrain.
    # Frontend has zero Threat-COA-Statement-specific branches.
    # ------------------------------------------------------------------
    "map_basemap": "default",

    # Per-product overlay gate. Threat COA Statement carries the
    # per-COA threat scheme of maneuver (axes), objectives, and
    # disposition over terrain.
    "map_overlay_kinds": [
        "avenue_of_approach", "key_terrain",
        "axis_of_advance",  # threat axes (per-COA)
        "threat_objective", "range_fan",
        "battle_position", "engagement_area",
        "phase_line", "boundary",
        "named_area_of_interest",
    ],

    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: same as SITEMP — Threat COA Statement feeds
    # SITEMP downstream and the two share the threat-disposition
    # graphic vocabulary.
    "map_doctrinal_layer_visibility": [
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-pl-line",
        "mcoo-bp-fill", "mcoo-bp-line",
        "mcoo-ea-fill", "mcoo-ea-line", "mcoo-ea-line-hostile",
        "mcoo-obj-line",
        "mcoo-nai-line", "mcoo-tai-line",
        "mcoo-points-hit-target",
    ],

    "map_show_topographic_contours": False,
    # Individual threat units shown per-COA (each templated echelon
    # at its COA-specific position).
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": True,
    "map_compact_legend_labels": True,

    # ------------------------------------------------------------------
    # Per-exercise product-shape configuration. THIS is the surface a
    # runtime config UI binds to. The writer reads from here at
    # generate-time; the validator reads from here at config-load time.
    # ------------------------------------------------------------------
    "product_config": {
        "coa_set": {
            # Number of COAs to emit. Per-exercise commander/analyst
            # knob. Doctrinal minimum is 2 per ATP 2-01.3 ¶6-35
            # (most-likely + most-dangerous). The writer emits
            # EXACTLY `count` COAs.
            "count": 4,

            # Per-rank role binding. Each entry:
            #   rank                    integer 1..count (slot index)
            #   role                    human-readable slot name; the
            #                           writer uses it as a pattern
            #                           selection hint
            #   required                if True, the rank MUST be
            #                           emitted; if False, optional
            #   narrative_doctrine_ref  None or a doctrine-artifact
            #                           tag that supplies a
            #                           narrative lens for this
            #                           rank (e.g., SunTzuOPFOR
            #                           supplies the deception
            #                           worksheet for the
            #                           most_deceptive rank). The
            #                           artifact itself is loaded
            #                           via consumes_artifacts; this
            #                           field BINDS the rank to it.
            #   flag_fields             list of boolean field names
            #                           on the COA row that MUST be
            #                           set True for this rank.
            "ranks": [
                {"rank": 1, "role": "most_likely",
                 "required": True,
                 "narrative_doctrine_ref": None,
                 "flag_fields": ["most_likely"]},
                {"rank": 2, "role": "intermediate",
                 "required": False,
                 "narrative_doctrine_ref": None,
                 "flag_fields": []},
                {"rank": 3, "role": "most_dangerous",
                 "required": True,
                 "narrative_doctrine_ref": None,
                 "flag_fields": ["most_dangerous"]},
                {"rank": 4, "role": "most_deceptive",
                 "required": False,
                 "narrative_doctrine_ref": "SunTzuOPFOR",
                 "flag_fields": ["most_deceptive"]},
            ],

            # --------------------------------------------------------
            # Doctrinal invariants — enforced at config-load time, NOT
            # configurable away. ATP 2-01.3 ¶6-35 + ¶6-34.
            # --------------------------------------------------------
            # Minimum number of COAs per ATP 2-01.3 ¶6-35.
            "doctrinal_minimum": 2,
            # Flag fields that MUST appear (set True) on some COA in
            # any valid coa_set.
            "doctrinal_required_flags": [
                "most_likely", "most_dangerous",
            ],
            # Flag fields that may appear AT MOST once across the set.
            "doctrinal_at_most_one_per_flag": [
                "most_likely", "most_dangerous", "most_deceptive",
            ],
            # Flag pairs that are mutually exclusive on the same COA.
            "doctrinal_mutually_exclusive_flag_sets": [
                ["most_dangerous", "most_deceptive"],
            ],
        },
    },

    "doctrine": {
        "purpose": (
            "Step-4 IPOE: identify and describe threat COAs that can "
            "influence friendly operations. The emitted COA set bounds "
            "the threat's decision space so the friendly commander has "
            "a defensible answer to 'what is the threat going to do?' "
            "in this phase of this operation. ATP 2-01.3 ¶6-35 sets "
            "the doctrinal floor: at minimum most-likely + most-"
            "dangerous. ATP 2-01.3 ¶6-34 sets the validity criteria: "
            "feasible, acceptable, suitable, distinguishable, "
            "complete (same five criteria the friendly staff uses for "
            "friendly COAs).\n\n"
            "Coverage of the COA set — count, per-rank role binding, "
            "per-rank narrative-doctrine binding — is configured per "
            "exercise in SPEC['product_config']['coa_set']. That block "
            "is the surface a commander or analyst tunes before a "
            "build: how many COAs to emit (typically 2-5), which "
            "ranks bind to which doctrinal flag (most_likely / "
            "most_dangerous / most_deceptive), and which (if any) "
            "additional narrative-doctrine artifact supplies a lens "
            "for a given rank (e.g., a deception-doctrine artifact "
            "for the most_deceptive rank). The schema enforces "
            "doctrinal invariants on top of the configuration (most-"
            "likely and most-dangerous always present; no COA carries "
            "both most-dangerous and most-deceptive). The writer "
            "reads the configured coa_set at generate-time and emits "
            "EXACTLY count COAs in rank order, with each rank's role, "
            "flag_fields, and narrative_doctrine_ref applied per the "
            "config.\n\n"
            "Each COA carries statement (six basic questions) + "
            "objectives + functional allocation + distinguishing "
            "characteristics + probability rationale + per-COA HVT "
            "list. The SITEMP graphic is a separate downstream "
            "artifact (one per COA)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "COAs ordered by rank, ascending. Rank 1 is the most "
            "likely COA; the highest rank in the emitted set is the "
            "least likely. The most_dangerous and most_deceptive "
            "flags are independent of rank order — the rank carrying "
            "each flag is set per SPEC['product_config']['coa_set']."
        ),
    },

    # Tier-2 IPOE inputs + Tier-1 BOTH rollups AND atomics. Mid-cycle
    # tactical shifts (sudden ADA repositioning, fresh source debrief
    # of imminent action) must surface in the Threat COA Statement
    # without waiting for the next-cycle SIGSUM/HUMINTSUM. Threat
    # doctrine artifacts (the base threat-doctrine reference + any
    # narrative-doctrine references bound by product_config.coa_set
    # ranks) are loaded here.
    "consumes_artifacts": [
        "MCOO", "TEM", "WEM", "CCA", "Threat Overlay",
        "SIGSUM", "HUMINTSUM",
        # Threat-doctrine artifacts. The specific artifact names
        # below are the ones the IDX-26 exercise loads; a different
        # exercise's scenario config rebinds these via the artifact
        # registry. The artifact NAMES are scenario data; the FACT
        # that the schema consumes one base threat-doctrine artifact
        # plus zero-or-more narrative-doctrine lenses (per
        # product_config.coa_set.ranks[*].narrative_doctrine_ref) is
        # schema.
        "DonovianDoctrine",
        "SunTzuOPFOR",
    ],

    "header_fields": {
        "phase": {**HEADER_PHASE,
                  "guidance": (
                      "MANDATORY — fill from the OE prose (e.g., "
                      "'Phase 2 (advance)') or OPORD §1.b. The analyst "
                      "names the phase verbatim in the request; carry "
                      "it through as `header_analysis.phase`. Extract "
                      "from analyst dispatch wording like 'Phase 2 in "
                      "AO ALPHA-NORTH'."
                  )},
        "dtg": HEADER_DTG,
        "area_of_operations": {**HEADER_AO,
                               "guidance": (
                                   "MANDATORY — fill from the OE prose "
                                   "(e.g., 'AO ALPHA-NORTH') or OPORD "
                                   "heading. The analyst names the AO "
                                   "verbatim in the request; carry it "
                                   "through as "
                                   "`header_analysis.area_of_operations`."
                               )},
        "threat": {"source": "session", "view": "header", "required": True,
                   "render_label": "Threat Force",
                   "guidance": (
                       "MANDATORY — name the threat force from the OE "
                       "prose (e.g., 'Donovian 11th Mech Bde'), latest "
                       "Threat Overlay artifact header.threat_force, or "
                       "the order of battle principal threat formation. "
                       "Fill via `header_analysis.threat`. Extract from "
                       "the threat unit named in the analyst dispatch "
                       "or the most recent SITEMP / Threat Overlay "
                       "artifact in the registry."
                   )},
        "mcoo_artifact_id": {"source": "upstream:MCOO", "view": "internal",
                             "required": False,
                             "depends_on": ["upstream:MCOO"]},
        "tem_artifact_id":  {"source": "upstream:TEM", "view": "internal",
                             "required": False,
                             "depends_on": ["upstream:TEM"]},
        "wem_artifact_id":  {"source": "upstream:WEM", "view": "internal",
                             "required": False,
                             "depends_on": ["upstream:WEM"]},
        "cca_artifact_id":  {"source": "upstream:CCA", "view": "internal",
                             "required": False,
                             "depends_on": ["upstream:CCA"]},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay",
                                       "view": "internal",
                                       "required": False,
                                       "depends_on": ["upstream:Threat Overlay"]},
        "prepared_by":    HEADER_PREPARED_BY,
        "classification": HEADER_CLASSIFICATION,
    },

    "paragraph_fields": [
        {"name": "coas",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Threat Courses of Action",
         "required": True,
         # Per-field max_tokens override: the coas paragraph emits 4 COA
         # rows each with ~10 narrative subfields (statement, objectives,
         # functional_allocation, distinguishing_characteristics,
         # probability_rationale, hvt_list, decisive_engagement,
         # branches_and_sequels, continuing_operations, task_org_units).
         # Each COA row averages ~2k chars; 4 rows × 2k = 8k chars =
         # ~2600 Gemma BPE tokens. Default _MAX_TOKENS["paragraph_field"]
         # of 3000 was truncating mid-COA after the decisive_engagement
         # field landed (7f08bbf). 8000-token budget gives the writer
         # 2x headroom + reasoning room.
         "max_tokens": 8000,
         # Row-count + per-rank flag/narrative_doctrine_ref binding is
         # pulled from product_config.coa_set at writer-prompt build time
         # and at post-emit validation time. The writer is told to emit
         # EXACTLY product_config.coa_set.count objects (one per rank
         # 1..count); the post-emit pass overwrites flag_fields and
         # narrative_doctrine_ref from the configured rank entry so the
         # rank->flag and rank->narrative-doctrine bindings are
         # deterministic (not writer-discretion).
         "row_count_source": "product_config.coa_set",
         "guidance": (
             # ---- Coverage (reads from product_config.coa_set) ----
             "Coverage: emit EXACTLY product_config.coa_set.count COAs "
             "in rank order. For each rank, apply the role + "
             "flag_fields + narrative_doctrine_ref from "
             "product_config.coa_set.ranks[rank-1]: the role names the "
             "slot (most-likely / intermediate / most-dangerous / "
             "most-deceptive / etc.) and guides doctrinal-pattern "
             "selection; flag_fields enumerate the boolean fields on "
             "the COA row to set True; narrative_doctrine_ref (if "
             "non-None) names the additional doctrine artifact whose "
             "narrative worksheet the writer applies for this rank "
             "(in addition to the base threat-doctrine artifact in "
             "consumes_artifacts). The doctrinal floor per ATP 2-01.3 "
             "¶6-35 — at minimum most-likely + most-dangerous — is "
             "enforced as a config invariant; the writer does not "
             "need to re-check it.\n\n"

             # ---- What each COA IS ----
             "Each COA is the INSTANTIATION of one doctrinal pattern "
             "from the threat-doctrine artifact this product consumes "
             "(see consumes_artifacts) against THIS threat formation, "
             "THIS AO terrain, THIS phase of THIS friendly operation. "
             "Pick a DISTINCT doctrinal pattern for each COA; the "
             "schema does not predetermine which pattern fills which "
             "rank. The rank's role (from product_config) is a "
             "selection HINT — for an offensive doctrinal menu, the "
             "most-likely rank typically picks the pattern the threat "
             "is currently posturing toward, the most-dangerous rank "
             "picks the pattern whose worst-case outcome most "
             "threatens friendly mission accomplishment, and an "
             "intermediate rank (where present) picks a pattern that "
             "brackets residual possibility space between the two. "
             "The writer is responsible for the pick; cite the "
             "pattern + the doctrine artifact section in _provenance.\n\n"

             # ---- Most-deceptive COA structure ----
             "Any COA carrying most_deceptive=True (set on the rank "
             "whose flag_fields includes 'most_deceptive' per "
             "product_config.coa_set) is structured around the "
             "five-element deception worksheet from hard_rules: "
             "(1) FALSE READ, (2) DECEPTION ACTION, (3) MASS, "
             "(4) COMMITMENT TRIGGER, (5) SIGNATURE DISAMBIGUATION. "
             "The structural worksheet is sourced from the "
             "narrative_doctrine_ref bound to that rank (e.g., the "
             "deception worksheet section of the configured "
             "deception-doctrine artifact); if no "
             "narrative_doctrine_ref is bound, the worksheet is "
             "sourced from the base threat-doctrine artifact's "
             "deception chapter. The COA is not actionable for the "
             "friendly commander unless friendly collection can "
             "detect the commitment-trigger release — element 5 "
             "(signature disambiguation) MUST identify which "
             "observable signatures are genuine vs spoofed.\n\n"

             # ---- Validity (ATP 2-01.3 ¶6-34) ----
             "All COAs in the set MUST pass the ATP 2-01.3 ¶6-34 "
             "validity criteria: feasible, acceptable, suitable, "
             "distinguishable, complete. Distinguishable "
             "operationalizes to: each COA carries at least one "
             "observable signature (force composition / axis / "
             "timing / ammunition class / preparation indicator) "
             "that friendly collection can use to disambiguate it "
             "from each of the other COAs in the set.\n\n"

             # ---- COA composition ----
             "Each COA = statement (six basic questions) + objectives "
             "+ functional allocation + distinguishing characteristics "
             "+ probability rationale + per-COA HVT list. See the "
             "per-subfield guidance below for the contract on each "
             "component."
         ),
         "depends_on": [
             "entities:units",
             "map:state",
             "entities:marked",
             # Threat-doctrine artifacts (base + any narrative-doctrine
             # references bound by product_config.coa_set.ranks). The
             # artifact names here mirror consumes_artifacts; the
             # writer's dependency planner resolves these tokens
             # against the artifact registry the same way it does for
             # MCOO / TEM / WEM.
             "document:DonovianDoctrine",
             "document:SunTzuOPFOR",
         ],
         "item_subfields": [
             {"name": "coa_id", "render_label": "COA ID",
              "guidance": (
                  "Short stable identifier, e.g. 'COA-1', 'COA-ML', "
                  "'COA-MD'."
              )},

             {"name": "label", "render_label": "Label",
              "guidance": (
                  "Short doctrinal name capturing scheme of maneuver "
                  "— e.g. 'Forward Defense Along Hill 220 Ridge', "
                  "'Mech Attack via Western Axis', 'Cellular Spoiling "
                  "Attack'. Reference the doctrinal pattern this COA "
                  "instantiates, not the rank role."
              )},

             # Doctrinal posture of THIS COA per ATP 2-01.3 §6. Drives the
             # downstream SITEMP variant (offense / defense / irregular /
             # hybrid). The SITEMP fan-out propagates this value into the
             # per-COA SITEMP header.coa_type via coa_focus; SITEMP uses it
             # to gate paragraph_fields whose required-ness depends on the
             # COA posture (battle_positions required for defense/hybrid
             # COAs per product_config.battle_position_required_for_defense_coas).
             {"name": "coa_type", "render_label": "COA Type",
              "enum": ["offense", "defense", "irregular", "hybrid"],
              "guidance": (
                  "Doctrinal posture of THIS COA per ATP 2-01.3 §6. "
                  "'offense' — the threat attacks (movement to contact, "
                  "deliberate attack, hasty attack, spoiling attack, "
                  "exploitation, pursuit). 'defense' — the threat "
                  "defends (area defense / mobile defense / "
                  "retrograde). 'hybrid' — the COA executes both "
                  "postures in distinct phases (e.g. defensive belt "
                  "plus counter-attack from depth). 'irregular' — "
                  "cellular / insurgent / unconventional. Pick by "
                  "inspecting THIS COA's statement.what (tactical-"
                  "mission task) and statement.how (scheme of "
                  "maneuver): attack / seize / exploit / pursue → "
                  "'offense'; hold / deny / retain / delay / withdraw "
                  "→ 'defense'; mixed phases → 'hybrid'; cellular / "
                  "networked / insurgent → 'irregular'. The most-"
                  "dangerous COA in a defensive friendly operation is "
                  "typically 'offense' (the threat attacks); the most-"
                  "likely COA in an exploitation friendly operation "
                  "is typically 'defense' (the threat consolidates)."
              )},

             {"name": "rank", "render_label": "Rank (1=most likely)",
              "guidance": (
                  "Integer 1..product_config.coa_set.count. Rank 1 = "
                  "most likely; highest rank in the set = least "
                  "likely. Rank is independent of the most_dangerous / "
                  "most_deceptive flags — the writer applies the rank "
                  "→ flag_fields mapping from "
                  "product_config.coa_set.ranks[rank-1]."
              )},

             {"name": "most_likely", "render_label": "Most Likely",
              "guidance": (
                  "Boolean. Exactly one COA across the set carries "
                  "True — the COA the threat is most likely to adopt. "
                  "Which rank carries this flag is configured in "
                  "product_config.coa_set.ranks (find the rank entry "
                  "whose flag_fields contains 'most_likely')."
              )},

             {"name": "most_dangerous", "render_label": "Most Dangerous",
              "guidance": (
                  "Boolean. Exactly one COA across the set carries "
                  "True — the COA most threatening to friendly mission "
                  "accomplishment in THIS phase of THIS operation. "
                  "Which rank carries this flag is configured in "
                  "product_config.coa_set.ranks (find the rank entry "
                  "whose flag_fields contains 'most_dangerous'). "
                  "probability_rationale MUST tie the danger to a "
                  "specific friendly decisive task or end-state "
                  "condition the COA threatens."
              )},

             {"name": "narrative_doctrine_ref",
              "render_label": "Narrative Doctrine Reference",
              "required": False,
              "guidance": (
                  "Deterministically populated post-emit from "
                  "product_config.coa_set.ranks[rank-1].narrative_doctrine_ref. "
                  "Names the additional doctrine artifact whose narrative "
                  "worksheet applies to this rank (e.g., 'SunTzuOPFOR' "
                  "for the most_deceptive rank to supply the five-"
                  "element deception worksheet). The writer does not "
                  "author this value — emit None or omit; the post-emit "
                  "pass overwrites with the configured value (None when "
                  "the rank has no narrative_doctrine_ref bound)."
              )},

             {"name": "most_deceptive", "render_label": "Most Deceptive",
              "guidance": (
                  "Boolean. At most one COA across the set carries "
                  "True — the COA whose primary mechanism of effect is "
                  "deception (inducing a specific friendly decision "
                  "against a phantom main effort, rather than "
                  "maximizing raw lethality on the actual axis). Which "
                  "rank (if any) carries this flag is configured in "
                  "product_config.coa_set.ranks (find the rank entry "
                  "whose flag_fields contains 'most_deceptive'); if no "
                  "rank carries it, no COA in the emitted set is "
                  "deception-shaped and the five-element worksheet "
                  "rule below does not fire. The COA MUST be "
                  "structured against the five-element deception "
                  "worksheet from hard_rules: (1) FALSE READ — what "
                  "the threat wants the friendly commander to believe; "
                  "(2) DECEPTION ACTION — the observable activity "
                  "produced to sell the false read; (3) MASS — where "
                  "the real decisive effort lands; (4) COMMITMENT "
                  "TRIGGER — the observable event that releases the "
                  "threat from deception phase to commitment phase; "
                  "(5) SIGNATURE DISAMBIGUATION — for each observable "
                  "signature, whether it is genuine or spoofed. The "
                  "worksheet is sourced from the narrative_doctrine_ref "
                  "bound to this rank in product_config.coa_set (or "
                  "from the base threat-doctrine artifact if none is "
                  "bound). Unit assignments for each element are "
                  "derived from the OOB and cited in _provenance — do "
                  "NOT name units in this subfield's narrative; that "
                  "belongs in functional_allocation. "
                  "distinguishing_characteristics MUST identify which "
                  "signatures are genuine vs spoofed so friendly "
                  "collection can disambiguate. probability_rationale "
                  "MUST articulate the deception scheme in the same "
                  "five-element vocabulary."
              )},

             {"name": "statement",
              "render_label": "COA Statement (Six Basic Questions)",
              "shape": "dict",
              "guidance": (
                  "Narrative answering the six basic questions. Each "
                  "answer is specific to THIS scenario in a way that "
                  "would not survive a search-and-replace of the "
                  "threat force name or AO — paraphrasing the "
                  "doctrine artifact verbatim is a writer bug."
              ),
              "subfields": ["who", "what", "when", "where", "how", "why"],
              "subfield_guidance": {
                  "who": (
                      "Organizational structure of the threat "
                      "organization, including external organizations "
                      "providing support."
                  ),
                  "what": (
                      "Tactical mission task — defeat, destroy, "
                      "seize, retain, delay, disrupt, fix, block, etc."
                  ),
                  "when": (
                      "Earliest time the action can begin, expressed "
                      "as a DTG or H-hour relative window."
                  ),
                  "where": (
                      "Battlefield geometry — boundaries, objectives, "
                      "axes, routes, NAIs, engagement areas."
                  ),
                  "how": (
                      "Scheme of maneuver — attack/defend posture, "
                      "formations, phasing, decisive operation.\n\n"

                      "For any COA carrying most_deceptive=True, this "
                      "field is the STRUCTURAL HOME for elements 1-4 "
                      "of the deception worksheet. The 'how' MUST "
                      "specify:\n"
                      "  - FALSE READ: what the threat WANTS the "
                      "friendly commander to believe (which axis is "
                      "decisive, which formation is the main effort, "
                      "which timeline). Name the specific friendly "
                      "decision the false read is targeting.\n"
                      "  - DECEPTION ACTION: the observable activity "
                      "the threat produces to sell the false read "
                      "(demonstration on the non-decisive axis, dummy "
                      "positions, decoy comms, demonstrative fires, "
                      "civilian-pattern movement on the masked axis). "
                      "State which activity is produced for friendly "
                      "observation versus which activity is masked "
                      "from observation.\n"
                      "  - MASS: where the real decisive effort "
                      "actually lands once the friendly main effort "
                      "commits to the false read, and the "
                      "formation(s) that deliver it.\n"
                      "  - COMMITMENT TRIGGER: the observable event "
                      "that releases the threat from the deception "
                      "phase into the commitment phase (friendly "
                      "recon confirmation of the phantom main effort, "
                      "friendly fires expended against decoy "
                      "preparations, friendly reserve committed "
                      "against the spoof, or a fixed time horizon "
                      "driven by threat logistics runtime). State the "
                      "trigger as a specific friendly action or DTG "
                      "window an analyst can collect against.\n\n"

                      "Element 5 (SIGNATURE DISAMBIGUATION) belongs "
                      "in distinguishing_characteristics. The "
                      "probability_rationale field does NOT carry any "
                      "deception-worksheet content; it carries only "
                      "the likelihood judgment + reasoning + COA "
                      "comparison per the HARD_RULES ICD-203 contract."
                  ),
                  "why": (
                      "Threat objectives and end state — what threat "
                      "is trying to achieve."
                  ),
              }},

             {"name": "objectives",
              "render_label": "Objectives + End State",
              "shape": "dict",
              "guidance": (
                  "Threat objectives are terrain- or force-oriented "
                  "for regular threats; event-driven for irregular. "
                  "End state defines achievement of objectives."
              ),
              "subfields": ["immediate", "subsequent", "desired_end_state"],
              "subfield_guidance": {
                  "immediate": (
                      "First-priority objective — usually a near-term "
                      "tactical task (seize Hill X, destroy CSS node, "
                      "retain crossing)."
                  ),
                  "subsequent": (
                      "Follow-on objective if the immediate is "
                      "achieved — branches and sequels."
                  ),
                  "desired_end_state": (
                      "Set of conditions defining mission success "
                      "(e.g., 'friendly forces incapable of "
                      "coordinated defense south of PL RED')."
                  ),
              }},

             {"name": "decisive_engagement",
              "render_label": "Decisive Engagement",
              "required": True,
              "provenance_required": True,
              "guidance": (
                  "Per ATP 2-01.3 §6 / FM 3-90: where and how the THREAT seeks to "
                  "decisively defeat the friendly attack for THIS COA. Names the "
                  "geographic area + the formations + the doctrinal mechanism "
                  "(envelopment, attrition in kill zone, counterattack from depth, "
                  "etc.). Cite the upstream OPORD body + the threat doctrine "
                  "artifact's decisive-engagement section in _provenance.\n\n"
                  "EXAMPLES by coa_type:\n"
                  "  - defense (area): 'Defeat the friendly main effort within the "
                  "    multi-belt positional defense vic Kopu-Rongu-Osula by "
                  "    canalizing 1st ID/V Corps into prepared kill zones supported "
                  "    by U-DN-605FABDE + U-DN-625FABDE massed indirect fires.'\n"
                  "  - defense (maneuver): 'Defeat 1st ID lead BDE at NAI-VALGA via "
                  "    counterattack from depth by U-DN-604TANKBDE once the "
                  "    penetration commits.'\n"
                  "  - hybrid: 'Canalize friendly main effort into the battle-zone "
                  "    kill zones, then commit U-DN-604TANKBDE counterattack force "
                  "    from depth against the penetration flank.'\n"
                  "  - offense / spoiling attack: 'Defeat the V Corps assembly area "
                  "    at NAI-CIMZA-ASSY via pre-emptive long-range fires + "
                  "    U-DN-601MECHIFVBDE spoiling assault before D-day.'\n"
                  "  - deception: 'Defeat the friendly main effort that commits to "
                  "    the SPOOFED axis at Rongu by exploiting their flank with the "
                  "    GENUINE mass U-DN-60MECHIFVDIV held off the Osula sector.'"
              )},

             {"name": "branches_and_sequels",
              "render_label": "Branches and Sequels",
              "required": True,
              "provenance_required": True,
              "guidance": (
                  "Per ATP 2-01.3 §6 / FM 3-90: decision points the THREAT "
                  "commander faces during execution + the alternative branches he "
                  "takes when conditions diverge from the base plan. For each "
                  "branch / sequel, name the TRIGGER condition + the THREAT ACTION "
                  "+ the formation committed.\n\n"
                  "FORMAT: short bulleted list. Each line is one branch or sequel.\n"
                  "EXAMPLES:\n"
                  "  - Branch (if friendly main effort shifts to Rongu): commit "
                  "    U-DN-623TANKBDE to reinforce the central sector.\n"
                  "  - Sequel (after successful canalization): commit "
                  "    U-DN-604TANKBDE counterattack force from depth against the "
                  "    penetration flank.\n"
                  "  - Branch (if friendly forces achieve PL ALPHA before H+24): "
                  "    transition to maneuver defense, withdraw "
                  "    U-DN-601MECHIFVBDE through battle zone.\n\n"
                  "Cite upstream Threat COA Statement objectives.subsequent + the "
                  "threat-doctrine artifact's branch/sequel decision triggers in "
                  "_provenance."
              )},

             {"name": "continuing_operations",
              "render_label": "Continuing Operations",
              "required": True,
              "provenance_required": True,
              "guidance": (
                  "Per ATP 2-01.3 §6 + ADP 5-0: what the THREAT does AFTER the "
                  "decisive engagement resolves. REQUIRED — every COA carries "
                  "this. No threat COA ends at the decisive engagement; the "
                  "force ALWAYS has a transition / consolidation / next-phase "
                  "posture.\n\n"

                  "MAPPING by outcome:\n"
                  "  - Successful defense: transition to counter-offensive / "
                  "    consolidate the recaptured ground / prepare for the "
                  "    next defensive cycle.\n"
                  "  - Successful offense (spoiling attack / counter-offensive): "
                  "    consolidate the gains / exploit toward the next "
                  "    objective / pursuit of broken friendly forces / "
                  "    transition back to a defensive posture if the spoil "
                  "    was a delaying action.\n"
                  "  - Successful deception: exploit the friendly mis-"
                  "    commitment by attacking their exposed flank / pursue "
                  "    the broken main effort / consolidate the gain.\n"
                  "  - Stalemated / partially-failed COA: withdraw the "
                  "    surviving combat power to a reconstitution area / "
                  "    transition to a secondary defensive band / preserve "
                  "    combat power for a renewed effort.\n\n"
                  "EXAMPLES by coa_type:\n"
                  "  - successful area defense: 'Transition U-DN-604TANKBDE + "
                  "    U-DN-623TANKBDE to a counter-offensive south through the "
                  "    disruption zone toward Valga.'\n"
                  "  - successful spoiling attack: 'Withdraw U-DN-601MECHIFVBDE to "
                  "    the main defensive belt; reconstitute for the main "
                  "    defensive battle.'\n"
                  "  - failed COA: 'Withdraw the surviving combat power to the "
                  "    Voru reconstitution area + transition the corps to a "
                  "    defensive posture along the secondary defensive band.'\n\n"
                  "Cite upstream Threat COA Statement coa.statement closure + the "
                  "threat-doctrine artifact's continuing-operations section in "
                  "_provenance."
              )},

             {"name": "functional_allocation",
              "render_label": "Functional Allocation",
              "shape": "dict",
              "guidance": (
                  "Per TC 7-100.2, threat formations are allocated to "
                  "doctrinal ROLE-BINS based on the COA's `coa_type`. "
                  "ROLE-BINS REQUIRED PER COA_TYPE:\n"
                  "  - defense (area/positional): "
                  "    disruption_force + main_defense_force + counterattack_force (3 required)\n"
                  "  - defense (maneuver): "
                  "    action_force + main_defense_force + counterattack_force (3 required)\n"
                  "  - hybrid (disruption-zone maneuver + battle-zone area): "
                  "    action_force + disruption_force + main_defense_force + counterattack_force (4 required)\n"
                  "  - offense (attack / spoiling attack / counter-offensive): "
                  "    action_force + exploitation_force + reserve (3 required) "
                  "    — note: 'counterattack_force' is for DEFENSIVE COAs; offensive COAs use "
                  "    'exploitation_force' for follow-on exploitation, NOT 'counterattack_force'.\n"
                  "  - deception (Sun Tzu pattern, most_deceptive=True): "
                  "    action_force + deception_force + main_defense_force + reserve (4 required) — "
                  "    deception_force projects false signatures; action_force is the genuine mass.\n\n"

                  "UNIT-TYPE → ROLE-BIN DOCTRINE (TC 7-100.2 + Donovian OOB convention):\n"
                  "  - MTZ INF DIV / BDE (motorized infantry, foot-speed): "
                  "    static roles — main_defense_force, deception_force (signature projection). "
                  "    NEVER as action_force in offensive/maneuver COAs (can't keep tempo).\n"
                  "  - MECH IFV DIV / BDE (mechanized infantry fighting vehicle): "
                  "    mobile roles — action_force, disruption_force, exploitation_force.\n"
                  "  - TANK BDE / DIV: "
                  "    counterattack_force (defensive COAs), exploitation_force (offensive COAs), "
                  "    or action_force when the operation is armor-led.\n"
                  "  - FA BDE (field artillery): NEVER in functional_allocation — fires are a warfighting "
                  "    function, not a maneuver role. Field artillery formations belong on the HVT list.\n"
                  "  - CBT ENG BDE (combat engineer): NEVER in functional_allocation — mobility / "
                  "    counter-mobility is a function. Combat engineer formations belong on the HVT list.\n"
                  "  - ADA BDE (air defense): NEVER in functional_allocation — air defense is a function. "
                  "    Air defense formations belong on the HVT list.\n"
                  "  - SIG BDE / RECON BDE / CBT AVN BDE / CSS / SUSTAINMENT BDE: enablers, NOT "
                  "    functional_allocation. Reconnaissance brigades go on the HVT list under "
                  "    reconnaissance_intelligence_surveillance_target_acquisition.\n\n"

                  "UNIQUENESS RULE: each unit appears in EXACTLY ONE role-bin per COA. A parent division "
                  "and its subordinate brigade are the SAME formation — if the parent DIV is "
                  "action_force, NONE of its subordinate brigades are eligible for other roles in this COA. "
                  "Look at the OOB row's `parent_id` / subordination field — if your candidate is a child of a "
                  "formation already assigned, pick a different parent formation OR a different child OF A "
                  "DIFFERENT PARENT for the second role.\n\n"

                  "ROLE-BIN DEFINITIONS:\n"
                  "  - action_force: the primary maneuver formation conducting THIS COA's decisive task.\n"
                  "  - disruption_force: forward force operating in the disruption zone (south of battle "
                  "    zone in this defense) to engage friendly recon + initial penetrations.\n"
                  "  - main_defense_force: the formation holding the battle-zone main defensive belts.\n"
                  "  - counterattack_force: the mobile reserve committed against friendly penetrations of "
                  "    the main defensive belts. DEFENSIVE COAs ONLY.\n"
                  "  - exploitation_force: the mobile follow-on formation passing through the action force "
                  "    after the initial breakthrough. OFFENSIVE COAs ONLY.\n"
                  "  - deception_force: the formation generating false signatures / dummy positions / "
                  "    spoofed emissions to mislead the friendly commander. Pair with most_deceptive=True.\n"
                  "  - reserve: uncommitted formation held back for contingencies, with explicit commitment "
                  "    criteria stated in the COA statement.\n\n"

                  "PROVENANCE: every unit designation written into a role MUST be an OOB row (cougaar.get_oob "
                  "rows[*].id). Cite the kbID in this COA's _provenance. Do not invent designations. Do not "
                  "assign a unit whose echelon, force-class, or affiliation contradicts the role-bin's "
                  "doctrinal type per the table above. If the doctrinal pattern calls for a role the OOB "
                  "has no candidate for, leave the role blank and emit a gap_note in this COA's "
                  "distinguishing_characteristics — never fabricate."
              ),
              "strict_subfields": False,
              "subfields": ["action_force", "disruption_force",
                            "main_defense_force", "counterattack_force",
                            "exploitation_force", "deception_force", "reserve"],
              "subfield_guidance": {
                  "action_force": (
                      "Primary maneuver formation conducting this COA's decisive task. "
                      "Must be MECH IFV / TANK echelon (mobile) for offensive / maneuver "
                      "COAs; may be MTZ INF only in pure area-defense COAs where the action "
                      "force IS the main defense (one bin only). Cite by OOB row id."
                  ),
                  "disruption_force": (
                      "Forward formation in the disruption zone (south of battle zone in "
                      "this defense). MECH IFV BDE or motorized recon are typical. Must be a "
                      "DIFFERENT formation from the action force — not a subordinate brigade "
                      "of it."
                  ),
                  "main_defense_force": (
                      "Formation holding the battle-zone main defensive belts. Typically "
                      "MTZ INF DIV (foot-mobile, dug-in). Cite by OOB row id."
                  ),
                  "counterattack_force": (
                      "Mobile reserve committed against penetrations of the main defensive "
                      "belts. Typically TANK BDE. DEFENSIVE COAs ONLY — do NOT use this bin "
                      "for offensive COAs (use exploitation_force instead)."
                  ),
                  "exploitation_force": (
                      "Mobile follow-on formation passing through the action force after the "
                      "initial breakthrough. Typically TANK BDE or MECH IFV BDE. OFFENSIVE "
                      "COAs ONLY — do NOT use this bin for defensive COAs."
                  ),
                  "deception_force": (
                      "Formation generating false signatures / dummy positions / spoofed "
                      "emissions to mislead the friendly commander. Typically MTZ INF "
                      "(static-looking by default) paired with SIG BDE assets. Required when "
                      "most_deceptive=True; cross-reference to the deception worksheet."
                  ),
                  "reserve": (
                      "Uncommitted formation held back for contingencies. The COA statement "
                      "MUST state explicit commitment criteria (trigger events that release "
                      "the reserve). Cite by OOB row id."
                  ),
              }},

             {"name": "distinguishing_characteristics",
              "render_label": "Distinguishing Characteristics",
              "guidance": (
                  "What makes THIS COA visibly different from the "
                  "others (validity criterion 4: distinguishable). "
                  "Identify the few observable signatures (force "
                  "composition / axis / timing / ammunition class / "
                  "preparation indicator) that friendly collection can "
                  "use to disambiguate which COA the threat has "
                  "adopted. Each signature MUST be something a named "
                  "friendly collection asset or NAI can actually "
                  "observe — not an internal analytical descriptor.\n\n"

                  "For any COA carrying most_deceptive=True: for each "
                  "observable signature, state whether it is GENUINE "
                  "(the real action is reflected in this signature) "
                  "or SPOOFED (the signature is produced for friendly "
                  "consumption while the real action is masked). This "
                  "is element 5 of the most-deceptive COA's five-"
                  "element structural framework (see hard_rules). A "
                  "deception COA whose signatures are all genuine has "
                  "no deception mechanism; a deception COA whose "
                  "signatures are all spoofed has no friendly-"
                  "detectable commitment trigger and is not "
                  "actionable for the commander."
              )},

             {"name": "probability_rationale",
              "render_label": "Probability Rationale",
              "guidance": (
                  "The ICD-203-shaped likelihood judgment for THIS "
                  "COA. The HARD_RULES ICD-203 contract is binding: "
                  "one vocabulary word from the seven-level scale, "
                  "evidence + reasoning chain (cited recent activity, "
                  "terrain/weather constraint, observed preparations, "
                  "doctrinal pattern paraphrased without publication "
                  "or section references), and EXPLICIT LIKELIHOOD-"
                  "AXIS COMPARISON to EVERY other COA in the set "
                  "('more likely than COA-X because...' / 'less "
                  "likely than COA-Y because...' or an explicit "
                  "ranking statement). No percentages. No section "
                  "symbols. No publication tokens.\n\n"

                  "For any COA carrying most_dangerous=True: the "
                  "likelihood judgment + comparative framing remain "
                  "mandatory. ADDITIONALLY identify what makes the "
                  "COA most threatening to friendly MISSION "
                  "ACCOMPLISHMENT in THIS phase of THIS operation — "
                  "tie the danger to a specific friendly decisive "
                  "task or end-state condition the COA threatens. "
                  "The danger axis NEVER substitutes for the "
                  "likelihood-axis comparison; both must appear. A "
                  "most-dangerous COA may simultaneously be the "
                  "least likely.\n\n"

                  "For any COA carrying most_deceptive=True: the "
                  "same ICD-203 contract applies — vocabulary word + "
                  "likelihood-axis comparison + reasoning. The five-"
                  "element deception worksheet (FALSE READ, "
                  "DECEPTION ACTION, MASS, COMMITMENT TRIGGER, "
                  "SIGNATURE DISAMBIGUATION) does NOT belong in this "
                  "field — elements 1-4 live in statement.how, "
                  "element 5 lives in distinguishing_characteristics. "
                  "The probability_rationale for a deception COA "
                  "answers: how likely is the threat to attempt this "
                  "deception scheme (vocabulary word), compared to "
                  "the other COAs (likelihood-axis comparisons), and "
                  "why (capability gap, observed indicators absent or "
                  "present, the historical pattern of this commander "
                  "using or not using deception, the operational "
                  "tempo permitting or not permitting the preparation "
                  "the deception requires). The deception mechanics "
                  "themselves are described in the structural fields, "
                  "not here."
              )},

             {"name": "hvt_list", "render_label": "Per-COA HVT List",
              "shape": "list_of_dicts",
              "guidance": (
                  "THREAT-side HVTs critical to THIS COA's success — "
                  "the THREAT formations that, if friendly forces kill "
                  "them, would degrade or break this COA. Group by "
                  "warfighting function.\n\n"

                  "EVERY UNIT_ID HERE MUST BE U-DN-<...> (RED / "
                  "DONOVIAN). NEVER list U-BL-<...> (BLUE / FRIENDLY) "
                  "formations on the HVT list. Friendly formations the "
                  "threat plans to target are a TARGET LIST (fires "
                  "planning), NOT an HVT list. HVT is doctrinally "
                  "FRIENDLY-perspective: what THREAT assets friendly "
                  "forces should prioritize for attack to disrupt the "
                  "threat COA. Even for OFFENSIVE threat COAs (spoiling "
                  "attack, deception), the HVT list is still THREAT C2 "
                  "/ fires / RISTA / sustainment — NOT the friendly "
                  "formations the threat will engage.\n\n"

                  "Identifying HVTs feeds HPT development during MDMP "
                  "COA development. For any COA carrying "
                  "most_deceptive=True, the HVT list MUST include the "
                  "C2 / signal / ISR nodes the deception depends on — "
                  "loss of those nodes collapses the spoof. Unit "
                  "identities are pulled from cougaar.get_oob (filter "
                  "by force_type='RED' or affiliation='Donovian') and "
                  "cited in _provenance."
              ),
              "item_subfields": [
                  {"name": "threat_element",
                   "render_label": "Threat Element",
                   "enum": ["c2", "movement_and_maneuver", "protection",
                            "fires", "intelligence", "sustainment"],
                   "guidance": (
                       "Warfighting function category: c2 | "
                       "movement_and_maneuver | protection | fires | "
                       "intelligence | sustainment."
                   )},
                  {"name": "hvt",
                   "render_label": "HVT (System Nomenclature)",
                   "guidance": (
                       "Specific system or facility by nomenclature "
                       "— pull from cougaar.get_oob() / "
                       "cougaar.list_targets() and cite the source "
                       "row in _provenance."
                   )},
                  {"name": "target_loss_effect",
                   "render_label": "Target-Loss Effect",
                   "guidance": (
                       "What happens to the COA if this HVT is "
                       "neutralized. One sentence."
                   )},
                  {"name": "possible_threat_response",
                   "render_label": "Possible Threat Response",
                   "guidance": (
                       "Threat's anticipated reaction — substitute "
                       "asset, branch/sequel, withdraw, accept risk."
                   )}]},

             {"name": "sitemp_artifact_id", "render_label": "SITEMP Reference",
              "required": False,
              "guidance": (
                  "OPTIONAL forward reference. The SITEMP graphic per "
                  "COA is a SEPARATE downstream artifact — leave blank "
                  "during the Threat COA Statement build; it gets "
                  "back-filled once SITEMPs are produced. Do NOT "
                  "invent placeholder ids."
              )},
         ]}],

    "subtleties": [
        # Doctrinal-shape subtleties only. No IDX-26-specific framing,
        # no fixed COA count, no named units.
        "Coverage of the COA set — count, per-rank role binding, "
        "per-rank narrative-doctrine binding — is configured in "
        "SPEC['product_config']['coa_set']. The doctrinal floor per "
        "ATP 2-01.3 ¶6-35 is most-likely + most-dangerous; the "
        "configuration may add additional ranks (intermediate, "
        "most-deceptive, branches, sequels) to bracket residual "
        "possibility space. Configuration-level invariants "
        "(doctrinal_minimum, doctrinal_required_flags, "
        "doctrinal_at_most_one_per_flag, "
        "doctrinal_mutually_exclusive_flag_sets) are validated at "
        "config-load time.",
        "Validity criteria (ATP 2-01.3 ¶6-34): feasible, acceptable, "
        "suitable, distinguishable, complete — same criteria used for "
        "friendly COAs.",
        "Six basic questions: Who (org structure incl. external "
        "support), What (tactical mission task), When (earliest "
        "start), Where (battlefield geometry), How (scheme of "
        "maneuver), Why (objectives).",
        "Per-COA HVT list grouped by warfighting function: c2 / "
        "movement_and_maneuver / protection / fires / intelligence / "
        "sustainment. HVTs usually fall within non-maneuver elements.",
        "Irregular threats: cellular array at every echelon; analyze "
        "through systems / network-engagement lens; doctrinal "
        "military terms (HVT, end state, mission) may need to be "
        "re-cast for irregular capabilities.",
        "Hybrid threats: if multiple threats with competing "
        "objectives, develop separate COAs per threat. If hybrid "
        "operates under unified C2, develop COAs against that "
        "command structure.",
        "Action vs enabling force decomposition: every COA has ONE "
        "action force performing the primary mission; remaining "
        "elements perform enabling functions (disruption / fixing / "
        "security).",
        "Objectives are terrain- or force-oriented for regular "
        "threats; event-driven for irregular. End state defines "
        "required conditions.",
        "Deception worksheet (five elements: false read / deception "
        "action / mass / commitment trigger / signature "
        "disambiguation) is a scenario-agnostic structural contract "
        "that fires whenever a COA in the emitted set carries "
        "most_deceptive=True. The worksheet body is sourced from the "
        "narrative_doctrine_ref bound to that rank in "
        "product_config.coa_set (e.g., a deception-doctrine artifact "
        "loaded via consumes_artifacts), or from the base threat-"
        "doctrine artifact's deception chapter if no rank-level "
        "narrative-doctrine reference is bound.",
        "SITEMP graphic per COA is a SEPARATE downstream artifact. "
        "sitemp_artifact_id is back-filled later; do not invent "
        "placeholders.",
        "Reverse IPB (consider friendly COA from threat perspective) "
        "is analytical input behind probability_rationale — does not "
        "appear as a separate field.",
    ],

    "hard_rules": [
        # ---- Provenance / grounding ----
        "Never invent threat intent without data basis. Every COA "
        "cites — in _provenance — the threat-doctrine artifact this "
        "product consumes (see consumes_artifacts), the OOB row(s) "
        "for each committed formation, and the recent-activity / "
        "FRAGO / observation entries that distinguish THIS COA from "
        "a generic doctrinal recital.",

        # ---- Coverage (reads from product_config.coa_set) ----
        "Coverage: emit EXACTLY product_config.coa_set.count COAs in "
        "rank order. Each emitted COA carries the role + flag_fields "
        "+ narrative_doctrine_ref from "
        "product_config.coa_set.ranks[rank-1]: the role is the "
        "doctrinal-pattern selection hint, flag_fields names the "
        "boolean fields on the COA row to set True (e.g., "
        "most_likely / most_dangerous / most_deceptive), and "
        "narrative_doctrine_ref (when non-None) names the additional "
        "doctrine artifact whose narrative worksheet applies for "
        "this rank. The doctrinal floor per ATP 2-01.3 ¶6-35 (at "
        "minimum most-likely + most-dangerous) is enforced as a "
        "config invariant via "
        "product_config.coa_set.doctrinal_required_flags; the writer "
        "does not need to re-check it. Cross-COA invariants: all "
        "rank values across the emitted set MUST be distinct "
        "integers in product_config.coa_set.ranks; at most one COA "
        "carries each flag listed in "
        "product_config.coa_set.doctrinal_at_most_one_per_flag; no "
        "COA carries two flags from the same entry in "
        "product_config.coa_set.doctrinal_mutually_exclusive_flag_sets.",

        # ---- Doctrinal grounding (principle, not answer) ----
        "Each COA MUST apply a distinct doctrinal pattern drawn from "
        "the COA pattern family in the threat-doctrine artifact this "
        "product consumes. For each COA, _provenance MUST cite (a) "
        "the doctrinal pattern name + the section of the doctrine "
        "artifact where it is described, and (b) the OOB-derived "
        "unit assignment (action force, enabling force(s), reserve, "
        "fires, C2) the COA commits to that pattern. The schema does "
        "NOT name which doctrinal pattern fills which rank, and does "
        "NOT name any unit — the writer makes the picks from threat "
        "doctrine + observed activity + the OE per ATP 2-01.3 ¶6-35. "
        "For offensive COAs the action_force is typically the lead "
        "echelon committed to the decisive task; for defensive COAs "
        "the action_force is typically the formation holding the "
        "decisive terrain — the writer applies the principle to "
        "THIS doctrine artifact's pattern menu.",

        # ---- Distinguishability (do not copy doctrine verbatim) ----
        "Do NOT copy the doctrine artifact verbatim into a COA. The "
        "doctrine artifact describes a doctrinal MENU; a COA is an "
        "INSTANTIATION — the doctrinal pattern applied to THIS "
        "threat formation, THIS AO terrain, THIS phase of THIS "
        "friendly operation. Each COA's statement / "
        "functional_allocation / objectives MUST be specific to "
        "THIS scenario in a way that would NOT survive a search-and-"
        "replace of the threat force name or AO. A COA whose "
        "narrative reads as a paraphrase of the doctrine artifact's "
        "pattern description (no AO-specific terrain, no phase-"
        "specific timing, no OE-specific shift from the artifact's "
        "default behavior) is a writer bug — fail the COA, not the "
        "rule.",

        # ---- Most-deceptive COA structural framework ----
        "When a COA in the set carries most_deceptive=True (a flag "
        "set per product_config.coa_set — the rank entry whose "
        "flag_fields contains 'most_deceptive'), that COA MUST "
        "specify each of the following five structural elements, "
        "sourced from the narrative_doctrine_ref bound to that rank "
        "(or from the base threat-doctrine artifact's deception "
        "chapter if no narrative-doctrine reference is bound) and "
        "adapted to ATP 2-01.3 Step-4 product shape: "
        "(1) FALSE READ — what the threat WANTS the friendly "
        "commander to believe (which axis is decisive, which "
        "formation is the main effort, which timeline). Cite the "
        "friendly decision the false read is targeting. "
        "(2) DECEPTION ACTION — the observable activity the threat "
        "produces to sell the false read (demonstration on the non-"
        "decisive axis, dummy positions, decoy comms, demonstrative "
        "fires, civilian-pattern movement on the masked axis). State "
        "which activity is produced for friendly observation vs "
        "which activity is masked from observation. "
        "(3) MASS — where the real decisive effort actually lands "
        "once the friendly main effort commits to the false read, "
        "and the formation(s) that deliver it. (Unit designations "
        "are derived from OOB and cited in _provenance — the rule "
        "does NOT name the units.) "
        "(4) COMMITMENT TRIGGER — the observable event that releases "
        "the threat from deception phase into commitment phase "
        "(typically: friendly recon confirmation of the phantom main "
        "effort, friendly fires expended against decoy preparations, "
        "friendly reserve committed against the spoof, or a fixed "
        "time horizon driven by threat logistics runtime). State the "
        "trigger as a specific friendly action or DTG window that an "
        "analyst can collect against. "
        "(5) SIGNATURE DISAMBIGUATION — for each of the COA's "
        "observable signatures, state whether it is GENUINE (the "
        "real action is reflected in this signature) or SPOOFED "
        "(the signature is produced for friendly consumption while "
        "the real action is elsewhere). This is the "
        "operationalization of validity-criterion-4 distinguishable "
        "for a deception COA — friendly collection must be ABLE to "
        "detect the spoof, or the COA is not actionable for the "
        "commander.",

        # ---- Distinguishability hard rule (ATP 2-01.3 ¶6-34 #4) ----
        "Each COA's distinguishing_characteristics MUST call out at "
        "least one observable signature (force composition / axis / "
        "timing / ammunition class / preparation indicator) that "
        "lets friendly collection disambiguate this COA from each of "
        "the other COAs in the set. For any COA carrying "
        "most_deceptive=True, distinguishing_characteristics MUST "
        "ADDITIONALLY identify, per signature, whether the signature "
        "is genuine or spoofed (per element 5 of the most-deceptive "
        "structural framework above).",

        # ---- Probability-rationale specifics ----
        "EVERY COA's probability_rationale follows the HARD_RULES "
        "ICD-203 contract: vocabulary word from the seven-level "
        "scale, reasoning chain, explicit likelihood-axis comparison "
        "to every other COA in the set. No percentages unless "
        "algorithmically computed. No publication or section "
        "references. For any COA carrying most_dangerous=True, "
        "ADDITIONALLY articulate why the COA is most dangerous TO "
        "FRIENDLY MISSION ACCOMPLISHMENT in THIS phase of THIS "
        "operation (not merely why it would be costly to friendly "
        "forces in isolation) — but the danger framing is "
        "additive, NOT a substitute for the likelihood-axis "
        "comparison. For any COA carrying most_deceptive=True, the "
        "same ICD-203 contract applies; the five-element deception "
        "worksheet (FALSE READ / DECEPTION ACTION / MASS / "
        "COMMITMENT TRIGGER / SIGNATURE DISAMBIGUATION) is owned "
        "by the structural fields — elements 1-4 by statement.how, "
        "element 5 by distinguishing_characteristics — and does NOT "
        "appear in probability_rationale.",

        # ---- HVT consistency ----
        "Per-COA HVT list MUST cover at least the warfighting "
        "functions the COA actually employs — a COA whose "
        "functional_allocation populates fires-related roles "
        "(support_by_fires, main_effort fires) but emits no fires-"
        "class HVTs is internally inconsistent. For any COA "
        "carrying most_deceptive=True, the HVT list MUST include "
        "the C2 + signal + ISR nodes the deception depends on (loss "
        "of those nodes collapses the spoof) — derived from OOB, "
        "cited in _provenance, NOT named in this rule.",

        # ---- Downstream coupling ----
        "sitemp_artifact_id is OPTIONAL (downstream artifact). Do "
        "not flag its absence as a gap; do not invent an id to "
        "fill it.",

        # ---- Provenance ----
        "Every analytical claim cites source in _provenance — at "
        "the COA level (which doctrinal pattern from which doctrine "
        "artifact + which OOB rows + which recent-activity entries "
        "grounded this COA) AND at the per-HVT-row level (which OOB "
        "row or target-catalog entry the HVT name resolves to).",
        PROVENANCE_HARD_RULE,
    ],

    "data_sources": [
        "Threat picture (PRIMARY — merges OPORD-derived threat-"
        "disposition rows + Road-to-War vectors): get_oob(), "
        "list_targets()",
        "Threat doctrine (REQUIRED — base reference for COA pattern "
        "selection across all ranks): get_project_doc(tag=...). The "
        "specific doctrine artifact bound to a given exercise (e.g., "
        "'DonovianDoctrine' for IDX 26) is loaded via "
        "consumes_artifacts; the schema rule is that COAs "
        "instantiate doctrinal patterns drawn from the base threat-"
        "doctrine artifact's COA pattern family.",
        "Narrative-doctrine references (CONDITIONAL — additional "
        "lens applied per-rank when "
        "product_config.coa_set.ranks[*].narrative_doctrine_ref is "
        "non-None): get_project_doc(tag=<narrative_doctrine_ref>). "
        "The canonical example is a deception-doctrine artifact "
        "(e.g., 'SunTzuOPFOR') bound to the most_deceptive rank, "
        "supplying the five-element deception worksheet. The schema "
        "does NOT prescribe which artifact is bound to which rank — "
        "that is per-exercise config.",
        "Recent activity: get_recent_intel(window_hours=24)",
        "Terrain: get_terrain()",
        "Latest SITEMPs (per-COA): list_project_docs(filter={type:'SITEMP'})",
        "Latest Threat Overlay: list_project_docs(filter={type:'Threat Overlay'}) "
        "then get_project_doc",
        "MCOO: list_project_docs(filter={type:'MCOO'})",
        "Operations overlay control measures (AO / boundaries / "
        "phase lines / axes / NAIs / TAIs / engagement areas / "
        "objectives — threat COA narrative geometry): "
        "get_spatial_overlay()",
        "Phased concept of operations (threat adapts per friendly "
        "phase): get_phases() — current phase + decisive point + "
        "phase objectives",
        "OPORD scheme: get_project_doc(tag='OPORD')",
        "Latest FRAGO: list_project_docs(filter={type:'FRAGO'})",
        "Prior Threat COA Statement (regen): "
        "list_project_docs(filter={type:'Threat COA Statement'})",
    ],

    "post_emit_summary": "artifact_id, COA count, ML one-liner, MD one-liner",
}
