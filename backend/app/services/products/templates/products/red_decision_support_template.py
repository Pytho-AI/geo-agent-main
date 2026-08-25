"""Threat (Red) Decision Support Template — ATP 2-01.3 Step 4 + ATP 2-01.3
para 6-72 analogue, applied to the THREAT commander.

This is the red-perspective mirror of decision_support_template.py. Where the
(blue) DST plots FRIENDLY commander decisions triggered BY enemy activity, this
product plots THREAT commander decisions triggered BY FRIENDLY activity:

  "6 threat decision points predict where the THREAT commander must decide on a
   particular COA — this is doctrinally distinct from friendly DPs and helps
   friendly forces drive when/where the threat must decide."
       — event_template.py subtleties (the threat-DP set this product expands)

The friendly DST answers "where must MY commander decide?". The red DST answers
"where must the ENEMY commander decide, and what friendly action forces that
decision?" — so the friendly staff can template the threat's decision logic and
drive (or pre-empt) it. Decisions are keyed to the same three trigger types
(phase lines, ground events, friendly actions) but read from the Donovian /
threat commander's seat.

Upstream is the Threat COA Statement (the threat COAs whose decision logic this
templates), the per-COA SITEMPs (the threat scheme of maneuver the DPs sit on),
and the Event Template's threat-decision-point section. Unlike the blue DST,
this product is text/matrix only — NO map. The substance is the threat-DP
matrix (DP × trigger × threat-decision × options × effect-on-threat-COA). A
threat-perspective graphic already lives on the SITEMP / Threat Overlay (both
red), so the red DST does not re-plot one.

The `scenario.py` source file is NEVER modified — this is a schema definition
consumed by the product writer / DAG runner.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map. The friendly
companion lives in decision_support_template.py.
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
    "name": "Threat Decision Support Template",
    "output_format": "pptx",
    "shape": "structured",
    # ------------------------------------------------------------------
    # NO MAP. Unlike the (blue) Decision Support Template, the red DST is a
    # text/matrix-only product — the threat-DP table is the substance. The
    # blue DST's map render config (map_basemap / map_overlay_kinds /
    # map_*_layer_visibility) and its shape="map" paragraph_field are
    # intentionally omitted here, so this product never emits a map slide
    # and the geo-agent doctrinal paint allowlist does not need an entry
    # for it. If a threat-DP graphic is wanted later, it belongs on the
    # SITEMP / Threat Overlay (already threat-perspective red), not here.
    # ------------------------------------------------------------------
    "doctrine": {
        "purpose": (
            "Step-4 IPOE, threat perspective: template the points on the "
            "battlefield where the THREAT commander will be required to make "
            "decisions on which COA to execute, and identify the deciding "
            "force's opposing action that forces each threat decision. Lets the "
            "opposing staff drive (or pre-empt) the threat's decision cycle — "
            "get inside the threat commander's OODA loop by knowing where and "
            "when he must commit. Decisions can be keyed to phase lines, events "
            "on the ground, or to specific opposing-force actions. Built off "
            "the Threat COA Statement + SITEMP + the Event Template's threat "
            "decision points. "
            # Party-naming directive — reaches every field via the system
            # prompt (dag_executor builds sys prompt from doctrine.purpose).
            # Roles are inverted vs. the blue DST: here the ENEMY (red) force is
            # the decider and the FRIENDLY (blue) force is the trigger.
            "PARTY NAMING: refer to each side by its ROLE followed by the "
            "ACTUAL force name in parentheses — write 'enemy (<force>)' for the "
            "red/threat side and 'friendly (<force>)' for the blue side, e.g. "
            "'enemy (Donovian)' / 'friendly (V Corps)'. Resolve the "
            "parenthetical from the data: for the enemy side use the red force's "
            "designation (the nation or named OPFOR plus the specific committing "
            "unit, from the threat OOB — the enemy is the DECIDING force in the "
            "red DST); for the friendly side use the commanding formation / "
            "higher HQ from the OPORD + friendly OOB (the friendly force's "
            "action TRIGGERS the enemy decision). After the first 'enemy "
            "(<force>)' / 'friendly (<force>)' reference in a field you may use "
            "the bare force name (e.g. 'Donovian', '1st ID'). Never emit a bare "
            "'enemy'/'friendly' with NO force name when one is available in the "
            "data." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Threat decision points ordered by trigger time (earliest "
            "first), then by NAI ID within the same time-phase line."
        ),
    },
    "consumes_artifacts": ["Threat COA Statement", "SITEMP", "Event Template", "MCOO"],
    "header_fields": {
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal",
                                "required": False,
                                "render_label": "Threat COA Statement Reference",
                                "depends_on": ["upstream:Threat COA Statement"],
                                "guidance": (
                                    "Parent Threat COA Statement — the threat "
                                    "COAs whose decision logic this red DST "
                                    "templates."
                                )},
        "event_template_artifact_id": {"source": "upstream:Event Template", "view": "internal",
                                         "required": False,
                                         "render_label": "Event Template Reference",
                                         "depends_on": ["upstream:Event Template"],
                                         "guidance": (
                                             "Upstream Event Template — its "
                                             "threat decision-point section is "
                                             "the canonical source for the "
                                             "threat DPs this product expands."
                                         )},
        "sitemp_artifact_ids": {"source": "upstream:SITEMP", "view": "internal",
                                  "required": False,
                                  "render_label": "SITEMP References",
                                  "depends_on": ["upstream:SITEMP"],
                                  "guidance": (
                                      "Comma-separated SITEMP artifact_ids the "
                                      "threat DPs anchor to. Each DP's "
                                      "trigger_NAI typically traces back to a "
                                      "SITEMP NAI on the threat scheme of "
                                      "maneuver."
                                  )},
        "mcoo_artifact_id":   {"source": "upstream:MCOO", "view": "internal",
                                "required": False,
                                "render_label": "MCOO Reference",
                                "depends_on": ["upstream:MCOO"],
                                "guidance": "Terrain basis for the threat DP locations (MGRS context)."},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # No spatial_overlay_* header fields — this product is text/matrix
        # only and emits no map slide (see the NO MAP note at the top).
    },
    "paragraph_fields": [
        {"name": "threat_decision_points",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Threat Decision Points",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Enemy commander decision points — where the enemy (<force>, e.g. "
             "enemy (Donovian)) commander must decide which COA to execute. "
             "Refer to the red side as 'enemy (<force>)' and the blue side as "
             "'friendly (<force>)', resolving each parenthetical to the actual "
             "force name from the OOB. These are the mirror of the friendly "
             "DST's DPs: an enemy-commander decision triggered BY friendly "
             "(<force>) activity. NEVER write a friendly decision into "
             "threat_decision_text (e.g. 'Commit 1st ID main effort to Valga' "
             "is the friendly (V Corps) commander's decision, not the enemy's). "
             "The canonical enemy decision is the enemy-force commitment — e.g. "
             "'Commit 604 TANK BDE from armored reserve to counter-attack', "
             "'Shift fires to the eastern axis', 'Withdraw to the subsequent "
             "defensive band'. Derive ONE row per enemy decision point in the "
             "Event Template's threat-DP section / the Threat COA Statement's "
             "branches-and-sequels decision logic."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "DP ID",
              "guidance": (
                  "Threat decision-point id, e.g. TDP-1, TDP-2, TDP-3. "
                  "Copy verbatim from the Event Template threat-DP section "
                  "when present; otherwise number sequentially in trigger-"
                  "time order. Prefix with TDP- to distinguish from the "
                  "friendly DST's DP- ids."
              )},
             {"name": "location_mgrs", "render_label": "Location (MGRS)",
              "provenance_required": True,
              "guidance": (
                  "MGRS of the linked NAI / threat decision geometry (look "
                  "up the SITEMP NAI or threat-COA decisive-point mgrs)."
              )},
             {"name": "trigger_NAI", "render_label": "Trigger NAI",
              "provenance_required": True,
              "guidance": (
                 "NAI(s) the enemy (<force>) commander watches to make this "
                 "decision (comma-separated string, NOT a JSON list literal). "
                 "For a red DST these are the NAIs over the friendly (<force>) "
                 "scheme of maneuver — the enemy is collecting against the "
                 "friendly force (name it from the friendly OOB, e.g. "
                 "'friendly (V Corps)', rather than saying 'us')."
              )},
             {"name": "trigger_event", "render_label": "Trigger Event",
              "provenance_required": True,
              "guidance": (
                 "The friendly (<force>) activity at the linked NAI(s) that "
                 "fires the enemy commander's decision — name the actual "
                 "friendly formation from the friendly OOB / OPORD (e.g. "
                 "'friendly (1st ID) main effort identified crossing PL FALCON "
                 "on the Valga axis', 'friendly (1st AD) committed on the "
                 "western flank'). This is the inverse of the friendly DST, "
                 "where the trigger is enemy activity."
              )},
             {"name": "threat_decision_text", "render_label": "Threat Decision",
              "guidance": (
                 "The enemy (<force>) commander's decision — a commitment by "
                 "the named enemy force from the threat OOB, NEVER a friendly "
                 "one. Name the actual committing unit (e.g. 'enemy (Donovian "
                 "604 TANK BDE)'). E.g. 'Commit 604 TANK BDE from armored "
                 "reserve to counter-attack the Valga penetration', 'Trigger "
                 "Donovian 2nd Tank Coy counter-attack at PL FALCON', 'Shift "
                 "main defensive effort east', 'Withdraw to subsequent "
                 "defensive band'. Derive from the Threat COA Statement's "
                 "branches/sequels + Event Template threat DPs."
              )},
             {"name": "options", "render_label": "Threat Options",
              "guidance": (
                 "The 2-3 COA options the enemy (<force>) commander chooses "
                 "between at this DP (pipe-separated). E.g. 'Commit reserve "
                 "forward | Hold reserve for depth | Reinforce eastern axis'. "
                 "An enemy DP with one option is not a decision."
              )},
             {"name": "effect_on_threat_COA", "render_label": "Effect on Threat COA",
              "provenance_required": True,
              "depends_on": ["upstream:Threat COA Statement"],
              "guidance": (
                 "Per-option effect on the enemy (<force>) COA success/risk, "
                 "and how the friendly (<force>) force should exploit / counter "
                 "each — name the friendly formation from the friendly "
                 "OOB/OPORD (e.g. 'friendly (V Corps)'). Derive from the Threat "
                 "COA Statement's distinguishing characteristics + branches/"
                 "sequels. Example: 'Option A commits the armored reserve "
                 "early — exposes the enemy to friendly (V Corps) deep fires in "
                 "EA; Option B preserves the reserve but cedes the Valga "
                 "crossing'."
              )},
             {"name": "latest_time", "render_label": "Latest Time",
              "guidance": (
                 "Latest time the enemy (<force>) commander can make this "
                 "decision and still execute (DDHHMMZ or H-relative, e.g. "
                 "'H+24', 'D+3 0600Z'). For the enemy this is driven by their "
                 "movement / commitment timelines."
              )},
             {"name": "assets_employed", "render_label": "Threat Assets Employed",
              "guidance": (
                 "Enemy (<force>) units the DP commits, named by their actual "
                 "designation from the threat OOB — extract from threat_"
                 "decision_text (e.g. '604 TANK BDE', 'Donovian 2nd Tank Coy', "
                 "'166 AT BDE'). Comma-separated. These are the enemy force's "
                 "own formations (not the friendly force's) — use the unit "
                 "designations from the OOB."
              )},
         ]},
        {"name": "associated_indicators",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Associated Indicators",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Indicators (from the upstream Event Matrix / Event Template) "
             "that signal the enemy (<force>) commander is approaching a "
             "decision point. For the red DST these are observable enemy-force "
             "preparatory actions (reserve repositioning, fires registration, "
             "recon surge) that tell the friendly (<force>) force the enemy is "
             "about to commit at a given enemy DP. Refer to the sides as "
             "'enemy (<force>)' and 'friendly (<force>)', resolving each "
             "parenthetical to the actual force name from the OOB."
         ),
         "item_subfields": [
             {"name": "indicator", "render_label": "Indicator",
              "provenance_required": True,
              "guidance": (
                 "Observable threat activity that signals an approaching "
                 "threat decision (e.g. 'Donovian armored reserve displaces "
                 "forward from assembly area', 'AT BDE emplacement on eastern "
                 "axis'). Same phrasing discipline as the Event Matrix "
                 "indicator column."
              )},
             {"name": "nai_id", "render_label": "NAI",
              "guidance": "NAI where the indicator is observed."},
             {"name": "threat_dp_id", "render_label": "Threat DP",
              "guidance": "Threat DP ID this indicator signals (cross-reference to threat_decision_points[].id)."},
         ]},
        {"name": "time_phase_markers",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Time-Phase Markers",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Time-phase lines / markers the red DST is keyed to. Aligns with "
             "the upstream Event Template's TPLs — the threat DPs are placed "
             "against the same time-phase framework as the friendly DST so "
             "the two decision cycles can be compared side by side."
         ),
         "item_subfields": [
             {"name": "label", "render_label": "Label",
              "guidance": "H-hour-relative label, e.g. 'H-24', 'H+0', 'H+6'."},
             {"name": "geometry", "render_label": "Geometry",
              "provenance_required": True,
              "guidance": "Phase-line geometry (MGRS line or GeoJSON)."},
             {"name": "associated_dps", "render_label": "Associated Threat DPs",
              "guidance": "Threat DP IDs keyed to this TPL (comma-separated)."},
         ]},
        # No map paragraph_field — this product is text/matrix only (see the
        # NO MAP note at the top of the SPEC).
    ],
    "subtleties": [
        "The red DST is the THREAT-commander mirror of the friendly DST: it templates where the ENEMY must decide, and what FRIENDLY action forces that decision — so the friendly staff can drive the threat's decision cycle.",
        "Decision-centric, NOT NAI-centric — NAIs are the trigger, the threat DP is the product. The NAIs here typically sit over the FRIENDLY scheme of maneuver (the threat is collecting against us).",
        "Decisions can be keyed to three trigger types: (a) phase lines, (b) events on the ground, (c) specific FRIENDLY actions. Each threat DP's trigger_event names which (trigger_NAI may be empty for a pure phase-line crossing).",
        "The threat DPs are doctrinally distinct from friendly DPs (event_template.py subtleties) — never mix the two. threat_decision_text is always an ENEMY commitment; if it reads like a friendly-commander order it is wrong.",
        "Text/matrix-only artifact — the threat-DP matrix (DP × trigger × threat-decision × options × effect-on-threat-COA) IS the product. There is no map slide; the threat-perspective graphic already lives on the SITEMP / Threat Overlay.",
        "Options per threat DP are typically 2-3 — the threat commander chooses between COA branches, so the option set must be manageable in his decision moment.",
        "effect_on_threat_COA is the friendly exploitation criterion — it's what makes the threat DP actionable for the friendly force (where to apply pressure to force / pre-empt the enemy decision).",
        "Every threat DP cites the trigger NAI / event from the upstream Threat COA Statement / SITEMP / Event Template threat-DP section in _provenance.",
    ],
    "hard_rules": [
        "Every threat DP MUST cite an upstream threat-COA decision point, NAI, or event in _provenance — threat DPs are not invented; they are derived from the Threat COA Statement branches/sequels + Event Template threat-DP set.",
        "threat_decision_text MUST be a THREAT (enemy) commander decision — NEVER a friendly-commander decision. A friendly order in this column is a hard validation failure (mirror of the blue DST's enemy-decision-in-friendly-column rule).",
        "Every threat DP's trigger_event MUST name one of the three: phase_line_crossing / ground_event / friendly_action (or use this verbatim phrasing in the trigger description) — and the trigger is FRIENDLY activity, not enemy.",
        "Every threat DP MUST have ≥ 2 options — a 'decision' with one option is not a decision.",
        "Every threat DP MUST have effect_on_threat_COA populated — without it the DP carries no exploitation criterion for the friendly force.",
        "associated_indicators rows MUST reference both an NAI ID and a threat DP ID present in the same artifact (cross-reference integrity).",
        "Time-phase markers MUST align with the upstream Event Template's TPLs (labels and geometries match) so the red and blue DSTs share one time framework.",
        "Every analytical claim cites source in _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Parent Threat COA Statement (threat COAs + branches/sequels decision logic): list_project_docs(filter={type:'Threat COA Statement'}) then get_project_doc(tag=<latest>)",
        "Per-COA SITEMPs (threat scheme of maneuver + NAI source): list_project_docs(filter={type:'SITEMP'})",
        "Upstream Event Template + Matrix (threat decision-point section): list_project_docs(filter={type:'Event Template'}) then get_project_doc(tag=<latest>)",
        "MCOO base terrain: list_project_docs(filter={type:'MCOO'})",
        "OPORD context (friendly COA — the activity that triggers threat decisions): get_project_doc(tag='OPORD')",
        "Phased concept of operations (PRIMARY — threat decision points anchored to phase windows): get_phases() — current phase + decisive point + phase objectives",
        "Operations overlay control measures (threat DPs anchored to NAIs/TAIs/EAs/OBJ/phase lines from the overlay): get_spatial_overlay()",
        # No render_map — this product emits no map slide.
    ],
    "post_emit_summary": "artifact_id, threat DP count, threat decision-asset coverage (reserve / fires / withdrawal), latest threat trigger time",
}
