"""TIDAT — Target Intelligence Data Report — FM 34-25-3 Ch. 5
(All-Source Analysis System / Analysis and Control Element).

Doctrinal intel-to-fires per-target handoff. The ACE targeting workstation
analyst sends a TIDAT message carrying ONE validated target electronically to
the FSE via CCS or CAMPS, where it is forwarded to AFATDS for action.
AFATDS terminates per-target — each target is an independent fire-mission
record — and the FM 6-30 / ATP 3-09.30 call-for-fire structure is per-target,
so TIDAT is per-target as well. One right-click on a hostile mil_unit on the
operations map yields one TIDAT artifact for that one target.

Per FM 34-25-3 Ch. 5 verbatim:

  "Targets determined to be valid, accurate, and timely are sent
   electronically to the FSE using a target intelligence data (TIDAT)
   report."

  "The targeting workstation analyst sends a TIDAT message to the CCS or
   CAMPS. The TIDAT is then forwarded to the AFATDS for action."

Family: targeting Deliver-phase per-target message form, alongside HPTL
(rollup of which targets matter), AGM (engagement decision rules), TSS
(validity thresholds), TMP (mensurated aimpoint data sheet).

Shape: header_only DOCX, portrait. Closest analog in this codebase is
target_material_production.py (TMP) — per-target header_only DOCX with the
same single-document analyst surface, same per-target identity, same
downstream-by-id consumption. NOT a row-XLSX rollup; HPTL is the rollup.

Provenance and chain-of-custody for "where did this target come from"
lives in originating_cell (the ACE / G-2 desk that pushed the TIDAT) +
detection_source (the sensor / SIGINT / IMINT / HUMINT vertex that
established the target) + prepared_by (the analyst running the workstation).
TIDAT does not carry the FM 6-30 / ATP 3-09.30 "Observer Identification"
element — it originates at the ACE targeting workstation, not at a forward
observer.

See templates/products/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    PRECEDENCE_ENUM,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
    TARGET_CATEGORY_ENUM,
    TARGET_CATEGORY_LABELS,
    TYPE_FIVE_O_ENUM,
)

# Doctrinal routing destinations (FM 34-25-3 Ch. 5). The ACE targeting
# workstation pushes to the FSE via CCS or CAMPS in the doctrinal default
# flow; AFATDS_DIRECT is the immediate-precedence override when the FSE
# routing relay is bypassed for time-critical engagement.
ROUTING_DESTINATION_ENUM = ["FSE_CCS", "FSE_CAMPS", "AFATDS_DIRECT"]

# Lifecycle marker for the per-target push. PENDING is the post-emission
# default; PUSHED is set when the artifact is electronically forwarded;
# ACK_BY_FSE / ACK_BY_AFATDS are external-receipt confirmations populated
# manually by the analyst until an external-receipt ingest pipeline exists;
# RESCINDED is set when the target is withdrawn post-push.
PUSH_STATUS_ENUM = ["PENDING", "PUSHED", "ACK_BY_FSE", "ACK_BY_AFATDS", "RESCINDED"]

# Target-focus binding hard rule. TIDAT is generated EXCLUSIVELY from a
# right-click on a hostile mil_unit on the operations map; the
# target_entity_id arrives in the generate-async args and is the primary
# key for the artifact. A request without target_entity_id has no target
# identity and must fail emission rather than write a malformed artifact.
TARGET_FOCUS_BINDING_HARD_RULE = (
    "TIDAT requires target_entity_id supplied via the operations-map "
    "right-click trigger. Emission MUST fail with a clear gap notice "
    "when target_entity_id is absent — no artifact is written. The "
    "target_id field is bound to the right-clicked entity's kg_id and "
    "is never invented."
)

SPEC = {
    "name": "TIDAT",
    "output_format": "docx",
    "output_formats": ["docx"],
    "shape": "header_only",
    "page_orientation": "portrait",
    "doctrine": {
        "purpose": (
            "Per-target intel-to-fires handoff message. The ACE targeting "
            "workstation analyst electronically pushes one validated target "
            "to the FSE via CCS or CAMPS, where it is forwarded to AFATDS "
            "for action. Carries the target identity (location, size, "
            "activity, DOI, detection source), the engagement decision "
            "echoed verbatim from AGM (method of engagement, method of "
            "fire and control), the validity decision (valid / accurate / "
            "timely triple cited against TSS thresholds or analyst "
            "rationale), precision-fires routing from TMP when present, "
            "and the handling block (precedence, collateral concern, push "
            "status). One artifact = one target. Right-click trigger on "
            "a hostile mil_unit binds target_entity_id; the originating "
            "intel side is attributed via originating_cell + "
            "detection_source + prepared_by." + PROVENANCE_DIRECTIVE
        ),
        "per_target_rationale": (
            "AFATDS terminates per-target — each target is an independent "
            "fire-mission record — and the call-for-fire structure is "
            "per-target. A rollup of N targets into one document would be "
            "N separate messages at the wire and would destroy the "
            "per-target identity the FSE and AFATDS both consume. HPTL is "
            "the rollup of which targets matter; TIDAT is the per-target "
            "handoff for each one. Single-document analyst surface, "
            "single-target downstream-by-id consumption."
        ),
        "ordering_rule": (
            "Single-target product (header_only shape). One TIDAT per "
            "validated target per push. Multiple pushes for the same "
            "target across time produce multiple TIDAT artifacts — the "
            "most recent push reflects the current valid/accurate/timely "
            "decision."
        ),
    },
    "consumes_artifacts": [
        "HPTL", "AGM", "TSS", "TMP", "SITEMP",
        "Threat COA Statement", "NSL", "RTL", "CCA-Matrix",
    ],
    # Per-field upstream dep filter — narrows every TIDAT writer prompt to
    # the writer-relevant subsection of each artifact dep payload. Without
    # this every per-field call drags the full upstream artifact (full
    # HPTL rows + AGM matrix + Threat COA Statement coas + ...) which
    # saturates the vllm_gate budget on a per-target dispatch. Mirrors
    # high_value_target_list.py default_data_source_filter (lines 101-129).
    # Empty list [] for artifacts kept purely for DAG ordering (SITEMP).
    "default_data_source_filter": {
        "upstream:HPTL": ["rows"],
        "upstream:AGM": ["agm_rows", "agm_matrix"],
        "upstream:TSS": ["rows"],
        "upstream:TMP": ["jdpi_id", "parent_etf_eid", "header"],
        "upstream:SITEMP": [],
        "upstream:Threat COA Statement": ["coas"],
        "upstream:NSL": ["rows"],
        "upstream:RTL": ["rows"],
        "upstream:CCA-Matrix": ["rows"],
    },
    # Batched-wave declarations — consolidate the 22 serial per-field LLM
    # calls into ~6 batched waves keyed by shared dep set. Pattern mirrors
    # the HVTL `hvt_analytical` batch_group; co-fires same-batch_group
    # fields into ONE LLM call per wave (see dag_executor.py batched-wave
    # handling). Without this, TIDAT per-target dispatch was 22 serial
    # calls; with this it's the wave count (~6).
    "batch_groups": {
        "tidat_target_lookup": {
            "depends_on": ["upstream:HPTL"],
        },
        "tidat_agm_echo": {
            "depends_on": ["upstream:AGM"],
        },
        "tidat_tss_validity": {
            "depends_on": ["upstream:TSS"],
        },
        "tidat_collateral": {
            "depends_on": [
                "upstream:NSL", "upstream:RTL", "upstream:CCA-Matrix",
            ],
        },
        "tidat_tmp_routing": {
            "depends_on": ["upstream:TMP"],
        },
        "tidat_handling": {},
    },
    "published_section_title": "Target Intelligence Data Report",
    "header_fields": {
        # ------------------------------------------------------------------
        # Session / dispatch
        # ------------------------------------------------------------------
        "dtg": HEADER_DTG,
        "area_of_operations": HEADER_AO,
        # Phase defaults via skeleton-fill (session.phase value copied at
        # skeleton-fill time). Matches HVTL line 136 pattern — TIDAT must
        # never publish with an empty phase header.
        "phase": {**HEADER_PHASE, "default": "Phase I (Penetration)"},
        "as_of_dtg": {
            "source": "session", "view": "header", "required": True,
            # as_of_dtg defaults to copy dtg value at skeleton-fill time
            # — the runner threads session DTG into both fields so the
            # post-emission TIDAT never publishes blank as_of_dtg.
            "default": "{dtg}",
            "render_label": "As-Of DTG",
            "guidance": (
                "Cutoff time for the observations this push is based on. "
                "Later confirming observations are a future push."
            ),
        },
        "routing_destination": {
            "source": "session", "view": "header", "required": True,
            # Doctrinal default: ACE → FSE via CCS. AFATDS_DIRECT is the
            # immediate-precedence override the analyst sets explicitly.
            "default": "FSE_CCS",
            "enum": ROUTING_DESTINATION_ENUM,
            "render_label": "Routing Destination",
            "guidance": (
                "FSE_CCS or FSE_CAMPS is the doctrinal default per the "
                "ACE-to-FSE routing relay; AFATDS_DIRECT is the "
                "immediate-precedence override that bypasses the FSE "
                "relay for time-critical engagement."
            ),
        },
        "originating_cell": {
            "source": "session", "view": "header", "required": True,
            # Doctrinal default: TIDAT originates at the ACE targeting
            # workstation per FM 34-25-3 Ch. 5. Never publish blank.
            "default": "ACE TARGETING WORKSTATION",
            "render_label": "Originating Cell",
            "guidance": (
                "ACE targeting workstation / G-2 fusion cell identifier "
                "for the desk that pushed this TIDAT. Drives the "
                "intel-side audit trail for the engagement."
            ),
        },
        "prepared_by": HEADER_PREPARED_BY,
        "classification": HEADER_CLASSIFICATION,

        # ------------------------------------------------------------------
        # Upstream artifact references
        # ------------------------------------------------------------------
        "hptl_artifact_id": {
            "source": "upstream:HPTL", "view": "internal", "required": True,
            "render_label": "HPTL Reference",
            "depends_on": ["upstream:HPTL"],
            "guidance": (
                "Active HPTL artifact_id. The target MUST be on the "
                "active HPTL — emission fails if absent."
            ),
        },
        "agm_artifact_id": {
            "source": "upstream:AGM", "view": "internal", "required": True,
            "render_label": "AGM Reference",
            "depends_on": ["upstream:AGM"],
            "guidance": (
                "Active AGM artifact_id. TIDAT echoes "
                "method_of_engagement + method_of_fire_and_control "
                "verbatim from the AGM structured row for this target's "
                "HPT category. Never authored independently."
            ),
        },
        "tss_artifact_id": {
            "source": "upstream:TSS", "view": "internal", "required": False,
            "render_label": "TSS Reference",
            "depends_on": ["upstream:TSS"],
            "guidance": (
                "Active TSS artifact_id when registered. valid_flag / "
                "accurate_flag / timely_flag cite the TSS row when "
                "present; when absent, analyst inline-justifies in "
                "source_basis."
            ),
        },
        "tmp_artifact_id": {
            "source": "upstream:TMP", "view": "internal", "required": False,
            "render_label": "TMP Reference",
            "depends_on": ["upstream:TMP"],
            "guidance": (
                "TMP artifact_id when the target has a completed "
                "mensurated aimpoint data sheet. Carries jdpi_id + "
                "parent_etf_eid for precision-fires routing."
            ),
        },
        "sitemp_artifact_id": {
            "source": "upstream:SITEMP", "view": "internal", "required": False,
            "render_label": "SITEMP Reference",
            "depends_on": ["upstream:SITEMP"],
            "guidance": (
                "Confirming situation-template geometry context for the "
                "writer; not rendered as a body field."
            ),
        },
        "threat_coa_statement_artifact_id": {
            "source": "upstream:Threat COA Statement", "view": "internal",
            "required": False,
            "render_label": "Threat COA Statement Reference",
            "depends_on": ["upstream:Threat COA Statement"],
            "guidance": (
                "Confirms target relevance to the current threat course "
                "of action. Optional context for the writer."
            ),
        },

        # ------------------------------------------------------------------
        # Target identity (the entity being nominated)
        # ------------------------------------------------------------------
        "target_id": {
            "source": "analytical", "view": "internal", "required": True,
            "provenance_required": True,
            "render_label": "Target ID",
            "guidance": (
                "kg_id of the hostile mil_unit entity supplied by the "
                "operations-map right-click trigger. Primary key for the "
                "artifact — emit the UUID string verbatim from the BOUND "
                "TARGET KG RECORD block in the user message (kg_id: line). "
                "Never invented, never empty. If no bound target is "
                "present in the context (sweep-fired TIDAT with no "
                "target_focus), emit a gap notice and the runner will "
                "fail emission per the TIDAT hard rule."
            ),
        },
        "target_number": {
            # Mechanical lookup from upstream HPTL row keyed by this
            # artifact's target_id. NEVER LLM-authored — see the lookup
            # resolver in dag_executor._run_field_node. Falls through to
            # the empty string when no HPTL row exists for this target_id.
            "source": "upstream:HPTL.rows[target_id].id", "view": "published",
            "required": False, "provenance_required": True,
            "batch_group": "tidat_target_lookup",
            "depends_on": ["upstream:HPTL"],
            "render_label": "Target Number",
            "guidance": (
                "Joint target number assigned by the HPTL writer at the "
                "row's HPTL placement. Mechanical lookup from the active "
                "HPTL row keyed by target_id. NOT LLM-authored — the "
                "lookup:HPTL.rows[target_id].id resolver in the DAG "
                "executor stamps the value mechanically."
            ),
        },
        "target_name": {
            "source": "entity:name", "view": "published", "required": True,
            "provenance_required": True,
            "render_label": "Target Name",
            "guidance": (
                "Doctrinal short name of the target entity from the "
                "knowledge graph."
            ),
        },
        "target_category": {
            "source": "entity:category", "view": "published", "required": True,
            "provenance_required": True,
            "enum": TARGET_CATEGORY_ENUM,
            "enum_labels": TARGET_CATEGORY_LABELS,
            # Fallback to LLM only when KG entity category is blank;
            # batch with target_lookup wave so the fallback ride-alongs
            # with the HPTL-bound row_lookup.
            "batch_group": "tidat_target_lookup",
            "render_label": "Target Category",
            "guidance": (
                "Target category from the knowledge graph. Drives the "
                "AGM row lookup for method_of_engagement + "
                "method_of_fire_and_control."
            ),
        },
        "type_five_o": {
            "source": "entity:type_five_o", "view": "published",
            "required": False,
            "enum": TYPE_FIVE_O_ENUM,
            "render_label": "Target Type",
            "guidance": (
                "Five-O target type from the knowledge graph: facility, "
                "individual, virtual, equipment, or organization."
            ),
        },
        "target_location_mgrs": {
            "source": "entity:location_mgrs", "view": "published",
            "required": True, "provenance_required": True,
            "render_label": "Target Location",
            "guidance": (
                "Target location in MGRS, 10-digit minimum precision, "
                "WGS 84 default datum. From the knowledge graph entity."
            ),
        },
        "target_size": {
            "source": "entity:echelon", "view": "published", "required": True,
            "provenance_required": True,
            "render_label": "Target Size",
            "guidance": (
                "Echelon and composition string describing the target "
                "(e.g., 'reinforced motorized rifle company, 10 BMP-2 + "
                "3 BTR-82A'). From the knowledge graph entity's echelon "
                "and composition fields."
            ),
        },
        "target_activity": {
            "source": "entity:size_posture_activity", "view": "published",
            "required": True, "provenance_required": True,
            # Fallback to LLM only when KG entity composite is blank;
            # batch with target_lookup wave.
            "batch_group": "tidat_target_lookup",
            "render_label": "Target Activity",
            "guidance": (
                "What the target is doing at the time of this push — "
                "assembling, moving, digging in, in hide site, etc. "
                "From the kg entity's size_posture_activity composite "
                "field. Render the activity component; if only a "
                "composite is present, render the composite verbatim."
            ),
        },
        "doi": {
            "source": "entity:doi", "view": "published", "required": True,
            "provenance_required": True,
            "render_label": "Date of Intel",
            "guidance": (
                "DOI for the most recent confirming observation that "
                "established the target identity and location at this "
                "push. Drives the timely_flag decision against the TSS "
                "dwell window."
            ),
        },
        "detection_source": {
            "source": "analytical", "view": "published",
            "required": True, "provenance_required": True,
            "render_label": "Detection Source",
            "guidance": (
                "Sensor or report identifier that established this "
                "target. When the kg entity exposes a detection_source "
                "field (cougaar-sourced units carry source_type), use "
                "that value verbatim. When the target identity is from "
                "the canonical scenario fixture (force_type set, no "
                "detection_source on the entity), emit "
                "'scenario_canonical_oob'. When a sensor vertex is "
                "available (SIGINT / IMINT / HUMINT kbID + objectType), "
                "name the specific vertex. Never an unqualified domain "
                "label and never invented."
            ),
        },

        # ------------------------------------------------------------------
        # Engagement decision (echoed from AGM)
        # ------------------------------------------------------------------
        "method_of_engagement": {
            # Mechanical echo from upstream AGM agm_rows[target_id] —
            # NOT LLM-authored. The DAG executor resolves the lookup
            # against AGM.structured_data.agm_rows keyed by target_id;
            # empty string when no AGM row exists for this target.
            "source": "upstream:AGM.agm_rows[target_id].how_engage",
            "view": "published", "required": True,
            "provenance_required": True,
            "batch_group": "tidat_agm_echo",
            "depends_on": ["upstream:AGM"],
            "render_label": "Method of Engagement",
            "guidance": (
                "Echoed verbatim from the AGM structured row for this "
                "target_id (AGM.structured_data.agm_rows[target_id]."
                "how_engage). Mechanical lookup — the writer LLM is "
                "BYPASSED entirely by the lookup: resolver. Never parsed "
                "from the AGM markdown matrix."
            ),
        },
        "method_of_fire_and_control": {
            # Mechanical echo — same pattern as method_of_engagement;
            # joins effects + remarks via the lookup resolver. The schema
            # references effects_plus_remarks which the resolver maps to
            # the AGM row's effects + ' ' + remarks composite.
            "source": "upstream:AGM.agm_rows[target_id].effects_plus_remarks",
            "view": "published", "required": True,
            "provenance_required": True,
            "batch_group": "tidat_agm_echo",
            "depends_on": ["upstream:AGM"],
            "render_label": "Method of Fire and Control",
            "guidance": (
                "Echoed verbatim from the AGM structured row for this "
                "target_id (AGM.structured_data.agm_rows[target_id]."
                "effects + .remarks joined). Mechanical lookup — the "
                "writer LLM is BYPASSED by the lookup: resolver."
            ),
        },

        # ------------------------------------------------------------------
        # Precision-fires routing (from TMP when present)
        # ------------------------------------------------------------------
        "jdpi_id": {
            # Mechanical lookup from upstream TMP — NOT LLM-authored.
            # Blank-when-absent: empty string is correct when no TMP
            # exists for this target. Explicitly NOT gated on analyst
            # input — the [ANALYST INPUT REQUIRED] sentinel default
            # does NOT apply here per the per-field guidance below.
            "source": "upstream:TMP.jdpi_id", "view": "published",
            "required": False,
            "batch_group": "tidat_tmp_routing",
            "depends_on": ["upstream:TMP"],
            "render_label": "JDPI ID",
            "guidance": (
                "Joint Desired Point of Impact identifier, pulled from "
                "the referenced TMP when present. Emit empty string "
                "when no TMP exists. NEVER the [ANALYST INPUT REQUIRED] "
                "sentinel — jdpi_id is blank-when-absent, not "
                "analyst-input-gated. The BANNED OUTPUT STRINGS "
                "sentinel-default rule does NOT apply to this field."
            ),
        },
        "parent_etf_eid": {
            # Same as jdpi_id — mechanical lookup, blank-when-absent.
            # NOT analyst-input-gated.
            "source": "upstream:TMP.parent_etf_eid", "view": "published",
            "required": False,
            "batch_group": "tidat_tmp_routing",
            "depends_on": ["upstream:TMP"],
            "render_label": "Parent ETF EID",
            "guidance": (
                "Electronic Target Folder element identifier the JDPI "
                "lives under, pulled from the referenced TMP. Emit "
                "empty string when no TMP exists. NEVER the "
                "[ANALYST INPUT REQUIRED] sentinel — parent_etf_eid is "
                "blank-when-absent, not analyst-input-gated. The "
                "BANNED OUTPUT STRINGS sentinel-default rule does NOT "
                "apply to this field."
            ),
        },

        # ------------------------------------------------------------------
        # Validity decision (valid / accurate / timely triple)
        # ------------------------------------------------------------------
        "valid_flag": {
            "source": "analytical", "view": "published", "required": True,
            "provenance_required": True,
            "default": False,
            "batch_group": "tidat_tss_validity",
            "depends_on": ["upstream:TSS"],
            "render_label": "Valid",
            "guidance": (
                "True when the target meets the TSS validity threshold "
                "and identification confidence supports engagement. "
                "Cite the specific TSS row in _provenance when TSS is "
                "registered; cite analyst rationale when TSS is absent."
            ),
        },
        "accurate_flag": {
            "source": "analytical", "view": "published", "required": True,
            "provenance_required": True,
            "default": False,
            "batch_group": "tidat_tss_validity",
            "depends_on": ["upstream:TSS"],
            "render_label": "Accurate",
            "guidance": (
                "True when target location error meets the TSS accuracy "
                "threshold. Cite the TSS row and the TMP CE90 / LE90 "
                "when TMP exists; cite analyst rationale when TSS is "
                "absent."
            ),
        },
        "timely_flag": {
            "source": "analytical", "view": "published", "required": True,
            "provenance_required": True,
            "default": False,
            "batch_group": "tidat_tss_validity",
            "depends_on": ["upstream:TSS"],
            "render_label": "Timely",
            "guidance": (
                "True when the last confirming observation lies within "
                "the TSS dwell window for this target category. Cite "
                "DOI and the TSS window when TSS is registered; cite "
                "analyst rationale when TSS is absent."
            ),
        },

        # ------------------------------------------------------------------
        # Handling
        # ------------------------------------------------------------------
        "precedence": {
            "source": "analytical", "view": "published", "required": True,
            "enum": PRECEDENCE_ENUM,
            "batch_group": "tidat_handling",
            "render_label": "Precedence",
            "guidance": (
                "FLASH / IMMEDIATE / PRIORITY / ROUTINE. Drives the "
                "FSE handling order for the push."
            ),
        },
        "collateral_concern": {
            "source": "analytical", "view": "published", "required": False,
            "provenance_required": True,
            "batch_group": "tidat_collateral",
            "depends_on": [
                "upstream:NSL", "upstream:RTL", "upstream:CCA-Matrix",
            ],
            "render_label": "Collateral Concern",
            "guidance": (
                "Single-sentence callout when adjacent civil "
                "considerations, the No-Strike List, the Restricted "
                "Target List, or the Civil Considerations Assessment "
                "matrix drive handling. Cite the NSL / RTL / CCA-Matrix "
                "artifact_id of the protected entity in _provenance."
            ),
        },
        "source_basis": {
            "source": "analytical", "view": "published", "required": True,
            "provenance_required": True,
            "batch_group": "tidat_tss_validity",
            "depends_on": ["upstream:TSS"],
            "render_label": "Source Basis",
            "guidance": (
                "One short sentence — what specific observation triggered "
                "the valid/accurate/timely decision for this target. "
                "Cites the originating knowledge-graph vertex in "
                "_provenance."
            ),
        },
        "push_status": {
            "source": "analytical", "view": "published", "required": True,
            "provenance_required": True,
            "enum": PUSH_STATUS_ENUM,
            "default": "PENDING",
            "batch_group": "tidat_handling",
            "render_label": "Push Status",
            "guidance": (
                "Lifecycle marker for this push. PENDING is the "
                "post-emission default. PUSHED is set when the artifact "
                "is electronically forwarded. ACK_BY_FSE / "
                "ACK_BY_AFATDS are set only on external receipt "
                "confirmation. RESCINDED is set when the target is "
                "withdrawn post-push."
            ),
        },
    },
    "subtleties": [
        "One artifact = one target. AFATDS terminates per-target and the "
        "call-for-fire structure is per-target; a rollup form would be N "
        "separate messages at the wire and would destroy the per-target "
        "identity the FSE and AFATDS both consume.",
        "method_of_engagement + method_of_fire_and_control are echoed "
        "verbatim from the AGM structured row keyed by target_id. The "
        "writer performs a clean dict lookup against "
        "AGM.structured_data.agm_rows[target_id] — it does NOT author "
        "these fields and does NOT parse the AGM markdown matrix.",
        "jdpi_id and parent_etf_eid are pulled directly from the "
        "referenced TMP artifact. They are blank when no TMP exists for "
        "this target. The writer NEVER invents either value.",
        "Chain-of-custody for where the target came from is carried by "
        "originating_cell (the ACE / G-2 desk that pushed the TIDAT) + "
        "detection_source (the sensor / SIGINT / IMINT / HUMINT vertex "
        "that established the target) + prepared_by (the analyst at the "
        "workstation). TIDAT does not carry the call-for-fire 'Observer "
        "Identification' element — it originates at the ACE, not at a "
        "forward observer.",
        "The valid / accurate / timely triple cites the TSS row in "
        "_provenance when TSS is registered. When TSS is absent the "
        "writer inline-justifies the decision in source_basis and the "
        "_provenance citation names the analyst rationale.",
        "push_status defaults to PENDING. ACK_BY_FSE / ACK_BY_AFATDS are "
        "set only when an external receipt confirmation has actually "
        "been observed (manual analyst update until an external "
        "ingest pipeline exists).",
        "The target identity (target_id) is bound by the operations-map "
        "right-click trigger on a hostile mil_unit. Generation paths "
        "that do not supply target_entity_id MUST fail emission rather "
        "than write a malformed artifact.",
    ],
    "hard_rules": [
        "Never invent a target_id — the value must come from the "
        "operations-map right-click trigger and must resolve against "
        "kg_targets_active.",
        "The target MUST be on the active HPTL — emission fails if "
        "absent. hptl_artifact_id is required.",
        "The target MUST NOT be in {DEFEATED, DESTROYED, EXPIRED, "
        "MOOTED} per the most recent BDA / Combat Assessment. Emission "
        "fails when the target is terminated.",
        "method_of_engagement + method_of_fire_and_control are looked "
        "up directly from AGM.structured_data.agm_rows[target_id] — "
        "never authored, never parsed from the AGM markdown matrix.",
        "valid_flag / accurate_flag / timely_flag cite the specific TSS "
        "row when TSS is registered; cite analyst rationale otherwise.",
        "jdpi_id and parent_etf_eid are pulled from the referenced TMP "
        "artifact only — never invented when no TMP exists.",
        "target_category is from TARGET_CATEGORY_ENUM.",
        "type_five_o, when populated, is from TYPE_FIVE_O_ENUM.",
        "precedence is from PRECEDENCE_ENUM.",
        "routing_destination is from ROUTING_DESTINATION_ENUM.",
        "push_status defaults to PENDING. ACK_BY_FSE / ACK_BY_AFATDS "
        "are only set on external receipt confirmation; RESCINDED is "
        "only set on explicit withdrawal.",
        "target_location_mgrs is 10-digit MGRS minimum precision, WGS "
        "84 default datum.",
        TARGET_FOCUS_BINDING_HARD_RULE,
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Target identity: get_target(target_id=<id from right-click>) — "
        "resolves the hostile mil_unit's kg_id to name, category, "
        "type_five_o, location_mgrs, echelon, posture, doi, "
        "detection_source.",
        "Active target roster: list_targets(filter={target_id:<id>}) — "
        "confirms the target is in kg_targets_active and not terminated.",
        "HPTL membership: list_project_docs(filter={type:'HPTL'}) then "
        "get_project_doc — fails emission when the target is not on "
        "the active HPTL.",
        "AGM row lookup: list_project_docs(filter={type:'AGM'}) then "
        "get_project_doc — reads structured_data.agm_rows[target_id] "
        "for method_of_engagement + method_of_fire_and_control echo.",
        "TSS thresholds: list_project_docs(filter={type:'TSS'}) then "
        "get_project_doc — cites the row keyed by target_category for "
        "the valid/accurate/timely triple.",
        "TMP precision-fires routing: list_project_docs(filter={type:"
        "'TMP', target_id:<id>}) then get_project_doc — reads jdpi_id "
        "and parent_etf_eid when present.",
        "BDA / Combat Assessment posture check: list_project_docs("
        "filter={type:'BDA', target_id:<id>}) and list_project_docs("
        "filter={type:'CA', target_id:<id>}) — fails emission when the "
        "most recent assessment carries a terminal posture (DEFEATED, "
        "DESTROYED, EXPIRED, MOOTED).",
        "Collateral proximity: list_project_docs(filter={type:'NSL'}), "
        "list_project_docs(filter={type:'RTL'}), list_project_docs("
        "filter={type:'CCA-Matrix'}) — drives collateral_concern when "
        "the target lies within a protected-entity buffer.",
        "Phased concept of operations: get_phases() — current phase + "
        "decisive point + phase objectives for the dispatch context.",
    ],
    "post_emit_summary": (
        "artifact_id, target_id, target_name, target_category, "
        "precedence, valid/accurate/timely triple, push_status"
    ),
}
