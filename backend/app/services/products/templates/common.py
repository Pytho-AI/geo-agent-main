"""Canonical enums and shared header-field bedrock for IBL product schemas.

Most enums trace to a specific doctrinal section (FM 3-60 App. C target categories,
ATP 2-01.3 OAKOC factors, JP 3-60 PDA damage categories, FM 6-99 line precedence,
etc.). The HEADER_* dicts are the bedrock the runner pre-fills from session context.
Per-product schemas live in `templates/products/` and import what they need from here.
"""

# ============================================================================
# CANONICAL ENUMS (referenced from per-field `enum` constraints)
# ============================================================================

# FM 3-60 App. C target categories
TARGET_CATEGORY_ENUM = [
    "command_and_control", "fire_support", "maneuver",
    "air_defense_artillery", "engineer", "reconnaissance_and_surveillance",
    "cyberspace_electromagnetic_activities", "information",
    "chemical_biological_radiological_nuclear", "sustainment",
    "lift", "line_of_communication",
]

# ATP 2-01.3 Fig 6-9 groups the published HVTL by warfighting function
# (ADP 3-0): Command and Control / Movement and Maneuver / Intelligence /
# Fires / Sustainment / Protection. The TARGET_CATEGORY_ENUM values
# (FM 3-60 App. C) collapse into those six buckets per FM 3-60 §C-1 cross-
# walk; we apply the mapping at HVTL render time so the published table
# matches Fig 6-9 row labels exactly.
WARFIGHTING_FUNCTION_FOR_CATEGORY = {
    "command_and_control":                       "command_and_control",
    "fire_support":                              "fires",
    "air_defense_artillery":                     "fires",
    "maneuver":                                  "movement_and_maneuver",
    "engineer":                                  "movement_and_maneuver",
    "lift":                                      "movement_and_maneuver",
    "reconnaissance_and_surveillance":           "intelligence",
    "information":                               "intelligence",
    "cyberspace_electromagnetic_activities":     "intelligence",
    "chemical_biological_radiological_nuclear":  "protection",
    "sustainment":                               "sustainment",
    "line_of_communication":                     "sustainment",
}

# Doctrinal display order for the published HVTL — ADP 3-0 warfighting
# functions in the same sequence shown in ATP 2-01.3 Fig 6-9.
WARFIGHTING_FUNCTION_ORDER = [
    "command_and_control",
    "movement_and_maneuver",
    "intelligence",
    "fires",
    "sustainment",
    "protection",
]

WARFIGHTING_FUNCTION_LABELS = {
    "command_and_control":   "Command and Control",
    "movement_and_maneuver": "Movement and Maneuver",
    "intelligence":          "Intelligence",
    "fires":                 "Fires",
    "sustainment":           "Sustainment",
    "protection":            "Protection",
}

# Doctrinal staff display for FM 3-60 App. C categories. Tactical products
# (HVTL/HPTL/CARVER group bars + cells) use the acronym form where one exists;
# auto-humanizer would otherwise produce e.g. "Command and Control" / "Chemical
# Biological Radiological Nuclear" which are correct English but not staff
# shorthand. Other categories pass through to the smart humanizer.
TARGET_CATEGORY_LABELS = {
    "command_and_control":                       "C2",
    "air_defense_artillery":                     "ADA",
    "cyberspace_electromagnetic_activities":     "CEMA",
    "chemical_biological_radiological_nuclear":  "CBRN",
    "line_of_communication":                     "LOC",
    "reconnaissance_and_surveillance":           "Reconnaissance and Surveillance",
    "fire_support":                              "Fire Support",
    "maneuver":                                  "Maneuver",
    "engineer":                                  "Engineer",
    "information":                               "Information",
    "sustainment":                               "Sustainment",
    "lift":                                      "Lift",
}

# FIVE-O target type per FM 3-60 paras 1-20 – 1-25
TYPE_FIVE_O_ENUM = ["facility", "individual", "virtual", "equipment", "organization"]

# OAKOC factors (TEM)
OAKOC_ENUM = [
    "observation_and_fields_of_fire", "avenues_of_approach",
    "key_terrain", "obstacles", "cover_and_concealment",
]

# Doctrinal display for OAKOC factors. Auto-humanizer produces the right
# capitalization with the stop-word rule but this guarantees exact doctrinal
# wording (ATP 2-01.3 §4-39 – §4-53).
OAKOC_LABELS = {
    "observation_and_fields_of_fire": "Observation and Fields of Fire",
    "avenues_of_approach":            "Avenues of Approach",
    "key_terrain":                    "Key Terrain",
    "obstacles":                      "Obstacles",
    "cover_and_concealment":          "Cover and Concealment",
}

# Weather aspects per ATP 2-01.3 para 4-55 (used in some references; primary
# WEM rows are Operations × {Favorable/Unfavorable} per Fig 4-17)
WEATHER_ASPECT_ENUM = [
    "visibility", "wind", "precipitation", "cloud_cover",
    "temperature", "humidity", "atmospheric_pressure",
]

# WEM Figure 4-17 operations/systems list
WEM_OPERATIONS_FIG_4_17 = [
    "maneuver_tracked",
    "maneuver_with_night_vision_goggles_tracked",
    "dismounted_infantry",
    "weapon_positioning",
    "fire_support_155mm",
    "close_air_support_a10",
    "air_defense_artillery_vulcan_chaparral_stinger",
    "battlefield_obscuration",
    "airborne_operations_c130_c17",
    "aviation_rotary",
    "medical_evacuation_plus_above_criteria",
    "gray_eagle",
    "shadow_unmanned_aircraft_system",
    "manned_isr_rc12_mc12",
    "visual_sensors",
    "infrared_sensors",
    "engineer_operations",
    "nuclear_biological_chemical",
]

# CARVER score enums. Two doctrinal scales exist:
#
#   SCORE_1_10_ENUM — FM 34-36 App. D (Special Operations Forces
#       Intelligence and EW Operations) — five anchor PAIRS giving
#       1-10 granularity. The IDX 26 reference sample
#       (scratch/docs/ibl/event_samples/CARVER Example.xlsx) uses
#       this scale: scores like 8 / 9 / 3 / 8 / 5 / 6 fit cleanly
#       into the 9-10 / 7-8 / 5-6 / 3-4 / 1-2 anchor pairs. This is
#       the default for the CARVER product schema.
#
#   SCORE_1_5_ENUM — FM 3-60 Aug 2023 App. G Table G-1 (Army
#       Targeting) — single anchor per value, conventional Army's
#       compressed CARVER. Kept here for products that explicitly
#       opt into the FM 3-60 variant. FM 3-60 G-8 itself defers to
#       ATP 2-33.4 + ATP 3-05.20 for "expanded use" — and ATP 3-05.20
#       Special Operations Intelligence carries the FM 34-36 1-10
#       lineage. Both scales are doctrinally valid; the 1-10 form is
#       the SOF-canonical and broader-community default.
SCORE_1_10_ENUM = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
SCORE_1_5_ENUM = [1, 2, 3, 4, 5]

# Damage categories per JP 3-60 App. C — target-type-specific
PDA_BUILDING_DAMAGE = ["light", "moderate", "severe"]
PDA_ARMORED_DAMAGE = ["damaged"]
PDA_RUNWAY_DAMAGE = ["cratered", "cut", "interdicted"]
PDA_CONFIDENCE = ["confirmed", "probable", "possible"]
DAMAGE_MECHANISM_ENUM = ["blast", "fragmentation", "fire"]

# Tactical obstacle effects per Table 4-3
OBSTACLE_EFFECT_ENUM = ["disrupt", "turn", "fix", "block"]

# Mobility classification per para 4-46
MOBILITY_CLASS_ENUM = ["severely_restricted", "restricted", "unrestricted"]

# WEM impact rating
WEM_RATING_ENUM = ["favorable", "unfavorable"]  # Fig 4-17 default
WEM_RATING_3TIER_ENUM = ["favorable", "marginal", "unfavorable"]  # Table B-12

# COA rank
COA_RANK_ENUM = ["most_likely", "most_dangerous", "alternate"]

# Echelon
ECHELON_ENUM = ["CORPS", "DIV", "BDE", "BN", "CO", "PLT", "SQD", "TM", "BTY", "DET", "CELL"]

# Combat effectiveness (FM 6-99 SITREP Line 7 — common practice; doctrine doesn't enum)
COMBAT_EFF_ENUM = ["GREEN", "AMBER", "RED", "BLACK"]

# Posture
POSTURE_ENUM = ["operational", "defending", "attacking", "withdrawing",
                 "emcon", "hide_site", "degraded", "destroyed", "defeated"]

# Tactical posture display. The terminal-state values render uppercase
# (DEFEATED / DESTROYED / DEGRADED) per BDA convention; active postures
# render Title Case. EMCON stays all-caps (already in acronym list).
POSTURE_LABELS = {
    "operational": "Operational",
    "defending":   "Defending",
    "attacking":   "Attacking",
    "withdrawing": "Withdrawing",
    "emcon":       "EMCON",
    "hide_site":   "Hide Site",
    "degraded":    "DEGRADED",
    "destroyed":   "DESTROYED",
    "defeated":    "DEFEATED",
}

# Precedence
PRECEDENCE_ENUM = ["FLASH", "IMMEDIATE", "PRIORITY", "ROUTINE"]


# ============================================================================
# Standard header-field bedrock — most products share these
# ============================================================================

HEADER_DTG = {"source": "session", "view": "header", "required": True,
              "provenance_required": False}
HEADER_AO = {"source": "session", "view": "header", "required": True,
              "default": "AO BALTIC RESTORE",
              "provenance_required": False, "render_label": "Area of Operations"}
HEADER_CLASSIFICATION = {"source": "session", "view": "header",
                          "default": "UNCLASSIFIED // FOR EXERCISE USE ONLY",
                          "required": True,
                          "provenance_required": False}
# Auto-populated from the active session's user (state.user_id, resolved in
# intel_agent._build_skeleton). Replaces the older HEADER_PREPARING_UNIT
# constant which carried a generic "V Corps G-2" label and lost per-analyst
# accountability. Every product was using HEADER_PREPARING_UNIT identically;
# renaming to HEADER_PREPARED_BY + source=session.user lights up real
# attribution without touching downstream rendering.
HEADER_PREPARED_BY = {"source": "session.user", "view": "header",
                       "required": True, "provenance_required": False,
                       "render_label": "Prepared By"}
# Backwards-compat alias — older product files may still import the old name.
# Same shape, just a different dict reference. Safe to delete once all
# product files have migrated to HEADER_PREPARED_BY.
HEADER_PREPARING_UNIT = HEADER_PREPARED_BY
HEADER_PHASE = {"source": "session", "view": "header", "required": True,
                "provenance_required": False}

# Map-bearing products (MCOO / SITEMP / Threat Overlay / GRINTSUM) attach the geo-agent's
# rendered PNG URL + bounding box + map UUID into the header. The exporter's
# _render_map_embed (utils/exporter.py:530) reads spatial_overlay_url to emit a
# TinyMCE-friendly <figure> below the header block; _render_header_block hides
# spatial_overlay_* keys from the header k/v table itself. Pre-fill happens
# in handlers/intel_agent.py:_build_skeleton from the runner's render_map
# tool output — the writer doesn't have to know the geo-agent URL.
#
# All three are optional from the writer's POV (the runner fills them); they
# only need to be schema-declared so _render_header_block knows to skip them
# from the k/v table.
HEADER_SPATIAL_OVERLAY_URL = {
    "source": "map:render",
    "view": "header",
    "required": False,
    "provenance_required": False,
    "render_label": "Spatial Overlay URL",
    "depends_on": ["map:render"],
    "guidance": "PNG URL of the rendered map; filled by runner from render_map() output. Hidden from header k/v table; surfaces as the <figure> map embed below the header.",
}
HEADER_SPATIAL_OVERLAY_MAP_ID = {
    "source": "map:render",
    "view": "header",
    "required": False,
    "provenance_required": False,
    "render_label": "Spatial Overlay Map ID",
    "depends_on": ["map:render"],
    "guidance": "UUID of the geo-agent map; filled by runner from render_map() output. Hidden from header k/v table; used by DocEditor to deep-link to the live OperationsMap edit view.",
}
HEADER_SPATIAL_OVERLAY_BBOX = {
    "source": "map:render",
    "view": "header",
    "required": False,
    "provenance_required": False,
    "render_label": "Spatial Overlay BBox",
    "depends_on": ["map:render"],
    "guidance": "[west, south, east, north] bbox of the rendered map; filled by runner from render_map() output. Hidden from header k/v table.",
}

# ============================================================================
# PROVENANCE DIRECTIVE
# ============================================================================
# Every product needs provenance. Each artifact must show where every
# data-derived field came from, citing the specific WORLD-MODEL record that
# backed the value. The engine presents the writer a CLOSED retrieval set
# (clauses + entities + documents, each with an id); the writer cites those
# ids in `_provenance`; the engine resolves every cited id against the
# presented set (an id outside the set fails the generation as
# writer_invalid) and renders the Sources footer from each clause's stored
# source fields — the document, position, and quote captured at ingest. The
# id IS the citation; the source field carries the evidence.
#
# Generic citations like "order of battle" or "civil data" are NOT
# sufficient — they don't let an analyst trace the value back to the source
# record.
#
# This constant is appended to each product schema's `doctrine.purpose` so
# it appears at the top of every per-field writer prompt. It is also added
# to each schema's `hard_rules` via HARD_RULES_REGISTRY.
#
# Analyst-authored fields (executive summaries, analytical comments,
# recommendations, narrative leadership assessments) cite the generation
# record + analyst intent rather than a world-model record.
PROVENANCE_DIRECTIVE = (
    " PROVENANCE: every analytical claim about a real-world entity, event, "
    "or condition MUST emit a `_provenance` citation naming the specific "
    "world-model record id it came from — a clause id, entity id, or "
    "document id drawn VERBATIM from the retrieval set presented in this "
    "prompt. The id IS the citation: the engine resolves it against the "
    "presented set and renders the Sources footer from the record's stored "
    "source (document, position, and quote captured at ingest), so never "
    "restate document titles or quotes inline in place of the id. NEVER "
    "cite an id that is not in the presented set, and NEVER emit "
    "unqualified domain references alone (e.g. 'order of battle' or "
    "'civil considerations' without a record id). Analyst-authored fields "
    "(executive summaries, narrative assessments) cite the generation "
    "record + analyst intent, not a world-model record."
)
PROVENANCE_HARD_RULE = (
    "Every data-derived field carries a `_provenance` citation naming the "
    "specific world-model record id(s) — clause ids / entity ids / "
    "document ids drawn VERBATIM from the retrieval set presented in the "
    "prompt. Ids outside the presented set are rejected (writer_invalid). "
    "Unqualified domain references are rejected."
)


# ============================================================================
# ICD-203 canonical reference data — used by HARD_RULES_REGISTRY below and
# also exposed as named constants for any caller that wants the structured
# form (e.g. UI badges, schema enum validators).
# ============================================================================

# The seven-level likelihood vocabulary (ICD-203 §D.6.e.(2)(a)). Each entry
# lists the two interchangeable terms (Row 1 = lay vocabulary, Row 2 =
# statistical vocabulary) and the doctrinal calibration band that defines
# what each term means. The bands are CALIBRATION METADATA — they tell a
# consumer reading 'likely' that the analyst's judgment lives in the 55-80
# range — they are NOT a format the analyst is required to emit. The writer
# prompt (HARD_RULES_REGISTRY['icd_203_likelihood_terms']) explicitly
# FORBIDS putting any percentage in analytic prose unless it came from an
# algorithmic calculation. The structured form here exists for downstream
# consumers (UI badges, schema validators, training data labels) that want
# to know which band corresponds to which word. Source:
# https://www.dni.gov/files/documents/ICD/ICD-203.pdf
LIKELIHOOD_TERMS = [
    {"pct": "01-05%", "row1": "almost no chance",     "row2": "remote"},
    {"pct": "05-20%", "row1": "very unlikely",        "row2": "highly improbable"},
    {"pct": "20-45%", "row1": "unlikely",             "row2": "improbable (improbably)"},
    {"pct": "45-55%", "row1": "roughly even chance",  "row2": "roughly even odds"},
    {"pct": "55-80%", "row1": "likely",               "row2": "probable (probably)"},
    {"pct": "80-95%", "row1": "very likely",          "row2": "highly probable"},
    {"pct": "95-99%", "row1": "almost certain(ly)",   "row2": "nearly certain"},
]

# Confidence levels per ICD-203 §D.6.e.(2)(b). Describes the analyst's
# confidence in the EVIDENTIARY BASE / REASONING underpinning a judgment,
# not the likelihood of the event.
CONFIDENCE_LEVELS = ["low confidence", "moderate confidence", "high confidence"]


# ============================================================================
# HARD_RULES_REGISTRY — central registry of writer-prompt hard rules with
# applies_to scoping. Replaces the pattern of repeating PROVENANCE_HARD_RULE
# in every per-product schema's `hard_rules` list. New cross-product rules
# (e.g. ICD-203, ATP 2-33.4 source-handling, classification markings) land
# here once with `applies_to: ["*"]` instead of being copy-pasted across 30+
# product templates.
#
# Per-product schemas still own their product-specific `hard_rules` (e.g.
# CARVER's "six axes always scored", TCS's capability-phrasing rule); the
# prompt assembly path (`product.py:_render_hard_rules_section`) MERGES the
# registry rules applicable to the current product with the per-product list
# and emits them all as the LAST block of the writer prompt — they're the
# freshest thing in the model's attention when it starts emitting.
#
# Each entry: id (stable slug for telemetry), applies_to (list of
# product_type strings or ["*"] for universal), rule (multiline string the
# writer reads verbatim). Order in the list = order in the rendered prompt.
HARD_RULES_REGISTRY = [
    {
        "id": "icd_203_likelihood_terms",
        "applies_to": ["*"],
        "rule": """EVERY probability claim is expressed using ONE WORD from the standardized seven-level likelihood vocabulary. NO percentages, NO percentage bands, NO numerical odds anywhere in analytic prose. The word is the entire calibrated expression of likelihood.

The lay vocabulary is: 'almost no chance', 'very unlikely', 'unlikely', 'roughly even chance', 'likely', 'very likely', 'almost certain(ly)'.

The statistical vocabulary is: 'remote', 'highly improbable', 'improbable' (or 'improbably'), 'roughly even odds', 'probable' (or 'probably'), 'highly probable', 'nearly certain'.

The two vocabularies are interchangeable row-for-row. Pick ONE vocabulary per product and stay consistent. Mixing both vocabularies in the same product requires an explicit disclaimer that the differing terms indicate the same probability assessment.

NUMERICAL ODDS ARE FORBIDDEN unless they are LITERALLY ALGORITHMICALLY CALCULATED from a model, simulation, or computation whose output is a probability. Acceptable sources for a number: weapon engagement-probability calculation from range and target geometry, sensor detection-probability from coverage geometry, logistics consumption rate yielding 'fuel exhausted by D+5', Monte Carlo simulation of a force exchange, statistical analysis of historical event frequency. In every such case the number appears alongside the citation of the calculation that produced it (the model, the inputs, the assumptions). A number that was not produced by a calculation MUST NOT appear in the prose — not as a band, not as a point estimate, not in parentheses next to the word. Echoing a band from a doctrinal lookup table is NOT a calculation and is FORBIDDEN.

The reason: structured analytic judgment under irreducible uncertainty does not reduce to a probability calculation. The seven-level vocabulary exists precisely so the analyst expresses calibrated judgment via the word, and the consumer reads the doctrinally-defined meaning of the word, without anyone being forced to invent or defend a number that the underlying analysis cannot support. Attaching a number to the word implies false precision.

EVERY likelihood word MUST be followed in the same prose passage by the reasoning that produced it. The reasoning chain enumerates, as applicable to the claim, plain-English statements about: doctrinal fit (does the threat's standard template predict this behavior, paraphrased in the analyst's own words — never naming the publication or section); observed-indicator convergence (which HUMINT/SIGINT/IMINT/MASINT artifacts point at this behavior, cited by artifact ID); capability match (does the arrayed force structure support this scheme with the right echelons, enablers, logistics tail); OAKOC terrain fit (observation, avenues of approach, key terrain, obstacles, cover and concealment — favor this scheme over alternatives); time-space feasibility (can the threat physically execute within the friendly decision cycle); threat commander pattern (what this commander has done before under similar conditions); friendly perception (what the threat believes about friendly disposition and how that shapes his preferred scheme); alternatives ruled out (explicit comparison to other candidate hypotheses).

For COA probability_rationale specifically, the prose MUST satisfy ALL of the following — failure on any one is non-compliant:
  - Name exactly one vocabulary word from the seven-level scale as the likelihood judgment.
  - Enumerate the subset of the reasoning criteria above that drives the judgment, citing specific indicators by ID and specific terrain/capability findings by name.
  - Include EXPLICIT LIKELIHOOD-AXIS COMPARISON to EVERY other COA in the set, using the literal phrasing pattern 'more likely than COA-X because...' or 'less likely than COA-Y because...' or an explicit ranking statement ('most likely / second most likely / third most likely / least likely of the four COAs because...'). The comparison MUST be on the LIKELIHOOD dimension. Comparisons along other dimensions — more dangerous, more decisive, more disruptive, higher-impact, more destabilizing, more decisive, greater threat — do NOT satisfy this requirement even when the vocabulary word is itself a likelihood term. A COA that is 'most dangerous' may simultaneously be the LEAST likely; the danger comparison says nothing about likelihood and does not exempt the rationale from naming where this COA sits in the likelihood ranking.
    EXAMPLE OF NON-COMPLIANT COMPARATIVE FRAMING (forbidden):
      'Very likely. This COA is most dangerous because it directly targets the V Corps ability to synchronize its defense. It is more dangerous than COA-1 because it proactively disables the friendly counter-response mechanisms.'
      — fails because every comparison is on the danger axis; the rationale never says whether COA-3 is more or less LIKELY than COA-1, COA-2, or COA-4.
    EXAMPLE OF COMPLIANT COMPARATIVE FRAMING (required pattern):
      'Very likely. ... It is more likely than COA-2 because the 72nd MRD has already begun shaping fires consistent with this scheme (cited indicators), while COA-2 would require coordinated multi-axis movement the unit has not demonstrated. It is less likely than COA-1 only marginally — both are doctrinally favored, but COA-1's single-axis penetration requires less coordination overhead. It is more likely than COA-4 because the deception signatures required for COA-4 (simulated radio traffic, false force concentrations) have not been observed.'

A bare vocabulary word with no reasoning chain is non-compliant. A reasoning chain with no vocabulary word is non-compliant. A number anywhere in the rationale is non-compliant unless it came from a calculation cited inline.

The phrases 'Most Likely COA' and 'Most Dangerous COA' (and bracketed variants like '[MOST LIKELY]' or '[MOST DANGEROUS]') are STRUCTURAL section labels naming which COA the section describes; they are not probability claims and are not subject to this rule.

NEVER use 'likely', 'probable', 'almost certain', or 'remote' as casual English synonyms for 'large', 'small', or 'common' — they are bound to specific calibrated probability bands and must only appear as analytic-judgment terms.

DOCTRINAL CITATIONS ARE FORBIDDEN in user-visible prose, in every form. The doctrine informs the analyst's reasoning but never appears in the rendered output. The forbidden surface includes ALL of the following:
  - Publication-name references: ATP, FM, TC, JP, MCWP, ADP, MCTP, MCRP, FMI, ADRP, AR, DA Pam, MIL-STD, MIL-HDBK, STANAG.
  - Numbered-publication tokens of any form: 'ATP 2-01.3', 'FM 3-0', 'TC 7-100.2', 'JP 2-01', 'MCWP 3-1.6.18', or any '<letter-token> <number>(-<number>)+' shape that names a publication.
  - Section-symbol references in any form: '§2.a', '§3-12', '§D.6.e.(2)(a)', 'Section 2.a', 'Para 3-12', 'Chapter 4', 'Annex C', 'Appendix B', or bare parenthetical section symbols like '(§2.a)' / '(§3.f)'.
  - Combined publication-and-section tokens: '(TC 7-100.2 §3.f)', '(ATP 2-01.3 §6-35)', 'per ATP 2-01.3', 'IAW FM 3-0'.
  - Doctrinal-attribution phrasings: 'per doctrine', 'per <publication>', 'IAW <publication>', 'in accordance with <publication>', 'doctrinally per <publication>', 'as defined in <publication>'.
  - Bracketed doctrinal references: '[ATP 2-01.3]', '[§2.a]', '[TC 7-100.2]'.
If the model needs to convey doctrinal alignment, it paraphrases the doctrinal pattern in plain analyst English without naming the publication, section, paragraph, chapter, annex, or appendix. Example of acceptable paraphrase: 'aligns with the standard mechanized-penetration pattern — first-echelon assault formations occupying forward BPs to establish the line of departure'. Example of forbidden citation: 'aligns with the core doctrinal pattern for a mechanized penetration (§2.a)'.""",
    },
    {
        "id": "icd_203_confidence_vs_likelihood",
        "applies_to": ["*"],
        "rule": """CONFIDENCE and LIKELIHOOD are distinct and must never be combined in the same sentence. Confidence ('low confidence', 'moderate confidence', 'high confidence') describes faith in the EVIDENTIARY BASE AND REASONING underpinning a judgment. Likelihood (the seven-level vocabulary in the prior rule) describes the probability of an event or development. Conflating them leaves the consumer unable to tell which one governs.
  WRONG: 'We assess with high confidence that the threat will likely attack via the Elk corridor.'
  RIGHT: 'The threat will likely attack via the Elk corridor. We assess this judgment with high confidence based on the convergence of HUMINT, SIGINT, and IMINT indicators.'""",
    },
    {
        "id": "icd_203_assumptions_vs_judgments",
        "applies_to": ["*"],
        "rule": """Distinguish ASSUMPTIONS from JUDGMENTS. An assumption is a supposition used to frame or support an argument; it affects interpretation of underlying intelligence. A judgment is a conclusion based on intelligence, analysis, AND assumptions. State assumptions EXPLICITLY when they are the linchpin of an argument or bridge a key information gap. Explain the implication for the judgment if the assumption proves incorrect. Identify the indicators that, if observed, would alter the judgment.""",
    },
    {
        "id": "icd_203_analysis_of_alternatives",
        "applies_to": ["*"],
        "rule": """When major judgments contend with significant uncertainty, complexity (e.g. forecasting), or when low-probability events could produce high-impact results, identify and assess plausible alternative hypotheses. For each alternative, address its associated assumptions, likelihood (using the seven-level vocabulary, word only), and implications. Identify indicators that, if detected, would affect the likelihood of the identified alternatives.""",
    },
    {
        "id": "icd_203_clear_argumentation",
        "applies_to": ["*"],
        "rule": """Lead with the main analytic message. Every analytical claim is supported by relevant intelligence and explicit reasoning. Acknowledge significant contrary information rather than omitting it. Express judgments clearly and precisely — the message the consumer receives must be the one the analyst intended to send. Reduce ambiguity by addressing the likelihood, timing, and nature of the outcome.""",
    },
    {
        "id": "provenance_hard_rule",
        "applies_to": ["*"],
        "rule": PROVENANCE_HARD_RULE,
    },
]


def hard_rules_for(product_type, per_product_extras=None):
    """Merge universal rules from HARD_RULES_REGISTRY with the per-product
    schema's own `hard_rules` list, in registry order followed by the
    per-product list. Returns a list[str] ready to feed to the bullet
    renderer.

    applies_to dispatch:
      - ["*"] or ["all"] entries match every product_type
      - otherwise the product_type must appear in the list verbatim

    The caller (product.py:_render_hard_rules_section) wraps the result in
    the `## Hard rules` markdown block at the END of the writer prompt so
    the rules are the freshest thing in the model's attention when it
    starts emitting.
    """
    rules = []
    seen = set()  # dedup by rule text — per-product schemas authored before
                  # this registry existed often duplicate registry rules
                  # (e.g. PROVENANCE_HARD_RULE) in their own hard_rules list.
                  # Keep the FIRST occurrence so registry order is preserved.
    for entry in HARD_RULES_REGISTRY:
        scope = entry.get("applies_to") or []
        if "*" in scope or "all" in scope or product_type in scope:
            rule = entry["rule"]
            if rule and rule not in seen:
                rules.append(rule)
                seen.add(rule)
    if per_product_extras:
        for r in per_product_extras:
            if r and r not in seen:
                rules.append(r)
                seen.add(r)
    return rules
