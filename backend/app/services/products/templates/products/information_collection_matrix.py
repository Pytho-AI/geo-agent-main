"""Information Collection Matrix — ATP 2-01.3 Step 4 paras 6-71 to 6-72 + Fig 6-15.

Per para 6-71: "The completed event template and event matrix form the basis
for planning collection strategies, synchronizing intelligence with friendly
operations, and developing the DST and matrix and information collection
matrix (see figure 6-14 and figure 6-15)."

Per Fig 6-15 the information collection matrix tabulates the PIRs from the
OPORD against the doctrinal collection columns — indicators, specific
information requirement (SIR), NAI / TAI, start / stop time windows, the
collection assets (capable / tasked-primary / tasked-alternate / requested
per asset), the decision points fed, and the target area of interest count.

This product is the consolidation layer that bridges Step-4 IPOE outputs
(SITEMP NAIs / DPs, Event Template indicators, DST decision points) into
the OPORD Annex L collection tasking. Doctrinally it sits SIBLING to the
DST under the Event Template + Matrix (para 6-71).

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
    "name": "Information Collection Matrix",
    # Doctrinally table-heavy (Fig 6-15 is a wide tabular matrix). DOCX only
    # — landscape for the column count.
    "output_format": "docx",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. ATP 2-01.3
    # Fig 6-15: PIR × {indicator, SIR, NAI, time window, asset, report-to,
    # DP, TAI} — already overflows DOCX landscape today.
    "output_formats": ["xlsx"],
    "legacy_formats": ["docx"],
    "shape": "matrix",
    "doctrine": {
        "purpose": (
            "Step-4 IPOE consolidation: tabulates each PIR from the OPORD "
            "against the collection columns — indicators, specific "
            "information requirement (SIR), NAI / TAI, start / stop time "
            "windows, collection assets, decision points fed. Developed off "
            "the completed event template + matrix. Bridges Step-4 IPOE "
            "NAI / DP outputs into OPORD Annex L collection tasking." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Rows grouped by PIR (OPORD §3.d order). Within a PIR, rows "
            "ordered by SIR sequence then by NAI ID."
        ),
    },
    # Tier 2 IPOE Step-4 inputs + Knowledgeability Brief (HUMINT
    # source-capability assessment feeds collection planning per source).
    "consumes_artifacts": ["Event Template", "Decision Support Template",
                            "Threat COA Statement", "OPORD"],
    # matrix_spec documents the doctrinal axes per Fig 6-15. The actual data
    # carrier is the `collection_rows` paragraph_field below — each row's
    # `pir` is the row-axis value and the col_axis fields populate the
    # remaining columns. row_axis is dynamic (per-session PIRs from OPORD);
    # col_axis is doctrinally fixed per Fig 6-15.
    "matrix_spec": {
        "field": "collection_rows",
        "row_axis_source": "opord_pirs",
        "row_label": "Priority Intelligence Requirement (PIR)",
        "col_axis": ["indicator", "specific_information_requirement",
                      "nai_or_tai", "start_window", "stop_window",
                      "collection_asset", "report_to", "decision_point"],
        "col_label": "Collection Column",
    },
    "header_fields": {
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "opord_artifact_id":  {"source": "upstream:OPORD", "view": "internal",
                                "required": True,
                                "render_label": "OPORD Reference",
                                "depends_on": ["upstream:OPORD"],
                                "guidance": (
                                    "OPORD whose §3.d PIRs the matrix tasks "
                                    "against. The row axis IS the PIR list "
                                    "from the OPORD — without an OPORD "
                                    "reference the matrix has no source of "
                                    "PIRs. Cite by tag (e.g., 'OPORD' or "
                                    "'FRAGO-3')."
                                )},
        "event_template_artifact_id": {"source": "upstream:Event Template", "view": "internal",
                                         "required": False,
                                         "render_label": "Event Template Reference",
                                         "depends_on": ["upstream:Event Template"],
                                         "guidance": (
                                             "Upstream Event Template + Matrix the "
                                             "indicators / NAIs trace to."
                                         )},
        "dst_artifact_id":    {"source": "upstream:Decision Support Template", "view": "internal",
                                "required": False,
                                "render_label": "DST Reference",
                                "depends_on": ["upstream:Decision Support Template"],
                                "guidance": (
                                    "Sibling DST artifact — the decision points the "
                                    "matrix feeds. The DST and ICM are sibling products "
                                    "downstream of the Event Template."
                                )},
        "pir_artifact_id":    {"source": "upstream:PIR", "view": "internal",
                                "required": False,
                                "render_label": "PIR Reference",
                                "guidance": (
                                    "PIR artifact whose questions the ICM tasks collection "
                                    "against. ICM rows ARE the PIR × indicator × SIR × asset "
                                    "decomposition — without a PIR ref the matrix has no "
                                    "source of intelligence requirements."
                                )},
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal",
                                "required": False,
                                "render_label": "Threat COA Statement Reference",
                                "depends_on": ["upstream:Threat COA Statement"],
                                "guidance": "Parent Threat COA Statement the collection plan supports."},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "collection_rows",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Information Collection Matrix",
         "required": True,
         "depends_on": [
             "upstream:Event Template",
             "upstream:OPORD",
         ],
         "guidance": (
             "One row per (PIR × SIR × NAI) tuple. The row axis is the PIR "
             "list from the OPORD's §3.d (e.g., 'Where along AA1 will the "
             "375th BTG initiate shaping operations for an area defense?'). "
             "Each PIR may carry multiple indicator / SIR / NAI rows. The "
             "asset columns code each cell as C (capable), TP (tasked as "
             "primary), TA (tasked as alternate), R (requested), or NT "
             "(not tasked) — but in this matrix the collection_asset column "
             "collapses that per-asset coding into a single assigned-asset "
             "designation per row (the per-asset cross tabulation belongs "
             "in the Annex L synch matrix downstream)."
         ),
         "item_subfields": [
             {"name": "pir", "render_label": "Priority Intelligence Requirement",
              "provenance_required": True,
              "guidance": (
                 "Verbatim PIR text from the OPORD §3.d (e.g., 'Where along "
                 "AA1 will the 375th BTG initiate shaping operations for an "
                 "area defense?'). Cite OPORD / FRAGO artifact_id + paragraph "
                 "in _provenance."
              )},
             {"name": "indicator", "render_label": "Indicator",
              "provenance_required": True,
              "guidance": (
                 "Observable indicator answering the PIR. Should match the "
                 "upstream Event Matrix indicator phrasing where applicable."
              )},
             {"name": "specific_information_requirement", "render_label": "Specific Information Requirement (SIR)",
              "provenance_required": True,
              "guidance": (
                 "Decomposes the indicator into one observable collection "
                 "tasking statement (e.g., 'Report communications coordinating "
                 "enemy movement', 'Report movement of fighters into defensive "
                 "positions'). The SIR is the collection-asset-actionable "
                 "form of the indicator."
              )},
             {"name": "nai_or_tai", "render_label": "NAI / TAI",
              "provenance_required": True,
              "guidance": (
                 "NAI ID (from Event Template) or TAI label where the "
                 "indicator is collected. Multi-NAI allowed (comma-separated). "
                 "TAI = target area of interest."
              )},
             {"name": "start_window", "render_label": "Start",
              "guidance": "Earliest collection window (H-hour relative, e.g., 'H-48', or DTG)."},
             {"name": "stop_window", "render_label": "Stop",
              "guidance": "Latest collection window (e.g., 'H+2', or DTG)."},
             {"name": "collection_asset", "render_label": "Collection Asset",
              "provenance_required": True,
              "guidance": (
                 "Primary assigned collection asset. Use the asset "
                 "designation (e.g., '3/67 CAV REG', 'Shadow UAS', "
                 "'Prophet/LLVI', 'HCT', 'COMINT', 'GEOINT'). Echelon prefix "
                 "where helpful (e.g., 'BDE Shadow', 'EAB GEOINT')."
              )},
             {"name": "asset_status", "render_label": "Asset Status",
              "enum": ["capable", "tasked_primary", "tasked_alternate",
                        "requested", "not_tasked"],
              "guidance": (
                 "Cell coding: capable (C) / tasked as primary (TP) / tasked "
                 "as alternate (TA) / requested (R) / not tasked (NT). Drives "
                 "how the assignment appears in the downstream Annex L "
                 "collection plan."
              )},
             {"name": "report_to", "render_label": "Report To",
              "guidance": (
                 "Echelon / cell the collection results are reported to "
                 "(e.g., 'BDE S-2', 'V Corps G-2 CMD'). Drives the "
                 "reporting chain in Annex L."
              )},
             {"name": "decision_point", "render_label": "Decision Point",
              "guidance": (
                 "DP ID (from DST) this collection row feeds. Cross-reference "
                 "to the sibling DST's decision_points[].id."
              )},
             {"name": "target_area_of_interest", "render_label": "Target Area of Interest",
              "guidance": (
                 "TAI label / count. TAI = target area of interest where "
                 "lethal / non-lethal effects are planned. Optional — "
                 "populated when this collection row also feeds a fires DP."
              )}]},
        {"name": "collection_summary",
         "view": "published",
         "shape": "dict",
         "render_label": "Collection Plan Summary",
         "required": False,
         "depends_on": [
             "upstream:OPORD",
         ],
         "guidance": (
             "Brief narrative summary keyed to the collection-plan "
             "synchronization activities. Optional — used when the matrix "
             "needs an analyst rollup for the OPORD §3.d / Annex L narrative."
         ),
         "subfields": ["pir_coverage", "asset_loading", "coordination_required",
                        "gaps"],
         "subfield_guidance": {
             "pir_coverage": "Which PIRs are fully covered (indicator + SIR + asset + NAI) vs partial.",
             "asset_loading": "Per-asset row count — highlights over-tasked assets that need EAB requests.",
             "coordination_required": "Cross-AO collection (NAIs in adjacent commander's AO) and the coordination required.",
             "gaps": "PIRs with no collection coverage — the request-from-higher list.",
         }}],
    "subtleties": [
        "The ICM is built off the completed Event Template + Matrix — the indicators / NAIs / time windows trace upstream. The PIR row axis comes separately from the OPORD §3.d.",
        "Asset columns are a per-asset cross-tabulation (Brigade / EAB / each battalion / each enabler) with C / TP / TA / R / NT cell codes. This schema collapses that into a single primary-asset designation per row with an asset_status enum — the per-asset cross tabulation belongs in the Annex L synch matrix downstream.",
        "The SIR (specific information requirement) is the collection-asset-actionable form of the indicator — it's what gets handed to the collection-asset operator as a tasking. Indicators are observables; SIRs are operational tasks.",
        "TAIs (target areas of interest) appear in the right-most column as a count — they enter the matrix when a collection row also feeds a fires DP (the NAI doubles as a TAI for the fires effect).",
        "The ICM is the SIBLING of the DST — both downstream of the Event Template, both feeding OPORD §3.d / Annex L. The DST gives the commander decision triggers; the ICM gives the collection cell tasking.",
        "Every PIR cites its OPORD basis; every indicator cites the upstream Event Matrix; every NAI cites the Event Template / SITEMP basis.",
        "In some instances the staff may disseminate the event template as a collection graphic to support intelligence planning and collection by other units — the ICM is the matrix companion to that dissemination.",
        "asset_status enum maps to cell coding: capable (C) / tasked_primary (TP) / tasked_alternate (TA) / requested (R) / not_tasked (NT). Use 'requested' for EAB asks."],
    "hard_rules": [
        "Every collection_rows row MUST cite the OPORD basis for its PIR in _provenance — PIRs are not invented; they come from §3.d.",
        "Every indicator MUST trace to the upstream Event Matrix where one exists (cite Event Template artifact_id + indicator phrasing). Indicators introduced fresh in the ICM (not in the Event Matrix) are a gap and must be flagged.",
        "Every NAI reference (nai_or_tai) MUST resolve to a NAI present in the cited Event Template's named_areas_of_interest set OR carry a TAI label.",
        "Every decision_point reference MUST resolve to a DP present in the cited DST's decision_points set.",
        "Every row MUST have collection_asset + asset_status populated — an ICM row with no assigned asset is a gap, not a tasking.",
        "asset_status MUST use the enum values (capable / tasked_primary / tasked_alternate / requested / not_tasked) — these map 1:1 to cell coding (C / TP / TA / R / NT).",
        "Every analytical claim cites source in _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "OPORD PIRs: get_project_doc(tag='OPORD') §3.d",
        "Latest FRAGO PIR updates: list_project_docs(filter={type:'FRAGO'}) then get_project_doc(tag=<latest>) §3.d",
        "Upstream Event Template + Matrix: list_project_docs(filter={type:'Event Template'}) then get_project_doc(tag=<latest>)",
        "Sibling DST (decision-point references): list_project_docs(filter={type:'Decision Support Template'}) then get_project_doc(tag=<latest>)",
        "Parent Threat COA Statement: list_project_docs(filter={type:'Threat COA Statement'}) then get_project_doc(tag=<latest>)",
        "Per-COA SITEMPs (NAI source if Event Template absent): list_project_docs(filter={type:'SITEMP'})",
        "Phased concept of operations (PRIMARY — collection windows per phase; NAIs and asset taskings key off phase boundaries): get_phases() — current phase + decisive point + phase objectives",
        "Operations overlay control measures (NAIs / AO / boundaries / phase lines bound the collection geography): get_spatial_overlay()",
        "Collection-asset list (Annex L / unit SOP): get_project_doc(tag='ANNEX_L_INTEL') if present"],
    "post_emit_summary": "artifact_id, PIR coverage (covered / partial / gap), row count, asset utilization",
}
