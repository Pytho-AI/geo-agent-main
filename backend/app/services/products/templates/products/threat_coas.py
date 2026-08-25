"""Threat COAs — Step-4 published deliverable per the IBL example exhibit.

Combines Threat COA Statement (analytical text per COA) + per-COA SITEMP
(templated graphic for each COA) into a single landscape PPTX with one
slide per COA. Each slide matches the layout in the IBL example pack
(scratch/docs/ibl/event_samples/IPSR03_B_16_Exh_03D01_Threat_COAs_OPORD_*
.pptx):

  ┌──────────────────────────────────────────────────────────────────┐
  │  Threat COA N — <descriptive name>           [classification]    │
  ├────────────┬────────────────────────────────────┬────────────────┤
  │ TASK ORG   │                                    │ Mission        │
  │            │                                    │ <text>         │
  │            │   per-COA SITEMP map (units,       │                │
  │            │   axes, EAs, objectives painted    │ Phased Actions │
  │            │   by per-COA SITEMP renderer)      │ <text>         │
  │            │                                    │                │
  │            │                                    │ Decisive       │
  │            │                                    │ Engagement     │
  │            │                                    │                │
  │            │                                    │ Continuing Ops │
  └────────────┴────────────────────────────────────┴────────────────┘

Threat COA Statement stays as the upstream analytical DOCX (six basic
questions, validity criteria, per-COA HVT lists). SITEMP per-COA stays
as the upstream graphic. Threat COAs is the consolidated commander-
facing PPTX that fuses them. Per the doctrinal example this is the
deliverable an analyst hands the commander.

The map for each slide is looked up at RENDER time from the per-COA
SITEMP artifact (matched by coa_id) — no back-fill, no in-place patch
of Threat COA Statement. The exporter does the lookup when emitting
the slide.

# ─────────────────────────────────────────────────────────────────────
# Threat COAs PPTX is a LAYOUT TRANSFORMER of upstream Threat COA
# Statement + per-COA SITEMP. Every subfield that mirrors an upstream
# field declares from:/path: keys to mechanically carry through; no
# LLM re-derivation. Subfields that don't mirror upstream are slide-
# format-specific and writer-LLM-authored.
#
# from:/path: grammar (canonical-on-disk resolver):
#   "from": "<UpstreamProductName>"   # e.g. "Threat COA Statement"
#   "path": "<json_path>"             # e.g. "coas[<index>].<field>"
#
# json_path supports:
#   - dot-walk: "header.coa_id"
#   - list-index by paragraph-iteration: "coas[<index>].<field>"
#       (the resolver iterates the upstream list and emits one slide
#       per upstream entry; <index> binds to the iteration cursor)
#   - list-lookup by subfield value:
#       "SITEMP[header.coa_id=<this.coa_id>]"
#       (the resolver scans the upstream list for the matching item)
#
# Subfield resolution runs POST-LLM-emit — the writer's emitted value
# for the subfield is overwritten by the mechanically-resolved value
# when the upstream payload yields a non-None result. The resolver
# routes every load through schema_state.json on disk so analyst edits
# to the upstream artifact (persisted by the finalize trigger) flow
# into downstream products on the next regenerate.
# ─────────────────────────────────────────────────────────────────────

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
    "name": "Threat COAs",
    "output_format": "pptx",
    "shape": "structured",

    # Analyst-configurable knobs surfaced via the gear button next to
    # Generate on the dashboard. Same gating + persistence mechanism as
    # HVTL's hvt_worthy_categories. See main._generate_with_config and
    # equipment_doctrine.SHOW_COA_ROLE_BADGES_OVERRIDE.
    "config_fields": {
        # Title-bar role badge ([MOST LIKELY] / [MOST DANGEROUS] /
        # [MOST DECEPTIVE]) on each per-COA slide. Default False — slide
        # titles read as bare "COA-1: <label>" / "COA-2: ..." / etc.
        # Toggle on for briefings where the audience needs the doctrinal
        # role surfaced. The rank / most_dangerous / most_deceptive
        # schema fields remain so the per-COA narrative + downstream
        # products can reference them; only the title-bar badge is
        # suppressed.
        "show_coa_role_badges": {
            "type": "bool",
            "render_label": "Show [MOST LIKELY] / [MOST DANGEROUS] / [MOST DECEPTIVE] badges on COA slide titles",
            "default": False,
        },
    },
    "doctrine": {
        "purpose": (
            "Consolidated Step-4 threat-COA presentation deck. Combines "
            "Threat COA Statement's analytical per-COA descriptions with "
            "the per-COA SITEMP graphic into one landscape PPTX — one "
            "slide per COA. This is the commander-facing deliverable; "
            "Threat COA Statement + SITEMPs remain as the analytical "
            "workpapers feeding it.\n\n"
            "LAYOUT TRANSFORMER — every subfield that mirrors an "
            "upstream Threat COA Statement subfield declares "
            "source='ref:Threat COA Statement:coas[<index>].<field>'. "
            "The backend resolver pulls the value mechanically; the "
            "writer LLM is bypassed for those subfields. Subfields not "
            "in the upstream payload (slide-format-specific) keep the "
            "existing depends_on + LLM mechanism." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "One slide per upstream Threat COA Statement COA, in COA "
            "rank order ascending (rank=1 first, highest rank last). "
            "The rank-to-role binding (most-likely / intermediate / "
            "most-dangerous / most-deceptive) is configured in the "
            "upstream Threat COA Statement product_config.coa_set; the "
            "deck inherits the order, never re-decides it."
        ),
    },
    "consumes_artifacts": ["Threat COA Statement", "SITEMP"],
    "header_fields": {
        # phase + threat_force carry through mechanically from the upstream
        # Threat COA Statement header via the from:/path: resolver. Without
        # this, `source: session` falls through _build_skeleton's setdefault
        # to "" — and the finalize importer treats "" as missing_required_*
        # (422). The session-resolved value upstream IS the canonical value;
        # mirror it here. threat_force aliases upstream `threat` (the
        # upstream column is named `threat`; the Threat COAs render_label is
        # "Threat Force" — alias the value mechanically).
        "phase":              {**HEADER_PHASE,
                                "from": "Threat COA Statement",
                                "path": "header.phase",
                                "depends_on": ["upstream:Threat COA Statement"]},
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "threat_force":       {"source": "session", "view": "header",
                                "required": True,
                                "render_label": "Threat Force",
                                "from": "Threat COA Statement",
                                "path": "header.threat",
                                "depends_on": ["upstream:Threat COA Statement"],
                                "guidance": (
                                    "Named threat for the COA set. "
                                    "Mechanically resolved from upstream "
                                    "Threat COA Statement header.threat via "
                                    "the from:/path: resolver."
                                )},
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal",
                                "required": False,
                                "render_label": "Threat COA Statement Reference",
                                "depends_on": ["upstream:Threat COA Statement"]},
        "prepared_by":        HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "coa_slides",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Threat COAs",
         "required": True,
         "provenance_required": True,
         # Per-slide narrative across N COAs is the largest single
         # emit in this product — each COA carries mission +
         # phased_actions (list of 3-5 phase dicts) +
         # decisive_engagement + branches_and_sequels +
         # continuing_operations + task_org_units (list of ~8-12 unit
         # dicts) + distinguishing_signatures. 3 COAs × all that =
         # ~9-12k chars ≈ 2500-3500 tokens. Default 3000 truncates
         # mid-COA-3; 6000 leaves headroom for the writer's longer
         # narrative on the most-dangerous / most-deceptive COA.
         "max_tokens": 6000,
         "depends_on": [
             "upstream:Threat COA Statement",
             "upstream:SITEMP",
             "anchors",
             "entities:units",
         ],
         "guidance": (
             "One entry per COA in the upstream Threat COA Statement "
             "artifact's coas[] list. Slide iteration cursor binds "
             "<index>; one slide per upstream coas[] entry.\n\n"

             "STRUCTURAL CARRY-THROUGH — the mirrored subfields "
             "(coa_id, rank, most_dangerous, most_deceptive, title, "
             "mission_statement, decisive_engagement, "
             "branches_and_sequels, continuing_operations, "
             "distinguishing_signatures) each declare a source token "
             "pointing at the matching upstream Threat COA Statement "
             "subfield. The backend resolver pulls each value "
             "mechanically; the writer LLM is bypassed for those "
             "subfields. Until the nested-ref resolver lands in "
             "dag_executor.py, the writer LLM continues to emit these "
             "subfields per the carry-through contract — copy the "
             "upstream value verbatim; do NOT re-narrate, re-order, "
             "or substitute synonyms.\n\n"

             "task_org_units is the ONE carry-through subfield that "
             "is NOT a pure 1:1 upstream mirror — it joins upstream "
             "functional_allocation × get_oob() (echelon, "
             "designation) × per-COA SITEMP templated_units. The "
             "source_transform 'task_org_sidebar' names the "
             "deterministic join handler. Until that handler is "
             "registered, the writer authors this field per the "
             "per-subfield guidance.\n\n"

             "sitemp_artifact_id is a render-time lookup against the "
             "autodraft pool. Leave blank during build; the exporter "
             "re-queries the pool at render time."
         ),
         "item_subfields": [
             {"name": "coa_id", "render_label": "COA ID",
              "required": True, "provenance_required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].coa_id",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].coa_id. Writer LLM "
                  "bypassed by the from:/path: resolver. The slide-"
                  "iteration cursor binds <index>; one slide is "
                  "emitted per upstream coas[] entry."
              )},

             {"name": "rank", "render_label": "Rank (1=most likely)",
              "required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].rank",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].rank. Drives slide order."
              )},

             {"name": "most_dangerous", "render_label": "Most Dangerous",
              "required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].most_dangerous",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].most_dangerous. Drives the "
                  "MOST DANGEROUS badge on the slide title bar."
              )},

             {"name": "most_deceptive", "render_label": "Most Deceptive",
              "required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].most_deceptive",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].most_deceptive. Drives the "
                  "MOST DECEPTIVE badge on the slide title bar."
              )},

             {"name": "title", "render_label": "Slide Title",
              "required": True, "provenance_required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].label",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].label. The scheme-of-"
                  "maneuver phrase IS the upstream label — verbatim. "
                  "The PPTX exporter composes the slide title bar "
                  "from rank + label at render time."
              )},

             {"name": "mission_statement",
              "render_label": "Mission",
              "required": True, "provenance_required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].statement",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].statement (six-basic-"
                  "questions dict). Carry-through preserves the "
                  "upstream dict shape; the PPTX exporter renders it "
                  "(key/value paragraph block, or flattened-to-"
                  "paragraph per the slide layout)."
              )},

             {"name": "phased_actions",
              "render_label": "Phased Actions",
              "required": True, "provenance_required": True,
              "guidance": (
                  "List of {phase, threat_action, timing} entries — "
                  "what the threat does during each friendly phase. "
                  "Phase labels come from cougaar.get_phases() / the "
                  "OPORD phase concept. For each phase describe the "
                  "threat's action and any timing anchor doctrine "
                  "specifies (e.g., 'within 4-6 h of confirmed "
                  "breach'). Phase enumeration is scenario-data, "
                  "sourced via get_phases() at runtime — the schema "
                  "does NOT name phases."
              ),
              "shape": "list_of_dicts",
              "item_subfields": [
                  {"name": "phase",
                   "guidance": "Friendly phase label from cougaar.get_phases() / OPORD §3.b."},
                  {"name": "threat_action",
                   "guidance": "One-to-two sentences on the threat's action during this phase."},
                  {"name": "timing",
                   "guidance": "Doctrine-anchored timing if applicable. Blank if no doctrinal anchor applies."}]},

             {"name": "decisive_engagement",
              "render_label": "Decisive Engagement",
              "required": True, "provenance_required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].decisive_engagement",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].decisive_engagement when "
                  "present. The from:/path: resolver bypasses the "
                  "writer LLM. If absent upstream, the LLM falls back "
                  "to composing from coas[].objectives + "
                  "coas[].functional_allocation + the per-COA SITEMP "
                  "engagement_areas — describing where the threat "
                  "seeks to defeat the friendly attack for THIS COA."
              )},

             {"name": "branches_and_sequels",
              "render_label": "Branches and Sequels",
              "required": True, "provenance_required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].branches_and_sequels",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].branches_and_sequels when "
                  "present. If absent upstream, the writer composes "
                  "from coas[].objectives.subsequent + the threat-"
                  "doctrine artifact's branch/sequel decision triggers."
              )},

             {"name": "continuing_operations",
              "render_label": "Continuing Operations",
              "required": False, "provenance_required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].continuing_operations",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].continuing_operations if "
                  "present. The resolver emits nothing (and the "
                  "exporter omits the slide region) if the upstream "
                  "field is absent. Optional."
              )},

             {"name": "task_org_units",
              "render_label": "Task Org (slide sidebar)",
              "required": True, "provenance_required": True,
              "shape": "list_of_dicts",
              "from": "Threat COA Statement",
              "path": "coas[<index>].functional_allocation",
              "source_transform": "task_org_sidebar",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].functional_allocation via "
                  "the deterministic join handler "
                  "source_transform='task_org_sidebar' (joins "
                  "functional_allocation entries with get_oob() "
                  "echelon/designation and optionally the per-COA "
                  "SITEMP templated_units for identity normalization "
                  "to produce the slide-sidebar shape "
                  "[{echelon, designation, doctrinal_role}, ...]).\n\n"

                  "If the source_transform mechanism is not yet "
                  "registered in the resolver, the writer authors "
                  "this field as a JSON array of "
                  "{echelon, designation, doctrinal_role} objects "
                  "(NOT a comma-separated string). Echelon sort "
                  "order CORPS -> DIVISION -> BRIGADE -> BATTALION. "
                  "Pull echelon + designation from get_oob() rows "
                  "named in the upstream functional_allocation; copy "
                  "the doctrinal role (action_force / enabling_force "
                  "/ reserve / fires / c2 / main_effort / "
                  "supporting_effort / reinforcing_effort) the "
                  "upstream entry assigned. Cite the OOB row + "
                  "upstream functional_allocation entry in "
                  "_provenance for each emitted row."
              ),
              "item_subfields": [
                  {"name": "echelon",
                   "enum": ["CORPS", "DIVISION", "BRIGADE", "BATTALION"],
                   "guidance": "Echelon — drives sidebar indent."},
                  {"name": "designation",
                   "guidance": "Unit designation per OOB."},
                  {"name": "doctrinal_role",
                   "required": False,
                   "guidance": "Optional one-line doctrinal role (e.g., 'corps C2', 'main effort', 'reserve')."}]},

             {"name": "sitemp_artifact_id",
              "render_label": "SITEMP Reference (lookup)",
              "required": False,
              "source": "upstream:autodraft_pool:SITEMP[header.coa_id=<this.coa_id>].artifact_id",
              "resolve_at": "exporter_render_time",
              "guidance": (
                  "Mechanically resolved by the exporter at render "
                  "time. The source token names the autodraft-pool "
                  "lookup: find the SITEMP artifact whose "
                  "header.coa_id matches this slide's coa_id, return "
                  "its artifact_id. The build-time resolver leaves "
                  "this blank because the SITEMP fanout may not have "
                  "landed yet at the time the deck writer is "
                  "dispatched; the exporter re-queries the autodraft "
                  "pool when rendering each slide. Do NOT invent."
              )},

             {"name": "distinguishing_signatures",
              "render_label": "Indicators",
              "required": False, "provenance_required": True,
              "from": "Threat COA Statement",
              "path": "coas[<index>].distinguishing_characteristics",
              "guidance": (
                  "Mechanically resolved from upstream Threat COA "
                  "Statement coas[<index>].distinguishing_"
                  "characteristics. The upstream field name is "
                  "'distinguishing_characteristics' (analytical "
                  "workpaper vocabulary); the slide region renders "
                  "it as 'Indicators' (commander-facing vocabulary). "
                  "The carry-through preserves the upstream content "
                  "exactly; only the render_label differs."
              )},
         ]}],
    "subtleties": [
        "Threat COAs is the consolidated commander-facing "
        "deliverable. Threat COA Statement remains the analytical "
        "workpaper (six basic questions, validity criteria, "
        "distinguishing characteristics, probability rationale). "
        "Per-COA SITEMPs remain the per-COA graphics (templated "
        "units, axes, EAs, NAIs, objectives). The Threat COAs deck "
        "reformats — it does not analyze.",

        "Carry-through is STRUCTURAL, not prose. Every subfield "
        "that mirrors an upstream Threat COA Statement subfield "
        "declares source='ref:Threat COA Statement:coas[<index>]."
        "<field>' and the backend resolver pulls the value "
        "mechanically. The writer LLM is bypassed entirely for "
        "those subfields; there is no LLM call to verify against "
        "because none happens. The mirrored set is: coa_id, rank, "
        "most_dangerous, most_deceptive, title, mission_statement, "
        "decisive_engagement, branches_and_sequels, "
        "continuing_operations, distinguishing_signatures.",

        "Map embed is RENDER-TIME LOOKUP. sitemp_artifact_id "
        "declares source='ref:autodraft_pool:SITEMP"
        "[header.coa_id=<this.coa_id>].artifact_id' and "
        "resolve_at='exporter_render_time'. The build-time resolver "
        "leaves the field blank; the exporter re-queries the "
        "autodraft pool when rendering each slide. Writer LLM not "
        "invoked.",

        "Task-org sidebar is a deterministic JOIN, not a mirror. "
        "task_org_units declares source='ref:Threat COA Statement:"
        "coas[<index>].functional_allocation' plus a "
        "source_transform='task_org_sidebar' handler that joins "
        "upstream allocation × get_oob() × SITEMP templated_units "
        "into the slide-sidebar shape. The transform is "
        "deterministic — no LLM. If the transform handler is not "
        "yet registered in the resolver, the field falls back to "
        "writer-LLM authoring with the join described in guidance.",

        "One slide per upstream Threat COA Statement coas[] entry. "
        "The DAG fires Threat COA Statement first, then SITEMP "
        "per-COA fanout, then Threat COAs — by which point the "
        "upstream coas[] list is in the pool and the resolver's "
        "iteration cursor walks it to emit one slide per entry.",

        "Every analytical field carries _provenance.",
    ],
    "hard_rules": [
        "Coverage: emit EXACTLY as many coa_slides entries as the "
        "upstream Threat COA Statement artifact has coas[] entries. "
        "One slide per COA. The resolver's iteration cursor walks "
        "coas[] and the slide count equals the upstream count.",

        "Structural carry-through: the subfields coa_id, rank, "
        "most_dangerous, most_deceptive, title, mission_statement, "
        "decisive_engagement, branches_and_sequels, "
        "continuing_operations, and distinguishing_signatures each "
        "declare source='ref:Threat COA Statement:coas[<index>]."
        "<field>'. The backend resolver pulls the value "
        "mechanically; the writer LLM is bypassed for these "
        "subfields. There is no writer responsibility for carry-"
        "through — the resolver does it. Until the nested-ref "
        "resolver lands in dag_executor.py, the writer emits the "
        "upstream value verbatim per the per-subfield guidance.",

        "title is a templated composition of upstream rank + label: "
        "'Threat COA <rank> — <label>'. The source_template field "
        "expresses the composition declaratively; the resolver "
        "evaluates the embedded ref tokens and substitutes them.",

        "task_org_units is a deterministic JOIN, not a mirror: "
        "source='ref:Threat COA Statement:coas[<index>]."
        "functional_allocation' joined with get_oob() echelon / "
        "designation (and optionally per-COA SITEMP templated_units) "
        "via source_transform='task_org_sidebar'. The transform "
        "handler is deterministic. If the handler is not yet "
        "registered, this is the one subfield that falls back to "
        "writer-LLM authoring with the carry-through contract "
        "enforced in prose.",

        "Map embed is render-time only: sitemp_artifact_id declares "
        "source='ref:autodraft_pool:SITEMP[header.coa_id="
        "<this.coa_id>].artifact_id' and "
        "resolve_at='exporter_render_time'. The build-time resolver "
        "leaves the field blank; the exporter re-queries at render "
        "time. Do NOT invent.",

        "Every analytical field carries _provenance citing the "
        "upstream Threat COA Statement / SITEMP source row. The "
        "resolver populates _provenance from the source token's "
        "resolution metadata; the writer does not author "
        "_provenance for mechanically-resolved subfields.",

        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Threat COA Statement parent (one slide per coas[] entry): "
        "list_project_docs(filter={type:'Threat COA Statement'}) "
        "then get_project_doc(tag=<latest>)",
        "Per-COA SITEMPs (templated_units / engagement_areas / NAIs "
        "/ TPLs / threat objectives for each COA): "
        "list_project_docs(filter={type:'SITEMP'}) then "
        "get_project_doc per SITEMP — match by header.coa_id",
        "OPORD friendly phase concept (drives phased_actions phase "
        "labels + timing anchors): get_project_doc(tag='OPORD') §3.b",
        "Threat structure (task_org_units): get_oob()",
        "Phased concept of operations: get_phases() — current phase "
        "+ decisive point + phase objectives",
        "Prior Threat COAs (regen): "
        "list_project_docs(filter={type:'Threat COAs'})",
    ],
    "post_emit_summary": "artifact_id, coa_slides count, slide titles",
}
