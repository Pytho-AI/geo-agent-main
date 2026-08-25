"""TMP — Target Material Production (target coordinate mensuration data sheet
+ JDPI graphic) — CJCSI 3505.01E paras 4.d.(1) + 4.f, JP 3-60 Ch. III §3.(6),
ATP 2-22.7 Table D-1.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.

The published artifact is named TMP — "Target Material Production". Pytho's
role is to PRE-FILL the data sheet + JDPI graphic structure for downstream
certified-analyst review at an NGA-accredited TMP work center. Pytho does NOT
generate NGA-validated coordinates; the mensurated 3D point, JDPI ID, and
rendered JDPI graphic are the OUTPUTS of the certified workflow.

Per the 2026-05-13 product audit, the JDPI graphic (formerly a standalone
"JDPI" product) is folded into TMP per CJCSI 3505.01E para 4.f: JDPIs are
created and databased by TMP-certified analysts as part of the TMP process —
the graphic is a constituent of TMP, not a separate deliverable. ATP 2-22.7
Table D-1 lists "JDPI graphics (mensurated points)" as a Weaponeering-support
item in the Electronic Target Folder; this schema renders both the data
sheet and the graphic structure in one product.
"""
from ..common import (
    HEADER_CLASSIFICATION, HEADER_DTG, HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "TMP",
    "output_format": "docx",
    "shape": "header_only",
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines the TMP map. JDPI
    # graphic per CJCSI 3505.01E — target reference card with full
    # collateral context. Frontend has zero TMP-specific branches.
    # ------------------------------------------------------------------

    "map_basemap": "default",

    # Per-product overlay gate. TMP = target material — JDPI graphic.
    # Targets + collateral context only.
    "map_overlay_kinds": [
        "threat_objective", "objective",
        "engagement_area",
        "urban_area",  # collateral context
        "boundary",
    ],

    # Full road density at target scale — analyst needs to read every
    # road around the target for navigation reference + collateral
    # evaluation, identical to CDE.
    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-secondary", "omt-road-tertiary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: urban (collateral risk), boundary, points.
    "map_doctrinal_layer_visibility": [
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-points-hit-target",
    ],

    "map_show_topographic_contours": False,
    # Per-target product — no mil-unit rollups; individual symbols
    # only if explicitly placed.
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": False,
    # Full doctrinal legend (target ID, JDPI label, CDE callouts).
    "map_compact_legend_labels": False,
    "doctrine": {
        "purpose": (
            "Target Material Production (TMP) data sheet — captures the inputs that "
            "drive JDPI assignment in the Electronic Target Folder. Provides the "
            "precise 3D geocoordinate to reduce TLE for D3A Deliver.\n\n"
            "Pytho's role here is to PRE-FILL as much of the TMP data sheet + JDPI "
            "graphics structure as the agent can automatically — target identity "
            "block, aimpoint description, source imagery metadata, analyst "
            "certification block — BEFORE human review and completion. The final "
            "mensurated 3D coordinate, TLE accuracy statistics, JDPI ID, and parent "
            "ETF EID are the OUTPUTS of the certified TMP workflow and are assigned "
            "downstream by a TCM-certified analyst at an NGA-accredited TMP work "
            "center. The agent does NOT generate NGA-validated coordinates." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Single-target product (header_only shape). One TMP per aimpoint per pre-strike timeline.",
    },
    "consumes_artifacts": ["HPTL"],
    # Per-field upstream dep filter — narrow the per-field writer prompt
    # to the writer-relevant HPTL slice only. Drops HPTL header /
    # provenance / map_overlays scaffolding which TMP doesn't need.
    "default_data_source_filter": {
        "upstream:HPTL": ["hptl_rows"],
    },
    "header_fields": {
        # JDPI ID is assigned by the certified TMP work center per CJCSI 3505.01E
        # AT THE MENSURATION STEP. It is the output of mensuration, not a session
        # input. Mark as analytical / optional — the writer leaves it blank when
        # mensuration hasn't actually been performed (IDX 26 stub case — the
        # default for this pipeline).
        "jdpi_id":       {"source": "analytical", "view": "header", "required": False,
                            "render_label": "JDPI ID",
                            "guidance": (
                                "Alphanumeric Joint Desired Point of Impact identifier. "
                                "Assigned by the certified TMP analyst at mensuration. "
                                "LEAVE BLANK when stub_flag is True — the downstream "
                                "TMP work center allocates this ID."
                            )},
        "target_id":     {"source": "session", "view": "header", "required": True,
                            "render_label": "Target ID",
                            "guidance": "BE / CTID / UID format — the parent target this aimpoint belongs to."},
        "dtg":           {**HEADER_DTG, "render_label": "Mensuration DTG"},
        "prepared_by": HEADER_PREPARED_BY,
        "hptl_artifact_id": {"source": "upstream:HPTL", "view": "internal", "required": False,
                                "render_label": "HPTL Reference",
                                "depends_on": ["upstream:HPTL"],
                                "guidance": "Parent HPTL artifact_id when available."},
        # parent_etf_eid is the ETF element identifier the JDPI lands under
        # once the certified ETF custodian publishes it (ATP 2-22.7 Table D-1
        # electronic-target-folder items).
        # In the IDX 26 stub path it is unset — promoted to header so the
        # `required: False` flag actually filters gap detection (which only
        # honors required:False for header fields, not for paragraph_fields).
        "parent_etf_eid":   {"source": "analytical", "view": "header", "required": False,
                                "render_label": "Parent ETF EID",
                                "guidance": (
                                    "Electronic Target Folder element identifier this "
                                    "JDPI is published under. Allocated by the ETF "
                                    "custodian. LEAVE BLANK when stub_flag is True — "
                                    "the downstream TMP work center allocates this when "
                                    "the JDPI is published into the folder."
                                )},
        # JDPI-graphic header fields (folded from the former standalone JDPI product
        # per 2026-05-13 audit). The graphic accompanies the data sheet per
        # CJCSI 3505.01E para 4.f.
        "weaponeering_objective": {"source": "session", "view": "header", "required": True,
                                       "render_label": "Weaponeering Objective",
                                       "guidance": (
                                           "Explicit weaponeering objective the JDPI is "
                                           "associated with (e.g., 'functional kill of "
                                           "fire-control radar emitter — break the "
                                           "engagement envelope'). Drives aimpoint "
                                           "selection rationale per JP 3-60 Ch. III §3.(6)."
                                       )},
        "graphic_standards_reference": {"source": "constant", "view": "header", "required": True,
                                            "default": "JDPI graphic — standard format",
                                            "render_label": "Graphic Standards Reference",
                                            "guidance": (
                                                "Reference for JDPI graphic format. "
                                                "Constant; surfaced in header for "
                                                "downstream-consumer compliance traceability."
                                            )},
        "archived_to_midb": {"source": "constant", "view": "header", "required": True,
                                 "default": True,
                                 "render_label": "Archived to MIDB/MARS",
                                 "guidance": (
                                     "TMP-produced JDPIs (data sheet + graphic) are "
                                     "databased in MIDB/MARS within five business days "
                                     "of publishing per CJCSI 3505.01E para 4.f. Always "
                                     "True for a completed TMP. (Cueing-grade "
                                     "mensuration that is not databased is TMO — a "
                                     "different workflow, out of scope here.)"
                                 )},
        "stub_flag":     {"source": "constant", "view": "header", "required": True,
                            "default": True,
                            "render_label": "STUB",
                            "guidance": "TCM-grade input data not provided"},
        "stub_reason":   {"source": "constant", "view": "header", "required": True,
                            "default": (
                                "TCM-grade input data not provided. JDPI ID + parent "
                                "ETF EID will be allocated by the certified TMP work "
                                "center when actual mensuration is performed."
                            )},
        "classification": HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "target_identity",
         "view": "published",
         "shape": "dict",
         "render_label": "Target Identity (ETF Heading)",
         "required": True,
         # Identity block is deterministic KG lookup against the bound
         # target's entity_id — NOT LLM-authored prose. Each subfield
         # resolves via kg:<field> against the bound target_focus.
         "subfields": ["category_code", "country_code", "target_identification",
                        "o_suffix", "last_update", "target_name", "geocoordinates"],
         "subfield_specs": {
            "category_code":          {"source": "entity:category"},
            "country_code":           {"source": "entity:country_code"},
            "target_identification":  {"source": "entity:target_identification"},
            "o_suffix":               {"source": "entity:o_suffix"},
            "last_update":            {"source": "entity:last_update"},
            "target_name":            {"source": "entity:name"},
            # geocoordinates surfaces the kg entity's coarse MGRS
            # reference only — deterministic, NEVER LLM-authored.
            "geocoordinates":         {"source": "entity:location_mgrs"},
         }},
        {"name": "mensurated_coordinate",
         "view": "published",
         "shape": "dict",
         "render_label": "Mensurated Coordinate (3D — TMP output)",
         # NOT required in stub mode. The hard constraint "no LLM-emitted
         # spatial coordinates anywhere" forbids the writer from filling
         # any subfield here — every coord subfield is stub-pass-through.
         "required": False,
         "guidance": (
             "STUB BLOCK in IDX-26 default. EVERY subfield emits the "
             "verbatim string '[ANALYST INPUT REQUIRED]' when "
             "stub_flag is True. Do NOT partially fill, do NOT "
             "concatenate derived values with this placeholder "
             "(e.g., '35VME00686633[ANALYST INPUT REQUIRED]' is a "
             "BUG class to avoid). The LLM has zero business "
             "emitting spatial coordinates; the certified TMP "
             "analyst at the NGA-accredited work center fills "
             "this block at mensuration."
         ),
         "subfields": ["lat_lon_decimal", "geodetic_height_hae_meters",
                        "msl_elevation_meters", "datum_horizontal", "datum_vertical",
                        "ellipsoid", "mgrs_10_digit", "mgrs_15_digit"],
         "subfield_specs": {
            "lat_lon_decimal":          {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "geodetic_height_hae_meters": {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "msl_elevation_meters":     {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "datum_horizontal":         {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "datum_vertical":           {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "ellipsoid":                {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "mgrs_10_digit":            {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "mgrs_15_digit":            {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
         }},
        {"name": "accuracy_statistics",
         "view": "published",
         "shape": "dict",
         "render_label": "Accuracy Statistics",
         "required": False,
         "guidance": (
             "TLE numeric thresholds CLASSIFIED — emit the category "
             "verbatim and stub the remaining numerics with the "
             "'[ANALYST INPUT REQUIRED]' sentinel. Do NOT synthesize "
             "CE/LE numerics."
         ),
         "subfields": ["ce_90_horizontal_m", "le_90_vertical_m",
                        "tle_category", "sep_3d_optional", "cep_50_optional"],
         "subfield_specs": {
            "ce_90_horizontal_m":   {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "le_90_vertical_m":     {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "sep_3d_optional":      {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "cep_50_optional":      {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
         }},
        # imagery_metadata now absorbs source_imagery_annotation's imagery
        # half — the two were divergent prose blocks describing the same
        # source image. Consolidated to one LLM call. The unique
        # aimpoint_pixel_x/y/callout fields stay in
        # source_imagery_annotation below.
        {"name": "imagery_metadata",
         "view": "published",
         "shape": "dict",
         "render_label": "Imagery / Source Metadata",
         "required": False,
         "subfields": ["primary_image_id", "secondary_image_id_optional",
                        "sensor_type", "platform", "collection_dtg_z",
                        "gsd_meters", "niirs_rating", "sensor_geometry_look_angle",
                        "sensor_geometry_azimuth", "support_data_model",
                        "dem_used", "mensuration_method"],
         "subfield_specs": {
            "primary_image_id":              {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "secondary_image_id_optional":   {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "sensor_type":                   {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "platform":                      {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "collection_dtg_z":              {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "gsd_meters":                    {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "niirs_rating":                  {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "sensor_geometry_look_angle":    {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "sensor_geometry_azimuth":       {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "support_data_model":            {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "dem_used":                      {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "mensuration_method":            {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
         }},
        {"name": "analyst_certification",
         "view": "published",
         "shape": "dict",
         "render_label": "Analyst Certification",
         "required": False,
         "guidance": (
             "Certified analyst block — every subfield emits the "
             "'[ANALYST INPUT REQUIRED]' sentinel when stub_flag is "
             "True. tcm_tool_name MUST be a NGA-validated TCM tool "
             "name (RainStorm / Socet GXP / PRISMATIC / DPPDB "
             "Workstation / [ANALYST INPUT REQUIRED]) — NEVER any "
             "Pytho-internal agent or tool name (cougaar, pytho, "
             "claude, vllm). This field names the certified "
             "mensuration tool the analyst will use, not the "
             "drafting agent."
         ),
         "subfields": ["analyst_name", "analyst_org", "tcm_certification_level",
                        "certification_number", "certification_expiry",
                        "tcm_tool_name", "tcm_tool_version",
                        "qc_reviewer_name", "qc_reviewer_certification"],
         "subfield_specs": {
            "analyst_name":                {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "analyst_org":                 {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "tcm_certification_level":     {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "certification_number":        {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "certification_expiry":        {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "tcm_tool_name": {
                "source": "constant", "default": "[ANALYST INPUT REQUIRED]",
                "stub_pass_through": True,
                "enum": [
                    "RainStorm", "Socet GXP", "PRISMATIC",
                    "DPPDB Workstation", "[ANALYST INPUT REQUIRED]",
                ],
                "guidance": (
                    "NGA-validated TCM tool name. NEVER any Pytho-"
                    "internal agent or tool name (cougaar, pytho, "
                    "claude, vllm). When stub_flag=True emit "
                    "'[ANALYST INPUT REQUIRED]'."
                ),
            },
            "tcm_tool_version": {
                "source": "constant", "default": "[ANALYST INPUT REQUIRED]",
                "stub_pass_through": True,
                "guidance": (
                    "Version of the NGA-validated TCM tool. NEVER "
                    "any Pytho-internal agent or model version. "
                    "When stub_flag=True emit '[ANALYST INPUT "
                    "REQUIRED]'."
                ),
            },
            "qc_reviewer_name":            {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "qc_reviewer_certification":   {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
         }},
        {"name": "aimpoint_description",
         "view": "published",
         "shape": "string",
         "render_label": "Aimpoint Description",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Prose description of the specific aimpoint on the target (e.g. "
             "'fire-control radar antenna pedestal, north face'). Drives weaponeering "
             "intent and post-strike Phase 1 PDA correlation."
         )},
        # JDPI-graphic paragraph fields (folded from the former standalone JDPI
        # product per 2026-05-13 audit). The graphic captures the visual product
        # showing the mensurated aimpoint on its source imagery for briefing,
        # mission-planning handoff, or strike-package reference.
        {"name": "aimpoint_identification",
         "view": "published",
         "shape": "dict",
         "render_label": "Aimpoint Identification (JDPI Graphic)",
         "required": True,
         "guidance": (
             "Identifies the specific aimpoint on the target. Aimpoints are "
             "selected based on analysis of critical elements to ensure their "
             "engagement creates the desired operational effect. Drives "
             "functional-kill rationale per JP 3-60 Ch. III §3.(6)."
         ),
         "subfields": ["aimpoint_name", "critical_element_description",
                        "intended_effect", "functional_kill_rationale"]},
        {"name": "source_imagery_annotation",
         "view": "published",
         "shape": "dict",
         "render_label": "Source Imagery Annotation (JDPI Graphic Content)",
         "required": False,
         "guidance": (
             "Annotation parameters for the rendered JDPI graphic — "
             "the source-imagery metadata half of this block has been "
             "merged into imagery_metadata (single source of truth). "
             "This block now carries ONLY the unique aimpoint-overlay "
             "fields: pixel_x / pixel_y on the primary image + the "
             "callout text. Every subfield is stub_pass_through in "
             "IDX-26 default. NGA samples ~10% of TMP-produced data "
             "for re-mensuration; analyst at the certified work "
             "center fills these at annotation time."
         ),
         "subfields": ["aimpoint_pixel_x", "aimpoint_pixel_y",
                        "annotation_callout_text"],
         "subfield_specs": {
            "aimpoint_pixel_x":         {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "aimpoint_pixel_y":         {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
            "annotation_callout_text":  {"source": "constant", "default": "[ANALYST INPUT REQUIRED]", "stub_pass_through": True},
         }},
        {"name": "weaponeering_annotation",
         "view": "published",
         "shape": "string",
         "render_label": "Weaponeering Annotation",
         "required": False,
         "provenance_required": True,
         "guidance": (
             "Optional weaponeering-context annotation rendered on the JDPI "
             "graphic — desired munition / attack heading / impact angle "
             "narrative. Drives downstream weaponeering review per ATP 2-22.7 "
             "Weaponeering-support row. NOT a substitute for the formal "
             "weaponeering solution."
         )},
    ],
    "subtleties": [
        "Panchromatic imagery is the common GEOINT source for mensuration. Tool-specific guidance comes from the NGA-validated TCM tool list and the tool's NGA Technical Review Team validation statement.",
        "TLE numeric thresholds are CLASSIFIED. Consume the category, never synthesize a numeric.",
        "TMP vs TMO authority: only TMP-produced JDPIs are databased in MIDB/MARS and authorize coordinate-seeking weapons. TMO is cueing-grade (not databased) and supports dynamic-targeting current operations only — different workflow, not in this product.",
        "NLRP is NOT mensuration — it is a separate aimpoint type for nonlethal effects and does NOT represent a precise 3D geocoordinate measured by a certified analyst. NLRP-based aimpoints must NOT be rendered through this schema.",
        "MIDB → MARS transition — ETF backend may be either; do not hardcode.",
        "jdpi_id and parent_etf_eid are OUTPUTS of the certified TCM/ETF process — not session inputs. They are correctly blank in the stub case; the downstream TMP work center allocates them.",
        "JDPI is the canonical DoD aimpoint identifier per JP 3-60 Ch. III §3.(6)(c). Other aimpoint types (DPI, DMPI, NLRP) are distinct; do not render them as JDPI.",
        "Graphic standards are externally published. The agent does not render the imagery overlay itself — that is produced by the certified analyst using NGA-validated tooling per the published graphic standards. The schema captures the structured metadata that must accompany it.",
        "STUB — TCM-grade inputs (sub-meter pan imagery, support-data model, certified mensuration tool, NGA-accredited work center) are not provided; the agent renders the TMP data sheet + JDPI graphic structure (target identity, source-imagery metadata, analyst-certification block, aimpoint description + identification + annotation) for downstream certified-analyst review and completion. The agent does NOT produce a TMP-grade JDPI.",
    ],
    "hard_rules": [
        "WGS 84 default datum.",
        "MGRS 10-digit standard procedure.",
        "Cite imagery_id + sensor_geometry for every measurement.",
        "Cite primary_image_id + aimpoint pixel coordinates for the rendered JDPI annotation.",
        "Cite analyst certification number.",
        "Never synthesize a numeric TLE (CE/LE) — those thresholds are classified; emit the category only.",
        "archived_to_midb must be True for a completed TMP (databasing requirement per CJCSI 3505.01E para 4.f). Stub case leaves the artifact incomplete; archived_to_midb remains True as the target state once the certified workflow runs.",
        "Do not produce a JDPI graphic from a TMO mensuration or an NLRP — those are distinct workflows / aimpoint types and not databased.",
        "When stub_flag is True, leave jdpi_id and parent_etf_eid blank (do not invent placeholder strings — they encode whether the certified TMP workflow has actually run).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Target identity: get_target(target_id=<id>)",
        "HPTL parent: list_project_docs(filter={type:'HPTL'}) then get_project_doc",
        "Imagery: get_recent_intel(types=['imagery'])",
        "Threat structure (target unit context — now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Operations overlay control measures (target material geometry — axis / OBJ / EA / NAI / TAI proximity): get_spatial_overlay()",
        "Phased concept of operations (production priority shifts by phase): get_phases() — current phase + decisive point + phase objectives",
        "Map render: render_map(layers=['targets','spatial_overlay'], format='structured')",
    ],
    "post_emit_summary": "artifact_id, target_id, JDPI summary or stub status",
}
