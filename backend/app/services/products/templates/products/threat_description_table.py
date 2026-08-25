"""Threat-Description-Table — per-unit row spreadsheet sibling of Threat
Overlay.

Per scratch/ibl/reports/EXCEL_DOCTRINAL_ALIGNMENT.md §3: ATP 2-01.3
para 4-6 describes Threat Overlay as a map slide plus a per-unit
description table. The map stays in PPTX (parent Threat Overlay); the
per-unit table is doctrinally sortable / filterable — spreadsheet
primitive. This product is the table half ONLY.
"""
from ..common import (
    ECHELON_ENUM,
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    POSTURE_ENUM,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "Threat-Description-Table",
    "output_format": "xlsx",
    "output_formats": ["xlsx"],
    "shape": "row",
    "doctrine": {
        "citation": "ATP 2-01.3 para 4-6 / Fig 4-2 (Threat Overlay)",
        "purpose": (
            "XLSX surface for the per-unit description table half of the "
            "Threat Overlay doctrinal pair. Spreadsheet-canonical per "
            "EXCEL_DOCTRINAL_ALIGNMENT.md §3 — analysts sort by echelon, "
            "filter by posture, filter by parent_unit during disposition "
            "review. Parent Threat Overlay carries the map graphic (PPTX)."
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows sortable; default order is echelon (largest first) then unit_id.",
    },
    "order_by": {"field": "echelon", "direction": "desc"},
    "row_source": "entities:units:hostile",
    "group_by": "echelon",
    "consumes_artifacts": ["Threat Overlay", "Threat Model", "DonovianDoctrine"],
    "published_section_title": "Threat Disposition",
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "as_of_dtg":          {"source": "session", "view": "header", "required": True,
                                 "render_label": "As-Of DTG",
                                 "guidance": "Cutoff DTG for the disposition snapshot."},
        "prepared_by":        HEADER_PREPARED_BY,
        "parent_threat_overlay_artifact_id": {"source": "upstream:Threat Overlay",
                                                "view": "internal", "required": False,
                                                "render_label": "Parent Threat Overlay",
                                                "depends_on": ["upstream:Threat Overlay"],
                                                "guidance": "Companion Threat Overlay graphic when present."},
        "classification":     HEADER_CLASSIFICATION,
    },
    "row_fields": {
        "unit_id":         {"source": "entity:id", "view": "published",
                              "required": True, "render_label": "Unit ID"},
        "unit_designation": {"source": "entity:unit_designation", "view": "published",
                               "required": True, "render_label": "Designation",
                               "guidance": "Per Change 2 of ATP 2-01.3 Table 4-1, the 'Identity' column."},
        "echelon":         {"source": "entity:echelon", "view": "published",
                              "required": True, "render_label": "Echelon",
                              "enum": ECHELON_ENUM},
        "parent_unit":     {"source": "entity:parent_unit", "view": "published",
                              "required": False, "render_label": "Parent"},
        "location_mgrs":   {"source": "entity:location_mgrs", "view": "published",
                              "required": True, "render_label": "Location"},
        "posture":         {"source": "entity:posture", "view": "published",
                              "required": False, "render_label": "Posture",
                              "enum": POSTURE_ENUM},
        "description":     {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Description",
                              "guidance": "Per Change 2 of ATP 2-01.3 Table 4-1, the 'Description' column (capability statement)."},
        "additional_information": {"source": "analytical", "view": "published",
                                     "required": False, "provenance_required": True,
                                     "render_label": "Additional Information",
                                     "guidance": "Per Change 2 of ATP 2-01.3 Table 4-1, the new '+Additional information' column (disposition narrative, recent activity)."},
        "last_observed_dtg": {"source": "entity:doi", "view": "published",
                                "required": False,
                                "render_label": "Last Observed",
                                "guidance": "DTG of the most recent sensor confirmation. MECHANICAL — pulled directly from the OOB unit's date-of-intel field (last_obs). Writer should NEVER author this; the runner short-circuits to the cougaar payload."},
        "strength_pct":    {"source": "entity:strength", "view": "published",
                              "required": False,
                              "render_label": "Strength %",
                              "guidance": "Current strength from OOB. MECHANICAL — pulled directly from the unit's strength field (e.g. 'full', '75%'). Writer should NEVER author this."},
    },
    "hard_rules": [
        "Never invent unit IDs — kg_units_active only.",
        "Never include DEFEATED / DESTROYED entities (per most recent BDA).",
        "Every analytical claim (strength, description, additional_information) cites the underlying sensor / SITREP source.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Order of Battle (now merges OPORD-derived threat-disposition + Road-to-War vectors with the fixture): get_oob('RED')",
        "Threat doctrine (anchors per-unit description / posture interpretation per OPFOR doctrinal pattern): get_project_doc(tag='DonovianDoctrine')",
        "Recent intel (ENSIT, SITREPs, sensor records): get_recent_intel(types=['OOB','TACTICAL','SIGINT','HUMINT'])",
        "Parent Threat Overlay when present: list_project_docs(filter={type:'Threat Overlay'})",
        "Threat Model (capability source for description column): list_project_docs(filter={type:'Threat Model'})",
        "Recent BDAs (DEFEATED exclusions): list_project_docs(filter={type:'BDA'})",
    ],
    "post_emit_summary": "artifact_id, unit row count, echelon distribution, posture distribution",
}
