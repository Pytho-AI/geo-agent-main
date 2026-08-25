"""TSA — Target System Analysis — JP 3-60 Ch. III §3.b.(4) + Fig III-3 / III-4.

Target System Analysis is the foundational military intelligence process of
system-level target development that identifies an adversary's critical
capabilities, evaluates target system elements for criticality and vulnerability,
and produces the system-level rationale that feeds HVT / HPT identification
downstream.

JP 3-60 glossary (p. III-7 / p. GL-9):
    "Target system analysis. An all-source examination of potential target
    systems to determine relevance to stated objectives, military importance,
    and priority of attack. Also called TSA. (DoD Dictionary. Source: JP 3-60)"

TSA is distinct from:
  - HVTL (FM 3-60 App. C / ATP 2-01.3 Ch. 5–6) — the downstream list of
    individual high-value targets the system analysis feeds.
  - TMP (CJCSI 3505.01E para 4.d.(1)) — per-aimpoint mensuration sheet for
    a single target; TSA is the upstream system-level workpaper.
  - TSDA (JP 3-60 glossary) — the post-strike target-system damage assessment
    counterpart to pre-strike TSA.

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

# JP 3-60 Ch. III §3.b.(4)(a) — examples enumerated in doctrine. Acts as a
# soft hint to the analyst; not a hard enum because TSA is performed against
# any target system relevant to the operational effort.
TARGET_SYSTEM_CATEGORY_EXAMPLES = [
    "command_and_control",
    "ground_forces_and_facilities",
    "infrastructure",
    "corporate_economic_and_financial",
    "strategic_industry",
    "integrated_air_defense",
    "ballistic_missile_system",
    "logistics_network",
    "insurgent_or_terrorist_network",
]

# JP 3-60 Fig III-4 — criticality factors (the four that contribute to a
# target's criticality per §3.b.(4)(c)1).
CRITICALITY_FACTOR_ENUM = ["value", "depth", "recuperation", "capacity"]

# JP 3-60 Fig III-4 — vulnerability characteristics per §3.b.(4)(c)2.
VULNERABILITY_CHARACTERISTIC_ENUM = [
    "cushion",
    "reserves",
    "dispersion",
    "mobility",
    "countermeasures",
    "physical_characteristics",
    "nonphysical_characteristics",
]

# Reaction the adversary takes when a critical node is degraded — matches
# the HVTL workpaper impact_of_loss vocabulary (FM 3-60 B-29 SUBSTITUTE /
# BRANCH / SEQUEL / ACCEPT) so the system-level call feeds the per-HVT call.
SYSTEM_REACTION_ENUM = ["substitute", "branch", "sequel", "accept"]

SPEC = {
    "name": "TSA",
    "output_format": "docx",
    "shape": "structured",
    "doctrine": {
        "purpose": (
            "All-source examination of an adversary target system "
            "(integrated air defense, command-and-control network, logistics "
            "network, strategic industry, etc.) to determine its relevance "
            "to JFC objectives, identify its constituent elements and critical "
            "nodes, evaluate criticality + vulnerability of each, and produce "
            "system-level target nominations that feed HVT identification — "
            "identify vulnerabilities in adversary systems that lead to the "
            "discovery of HVTs and HPTs. Published artifact is the pre-strike "
            "system-level workpaper; the downstream HVTL surfaces only the "
            "per-target rows that fall out of this analysis. TSA is "
            "system-level — it does NOT replace per-target development "
            "(TMP / entity-level target development)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Single target system per artifact (one TSA = one adversary system). "
            "Components ordered by criticality_rank ascending (1 = most critical); "
            "critical nodes within each component ordered by criticality_rank "
            "ascending; recommended nominations ordered by criticality_rank "
            "ascending."
        ),
    },
    "consumes_artifacts": ["MCOO", "Threat Overlay", "SITEMP", "Threat COA Statement"],
    "produces_inputs_for": ["HVTL"],
    "header_fields": {
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "target_system_name": {
            "source": "analytical", "view": "header", "required": True,
            "provenance_required": True,
            "render_label": "Target System",
            "depends_on": ["artifact.SITEMP"],
            "guidance": (
                "Name of the adversary target system under analysis "
                "Examples: 'Donovian Integrated Air "
                "Defense System — South-Eastern Estonia', '11th Mech Brigade "
                "Command-and-Control Network', 'Petroleum, Oils, and Lubricants "
                "Distribution Network — Pskov Oblast'. Cite OOB / SITEMP / "
                "Threat Overlay artifact_id in _provenance."
            ),
        },
        "target_system_category": {
            "source": "analytical", "view": "header", "required": True,
            "provenance_required": True,
            "render_label": "Target System Category",
            "guidance": (
                "Category from the canonical examples list."
                "Soft-vocabulary list — extend when an actual system does not "
                "map cleanly to one of the published examples, but cite the "
                "rationale in _provenance."
            ),
            "enum_examples": TARGET_SYSTEM_CATEGORY_EXAMPLES,
        },
        "adversary":          {
            "source": "session", "view": "header", "required": True,
            "render_label": "Adversary",
            "guidance": (
                "Adversary force or actor whose system is under analysis "
                "(e.g., 'Donovian Northwestern Group of Forces'). Pull from "
                "the order of battle data or latest Threat Overlay artifact_id; cite in _provenance."
            ),
        },
        "objective_supported": {
            "source": "analytical", "view": "header", "required": True,
            "provenance_required": True,
            "render_label": "JFC Objective Supported",
            "guidance": (
                "JFC objective the TSA supports (the"
                "initial step is to evaluate target systems RELEVANT TO the "
                "operational effort). Cite OPORD / FRAGO paragraph in "
                "_provenance — e.g. 'OPORD §3.a.(2) — defeat enemy IADS to "
                "enable corps-level air operations south of PL RED'."
            ),
        },
        "mcoo_artifact_id":   {"source": "ref:MCOO", "view": "internal",
                                "required": False,
                                "depends_on": ["artifact.MCOO"],
                                "render_label": "MCOO Reference"},
        "threat_overlay_artifact_id": {"source": "ref:Threat Overlay", "view": "internal",
                                          "required": False,
                                          "depends_on": ["artifact.Threat Overlay"],
                                          "render_label": "Threat Overlay Reference"},
        "sitemp_artifact_id": {"source": "ref:SITEMP", "view": "internal",
                                "required": False,
                                "depends_on": ["artifact.SITEMP"],
                                "render_label": "SITEMP Reference"},
        "threat_coa_statement_artifact_id":   {"source": "ref:Threat COA Statement", "view": "internal",
                                "required": False,
                                "depends_on": ["artifact.Threat COA Statement"],
                                "render_label": "Threat COA Statement Reference"},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        # --- §3.b.(4)(a) Target system identification + scope -----------------
        {
            "name": "system_identification",
            "view": "published",
            "shape": "dict",
            "render_label": "Target System Identification",
            "required": True,
            "provenance_required": True,
            "guidance": (
                "identify the target system, its "
                "function in the adversary's operations, and why it is "
                "relevant to the JFC objective named in the header."
            ),
            "subfields": [
                "system_function",
                "relevance_to_objective",
                "geographic_extent_mgrs",
                "supporting_intelligence",
            ],
            "subfield_guidance": {
                "system_function": (
                    "What the target system does for the adversary — e.g., "
                    "'provides layered air defense from S-300V4 strategic "
                    "SAMs down to ZSU-23-4 point-defense for the entire "
                    "South-Eastern Estonia AO, coordinated via 5N63S battle-"
                    "management radars'. One paragraph."
                ),
                "relevance_to_objective": (
                    "Why engaging this system contributes to the JFC "
                    "objective named in objective_supported ."
                ),
                "geographic_extent_mgrs": (
                    "Bounding box or list of MGRS grids that delimit the "
                    "system's physical footprint. Cite SITEMP / GEOINT "
                    "source per JIPOE."
                ),
                "supporting_intelligence": (
                    "All-source basis — list source disciplines and report "
                    "IDs (HUMINT / SIGINT / GEOINT / OSINT) — collectionrequirements feeding TSA."
                ),
            },
        },
        # --- §3.b.(4)(b) Target system components / elements -----------------
        {
            "name": "system_components",
            "view": "published",
            "shape": "list_of_dicts",
            "render_label": "Target System Components",
            "required": True,
            "depends_on": [
                "cougaar.get_oob",
                "cougaar.list_targets",
            ],
            "guidance": (
                "Atarget system "
                "component (== target system element) is 'a related group of "
                "entities within a target system that performs or contributes "
                "toward similar functions.' For an integrated air defense "
                "system, components are the functional decomposition: "
                "long-range SAM batteries, short-range/point-defense, "
                "battle-management radars, early-warning radars, C2 nodes, "
                "communications links, logistics support. List every "
                "component the analysis covers — gaps in the decomposition "
                "are coverage gaps in the TSA. "
                "IDENTIFIER DISCIPLINE: every kg_id (unit U-..., target T-...) "
                "referenced in the component's entities list MUST come "
                "VERBATIM from the upstream order of battle or target catalog "
                "payload supplied in this prompt. NEVER invent unit IDs (e.g. "
                "'U-DN-092') or target IDs that are not literally present in "
                "those payloads. If no qualifying entity is in the payload, "
                "describe the entity in free text (no fake kg_id) or omit "
                "the component."
            ),
            "item_subfields": [
                {"name": "component_id", "render_label": "Component ID",
                 "guidance": "Short stable identifier within this TSA, e.g. 'C-1', 'IADS-LR-SAM'. Local to the artifact."},
                {"name": "component_name", "render_label": "Component Name",
                 "guidance": "Functional label — e.g. 'Long-Range Strategic SAM', 'Battle-Management Radar Net', 'Forward Logistics Resupply'."},
                {"name": "function_within_system", "render_label": "Function Within System",
                 "guidance": "What this component does for the larger system."},
                {"name": "entities", "render_label": "Constituent Entities",
                 "shape": "list",
                 "guidance": (
                     "List of specific entities (units / facilities / equipment) "
                     "that make up this component. Reference by kg_id when "
                     "available (e.g. 'U-DA0142 — 1/123 SAM Bn S-300V4 "
                     "battery'); free-text only when no kg entity exists "
                     "(e.g. 'unnamed radio-relay site vic 35V NL 412 887'). "
                     "kg_id MUST be copied verbatim from the order of battle "
                     "or target catalog payload — NEVER invent identifiers like "
                     "U-DN-092 / T-XX-### that are not in those payloads."
                 )},
                {"name": "intradependencies", "render_label": "Intradependencies",
                 "guidance": (
                     "Other components within THIS target system this "
                     "component depends on ("
                     "intradependencies). Reference by component_id."
                 )},
                {"name": "interdependencies", "render_label": "Interdependencies",
                 "guidance": (
                     "External target systems this component depends on "
                     "(interdependencies). Example: "
                     "the SAM component depends on the adversary electric "
                     "power system for fixed-site primary power."
                 )},
                {"name": "criticality_rank", "render_label": "Criticality Rank (1=most critical)",
                 "guidance": (
                     "Analyst rank within this TSA, integer 1..N. Driven by "
                     "the four criticality factorsrecorded in criticality_assessment "
                     "below — value / depth / recuperation / capacity."
                 )},
                {"name": "criticality_assessment", "render_label": "Criticality Assessment",
                 "shape": "dict",
                 "guidance": (
                     "The fourcriticality "
                     "factors. Each subfield is one short paragraph of "
                     "doctrinal analysis with citations in _provenance."
                 ),
                 "subfields": ["value", "depth", "recuperation", "capacity"],
                 "subfield_guidance": {
                     "value": (
                         "Significance to the adversary's target system and to "
                         "friendly mission accomplishment —"
                         "may reflect military, economic, political, "
                         "psychological, informational, environmental, "
                         "cultural, or geographic importance."
                     ),
                     "depth": (
                         "Time between disruption of the component's activity "
                         "and measurable impact on system output per "
                         "Example: 'C2 network disruption "
                         "felt immediately; ammunition production-line "
                         "disruption takes months'."
                     ),
                     "recuperation": (
                         "Time and cost required for the component to regain "
                         "functional capability after disruption per "
                         "Drives reattack timing."
                     ),
                     "capacity": (
                         "Current output AND maximum output per "
                         "For non-industrial components, "
                         "express as operational throughput (sorties / day, "
                         "tons / day, intercepts simultaneous)."
                     ),
                 }},
                {"name": "vulnerability_assessment", "render_label": "Vulnerability Assessment",
                 "shape": "dict",
                 "guidance": (
                     "The vulnerability"
                     "characteristics. Populate the characteristics that "
                     "matter for this component; leave others blank rather "
                     "than fabricate."
                 ),
                 "subfields": [
                     "cushion", "reserves", "dispersion", "mobility",
                     "countermeasures", "physical_characteristics",
                     "nonphysical_characteristics",
                 ],
                 "subfield_guidance": {
                     "cushion": (
                         "Damage / disruption the component can absorb and "
                         "continue to function. "
                         "Industrial: idle plant capacity, substitution of "
                         "parts. Military: redundancy, alternate sites."
                     ),
                     "reserves": (
                         "Stored resources usable when normal supply is "
                         "disrupted. Express as "
                         "percentage when flow rate is estimable."
                     ),
                     "dispersion": (
                         "Geographic or virtual distribution of elements "
                         "More dispersion = harder "
                         "target engagement; may also degrade adversary's "
                         "operational efficiency."
                     ),
                     "mobility": (
                         "Time to shift the component's function from one "
                         "location to another Drives "
                         "perishability of location intelligence."
                     ),
                     "countermeasures": (
                         "Adversary's active and passive measures to "
                         "negate friendly disruption "
                         "— terrain use, camouflage, emission controls, "
                         "active/passive defenses."
                     ),
                     "physical_characteristics": (
                         "Weight, shape, volume, construction, sturdiness "
                         "driving susceptibility to physical effects per "
                         ""
                     ),
                     "nonphysical_characteristics": (
                         "Reliance on cyberspace / EMS that increases or "
                         "mitigates vulnerability "
                         "Relevant for cyber and EW engagement options."
                     ),
                 }},
            ],
        },
        # --- Critical nodes (FM 3-60 nodal analysis; JP 3-60 §3.b.(4)(c)1) ---
        {
            "name": "critical_nodes",
            "view": "published",
            "shape": "list_of_dicts",
            "render_label": "Critical Nodes",
            "required": True,
            "depends_on": [
                "cougaar.get_oob",
                "cougaar.list_targets",
            ],
            "guidance": (
                "'Target development should focus "
                "on identifying the critical nodes of key target systems that "
                "achieve the JFC's objectives.' Nodal"
                "analysis): critical nodes are the specific entities whose "
                "neutralization degrades the system disproportionately. Each "
                "row is a specific entity (NOT a whole component) tied back "
                "to the component it sits in. Critical nodes are the entities "
                "that become HVT nominations in the next section. "
                "IDENTIFIER DISCIPLINE: entity_reference kg_ids MUST come "
                "VERBATIM from the upstream order of battle or target catalog "
                "payload supplied in this prompt. NEVER invent unit IDs (e.g. "
                "'U-DN-092') or target IDs not literally present in those "
                "payloads. If no qualifying entity is in the payload, "
                "describe the entity in free text without a fake kg_id, or "
                "omit the row."
            ),
            "item_subfields": [
                {"name": "node_id", "render_label": "Node ID",
                 "guidance": "Short stable identifier within this TSA, e.g. 'N-1'."},
                {"name": "component_id", "render_label": "Parent Component",
                 "guidance": "References system_components[i].component_id."},
                {"name": "entity_reference", "render_label": "Entity Reference",
                 "guidance": (
                     "Specific entity (unit / facility / equipment) the node "
                     "is. Use kg_id when available (e.g. 'T-DA0173 — S-300V4 "
                     "fire-control radar, 1/123 SAM Bn'); free-text only when "
                     "no kg entity exists. This is the entity that will "
                     "appear on the downstream HVTL. kg_id MUST be copied "
                     "verbatim from the order of battle or target catalog "
                     "payload — NEVER invent identifiers like U-DN-092 / "
                     "T-XX-### that are not in those payloads."
                 )},
                {"name": "location_mgrs", "render_label": "Location (MGRS)",
                 "guidance": "Cite GEOINT source in _provenance."},
                {"name": "node_function", "render_label": "Node Function",
                 "guidance": "What the node specifically does within the parent component."},
                {"name": "criticality_rank", "render_label": "Criticality Rank (1=most critical)",
                 "guidance": "Integer 1..N within the critical_nodes list. Drives nomination ordering."},
                {"name": "criticality_rationale", "render_label": "Criticality Rationale",
                 "guidance": (
                     "One paragraph synthesizing the four criticality factorsas "
                     "they apply to THIS specific entity — why this entity "
                     "is the node that matters, not the rest of the "
                     "component. Cite the factor(s)driving the call."
                 )},
                {"name": "system_reaction_if_neutralized", "render_label": "System Reaction If Neutralized",
                 "enum": SYSTEM_REACTION_ENUM,
                 "guidance": (
                     "Reaction"
                     "preface (vulnerabilities lead to HVT discovery). "
                     "SUBSTITUTE (adversary redirects similar asset), BRANCH "
                     "(alternate plan), SEQUEL (follow-on operations "
                     "constrained), ACCEPT (degradation tolerated). Carries "
                     "forward to the HVTL impact_of_loss field for this entity."
                 )},
                {"name": "expected_system_effect", "render_label": "Expected System-Level Effect",
                 "guidance": (
                     "Quantified effect on the larger target system when this "
                     "node is neutralized, per the metric convention in JP "
                     "(e.g. 'destruction of Critical Node 1 "
                     "will degrade Target A functionality by at least 50 "
                     "percent'). Drives downstream BDA / TSDA criteria."
                 )},
                {"name": "primary_vulnerability", "render_label": "Primary Vulnerability",
                 "enum": VULNERABILITY_CHARACTERISTIC_ENUM,
                 "guidance": (
                     "Which vulnerability characteristicis the "
                     "highest-leverage vulnerability for this node. Drives "
                     "engagement-method recommendation"
                     "(capabilities analysis)."
                 )},
                {"name": "detection_signatures", "render_label": "Detection Signatures",
                 "guidance": (
                     "Multi-INT signatures so collection can find/fix this "
                     "node (mirrors the HVTL workpaper). Atleast "
                     "two of: SIGINT (emitter band + activity pattern), "
                     "GEOINT (visible/IR/SAR appearance), HUMINT (source "
                     "access). Carries forward to HVTL detection_signatures."
                 )},
            ],
        },
        # --- §3.b.(4) preface — recommended target nominations to HVTL ------
        {
            "name": "recommended_nominations",
            "view": "published",
            "shape": "list_of_dicts",
            "render_label": "Recommended Target Nominations",
            "required": True,
            "depends_on": [
                "cougaar.get_oob",
                "cougaar.list_targets",
            ],
            "guidance": (
                "'The purpose of TSA is to "
                "identify vulnerabilities in adversary systems that lead "
                "to the discovery of HVTs and HPTs.' This section is the "
                "explicit handoff — one row per recommended HVT nomination, "
                "referencing the critical node it came from. The downstream "
                "HVTL build"
                "consumes these as its row set for the named threat_coa."
            ),
            "item_subfields": [
                {"name": "nomination_id", "render_label": "Nomination ID",
                 "guidance": "Short stable identifier, e.g. 'NOM-1'."},
                {"name": "node_id", "render_label": "Source Critical Node",
                 "guidance": "References critical_nodes[i].node_id — the analytical chain back to the system."},
                {"name": "entity_reference", "render_label": "Nominated Entity",
                 "guidance": (
                     "kg_id of the specific entity nominated (matches "
                     "critical_nodes[i].entity_reference). kg_id MUST come "
                     "verbatim from the order of battle or target catalog "
                     "payload — NEVER invent identifiers not present in the "
                     "payload."
                 )},
                {"name": "category", "render_label": "Category",
                 "guidance": (
                     "Category the nominated entity falls under (e.g. "
                     "'air_defense_artillery', 'command_and_control'). "
                     "Drives HVTL grouping. Uses TARGET_CATEGORY_ENUM "
                     "from common.py."
                 )},
                {"name": "criticality_rank", "render_label": "Criticality Rank (1=highest priority nomination)",
                 "guidance": "Integer 1..N — drives the order in which downstream HVTL / CARVER processes the nominations."},
                {"name": "justification", "render_label": "Justification (HVTL feed)",
                 "guidance": (
                     "ONE short sentence — why this entity should be on the "
                     "HVTL. Distilled from the critical-node rationale; "
                     "becomes the HVTL Justification cell."
                 )},
                {"name": "engagement_consideration", "render_label": "Engagement Consideration",
                 "guidance": (
                     "Short note on engagement options the system-level "
                     "analysis surfaces (lethal vs. nonlethal; cyber vs. "
                     "kinetic; sequencing constraint with other nominations). "
                     "Informs Phase 3 (capabilities analysis) —not "
                     "weaponeering itself."
                 )},
            ],
        },
        # --- Coverage / gap log -----------------------------------------------
        {
            "name": "intelligence_gaps",
            "view": "published",
            "shape": "list_of_dicts",
            "render_label": "Intelligence Gaps",
            "required": False,
            "guidance": (
                "'Establishing intelligence "
                "collection requirements is critical to the success of "
                "target development.' List the gaps the TSA could not close "
                "with on-hand intelligence so the collection manager can "
                "drive new requirements. Each gap should reference the "
                "component_id or node_id it constrains."
            ),
            "item_subfields": [
                {"name": "gap_id", "render_label": "Gap ID"},
                {"name": "constrains_component_id", "render_label": "Constrains Component",
                 "guidance": "References system_components[i].component_id (optional — gap may be system-wide)."},
                {"name": "constrains_node_id", "render_label": "Constrains Critical Node",
                 "guidance": "References critical_nodes[i].node_id (optional)."},
                {"name": "gap_description", "render_label": "Gap",
                 "guidance": "What is unknown — e.g. 'fire-control radar deployment cycle for 1/123 SAM Bn (used to estimate depth factor for SAM long-range component)'."},
                {"name": "recommended_collection", "render_label": "Recommended Collection",
                 "guidance": "Discipline + tasking recommendation (SIGINT / GEOINT / HUMINT)."},
            ],
        },
    ],
    "subtleties": [
        "'TSA is the foundational military intelligence process of system-level target development that identifies an adversary's critical capabilities.' One TSA per adversary target system — do NOT collapse multiple systems (e.g., IADS + logistics) into a single artifact; produce one TSA per system and let HVTL aggregate downstream.",
        "Hierarchy: target system → component (== element) → entity → target element. TSA owns the upper three layers; per-target development (TMP / entity-level target development) ownsthe entity → target-element refinement.",
        "Intra- vs. interdependencies:intradependencies are within the same target system; interdependencies cross system boundaries (e.g., IADS depends on the adversary electric power system). Both must be captured — the analytical chain for HVT nomination often runs through an interdependency.",
        "Criticality factors are four: value, depth, recuperation, capacity. Vulnerability characteristics are seven: cushion, reserves, dispersion, mobility, countermeasures, physical, nonphysical. These are the controlled vocabulary —do not invent additional factors / characteristics.",
        "Critical-node identification is the load-bearing analytical step ('Target development should focus on identifying the critical nodes of key target systems that achieve the JFC's objectives'). The TSA quality is judged by whether the critical nodes it surfaces actually drive the recommended nominations.",
        "TSA → HVTL handoff: recommended_nominations is the explicit feed. Downstream HVTL build consumes the nominations as its row set for the named phase × threat_coa, mapping each nomination to an HVTL row whose Justification cell is the nomination's justification field, whose detection_signatures carry forward, and whose impact_of_loss carries forward from system_reaction_if_neutralized.",
        "Pre-strike TSA has a post-strike counterpart: TSDA (target system damage assessment) —'the broad assessment of the overall impact and effectiveness of military force applied against the operation of an enemy target system.' TSDA is a separate product (consumed by Phase 6 CA); do not conflate with TSA.",
        "Truncated TSA ('planning during a crisis may necessitate a truncated TSA process') is allowed; the system_components and critical_nodes lists may be narrower, but the recommended_nominations list MUST still trace back to a critical_node and a component, even in the truncated case.",
        "Irregular / non-state systems — 'TSA is equally applicable to systems and capabilities of both nation-state and non-state adversaries.' For insurgent / terrorist networks, components are leadership / fighting elements / training / logistics / financial / recruitment / propaganda cells; the schema does not change.",
        "Per IDX 26: every analytical claim has _provenance — system_function, criticality_assessment subfields, vulnerability_assessment subfields, criticality_rationale, expected_system_effect, justification.",
    ],
    "hard_rules": [
        "One target system per TSA artifact. Multi-system analyses produce multiple TSAs.",
        "Every recommended_nominations row MUST reference a node_id that exists in critical_nodes; every critical_nodes row MUST reference a component_id that exists in system_components. No orphan nominations.",
        "criticality_factor and vulnerability_characteristic vocabulary is the canonical enum —do not invent additional factors or characteristics.",
        "Critical-node detection_signatures must cover at least two disciplines (mirrors the HVTL convention).",
        "system_reaction_if_neutralized uses the controlled vocabulary (substitute / branch / sequel / accept) so the call carries forward to HVTL impact_of_loss without translation.",
        "TSA does NOT produce JDPIs / mensurated coordinates — that is TMP's role.Critical-node location_mgrs is collection-grade, not TMP-grade.",
        "TSA does NOT publish a priority-ordered HVT list — that is HVTL's role.recommended_nominations carries criticality_rank as a downstream hint; the actual HVTL priority ranking happens through CARVER.",
        "Per IDX 26 organizer requirement: every analytical claim has _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Force structure (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Targets in AO: list_targets()",
        "Recent activity for system characterization: get_recent_intel(window_hours=72)",
        "Terrain (component geographic extent): get_terrain()",
        "Civil considerations (target-system civil dependencies — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures + sustainment overlay (target-system geometry — AO / boundaries / phase lines / axes / OBJ / EA; sustainment-node dependencies BSA/DSA/LSA/FLE/APOD/SPOD/MSR/ASR/MTF/CCP/Class III/V/VIII): get_spatial_overlay()",
        "Phased concept of operations (target-system criticality shifts by phase): get_phases() — current phase + decisive point + phase objectives",
        "OPORD / FRAGO for JFC objectives: get_project_doc(tag='OPORD'), list_project_docs(filter={type:'FRAGO'})",
        "MCOO: list_project_docs(filter={type:'MCOO'})",
        "Threat Overlay: list_project_docs(filter={type:'Threat Overlay'})",
        "SITEMP: list_project_docs(filter={type:'SITEMP'})",
        "Threat COA Statement: list_project_docs(filter={type:'Threat COA Statement'})",
        "Prior TSA (regen): list_project_docs(filter={type:'Target System Analysis'})",
    ],
    "post_emit_summary": (
        "artifact_id, target_system_name, component count, critical-node count, "
        "recommended-nomination count, top-3 nominations one-liner"
    ),
}
