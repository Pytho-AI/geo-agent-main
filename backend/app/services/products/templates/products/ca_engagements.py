"""CA-Engagements — per-engagement spreadsheet sibling of Combat Assessment.

Per scratch/ibl/reports/EXCEL_DOCTRINAL_ALIGNMENT.md §3 (hybrid candidate):
the per-engagement rows (engagements_assessed / mea_findings) are filterable
by MOE status, weapon, target — spreadsheet-native. The parent CA carries
the executive summary, rollups, and recommendations as DOCX narrative.

This product is the engagements ledger ONLY — one row per assessed
engagement with PDA / FDA / MEA columns. Drives the assess-phase working
group's row-by-row review.
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
    "name": "CA-Engagements",
    "output_format": "xlsx",
    "output_formats": ["xlsx"],
    "shape": "row",
    "doctrine": {
        "citation": "FM 3-60 paras 2-70 – 2-82 (Combat Assessment)",
        "purpose": (
            "XLSX surface for the per-engagement assessment ledger that backs "
            "the Combat Assessment narrative. Spreadsheet-canonical per "
            "EXCEL_DOCTRINAL_ALIGNMENT.md §3 — analysts filter by MOE status "
            "(success / partial / fail), by weapon system, by target category "
            "during assess-phase review. Parent CA carries the executive "
            "summary, rollups, and reattack recommendations." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows sortable; default order is engagement DTG ascending.",
    },
    "order_by": {"field": "engagement_dtg", "direction": "asc"},
    "row_source": "kg_engagements",
    "group_by": "moe_status",
    "consumes_artifacts": ["CA", "HPTL", "BDA"],
    "published_section_title": "Engagements Assessed",
    "header_fields": {
        "dtg":                  HEADER_DTG,
        "area_of_operations":   HEADER_AO,
        "assess_window_start":  {"source": "session", "view": "header", "required": True,
                                   "render_label": "Window Start DTG",
                                   "guidance": "Earliest engagement DTG in scope. Drives the row filter."},
        "assess_window_end":    {"source": "session", "view": "header", "required": True,
                                   "render_label": "Window End DTG",
                                   "guidance": "Latest engagement DTG in scope."},
        "prepared_by":          HEADER_PREPARED_BY,
        "parent_ca_artifact_id": {"source": "upstream:CA", "view": "internal", "required": False,
                                    "depends_on": ["upstream:CA"],
                                    "render_label": "Parent CA",
                                    "guidance": "Companion Combat Assessment narrative when present."},
        "classification":       HEADER_CLASSIFICATION,
    },
    "row_fields": {
        "engagement_id":   {"source": "entity:id", "view": "published",
                              "required": True, "render_label": "Engagement ID"},
        "engagement_dtg":  {"source": "entity:engagement_dtg", "view": "published",
                              "required": True, "render_label": "DTG"},
        "target_id":       {"source": "entity:target_id", "view": "published",
                              "required": True, "render_label": "Target"},
        "weapon_system":   {"source": "entity:weapon_system", "view": "published",
                              "required": True, "render_label": "Weapon"},
        "moe_status":      {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "MOE Status",
                              "enum": ["success", "partial", "fail", "no_assess"],
                              "guidance": "Measure-of-Effectiveness assessment per FM 3-60 para 2-78."},
        "pda_finding":     {"source": "analytical", "view": "published",
                              "required": False, "provenance_required": True,
                              "render_label": "PDA Finding",
                              "guidance": "Physical Damage Assessment — see FM 3-60 para 2-75."},
        "fda_finding":     {"source": "analytical", "view": "published",
                              "required": False, "provenance_required": True,
                              "render_label": "FDA Finding",
                              "guidance": "Functional Damage Assessment — see FM 3-60 para 2-76."},
        "mea_finding":     {"source": "analytical", "view": "published",
                              "required": False, "provenance_required": True,
                              "render_label": "MEA Finding",
                              "guidance": "Munitions Effectiveness Assessment — see FM 3-60 paras 2-80/2-81."},
        "reattack_recommended": {"source": "analytical", "view": "published",
                                   "required": False, "render_label": "Reattack?",
                                   "guidance": "True when commander should reengage; surfaces in parent CA's recommendations."},
        "bda_artifact_id": {"source": "upstream:BDA", "view": "workpaper",
                              "required": False, "render_label": "BDA Reference",
                              "depends_on": ["upstream:BDA"],
                              "guidance": "Per-target BDA artifact when one exists."},
    },
    "hard_rules": [
        "Never invent engagement IDs — kg_engagements only.",
        "Every analytical claim (moe_status, pda/fda/mea findings) cites the upstream BDA / sensor record.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Engagements in window: get_recent_intel(types=['engagement'])",
        "Per-target BDA artifacts: list_project_docs(filter={type:'BDA'})",
        "HPTL context (drives priority for the working group's filter): get_project_doc(tag=<latest HPTL>)",
        "Parent CA narrative when present: list_project_docs(filter={type:'CA'})",
    ],
    "post_emit_summary": "artifact_id, engagement count, MOE distribution, reattack count",
}
