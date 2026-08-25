"""HUMINTSUM — HUMINT Summary — HAC periodic rollup.

Tier 1 HUMINT analytical product. Periodic windowed rollup of HUMINT
activity in the AO produced by the HUMINT Analysis Cell (HAC). Mirrors
SIGSUM / OSIR on the HUMINT side. Aggregates atomic HUMINT IIRs across
the reporting window into the cell's vouched summary — what sources
reported, what changed, what is expected next.

DOCTRINAL FORMAT CAVEAT: The named format spec lives in ATP 2-22.31
(classified SECRET//NOFORN — see HUMINT IIR schema docstring for the
unclassified-availability situation) and NATO AIntP-05 (STANAG 2578,
HUMINT TTPs). On-disk unclassified anchor is ATP 2-33.4 §4 lines
1787-1790 which confirms the HAC "disseminates this newly produced
intelligence in a summary that contains the determination... The
summary of HUMINT reporting is disseminated to the commander and shared
with all other intelligence elements within the division." The
production exists; the named format is off-disk on unclassified.

Authored from FM 2-0 §1-73 (HUMINT product set) + ATP 2-33.4 §4 + the
parallel structure of SIGSUM (organizer template) and OSIR (ATP 2-22.9).
Format fidelity will improve only if AIntP-05 or an unclassified release
of ATP 2-22.31 surfaces.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO, HEADER_CLASSIFICATION, HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "HUMINTSUM",
    "output_format": "docx",
    "shape": "paragraph",
    "title_field": "humintsum_number",
    # 24h periodic rollup mirroring SIGSUM cadence on the SIGINT side and
    # the broader INTSUM cycle. HAC publishes once per reporting cycle.
    "cadence_hours": 24,
    "doctrine": {
        "citation": "ATP 2-33.4 §4 (HAC summary production); FM 2-0 §1-73; ATP 2-22.31 SECRET//NOFORN; NATO AIntP-05 (STANAG 2578) — format APPROXIMATE",
        "purpose": (
            "Periodic HUMINT activity rollup produced by the HUMINT Analysis "
            "Cell (HAC). Aggregates accumulated HUMINT IIRs / BIIRs across "
            "the reporting window into the cell's vouched summary — what "
            "sources reported on threat plans / intentions / capabilities / "
            "disposition / sociocultural context, what shifted, what is "
            "expected next. Feeds INTSUM, IRE, Threat Model (preferred "
            "tactics, key personalities), Threat Capability Statement, "
            "Threat COA Statement, OED, CCA (human-source civil context), SITEMP, and the "
            "Information Collection Matrix." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Fixed-section structure: Executive Summary → Threat Disposition "
            "(source-reported) → Threat Plans & Intentions → Threat "
            "Capabilities → Sociocultural / Civil Context → Source "
            "Reliability Rollup → Analytical Outlook."
        ),
    },
    "consumes_artifacts": [],  # Atomic HUMINT inputs the HAC summarizes
    "header_fields": {
        "humintsum_number":  {"source": "computed", "view": "header", "required": True,
                                "default": "HUMINTSUM-{period_start_dtg}-{period_end_dtg}",
                                "render_label": "HUMINTSUM Number"},
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
         "guidance": (
            "Two-to-four sentence rollup of HUMINT activity this period. "
            "Headline themes from source reporting, what shifted vs the "
            "prior cycle, what this implies about threat intent. Cite the "
            "most significant contributing HUMINT IIRs in _provenance — "
            "downstream consumers (INTSUM / Threat Model / Threat COA Statement) read this "
            "provenance to transitively cite the atomic IIRs."
         )},
        {"name": "paragraph_2_threat_disposition",
         "view": "published", "shape": "string",
         "render_label": "2. Threat Disposition",
         "required": True, "provenance_required": True,
         "guidance": (
            "Source-reported threat unit positions, movements, and "
            "compositions. One paragraph. Cite each contributing HUMINT IIR "
            "by artifact_id in _provenance."
         )},
        {"name": "paragraph_3_threat_plans_and_intentions",
         "view": "published", "shape": "string",
         "render_label": "3. Threat Plans & Intentions",
         "required": True, "provenance_required": True,
         "guidance": (
            "Source-reported threat plans, decisions, and intent. Distinct "
            "from disposition (where they are) — this is what they're "
            "planning. Cite contributing HUMINT IIRs."
         )},
        {"name": "paragraph_4_threat_capabilities",
         "view": "published", "shape": "string",
         "required": True, "provenance_required": True,
         "render_label": "4. Threat Capabilities",
         "guidance": (
            "Source-reported threat capabilities — weapons systems observed, "
            "training levels, logistics readiness, technical access. Feeds "
            "Threat Capability Statement."
         )},
        {"name": "paragraph_5_sociocultural_and_civil_context",
         "view": "published", "shape": "string",
         "render_label": "5. Sociocultural & Civil Context",
         "required": False, "provenance_required": True,
         "guidance": (
            "Source-reported civil / cultural / population context — "
            "displaced-persons indicators, host-nation security shifts, "
            "civic sentiment. Feeds CCA, OED."
         )},
        {"name": "paragraph_6_source_reliability_rollup",
         "view": "published", "shape": "string",
         "render_label": "6. Source Reliability Rollup",
         "required": True, "provenance_required": True,
         "guidance": (
            "Aggregate source-reliability and information-credibility "
            "ratings for the reporting period. Per the doctrinal source / "
            "information evaluation matrix (A-F / 1-6). Flag any sources "
            "newly assessed as unreliable or compromised."
         )},
        {"name": "paragraph_7_analytical_outlook",
         "view": "published", "shape": "string",
         "render_label": "7. Analytical Outlook (Next 24 Hours)",
         "required": True, "provenance_required": True,
         "guidance": (
            "Forward-looking — expected HUMINT signatures over the next "
            "reporting window, collection-priority shifts (input to ICM), "
            "and gaps to be filled. Tie to threat COA per latest Threat COA Statement / "
            "Threat Model."
         )}],
    "subtleties": [
        "HUMINTSUM mirrors INTSUM cadence on the HUMINT side; the all-source INTSUM should consume the HUMINTSUM as its HUMINT input rather than re-deriving from raw HUMINT IIRs.",
        "Source identifiers in this published summary remain anonymized — per HUMINT IIR doctrine, names / biometrics / source location stay in the protected biographic file.",
        "Each section's _provenance carries the contributing HUMINT IIR / BIIR artifact_ids — downstream consumers (INTSUM, Threat Model, Threat COA Statement) transitively cite atomics through this provenance chain.",
        "Format is APPROXIMATE per FM 2-0 + ATP 2-33.4 — see schema docstring for the ATP 2-22.31 / AIntP-05 caveat."],
    "hard_rules": [
        "Section ordering is fixed.",
        "Source identifiers stay anonymized (no name / biometric / precise location in published fields).",
        "Source reliability + information credibility ratings use the doctrinal A-F / 1-6 matrix.",
        "Every analytical claim has _provenance citing contributing HUMINT IIR / BIIR artifact_ids.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Raw HUMINT collects in window: get_recent_intel(types=['HUMINT'], window_hours=<cadence>)",
        "Accumulated HUMINT IIRs in window: list_project_docs(filter={type:})",
        "Accumulated BIIRs (per-person dossiers): list_project_docs(filter={type:})",
        "Source country / threat parent-unit context (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()"],
    "post_emit_summary": "artifact_id, dominant threat themes, count of cited HUMINT IIRs",
}
