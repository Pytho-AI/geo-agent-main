"""HVTL — High-Value Target List — FM 3-60 App. C.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    TARGET_CATEGORY_ENUM,
    TARGET_CATEGORY_LABELS,
    WARFIGHTING_FUNCTION_FOR_CATEGORY,
    WARFIGHTING_FUNCTION_LABELS,
    WARFIGHTING_FUNCTION_ORDER,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "HVTL",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. FM 3-60 App. C
    # Fig C-1 is a 3-col table grouped by category; multiple HVTLs coexist
    # per phase × COA. DISABLE_XLSX=1 falls back to legacy PPTX. The
    # singular `output_format` field was removed — it disagreed with
    # `output_formats` (singular still said "pptx") and caused the
    # deliverable resolver to look for an HVTL.pptx file that never
    # exists, returning None and 404'ing the finalize handler even
    # though the .xlsx was present with all 60 markers. The resolver
    # now iterates output_formats; legacy_formats appended last covers
    # the DISABLE_XLSX rollback path without re-introducing the
    # disagreement.
    "output_formats": ["xlsx"],
    "legacy_formats": ["pptx"],
    "shape": "row",
    "doctrine": {
        "citation": "ATP 2-01.3 Figure 6-9 (Step 4 refined HVTL)",
        "purpose": (
            "Per-phase, per-COA list of threat assets the enemy commander requires for "
            "successful completion of the mission. Intel-staff product (IPOE Step 4). "
            "Per ATP 2-01.3 Figure 6-9 the published HVTL is two columns: "
            "warfighting-function group (Command and Control / Movement and Maneuver / "
            "Fires / Protection / Intelligence / Sustainment) with each row's HVTs "
            "listed as a bulleted set under that function. No Justification column "
            "is rendered to the analyst; the per-target analytical workpaper "
            "(function / critical elements / signatures / impact of loss / "
            "justification) feeds the writer's reasoning and downstream CARVER + "
            "HPTL rationales but stays out of the published artifact." + PROVENANCE_DIRECTIVE +
            " Per ATP 2-01.3 §5-70 and DonovianDoctrine §6, the HVT pool is enemy UNITS"
            " (corps/division/brigade and corps-level enablers from the OOB) — not point"
            " targets. Facility-class HVTs (forward C2 facilities, ammunition transfer"
            " points, key bridges) enter via a future enhancement; this schema's row_source"
            " is units only."
        ),
        "ordering_rule": "Rows grouped by warfighting function in the doctrinal order: C2, Movement & Maneuver, Fires, Protection, Intelligence, Sustainment. HVTL itself is NOT priority-ordered; CARVER ranks the HVTs afterwards.",
    },
    "row_source": "entities:units:hostile",
    # Per per-coa-product-scope.md §11.1a + §11.4: HVTs are equipment items,
    # sub-units, facilities, or HVIs — not whole brigades. The writer picks
    # BEARER UNITS via selected_hvt_kg_ids (limits the LLM prompt to ~6-12
    # candidates instead of 15,651 IDXEquipment vertices), then intel_agent
    # ._build_skeleton fans each picked unit's HVT-worthy composition_rollup
    # entries into individual equipment rows. Each row carries the
    # equipment nomenclature, organic count, FM 3-60 category, bearer unit
    # designation, and primary-position MGRS. The unit-level analytical
    # text (justification, function_primary, impact_of_loss, etc.) is
    # inherited from the parent unit row — correct doctrinally per
    # FM 3-60 ¶B-32 (TVA reasons over the unit's expected actions; the
    # row IS the equipment piece that carries that capability).
    "expand_to_equipment": True,
    # No group_by — HVTL is a single flat ranked list per the user's
    # directive ("STOP GROUPING BY CATEGORY THAT SHOULD GET ITS OWN
    # COLUMN"). Category surfaces as a published row_field instead.
    # Rows sort by priority (1 = highest, writer-assigned via the
    # selected_hvt_kg_ids list order) per the user's directive ("HVTL
    # MUST BE SORTED BY PRIORITY — THAT IS THE ENTIRE POINT OF AN
    # HVTL"). order_by drives the xlsx_exporter's row-sort pass.
    "order_by": {"field": "priority", "direction": "asc"},
    # Writer-controlled row-id selection. The row_source ("kg_red_oob_active")
    # is the FULL pool of candidate units (every RED brigade / battalion in
    # the OOB); HVTL must NOT emit a row per pool entry. Instead the writer
    # picks the subset of kg_ids the doctrine + Threat COA actually elevates
    # to HVT status, lists them in this header field, and the DAG runner
    # iterates row_fields over THAT list. Doctrinal HVTL row count is small
    # (~6-12 for a corps-scale fight); 214-row dumps of the entire OOB are
    # the bug this knob fixes.
    "row_id_selection_field": "selected_hvt_kg_ids",
    # Analyst-configurable knobs surfaced via a 'gear' affordance next
    # to the Generate button on the dashboard. Frontend renders one
    # control per entry; submit threads `config_json` through the
    # /api/products/generate query string; backend applies via the
    # equipment_doctrine.HVT_WORTHY_CATEGORIES override pathway.
    "config_fields": {
        "hvt_worthy_categories": {
            "type": "multi_select",
            "render_label": "HVT-worthy categories",
            "options": [
                {"value": "AirDefense",   "label": "Air Defense"},
                {"value": "FireSupport",  "label": "Fire Support"},
                {"value": "EW_REC",       "label": "EW / Recon"},
                {"value": "C2_Signal",    "label": "C2 / Signal"},
                {"value": "Engineer",     "label": "Engineer"},
                {"value": "RISTA_UAV",    "label": "RISTA / UAV"},
                {"value": "Lift",         "label": "Lift / Aviation"},
                {"value": "Radar",        "label": "Radar"},
                {"value": "Maneuver",     "label": "Maneuver"},
                {"value": "Sustainment",  "label": "Sustainment"},
                {"value": "POL",          "label": "POL"},
                {"value": "Transport",    "label": "Transport"},
            ],
            "default": [
                "AirDefense", "FireSupport", "EW_REC", "C2_Signal",
                "Engineer", "RISTA_UAV", "Lift", "Radar", "Maneuver",
                "Sustainment", "POL", "Transport",
            ],
        },
    },
    # Tier 2 IPOE inputs + BIIR (HUMINT biographic dossier — when a named
    # individual qualifies as an HVT, BIIR carries the identity dossier).
    # Upstream analytical products HVTL reads. DonovianDoctrine (the raw
    # OPFOR-doctrine reference artifact) is NOT in this list — pulling it
    # into the writer prompt drags ~80K tokens of reference narrative the
    # writer doesn't need. Threat Model is Pytho's distilled OPFOR
    # analytical summary (doctrinal template + organizational_structure +
    # roles) — that's the right HVT-relevant abstraction. The doctrinal
    # CITATIONS still appear in comments / guidance text (ATP 2-01.3
    # §5-70, FM 3-60 App. C, TC 7-100 OPFOR pattern) but those are
    # citations for the analyst, not artifact-dep payload for the LLM.
    "consumes_artifacts": ["SITEMP", "Threat Overlay", "Threat COA Statement", "Threat Model"],
    # Per-field upstream dep filter — applies to EVERY HVTL field unless
    # the field overrides its own data_source_filter. Without this every
    # row_field's prompt drags the FULL Threat Model + Threat COA Statement
    # + Threat Overlay artifacts (~80K+ tokens combined), saturating the
    # vllm_gate budget on a SINGLE batched call. The writer doesn't need
    # those artifact's full bodies — it needs the analytical-relevant
    # subsections only. Mirrors situation_template.py's
    # default_data_source_filter pattern (line ~230).
    #
    # Keys here are what gets KEPT from each dep payload (everything else
    # is dropped before the writer sees it). Per-field data_source_filter
    # still wins per the merge rule in dag_executor._apply_field_filters.
    "default_data_source_filter": {
        # Threat Model: organizational_structure carries the unit roster
        # (id + echelon + role + parent_id + primary_systems). threat_overview
        # is the narrative summary of OPFOR pattern. doctrinal_template_map
        # is a map render (irrelevant to HVT selection text). Provenance +
        # header are renderer scaffolding the writer doesn't read.
        "upstream:Threat Model": ["threat_overview"],
        # Threat COA Statement: HVT selection is per-COA, so the writer
        # needs every COA's scheme_of_maneuver / fires / intent block.
        # Header + provenance + map_overlays are renderer scaffolding.
        "upstream:Threat COA Statement": ["coas"],
        # Threat Overlay: HVTL doesn't paint geometry; the COA's templated
        # unit positions are nice-to-have for context but the bulk (288
        # rows × full provenance) is noise relative to the selection
        # analytical task. Drop the artifact entirely from the prompt —
        # the dep-edge stays so the DAG ordering is preserved (HVTL
        # waits for Threat Overlay to land) but the payload doesn't
        # bloat HVTL's prompt.
        "upstream:Threat Overlay": [],
        # SITEMP: same as Threat Overlay — dep edge for ordering, no
        # payload. HVTL doesn't consume SITEMP content; the schema
        # declares it for the row_count footnote at render time, not
        # for writer-prompt input.
        "upstream:SITEMP": [],
        # cougaar.get_oob: every HVTL field needs the named-unit list (writer
        # picks HVTs by composition; downstream batched analytical fields
        # need per-unit context to reason about function / impact /
        # signatures). unidentified_formations and fusion_stats are
        # selection-specific surface area — they belong on
        # selected_hvt_kg_ids's per-field filter (see §11.1a + §12 of
        # per-coa-product-scope.md re: orphan-cluster PIR candidates),
        # NOT on the batched analytical wave or justification (those
        # have nothing to do with the orphan-stub fusion residue).
        # Keeping the default narrow → ~10k saved per batched call.
        # HVTL is RED-only by doctrine, so every field's cougaar dep is
        # routed through "entities:units:hostile" (the kg_red_oob_active
        # row_source + the explicit selected_hvt_kg_ids depends_on entry).
    },
    "published_section_title": "High-Value Targets",
    "header_fields": {
        # Phase defaults to Phase I (Penetration) when session/runner does not
        # supply it — HVTL is per-phase and the artifact must never publish
        # with an empty phase header. If the analyst needs a different phase
        # they override; otherwise the doctrinal default phase is filled.
        "phase":              {**HEADER_PHASE, "default": "Phase I (Penetration)"},
        "threat_coa":         {"source": "analytical", "view": "header", "required": True,
                                 "provenance_required": True,
                                 "render_label": "Threat COA",
                                 "depends_on": ["upstream:SITEMP", "upstream:Threat COA Statement"],
                                 "guidance": (
                                     "Per-phase enemy COA the HVTL is scoped to — HVTs are "
                                     "COA-specific. Pull from OE context or upstream Threat COA Statement "
                                     "artifact; cite SITEMP and/or Threat COA Statement artifact_id in "
                                     "_provenance."
                                 )},
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "sitemp_artifact_id": {"source": "upstream:SITEMP", "view": "internal", "required": False,
                                 "depends_on": ["upstream:SITEMP"],
                                 "render_label": "SITEMP Reference"},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay", "view": "internal", "required": False,
                                          "depends_on": ["upstream:Threat Overlay"],
                                          "render_label": "Threat Overlay Reference"},
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal", "required": False,
                                 "depends_on": ["upstream:Threat COA Statement"],
                                 "render_label": "Threat COA Statement Reference"},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Writer's analytical HVT selection — list of EQUIPMENT NOMENCLATURE
        # STRINGS (not kg_ids), the way a human analyst thinks: "we need to
        # take out the AA batteries first, then the FA brigades carrying
        # BM-30, then the bridging companies". The writer picks ~6-12
        # distinctive equipment nomenclatures the threat COA depends on;
        # the runner mechanically enumerates every instance from
        # cougaar.get_oob_red.units[*].composition_rollup (one row per
        # bearer-unit instance of each picked type). Per
        # scratch/docs/ibl/per-coa-product-scope.md §11.1a + FM 3-60
        # ¶B-31: HVTs are equipment / sub-units / facilities / HVIs.
        "selected_hvt_kg_ids": {
            "source": "analytical", "view": "internal",
            "required": True, "provenance_required": True,
            "max_tokens": 4096,
            # Inject the live cougaar OOB nomenclature enumeration into
            # this field's prompt so the writer picks VERBATIM strings.
            # Eliminates the hyphen-vs-space / writer-renaming class of
            # match failures (T-90A ≠ T 90A ATGM substring). Downstream
            # expand_to_equipment becomes an exact dict lookup.
            "inject_oob_nomenclatures": True,
            # Per-field narrow filter — overrides the schema-level default.
            # The selection prompt needs cougaar.get_oob.units (the candidate
            # pool the writer picks from), Threat COA Statement.coas (which
            # COA the HVTL is scoped to), and Threat Model.threat_overview
            # (doctrinal pattern). Drop unidentified_formations + fusion_stats
            # (selection picks from named units, not orphan clusters or
            # metadata) — saves ~5-10k tokens per call without losing any
            # selection-relevant context.
            "data_source_filter": {
                # Selection-specific surfaces: include the orphan-cluster
                # pool (per §11.1a "ALSO consider unidentified_formations[]")
                # and the fusion metadata for confidence signaling.
                "upstream:Threat COA Statement": ["coas"],
                "upstream:Threat Model": ["threat_overview"],
            },
            # Singleton — must NOT share a batch_group with the analytical
            # row_fields. Two reasons: (a) co-firing in the same batch
            # would let the row_fields run BEFORE the selection result is
            # available, so row_ids would be empty and the per-row prompt
            # constraint would silently fall back to "every OOB id" (the
            # exact bug this field exists to fix); (b) batch_group unions
            # every member's depends_on into one giant prompt — selection
            # needs OOB + doctrine + COA only (~50K tokens), whereas the
            # row_fields drag in the full SITEMP + Threat Overlay
            # payloads pushing the prompt past the 131K-token vllm gate
            # budget and saturating the queue. Keeping this field as its
            # own singleton wave lets it complete first with a smaller
            # prompt; the post-wave row_id_selection_field harvest then
            # populates row_ids before the row_field batch wave runs.
            "render_label": "Selected HVT equipment types",
            "depends_on": [
                "upstream:Threat Model",
                "upstream:Threat COA Statement",
                "upstream:Threat Overlay",
                # RED-only OOB — writer reads composition_rollup keys to
                # discover what equipment is present in the AO. Doctrinally
                # HVTs are enemy assets only, so BLUE has no place here.
                "entities:units:hostile",
            ],
            "guidance": (
                "═════════════════════════════════════════════════════════\n"
                "OUTPUT: A JSON ARRAY OF EQUIPMENT NOMENCLATURE STRINGS.\n"
                "NOT UNITS. NOT KG_IDS. NOT FORMATIONS. EQUIPMENT.\n"
                "═════════════════════════════════════════════════════════\n\n"
                "AN HVT IS A PHYSICAL PIECE OF EQUIPMENT — a tank model, "
                "a launcher model, a radar model, a bridging vehicle. "
                "NOT a battalion. NOT a brigade. NOT a division. NOT a "
                "company. UNITS ARE NOT HVTS. THE EQUIPMENT THE UNIT "
                "CARRIES IS THE HVT.\n\n"
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
                "═════════════════════════════════════════════════════════\n"
                "#1 RULE: PICK THE NODE WITH HIGHEST DOWNSTREAM-N.\n"
                "═════════════════════════════════════════════════════════\n"
                "The single most important selection question is:\n\n"
                "  'How many OTHER assets / formations / operations "
                "  does losing THIS ONE item neutralize?'\n\n"
                "Higher N = higher priority. The threat builds networks "
                "of dependencies — ONE single point of failure typically "
                "controls many downstream effectors. Find it. Pick it. "
                "Don't pick the 620 effectors it controls.\n\n"
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
                "Substitution rule: WHENEVER a saturated effector\n"
                "appears in the OOB nomenclature enumeration with\n"
                "instance count > 200, ASK yourself 'what single asset\n"
                "upstream ENABLES this saturated effector?' — fuel,\n"
                "ammo, fire-direction, C2, recon-cueing. THAT upstream\n"
                "asset is the HVT, not the saturated effector itself.\n\n"
                "═════════════════════════════════════════════════════════\n"
                "Selection rule: an HVT-type is an equipment model "
                "whose loss across the threat formation would force "
                "the threat to substitute, branch, sequel, or accept "
                "degradation against the named Threat COA. Pick "
                "distinctive nomenclatures the cougaar OOB "
                "composition_rollup actually carries.\n\n"
                "═════════════════════════════════════════════════════════\n"
                "THINK SECOND-ORDER: weakest LINK, not biggest STACK.\n"
                "═════════════════════════════════════════════════════════\n"
                "🚫 HARD CAP: any nomenclature whose total OOB instance "
                "count is > 200 is automatically DROPPED. A T-90A tank "
                "with 600+ instances is NOT an HVT — it's an engagement "
                "footprint we cannot saturate against; pick the "
                "ENABLING chokepoint upstream of those instances (fuel "
                "depot keeping them moving, fire-direction radar "
                "cueing them, C2 van coordinating them). Look at the "
                "cougaar OOB composition_rollup counts BEFORE picking "
                "and drop the saturated end-effectors.\n\n"
                "Examples — saturated shooters BANNED, replace with "
                "upstream enabler:\n"
                "  ✗ 'T 90A ATGM' (count 620)        → ✓ ammo dump / Class V FARP\n"
                "  ✗ 'BMP 2 IFV' (count 400+)        → ✓ POL depot moving fuel\n"
                "  ✗ generic infantry weapons         → ✓ MTLB CP coordinating fires\n"
                "  ✗ 'TRK CGO 2T TO 5T' (saturated)   → ✓ Class III tanker push\n\n"
                "When a single equipment type appears in the OOB with "
                "an instance count > 200, the doctrinal targeting move "
                "is NOT to attack each instance — it's to attack the "
                "system enabling them.\n\n"
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
                "operations does this enable?' Higher answer → higher HVT "
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
                "ORDER BY CARVER — HIGHEST TOTAL FIRST.\n"
                "═════════════════════════════════════════════════════════\n"
                "The published HVTL priority IS the CARVER ranking: rank "
                "your selected equipment types by their CARVER total "
                "(highest score = priority 1). Per FM 3-60 App. C / "
                "JP 3-60 the CARVER framework is the doctrinal HVT "
                "prioritization tool — six dimensions (Criticality, "
                "Accessibility, Recoverability, Vulnerability, Effect, "
                "Recognizability) scored 1-5 each; total 6-30. Mentally "
                "pre-score each candidate as you list it; the actual "
                "per-row CARVER object lands in the carver_score row "
                "field downstream and the runner re-ranks priority "
                "from those totals. Tiebreak on Criticality.\n\n"
                "Heuristic ordering when CARVER totals are close: "
                "integrated air defense usually outranks long-range "
                "fires (IAD has to fall first for everything else to "
                "be reachable); long-range fires usually outrank C2 "
                "(degrades enemy massed-effects ability); engineer "
                "breaching outranks tank-platform saturation in COAs "
                "that require wet-gap crossings; chokepoint enablers "
                "(fuel, ammo, comms) outrank saturated end-effectors "
                "(tanks, infantry). Pick the ordering that matches "
                "THIS COA's scheme of maneuver."
            ),
        },
    },
    "row_fields": {
        # Per ATP 2-01.3 Figure 6-9, the published HVTL is two columns: the
        # warfighting-function group label and the HVT name. Everything else
        # is workpaper-internal — used for grouping, reasoning, or
        # provenance, but NEVER rendered to the analyst.
        "id":            {"source": "entity:id", "view": "internal",
                            "required": True, "provenance_required": True,
                            "render_label": "ID"},
        # After expand_to_equipment, `name` carries the equipment nomenclature
        # (e.g. "T 90A", "BM-30 9K58 Smerch", "Pantsir-S1") — written by the
        # equipment-fanout pass in _merge_pw_emit. derive:placeholder skips
        # the LLM fallback (kg:name would otherwise dispatch a row_field LLM
        # call when by_id misses, and the writer would hallucinate unit
        # names into this column).
        # Priority — the 1..N rank the writer assigned by ordering its
        # selected_hvt_kg_ids list (1 = highest, the equipment whose loss
        # most disrupts the named threat_coa). Stamped per row by the
        # post-merge fan-out pass in _merge_pw_emit.
        "priority":      {"source": "derive:placeholder", "view": "published",
                            "required": False, "provenance_required": True,
                            "render_label": "Priority"},
        # CARVER analysis — the doctrinal HVT-prioritization framework
        # per FM 3-60 App. C / JP 3-60. Six dimensions scored 1-5:
        #   C riticality      — importance to enemy operation
        #   A ccessibility    — how reachable by friendly fires/maneuver
        #   R ecoverability   — how fast enemy reconstitutes
        #   V ulnerability    — susceptibility to attack
        #   E ffect           — downstream operational impact
        #   R ecognizability  — ease of identification by sensor / observer
        # Total = sum (6-30). The published HVTL priority IS the CARVER
        # ranking — selected_hvt_kg_ids ordering = highest-CARVER first.
        # Writer emits the breakdown + total + one-line rationale; the
        # render shows the total prominently with the breakdown
        # available on hover / in the workpaper view.
        "carver_score":   {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "batch_group": "hvt_analytical",
                              "depends_on": ["selected_hvt_kg_ids"],
                              "render_label": "CARVER",
                              "guidance": (
                                "ROW IDS ARE EQUIPMENT NOMENCLATURES "
                                "(\"T-90A\", \"BM-30 Smerch\", ...). Emit "
                                "your JSON object KEYED BY THOSE TYPE "
                                "STRINGS. ONE entry per equipment type.\n\n"
                                "PER-ROW VALUE: a JSON object with the SIX "
                                "doctrinal CARVER subscores (1-5 each) + the "
                                "total + a one-line rationale. Shape:\n"
                                "  {\"C\": 5, \"A\": 3, \"R\": 5, \"V\": 4, "
                                "\"E\": 5, \"R\": 4, \"total\": 26, "
                                "\"rationale\": \"...\"}\n\n"
                                "Doctrinal anchors (FM 3-60 App. C / "
                                "JP 3-60):\n"
                                "  - Criticality (1-5): how essential is "
                                "    this equipment to the enemy's COA? "
                                "    5 = single-point-of-failure for the "
                                "    named threat_coa.\n"
                                "  - Accessibility (1-5): can friendly "
                                "    fires / maneuver reach the bearer "
                                "    unit's position? 5 = within "
                                "    organic-fires envelope today.\n"
                                "  - Recoverability (1-5): how fast can "
                                "    the threat replace / reconstitute "
                                "    this asset? 5 = irreplaceable in the "
                                "    operational window.\n"
                                "  - Vulnerability (1-5): how susceptible "
                                "    is this equipment to the friendly "
                                "    weapon mix on hand? 5 = soft-target "
                                "    against PGM / fires available.\n"
                                "  - Effect (1-5): cascade impact if "
                                "    destroyed. 5 = removes a whole "
                                "    capability set across the threat "
                                "    formation.\n"
                                "  - Recognizability (1-5): how easily "
                                "    can a sensor / observer confirm "
                                "    identity for engagement? 5 = "
                                "    distinctive signature (e.g. dome-"
                                "    mounted Pantsir radar).\n\n"
                                "Sum the six into `total` (6-30). "
                                "Rationale: ONE short sentence naming "
                                "the dominant 1-2 dimensions driving the "
                                "score. Cite FM 3-60 / JP 3-60 / OPORD "
                                "anchors in _provenance.\n\n"
                                "The HVTL priority ranking IS the CARVER "
                                "ordering: highest total = priority 1. "
                                "When CARVER totals tie, use Criticality "
                                "as tiebreaker. The runner re-ranks "
                                "priority post-merge based on the totals "
                                "you emit here, so put effort into the "
                                "score — it directly drives the published "
                                "HVTL ordering and the downstream CARVER "
                                "/ HPTL artifacts."
                              )},
        "name":          {"source": "derive:placeholder", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "High-Value Target"},
        # Bearer unit — the parent unit the equipment is organic to.
        # Source: kg:name. Pre-expansion this resolves to the picked
        # unit's name (kg-mechanical, no LLM call); the expand_to_equipment
        # pass in _build_skeleton overwrites with the actual bearer unit
        # designation per equipment row. Using kg:* (vs analytical) is
        # what keeps this from queueing a wasteful ~100k-token LLM call
        # for a mechanically-resolvable field.
        "bearer_unit":   {"source": "derive:placeholder", "view": "published",
                            "required": False, "provenance_required": True,
                            "render_label": "Bearer Unit"},
        # Operational count — number of items of this equipment type the
        # bearer unit organic-carries. Source derive:placeholder returns ""
        # pre-expansion (no LLM call); the expansion pass writes the real
        # composition_rollup count per equipment row. Identical reasoning
        # as bearer_unit.
        "count":         {"source": "derive:placeholder", "view": "published",
                            "required": False, "provenance_required": True,
                            "render_label": "Operational Count"},
        # Category drives the warfighting-function grouping but is not its
        # own column — the group_by render emits a section header per
        # category value with the HVT names bulleted underneath.
        # Source: _t1_unit's category column, which projects the unit's `class`
        # enum through CLASS_TO_CATEGORY (intel_agent.py:1350) into
        # TARGET_CATEGORY_ENUM. The published HVTL collapses category →
        # warfighting function at render time via group_collapse_map (unchanged).
        "category":      {"source": "derive:placeholder", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "Category",
                            "enum": TARGET_CATEGORY_ENUM,
                            "enum_labels": TARGET_CATEGORY_LABELS},
        # Per scratch/docs/ibl/per-coa-product-scope.md §4 + §11.1a: an HVT
        # is "a person, place, or thing that performs a function for the
        # threat" (FM 3-60 ¶B-31). The doctrinally-correct HVTL has rows
        # at the equipment item granularity (BM-30 MLRS battery, Pantsir
        # battery, etc.) — see §11.4 for the union-pool row_source plan
        # (kg_hvt_pool_union across IDXEquipment + IDXRedUnit + facility +
        # HVI sources). Until that union pool lands, each unit row exposes
        # its organic composition_rollup + FM 3-60 category breakdown so
        # the analyst can see WHAT each HVT-elevated unit actually carries.
        # Both source from the resolved-OOB primitive (see scope-doc §12)
        # via cougaar.get_oob units[].composition_rollup /
        # composition_by_fm360_category — these survive the
        # _OOB_UNIT_KEEP_KEYS slim pass and are kg-sourced (no writer
        # hallucination). The xlsx_exporter `render: "compact_dict"` hint
        # turns the dict into a top-by-count "K: V / K: V / ..." line so
        # the heaviest assets surface first.
        # Key visual indicator — short prose describing the most
        # doctrinally-distinguishing piece of equipment the unit carries,
        # in OBSERVATION terms (what a sensor / collector / analyst would
        # SEE that confirms this is the named HVT). Drives recognition
        # for the collection cycle: a Pantsir battery is "tracked AD
        # vehicles with 12 tubes and dome-mounted radar"; a BM-30 Smerch
        # battery is "heavy 12-tube MLRS on URAL-4320 truck"; an IL-220
        # counter-battery radar is "trailer-mounted phased-array dish".
        # Writer reads composition_rollup + composition_by_fm360_category
        # from the dep payload and picks the heaviest doctrinally-
        # significant system, then describes its visual signature.
        "key_indicator": {"source": "analytical", "view": "published",
                            "required": True, "provenance_required": True,
                            "batch_group": "hvt_analytical",
                            "depends_on": ["selected_hvt_kg_ids"],
                            "render_label": "Key Visual Indicator",
                            "guidance": (
                                "ROW IDS IN THIS BATCH ARE EQUIPMENT NOMENCLATURE "
                                "STRINGS (e.g. \"T-90A\", \"Pantsir-S1\", \"BM-30 "
                                "Smerch\"). Emit your JSON object KEYED BY THOSE "
                                "TYPE STRINGS — one entry per type. NEVER key by "
                                "a unit name or a UUID.\n\n"
                                "═══════════════════════════════════════════════\n"
                                "POV: OVERHEAD — UAV / SATELLITE / IMAGERY ANALYST.\n"
                                "═══════════════════════════════════════════════\n"
                                "ONE short phrase (≤ 25 words) per equipment "
                                "TYPE describing what the equipment LOOKS LIKE "
                                "FROM ABOVE — top-down, plan view, the way a "
                                "UAV-feed or satellite image renders it. NOT "
                                "ground-level descriptions. NOT side profile. "
                                "Imagine the analyst staring at a freshly-pulled "
                                "MSI tile and trying to ID the row.\n\n"
                                "Describe the SHAPE the chassis projects, the "
                                "tube / launcher / dish layout visible from "
                                "directly overhead, the shadow signature when "
                                "deployed, the dispersal pattern (single-vehicle "
                                "vs cluster), and any distinctive "
                                "orientation cues (rotated radar dish, raised "
                                "launchers, opened-tarp cargo bed).\n\n"
                                "Examples (key → value), all OVERHEAD POV:\n"
                                "  \"Pantsir-S1\" → 'tracked vehicle silhouette "
                                "with rectangular launch-tube cluster amidships; "
                                "rotating radar dish casts circular shadow when "
                                "deployed'\n"
                                "  \"BM-30 Smerch\" → '12 launch tubes arranged "
                                "in a tight 3×4 rectangle on a heavy 8-wheel "
                                "chassis; tubes elevated for firing produce a "
                                "characteristic forward shadow'\n"
                                "  \"IL-220 counter-battery radar\" → 'trailer-"
                                "mounted with large rotating dish/antenna array "
                                "fully visible from overhead; deployed "
                                "stabilizers form a four-point footprint'\n"
                                "  \"2S19 Msta\" → 'tracked SP howitzer hull with "
                                "long gun barrel extending forward of the turret; "
                                "barrel orientation visible in plan view'\n"
                                "  \"Krasukha-4\" → 'wheeled trailer/truck with "
                                "deployed parabolic dish casting a wide oval "
                                "shadow; cab + cargo-bed two-segment shape'\n"
                                "  \"T-90A\" → 'tracked MBT hull, low turret "
                                "rotated relative to hull, smooth-bore barrel "
                                "extending forward; rectangular ERA tiles "
                                "visible on hull edges'\n"
                                "  \"BMP-2 IFV\" → 'tracked IFV hull, small "
                                "turret offset to right, short autocannon "
                                "barrel; troop hatch lines visible on top'\n"
                                "  \"PMP pontoon bridge\" → 'segmented "
                                "rectangular floating sections strung "
                                "perpendicular to a watercourse; matching "
                                "transporter trucks staged on the near bank'"
                            )},
        # Equipment-rollup + capability-mix columns are obsolete after
        # expand_to_equipment — each row IS one piece of equipment now,
        # not a unit whose rollup needs surfacing. _build_skeleton drops
        # these keys from each row at expansion time, so they would only
        # ever render an empty cell. Keep declarations OUT of the schema
        # to avoid empty xlsx columns.
        # Justification surfaces on the published HVTL — it is the
        # analyst's distilled "why this is an HVT" for the named
        # threat_coa, the column most reviewers look at after the
        # target name. ATP 2-01.3 §5-70 names it as the HVT-identification
        # analysis; doctrine treats it as the deliverable's reasoning
        # column, not workpaper-only.
        "justification": {"source": "analytical", "view": "published",
                            "required": True, "provenance_required": True,
                            "render_label": "Justification",
                            "depends_on": ["function_primary", "function_secondary",
                                            "impact_of_loss", "critical_elements",
                                            "detection_signatures"],
                            # Per-field narrow filter: justification distills
                            # the workpaper fields the prior batch wave just
                            # wrote (function_primary, function_secondary,
                            # impact_of_loss, critical_elements,
                            # detection_signatures) into one sentence about
                            # WHY this is an HVT for the named COA. It needs
                            # the COA context (coas) but does NOT need
                            # cougaar at all — by this wave the analytical
                            # row data is already in the prompt as
                            # depends_on field values. Drops cougaar
                            # entirely, drops Threat Model entirely. The
                            # ~75k saved off this wave is the biggest single
                            # win in the chain.
                            "data_source_filter": {
                                # justification is a row_field; its cougaar dep
                                # arrives under "entities:units:hostile" (routed
                                # via HVTL's row_source = kg_red_oob_active per
                                # dag_parser.py:90). Drop entirely — by wave 3
                                # the analytical row fields are already in the
                                # prompt as depends_on.
                                "upstream:Threat COA Statement": ["coas"],
                                "upstream:Threat Model": [],
                                "upstream:Threat Overlay": [],
                                "upstream:SITEMP": [],
                            },
                            "guidance": (
                                "ROW IDS IN THIS WAVE ARE EQUIPMENT NOMENCLATURE "
                                "STRINGS (\"T-90A\", \"Pantsir-S1\", \"BM-30 Smerch\", "
                                "...) — emit your JSON object KEYED BY THOSE "
                                "EQUIPMENT TYPE STRINGS. One justification per "
                                "type the writer picked. NEVER key by a unit "
                                "name or a UUID — the HVTL row IS the equipment "
                                "type, not the unit that carries it.\n\n"
                                "Per-row value: ONE short sentence — why losing "
                                "THIS EQUIPMENT TYPE is critical to the enemy's "
                                "mission for the named threat_coa. Distill from "
                                "the workpaper function + impact_of_loss fields "
                                "the prior batch wave just emitted for the same "
                                "key. Cite FRAGO / OPORD / imagery / OOB basis "
                                "in _provenance. Downstream CARVER and HPTL "
                                "read this for their published rationales."
                            )},
        # HVI flag / ID / MGRS / DOI are analyst-internal — they inform
        # downstream products (CARVER, HPTL) and the Justification reasoning
        # but do not surface on the published HVTL per FM 3-60 App C.
        "hvi_flag":      {"source": "analytical", "view": "workpaper",
                            "required": False, "default": False,
                            "batch_group": "hvt_analytical",
                            "depends_on": ["selected_hvt_kg_ids"],
                            "render_label": "HVI",
                            "guidance": (
                                "ROW IDS IN THIS BATCH ARE EQUIPMENT NOMENCLATURE "
                                "STRINGS (\"T-90A\", \"Pantsir-S1\", ...) — emit "
                                "your JSON object keyed by those strings. For "
                                "every equipment type return `false` — equipment "
                                "is never a high-value individual. HVI flagging "
                                "only fires when the writer extends HVTL to "
                                "named-individual rows (not used in the current "
                                "equipment-type model)."
                            )},
        "hvi_identifier": {"source": "analytical", "view": "workpaper",
                              "required": False, "default": "N/A",
                              "batch_group": "hvt_analytical",
                              "depends_on": ["selected_hvt_kg_ids"],
                              "render_label": "HVI ID",
                              "guidance": (
                                "ROW IDS ARE EQUIPMENT NOMENCLATURES. For "
                                "every row emit 'N/A' — equipment HVTs have no "
                                "individual identifier."
                              )},
        "location_mgrs": {"source": "derive:placeholder", "view": "workpaper",
                            "required": False, "provenance_required": True,
                            "render_label": "Location (MGRS)"},
        "doi":           {"source": "derive:placeholder", "view": "workpaper",
                            "required": False, "provenance_required": True,
                            "render_label": "DOI"},
        # Workpaper — analyst's HVT identification analysis.
        # All 6 analytical workpaper row_fields share the same upstream
        # dep set (DonovianDoctrine + Threat COA + OOB + Threat Model)
        # and have no inter-field dependencies, so they all batch into
        # ONE LLM call via `batch_group: "hvt_analytical"`. Without
        # batching the DAG fires 6 serial calls each re-dumping the
        # ~25K-token dep payload — the bottleneck the user flagged at
        # ~1 LLM call/min. Justification (below) stays its own call
        # because it depends_on these six and must run AFTER.
        "function_primary": {"source": "analytical", "view": "workpaper",
                              "required": False, "provenance_required": True,
                              "batch_group": "hvt_analytical",
                              "depends_on": ["selected_hvt_kg_ids"],
                              "render_label": "Function (Primary)",
                              "guidance": (
                                "ROW IDS IN THIS BATCH ARE EQUIPMENT NOMENCLATURE "
                                "STRINGS (\"T-90A\", \"Pantsir-S1\", \"BM-30 Smerch\", "
                                "...) — emit your JSON object KEYED BY THOSE "
                                "TYPE STRINGS. One entry per type the writer "
                                "picked in selected_hvt_kg_ids. NEVER key by a "
                                "unit name (e.g. \"364 FA BDE\") or a UUID — "
                                "you'll get every cougaar unit you saw in the "
                                "dep payload and that's wrong, the row IS the "
                                "equipment.\n\n"
                                "Per-row value: what this EQUIPMENT TYPE does "
                                "for the enemy in the named threat_coa — one "
                                "short verb-phrase, e.g.:\n"
                                "  \"Pantsir-S1\" → 'integrated air defense for "
                                "the Tartu-Pikasilla corridor'\n"
                                "  \"BM-30 Smerch\" → 'long-range area "
                                "neutralization fires on friendly assembly areas'\n"
                                "  \"T-90A\" → 'armored counter-attack force from "
                                "depth against penetrations'"
                              )},
        "function_secondary": {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "batch_group": "hvt_analytical",
                                "depends_on": ["selected_hvt_kg_ids"],
                                "render_label": "Function (Secondary)",
                                "guidance": (
                                  "ROW IDS ARE EQUIPMENT NOMENCLATURES (\"T-90A\", "
                                  "\"Pantsir-S1\", ...). Emit keyed by those. "
                                  "Optional second-order role for this equipment "
                                  "type (e.g. EW relay, logistics node, breakthrough "
                                  "force component)."
                                )},
        "impact_of_loss": {"source": "analytical", "view": "workpaper",
                            "required": False, "provenance_required": True,
                            "batch_group": "hvt_analytical",
                            "depends_on": ["selected_hvt_kg_ids"],
                            "render_label": "Impact of Loss",
                            "guidance": (
                                "ROW IDS ARE EQUIPMENT NOMENCLATURES. Emit "
                                "keyed by the writer's equipment-type strings. "
                                "How the enemy reacts to losing this EQUIPMENT "
                                "TYPE — pick one per type: SUBSTITUTE (similar "
                                "asset redirected), BRANCH (alternate plan), "
                                "SEQUEL (follow-on ops constrained), or ACCEPT "
                                "(degradation tolerated)."
                            )},
        # Enemy reaction (published) — the explicit ACTIONS the enemy
        # commander would be FORCED to take if this HVT type was
        # removed. Distinct from impact_of_loss (which classifies the
        # enemy's CHOICE: substitute / branch / sequel / accept);
        # enemy_reaction names the concrete operational decisions.
        # Drives the targeting board's "so what" — analyst sees the
        # forced enemy moves alongside the HVT, not just a category.
        "enemy_reaction": {"source": "analytical", "view": "published",
                              "required": True, "provenance_required": True,
                              "batch_group": "hvt_analytical",
                              "depends_on": ["selected_hvt_kg_ids"],
                              "render_label": "Enemy Reaction",
                              "guidance": (
                                "ROW IDS ARE EQUIPMENT NOMENCLATURES. Emit "
                                "keyed by the writer's equipment-type strings. "
                                "ONE per type.\n\n"
                                "PER-ROW VALUE: 1–2 sentences naming the "
                                "CONCRETE ACTIONS the threat commander would "
                                "be FORCED to take after losing this HVT type. "
                                "Not what the loss means abstractly — what the "
                                "commander would do tomorrow morning.\n\n"
                                "Examples (style + specificity to match):\n"
                                "  ✓ 'Pantsir-S1' → 'Pull S-300 batteries "
                                "    forward to fill the SHORAD gap; restrict "
                                "    deep maneuver under the resulting "
                                "    coverage gap window; accept higher "
                                "    UAV/CAS attrition until reinforcement.'\n"
                                "  ✓ 'BM-30 Smerch' → 'Shift counter-battery "
                                "    plan to 2S19 Msta tubes (range −40km); "
                                "    re-cue Krasukha EW for area suppression; "
                                "    re-task Mi-28N for deep precision.'\n"
                                "  ✓ 'Fuel depot at GROZNYI' → 'Withdraw 6011 "
                                "    MECH IFV BN to AA EAST to ration "
                                "    organic fuel; suspend 364 FA BDE "
                                "    displacement; request Echelon-Above-Corps "
                                "    Class III push within 12h or lose "
                                "    initiative.'\n\n"
                                "Frame each action in the threat commander's "
                                "POV: which UNITS he repositions, which "
                                "SUPPORT he requests, which OBJECTIVES he "
                                "delays, which SCHEMES he abandons. Reference "
                                "real cougaar bearer units + AGM-style "
                                "delivery means where appropriate. Cite "
                                "doctrine in _provenance."
                              )},
        "interdependencies": {"source": "analytical", "view": "workpaper",
                               "required": False, "provenance_required": True,
                               "batch_group": "hvt_analytical",
                               "depends_on": ["selected_hvt_kg_ids"],
                               "render_label": "Interdependencies",
                               "guidance": (
                                "ROW IDS ARE EQUIPMENT NOMENCLATURES. Emit "
                                "keyed by type. Per-row value: other HVT TYPES "
                                "this equipment depends on or that depend on "
                                "it — reference by nomenclature (e.g. "
                                "\"Pantsir-S1\" depends on \"IL-220 counter-"
                                "battery radar\" for cueing)."
                               )},
        "critical_elements": {"source": "analytical", "view": "workpaper",
                               "required": False, "provenance_required": True,
                               "batch_group": "hvt_analytical",
                               "depends_on": ["selected_hvt_kg_ids"],
                               "render_label": "Critical Elements",
                               "guidance": (
                                "ROW IDS ARE EQUIPMENT NOMENCLATURES. Emit "
                                "keyed by type. Sub-components whose "
                                "neutralization defeats THIS EQUIPMENT TYPE — "
                                "feeds CARVER Criticality scoring downstream. "
                                "E.g. \"Pantsir-S1\" → 'fire-control radar dish, "
                                "missile rack, vehicle engine'; \"BM-30 Smerch\" "
                                "→ 'launch tubes, fire-control panel, transporter "
                                "engine'."
                               )},
        "detection_signatures": {"source": "analytical", "view": "workpaper",
                                   "required": False, "provenance_required": True,
                                   "batch_group": "hvt_analytical",
                                   "depends_on": ["selected_hvt_kg_ids"],
                                   "render_label": "Detection Signatures",
                                   "guidance": (
                                    "ROW IDS ARE EQUIPMENT NOMENCLATURES. Emit "
                                    "keyed by type. Multi-INT signatures THIS "
                                    "EQUIPMENT TYPE emits when active. Cover "
                                    "at least two of: SIGINT (emitter band + "
                                    "activity pattern), GEOINT (visible / IR / "
                                    "SAR signature — what does it look like?), "
                                    "HUMINT (informant / source access). Feeds "
                                    "CARVER Recognizability."
                                   )},
    },
    "subtleties": [
        "HVT vs HPT: HVT is valued to the enemy; HPT is valued to friendly COA success. Every HPT is drawn from HVTL via CARVER (flow: HVTL → CARVER → HPTL).",
        "HVTL is NOT priority-ordered — rows are grouped by category. CARVER ranks afterwards; HPTL applies friendly-side payoff priority.",
        "Same HVT can appear in multiple HVTLs (one per phase × COA). Re-derive each phase; do not carry forward stale rows.",
        "DEFEATED exclusion (per most recent BDA): exclude DESTROYED / DEFEATED entities.",
        "Workpaper fields (function / critical_elements / impact_of_loss / detection_signatures) feed the Justification cell AND downstream CARVER rationales. Published HVTL surfaces only the lean 3-col view (Category | HVT | Justification).",
        "HVI rows (hvi_flag=True) optionally carry the detailed HVI sheet — useful for named-individual HVTs but not for equipment.",
        "Every published field needs source citation in _provenance.",
        # HVT selection is ANALYTICAL — derive from doctrine + OOB + threat
        # COA, never from a hardcoded list. The writer reads
        # DonovianDoctrine (TC 7-100 OPFOR doctrine), the current Threat COA
        # Statement, the OOB (force structure), and the Threat Model, then
        # identifies the threat assets the enemy commander requires for
        # COA success. Hardcoded "must include unit X" enumeration in this
        # schema is a doctrinal violation — it pre-empts the analyst's
        # function/critical-elements/impact-of-loss reasoning that ATP
        # 2-01.3 §5-70 requires.
        "HVT selection is analytical, not enumerated. The writer derives "
        "the HVT list per phase × COA from: the Threat Model artifact "
        "(Pytho's distilled OPFOR analytical summary — doctrinal "
        "template + organizational_structure + asset roles), the current "
        "Threat COA Statement (which threat assets that COA's success "
        "actually depends on), and the OOB (force structure present in "
        "the AO). HVTs are the intersection of doctrine-driven asset "
        "criticality and COA-specific dependence — re-derive every "
        "phase, never carry forward a static list. The schema does NOT "
        "pull in the raw DonovianDoctrine reference document; Threat "
        "Model is the right doctrinal abstraction for HVT analysis. "
        "Naming specific units (e.g. brigade designators) in this schema "
        "would short-circuit the analytical derivation; the writer must "
        "produce the list from the artifact deps."],
    "hard_rules": [
        "Never invent ids — kg-sourced.",
        "Never re-derive programmatic fields (category, type, location, doi).",
        "Never include rows for DEFEATED / DESTROYED entities (per most recent BDA).",
        "Never order rows by priority — HVTL is grouped by category, not ranked. Priority ranking is CARVER's job.",
        "Category enum is TARGET_CATEGORY_ENUM — do not invent categories.",
        "HVT selection derives analytically from Threat Model (Pytho's distilled OPFOR analytical summary), Threat COA Statement (COA-specific asset dependencies), and OOB (force structure in the AO). Never enumerate specific units in this schema — the writer reads the artifact deps and produces the list.",
        "Echelon filter is doctrinal, not enumerated: the HVT candidate pool is RED units at corps, division, and brigade echelon (plus corps-level enablers per the Threat Model's organizational_structure). The writer reads echelon from the OOB row's `echelon` field and excludes BN/CO/PLT rows unless the Threat Model + Threat COA Statement specifically justify a sub-brigade echelon (e.g. an MRL battalion that is the sole long-range fires asset on a phase's main effort axis). Never enumerate which units those are in this schema — the OOB is the source of truth.",
        "Every analytical claim has _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Force structure (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Threat doctrine (REQUIRED — drives HVT selection per centralized-C2 + IFC + integrated-air-defense pattern): get_project_doc(tag='DonovianDoctrine')",
        "RED force structure (the HVT candidate pool — corps/division/brigade and supporting separates): get_oob(force_type='RED')",
        "Recent activity (BDA-driven exclusions): get_recent_intel(window_hours=72, types=['engagement','imagery'])",
        "Targeting guidance / PIR context: get_project_doc(tag='OPORD') §3.d, §4",
        "Latest FRAGO: list_project_docs(filter={type:'FRAGO'}) then get_project_doc(tag=<latest>)",
        "Prior threat artifacts (Threat Overlay, SITEMP, Threat COA Statement): list_project_docs + get_project_doc",
        "Operations overlay control measures (operational context — axis / OBJ / EA / NAI / TAI proximity to HVT candidates): get_spatial_overlay()",
        "Phased concept of operations (HVT priority shifts by phase per commander's guidance): get_phases() — current phase + decisive point + phase objectives",
        "Prior HVTL (regen): list_project_docs(filter={type:'HVTL'}) then get_project_doc(tag=<latest>)"],
    "post_emit_summary": "artifact_id, row count, top categories, any DEFEATED-driven exclusion",
}
