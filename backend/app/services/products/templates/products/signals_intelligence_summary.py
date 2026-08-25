"""SIGSUM — SIGINT Summary — organizer-provided minimum standard.

Tier 1 SIGINT analytical product. Periodic windowed rollup of SIGINT
activity in the deep area, organized by warfighting function. Mirrors
INTSUM cadence on the SIGINT side. The 24-hour version is a doctrinal
division-level briefing artifact.

Doctrinal anchor: ATP 2-22.6 SIGINT TTPs (off-disk on unclassified
systems); the on-disk authority is the IDX 26 organizer template at
scratch/docs/ibl/event_docs/Example of SIGSUM and KLIEGLIGHT.docx
(treated as the minimum standard per the integration plan). FM 2-0 §1-86
lists SIGINT periodic reports as a product category.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO, HEADER_CLASSIFICATION, HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "SIGSUM",
    "output_format": "docx",
    "shape": "paragraph",
    "title_field": "sigsum_number",
    # 24h periodic rollup per organizer template. Mirrors INTSUM cadence
    # on the SIGINT side; forward / division cycle = 24h, corps may run
    # 12h. Default to the division standard the organizer template models.
    "cadence_hours": 24,
    "doctrine": {
        "citation": "Organizer minimum standard (IDX 26 example doc) — ATP 2-22.6 off-disk; FM 2-0 §1-86",
        "purpose": (
            "Periodic SIGINT activity rollup organized by warfighting function. "
            "Aggregates accumulated TACELINTs / KLIEGLIGHTs / raw SIGINT collects "
            "across the reporting window into the SIGINT cell's vouched "
            "summary — what was emitting, what shifted, what is expected next. "
            "Feeds INTSUM, IRE, GRINTSUM, Threat Capability Statement, and "
            "Threat Model." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Fixed five-section order: Executive Summary → Maneuver/C2 → "
            "Fires/Artillery → Air Defense Artillery (ADA) → Analytical Outlook."
        ),
    },
    "consumes_artifacts": [ "KLIEGLIGHT"],
    "header_fields": {
        "sigsum_number":     {"source": "computed", "view": "header", "required": True,
                                "default": "SIGSUM-{period_start_dtg}-{period_end_dtg}",
                                "render_label": "SIGSUM Number"},
        "period_start_dtg":  {"source": "computed", "view": "header", "required": True,
                                "render_label": "Period Start"},
        "period_end_dtg":    {"source": "computed", "view": "header", "required": True,
                                "render_label": "Period End"},
        "area_of_operations": HEADER_AO,
        "prepared_by":       HEADER_PREPARED_BY,
        "classification":    HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "paragraph_1_executive_summary",
         "view": "published", "shape": "string",
         "render_label": "1. Executive Summary",
         "required": True, "provenance_required": True,
         # Doctrinal rollup: the executive summary synthesizes what sections
         # 2-4 found. depends_on makes the DAG run p1 AFTER p2/p3/p4 so the
         # writer reads their narratives + the underlying KLIEGLIGHT
         # dependency, not a blank deps payload.
         "depends_on": [
             "paragraph_2_maneuver_and_command_and_control",
             "paragraph_3_fires_and_artillery",
             "paragraph_4_air_defense_artillery",
             "upstream:KLIEGLIGHT",
         ],
         "guidance": (
            "Two-to-four sentence rollup of overall SIGINT activity this "
            "period. Synthesize from the dep payload, which carries the "
            "completed Sections 2 (Maneuver & C2), 3 (Fires/Artillery), and "
            "4 (Air Defense) PLUS the underlying KLIEGLIGHT artifact pool "
            "(count = N items). Name which warfighting function dominated, "
            "what shifted vs the prior cycle, what this implies about "
            "threat operational tempo. Cite the most significant KLIEGLIGHT "
            "artifact_ids in _provenance."
         )},
        {"name": "paragraph_2_maneuver_and_command_and_control",
         "view": "published", "shape": "string",
         "render_label": "2. Maneuver & C2",
         "required": True, "provenance_required": True,
         "guidance": (
            "Maneuver and C2 SIGINT — push-to-talk activity, encrypted UHF "
            "data bursts, line-of-bearing concentrations indicating C2 nodes. "
            "Cite each cited emitter / unit by SIGINT ID (TACELINT cross-ref)."
         )},
        {"name": "paragraph_3_fires_and_artillery",
         "view": "published", "shape": "string",
         "render_label": "3. Fires / Artillery",
         "required": True, "provenance_required": True,
         "guidance": (
            "Fires / artillery SIGINT — target-acquisition radar activations, "
            "counter-battery emissions, artillery-net coordination. Cite each "
            "TACELINT artifact_id that contributed."
         )},
        {"name": "paragraph_4_air_defense_artillery",
         "view": "published", "shape": "string",
         "render_label": "4. Air Defense Artillery",
         "required": True, "provenance_required": True,
         "guidance": (
            "ADA SIGINT — early-warning radar emissions (Spoon Rest, Big Bird, "
            "etc.), engagement radar activations (Snow Drift, Grill Pan, …), "
            "MANPADS chatter. Movement of ADA-radar emissions along MSRs "
            "indicates re-positioning. Cite TACELINT references."
         )},
        {"name": "paragraph_5_analytical_outlook",
         "view": "published", "shape": "string",
         "render_label": "5. Analytical Outlook (Next 24 Hours)",
         "required": True, "provenance_required": True,
         # The outlook is forward-looking but informed by what sections 2-4
         # observed this cycle. Same depends_on chain as the exec summary so
         # the writer can extrapolate from the trend.
         "depends_on": [
             "paragraph_2_maneuver_and_command_and_control",
             "paragraph_3_fires_and_artillery",
             "paragraph_4_air_defense_artillery",
             "upstream:KLIEGLIGHT",
         ],
         "guidance": (
            "Forward-looking assessment — expected SIGINT signatures over "
            "the next reporting window, collection-priority shifts, and "
            "gaps to be filled. Extrapolate from the activity sections 2-4 "
            "described (carried in the dep payload) + the underlying "
            "KLIEGLIGHT pool. Tie to threat COA per latest Threat COA Statement / Threat "
            "Model."
         )}],
    "subtleties": [
        "SIGSUM mirrors INTSUM cadence on the SIGINT side; the all-source INTSUM should consume the SIGSUM as its SIGINT input rather than re-deriving from raw TACELINTs.",
        "Five-section structure is fixed per organizer template — do not invent a sixth section.",
        "Each section's prose should name the warfighting function's specific systems by SIGINT signature (Tombstone, Snow Drift, Spoon Rest, etc.) not generic 'radar emissions'."],
    "hard_rules": [
        "Never invent emitter signatures — pull from cougaar SIGINT records or upstream TACELINTs.",
        "Section ordering is fixed.",
        "Every analytical claim has _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Raw SIGINT collects in window: get_recent_intel(types=['SIGINT','ELINT','COMINT'], window_hours=<cadence>)",
        "Emitter inventory: get_oob",
        "Accumulated TACELINTs in window: list_project_docs(filter={type:})",
        "Accumulated KLIEGLIGHTs in window: list_project_docs(filter={type:'KLIEGLIGHT'})"],
    "post_emit_summary": "artifact_id, dominant warfighting functions, count of cited TACELINTs",
}
