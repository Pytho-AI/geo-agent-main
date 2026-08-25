"""Event-Matrix — NAI × indicator × time × DP spreadsheet sibling of
Event Template.

Per scratch/ibl/reports/EXCEL_DOCTRINAL_ALIGNMENT.md §3: ATP 2-01.3
Fig 6-13 IS the matrix. The parent Event Template carries the graphic
(PPTX overlay) AND the matrix; this XLSX sibling extracts the matrix
half so analysts can filter rows by NAI, by time-phase, by decision
point during collection planning.
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
    "name": "Event-Matrix",
    "output_format": "xlsx",
    "output_formats": ["xlsx"],
    "shape": "row",
    "doctrine": {
        "citation": "ATP 2-01.3 Fig 6-13 (Event Matrix)",
        "purpose": (
            "XLSX surface for the Event Matrix half of the Event Template "
            "doctrinal pair. Spreadsheet-canonical per "
            "EXCEL_DOCTRINAL_ALIGNMENT.md §3 — analysts filter NAIs by "
            "time-phase, by indicator, by associated decision point during "
            "collection planning. Parent Event Template carries the graphic "
            "PPTX overlay; both products consume the same upstream "
            "phase + threat-COA + spatial-overlay data." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows sortable; default ordering is time_window then NAI.",
    },
    "order_by": {"field": "time_window_start", "direction": "asc"},
    "row_source": "kg_event_matrix_rows",
    "group_by": "time_phase",
    "consumes_artifacts": ["Event Template", "SITEMP", "Threat COA Statement", "PIR", "DonovianDoctrine"],
    "published_section_title": "Event Matrix",
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "phase_or_critical_event": {"source": "session", "view": "header", "required": True,
                                      "render_label": "Phase or Critical Event",
                                      "guidance": "Phase tag the matrix covers — scopes the row count."},
        "prepared_by":        HEADER_PREPARED_BY,
        "parent_event_template_artifact_id": {"source": "upstream:Event Template",
                                                "view": "internal", "required": False,
                                                "render_label": "Parent Event Template",
                                                "depends_on": ["upstream:Event Template"],
                                                "guidance": "Companion Event Template graphic when present."},
        "pir_artifact_id":    {"source": "upstream:PIR", "view": "internal", "required": False,
                                "render_label": "PIR Reference",
                                "depends_on": ["upstream:PIR"],
                                "guidance": (
                                    "PIR artifact whose indicators are decomposed into this "
                                    "matrix's NAI × indicator × time × DP rows. Each Event "
                                    "Matrix indicator typically traces back to a PIR's "
                                    "indicators field — cite the PIR ref so the analyst can "
                                    "walk back to the commander-approved question."
                                )},
        "classification":     HEADER_CLASSIFICATION,
    },
    "row_fields": {
        "nai_id":            {"source": "entity:id", "view": "published",
                                "required": True, "render_label": "NAI"},
        "nai_name":          {"source": "entity:name", "view": "published",
                                "required": False, "render_label": "NAI Name"},
        "indicator":         {"source": "analytical", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Indicator",
                                "guidance": "Observable that confirms / denies a threat COA branch."},
        "time_phase":        {"source": "analytical", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Time Phase",
                                "guidance": "Time-phase tag (e.g. 'D-2 to D-Day') the NAI is active."},
        "time_window_start": {"source": "analytical", "view": "published",
                                "required": False, "render_label": "Window Start DTG"},
        "time_window_end":   {"source": "analytical", "view": "published",
                                "required": False, "render_label": "Window End DTG"},
        "associated_dp":     {"source": "analytical", "view": "published",
                                "required": False, "provenance_required": True,
                                "render_label": "Decision Point",
                                "guidance": "DP the indicator feeds. Cross-reference DST-Matrix DP IDs."},
        "tai_id":            {"source": "analytical", "view": "published",
                                "required": False, "render_label": "TAI",
                                "guidance": "Targeted Area of Interest when the NAI is paired with a TAI."},
        "collection_asset":  {"source": "analytical", "view": "published",
                                "required": False, "provenance_required": True,
                                "render_label": "Collection Asset",
                                "guidance": "Asset assigned to observe this indicator (SIR-style)."},
        "report_to":         {"source": "analytical", "view": "published",
                                "required": False, "render_label": "Report To"},
    },
    "hard_rules": [
        "Never invent NAI/TAI IDs — only IDs present in the operations overlay (get_spatial_overlay).",
        "Every indicator and its DP linkage cites the upstream Threat COA Statement / SITEMP source.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Operations overlay NAIs / TAIs: get_spatial_overlay()",
        "Phased concept of operations: get_phases()",
        "Threat doctrine (REQUIRED — anchors indicator interpretation per OPFOR signature behaviors): get_project_doc(tag='DonovianDoctrine')",
        "Threat COAs (indicator source): list_project_docs(filter={type:'Threat COA Statement'})",
        "SITEMP (NAI placement context): list_project_docs(filter={type:'SITEMP'})",
        "Parent Event Template when present: list_project_docs(filter={type:'Event Template'})",
    ],
    "post_emit_summary": "artifact_id, NAI row count, phase distribution, DP coverage",
}
