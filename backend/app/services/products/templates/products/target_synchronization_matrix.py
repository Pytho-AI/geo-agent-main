"""TSM — Target Synchronization Matrix — paras 2-27 – 2-28 + App. D Table D-4.

Final Decide-phase product. Integrates the D3A picture: each HPT row maps to
specific DETECT agencies/assets, DELIVER agencies/assets, and ASSESS agencies/
assets — synchronizing collection, fires, and BDA across the targeting cycle
(paras 2-27 – 2-28, App. D paras D-11 – D-13). The TSM also serves as
the basis for updating the information collection plan and issuing the
fragmentary order after the targeting working group / targeting board (para
D-11 last sentence).

Ch. 2 (paras 2-149+) and Ch. 3 corroborate TSM as a fires-cell
product the DIVARTY targeting officer drafts; this schema is echelon-agnostic.

See templates/products/__init__.py for the assembled PRODUCT_SCHEMAS map.
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

# Doctrinal TSM column axis. The DECIDE column in
# Table D-4 splits into Priority + Category + HPTs; in this schema the row
# label IS the HPT (matrix keys are HPTs), and the priority + category are
# carried inside the decide cell. The four columns each split into Agency
# and Asset. Cells are dicts: {agency: ..., asset: ...} so
# the writer can populate both halves and the renderer prints "AGENCY /
# ASSET" inside each cell.
TSM_COL_AXIS = [
    "decide",
    "detect",
    "deliver",
    "assess",
]

SPEC = {
    "name": "TSM",
    "output_format": "pptx",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. FM 3-60 App. D
    # Table D-4 (landscape in the FM): HPT × D3A columns with split
    # agency/asset cells — PPTX truncates the split past ~8 HPTs.
    "output_formats": ["xlsx"],
    "legacy_formats": ["pptx"],
    "shape": "matrix",
    # Landscape: TSM is the widest of the targeting trio — 4 split columns
    # (each carrying Agency + Asset) plus narrative cells. Landscape gives
    # ~14" of usable width; portrait would compress agency/asset entries.
    # Matches Table D-4 layout which is itself printed landscape in
    # the FM.
    "doctrine": {
        "purpose": (
            "Final D3A integration product — for every HPT the matrix names "
            "the DETECT asset / agency, the DELIVER asset / agency, and the "
            "ASSESS asset / agency, in priority + category order. Acts as "
            "both the synchronization tool for the targeting working group "
            "AND the basis for the next FRAGO + ICSM update. Could be "
            "prepared for a specific event or per phase of the battle." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Rows = HPTs from the consumed HPTL grouped by category, in HPTL "
            "priority order. Columns: decide (HPT context — priority + "
            "category + covering NAI), detect (agency / asset / NAI), "
            "deliver (agency / asset — primary engagement system), assess "
            "(agency / asset — BDA tasking)."
        ),
    },
    # ICM (Information Collection Matrix) is referenced when a parallel ICM
    # artifact exists; the schema gracefully omits it if not present. Listed
    # explicitly here per the planning note from the audit; the runner's UI
    # prerequisite check tolerates a missing ICM since it doesn't yet exist
    # in PRODUCT_SCHEMAS.
    "consumes_artifacts": ["HPTL", "TSS", "AGM", "Information Collection Matrix"],
    "published_section_title": "Target Synchronization",
    "matrix_spec": {
        "field": "tsm_matrix",
        # Row axis is dynamic — the HPTs from the consumed HPTL grouped by
        # category. The renderer treats matrix keys as rows when row_axis is
        # missing.
        "col_axis": TSM_COL_AXIS,
        "row_label": "High-Payoff Target",
        "col_label": "D3A Synchronization",
    },
    "header_fields": {
        "area_of_operations":  HEADER_AO,
        "dtg":                 HEADER_DTG,
        "phase":               HEADER_PHASE,
        "prepared_by":         HEADER_PREPARED_BY,
        "classification":      HEADER_CLASSIFICATION,
        "hptl_artifact_id":    {"source": "upstream:HPTL", "view": "internal",
                                  "required": True,
                                  "render_label": "HPTL Reference",
                                  "depends_on": ["upstream:HPTL"],
                                  "guidance": (
                                    "Upstream HPTL — TSM rows ARE the HPTs "
                                    "from the HPTL grouped by category in "
                                    "priority order."
                                  )},
        "tss_artifact_id":     {"source": "upstream:TSS", "view": "internal",
                                  "required": False,
                                  "render_label": "TSS Reference",
                                  "depends_on": ["upstream:AGM", "upstream:TSS"],
                                  "guidance": (
                                    "Upstream TSS — when present, the detect "
                                    "column SHOULD acquire to a TLE that "
                                    "meets the TSS gate for the planned "
                                    "deliver asset (para 2-20 'HPT "
                                    "that meets all the criteria should be "
                                    "tracked until they are attacked in "
                                    "accordance with the AGM')."
                                  )},
        "agm_artifact_id":     {"source": "upstream:AGM", "view": "internal",
                                  "required": True,
                                  "render_label": "AGM Reference",
                                  "depends_on": ["upstream:AGM"],
                                  "guidance": (
                                    "Upstream AGM — the deliver column draws "
                                    "from the AGM how_engage column "
                                    "(weapon-system selection is the AGM's "
                                    "call; the TSM maps that selection to the "
                                    "actual unit / asset). Required because "
                                    "the workflow derives delivery from the AGM."
                                  )},
        "icm_artifact_id":     {"source": "upstream:Information Collection Matrix",
                                  "view": "internal",
                                  "required": False,
                                  "render_label": "ICM Reference",
                                  "depends_on": ["upstream:Information Collection Matrix"],
                                  "guidance": (
                                    "Upstream Information Collection Matrix / "
                                    "ICSM — when present, the detect column "
                                    "SHOULD reference the NAI + collection "
                                    "asset already tasked by the ICM ("
                                    "'the ICSM "
                                    "allows the targeting team to "
                                    "effectively build an accurate and "
                                    "detailed TSM'). When ICM has not been "
                                    "produced yet, the TSM nominates assets "
                                    "and the next ICM cycle picks them up "
                                    "."
                                  )},
    },
    "paragraph_fields": [
        {"name": "tsm_matrix",
         "view": "published",
         "shape": "grid_table",
         "render_label": "Targeting Synchronization Matrix",
         "required": True,
         "depends_on": [
             "upstream:AGM",
             "upstream:HPTL",
         ],
         "guidance": (
            "Per-HPT × 4-column integrated D3A matrix. "
            "Rows = HPTs from the consumed HPTL grouped by "
            "category in HPTL priority order. Columns:\n"
            "  - decide = DECIDE context for the HPT. Carry priority "
            "(integer), category (TARGET_CATEGORY_ENUM), and any covering "
            "NAI number. Format: 'P{n} · {category} · NAI {id}' (e.g., 'P1 · "
            "Fire Support · NAI 14').\n"
            "  - detect = DETECT agency + asset. Format: '{agency} / "
            "{asset}' (e.g., 'FAB / Q-53', 'CAB / FMV', 'G-2 / JSTARS', "
            "'E-MIB / Rivet Joint', 'CEMA / NOS'). Be specific about WHO "
            "and WHAT. When multiple assets "
            "are tasked redundantly, separate with '; '. The collection "
            "manager owns this column.\n"
            "  - deliver = DELIVER agency + asset / firing unit. Format: "
            "'{agency} / {asset}' (e.g., '1-FAB / 1-MLRS', '2-Avn / 2 × "
            "AH-64E', 'AI / F-35 + F-16', 'DIVARTY / Artillery'). Pulls from "
            "the consumed AGM how_engage column — the AGM names the SYSTEM, "
            "the TSM names the UNIT. Para D-11 step three: 'determine which "
            "attack asset or resource will be used to attack each target'.\n"
            "  - assess = ASSESS agency + asset for BDA. Format: '{agency} / "
            "{asset}' (e.g., 'E-MIB / FMV', 'G-2 / NOS', 'CAB / AH-64E "
            "post-strike'). Para D-11 step four: 'determine and prioritize "
            "which assets will assess how well the attack was executed and "
            "whether desired effects were created'. Pulls from the consumed "
            "HPTL bda_required + bda_time_window workpaper fields.\n"
            "All cells cite source in _provenance: HPTL artifact_id (for "
            "decide priority + category), ICM / Annex L Intel artifact_id "
            "(for detect tasking), AGM artifact_id (for deliver selection), "
            "OPORD §3.d (for assess BDA requirements). Both nonlethal and "
            "lethal capabilities approved in the targeting coordination "
            "board appear in the same TSM."
         )},
        {"name": "nai_to_hpt_crosswalk",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "NAI to HPT Crosswalk",
         "required": False,
         "guidance": (
            "'Consider assigning a NAI to "
            "the target and enter the number on the TSM.' This crosswalk "
            "lists every NAI that covers an HPT row in the matrix, with "
            "the activating event the NAI watches for. Feeds the ICM and "
            "Annex L Intel update issued as a FRAGO after the targeting "
            "working group."
         ),
         "item_subfields": [
             {"name": "nai_id", "render_label": "NAI",
              "guidance": "Named area of interest identifier (e.g., 'NAI 14')."},
             {"name": "hpt", "render_label": "HPT",
              "guidance": "HPT name matching the matrix row label."},
             {"name": "activating_event", "render_label": "Activating Event",
              "provenance_required": True,
              "guidance": "What activity inside the NAI triggers HPT engagement consideration (e.g., 'enemy SP artillery battery occupies firing position', 'IADS radar emits in target-tracking mode')."},
             {"name": "collection_asset", "render_label": "Collection Asset",
              "guidance": "Primary collection asset tasked to watch this NAI (matches the matrix detect cell for the same HPT)."},
         ]},
        {"name": "redundancy_and_overtaxation_check",
         "view": "published",
         "shape": "dict",
         "render_label": "Redundancy and Overtaxation Check",
         "required": False,
         "guidance": (
            "'This provides the targeting working "
            "group the checks to ensure all assets are used and that assets "
            "or agencies are not overtaxed.' Surface the working group's "
            "review of asset loading — which assets are tasked across "
            "multiple HPTs, which agencies are at or above capacity, where "
            "redundant means are planned1 step three "
            "('consider redundant means to attack each target')."
         ),
         "subfields": [
            "assets_tasked_multiple_hpts",
            "agencies_at_or_over_capacity",
            "redundant_means_planned",
            "untasked_assets",
         ],
         "subfield_guidance": {
            "assets_tasked_multiple_hpts": "Single assets tasked to detect or deliver against more than one HPT — list the asset and the HPT count (e.g., 'JSTARS — 4 HPTs in Phase 2'). Risk indicator for the working group.",
            "agencies_at_or_over_capacity": "Agencies whose total tasking exceeds doctrinal employment thresholds (e.g., 'CEMA cell at 8 tasks vs 6-task SOP cap'). Cite the cap source.",
            "redundant_means_planned": "HPTs where 'redundant means' guidance is exercised — e.g., 'BM-30 detected by FAB/Q-53 AND E-MIB/Rivet Joint; delivered by 1-FAB/MLRS AND 2-Avn/AH-64E'. Lists the HPT and the redundant pairing.",
            "untasked_assets": "Available assets the working group did not task — visible-capability list for the targeting board to review.",
         }},
        {"name": "icsm_alignment_note",
         "view": "published",
         "shape": "string",
         "render_label": "ICSM Alignment",
         "required": False,
         "provenance_required": True,
         "depends_on": [
             "upstream:AGM",
             "upstream:HPTL",
             "upstream:TSS",
         ],
         "guidance": (
            "'In conjunction with the other targeting "
            "products (HPTL, TSS, AGM), the ICSM allows the targeting team "
            "to effectively build an accurate and detailed TSM.' One short "
            "paragraph noting the ICSM artifact this TSM aligns with — "
            "which NAIs and collection assets in the ICSM correspond to the "
            "detect column entries here. Cite the ICSM artifact_id when "
            "available. When no ICSM exists yet, note that the next ICSM "
            "cycle picks up the detect tasking nominated in this TSM."
         )},
        {"name": "fragmentary_order_update_note",
         "view": "published",
         "shape": "string",
         "render_label": "FRAGO Update Note",
         "required": False,
         "guidance": (
            "'Once completed, the TSM "
            "serves as a basis for updating the information collection plan "
            "and issuing a fragmentary order once the targeting working "
            "group and targeting board concludes their sessions.' One short "
            "paragraph noting the FRAGO that will publish the TSM-derived "
            "tasking (or 'pending working-group conclusion' before approval)."
         )},
    ],
    "subtleties": [
        "TSM is the FINAL integration artifact of the Decide phase. Pulls HPTL (priority + category for the decide column), TSS (detect → deliver gating), AGM (deliver weapon selection) into a single synchronized D3A picture.",
        "The TSM is the basis for updating the ICM and issuing the next FRAGO once the targeting working group + targeting board conclude. Capture that downstream linkage in fragmentary_order_update_note.",
        "Build the TSM in order — (1) Select / update HPTL → fill decide column; (2) Determine and prioritize collection assets → fill detect column with NAIs; (3) Determine attack asset for each target → fill deliver column; (4) Determine and prioritize BDA assets → fill assess column.",
        "Could be prepared for a specific event OR for each phase of the battle. The phase header field disambiguates which TSM applies; a single operation typically carries one TSM per phase plus event-specific TSMs for major engagements.",
        "Both nonlethal and lethal capabilities approved in the targeting coordination board appear in the same TSM. CEMA / cyber / IO assets populate detect and deliver columns alongside kinetic fires.",
        "REDUNDANCY check: 'consider redundant means to attack each target'. Capture in redundancy_and_overtaxation_check.redundant_means_planned. Mobile HPTs require detect-track-detect cycles, which means more than one collection asset on the same target (mobile HPT targets must be detected and tracked to maintain current target location).",
        "OVERTAXATION check1 step three: 'ensure all assets are used and that assets or agencies are not overtaxed'. JSTARS, Rivet Joint, and FMV-equipped UAS are commonly oversubscribed — surface this for the working group to rebalance.",
        "ICSM cross-feed:ICSM and TSM are mutually reinforcing — ICSM synchronizes information collection horizontally/vertically across echelons; TSM is the D3A view per HPT. When both exist, detect column entries should reference the ICSM-tasked asset.",
        "Information Collection Matrix (ICM) is being added in a parallel agent and may not yet be in PRODUCT_SCHEMAS. The icm_artifact_id header field is optional — the schema gracefully omits it when ICM hasn't run yet. The ref:Information Collection Matrix source label hooks up automatically once ICM is registered.",
        "Ch. 2 (paras 2-149+) and Ch. 3 corroborate TSM as a fires-cell product the DIVARTY targeting officer drafts; the wargaming-output box ('refined draft TSM, HPTL, TSS, and AGM') in Fig 3-2 names the four products explicitly as the deliverable set.",
        "Per IDX 26: every cell entry + every crosswalk row + every redundancy/overtaxation entry cites source in _provenance.",
    ],
    "hard_rules": [
        "TSM rows are exactly the HPTs from the consumed HPTL — never invent rows, never drop rows. Order matches HPTL priority and rows group by category.",
        "Every row carries values in ALL four columns (decide, detect, deliver, assess). A row missing detect or deliver is a non-synchronized HPT — that condition is a working-group risk that the analyst MUST surface; the cell can carry 'UNRESOLVED — needs working-group rebalance' but must not be silently blank.",
        "deliver column MUST align with the consumed AGM's how_engage column for the same HPT. The TSM names the UNIT executing the AGM-named SYSTEM.",
        "When ICM artifact exists, detect entries cite the ICM artifact_id.When ICM doesn't exist yet, the writer notes that in icsm_alignment_note and proceeds with TSM-nominated tasking.",
        "When TSS artifact exists, detect column entries acquire to a TLE that meets the TSS gate for the planned deliver asset. When TSS doesn't exist, the writer flags the gap in the cell's provenance.",
        "decide column format: 'P{n} · {category} · NAI {id}' when an NAI covers the HPT; 'P{n} · {category}' otherwise — never free-text narrative in the decide cell.",
        "Per IDX 26: every analytical field carries _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream HPTL: list_project_docs(filter={type:'HPTL'}) then get_project_doc(tag=<latest>)",
        "Upstream TSS: list_project_docs(filter={type:'TSS'}) then get_project_doc(tag=<latest>)",
        "Upstream AGM: list_project_docs(filter={type:'AGM'}) then get_project_doc(tag=<latest>)",
        "Upstream ICM / ICSM (optional — may not exist yet): list_project_docs(filter={type:'Information Collection Matrix'})",
        "OPORD §3.d targeting guidance + Annex D (Fires) friendly fires OOB + Annex L (Intel) collection plan: get_project_doc(tag='OPORD')",
        "Threat structure (HPT unit context — now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Operations overlay control measures (synchronization geometry — NAI / TAI / OBJ / EA / axis bind D3A windows): get_spatial_overlay()",
        "Phased concept of operations (D3A synchronization keyed to phases): get_phases() — current phase + decisive point + phase objectives",
        "FRAGO updates: list_project_docs(filter={type:'FRAGO'})",
        "Standing NAI list: get_project_doc(tag='NAI_LIST') when present",
        "Friendly fires + ISR OOB: get_project_doc(tag='OOB_FRIENDLY') or OPORD Annex D",
    ],
    "post_emit_summary": "artifact_id, HPT row count, count by category, count of HPTs with redundant deliver means, count of unresolved-tasking rows, ICM alignment status",
}
