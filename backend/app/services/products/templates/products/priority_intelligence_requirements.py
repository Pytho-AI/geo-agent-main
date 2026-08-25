"""PIR — Priority Intelligence Requirements — ATP 2-01 + ATP 2-01.3 + FM 6-0.

Commander-approved subset of intelligence requirements that critically
support decision-making. Per ATP 2-01.3 paras 1-28, 1-44, 2-20–2-25,
PIRs come out of IPOE Step 4 + MDMP Step 2, get commander-approved
in OPORD §3.b.2 / Annex B, and evolve per FRAGO as phases shift.

PIR is the PARENT of the collection-planning chain:

  PIR  →  ICM (Information Collection Matrix — PIR × Indicator × NAI × …)
       →  Event-Matrix (NAI × indicator × time × DP cross-tab)
       →  DST-Matrix (decision points whose triggers ARE PIR-answered conditions)
       →  ICSM (collection synchronization across phases)
       →  SITREP Line 7 (current PIRs in priority order)
       →  IRE Para 2.a (running PIR estimate)

Standalone XLSX product per the EXCEL_DOCTRINAL_ALIGNMENT.md doctrine:
working-group ledger sorted by priority, filterable by phase, edited
per FRAGO. Each PIR is a row.

XLSX as canonical (no DOCX/PPTX legacy) because PIRs are inherently
spreadsheet-shaped — sort/filter on phase/status/priority is the
analyst's daily workflow.
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

PIR_STATUS_ENUM = ["open", "partial", "answered", "closed"]
PIR_STATUS_LABELS = {
    "open":     "Open",
    "partial":  "Partial",
    "answered": "Answered",
    "closed":   "Closed",
}

SPEC = {
    "name": "PIR",
    "output_format": "xlsx",
    "output_formats": ["xlsx"],
    "shape": "row",
    "doctrine": {
        "citation": "ATP 2-01 (Plan Requirements and Assess Collection) + ATP 2-01.3 paras 1-28, 1-44, 2-20–2-25 + FM 6-0 CCIR",
        "purpose": (
            "Commander-approved list of priority intelligence "
            "requirements driving collection asset tasking and the "
            "indicator/SIR/NAI/DP chain. Each PIR is a question whose "
            "answer feeds a commander decision. Status evolves across "
            "the operation as collection assets report against the "
            "indicators. The XLSX surface lets the working group sort "
            "by priority, filter by phase, mark answered, and reissue "
            "per FRAGO without losing the audit trail."
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows ordered by priority (1 highest) within each phase. group_by=phase produces a per-phase section banner.",
    },
    "order_by": {"field": "priority", "direction": "asc"},
    # PIRs are 1-per-DST-decision-point. Row IDs come from upstream DST's
    # decision_points[].id list (handled by intel_agent._derive_row_ids
    # under the "dst_dps" branch), naming each row "PIR-<DP-ID>" so the
    # writer per-column LLM call can mechanically map row_id → DP context.
    # Old "kg_pirs" source silently returned [] and the writer invented
    # uncoordinated row IDs per column, scrambling the rendered table.
    "row_source": "dst_dps",
    "group_by": "phase",
    "consumes_artifacts": [
        "Operational Environment Definition",
        "Threat COA Statement",
        "Event Template",
        # DST supplies the DP catalog every PIR is derived from.
        "Decision Support Template",
        # SITEMP supplies the NAI polygons each indicator lands in.
        "SITEMP",
    ],
    # PIR indicators must reference REAL bearer units + equipment from the
    # resolved RED OOB (§ 12). Including cougaar.get_oob in the per-field
    # depends_on (below) lets the writer cite specific unit kg_ids,
    # composition_rollup contents (e.g. "Pantsir-S1 battery"), and
    # attributed_positions (multi-position observations) when composing
    # observable indicators. Without this the writer falls back to generic
    # OPFOR doctrinal references which don't anchor to the live scenario.
    "default_data_source_filter": {
        # Each unit row carries name + sidc + echelon + composition_rollup +
        # composition_by_fm360_category + attributed_positions (multi-pos)
        # + rate_of_march_kmh. unidentified_formations are orphan
        # observations the writer should flag as collection gaps (these
        # become candidate PIRs that ask "what unit is at MGRS X carrying
        # capability Y?").
        # Decision Support Template carries the full DP catalog the writer
        # needs to derive each PIR from. coas[] indices through threat
        # COA branches keep the LTIOV alignment honest.
        "upstream:Decision Support Template": ["decision_points", "header"],
        # Event Template carries the NAI catalog the writer indicators
        # are observed against.
        "upstream:Event Template": ["named_areas_of_interest", "indicators_to_watch"],
        # SITEMP NAIs (per-COA) align indicators to specific COA branches.
        "upstream:SITEMP": ["named_areas_of_interest", "header"],
        # Threat COA Statement coas[] drive priority + indicator framing.
        "upstream:Threat COA Statement": ["coas"],
    },
    "published_section_title": "Priority Intelligence Requirements",
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "phase_or_critical_event": {"source": "session", "view": "header",
                                      "required": True,
                                      "default": "{phase}",
                                      "render_label": "Phase or Critical Event",
                                      "guidance": (
                                          "Scope of this PIR set. PIRs are phase-keyed; "
                                          "the same operation carries different PIRs across "
                                          "Phase II / Decisive / Stabilization etc."
                                      )},
        "approving_commander": {"source": "session", "view": "header", "required": True,
                                  "default": "TBD — commander approval pending",
                                  "render_label": "Approving Commander",
                                  "guidance": (
                                      "Commander or staff principal who approved this PIR set. "
                                      "Pull from OPORD §3.b.2 / Annex B header / FRAGO header."
                                  )},
        "opord_artifact_id": {"source": "upstream:OPORD", "view": "internal", "required": False,
                                "render_label": "OPORD Reference",
                                "guidance": "Source OPORD this PIR set was approved against."},
        "annex_l_artifact_id": {"source": "upstream:ANNEX_L_INTEL", "view": "internal", "required": False,
                                  "render_label": "Annex L Intel Reference",
                                  "guidance": "Annex L Intel companion when present (some commanders place PIRs there instead of §3.b.2)."},
        "prepared_by":        HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    # ROW DERIVATION CONTRACT
    # =======================
    # row_ids come from intel_agent._derive_row_ids("dst_dps") = one row
    # per DST decision_point, named PIR-<DP-ID> (e.g. PIR-DP-1, PIR-DP-2).
    # Every row_field per-column LLM call sees:
    #   1. The row_id list (PIR-DP-1, ..., PIR-DP-N)
    #   2. Upstream DST artifact in dependency payloads, containing
    #      decision_points[] with id / trigger_NAI / trigger_event /
    #      decision_text / location_mgrs / latest_time / assets_employed
    #      / effect_on_friendly_COA per DP
    #   3. Upstream SITEMP for NAI polygons
    #   4. Scenario fixture (NAI catalog, phase concept, OOB)
    # The writer mechanically maps PIR-DP-N → DST.decision_points where
    # id == "DP-N" and derives every column from that DP's context.
    "row_fields": {
        "pir_id":          {"source": "entity:id", "view": "published",
                              "required": True, "render_label": "PIR"},
        "priority":        {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Priority",
                              "depends_on": ["upstream:Decision Support Template", "upstream:Threat COA Statement"],
                              "guidance": (
                                  "Integer rank within the PHASE — 1 = highest. "
                                  "Derive from the matched Decision Support Template DP's impact: DPs that "
                                  "trigger on the main effort (AA1 / Valga / 1st ID) "
                                  "are priority 1; supporting attack DPs (AA2 / Rongu / "
                                  "1st AD) priority 2; screen DPs (AA3 / Osula / 1st CAV) "
                                  "priority 3. If multiple DPs share a phase, rank by "
                                  "Threat COA Statement branch criticality (defeat reserve > obstacle > "
                                  "ADA repositioning)."
                              )},
        # Runner-populated from DP catalog — phase is mechanically derivable
        # from the matched DP's catalog entry. Bypasses LLM to avoid the
        # writer keying by something other than PIR-DP-N (which created
        # phantom rows in v8).
        "phase":           {"source": "derive_from_dp_catalog:phase",
                              "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Phase",
                              "guidance": (
                                  "Runner-populated — copies dp_catalog[<dp>].phase verbatim "
                                  "(e.g. 'Phase I (Penetration)', 'Phase II (Advance to Contact)'). "
                                  "Drives the section banner via group_by."
                              )},
        "question":        {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "PIR Question",
                              "depends_on": ["upstream:Decision Support Template"],
                              "guidance": (
                                  "One question per FM 6-0 — begin with Will / Has / "
                                  "What / When / Where (never a noun phrase). The "
                                  "question must be the inverse of the matched Decision Support Template DP's "
                                  "trigger_event: if the DP triggers on 'X happens', "
                                  "the PIR asks 'Will X happen by LTIOV?'. Example: "
                                  "DP-3 trigger_event = '604 TANK BDE movement out of "
                                  "armored reserve position vic Kopu' → PIR question = "
                                  "'Has 604 TANK BDE displaced from its armored reserve "
                                  "position vic Kopu (35VME00686633) prior to D+3 0600Z?'. "
                                  "Use the EXACT unit IDs, MGRS, and DTGs from the matched "
                                  "DP — never paraphrase."
                              )},
        "justification":   {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Justification",
                              "depends_on": ["upstream:Decision Support Template"],
                              "guidance": (
                                  "ONE sentence naming the DP this PIR feeds. Format "
                                  "verbatim: 'Drives <DP-ID> decision on <decision_text "
                                  "from matched Decision Support Template DP>.' Example: 'Drives DP-3 decision "
                                  "on commit/hold 604 TANK BDE counter-attack along AA1.'"
                              )},
        # Runner-populated from DP catalog — copies dp_catalog[<dp>].ltiov.
        "ltiov":           {"source": "derive_from_dp_catalog:ltiov",
                              "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "LTIOV",
                              "guidance": (
                                  "Runner-populated — copies dp_catalog[<dp>].ltiov verbatim "
                                  "(e.g. 'H+24', 'D+3 0600Z', 'D+20'). After this DTG the "
                                  "decision window closes whether the PIR is answered or not."
                              )},
        # Runner-populated: dst_dps + row_id_strip_pir transposes the row_id
        # "PIR-DP-N" → "DP-N" verbatim. Bypasses the LLM because per-column
        # writer calls kept emitting {} as the value (LLMs are bad at this
        # narrow string-slice task and there's nothing to interpret).
        "linked_dp_ids":   {"source": "row_id_strip_pir", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Decision Points",
                              "guidance": (
                                  "The DP-N this PIR is derived from — runner-populated "
                                  "by stripping 'PIR-' from the row_id (e.g. PIR-DP-3 → "
                                  "DP-3). Always one DP per PIR row."
                              )},
        # Runner-populated from DP catalog — copies dp_catalog[<dp>].linked_nais.
        # Switched off the writer LLM because per-column emit kept keying
        # by NAI name (NAI-VALGA: "...") instead of row_id (PIR-DP-1: "..."),
        # creating phantom rows in the merge.
        "linked_nai_ids":  {"source": "derive_from_dp_catalog:linked_nais",
                              "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "NAIs",
                              "guidance": (
                                  "Runner-populated — copies dp_catalog[<dp>].linked_nais "
                                  "verbatim (comma-separated string like 'NAI-VALGA, "
                                  "NAI-PIKASILLA, NAI-ADA-FWD'). Each NAI ID must "
                                  "exist in the scenario fixture NAI catalog."
                              )},
        "indicators":      {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Indicators",
                              # Indicators must reference REAL units + equipment from
                              # the resolved RED OOB. cougaar.get_oob in depends_on
                              # gives the writer per-bearer composition_rollup +
                              # composition_by_fm360_category + attributed_positions
                              # so indicators say "Pantsir-S1 firing position at MGRS X"
                              # not "ADA system in the area".
                              "depends_on": [
                                  "upstream:Decision Support Template",
                                  "upstream:Event Template",
                                  "upstream:SITEMP",
                                  "entities:units",
                              ],
                              "guidance": (
                                  "Decompose the matched DST DP's trigger_event into "
                                  "2-4 observable, collectable indicators. Each "
                                  "indicator is a specific signature an asset can "
                                  "observe — thermal hit, radar emission, vehicle "
                                  "count, comms spike, equipment-type spotted at MGRS.\n\n"
                                  "Anchor every indicator to a REAL named bearer unit "
                                  "from cougaar.get_oob.red_units_by_category — use "
                                  "the unit's name verbatim (e.g. '604 TANK BDE', "
                                  "'6063 AD CO') and one of its organic equipment "
                                  "types from composition_rollup (e.g. 'T-90A thermal "
                                  "signature', 'Pantsir-S1 radar emission'). When the "
                                  "unit has attributed_positions[] (multi-position "
                                  "view), pick the position closest to the linked NAI "
                                  "and quote its MGRS.\n\n"
                                  "When an unidentified_formations[] cluster is near "
                                  "the linked NAI and carries an HVT-worthy capability, "
                                  "compose an indicator AND surface the collection_"
                                  "recommendation in the SIR (it becomes a "
                                  "discriminating PIR for the next intel cycle).\n\n"
                                  "Newline-separated. Example (for DP-3 / NAI-KOPU): "
                                  "'604 TANK BDE thermal signature departing "
                                  "35VME00686633 (organic T-90A x38 per cougaar OOB "
                                  "composition rollup)\\n60 MECH IFV DIV C2 net "
                                  "traffic spike >50% baseline\\nUnidentified BTG-class "
                                  "formation at (57.939, 26.412) — request HUMINT to "
                                  "confirm 604 TANK BDE forward element'."
                              )},
        "sirs":            {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "SIRs",
                              "depends_on": [
                                  "upstream:Decision Support Template",
                                  "upstream:Event Template",
                                  "entities:units",
                              ],
                              "guidance": (
                                  "Specific Information Requirements — one SIR per "
                                  "indicator per INT discipline. Format: "
                                  "'<INT>: <specific tasking>'.\n\n"
                                  "Each SIR must name the SPECIFIC equipment type "
                                  "(from composition_rollup) + MGRS (from "
                                  "primary_position or attributed_positions) the "
                                  "collection asset is tasked against. Generic "
                                  "'<unit> activity' SIRs are not collectable.\n\n"
                                  "Example: 'IMINT: thermal at 35VME00686633 "
                                  "confirming 604 TANK BDE T-90A departure | SIGINT: "
                                  "60 MECH IFV DIV command-net (Pantsir-S1 fire-"
                                  "control radar emissions identified per cougaar "
                                  "composition_rollup) | HUMINT: civilian reports of "
                                  "armor movement on Route Kopu | IMINT/MASINT: "
                                  "patrol Krasukha-like signature at MGRS Y (target "
                                  "cluster from cougaar unidentified_formations[])'. "
                                  "Pipe-separated. Each indicator usually spawns 2-3 "
                                  "SIRs across multiple INTs."
                              )},
        "collection_assets": {"source": "analytical", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Assets Tasked",
                                "guidance": (
                                    "Match SIR INT to available ISR. Canonical "
                                    "asset names from the scenario fixture: RQ-7B "
                                    "Shadow (IMINT/EO), MQ-9 (IMINT/EO/SIGINT, "
                                    "national), DOGEARTA (SIGINT/COMINT), Rivet "
                                    "Joint (ELINT), JSTARS (GMTI), national SIGINT, "
                                    "HUMINT collection plan 26-04. Comma-separated."
                                )},
        "report_to":       {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Report To",
                              "guidance": (
                                  "G-2 1ID + the principal owning the DP. Format: "
                                  "'G-2 1ID + <DP owner>' where DP owner is the "
                                  "commander of the unit named in the matched DST "
                                  "DP's assets_employed (e.g. 'CDR 1st ID' for AA1 "
                                  "DPs, 'CDR 1st AD' for AA2, 'CDR 1st CAV' for AA3)."
                              )},
        "status":          {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "render_label": "Status",
                              "enum": PIR_STATUS_ENUM,
                              "enum_labels": PIR_STATUS_LABELS,
                              "guidance": (
                                  "Default 'open' for autodrafts (no indicators yet "
                                  "observed). Flips to 'partial' once any indicator "
                                  "lands in recent intel, 'answered' once the question "
                                  "is confirmed/denied, 'closed' past LTIOV."
                              )},
        "last_observed_dtg": {"source": "analytical", "view": "workpaper",
                                "required": False, "provenance_required": True,
                                "render_label": "Last Observed DTG",
                                "guidance": (
                                    "DTG of the most recent indicator observation "
                                    "from recent intel. Empty for autodrafts."
                                )},
        "summary_of_findings": {"source": "analytical", "view": "workpaper",
                                  "required": False, "provenance_required": True,
                                  "render_label": "Findings Summary",
                                  "guidance": (
                                      "Running narrative of indicator hits. Empty for "
                                      "autodrafts (no intel observed yet against the "
                                      "PIR); analyst fills in as collection reports."
                                  )},
    },
    "subtleties": [
        "PIRs are QUESTIONS, not topics. FM 6-0: 'What' / 'Where' / 'When' / 'Will' framing — never a noun phrase.",
        "PIRs are PHASE-KEYED. Same operation carries different PIRs across phases; the group_by=phase section banner reflects this.",
        "Priority is rank WITHIN a phase, not across phases. Each phase resets to priority=1.",
        "Indicators ≠ SIRs. Indicators are observable PHENOMENA (qualitative); SIRs are the COLLECTION TASKING (specific information bits). One indicator usually spawns 2-5 SIRs across multiple INTs.",
        "Each PIR should feed exactly ONE decision point (DP). If a PIR feeds multiple DPs, that's usually a sign it's too broad and should be split.",
        "LTIOV is calendar-anchored, not relative. After LTIOV the PIR auto-closes whether answered or not.",
        "PIR evolution: PIRs change per FRAGO. Don't delete answered/closed PIRs — mark status and keep the row for audit.",
        "Doctrinal next: ICM (collection cross-tab), Event-Matrix (NAI × time × DP), DST-Matrix (DPs whose triggers are PIR answers).",
    ],
    "hard_rules": [
        "PIRs MUST be stated as questions (begin with 'What' / 'Will' / 'Where' / 'When' / 'Has' / etc.).",
        "Every PIR cites the approving commander + the OPORD/FRAGO source in _provenance.",
        "linked_nai_ids must exist in the operations overlay's NAI set — never invent NAI IDs.",
        "linked_dp_ids must exist in DST-Matrix when DST-Matrix is present — never invent DP IDs.",
        "Priority is unique within a (phase) group.",
        "status field is from PIR_STATUS_ENUM (open / partial / answered / closed).",
        "LTIOV is a valid DTG (DDHHMMZmonYY).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Commander's approved PIR set: get_project_doc(tag='OPORD') §3.b.2 + Annex B; "
        "list_project_docs(filter={type:'FRAGO'}) for phase updates.",
        "Annex L Intel companion (when present): get_project_doc(tag='ANNEX_L_INTEL').",
        "Phase boundaries + DP windows: get_phases() — drives LTIOV alignment + phase grouping.",
        "Operations overlay (NAI / TAI / DP placement): get_spatial_overlay().",
        "Threat COA branches (what could happen to invalidate / answer the PIR): list_project_docs(filter={type:'Threat COA Statement'}).",
        "Event Template (NAI × indicator × time matrix — overlap with PIR indicators): list_project_docs(filter={type:'Event Template'}).",
        "Recent intel against indicators (status evolution + last_observed_dtg): get_recent_intel(types=['TACTICAL','SIGINT','IMINT','HUMINT']).",
    ],
    "post_emit_summary": "artifact_id, PIR count, per-phase distribution, status distribution (open / partial / answered / closed), unanswered count past LTIOV",
}
