"""Threat Capability Statement — Step-3 enumeration of threat capabilities.

Step-3 enumeration of the threat's capabilities by warfighting function /
zone. Renders the tabular form by default (matrix shape) and also carries
a narrative paragraph_field for the prose form.

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

# Warfighting-function axis for the capability matrix. Mirrors the standard
# threat elements (C2, Movement and Maneuver, Intelligence, Fires,
# Sustainment, Protection) plus an information/cyber-EW row.
WARFIGHTING_FUNCTION_AXIS = [
    "command_and_control",
    "movement_and_maneuver",
    "intelligence",
    "fires",
    "sustainment",
    "protection",
    "information_cyber_electromagnetic"]

# Capability descriptor axis. Capabilities are broad options and supporting
# operations the threat can take. The columns model the four dimensions an
# analyst must capture per capability — strength (combat power / TPME),
# posture (current disposition), effects-on-friendly (what it does to us),
# indicators (how we detect it being exercised). The zone-based layout
# (disruption / battle / support) is captured via the zone_distribution
# paragraph_field below.
CAPABILITY_DESCRIPTOR_AXIS = [
    "strength",
    "posture",
    "effects_on_friendly",
    "indicators"]

SPEC = {
    "name": "Threat Capability Statement",
    "output_format": "docx",
    "shape": "matrix",
    # Portrait: the matrix is 7-row × 4-col of moderate-length narrative cells.
    # Portrait gives the rows enough vertical space to carry strength + posture
    # + effects narratives without the cells becoming illegible. Landscape
    # would compress the row heights and bloat the column widths past what the
    # narrative cell content needs.
    "doctrine": {
        "purpose": (
            "Step-3 enumeration of the threat's capabilities by warfighting "
            "function. Identifies a particular action the threat has the "
            "capability to complete, and the tactics the threat prefers to "
            "accomplish its objectives. Threat actors employ a combination "
            "of four major capabilities (conventional, irregular, disruptive, "
            "WMD). Feeds the SITEMP (each capability maps to a templated "
            "action) and Threat COA Statement (the COA enumeration draws from the capability "
            "set)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Matrix axes fixed: rows = warfighting functions (7 — C2, "
            "Movement and Maneuver, Intelligence, Fires, Sustainment, "
            "Protection, Information/Cyber-EM), columns = descriptors "
            "(4 — strength, posture, effects-on-friendly, indicators)."
        ),
    },
    # Step-3 capability enumeration. Tier 1 BOTH rollups AND atomics —
    # mid-cycle capability changes (e.g. newly observed SAM system, novel
    # tactic) must surface without waiting for the next-cycle rollup.
    "consumes_artifacts": ["Threat Model",
                            "SIGSUM", "HUMINTSUM", "OSIR", "DonovianDoctrine"],
    "matrix_spec": {
        "field": "capabilities_matrix",
        "row_axis": WARFIGHTING_FUNCTION_AXIS,
        "col_axis": CAPABILITY_DESCRIPTOR_AXIS,
        "row_label": "Warfighting Function",
        "col_label": "Capability Descriptor",
    },
    "header_fields": {
        "threat_actor":       {"source": "session", "view": "header",
                                 "required": True,
                                 "render_label": "Threat Actor",
                                 "default": "Donovian Armed Forces",
                                 "depends_on": ["upstream:Threat Model"],
                                 "guidance": (
                                    "Named threat the statement enumerates. "
                                    "Should match the upstream Threat Model "
                                    "and Threat Template headers. Writer "
                                    "MUST override the default with the "
                                    "specific echelon from get_oob() / OPORD "
                                    "threat characterization when available "
                                    "(e.g., 'Donovian 25th Motor Rifle "
                                    "Division'); default keeps the field "
                                    "populated until that resolution occurs."
                                 )},
        # Phase + DTG are session-sourced but the session value can be empty
        # in some flows; the explicit {phase} / {dtg} default keeps the
        # header band populated rather than rendering blank. Writer MUST
        # override with the OPORD §3.b phase token / current DTG when those
        # are available.
        "phase":              {**HEADER_PHASE, "default": "{phase}",
                                 "render_label": "Phase"},
        "dtg":                {**HEADER_DTG, "default": "{dtg}",
                                 "render_label": "DTG"},
        "area_of_operations": HEADER_AO,
        "threat_model_artifact_id": {"source": "upstream:Threat Model", "view": "internal",
                                       "required": False,
                                       "render_label": "Threat Model Reference",
                                       "depends_on": ["upstream:Threat Model"],
                                       "guidance": (
                                          "Upstream Threat Model — soft-"
                                          "required since the capability "
                                          "statement is one of the three "
                                          "Step-3 outputs and the model "
                                          "provides the doctrinal basis."
                                       )},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay", "view": "internal",
                                          "required": False,
                                          "render_label": "Threat Overlay Reference",
                                          "guidance": (
                                            "Upstream Threat Overlay (which "
                                            "ATP 2-01.3 §5-45 calls 'Threat "
                                            "Template' — same product, same "
                                            "DOCTEMP graphic + tactics + "
                                            "HVT-ID payload) that visualizes "
                                            "the capability set depicted here."
                                          )},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "capabilities_matrix",
         "view": "published",
         "shape": "grid_table",
         "render_label": "Threat Capabilities by Warfighting Function",
         "required": True,
         "provenance_required": True,
         "depends_on": ["document:DonovianDoctrine"],
         "guidance": (
            "7×4 grid. Rows = warfighting functions (C2, Movement and "
            "Maneuver, Intelligence, Fires, Sustainment, Protection, "
            "Information/Cyber-EM). Cols = descriptors:\n"
            "  - strength = combat power (echelon × system count) or TPME "
            "summary for the WfF. Cite OOB / NGIC.\n"
            "  - posture = current disposition (defending, attacking, "
            "withdrawing, EMCON, etc.) for the WfF.\n"
            "  - effects_on_friendly = what this capability does to friendly "
            "operations (e.g., 'denies CAS within 25 km of BDE artillery "
            "group'). Pulls from the threat OOB + observed engagements.\n"
            "  - indicators = signatures by which friendly ISR detects this "
            "capability being exercised (e.g., 'SNAR-10 radar emissions in "
            "the 14.5-15.0 GHz band'). Cite SIGINT / IMINT references.\n"
            "Each cell carries one or more capability-statement bullets in "
            "the standard phrasing: 'The threat has the capability to ...'. "
            "Each bullet cites source.\n"
            "\n"
            "RENDER SHAPE — emit as a canonical nested dict keyed by "
            "warfighting-function row names that EXACTLY match the "
            "matrix_spec.row_axis tokens (command_and_control, "
            "movement_and_maneuver, intelligence, fires, sustainment, "
            "protection, information_cyber_electromagnetic), with each row "
            "value a dict keyed by descriptor column tokens (strength, "
            "posture, effects_on_friendly, indicators):\n"
            "  {\n"
            "    'command_and_control': {\n"
            "      'strength': '...', 'posture': '...',\n"
            "      'effects_on_friendly': '...', 'indicators': '...',\n"
            "      '_provenance': {'strength': '...', 'posture': '...',\n"
            "                       'effects_on_friendly': '...', 'indicators': '...'}\n"
            "    },\n"
            "    'movement_and_maneuver': {...},\n"
            "    ... (7 rows total, one per WfF axis token)\n"
            "  }\n"
            "Do NOT emit as a flat list, a 'cells' wrapper, or a positional "
            "rows/cols array — the exporter's matrix-from-spec renderer "
            "consumes this dict-of-dicts directly. Row keys MUST match the "
            "axis tokens verbatim (snake_case, no spaces, no display "
            "casing) so _render_grid_inline aligns rows to the row_axis. "
            "An empty cell is valid output when the threat lacks the named "
            "WfF (e.g., information_cyber_electromagnetic empty for a "
            "low-tech insurgent group) — but every row key still appears."
         )},
        {"name": "major_capability_classification",
         "view": "published",
         "shape": "dict",
         "render_label": "Major Capability Classification",
         "required": True,
         "provenance_required": True,
         "guidance": (
            "Threat actors employ a combination of four major capabilities. "
            "For each capability category, one-to-two sentences describing "
            "what the named threat actor employs of this type, or 'Not "
            "Applicable' with rationale.\n"
            "  - conventional: state-organized military assets in identifiable formations\n"
            "  - irregular: unregulated / asymmetric methods\n"
            "  - disruptive: technologies that reduce friendly advantages\n"
            "  - weapons_of_mass_destruction: CBRN capabilities"
         ),
         "subfields": ["conventional", "irregular", "disruptive", "weapons_of_mass_destruction"]},
        {"name": "supporting_operations",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Supporting Operations",
         "required": False,
         "guidance": (
            "Other threat capabilities — operations that would allow threat "
            "forces to use a COA that would not normally be available. From "
            "the catalog: CBRN use, intelligence collection, EW operations, "
            "air assets (fixed + rotary), engineering operations, air "
            "assault / airborne, amphibious, river, propaganda, recruitment, "
            "deception, car bombings, raids on weapons facilities, "
            "carjacking, offensive cyberspace operations, anti-access / area "
            "denial, social media exploitation. List those the named threat "
            "actor demonstrably has.\n"
            "\n"
            "DIVERSIFY enables_coa ACROSS ROWS — each supporting operation "
            "must call out a DIFFERENT downstream Threat COA Statement option / supporting "
            "effort it enables, not the same COA repeated. The supporting-"
            "operations list is the bridge from threat capabilities into "
            "the Threat COA Statement option space; if every row enables the same COA the "
            "Threat COA Statement developer has no branch/sequel signal to work with. "
            "Cover the spread of COAs the threat actor's capability mix "
            "supports — Most-Likely, Most-Dangerous, and any deception / "
            "shaping / branch options between them — with at least one "
            "supporting-operation row per distinct COA. When two operations "
            "genuinely enable the same COA, group them as a single row "
            "(combined capability_statement) rather than duplicating the "
            "enables_coa value."
         ),
         "item_subfields": [
             {"name": "operation", "render_label": "Operation",
              "guidance": "operation name (e.g., 'offensive cyberspace operations', 'air assault', 'CBRN use')"},
             {"name": "capability_statement", "render_label": "Capability Statement",
              "provenance_required": True,
              "guidance": "Standard phrasing: 'The threat has the capability to ...'. Cite OOB / NGIC / observed-engagement basis."},
             {"name": "enables_coa", "render_label": "Enables COA",
              "required": False,
              "guidance": (
                 "Which downstream Threat COA Statement option this supporting operation "
                 "makes available (e.g., 'enables Most-Dangerous urban-"
                 "defense COA', 'enables Most-Likely zone-defense COA', "
                 "'enables deception-branch withdrawal-feint COA'). MUST "
                 "differ across supporting_operations rows — see parent "
                 "guidance on diversification."
              )}]},
        {"name": "narrative_statement",
         "view": "published",
         "shape": "string",
         "render_label": "Capability Narrative",
         "required": False,
         "provenance_required": True,
         "guidance": (
            "Narrative form: prose enumeration of the threat's capabilities "
            "by warfighting function (one paragraph per WfF). Optional — the "
            "published artifact carries the table form by default; the "
            "narrative is provided when the analyst directs a narrative "
            "output. Cite sources inline."
         )},
        {"name": "constraints_and_shortfalls",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Constraints and Shortfalls",
         "required": False,
         "guidance": (
            "Most situations do not present the threat with ideal "
            "conditions envisioned by its doctrine — the threat's actual "
            "capabilities usually do not mirror the ideal. List observed "
            "constraints (under strength, lacking logistics, inexperienced "
            "personnel, METT-TC conditions degrading the capability). "
            "Distinct from the Threat Model's 'peculiarities' field — that "
            "is doctrinal/cultural; this is current-state operational. Both "
            "feed friendly COA development."
         ),
         "depends_on": [
             "upstream:Threat Model",
         ],
         "item_subfields": [
             {"name": "warfighting_function", "render_label": "Warfighting Function",
              "enum": WARFIGHTING_FUNCTION_AXIS,
              "guidance": "which WfF row this constraint applies to"},
             {"name": "description", "render_label": "Description",
              "provenance_required": True,
              "guidance": "one-sentence description of the shortfall (e.g., 'lead fires battalion at 65% strength following Phase 1 attrition')"},
             {"name": "impact_on_capability", "render_label": "Impact on Capability",
              "required": False,
              "guidance": "how this degrades the capability listed in the matrix above"}]},
        {"name": "zone_distribution",
         "view": "published",
         "shape": "dict",
         "render_label": "Zone Distribution",
         "required": False,
         "depends_on": ["document:DonovianDoctrine"],
         "guidance": (
            "Capability distribution across the disruption / battle / "
            "support zones per the threat's zone doctrine. Optional "
            "secondary view of the same capability data the matrix above "
            "carries. Use when the threat's doctrine is zone-based "
            "(Donovian / OPFOR-style); skip for non-zone-doctrine threats "
            "(insurgent networks, urban defenders, etc.). For Donovian, "
            "follow section 2 of the DonovianDoctrine reference verbatim."
         ),
         "subfields": ["disruption_zone", "battle_zone", "support_zone"]}],
    "subtleties": [
        "Two formats: narrative and table. Default published form is the matrix table; narrative_statement carries the prose form when the analyst directs prose output.",
        "Capability statements use the phrasing: 'The threat has the capability to ...' — every cell bullet in the matrix and every supporting_operations row follows this voice. Drives downstream readability.",
        "Four major capability types: conventional, irregular, disruptive, WMD. The threat's combination of these drives whether the model is regular / irregular / hybrid (upstream Threat Model header field).",
        "The threat's ACTUAL capabilities usually do not mirror the IDEAL. The capabilities_matrix carries the ideal; constraints_and_shortfalls carries the current-state degradation. Both are required for accurate downstream Threat COA Statement.",
        "Zone-based threats (Donovian / OPFOR) carry the optional zone_distribution paragraph. Insurgent / urban / criminal threats do not — leave it blank. Don't force a zone framework on a threat whose doctrine doesn't use one.",
        "Indicators column feeds SITEMP NAI watching_for and Threat COA Statement confirmation/denial criteria. Cite SIGINT band, IMINT visual signature, HUMINT source class.",
        "Every cell bullet, every supporting-operation statement, every constraint cites source in _provenance."],
    "hard_rules": [
        "Never invent capabilities. Every cell entry, every supporting-operations row, every constraint cites a real source (OOB / NGIC / DonovianDoctrine / observed engagement / SIGINT / IMINT report).",
        "Matrix axes are fixed and complete: 7 WfF rows × 4 descriptor columns = 28 cells. A cell may be empty if the threat lacks the named WfF (e.g., information_cyber_electromagnetic empty for a low-tech insurgent group) — but every row and column appears in the rendered matrix.",
        "Capability statements use the 'The threat has the capability to ...' phrasing — not 'The threat will ...' (that conflates capability with intent / COA).",
        "Four-capability classification is required — list the threat's mix of conventional + irregular + disruptive + WMD, or 'Not Applicable' with rationale.",
        "Donovian threat actor uses the OPFOR / TC 7-100 doctrinal model — WfF capability statements MUST reflect the doctrinal patterns in get_project_doc(tag='DonovianDoctrine') section 7 (centralized C2 with corps-level integrated fires, reconnaissance-fires complex, layered antitank, layered integrated air defense, maskirovka, etc.). zone_distribution MUST follow the disruption / battle / support zone construct in section 2.",
        "Every analytical field carries _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream Threat Model: list_project_docs(filter={type:'Threat Model'}) then get_project_doc",
        "Upstream Threat Overlay (the rendered 'threat template' graphic per ATP 2-01.3 §5-45 — same product): list_project_docs(filter={type:'Threat Overlay'})",
        "Threat structure (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Threat OOB reference: get_project_doc(tag='OOB')",
        "Threat doctrine (REQUIRED — anchors WfF capability statements + zone_distribution): get_project_doc(tag='DonovianDoctrine')",
        "Recent threat activity (current-state constraints): get_recent_intel(window_hours=168, types=['report','engagement','imagery'])",
        "Recent BDA (constraints from attrition): list_project_docs(filter={type:'BDA'})",
        "Threat COA Statement upstream context: list_project_docs(filter={type:'Threat COA Statement'})",
        "Operations overlay control measures (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ — capability geometry references): get_spatial_overlay()",
        "Phased concept of operations (enemy capability adapts per friendly phase): get_phases() — current phase + decisive point + phase objectives",
        "Prior threat-capability-statement artifact (regen): list_project_docs(filter={type:'Threat Capability Statement'})"],
    "post_emit_summary": "artifact_id, threat_actor, WfF row coverage, supporting-operations count, constraint count",
}
