"""OE Definition — IPOE Step 1 — ATP 2-01.3 Ch. 3.

Doctrine source: ATP 2-01.3 Chapter 3 (paras 3-1 – 3-25, Figs 3-1 and 3-2),
with the operational-variable lens extended per FM 3-0 paras 1-125 – 1-126
(PMESII-PT 8-lens) and the mission-variable lens per FM 6-0 / FM 3-0 para
1-126 (METT-TC). ATP 2-01.3 does not publish an acronym for this product
type; the registry key is "Operational Environment Definition" (full doctrinal name).

This is the FIRST product in any IPOE analytical chain. Every downstream
IPOE product (MCOO, TEM, WEM, CCA, Threat Overlay, SITEMP, Threat COA Statement, threat family, etc.)
cites the OE Definition's AO, AOI, and significant-characteristics list as
its scoping input. Without an OE Definition, downstream products have to
re-derive scope from the OPORD on every cycle.

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
    "name": "Operational Environment Definition",
    "output_format": "docx",
    "shape": "structured",
    "doctrine": {
        "purpose": (
            "Step-1 IPOE output: identify for further analysis the significant "
            "characteristics of the OE that may influence friendly and threat "
            "COAs and command decisions, and the physical space the mission "
            "will occupy. Captures AO + AOI definitions, significant "
            "characteristics list, mission variables (METT-TC), operational "
            "variables (PMESII-PT 8-lens), and a commander-facing OE summary. "
            "Briefed to the commander before Step 2 begins." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Substeps: (a) Identify limits of the AO, (b) Identify limits of "
            "the AOI, (c) Identify significant characteristics for further "
            "analysis, (d) Evaluate current operations and intel holdings to "
            "determine information gaps, (e) Initiate processes to acquire "
            "information needed to complete IPOE."
        ),
    },
    # OE Definition is the FIRST product in the IPOE chain — it consumes no
    # prior IPOE artifacts. Initial scope comes from the OPORD + the
    # environmental/civil/terrain primitives. Downstream products consume
    # the OE Definition.
    # Step 1 IPOE. Rollups (OSIR / HUMINTSUM) carry the cumulative civic
    # baseline; atomic HUMINT IIRs + Tactical OSINT Tippers carry
    # current-cycle civic events / source updates.
    "consumes_artifacts": ["OSIR", "HUMINTSUM"],
    # BLUF (issue #176): the commander reads the summary first.
    "paragraph_render_order": ["oe_summary"],
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "phase":              {**HEADER_PHASE, "required": False,
                                "guidance": "OPORD phase if specified; optional for an initial OE Definition that precedes phasing"},
        # WRITER-INVOLVEMENT LAW (2026-07-23): a verbatim 1:1 copy of
        # world-model content is MECHANICAL — the mission is a task
        # clause; the engine resolves value + provenance; no model
        # runs. (Was source:"analytical" over a whole-document dump —
        # the writer fabricated mission content twice.)
        "mission_statement":  {"source": "clause:task:V Corps defeats",
                                "view": "header",
                                "required": True, "provenance_required": True,
                                "render_label": "Mission Statement",
                                "guidance": (
                                    "OPORD mission statement — engine-"
                                    "resolved verbatim from the world "
                                    "model's task clause."
                                )},
        "commander":          {"source": "session", "view": "header",
                                "required": False,
                                "render_label": "Commander",
                                "guidance": "preparing unit commander; pulled from OPORD header when present"},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        # --------------------------------------------------------------
        # Substep (a) — Identify the limits of the commander's AO
        # paras 3-4 – 3-5, Fig 3-2
        # `ao_definition` (paragraph) carries the structured AO scope;
        # `header.area_of_operations` carries the AO designator label.
        # --------------------------------------------------------------
        {"name": "ao_definition",
         "view": "published",
         "shape": "dict",
         "render_label": "Area of Operations (AO)",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Anoperational area defined by a commander for the "
             "land and maritime force commander to accomplish their missions "
             "and protect their forces."
             "external boundary delineates adjacent unit AOs; includes "
             "subordinate AOs (contiguous or noncontiguous). Cite OPORD "
             "operations overlay / Annex C / FRAGO in _provenance."
         ),
         "subfields": ["designator", "external_boundary", "subordinate_aos",
                        "adjacent_units", "contiguity", "political_or_civil_constraints"],
         "subfield_guidance": {
             "designator":     "AO name/designator (e.g., 'AO ALPHA-NORTH', 'AO PALADIN'). Pull verbatim from OPORD Annex C operations overlay.",
             "external_boundary": "External boundary description — perimeter trace by phase line / grid line / terrain feature / MGRS polygon. Cite the operations-overlay graphic.",
             "subordinate_aos": "Subordinate-unit AOs assigned within this AO (the AO can be subdivided as needed). List by designator + assigned unit. Use 'NSTR' if no subordinate AOs are yet assigned.",
             "adjacent_units": "Units holding adjacent AOs along the external boundary (north / south / east / west). Pull from OPORD Annex C operations overlay or higher-headquarters OPORD.",
             "contiguity":     "Doctrinal posture — contiguous or noncontiguous.subordinate AOs may be contiguous OR noncontiguous.",
             "political_or_civil_constraints": "the AO may be impacted due to political boundaries and/or other civil considerations. List any constraint (international border restriction, ROE-driven exclusion zone, host-nation civilian-control area) that shapes the AO. Use 'NSTR' when none.",
         },
         # 2026-07-23 audit: the AO designator is the drawn graphic's
         # name — verbatim, engine-resolved (writer-involvement law);
         # the framing subfields ground on the AO graphics + the
         # assigned-area/task clauses (doc-stated in OPORD 1.b).
         "subfield_sources": {
             "designator": "graphic:area_of_operations:name",
         },
         "depends_on": ["map:state", "clauses:episodic"],
         "clause_scope": {"kinds": ["state", "task"]}},
        # --------------------------------------------------------------
        # Substep (b) — Identify the limits of the commander's AOI
        # paras 3-6 – 3-9
        # --------------------------------------------------------------
        {"name": "area_of_interest",
         "view": "published",
         "shape": "dict",
         "render_label": "Area of Interest (AOI)",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "That area of concern to the commander, including the "
             "area of influence, areas adjacent to it, and extending into "
             "enemy territory.AOI also "
             "includes areas occupied by threat forces who could jeopardize "
             "mission accomplishment; normally LARGER than the area of "
             "influence; may be irregular in shape or noncontiguous. Time "
             "limits are based on threat mobility AND time needed to "
             "accomplish the friendly mission . Cite intel-staff "
             "estimate basis in _provenance."
         ),
         "subfields": ["geographic_extent", "ground_aoi", "air_aoi",
                        "subterranean_aoi", "maritime_aoi", "space_aoi",
                        "cyberspace_aoi", "temporal_extent_hours",
                        "temporal_extent_basis", "neutral_territory_inclusion",
                        "rationale"],
         "subfield_guidance": {
             "geographic_extent": "Outer perimeter of the AOI relative to the AO — e.g., '50 km beyond external boundary along threat mobility corridors; full enemy operational depth east of PL RED'. Include direction-of-interest weighting.",
             "ground_aoi":       "Ground AOI extent. Per-domain decomposition supports the holistic overlay treatment doctrine recommends. Use 'NSTR' if not separately scoped.",
             "air_aoi":          "Air AOI extent — typically extends well beyond ground AOI for ADA/CAS/SEAD scoping. Cite air-component coordination.",
             "subterranean_aoi": "Subterranean AOI when subterranean threat is in scope. Use 'NSTR' when none.",
             "maritime_aoi":     "Maritime AOI when coastal / riverine operations are in scope. Use 'NSTR' when none.",
             "space_aoi":        "Space AOI for threat space capabilities affecting the AO. Use 'NSTR' when none.",
             "cyberspace_aoi":   "Cyberspace AOI —threat cyber actors outside the geographic AO who can affect friendly operations across multiple domains.",
             "temporal_extent_hours": "AOI time window in hours.Computed as the longer of (threat mobility into the AO) and (time needed to accomplish the friendly mission).",
             "temporal_extent_basis": "Doctrinal basis for the time window — e.g., 'mission duration estimate H+72', 'threat reinforcement window of 48h from corps reserve at MGRS X', 'phase 2 duration per OPORD'.",
             "neutral_territory_inclusion": "Neutral-terraincountries included in the AOI when political decisions or population support to threat forces in those countries can influence the mission. List each included neutral country with brief rationale, or 'NSTR'.",
             "rationale":        "Why these AOI boundaries — what is in the AOI that is NOT in the AO and why it must be tracked.",
         },
         # 2026-07-23 audit: the AOI is DOC-STATED (OPORD 1.a + Annex
         # B 1.a, both minted as clauses); the per-domain decomposition
         # and temporal basis are the analytical residue, grounded on
         # those clauses + the AOI graphic + the anchors.
         "depends_on": ["map:state", "clauses:episodic", "anchors"],
         "clause_scope": {"kinds": ["state", "task"]}},
        # --------------------------------------------------------------
        # Substep (c) — Identify significant characteristics
        # paras 3-10 – 3-13
        # --------------------------------------------------------------
        {"name": "significant_characteristics",
         "view": "published",
         "shape": "list_of_dicts",
         "render_sectioned": True,
         "render_label": "Significant Characteristics",
         "required": True,
         "guidance": (
             "Thefocused list of OE "
             "characteristics that materially affect mission accomplishment "
             "and command decisions. This list FOCUSES IPOE — it determines "
             "the time/resources the intelligence staff commits to detailed "
             "analysis during Step 2. Each entry names ONE characteristic "
             "with its category, brief description, mission relevance, and "
             "the downstream IPOE product that will analyze it. Per para "
             "3-12, characteristics include but are not limited to: terrain "
             "+ weather, population demographics, political/socioeconomic "
             "factors, infrastructure (transportation / telecommunications), "
             "ROE / legal restrictions, threat force capabilities."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "ID",
              "guidance": "stable id (e.g., 'SC-01')"},
             {"name": "category", "render_label": "Category",
              "enum": ["terrain", "weather", "enemy",
                        "civil_considerations", "infrastructure",
                        "population_demographics", "political_socioeconomic",
                        "rules_of_engagement_or_legal", "cyberspace",
                        "information_environment", "other"],
              "guidance": (
                  "Maps to which Step-2/Step-3 product "
                  "carries the detailed analysis: terrain → TEM/MCOO; weather → "
                  "WEM; enemy → Threat Overlay / Threat Model / Threat "
                  "Capability Statement; civil_considerations / infrastructure / "
                  "population_demographics / political_socioeconomic → CCA."
              )},
             {"name": "characteristic", "render_label": "Characteristic",
              "provenance_required": True,
              "guidance": "Short doctrinal name (e.g., 'Severely-restricted marshland along PL RED', 'Donovian SA-15b SAM coverage of AO east half', 'Pro-Donovian Russian-speaking enclave in northern AO')."},
             {"name": "description", "render_label": "Description",
              "provenance_required": True,
              "guidance": "One-to-three sentence factual description grounded in retrieved data (terrain / environmental / civil / order of battle / OPORD). Cite source in _provenance."},
             {"name": "mission_relevance", "render_label": "Mission Relevance",
              "provenance_required": True,
              "guidance": "Why this characteristic is SIGNIFICANT — how it influences friendly COAs, threat COAs, or command decisions. This is the 'so what'. Characteristics that do not influence the operation are intentionally EXCLUDED."},
             {"name": "downstream_product", "render_label": "Downstream Analysis Product",
              "enum": ["TEM", "MCOO", "WEM", "CCA", "Threat Overlay", "Threat Model",
                        "Threat Capability Statement",
                        "SITEMP", "Threat COA Statement", "HVTL", "HPTL"],
              "guidance": "Which downstream IPOE / targeting product will carry the detailed analysis of this characteristic (per the IPOE chain). Drives the analyst's build order from Step 2 onward."}],
         "depends_on": [
             "entities:civil",
             "weather",
             "entities:units",
             "map:state",
             "clauses:episodic",
         ]},
        # --------------------------------------------------------------
        # Mission variables (METT-TC) per FM 6-0 / FM 3-0 para 1-126
        # The OE Definition records the METT-TC framing the commander
        # and staff will refine throughout the operation.
        # --------------------------------------------------------------
        {"name": "mission_variables",
         "view": "published",
         "shape": "dict",
         "render_label": "Mission Variables (METT-TC)",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Themission variables — "
             "Mission, Enemy, Terrain and weather, Troops and support "
             "available, Time available, Civil considerations (with the "
             "informational considerations parenthetical 'I'). Each subfield is a short narrative — one "
             "or two paragraphs framing what the staff knows now about "
             "that variable. Pull from OPORD + most recent published "
             "artifacts in the project; OE Definition is BEFORE Step 2 "
             "detailed analysis, so depth here is initial framing not "
             "exhaustive analysis."
         ),
         "subfields": ["mission", "enemy", "terrain_and_weather",
                        "troops_and_support_available", "time_available",
                        "civil_considerations"],
         "subfield_guidance": {
             "mission":                       "Friendly mission as stated in the OPORD (purpose + tasks). Pull verbatim from OPORD para 2 when available.",
             "enemy":                         "Composition, disposition, strength of known and likely threats (includes regular, irregular, hybrid, and non-state actors). Initial framing only — detailed analysis lives in the Threat Overlay / Threat Model / Threat Capability Statement.",
             "terrain_and_weather":           "Initial terrain + weather framing.Detailed analysis lives in TEM/MCOO/WEM. Reference the terrain primitives and SWO environmental record as factual base.",
             "troops_and_support_available":  "Friendly force composition, attached/detached units, support available (joint, multinational, host-nation). Pull from OPORD task organization.",
             "time_available":                "Time available to plan, prepare, execute. Includes any commander-imposed timeline or higher-headquarters time constraint.",
             "civil_considerations":          "ASCOPE framing of civil environment:Areas, Structures, Capabilities, Organizations, People, Events. Detailed analysis lives in the CCA. The informational-considerations (I) parenthetical attaches across all six METT-TC variables — surface it here when information operations materially affect the mission.",
         },
         # 2026-07-23 audit: METT-TC facts are DOC-STATED + world-model
         # held. This field previously saw ONLY map:state graphics and
         # fabricated whole friendly units (502nd/506th Infantry) —
         # scoping gaps invite fabrication. The mission subfield is a
         # verbatim clause copy: engine-resolved, no model.
         "subfield_sources": {
             "mission": "clause:task:V Corps defeats",
         },
         "depends_on": [
             "entities:units",
             "entities:civil",
             "weather",
             "anchors",
             "clauses:episodic",
             "map:state",
         ]},
        # --------------------------------------------------------------
        # Operational variables (PMESII-PT 8-lens) per FM 3-0 para 1-125
        # --------------------------------------------------------------
        {"name": "operational_variables",
         "view": "published",
         "shape": "dict",
         "render_label": "Operational Variables (PMESII-PT)",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Theeight interrelated "
             "operational variables — Political, Military, Economic, Social, "
             "Information, Infrastructure, Physical environment, Time. "
             "Each subfield is a short narrative framing the AOI in that "
             "lens. The operational variables help leaders understand the "
             "land domain and its interrelationships with information, "
             "relevant actors, and capabilities in the other domains. The "
             "8-lens treatment is intentionally broader than METT-TC — "
             "it captures the systems context inside which the mission sits."
         ),
         "subfields": ["political", "military", "economic", "social",
                        "information", "infrastructure", "physical_environment",
                        "time"],
         "subfield_guidance": {
             "political":             "Political lens — governance, factions, rule of law, host-nation political dynamics, international constraints. Includes clans, tribes, religious organizations, corruption, sex (male or female), age, cultural groups, ethnicity where these are politically organized.",
             "military":              "Military lens — friendly + threat + host-nation + multinational + non-state armed actors. Strategic context of the threat force. Distinct from the METT-TC 'enemy' framing in scope: military lens covers ALL armed actors in the OE, not just the principal threat.",
             "economic":              "Economic lens — local economy, key industries, trade flows, financial infrastructure, illicit economy, sanctions/embargoes affecting the OE.",
             "social":                "Social lens — population demographics, ethnic and religious composition, sociocultural fault lines, displaced-persons situation, public attitudes toward friendly forces.",
             "information":           "Information lens — local media reach, social media penetration, threat IO/propaganda capabilities, friendly-MISO coverage. Includes sociocultural databases the staff can draw on.",
             "infrastructure":        "Infrastructure lens — transportation network, telecommunications, electric grid, water/sewer, health facilities, port/airfield capacity.",
             "physical_environment":  "Physical environment lens — terrain, weather, climate, hydrology, vegetation, geology over the AOI. Sets the scope that TEM / MCOO / WEM will analyze in detail in Step 2.",
             "time":                  "Time lens — temporal context: relevant historical anniversaries, seasonal cycles, planting/harvest, religious calendar, election cycles, threat operational tempo. The 'PT' in PMESII-PT.",
         },
         # 2026-07-23 audit: this field had NO depends_on — the writer
         # saw nothing and fabricated its provenance outright. The
         # 8-lens survey grounds on the full scoped picture.
         "depends_on": [
             "entities:units",
             "entities:civil",
             "weather",
             "clauses:episodic",
             "map:state",
         ]},
        # --------------------------------------------------------------
        # Substep (d) — Evaluate current operations + intel holdings,
        # determine additional information needed
        # paras 3-24 – 3-25
        # --------------------------------------------------------------
        {"name": "information_gaps",
         "view": "published",
         "shape": "list_of_dicts",
         "render_sectioned": True,
         "render_label": "Information Gaps",
         "required": True,
         "guidance": (
             "information not in command or higher-"
             "headquarters data files that is needed to complete IPOE. "
             "Identified early, prioritized against the commander's initial "
             "guidance. Each gap carries a proposed handling (RFI / RFC / "
             "working assumption) and the assumption text when one is to be "
             "used in place of the missing information."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "Gap ID",
              "guidance": "stable id (e.g., 'GAP-01')"},
             {"name": "characteristic_ref", "render_label": "Characteristic",
              "guidance": "significant_characteristics[].id this gap attaches to, or '—' if free-standing"},
             {"name": "information_needed", "render_label": "Information Needed",
              "provenance_required": True,
              "guidance": "What is missing — phrased as an answerable PIR-style question."},
             {"name": "handling", "render_label": "Handling",
              "enum": ["request_for_information", "request_for_collection",
                        "working_assumption", "deferred"],
              "guidance": "RFI to higher-HQ data files, RFC to the collection plan, a working assumption with explicit rationale, or explicitly deferred until later."},
             {"name": "assumption_text", "render_label": "Assumption (if handling = working_assumption)",
              "required": False,
              "guidance": "reasonable assumption used in place of the missing answer. Required only when handling == 'working_assumption'. The staff must explain to the commander how the assumption was arrived at."},
             {"name": "priority", "render_label": "Priority",
              "enum": ["high", "medium", "low"],
              "guidance": "prioritized against the commander's initial guidance and intent for intelligence collection."}],
         # 2026-07-23 audit: gaps ground on the CCIR/PIR/assumption
         # clauses (doc-stated in Annex B) and attach to the sibling
         # characteristics list (wave ordering).
         "depends_on": ["clauses:episodic",
                        "significant_characteristics"]},
        # --------------------------------------------------------------
        # OE summary — commander-facing brief
        # paras 3-2 (so what) + 3-23 (briefing example)
        # --------------------------------------------------------------
        {"name": "oe_summary",
         "view": "published",
         "shape": "string",
         "render_label": "OE Summary (Commander's Brief)",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Concisecommander-facing brief on the AO's "
             "significant characteristics. SHOULD NOT include MCOO or "
             "threat-template specifics (those belong to Steps 2 and 3). "
             "Three to five paragraphs synthesizing AO + AOI definition, "
             "the focused significant-characteristics list, the principal "
             "operational/mission-variable findings, the most consequential "
             "information gaps and how the staff proposes to handle them, "
             "and the next-product recommendation (typically MCOO for "
             "terrain-driven scoping, or CCA for civil-driven scoping). "
             "Read by the commander before Step 2 begins; sets the "
             "analytical focus for the rest of IPOE."
         ),
         # 2026-07-23 audit: the summary synthesizes the sibling
         # fields — sequenced after all of them (prior-fields context).
         "depends_on": ["ao_definition", "area_of_interest",
                        "significant_characteristics",
                        "mission_variables", "operational_variables",
                        "information_gaps"]}],
    "subtleties": [
        "OE Definition is Step 1 of the IPOE process —the FIRST product in any IPOE analytical chain. Every downstream product (MCOO, TEM, WEM, CCA, Threat Overlay, Threat Model, Threat Capability Statement, SITEMP, Threat COA Statement, HVTL, HPTL) consumes the AO, AOI, and significant-characteristics list defined here.",
        "TheOE Definition exists to FOCUS subsequent IPOE work. Characteristics that do not influence the operation are intentionally EXCLUDED so the staff doesn't waste collection capacity on irrelevant aspects of the OE.",
        "AO definition is doctrinally tied to the OPORD operations overlay — pull the external boundary VERBATIM from the OPORD or higher-HQ overlay; do not redraw it.",
        "AOI definition is normally LARGER than the area of influence and extends into threat territory. Time is a primary AOI consideration: scope the AOI to encompass everything the threat can bring to bear in the time it takes friendly forces to accomplish the mission.",
        "The AOI may be subdivided by domain (ground / air / subterranean / maritime / space / cyberspace). Surface each domain in its own subfield; use 'NSTR' for domains not in scope.",
        "Neutral-terrain countries are included in the AOI when political decisions or supportive population segments in those countries can influence mission accomplishment.",
        "Significant-characteristics list is the central output. Each entry names its downstream product so the analyst knows where the detailed analysis will live. Per the IPOE chain: terrain → TEM/MCOO; weather → WEM; enemy → Threat Overlay/Threat Model/Threat Capability Statement; civil/infrastructure/demographics/political → CCA.",
        "Mission variables (METT-TC) frame the immediate mission context. The informational-considerations parenthetical 'I' in METT-TC (I) attaches across ALL six variables — it is not a seventh independent variable.",
        "Operational variables (PMESII-PT) are the8-lens framing of the broader OE. The'PT' suffix is two variables: Physical environment AND Time. Eight variables total, not six plus a hyphen.",
        "The commander brief should be CONCISE and stay at Step 1 scope. Do NOT roll in MCOO mobility classifications or threat-template specifics — those belong to the briefings for Steps 2 and 3.",
        "Theinformation-gap list and the request-for-information / request-for-collection plan are doctrinally part of Step 1. Gaps that arrive in this product are gaps the staff identified DURING scoping; new gaps that emerge during Step 2+ analysis are captured in that step's products, not back into the OE Definition.",
        "Per IDX 26: every analytical claim cites its source in _provenance — AO boundary cites OPORD operations overlay, AOI scope cites intel-staff estimate, each significant characteristic cites the retrieved terrain / environmental / civil / order-of-battle datum, each METT-TC + PMESII-PT subfield cites the source artifacts behind its framing."],
    "hard_rules": [
        "Substep (a) AO definition fields (designator, external_boundary) must cite OPORD operations overlay / Annex C / FRAGO in _provenance. Do NOT invent an AO boundary.",
        "Substep (b) AOI temporal_extent_hours MUST be computed against (threat mobility into the AO) and (friendly mission duration),. State the basis in temporal_extent_basis.",
        "Significant characteristics MUST each carry a `downstream_product` value identifying which Step-2/Step-3 IPOE product will analyze the characteristic in detail. A characteristic with no downstream owner is not significant by definition.",
        "Mission variables MUST include all six METT-TC subfields. A METT-TC framing missing any of the six variables is invalid.",
        "Operational variables MUST include all eight PMESII-PT subfields. A PMESII-PT framing missing any variable is invalid.",
        "Per para 3-23, oe_summary MUST be concise (3–5 paragraphs) and MUST NOT include MCOO mobility classifications, threat-template specifics, or other Step-2/Step-3 content. Those products carry their own briefs.",
        "Information gaps with handling == 'working_assumption' MUST populate assumption_text. Per para 3-24 the staff must explain to the commander how each assumption was arrived at.",
        "OE Definition consumes NO upstream IPOE artifacts (it is Step 1). Do NOT cite MCOO/TEM/WEM/CCA/Threat Overlay/SITEMP/Threat COA Statement artifact_ids in this product — those don't exist yet.",
        "Per IDX 26: every characteristic, every METT-TC subfield, every PMESII-PT subfield, every information gap cites its source in _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Mission + AO + commander's intent: get_project_doc(tag='OPORD')",
        "Initial environmental scope (terrain extent, climatology): get_environmental(date=<canonical_now>)",
        "Initial terrain primitives over the AO: get_terrain()",
        "Civil baseline (population, infrastructure, ASCOPE primitives — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Known threat picture for the 'enemy' significant-characteristic seed (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob(), list_targets()",
        "Operations overlay control measures + sustainment kinds (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ + BSA/DSA/LSA/FLE/APOD/SPOD + MSR/ASR + LRP/ATP/ROM/MTF/CCP/MCP/Class III/V/VIII — civil + sustainment block in the OE definition): get_spatial_overlay()",
        "Phased concept of operations (phased operational environment narrative): get_phases() — current phase + decisive point + phase objectives",
        "Higher-HQ guidance and recent FRAGOs that re-scope the AO/AOI: list_project_docs(filter={type:'FRAGO'})",
        "Annex L (intelligence): get_project_doc(tag='ANNEX_L_INTEL')",
        "Prior OE Definition for refresh / regen: list_project_docs(filter={type:'OE Definition'}) then get_project_doc"],
    "post_emit_summary": "artifact_id, AO designator, AOI extent (geographic + hours), count of significant characteristics, count of information gaps with handling distribution, doctrinal-next recommendation",
}
