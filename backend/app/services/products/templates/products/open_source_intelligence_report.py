"""OSIR — Open-Source Intelligence Report — FM 2-0 §1-82.

Tier 1 OSINT single-INT product. Per FM 2-0 §1-82 the OSINT cell's
stand-alone products are exactly two: OSIR (open-source report) and the
Tactical OSINT Tipper (OSINT-discipline analog of the SIGINT KLIEGLIGHT).

OSIR shape: ONE published OSIR per discrete open-source event. A single
Telegram post, a single news article, a single broadcast intercept, a
single commercial-imagery pass — each emits one OSIR with the source
description, source reliability per ICD 203, the verbatim post or article
content, the geospatial / technical metadata, and the collector's
analytical comments. The all-source analyst then folds individual OSIRs
into the INTSUM / IRE / OED downstream (per FM 2-0: "OSIR reports … which
may be incorporated into intelligence estimates, intelligence summaries").

NOT a periodic rollup. There is no doctrinal "OSINT summary" product —
the rollup happens in the multi-INT INTSUM. Prior periodic-rollup
implementation of this schema (period_start / period_end / list of
findings) was deleted 2026-05-28 after customer feedback identified the
shape mismatch against the FM 2-0 example.

Format spec: customer-provided OSIR example
(scratch/docs/ibl/event_samples/🌐 Open Source Intelligence Report_Example
for Pytho.docx) defines the field order. ATP 2-22.9 (OSINT) is off-disk
on unclassified — the active August 2019 edition was marked INACTIVE on
armypubs without a public replacement.

Producer: handlers/osir_autofire.py fires one OSIR per IDXOpenSourceReport
vertex (live cougaar or scenario.KG['report'] type='OSINT' fallback via
utils.event_data_fixtures._parse_osint). Mirrors KLIEGLIGHT autofire.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_CLASSIFICATION, HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "OSIR",
    "output_format": "docx",
    "shape": "paragraph",
    "title_field": "report_number",
    # Event-driven — fires on each new OSINT row, NOT on a periodic cadence.
    # No cadence_hours field. The producer (osir_autofire.on_poll_callback)
    # fires one OSIR per new IDXOpenSourceReport kbID arriving in the
    # cougaar recent-intel poll, mirroring KLIEGLIGHT's per-emitter fire.
    "doctrine": {
        "citation": (
            "FM 2-0 §1-82; ATP 2-22.9 (off-disk on unclassified); customer "
            "example shape (IDX 26 organizer-provided OSIR sample, 2026-05-28)"
        ),
        "purpose": (
            "Single-event open-source intelligence report. ONE OSIR per "
            "discrete open-source observation (social media post, news "
            "article, broadcast intercept, academic publication, commercial "
            "imagery, web post). The OSINT cell publishes the OSIR; the "
            "all-source analyst folds individual OSIRs into INTSUM / IRE / "
            "OED / CCA downstream. Per FM 2-0: 'OSINT reports … which may "
            "be incorporated into intelligence estimates, intelligence "
            "summaries, intelligence running estimates, and others.'"
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Header chrome (REPORT NUMBER / DATE OF PUBLICATION / DATE OF "
            "ACQUISITION / COUNTRY-REGION / SUBJECT) → §1 Source "
            "Description and Reliability → §2 Summary of Information → §3 "
            "Details of Post / Intercepted Text (verbatim) → §4 Geospatial "
            "and Technical Metadata → §5 Collector's Comments. Section "
            "numbering and titles match the customer-provided example."
        ),
    },
    # Tier 1 — single-source, no upstream artifact dependency. The source
    # IS the IDXOpenSourceReport vertex bound by the autofire context.
    "consumes_artifacts": [],
    "header_fields": {
        # Per-event header fields — values vary across every fire. The
        # autofire's ANALYST CONTEXT block exposes the canonical value
        # for each (report_number / date_of_publication / etc.) and the
        # writer LLM copies them verbatim. source="analytical" routes
        # through the per-field LLM dispatch so the writer SEES the
        # context block; source="session" would short-circuit the
        # dispatch in dag_executor._run_field_node (DAG returns None
        # for session/computed/tool: header sources) leaving the field
        # empty. Confirmed empty-header symptom on OSIR_20260529T043418Z
        # — paragraph fields rendered correctly via analytical dispatch
        # but every session-sourced header cell came back blank.

        # Customer example: "REPORT NUMBER: OSIR-DIV3ID-26-0442".
        # Format: OSIR-<org-token>-<fiscal-year>-<sequence>. The source
        # IDXOpenSourceReport vertex carries report_id verbatim; the
        # autofire passes it to the writer as the canonical number.
        "report_number": {
            "source": "analytical", "view": "header", "required": True,
            "render_label": "REPORT NUMBER",
            "guidance": (
                "Verbatim report_id from the source IDXOpenSourceReport "
                "vertex (autofire ANALYST CONTEXT 'Header' block supplies "
                "it as `report_number:`). Format: "
                "OSIR-<org-token>-<fiscal-year>-<sequence>. Never invent. "
                "If the context lacks report_number, emit the empty string "
                "rather than fabricate."
            ),
        },
        # Two distinct DTGs — when the source published vs. when the OSINT
        # cell acquired the item. Customer example shows them stacked in
        # the header block, both required.
        "date_of_publication": {
            "source": "analytical", "view": "header", "required": True,
            "render_label": "DATE OF PUBLICATION",
            "guidance": (
                "DTG the SOURCE published the item (post timestamp, "
                "article publication time, broadcast slot). Pull verbatim "
                "from the ANALYST CONTEXT 'Header' block's "
                "`date_of_publication:` line (sourced from "
                "IDXOpenSourceReport.publication_time)."
            ),
        },
        "date_of_acquisition": {
            "source": "analytical", "view": "header", "required": True,
            "render_label": "DATE OF ACQUISITION",
            "guidance": (
                "DTG the OSINT cell acquired / archived the item. Pull "
                "verbatim from the ANALYST CONTEXT 'Header' block's "
                "`date_of_acquisition:` line (sourced from "
                "IDXOpenSourceReport.acquisition_time)."
            ),
        },
        "country_region": {
            "source": "analytical", "view": "header", "required": True,
            "render_label": "COUNTRY/REGION",
            "guidance": (
                "Country and named AO (e.g. 'Estonia / AO BALTIC RESTORE'). "
                "Pull verbatim from the ANALYST CONTEXT 'Header' block's "
                "`country_region:` line; if absent, derive from the "
                "geolocated coordinate's national territory."
            ),
        },
        "subject": {
            "source": "analytical", "view": "header", "required": True,
            "render_label": "SUBJECT",
            "guidance": (
                "One-line subject describing what the report covers. Pull "
                "verbatim from the ANALYST CONTEXT 'Header' block's "
                "`subject:` line — this is what the analyst reading the "
                "distribution list will see first."
            ),
        },
        "prepared_by":    HEADER_PREPARED_BY,
        "classification": HEADER_CLASSIFICATION,
        # Provenance back to the IDXOpenSourceReport kbID. view=internal
        # keeps it off the rendered surface; the writer still gets the
        # dispatch so the value is captured in structured_data.header for
        # downstream consumers and audit.
        "source_kbid": {
            "source": "analytical", "view": "internal", "required": False,
            "render_label": "Source kbID",
            "guidance": (
                "IDXOpenSourceReport.kbID of the source vertex (cougaar "
                "live kbID OR event_data_fixtures synthetic UUID). Pull "
                "verbatim from the ANALYST CONTEXT 'PROVENANCE TAG' line: "
                "`IDXOpenSourceReport.kbID=<uuid>` — emit ONLY the <uuid> "
                "value (drop the 'IDXOpenSourceReport.kbID=' prefix)."
            ),
        },
    },
    "paragraph_fields": [
        # §1 Source Description and Reliability — ICD 203 reliability +
        # information credibility, named source channel + account.
        {"name": "paragraph_1_source_description_and_reliability",
         "view": "published", "shape": "dict",
         "render_label": "1. Source Description and Reliability",
         "required": True, "provenance_required": True,
         "guidance": (
            "Describe the open-source feed and assess its reliability per "
            "ICD 203. Pull every subfield from the IDXOpenSourceReport "
            "vertex VERBATIM — never invent a source name, channel, or "
            "reliability tier. If the vertex lacks a subfield, leave it "
            "empty (the runner will surface the gap) rather than fabricate."
         ),
         "subfields": [
            "source", "source_reliability_icd203",
            "source_reliability_rationale",
            "information_credibility",
            "information_credibility_rationale",
         ]},
        # §2 Summary of Information — narrative rollup of what was observed.
        {"name": "paragraph_2_summary_of_information",
         "view": "published", "shape": "string",
         "render_label": "2. Summary of Information",
         "required": True, "provenance_required": True,
         "guidance": (
            "Two-to-four-sentence narrative summary of what the source "
            "reported — who, what, where, when. Derive from the "
            "IDXOpenSourceReport.summary field (preferred) or condense "
            "from body_text. NEVER add tactical interpretation here — "
            "that belongs in §5."
         )},
        # §3 Details of Post / Intercepted Text — verbatim source content,
        # with translation note if applicable, plus media description.
        {"name": "paragraph_3_details_of_post_or_intercepted_text",
         "view": "published", "shape": "dict",
         "render_label": "3. Details of Post / Intercepted Text",
         "required": True, "provenance_required": True,
         "guidance": (
            "Reproduce the source content verbatim. If translated, include "
            "the translation_note and (when present) the original-language "
            "version. media_description summarizes any attached imagery / "
            "video / audio (duration, content, identifying landmarks). "
            "Pull every subfield from the IDXOpenSourceReport vertex; do "
            "NOT paraphrase the body text."
         ),
         "subfields": [
            "translation_note", "body_text",
            "body_text_original_language",
            "media_description",
         ]},
        # §4 Geospatial and Technical Metadata — MGRS pin, named landmark,
        # tactical markings observed, time of source-media capture.
        {"name": "paragraph_4_geospatial_and_technical_metadata",
         "view": "published", "shape": "dict",
         "render_label": "4. Geospatial and Technical Metadata",
         "required": True, "provenance_required": True,
         "guidance": (
            "Geo + technical metadata that anchors the report to ground. "
            "MGRS coordinate plus named landmark (so the reader recognizes "
            "the location without lookup). tactical_markings lists unit / "
            "vehicle markings observed in source media (verbatim from "
            "IDXOpenSourceReport.tactical_markings — do NOT infer markings "
            "the source did not show). capture_time is when the source "
            "MEDIA was captured (distinct from publication / acquisition "
            "DTGs in the header)."
         ),
         "subfields": [
            "geolocated_mgrs", "geolocated_named_landmark",
            "tactical_markings", "time_of_capture",
         ]},
        # §5 Collector's Comments — PIR alignment + contextual analyst note +
        # cross-cueing recommendation for follow-on collection.
        {"name": "paragraph_5_collectors_comments",
         "view": "published", "shape": "dict",
         "render_label": "5. Collector's Comments",
         "required": True, "provenance_required": True,
         "guidance": (
            "Analyst's interpretation and recommended next collection. "
            "requirement_alignment names the specific PIR this report "
            "satisfies (verbatim from IDXOpenSourceReport.pir_alignment). "
            "contextual_note is short analyst context — what this report "
            "means in the existing intel picture, baselines or prior "
            "reports it corroborates / contradicts. cross_cueing_recommen"
            "dation names the specific follow-on collection asset / area / "
            "tasking the report justifies (verbatim from "
            "IDXOpenSourceReport.cross_cueing_recommendation when present)."
         ),
         "subfields": [
            "requirement_alignment", "contextual_note",
            "cross_cueing_recommendation",
         ]},
    ],
    "subtleties": [
        "ONE OSIR per OSINT row — the OSIR is per-event, not a rollup. "
        "The all-source rollup is INTSUM (a multi-INT product), not OSIR.",
        "Source provenance is non-negotiable — every section's _provenance "
        "carries the IDXOpenSourceReport.kbID of the source vertex.",
        "ICD 203 reliability matrix is for the SOURCE; the information "
        "credibility scale is for the CONTENT. Both are required.",
        "Geolocated MGRS is what makes OSIRs plottable on the operational "
        "graphic — the OSIR autofire pushes an overlay feature with "
        "kind='osint_report' so map renders show the pin and link to the doc.",
        "If the vertex lacks a subfield, emit empty rather than fabricate. "
        "The hard-rule below + runner gap surfacing make absence visible.",
    ],
    "hard_rules": [
        "NEVER invent a source — every cited source name, channel, account, "
        "and URL traces verbatim to IDXOpenSourceReport vertex fields.",
        "NEVER invent source reliability or information credibility ratings — "
        "pull verbatim from sourceReliabilityIcd203 / informationCredibility.",
        "NEVER paraphrase the body_text — §3 reproduces source content verbatim.",
        "Every paragraph's _provenance cites the IDXOpenSourceReport.kbID.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Single source vertex bound at autofire time: the triggering "
        "IDXOpenSourceReport raw record (autofire passes every field in the "
        "ANALYST CONTEXT block — the writer fills sections directly from there).",
        "Multi-OSINT cross-reference (optional): "
        "get_recent_intel(types=['OSINT']) for prior reports the analyst "
        "may want to cite in §5 contextual_note.",
    ],
    "post_emit_summary": (
        "artifact_id, report_number, source_name + source_channel, "
        "geolocated_mgrs, pir_alignment"
    ),
}
