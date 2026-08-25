"""KLIEGLIGHT — Tactical SIGINT Data Report — FM 2-0 §1-86 line 1585.

Tier 1 SIGINT single-INT product. Time-perishable structured message
pushing technical SIGINT data (frequency, location, equipment type) to
all consumers in the corps / division SIGINT distribution. SIGINT analog
to the OSINT tipper — fires on detection, not on cycle.

Doctrinal anchor: FM 2-0 §1-86 lists KLIEGLIGHT in the SIGINT product
set. Full format spec lives in ATP 2-22.6 (off-disk on unclassified);
the on-disk authority is the IDX 26 organizer template at
scratch/docs/ibl/event_docs/Example of SIGSUM and KLIEGLIGHT.docx.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_CLASSIFICATION, HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "KLIEGLIGHT",
    "output_format": "docx",
    "shape": "paragraph",
    "title_field": "kliegl_number",
    # Time-perishable / event-driven — no periodic cadence. Each
    # KLIEGLIGHT fires on a single emitter detection.
    "doctrine": {
        "citation": "FM 2-0 §1-86; organizer minimum standard (IDX 26 example doc); ATP 2-22.6 off-disk",
        "purpose": (
            "Time-sensitive structured push of technical SIGINT data on a "
            "newly detected threat emitter — frequency, geolocation, equipment "
            "type, line-of-bearing — so downstream consumers (fires, aviation, "
            "EOB) can act inside the emitter's window. SIGINT analog to the "
            "OSINT tipper. Feeds SITREP (time-sensitive) and INTSUM "
            "(windowed rollup)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Six fixed sections: Emitter/Target Identification → Time of "
            "Intercept → Frequency & Parameters → Geolocation (MGRS) → "
            "Analytical Comments → Action Taken. Plus message-header chrome "
            "(FROM / TO / DTG / SUBJECT)."
         ),
    },
    "consumes_artifacts": [],  # Tier 1 — fires from raw SIGINT, no upstream artifact
    "header_fields": {
        "kliegl_number": {"source": "computed", "view": "header", "required": True,
                            "default": "KL-{from_unit}-{message_dtg}",
                            "render_label": "KLIEGLIGHT Number"},
        # Originating SIGINT cell + distribution are scenario-fixed for IDX 26:
        # XX Corps' SIGINT analysis cell (TCAE = Technical Control & Analysis
        # Element per FM 2-22.6 ch. 5) sends KLIEGLIGHTs to its subordinate
        # divisions. Holding these as `session` defaults (vs. `analytical`)
        # keeps the writer from pattern-matching its training corpus and
        # emitting the literal guidance example ("TCAE 1ST ARMORED DIV") as
        # data — which was happening on autofire-generated KLIEGLIGHTs.
        "from_unit":     {"source": "session", "view": "header", "required": True,
                            "render_label": "FROM",
                            "default": "XX CORPS TCAE",
                            "guidance": (
                                "Originating SIGINT cell. For IDX 26 the "
                                "default is XX CORPS TCAE (V Corps' Technical "
                                "Control & Analysis Element); override only "
                                "if a different cell originated the report."
                            )},
        "to_distribution": {"source": "session", "view": "header", "required": True,
                              "render_label": "TO",
                              "default": "ALL XX CORPS / DIVISION SIGINT CONSUMERS",
                              "guidance": (
                                "Distribution list. For IDX 26 the default is "
                                "ALL XX CORPS / DIVISION SIGINT CONSUMERS; "
                                "override only for a named single-recipient "
                                "tip."
                              )},
        "message_dtg":   {"source": "computed", "view": "header", "required": True,
                            "render_label": "DTG"},
        "subject":       {"source": "session", "view": "header", "required": True,
                            "default": "KLIEGLIGHT / TACTICAL REPORT",
                            "render_label": "SUBJECT"},
        "prepared_by":   HEADER_PREPARED_BY,
        "classification": HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "paragraph_1_emitter_target_identification",
         "view": "published", "shape": "string",
         "render_label": "1. Emitter / Target Identification",
         "required": True, "provenance_required": True,
         "guidance": (
            "Emitter call sign + parent threat system (e.g. 'SNOWDRIFT Target "
            "Acquisition Radar / Donovian SA-11 (BUK) System'). Pull from the "
            "SIGINT entity record verbatim."
         )},
        {"name": "paragraph_2_time_of_intercept",
         "view": "published", "shape": "string",
         "render_label": "2. Time of Intercept (TOI)",
         "required": True, "provenance_required": True,
         "guidance": (
            "DTG range of intercept window (e.g. '190905ZMAY26 to 190912ZMAY26'). "
            "Read from the SIGINT observation timestamps."
         )},
        {"name": "paragraph_3_frequency_and_parameters",
         "view": "published", "shape": "dict",
         "render_label": "3. Frequency & Parameters",
         "required": True, "provenance_required": True,
         "guidance": (
            "Signal parameter block — frequency, pulse repetition frequency, "
            "pulse duration, modulation. Each value verbatim from the SIGINT "
            "intercept record."
         ),
         "subfields": ["frequency", "pulse_repetition_frequency",
                        "pulse_duration", "modulation"]},
        {"name": "paragraph_4_geolocation_mgrs",
         "view": "published", "shape": "dict",
         "render_label": "4. Geolocation (MGRS)",
         "required": True, "provenance_required": True,
         "guidance": (
            "Geolocation block — MGRS coordinate with elliptical error in "
            "meters, plus two lines of bearing from named sensor positions."
         ),
         "subfields": ["mgrs", "elliptical_error_meters",
                        "line_of_bearing_1", "line_of_bearing_2"]},
        {"name": "paragraph_5_analytical_comments",
         "view": "published", "shape": "string",
         "render_label": "5. Analytical Comments",
         "required": True, "provenance_required": True,
         "guidance": (
            "Analyst's assessment — signal-parameter match confidence, parent "
            "system inference, operational implication. Typically 'parameters "
            "are a 95% match for the X radar which acts as primary engagement "
            "radar for the Y system' followed by tactical implication."
         )},
        {"name": "paragraph_6_action_taken",
         "view": "published", "shape": "string",
         "render_label": "6. Action Taken",
         "required": True, "provenance_required": True,
         "guidance": (
            "Concrete actions the SIGINT cell took on this detection — "
            "coordinates passed to fires (AFATDS), EOB updates, aviation "
            "rerouting recommendations. NOT speculation — only what the cell "
            "actually did."
         )},
    ],
    "subtleties": [
        "Time-perishable — KLIEGLIGHT fires on detection, not on a reporting cycle. No cadence_hours.",
        "FROM/TO/DTG/SUBJECT are message-header chrome, not analytical content.",
        "Lines of bearing are from NAMED sensor positions ('Sensor Alpha', 'Sensor Bravo') — pull verbatim from the SIGINT intercept record.",
        "Action Taken section is factual — what the SIGINT cell did, not what they recommend.",
    ],
    "hard_rules": [
        "Never invent signal parameters — pull verbatim from the SIGINT intercept record.",
        "Never invent MGRS — pull from the cougaar geolocation record.",
        "Every analytical claim has _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Time-perishable SIGINT collect: get_recent_intel(types=['SIGINT','ELINT'], window_hours=1)",
        "Emitter signature lookup: get_oob",
    ],
    "post_emit_summary": "artifact_id, emitter identification, geolocation MGRS, action taken",
}
