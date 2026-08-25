"""DSM — Decision Support Matrix — ATP 5-0 / FM 6-0.

Tier 2 fused product. The tabular companion to the DST (Decision Support
Template) — DST is the graphical overlay plotting decision points on
terrain; DSM is the tabulated companion listing each decision point with
its trigger event, named area of interest, commander decision, supporting
cell, and branch/sequel routing. Per ATP 5-0, the DSM is the working
copy carried by the staff during execution.

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
    "name": "DSM",
    "output_format": "pptx",
    "shape": "row",
    "doctrine": {
        "citation": "ATP 5-0 (The Operations Process) Decision Support Matrix; FM 6-0 §10",
        "purpose": (
            "Tabulated companion to the DST. Lists each commander decision "
            "point with: the trigger event that drives the decision, the NAI/"
            "TAI providing the indicator, the commander's named decision, the "
            "responsible staff cell, and the branch / sequel that follows. "
            "Carried by the staff during execution as the working copy of "
            "the DST." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows = decision points in time-sequence order (T-72 → T+0 → T+6).",
    },
    "consumes_artifacts": ["Decision Support Template", "Event Template",
                            "Information Collection Matrix"],
    "row_source": "factor_list",  # DPs are an analyst-derived list, not KG-sourced
    "header_fields": {
        "area_of_operations": HEADER_AO,
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "dst_artifact_id":    {"source": "upstream:Decision Support Template",
                                 "view": "internal", "required": True,
                                 "depends_on": ["upstream:Decision Support Template"],
                                 "render_label": "DST Reference",
                                 "guidance": "Upstream DST — DSM rows ARE the decision points from this DST in the same priority/time order."},
        "event_template_artifact_id": {"source": "upstream:Event Template",
                                         "view": "internal", "required": False,
                                         "depends_on": ["upstream:Event Template"],
                                         "render_label": "Event Template Reference"},
        "icm_artifact_id":    {"source": "upstream:Information Collection Matrix",
                                 "view": "internal", "required": False,
                                 "depends_on": ["upstream:Information Collection Matrix"],
                                 "render_label": "ICM Reference"},
        "prepared_by":        HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "published_section_title": "Decision Support Matrix",
    "row_fields": {
        "decision_point_id":   {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "render_label": "DP ID",
                                  "guidance": "Cross-reference to the upstream DST's decision-point identifier."},
        "decision_point_name": {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "render_label": "Decision Point"},
        "trigger_event":       {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "render_label": "Trigger Event",
                                  "depends_on": ["upstream:Event Template"],
                                  "guidance": "The event on the battlefield that signals the commander to decide. Pull from the Event Template / NAI indicator set."},
        "named_area_of_interest": {"source": "analytical", "view": "published",
                                      "required": True, "provenance_required": True,
                                      "render_label": "NAI"},
        "commander_decision":  {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "render_label": "Commander's Decision",
                                  "guidance": "What the commander DOES when the trigger fires. Per the DST's decision-point doctrine."},
        "supporting_cell":     {"source": "analytical", "view": "published",
                                  "required": True,
                                  "render_label": "Supporting Cell",
                                  "guidance": "Which staff cell owns the decision (G-2 / G-3 / G-5 / fires / aviation / sustainment)."},
        "branch_or_sequel":    {"source": "analytical", "view": "published",
                                  "required": False,
                                  "render_label": "Branch / Sequel",
                                  "guidance": "Branch (alternative plan) or sequel (follow-on operation) triggered by this decision."},
    },
    "subtleties": [
        "DSM rows correspond 1:1 to DST decision points — re-derive when DST changes.",
        "Trigger events pull from the Event Template's NAI indicator set when one exists.",
        "Supporting cell drives execution-time routing: G-2 owns indicator confirmation; G-3 owns the decision; supporting staff cell owns the action.",
    ],
    "hard_rules": [
        "Never invent decision points — pull from the upstream DST verbatim.",
        "Every analytical claim has _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream DST: list_project_docs(filter={type:'Decision Support Template'})",
        "Upstream Event Template: list_project_docs(filter={type:'Event Template'})",
        "Upstream ICM (for collection indicators): list_project_docs(filter={type:'Information Collection Matrix'})",
        "Phased concept of operations (decision points key off phases): get_phases() — current phase + decisive point + phase objectives",
        "Operations overlay control measures (decision-asset deconfliction against NAIs/TAIs/EAs/OBJ/phase lines): get_spatial_overlay()",
    ],
    "post_emit_summary": "artifact_id, decision-point count, supporting-cell distribution",
}
