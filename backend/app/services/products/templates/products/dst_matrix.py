"""DST-Matrix — DP × {trigger, decision, options, effect, time, assets}
spreadsheet sibling of Decision Support Template.

Per scratch/ibl/reports/EXCEL_DOCTRINAL_ALIGNMENT.md §3: ATP 2-01.3
Fig 6-14 is a two-panel product (map graphic + DP matrix). This XLSX
sibling carries the DP matrix only; parent DST renders the graphic
(PPTX) plus the matrix.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "DST-Matrix",
    "output_format": "xlsx",
    "output_formats": ["xlsx"],
    "shape": "row",
    "doctrine": {
        "citation": "ATP 2-01.3 Fig 6-14 (Decision Support Template — matrix panel)",
        "purpose": (
            "XLSX surface for the DP matrix half of the Decision Support "
            "Template doctrinal pair. Spreadsheet-canonical per "
            "EXCEL_DOCTRINAL_ALIGNMENT.md §3 — analysts filter DPs by "
            "trigger, by phase, by required-effect during wargaming and "
            "during commander brief prep. Parent DST carries the map "
            "graphic." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows sortable; default ordering is phase then DP ID.",
    },
    "order_by": {"field": "dp_id", "direction": "asc"},
    "row_source": "kg_decision_points",
    "group_by": "phase",
    "consumes_artifacts": ["Decision Support Template", "Event Template", "DSM", "PIR"],
    "published_section_title": "Decision Points",
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "phase_or_critical_event": {"source": "session", "view": "header", "required": True,
                                      "render_label": "Phase or Critical Event"},
        "prepared_by":        HEADER_PREPARED_BY,
        "parent_dst_artifact_id": {"source": "upstream:Decision Support Template",
                                     "view": "internal", "required": False,
                                     "render_label": "Parent DST",
                                     "depends_on": ["upstream:Decision Support Template"],
                                     "guidance": "Companion Decision Support Template graphic when present."},
        "pir_artifact_id":    {"source": "upstream:PIR", "view": "internal", "required": False,
                                "render_label": "PIR Reference",
                                "depends_on": ["upstream:PIR"],
                                "guidance": (
                                    "PIR artifact whose questions drive the DPs in this "
                                    "matrix. Each DP row's trigger maps back to a PIR's "
                                    "indicators — cite the PIR ref so the matrix carries the "
                                    "commander-approved intelligence requirement that "
                                    "justifies each decision."
                                )},
        "classification":     HEADER_CLASSIFICATION,
    },
    "row_fields": {
        "dp_id":         {"source": "entity:id", "view": "published",
                            "required": True, "render_label": "DP"},
        "name":          {"source": "entity:name", "view": "published",
                            "required": False, "render_label": "DP Name"},
        "phase":         {"source": "analytical", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "Phase"},
        "trigger":       {"source": "analytical", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "Trigger",
                            "guidance": "Observable condition that fires the DP — usually one or more Event-Matrix indicators."},
        "decision":      {"source": "analytical", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "Decision",
                            "guidance": "The commander's go/no-go choice when trigger fires."},
        "options":       {"source": "analytical", "view": "published",
                            "required": False, "provenance_required": True,
                            "render_label": "Options",
                            "guidance": "Branches available to the commander at the DP."},
        "expected_effect": {"source": "analytical", "view": "published",
                              "required": False, "provenance_required": True,
                              "render_label": "Effect",
                              "guidance": "Desired effect each branch produces."},
        "time_window":   {"source": "analytical", "view": "published",
                            "required": False, "render_label": "Time Window",
                            "guidance": "Time window the DP is live (e.g. 'D-1 0600Z to D+1 1800Z')."},
        "assets_required": {"source": "analytical", "view": "published",
                              "required": False, "provenance_required": True,
                              "render_label": "Assets",
                              "guidance": "Assets required to execute the decision."},
        "linked_nai_ids": {"source": "analytical", "view": "workpaper",
                             "required": False, "render_label": "Linked NAIs",
                             "guidance": "Event-Matrix NAI IDs whose indicators feed the trigger."},
    },
    "hard_rules": [
        "Never invent DP IDs — only IDs present in get_phases / get_spatial_overlay.",
        "Every trigger cites the underlying Event-Matrix indicator(s) or sensor source.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Phased concept of operations + decision points: get_phases()",
        "Operations overlay (DP placement context): get_spatial_overlay()",
        "Companion Event Template / Event-Matrix (NAI → trigger linkage): list_project_docs(filter={type:'Event Template'}) / list_project_docs(filter={type:'Event-Matrix'})",
        "Parent DST when present: list_project_docs(filter={type:'Decision Support Template'})",
        "DSM (paired Decision Support Matrix) when present: list_project_docs(filter={type:'DSM'})",
    ],
    "post_emit_summary": "artifact_id, DP row count, phase distribution",
}
