"""CCA-Matrix — ASCOPE × PMESII-PT spreadsheet sibling of CCA.

Per scratch/ibl/reports/EXCEL_DOCTRINAL_ALIGNMENT.md §3 (canonical hybrid):
the 48-cell ASCOPE × PMESII-PT grid is a spreadsheet primitive; the
parent CCA's narrative_assessment + protected-targets list stay in DOCX.
This product is the matrix half ONLY — analysts generate both the
parent CCA (full hybrid) and CCA-Matrix (XLSX) independently and
neither propagates edits to the other.

Schema reuses the same matrix_spec axes as the parent CCA so a regenerate
on either side produces the same 8 PMESII-PT × 6 ASCOPE grid; only the
output format differs.
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
    "name": "CCA-Matrix",
    "output_format": "xlsx",
    "output_formats": ["xlsx"],
    # No legacy_formats — CCA-Matrix is XLSX-only by design. The parent
    # CCA carries the DOCX rendition for analysts who want the hybrid.
    "shape": "matrix",
    "doctrine": {
        "citation": "ATP 2-01.3 §4-96 ASCOPE × PMESII-PT",
        "purpose": (
            "XLSX surface for the 48-cell ASCOPE × PMESII-PT civil-considerations "
            "matrix. Spreadsheet-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §3 — "
            "analysts sort, filter, and edit cell-by-cell during civic-baseline "
            "evolution; narrative synthesis lives in the parent CCA artifact."
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Matrix axes fixed: rows = PMESII-PT (8); cols = ASCOPE (6).",
    },
    "consumes_artifacts": ["CCA", "MCOO", "HUMINTSUM", "OSIR"],
    "matrix_spec": {
        "field": "ascope_pmesii_pt_matrix",
        "row_axis": ["political", "military", "economic", "social",
                      "information", "infrastructure",
                      "physical_environment", "time"],
        "col_axis": ["areas", "structures", "capabilities",
                      "organizations", "people", "events"],
        "row_label": "PMESII-PT Lens",
        "col_label": "ASCOPE Characteristic",
    },
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "area_of_interest":   {"source": "session", "view": "header",
                                "required": True,
                                "render_label": "Area of Interest",
                                "default": "{area_of_operations}"},
        "prepared_by":        HEADER_PREPARED_BY,
        "parent_cca_artifact_id": {"source": "upstream:CCA", "view": "internal",
                                     "required": False,
                                     "render_label": "Parent CCA",
                                     "depends_on": ["upstream:CCA"],
                                     "guidance": "Companion CCA artifact_id when both exist; not required."},
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "ascope_pmesii_pt_matrix",
         "view": "published",
         "shape": "grid_table",
         "render_label": "ASCOPE × PMESII-PT Matrix",
         "required": True,
         "engine_join": "ascope_pmesii",
         "guidance": (
             "ENGINE-CONSTRUCTED (2026-07-27 ruling) — no writer involvement. "
             "Each of the 48 cells is the mechanical tag join: entities whose "
             "ascope tags carry the COLUMN category, joined through clause_about "
             "to clauses whose pmesii tags carry the ROW facet. Cell display = "
             "entity names; per-cell _provenance = the entity's mark plus its "
             "supporting clauses' marks. Empty intersections stay honestly "
             "empty; all 8 rows x 6 columns always render. Tags are stamped at "
             "ingestion (assert_section clause pmesii / entity ascope) and "
             "corrected through the repair surface — a wrong cell is a wrong "
             "TAG, never a writer-prompt problem."
         ),
         "depends_on": [
             "matrix:ascope_pmesii",
         ]},
    ],
    "hard_rules": [
        "Matrix axes are fixed: 8 PMESII-PT rows × 6 ASCOPE cols, no row/col added or removed.",
        "Every populated cell cites its retrieval-set marks in _provenance.",
        "Never invent entity identifiers — reference entities by name exactly as the retrieval set carries them.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Civil baseline: get_civil()",
        "Per ASCOPE category: get_civil(layer='areas'), get_civil(layer='structures'), etc.",
        "Civic SITREPs (rollups): list_project_docs(filter={type:'HUMINTSUM'}) + list_project_docs(filter={type:'OSIR'})",
        "MCOO for urban infrastructure overlap: get_project_doc(tag=<latest MCOO>)",
        "OPORD §5 (CMO annex when present): get_project_doc(tag='OPORD')",
        "Parent CCA artifact (when present): list_project_docs(filter={type:'CCA'}) — share narrative anchor",
    ],
    "post_emit_summary": "artifact_id, filled cell count out of 48, top 3 row/col intersections by entry count",
}
