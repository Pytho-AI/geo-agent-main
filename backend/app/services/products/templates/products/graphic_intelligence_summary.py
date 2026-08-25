"""GRINTSUM — Graphic INTSUM — ATP 2-33.4.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_PREPARED_BY,
    HEADER_SPATIAL_OVERLAY_BBOX,
    HEADER_SPATIAL_OVERLAY_MAP_ID,
    HEADER_SPATIAL_OVERLAY_URL,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "GRINTSUM",
    "output_format": "pptx",
    "shape": "paragraph",
    # Daily roll-up cadence per V Corps OPORD reporting standard:
    # "GRINTSUMs daily NLT 0600L".
    "cadence_hours": 24,
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines the GRINTSUM map.
    # Daily intel roll-up — broad threat disposition + NAIs/DPs over
    # clean SITEMP-style backdrop. Frontend has zero GRINTSUM-specific
    # branches.
    # ------------------------------------------------------------------

    "map_basemap": "default",

    # Per-product overlay gate. GRINTSUM = broad graphic intel summary.
    # Includes threat disposition + key terrain + NAIs/DPs.
    "map_overlay_kinds": [
        "avenue_of_approach", "key_terrain",
        "threat_objective", "range_fan",
        "battle_position", "engagement_area",
        "named_area_of_interest", "decision_point",
        "phase_line", "boundary",
        "axis_of_advance",  # friendly framework
    ],

    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: urban + boundary framework, NAI/TAI (recent
    # activity dots typically land in NAIs). No phase lines — GRINTSUM
    # is a daily roll-up, phase lines clutter at this cadence.
    "map_doctrinal_layer_visibility": [
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-nai-line", "mcoo-tai-line",
        "mcoo-points-hit-target",
    ],

    "map_show_topographic_contours": False,
    # GRINTSUM is roll-up cadence; individual threat unit symbols
    # would crowd the 1-2 slide format. No mil-units typically.
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": True,
    "map_compact_legend_labels": True,
    "doctrine": {
        "purpose": (
            "Graphical representation of the INTSUM. 1–2 PowerPoint slides emphasizing "
            "threat force locations vs friendly force locations. Includes current PIRs + "
            "summary of threat activities + multi-discipline rollup. Daily roll-up per OPORD." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Map-dominant slide 1 + optional zoom-inset slide 2.",
    },
    # INTSUM is the canonical upstream — GRINTSUM is its graphical
    # rendering. Tier 1 BOTH rollups AND atomics so mid-cycle graphical
    # briefs surface developing activity (see INTSUM comment).
    "consumes_artifacts": ["INTSUM", "SITEMP", "Threat Overlay", "MCOO", "WEM",
                            "TEM", "CCA", "HPTL", "HVTL", "BDA",
                            "SIGSUM", "HUMINTSUM", "OSIR", "KLIEGLIGHT"],
    "header_fields": {
        "area_of_operations":  HEADER_AO,
        "reporting_period_start_z": {"source": "computed", "view": "header", "required": True,
                                       "render_label": "Reporting Period Start"},
        "reporting_period_end_z":   {"source": "computed", "view": "header", "required": True,
                                       "render_label": "Reporting Period End"},
        "dissemination_nlt":   {"source": "session", "view": "header", "required": True,
                                  "render_label": "Disseminate NLT"},
        "intsum_artifact_id":  {"source": "upstream:INTSUM", "view": "internal", "required": True,
                                  "depends_on": ["upstream:INTSUM"]},
        "sitemp_artifact_id":  {"source": "upstream:SITEMP", "view": "internal", "required": False,
                                  "depends_on": ["upstream:SITEMP"]},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay", "view": "internal", "required": False,
                                          "depends_on": ["upstream:Threat Overlay"]},
        "mcoo_artifact_id":    {"source": "upstream:MCOO", "view": "internal", "required": False,
                                  "depends_on": ["upstream:MCOO"]},
        "prepared_by":      HEADER_PREPARED_BY,
        "classification":      HEADER_CLASSIFICATION,
        # Map embed fields — populated by handlers/intel_agent.py:_build_skeleton
        # from render_map() output. Hidden from the header k/v table; surface as
        # the <figure> map embed below the header.
        "spatial_overlay_url":    HEADER_SPATIAL_OVERLAY_URL,
        "spatial_overlay_map_id": HEADER_SPATIAL_OVERLAY_MAP_ID,
        "spatial_overlay_bbox":   HEADER_SPATIAL_OVERLAY_BBOX,
    },
    "paragraph_fields": [
        # GRINTSUM doctrinally renders as 1-2 slides: a theater overview map
        # (slide 1) emphasizing threat vs friendly disposition + an optional
        # zoom inset (slide 2) focused on the area where the period's
        # significant activity occurred. Both are declared as map paragraph
        # fields; the zoom is optional so an empty render leaves no slide.
        {"name": "overview_map",
         "view": "published",
         "shape": "map",
         "render_label": "Threat / Friendly Disposition",
         "required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Live data — threat dispositions, targets, period SIGACTs/
             # engagements/imagery, control measures, phase blocks,
             # terrain anchors, civil context.
             "entities:units",
             "entities:marked",
             "clauses:episodic",
             "map:state",
             "anchors",
             "map:state",
             "entities:civil",
             # Upstream products that contribute map overlays.
             "upstream:INTSUM", "upstream:SITEMP",
             "upstream:Threat Overlay", "upstream:MCOO",
             "upstream:SIGSUM",
         ]},
        {"name": "zoom_inset_map",
         "view": "published",
         "shape": "map",
         "render_label": "Period Activity Zoom",
         "required": False,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Same data as overview_map — render is a zoomed crop of
             # the same overlay set, no different data deps.
             "entities:units",
             "entities:marked",
             "clauses:episodic",
             "map:state",
             "anchors",
             "map:state",
             "entities:civil",
             "upstream:INTSUM", "upstream:SITEMP",
             "upstream:Threat Overlay", "upstream:MCOO",
             "upstream:SIGSUM",
         ]},
        {"name": "current_pirs",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Current PIRs",
         "required": True,
         "guidance": (
             "Mirror the PIR list carried in the parent INTSUM's Paragraph 6 (so "
             "graphic and narrative products agree). Pull from intsum_artifact_id "
             "when available; otherwise from OPORD / FRAGO."
         ),
         "item_subfields": [
             {"name": "requirement_text", "render_label": "PIR",
              "required": True,
              "depends_on": ["upstream:INTSUM"],
              "guidance": "PIR text VERBATIM from OPORD / FRAGO / parent INTSUM — do not paraphrase."},
             {"name": "answered", "render_label": "Answered",
              "required": True,
              "guidance": "Yes / No / Partially, against intel collected this reporting period."},
             {"name": "explanation", "render_label": "Explanation",
              "required": False,
              "guidance": (
                  "Conditional. Populate only when answered is No or Partially. "
                  "Short note ('asset weather-degraded', 'no observation opportunity'). "
                  "'No update this period' is acceptable. Leave blank when answered==Yes."
              )}]},
        {"name": "threat_activities_summary",
         "view": "published",
         "shape": "string",
         "render_label": "Threat Activities Summary",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Bulleted significant threat activity during the reporting period — one bullet "
             "per discrete observation/engagement/movement. Each bullet cites its source "
             "(recent intel report id, BDA artifact id, SPOTREP, etc.). Map-page "
             "icons should correspond 1:1 to these bullets so the slide reads as a single "
             "coherent story."
         )},
        {"name": "current_near_term_ao_assessment",
         "view": "published",
         "shape": "string",
         "render_label": "Current Near-Term AO Assessment",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Short G-2 assessment of what the threat is most likely to do in the next "
             "24h in this AO. Synthesizes Paragraphs 3+4 of the parent INTSUM into "
             "1–3 sentences a commander can read at a glance. Cite the underlying "
             "Threat COA Statement / SITEMP / INTSUM artifact ids in _provenance."
         )},
        {"name": "multi_discipline_rollup",
         "view": "published",
         "shape": "dict",
         "render_label": "Multi-Discipline Rollup",
         "required": True,
         "guidance": (
             "Per OPORD-example daily rollup: one short paragraph per intel discipline "
             "naming the most relevant collection / report from the reporting period. "
             "Disciplines with no activity get 'No reporting this period.' — never delete "
             "a subfield. 'other' covers OSINT, MASINT, or any discipline not covered "
             "by the named subfields."
         ),
         "subfields": ["sigint", "humint", "geoint", "imint",
                        "interrogation", "other"]},
        {"name": "written_assessment_notes_page",
         "view": "workpaper",
         "shape": "string",
         "render_label": "Written Assessment (Notes Page)",
         "required": False,
         "guidance": "Deeper analytical text in PowerPoint Notes page so graphic stays legible"},
        # Map IS the shape:"map" field(s) above; runner auto-renders + captions.
        # Redundant string field dropped — writer had no handle on the runner UUID.
    ],
    "subtleties": [
        "GRINTSUM is the visual complement to INTSUM; INTSUM carries textual depth.",
        "1–2 slides, file-size constrained for LSCO dissemination.",
        "Zoom strategy: start with general OE map, zoom on key areas.",
        "Notes-page text is the repository for written assessment.",
        "Daily cadence per OPORD example (NLT 0600L for 0001L–2400L period)."],
    "hard_rules": [
        "GRINTSUM is the graphic companion to an INTSUM — never emit a GRINTSUM without a parent intsum_artifact_id.",
        "Map-dominant — threat AND friendly locations both visible.",
        "All current PIRs included (mirror the parent INTSUM's PIR list).",
        "Multi-discipline rollup mandatory per OPORD example; every named subfield emitted (no-activity disciplines say so explicitly).",
        "Each threat-activity bullet cites its observation source.",
        "Current_pirs.explanation is conditional — required only when answered != Yes.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "INTSUM parent: list_project_docs(filter={type:'INTSUM'}) then get_project_doc",
        "Threat dispositions (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob(), list_targets()",
        "Recent intel: get_recent_intel(window_hours=24)",
        "Civil considerations (civil annotations on the graphic — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ — graphic summary base layer): get_spatial_overlay()",
        "Phased concept of operations (phase block on the graphic): get_phases() — current phase + decisive point + phase objectives",
        "SITEMP, Threat Overlay, MCOO, WEM, TEM, CCA, HPTL, BDA: list_project_docs + get_project_doc",
        "Map render: render_map(layers=['terrain','units','spatial_overlay','targets'], format='both')"],
    "post_emit_summary": "artifact_id, near-term AO assessment one-liner, PIR status",
}
