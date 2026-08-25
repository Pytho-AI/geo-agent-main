"""HPTL — High-Payoff Target List — FM 3-60 paras 2-12 – 2-15 + App. D.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    TARGET_CATEGORY_ENUM,
    TARGET_CATEGORY_LABELS,
    TYPE_FIVE_O_ENUM,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "HPTL",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. FM 3-60 App. D
    # publishes the HPTL as a working-group ledger sorted by priority,
    # filtered by category, edited per FRAGO. DISABLE_XLSX=1 falls back
    # to legacy PPTX render. The singular `output_format` field was
    # removed — it disagreed with `output_formats` (singular still said
    # "pptx") and caused the deliverable resolver to 404 finalize on
    # the .xlsx that was actually written. The resolver now iterates
    # output_formats; legacy_formats appended last covers the
    # DISABLE_XLSX rollback path without re-introducing the
    # disagreement.
    "output_formats": ["xlsx"],
    "legacy_formats": ["pptx"],
    "shape": "row",
    "doctrine": {
        "purpose": (
            "Commander-approved prioritized list of HPTs by phase. Drives Detect "
            "collection priorities + AGM, indicates BDA needs. Drawn from HVTL via "
            "CARVER scoring with applied commander's targeting guidance + scheme of "
            "maneuver + TSS gating. Friendly-side payoff is the ordering criterion — "
            "distinct from CARVER's enemy-side value." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows ordered by priority (1 highest). Commander-approved priority is canonical; CARVER composite_total is one input but does NOT dictate priority.",
    },
    "order_by": {"field": "priority", "direction": "asc"},
    # HPTL pulls from the SAME cougaar OOB equipment universe HVTL
    # does — composition_rollup nomenclatures across the 179 unique
    # equipment types live cougaar carries. `list_targets`
    # (kg_targets_active) is the wrong source — cougaar IDXImageIir
    # placeholders aren't doctrinal targets. HVTL is enemy-side value
    # over those equipment types; HPTL is friendly-side payoff over
    # the same universe.
    "row_source": "entities:units:hostile",
    "row_id_selection_field": "selected_hpt_kg_ids",
    # Writer emits equipment NOMENCLATURE strings (not kg_ids); the
    # post-merge fan-out expands each to one row per bearer-unit
    # instance, identical to HVTL's expand_to_equipment pass.
    "expand_to_equipment": True,
    "group_by": "category",
    # Threat Model is the Pytho analytical OPFOR abstraction; the raw
    # DonovianDoctrine artifact is NOT in this list — same anti-bloat
    # rule HVTL applies (don't drag ~80K tokens of doctrine narrative
    # into every per-field call).
    "consumes_artifacts": [
        "HVTL", "CARVER", "Threat COA Statement", "SITEMP", "Threat Model",
    ],
    # Per-field upstream dep filter — applies to every HPTL field unless
    # the field overrides via its own data_source_filter. Mirrors HVTL
    # default_data_source_filter (lines 101-129). Empty list [] keeps the
    # dep edge for DAG ordering without bloating writer prompts.
    "default_data_source_filter": {
        "upstream:HVTL": ["rows", "header"],
        "upstream:CARVER": ["rows"],
        "upstream:Threat COA Statement": ["coas"],
        "upstream:SITEMP": [],
        "upstream:Threat Model": ["organizational_structure"],
        # cougaar.list_targets dropped — was returning generic
        # 'TARGET CIRCLE 1' placeholders from IIR Items, not real
        # targets. The cougaar OOB equipment-composition universe
        # (via cougaar.get_oob_red) is the canonical pool.
    },
    "published_section_title": "High-Payoff Targets",
    "header_fields": {
        # The {phase} macro does not substitute in the autodraft path, so
        # the doctrinal literal default is hardcoded — matches HVTL line
        # 136 fix. Analyst overrides at draft time if a different phase
        # is desired.
        "phase_or_critical_event": {"source": "session", "view": "header",
                                      "default": "Phase I (Penetration)",
                                      "required": True,
                                      "render_label": "Phase or Critical Event",
                                      "guidance": "Phase tag (e.g. '2') or critical event name. Every HPTL is phase-scoped."},
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "approving_commander": {"source": "session", "view": "header", "required": True,
                                  "default": "TBD — commander approval pending",
                                  "render_label": "Approving Commander",
                                  "guidance": (
                                    "Commander or staff principal who approved this HPTL. "
                                    "Pull from OPORD §3.d / FRAGO header. Leave default when "
                                    "running a draft before approval."
                                  )},
        # HVTL / CARVER upstream: doctrinal source but the HPTL can be drafted
        # in parallel (commander's targeting guidance is the canonical input).
        # Not required — reference when present.
        "hvtl_artifact_id":   {"source": "upstream:HVTL", "view": "internal", "required": False,
                                 "render_label": "HVTL Reference",
                                 "depends_on": ["upstream:HVTL"],
                                 "guidance": "Upstream HVTL artifact_id when available. Cite the latest per-phase HVTL."},
        "carver_artifact_id": {"source": "upstream:CARVER", "view": "internal", "required": False,
                                 "render_label": "CARVER Reference",
                                 "depends_on": ["upstream:CARVER"],
                                 "guidance": "Upstream CARVER artifact_id when available. CARVER composite_total feeds priority but does not dictate it."},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Writer's analytical HPT selection — list of kg_ids the commander
        # targeting guidance + scheme of maneuver elevate to HPT status.
        # The DAG runner uses this list as the row-iteration pool (see
        # row_id_selection_field above). Without it row_source would emit
        # one row per kg_targets_active entry (every active target in the
        # AO), which is doctrinally wrong: HPTL is the SELECTIVE list of
        # targets the commander intends to engage this phase. Mirrors HVTL
        # selected_hvt_kg_ids singleton wave (lines 167-213).
        "selected_hpt_kg_ids": {
            "source": "analytical", "view": "internal",
            "required": True, "provenance_required": True,
            # Same exact-nomenclature injection as HVTL — writer picks
            # verbatim from the cougaar OOB composition_rollup
            # enumeration; downstream fanout is an exact dict lookup.
            "inject_oob_nomenclatures": True,
            # Singleton — NOT in any batch_group. Must land BEFORE the
            # hpt_analytical row_field wave so row_ids are populated when
            # row_fields fire. Same wave-ordering pattern as HVTL.
            "render_label": "Selected HPT kg_ids",
            "depends_on": [
                "upstream:HVTL",
                "upstream:CARVER",
                "upstream:Threat COA Statement",
                "upstream:SITEMP",
                "upstream:Threat Model",
                "entities:units:hostile",
                "anchors",
                "map:state",
            ],
            "guidance": (
                "═════════════════════════════════════════════════════════\n"
                "OUTPUT: A JSON ARRAY OF EQUIPMENT NOMENCLATURE STRINGS.\n"
                "NOT UNITS. NOT KG_IDS. NOT FORMATIONS. EQUIPMENT.\n"
                "═════════════════════════════════════════════════════════\n\n"
                "AN HPT IS A PHYSICAL PIECE OF EQUIPMENT — a tank model, "
                "a launcher model, a radar model, a bridging vehicle. "
                "NOT a battalion. NOT a brigade. NOT a division. NOT a "
                "company. UNITS ARE NOT HPTS. THE EQUIPMENT THE UNIT "
                "CARRIES IS THE HPT.\n\n"
                "BANNED outputs (if you emit any of these, the artifact "
                "is doctrinally wrong and will be rejected):\n"
                "  ✗ \"60 MECH IFV DIV\"          ← unit, not equipment\n"
                "  ✗ \"364 FA BDE\"               ← unit, not equipment\n"
                "  ✗ \"6052 FA BN\"               ← unit, not equipment\n"
                "  ✗ \"676 SIG BDE\"              ← unit, not equipment\n"
                "  ✗ \"AA battery\"               ← role label, not equipment\n"
                "  ✗ \"FA brigade\"               ← formation, not equipment\n"
                "  ✗ ANY string containing \"BN\", \"BDE\", \"DIV\", \"BTRY\", "
                "\"DIVISION\", \"BRIGADE\", \"BATTALION\", \"COMPANY\", "
                "\"REGIMENT\", \"CO\", or an echelon suffix.\n"
                "  ✗ ANY string containing a kg-id / UUID character pattern.\n\n"
                "REQUIRED output shape — equipment NOMENCLATURES only:\n"
                "  ✓ \"BM-30 Smerch\"              ← MLRS launcher model\n"
                "  ✓ \"Pantsir-S1\"                ← AD system model\n"
                "  ✓ \"2S19 Msta\"                 ← SP howitzer model\n"
                "  ✓ \"T-90A\" / \"T-72B\"          ← tank model\n"
                "  ✓ \"BMP-3 IFV\"                 ← IFV model\n"
                "  ✓ \"Krasukha-4\"                ← EW system model\n"
                "  ✓ \"IL-220 counter-battery radar\"\n"
                "  ✓ \"PRP-4 recon vehicle\"\n"
                "  ✓ \"UR-77 mine-clearing\" / \"PMP pontoon\" / \"MT-55A bridge\"\n\n"
                "Think like the analyst at the targeting board: \"we "
                "need to take out the air-defense LAUNCHERS, the "
                "self-propelled HOWITZERS, the bridging VEHICLES, the "
                "counter-battery RADARS.\" Those are equipment models — "
                "what you list. The backend enumerates every instance "
                "of each model across every cougaar unit's "
                "composition_rollup automatically; you do NOT need to "
                "name the bearer unit or the count — the runner fills "
                "those mechanically.\n\n"
                "Lens framing: HVTL is the SAME universe ordered by "
                "enemy-side VALUE (CARVER). HPTL re-ranks the same "
                "universe by friendly-side PAYOFF — what WE intend to "
                "attack this phase, given commander's targeting "
                "guidance + scheme of maneuver + available delivery "
                "means. Same equipment pool; different lens; "
                "different ordering.\n\n"
                "═════════════════════════════════════════════════════════\n"
                "#1 RULE: PICK THE NODE WITH HIGHEST DOWNSTREAM-N.\n"
                "═════════════════════════════════════════════════════════\n"
                "The single most important selection question is:\n\n"
                "  'How many OTHER assets / formations / operations "
                "  does losing THIS ONE item neutralize?'\n\n"
                "Higher N = higher friendly payoff. The threat builds "
                "networks of dependencies — ONE single point of failure "
                "typically controls many downstream effectors. Find it. "
                "Pick it. Don't pick the 620 effectors it controls.\n\n"
                "Examples — DEPENDENCY N quantified:\n"
                "  ✓ ONE IL-220 counter-battery radar (N≈12 MLRS tubes "
                "    blinded — radar cues every fire mission across\n"
                "    the BDE).\n"
                "  ✓ ONE 1L271 / 1RL257 AD search radar (N≈8 SAM "
                "    launchers go to optical fallback; engagement\n"
                "    envelope collapses).\n"
                "  ✓ ONE Krasukha-4 EW van (N=division-wide GPS / SATCOM "
                "    coverage gap; comms degrade across formations).\n"
                "  ✓ ONE Class III / POL depot (N=620 tanks halt within\n"
                "    hours — entire maneuver brigade combat-ineffective\n"
                "    without fuel push).\n"
                "  ✓ ONE Class V / FARP / ammo dump (N=days of indirect-\n"
                "    fires capacity gone; rocket batteries fire-rate\n"
                "    collapses).\n"
                "  ✓ ONE MTLB 1V14 CP / division C3 van (N=whole division\n"
                "    loses fires synchronization; sub-units default to\n"
                "    last orders).\n"
                "  ✓ ONE MT-55A AVLB / PMP pontoon (N=entire crossing\n"
                "    fails; tanks at the LD accomplish nothing).\n\n"
                "ANTI-EXAMPLES — saturated effectors w/ LOW downstream-N:\n"
                "  ✗ Tank model with 620 instances (N≈0 — each tank's\n"
                "    loss is one tank).\n"
                "  ✗ IFV model with 400+ instances (N≈0).\n"
                "  ✗ Generic infantry weapons (N≈0).\n\n"
                "🚫 HARD CAP: any nomenclature whose total OOB instance "
                "count is > 200 is automatically DROPPED. Pick the "
                "ENABLING chokepoint upstream of those instances "
                "instead (fuel depot keeping them moving, fire-direction "
                "radar cueing them, C2 van coordinating them). Look at "
                "the OOB nomenclature enumeration counts BEFORE picking "
                "and drop the saturated end-effectors.\n\n"
                "Substitution rule: WHENEVER a saturated effector "
                "appears in the OOB nomenclature enumeration with "
                "instance count > 200, ASK yourself 'what single asset "
                "upstream ENABLES this saturated effector?' — fuel, "
                "ammo, fire-direction, C2, recon-cueing. THAT upstream "
                "asset is the HPT, not the saturated effector itself.\n\n"
                "Look for nodes whose REMOVAL would CASCADE — assets whose "
                "loss disables many other assets / units that are NOT "
                "themselves targeted:\n"
                "  ✓ FUEL — POL depots, MSR refuel sites, Class III "
                "    tankers. Lose these → maneuver brigade halts within "
                "    hours, no need to kill every tank.\n"
                "  ✓ C2 — formation CPs, signal HQ vans, divisional comms "
                "    nodes. Lose these → fires desync, formations lose "
                "    cohesion, sub-units default to last orders.\n"
                "  ✓ ENABLERS for breach / wet-gap — bridging vehicles, "
                "    mine-clearing line charges, engineer assault assets. "
                "    Lose these → entire crossing fails; tanks at the LD "
                "    accomplish nothing.\n"
                "  ✓ ISR / fire-direction — counter-battery radars, EW, "
                "    forward observers. Lose these → MLRS battery has no "
                "    targets, AD has no early warning.\n"
                "  ✓ CLASS V — ammo dumps, FARP, JAT prep sites. Lose "
                "    these → indirect fires + sortie generation collapse.\n"
                "  ✓ KEY LEADER + INTEGRATION — corps fire-coordination "
                "    cell, AD integration center. Lose these → the most-"
                "    networked enemy advantage degrades into 1980s-era "
                "    isolated systems.\n\n"
                "Bias HEAVILY toward the chokepoint over the saturated "
                "shooter. If the AO has 600 tanks but ONE fuel depot, the "
                "fuel depot belongs at PRIORITY 1, not the tank. The "
                "targeting board cannot play whack-a-mole against the "
                "saturated end-effector; the analyst's job is to find the "
                "single node whose loss propagates.\n\n"
                "ASK on each candidate: 'how many OTHER assets / units / "
                "operations does this enable?' Higher answer → higher HPT "
                "priority. The dramatic, photogenic shooter usually has "
                "a less-dramatic enabler upstream — pick the enabler.\n\n"
                "Doctrinal anchors per FM 3-60 App. C category (pick "
                "EQUIPMENT MODELS, not the unit that carries them):\n"
                "  - Fire Support → BM-30 / 9K58 Smerch, 2S19 Msta, "
                "PRIMA MRL, 2A45M towed AT.\n"
                "  - Air Defense → Pantsir-S1, 2S6 Tunguska, S-300, "
                "Crotale, SA-18/SA-19 launchers.\n"
                "  - EW / RISTA → Krasukha-4, IL-220 counter-battery "
                "radar, PRP-4 recon vehicle, BRM-3K, UAV systems.\n"
                "  - Engineer → UR-77 mine-clearing, TMM bridge, PMP "
                "pontoon, MT-55A bridging.\n"
                "  - C2 / Signal → MTLB 1V14 CP, BMP 1 KSH, division "
                "C3 vans, Ural-375D signal vans.\n"
                "  - Maneuver → T-90A tank, T-72B, BMP-3 IFV (the "
                "platform model, not the brigade that fields them).\n\n"
                "Each pick must be a substring distinctive enough that "
                "a case-insensitive contains-match against the cougaar "
                "composition_rollup keys (e.g. \"BMP 2 IFV\", \"PANTSIR "
                "S1\", \"BM 30 9K58 SMERCH\", \"T 90A\") hits the right "
                "items without colliding with unrelated equipment. Pick "
                "6-12 types. Specific > generic. ONLY EQUIPMENT MODELS.\n\n"
                "═════════════════════════════════════════════════════════\n"
                "ORDER BY FRIENDLY PAYOFF — HIGHEST PAYOFF FIRST.\n"
                "═════════════════════════════════════════════════════════\n"
                "The published HPTL priority IS the friendly-payoff "
                "ranking. Per FM 3-60 paras 2-12 — 2-15 + App. D the "
                "HPTL is commander-approved and ordered by the value "
                "to OUR operation of removing the target — not by the "
                "enemy's CARVER assessment (that's the HVTL).\n\n"
                "Phase-scoped: pull from upstream HVTL but RE-RANK per "
                "the commander's targeting guidance for THIS phase. "
                "The HVTL is enemy-value-ordered; HPTL is friendly-"
                "payoff-ordered against THIS COA.\n\n"
                "Capability + delivery mix matter: pick targets we have "
                "effective munitions / delivery for. Don't list a target "
                "the TSS would reject for TLE.\n\n"
                "Heuristic ordering when payoffs are close: integrated "
                "air defense usually outranks long-range fires (IAD has "
                "to fall first for everything else to be reachable); "
                "long-range fires usually outrank C2 (degrades enemy "
                "massed-effects ability); engineer breaching outranks "
                "tank-platform saturation in COAs that require wet-gap "
                "crossings; chokepoint enablers (fuel, ammo, comms) "
                "outrank saturated end-effectors (tanks, infantry). "
                "Pick the ordering that matches THIS COA's scheme of "
                "maneuver.\n\n"
                "Pick 6-12 entries for a corps-scale fight, never more "
                "than ~15. SELECTIVE list, not the whole HVTL. NSL-"
                "flagged equipment MUST be dropped here. NEVER list "
                "every cougaar nomenclature — HPTL is the commander's "
                "narrow targeting cut.\n\n"
                "Cite OPORD §3.d targeting guidance + FRAGOs in "
                "_provenance."
            ),
        },
    },
    "row_fields": {
        # Priority is derived from selected_hpt_kg_ids ORDER (the
        # commander-approved ordering is the list itself). DAG executor
        # resolves the row's index in selected_hpt_kg_ids + 1 = priority.
        # Eliminates the duplicate pri=1/pri=2 cluster bug from per-row
        # LLM authoring.
        "priority":      {"source": "analytical", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "PRI",
                            "batch_group": "hpt_analytical",
                            "depends_on": [
                                "selected_hpt_kg_ids", "upstream:CARVER",
                            ],
                            "guidance": (
                                "Integer rank derived from the row's position "
                                "in selected_hpt_kg_ids (index 0 -> priority 1). "
                                "Commander-approved per OPORD §3.d + FRAGO "
                                "updates is encoded in the selected_hpt_kg_ids "
                                "order. CARVER composite_total feeds the "
                                "selection but does not dictate priority — "
                                "friendly capability + scheme of maneuver are "
                                "equal inputs."
                            )},
        # Row IDs are equipment nomenclatures; the post-merge fan-out
        # in intel_agent._merge_pw_emit rewrites these placeholder
        # sources with the actual bearer-unit + count per equipment
        # instance (same mechanism HVTL uses). derive:placeholder
        # skips any LLM fallback so the writer doesn't hallucinate
        # unit names into these mechanical columns.
        "category":      {"source": "derive:placeholder", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "Category",
                            "enum": TARGET_CATEGORY_ENUM,
                            "enum_labels": TARGET_CATEGORY_LABELS},
        "id":            {"source": "entity:id", "view": "internal",
                            "required": True, "render_label": "ID"},
        "name":          {"source": "derive:placeholder", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "High-Payoff Target"},
        "bearer_unit":   {"source": "derive:placeholder", "view": "published",
                            "required": False, "provenance_required": True,
                            "render_label": "Bearer Unit"},
        "count":         {"source": "derive:placeholder", "view": "published",
                            "required": False, "provenance_required": True,
                            "render_label": "Operational Count"},
        "location_mgrs": {"source": "derive:placeholder", "view": "workpaper",
                            "required": False, "provenance_required": True,
                            "render_label": "Location (MGRS)"},
        "doi":           {"source": "derive:placeholder", "view": "workpaper",
                            "required": False, "provenance_required": True,
                            "render_label": "DOI"},
        "bda_required":  {"source": "analytical", "view": "published",
                            "required": False, "default": False,
                            "render_label": "BDA Required",
                            "batch_group": "hpt_analytical",
                            "depends_on": ["selected_hpt_kg_ids"],
                            "guidance": (
                                "True when commander wants BDA on this target. Drives "
                                "downstream BDA artifact production after engagement."
                            )},
        # Workpaper — supporting fields for TSS / AGM / ICSM (separate artifacts)
        "tle_requirement":   {"source": "analytical", "view": "workpaper",
                                "required": False, "provenance_required": True,
                                "render_label": "TLE Requirement",
                                "batch_group": "hpt_analytical",
                                "depends_on": ["selected_hpt_kg_ids"],
                                "guidance": (
                                    "Target Location Error tolerance per the "
                                    "planned delivery means for TSS gating. "
                                    "Derive from JWS / weapon-system pairing on "
                                    "this row; never substitute a hardcoded "
                                    "anchor when the planned delivery means is "
                                    "known. Cite the source in _provenance."
                                )},
        "dwell_time":        {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "batch_group": "hpt_analytical",
                                "depends_on": ["selected_hpt_kg_ids"],
                                "render_label": "Dwell Time",
                                "guidance": (
                                    "Expected time the target spends at one location "
                                    "(mobile systems). Drives Detect-to-Deliver timeline + "
                                    "TSS Report Age tolerance."
                                )},
        "bda_time_window":   {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "batch_group": "hpt_analytical",
                                "depends_on": ["selected_hpt_kg_ids"],
                                "render_label": "BDA Time Window",
                                "guidance": "Commander's BDA time window when bda_required is true (e.g. 'NLT 4h post-engagement')."},
        # Functional characterization is now an analytical copy from the
        # HVTL workpaper function_primary, not a ref: resolve (the ref:
        # path had no per-row resolution). Writer reads the upstream
        # HVTL row matching this kg_id and copies the function_primary
        # token verbatim.
        "functional_characterization": {"source": "analytical", "view": "workpaper",
                                          "required": False, "provenance_required": True,
                                          "render_label": "Functional Characterization",
                                          "batch_group": "hpt_analytical",
                                          "depends_on": [
                                              "selected_hpt_kg_ids",
                                              "upstream:HVTL",
                                          ],
                                          "guidance": (
                                              "Copy the upstream HVTL row's "
                                              "function_primary verbatim for "
                                              "this kg_id. Mechanical copy — "
                                              "do NOT re-author the role."
                                          )},
        # CARVER composite — promoted to published view (matches HVTL's
        # CARVER column). Friendly-payoff ordering uses commander intent
        # + scheme of maneuver as the canonical ranker, but the CARVER
        # total is the published quantitative anchor analysts read off
        # the row. Renamed render_label to 'CARVER' for parity with HVTL.
        "carver_score":   {"source": "analytical", "view": "published",
                              "required": False,
                              "render_label": "CARVER",
                              "batch_group": "hpt_analytical",
                              "depends_on": [
                                  "selected_hpt_kg_ids",
                                  "upstream:CARVER",
                              ],
                              "guidance": (
                                "Extract composite_total for this "
                                "row.id from upstream CARVER.rows[] "
                                "(range 6-30). Mechanical extract — "
                                "do NOT re-score the row. Leave "
                                "blank when CARVER hasn't run for "
                                "this id. Downstream HPTL render "
                                "shows this value alongside priority."
                              )},
        # Enemy reaction (published) — analyst-facing column mirroring
        # HVTL.enemy_reaction. The concrete actions the threat
        # commander is FORCED to take if THIS HPT is engaged / removed.
        # Friendly-side payoff framing: 'we strike this; threat reacts
        # by X, which opens / closes Y on our axis.'
        "enemy_reaction":   {"source": "analytical", "view": "published",
                                "required": True, "provenance_required": True,
                                "batch_group": "hpt_analytical",
                                "depends_on": ["selected_hpt_kg_ids"],
                                "render_label": "Enemy Reaction",
                                "guidance": (
                                    "ONE-TO-TWO SENTENCES naming the "
                                    "CONCRETE ACTIONS the threat "
                                    "commander would be FORCED to take "
                                    "after this HPT is engaged. Frame "
                                    "from the threat-commander POV "
                                    "(which units repositioned, which "
                                    "support requested, which sequels "
                                    "abandoned). Examples:\n"
                                    "  ✓ 'Pantsir-S1' → 'Pull S-300 "
                                    "    batteries forward to fill the "
                                    "    SHORAD gap; accept higher "
                                    "    UAV/CAS attrition.'\n"
                                    "  ✓ 'Bridging at Karksi' → "
                                    "    'Withdraw 6011 MECH IFV from "
                                    "    AA EAST; cancel sequel SE; "
                                    "    accept loss of initiative.'\n"
                                    "Cite OPORD / FRAGO / Threat COA "
                                    "Statement anchors in _provenance."
                                )},
        # Justification (published) — short analytical narrative on
        # WHY this target makes the HPTL at THIS priority. Mirrors
        # HVTL.justification but framed as friendly payoff rather
        # than enemy value.
        "justification":   {"source": "analytical", "view": "published",
                                "required": True, "provenance_required": True,
                                "batch_group": "hpt_analytical",
                                "depends_on": [
                                    "selected_hpt_kg_ids",
                                    "upstream:HVTL", "upstream:CARVER",
                                ],
                                "render_label": "Justification",
                                "guidance": (
                                    "ONE sentence: why this target "
                                    "earned its priority slot on the "
                                    "HPTL. Friendly-side payoff anchor: "
                                    "'engaging this HPT enables COA X / "
                                    "denies threat Y / accelerates "
                                    "decision point Z'. Cross-reference "
                                    "the upstream HVTL row's "
                                    "impact_of_loss + the CARVER "
                                    "composite_total when available. "
                                    "Cite OPORD §3.d targeting "
                                    "guidance + FRAGO in _provenance."
                                )},
    },
    "subtleties": [
        "HPTL ordering reflects FRIENDLY-side payoff, not enemy-side value. CARVER ranks enemy value; HPTL ranks friendly payoff.",
        "Category name OR number acceptable; use the canonical name (e.g. 'fire_support', not '02').",
        "Number of priorities should not be excessive — keep the list focused on what the commander actually intends to attack this phase.",
        "Organize target sets by capability/function with individual targets ordered by target value / sequence-of-appearance / commander criteria.",
        "NSL/RTL deconfliction: NSL entries CANNOT be on HPTL. When the upstream list_targets includes NSL-flagged entries, drop them at the row-derivation step.",
        "TSS / AGM / ICSM / TSM are SEPARATE artifacts. The workpaper fields (tle_requirement, dwell_time, bda_time_window) feed those products but do not belong in the published HPTL surface.",
        "TSTs and Component-Critical Targets are sub-classes of HPTs handled via dynamic targeting — they live on the HPTL with appropriate flags.",
        "Desired-effect column (suppress/neutralize/destroy) is part of the AGM, not the HPTL — keep it out of this product.",
        "Every priority + analytical claim cites source.",
    ],
    "hard_rules": [
        "Never invent ids — kg_targets_active is the candidate pool; the writer selects the subset via selected_hpt_kg_ids. NSL-flagged entries dropped at selection.",
        "Never include DEFEATED / DESTROYED entities (per most recent BDA).",
        "Never include NSL entries.",
        "Category must be from TARGET_CATEGORY_ENUM.",
        "KG-required row_fields (category, id, name, location_mgrs) MUST resolve from the KG entity — drop the row at derivation time if any KG-required field returns None. NEVER emit blank category for T-OTE001-style rows.",
        "Cite hvtl_artifact_id + carver_artifact_id in header when those upstream artifacts exist; leave blank only if the upstream truly hasn't been produced.",
        "Priority field is integer >=1, 1=highest, derived from selected_hpt_kg_ids index+1. Do not skip integers; do not duplicate; do not re-order at row-field time.",
        "Every priority + analytical claim cites source. Analytical row_fields declaring provenance_required:True (priority, tle_requirement, functional_characterization) MUST carry a _provenance entry — emission rejected without it.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Refined HVTL: list_project_docs(filter={type:'HVTL'}) then get_project_doc(tag=<latest>)",
        "CARVER scoring: list_project_docs(filter={type:'CARVER'}) then get_project_doc(tag=<latest>)",
        "Current targets in AO: list_targets()",
        "Threat structure (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Recent BDAs (DEFEATED exclusions): list_project_docs(filter={type:'BDA'}) plus get_recent_intel(types=['engagement','imagery'])",
        "Targeting guidance: get_project_doc(tag='OPORD') §3.d",
        "Latest FRAGO: list_project_docs(filter={type:'FRAGO'}) then get_project_doc(tag=<latest>)",
        "OOB context: get_project_doc(tag='OOB')",
        "Operations overlay control measures (operational context — axis / OBJ / EA / NAI / TAI proximity drives HPT priority placement): get_spatial_overlay()",
        "Phased concept of operations (HPTL prioritizes per phase commander's guidance per OPORD 3.d): get_phases() — current phase + decisive point + phase objectives",
        "NSL/RTL deconfliction (when available): list_project_docs(filter={type:'NSL'})",
    ],
    "post_emit_summary": "artifact_id, row count, top 3 categories by priority, FRAGO-driven changes",
}
