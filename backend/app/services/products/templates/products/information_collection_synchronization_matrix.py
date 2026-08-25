"""ICSM — Information Collection Synchronization Matrix — ATP 2-01 / FM 3-55.

Tier 2 fused product. Sibling to ICM (Information Collection Matrix):
ICM declares WHAT collection is tasked per PIR; ICSM synchronizes WHEN
each collection task fires across the operational timeline so that
collection feeds intersect decision points before the commander needs
to decide. Per ATP 2-01.3 the ICSM is named alongside the Event
Template and DST as the time-synchronization companion to the ICM.

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

# Time-phase column axis. Doctrinally the ICSM columns are decision
# points pulled from the DST; in the absence of an upstream DST the
# matrix falls back to operational-tempo phases.
ICSM_DEFAULT_TIME_PHASES = [
    "T-72",  # 72 hours before decision
    "T-48",
    "T-24",
    "T-12",
    "T-06",
    "T-00",  # Decision point itself
    "T+06",  # Post-decision assessment
]

SPEC = {
    "name": "ICSM",
    # Matrix products render as xlsx — pptx was the legacy default for
    # every schema before the matrix grid-renderer landed. Sibling
    # matrix products (TSM / AGM / CARVER / CCA Matrix) all moved to
    # xlsx output. The output_format singular is kept for any legacy
    # consumer that still reads it; output_formats list is the new
    # canonical key the exporter dispatches on.
    "output_format": "xlsx",
    "output_formats": ["xlsx"],
    "shape": "matrix",
    "doctrine": {
        "citation": "ATP 2-01 / FM 3-55 (Information Collection); ATP 2-01.3 (sibling product to ICM + DST + Event Template)",
        "purpose": (
            "Synchronizes WHEN each information-collection task fires across "
            "the operational timeline so collection results land BEFORE the "
            "named decision points they support. ICM names the collection "
            "(asset → NAI → PIR); ICSM names the firing time (collection "
            "task → time-phase / decision-point trigger)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Rows = collection tasks from the upstream ICM (cross-referenced "
            "by collection_task_id). Columns = decision points from the "
            "upstream DST (when present) or doctrinal time-phase axis "
            "(T-72 through T+06)."
        ),
    },
    "consumes_artifacts": ["Information Collection Matrix",
                            "Decision Support Template",
                            "Event Template"],
    "header_fields": {
        "area_of_operations": HEADER_AO,
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "icm_artifact_id":    {"source": "upstream:Information Collection Matrix",
                                 "view": "internal", "required": True,
                                 "depends_on": ["upstream:Information Collection Matrix"],
                                 "render_label": "ICM Reference",
                                 "guidance": "Upstream ICM — ICSM rows ARE the collection tasks from this ICM, in the same order."},
        "dst_artifact_id":    {"source": "upstream:Decision Support Template",
                                 "view": "internal", "required": False,
                                 "depends_on": ["upstream:Decision Support Template"],
                                 "render_label": "DST Reference",
                                 "guidance": "Upstream DST — when present, ICSM columns ARE the DST's named decision points. Without a DST, columns fall back to the doctrinal time-phase axis."},
        "event_template_artifact_id": {"source": "upstream:Event Template",
                                         "view": "internal", "required": False,
                                         "render_label": "Event Template Reference",
                                         "depends_on": ["upstream:Event Template"],
                                         "guidance": "Upstream Event Template — provides the NAI/TAI list each ICM row collects against."},
        "prepared_by":        HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "matrix_spec": {
        "field": "icsm_matrix",
        "row_axis": None,  # Dynamic — derived from upstream ICM's collection tasks
        "col_axis": ICSM_DEFAULT_TIME_PHASES,
        "row_label": "Collection Task",
        "col_label": "Time / Decision Point",
    },
    "paragraph_fields": [
        {"name": "icsm_matrix",
         "view": "published", "shape": "grid_table",
         "render_label": "Information Collection Synchronization Matrix",
         "required": True, "provenance_required": True,
         "guidance": (
            "═════════════════════════════════════════════════════════\n"
            "OUTPUT: JSON OBJECT — NOT MARKDOWN, NOT A STRING.\n"
            "═════════════════════════════════════════════════════════\n"
            "Emit a JSON OBJECT mapping row_id → {col_id: cell_text}. "
            "DO NOT emit a markdown table string. DO NOT pipe-delimit "
            "rows. The renderer parses your JSON directly into the xlsx "
            "grid; markdown output renders as a single garbled cell.\n\n"
            "REQUIRED SHAPE (one of these — pick whichever fits):\n"
            "  a) {\"<task_id>\": {\"<col>\": \"<cell text>\", ...}, ...}\n"
            "  b) {\"cells\": [{\"row\": \"<task_id>\", \"col\": \"<col>\", "
            "\"value\": \"<text>\"}, ...]}\n"
            "  c) {\"rows\": [{\"row_id\": \"<task_id>\", \"cols\": [\"v0\", "
            "\"v1\", ...]}, ...]}\n\n"
            "ROWS: Collection tasks from the upstream ICM, cross-"
            "referenced by collection_task_id. Use the ICM's task IDs "
            "verbatim (e.g. 'COL-VALGA-OBS', 'COL-KOPU-RES').\n\n"
            "COLUMNS: PICK ONE COLUMN CONVENTION FOR THE ENTIRE MATRIX "
            "— NEVER MIX. Either:\n"
            "  (a) DST is bound (dst_artifact_id is populated):\n"
            "      use the DST's decision points verbatim as columns. "
            "      Examples: 'DP-1 (Commit 1st ID)', "
            "      'DP-2 (Commit 1st AD Supporting Attack)', etc. \n"
            "      DO NOT include ANY time-phase column "
            "      (T-72 / T-48 / T-24 / T-00 / T+06) in this case. \n"
            "      DO NOT duplicate the same collector+activity value "
            "      under both a DP column AND a T-phase column for the "
            "      same row — that's the writer drift that produced the "
            "      spurious 'T-24' column in ICSM_20260611T104606_693Z. \n"
            "  (b) DST is NOT bound:\n"
            "      use the doctrinal time-phase axis "
            "      (T-72 / T-48 / T-24 / T-12 / T-06 / T-00 / T+06). \n"
            "      DO NOT invent decision-point labels in this case.\n"
            "Determine which case applies by checking the header's "
            "dst_artifact_id — present → (a), absent → (b). The two "
            "column conventions are mutually exclusive in a single "
            "ICSM artifact.\n\n"
            "CELLS: 'COLLECTOR / ACTIVITY' short form. Examples:\n"
            "  'UAS / NAI-VALGA observation'\n"
            "  'JSTARS / convoy movement'\n"
            "  'HUMINT / civil-leader engagement'\n"
            "  'SIGINT / EW signature watch'\n"
            "  empty string '' when a task is NOT scheduled against "
            "that DP / time-phase — sparse matrix is doctrinally "
            "correct (each collection task informs only the subset of "
            "DPs it actually answers; do NOT pad empty cells with "
            "duplicated content from adjacent cells).\n\n"
            "PROVENANCE: cite ICM.<artifact_id> + DST.<artifact_id> "
            "(when present) per cell in _provenance. NEVER fabricate "
            "collection tasks or decision points — pull verbatim from "
            "the upstream artifacts."
         )},
    ],
    "subtleties": [
        "ICSM is synchronized to the DST's decision-point timeline when one exists — otherwise it falls back to a generic T-phase axis.",
        "Each row in ICSM corresponds 1:1 to a collection task in the upstream ICM.",
        "ICSM updates after every FRAGO when collection priorities shift; re-derive when ICM or DST changes.",
    ],
    "hard_rules": [
        "Never invent collection tasks — pull from the upstream ICM verbatim.",
        "Never invent decision points — pull from the upstream DST when present.",
        "Every cell has _provenance back to the ICM row (collection_task_id).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream ICM: list_project_docs(filter={type:'Information Collection Matrix'})",
        "Upstream DST: list_project_docs(filter={type:'Decision Support Template'})",
        "Upstream Event Template: list_project_docs(filter={type:'Event Template'})",
        "Phased concept of operations (PRIMARY — synchronization of collection across phases): get_phases() — current phase + decisive point + phase objectives",
        "Operations overlay control measures (NAIs / phase lines bound the synchronization geometry): get_spatial_overlay()",
    ],
    "post_emit_summary": "artifact_id, collection-task count, decision-point coverage",
}
