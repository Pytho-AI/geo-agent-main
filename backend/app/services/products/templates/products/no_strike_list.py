"""No-Strike List (NSL) — JP 3-60 Ch. III §B para 6(e); FM 3-60 paras 1-11 – 1-12.

The NSL is a list of entities — characterized as noncombatant in nature and
protected from the effects of military operations under international law and
ROE — that are off-limits to engagement. JP 3-60 explicitly states the NSL is
NOT a target list (Ch. III §B para 6(e)); it is the joint targeting cycle's
legal-protection filter. CCMDs with geographic responsibilities maintain an
NSL for their AOR ().

Doctrinal acronym: NSL appears verbatim in JP 3-60 (GL-2 and III-13 §(e)) and
in FM 3-60 (acronym list and paras 1-11 / 1-12).

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

# Doctrinal categories of protected entities per # ("cultural and religious sites, embassies belonging to noncombatant
# countries, hospitals, schools") + Appendix A §4 (protected objects under the
# law of war). Categories are explicit doctrinal exemplars; the runner must not
# invent new ones.
PROTECTED_ENTITY_CATEGORY_ENUM = [
    "medical_facility",
    "religious_site",
    "cultural_site",
    "educational_facility",
    "diplomatic_facility",
    "humanitarian_facility",
    "civil_defense_facility",
    "prisoner_of_war_camp",
    "dangerous_forces_installation",
    "civilian_infrastructure",
    "civilian_population_concentration",
    "other_protected_entity"]

PROTECTED_ENTITY_CATEGORY_LABELS = {
    "medical_facility":                 "Medical Facility",
    "religious_site":                   "Religious Site",
    "cultural_site":                    "Cultural Site",
    "educational_facility":             "Educational Facility",
    "diplomatic_facility":              "Diplomatic Facility",
    "humanitarian_facility":            "Humanitarian Facility",
    "civil_defense_facility":           "Civil Defense Facility",
    "prisoner_of_war_camp":             "Prisoner of War Camp",
    "dangerous_forces_installation":    "Installation Containing Dangerous Forces",
    "civilian_infrastructure":          "Civilian Infrastructure",
    "civilian_population_concentration": "Civilian Population Concentration",
    "other_protected_entity":           "Other Protected Entity",
}

# Source-of-protection enum per JP 3-60 Ch. III §B para 6(e) ("defined by the
# law of war ... protected from the effects of military operations under
# international law and ROE") + FM 3-60 para 1-12 (NSL protections derive from
# "Law of war / International laws / ROE / Other considerations").
PROTECTION_SOURCE_ENUM = [
    "law_of_war",
    "international_law",
    "rules_of_engagement",
    "joint_force_commander_guidance",
    "host_nation_agreement",
    "other_authority"]

PROTECTION_SOURCE_LABELS = {
    "law_of_war":                     "Law of War",
    "international_law":              "International Law",
    "rules_of_engagement":            "ROE",
    "joint_force_commander_guidance": "JFC Guidance",
    "host_nation_agreement":          "Host-Nation Agreement",
    "other_authority":                "Other Authority",
}

SPEC = {
    "name": "NSL",
    "output_format": "pptx",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. JP 3-60 Ch. III
    # §B 6(e): SJA-maintained protection ledger reviewed row-by-row.
    "output_formats": ["xlsx"],
    "legacy_formats": ["pptx"],
    "shape": "row",
    "doctrine": {
        "purpose": (
            "Protection-list product. Enumerates entities in or near the AOR that are "
            "protected from the effects of military operations under international law "
            "and ROE. The NSL is NOT a target list — it is the legal filter that "
            "constrains the JTL, RTL, JIPTL, and HPTL. A listed object on the NSL must "
            "be removed from that list before a strike on the object can be lawfully "
            "authorized. Drives the deconfliction check in HPTL row derivation and the "
            "CDE for any target with collateral proximity to NSL entities.\n\n"
            "ROW-LEVEL PROVENANCE (MANDATORY): every protected-site row MUST cite its "
            "source civil entity by C-### ID in `_provenance`. Rows are derived from the "
            "`get_civil` payload (KG.civil) — the C-### IDs are the canonical entity "
            "handles. Format each row's `_provenance` to map field name → "
            "`get_civil.<ascope_layer>.C-###`. Example for Tartu power substation: "
            "`_provenance['entity_name'] = 'get_civil.structures.C-005'`. Use ONLY IDs "
            "present in the get_civil payload. NEVER invent C-### IDs — if no C-### "
            "matches, the row must not be emitted."
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Rows grouped by protected-entity category (medical, religious, cultural, "
            "diplomatic, etc.). NSL is NOT priority-ordered — every entry is "
            "categorically off-limits absent explicit removal by the documented "
            "approval authority. Within a category, rows are ordered alphabetically by "
            "entity_name for staff readability."
        ),
    },
    "row_source": "kg_protected_entities",
    "group_by": "category",
    # OE Definition + Tier 1 BOTH rollups AND atomics — a hospital
    # newly identified by a HUMINT IIR mid-cycle must surface on the
    # NSL immediately, not wait for the next HUMINTSUM publish.
    "consumes_artifacts": ["Operational Environment Definition",
                            "HUMINTSUM", "OSIR"],
    "published_section_title": "No-Strike Entities",
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "approving_authority": {"source": "session", "view": "header", "required": True,
                                  "default": "TBD — JFC / CCMD approval pending",
                                  "render_label": "Approving Authority",
                                  "guidance": (
                                    "Authority that approved and maintains this NSL "
                                    "( — the responsible "
                                    "CCMD with geographic responsibility, delegated as "
                                    "the JFC directs). Pull from OPORD §3.d / FRAGO "
                                    "header. Leave default when running a draft before "
                                    "approval."
                                  )},
        "establishing_directive": {"source": "session", "view": "header", "required": False,
                                     "render_label": "Establishing Directive",
                                     "guidance": (
                                        "Order or directive that establishes this NSL "
                                        "for the named AOR (OPORD §3.d, FRAGO, or "
                                        "standalone NSL promulgation message). Cite by "
                                        "reference number when available."
                                     )},
        "oe_definition_artifact_id": {"source": "upstream:OE Definition", "view": "internal",
                                        "required": False,
                                        "render_label": "OE Definition Reference",
                                        "guidance": (
                                            "Upstream OE Definition artifact_id when "
                                            "available — establishes the AOR / time "
                                            "window the NSL is scoped to."
                                        )},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "row_fields": {
        # Identity block — published view
        "id":                {"source": "entity:id", "view": "internal",
                                "required": True, "provenance_required": True,
                                "render_label": "ID",
                                "depends_on": ["entities:civil"],
                                "guidance": (
                                    "Source civil entity C-### ID (e.g., 'C-005'). "
                                    "_provenance MUST cite "
                                    "`get_civil.<ascope_layer>.C-###` (e.g., "
                                    "`get_civil.structures.C-005`)."
                                )},
        "entity_name":       {"source": "entity:name", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Protected Entity",
                                "depends_on": ["entities:civil"],
                                "guidance": (
                                    "Entity name copied verbatim from the get_civil "
                                    "row's `name` field. _provenance MUST cite the "
                                    "source C-### ID as "
                                    "`get_civil.<ascope_layer>.C-###`."
                                )},
        "category":          {"source": "entity:category", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Category",
                                "enum": PROTECTED_ENTITY_CATEGORY_ENUM,
                                "enum_labels": PROTECTED_ENTITY_CATEGORY_LABELS,
                                "depends_on": ["entities:civil"],
                                "guidance": (
                                    "Protected-entity category. The enum covers the "
                                    "explicit doctrinal exemplars; use "
                                    "'other_protected_entity' only when none of the "
                                    "named categories fits and the entity is protected "
                                    "by one of the PROTECTION_SOURCE_ENUM authorities. "
                                    "_provenance MUST cite the source C-### ID as "
                                    "`get_civil.<ascope_layer>.C-###`."
                                )},
        "location_mgrs":     {"source": "entity:location_mgrs", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Location (MGRS)",
                                "depends_on": ["entities:civil"],
                                "guidance": (
                                    "MGRS copied verbatim from the get_civil row's "
                                    "`mgrs` field. _provenance MUST cite the source "
                                    "C-### ID as `get_civil.<ascope_layer>.C-###`."
                                )},
        "protection_basis":  {"source": "analytical", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Protection Basis",
                                "enum": PROTECTION_SOURCE_ENUM,
                                "enum_labels": PROTECTION_SOURCE_LABELS,
                                "guidance": (
                                    "Authority under which this entity is protected "
                                    "('Law of war / International "
                                    "laws / ROE / Other considerations'). When more "
                                    "than one basis applies, list the most binding one "
                                    "here and cite the others in protection_rationale."
                                )},
        "protection_rationale": {"source": "analytical", "view": "published",
                                   "required": True, "provenance_required": True,
                                   "render_label": "Rationale",
                                   "guidance": (
                                    "ONE short sentence — why this entity is protected. "
                                    "Cite the controlling treaty/convention/ROE "
                                    "paragraph / directive in _provenance (e.g. "
                                    "Geneva Conventions Additional Protocol I Art. 15, "
                                    "Hague IV Convention 1907 Art. 27, ROE serial nr.). "
                                    "Examples —"
                                    "cultural and religious sites, embassies of "
                                    "noncombatant countries, hospitals, schools."
                                   )},
        # Workpaper — supports SJA review and downstream HPTL/CDE deconfliction
        "established_dtg":   {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "render_label": "Date Added to NSL",
                                "guidance": "When the entity was added to this NSL (NSLs are continuously updated)."},
        "last_reviewed_dtg": {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "render_label": "Last Reviewed DTG",
                                "guidance": "Most recent SJA / J-2 review."},
        "review_authority":  {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "render_label": "Review Authority",
                                "guidance": "Staff judge advocate or J-2 element that reviewed the entity for continued NSL inclusion."},
        "nominating_source": {"source": "analytical", "view": "workpaper",
                                "required": False, "provenance_required": True,
                                "render_label": "Nominating Source",
                                "guidance": (
                                    "Who proposed this entity for the NSL — other CCMDs and "
                                    "agencies may propose; the G-2 also identifies "
                                    "G-2 as Army nominator. Civil-affairs / civil-"
                                    "military operations cells, IC partners, NGOs, "
                                    "humanitarian-notification systems (ICRC / OCHA / etc.) are doctrinal sources."
                                )},
        "humanitarian_notification": {"source": "analytical", "view": "workpaper",
                                        "required": False,
                                        "render_label": "Humanitarian Notification",
                                        "guidance": (
                                            "True when the entity was registered via a "
                                            "humanitarian-notification system (ICRC / OCHA / etc.)."
                                            "Cite system + record id in _provenance."
                                        ),
                                        "default": False},
        "associated_signatures": {"source": "analytical", "view": "workpaper",
                                    "required": False, "provenance_required": True,
                                    "render_label": "Distinctive Markings / Signatures",
                                    "guidance": (
                                        "Distinctive signs the entity displays per JP "
                                        "('protected facilities "
                                        "such as hospitals and POW camps are also "
                                        "clearly marked through the use of distinctive "
                                        "and visible signs as required by the law of "
                                        "war'). Helpful for sensor-derived PID and CDE "
                                        "proximity checks."
                                    )},
        # Override conditions — the entity may lose protection (JP 3-60 App. A
        # §4 paras (6)–(7) — when "used for military or combat purposes",
        # protected status may be lost; but removal from the NSL is an explicit
        # documented action per ).
        "override_authority": {"source": "analytical", "view": "workpaper",
                                  "required": False,
                                  "render_label": "Override / Removal Authority",
                                  "guidance": (
                                    "Authority required to REMOVE this entity from the "
                                    "NSL before a strike can be lawfully authorized "
                                    "('A listed object on "
                                    "the NSL is removed from that list before a strike "
                                    "on the object can be lawfully authorized'). For "
                                    "sensitive-target overlap, the authority is "
                                    "Presidential or SecDef per the STAR process. For "
                                    "ROE-only "
                                    "protections, the authority is whoever owns the "
                                    "ROE. Default to JFC unless a higher authority is "
                                    "named in OPORD / FRAGO."
                                  )},
        "override_conditions": {"source": "analytical", "view": "workpaper",
                                   "required": False, "provenance_required": True,
                                   "render_label": "Conditions for Loss of Protection",
                                   "guidance": (
                                    "Doctrinal conditions under which the entity may "
                                    "lose protected status : 'the enemy's use of a civilian or protected "
                                    "object or location for military or combat purposes "
                                    "may result in the loss of protected status, "
                                    "rendering it subject to attack.' Spell out the "
                                    "specific observed-condition trigger and the "
                                    "evidence threshold. NEVER imply automatic loss — "
                                    "removal still requires the named override "
                                    "authority's action."
                                   )},
        "collateral_proximity_note": {"source": "analytical", "view": "workpaper",
                                        "required": False,
                                        "render_label": "Collateral Proximity Note",
                                        "guidance": (
                                            "Free-text note flagging nearby valid "
                                            "targets that will require CDE for collateral "
                                            "risk (: when "
                                            "civilian/protected structures are "
                                            "collocated with or in proximity to military "
                                            "targets, the responsible commander "
                                            "mitigates collateral damage via CDE/CEE). "
                                            "Reference parent CDE artifact_id where "
                                            "one exists."
                                        )},
    },
    "subtleties": [
        "'The NSL is not a target list, though it is a critical part of the joint targeting process.' Do not treat NSL rows as nominations — they are protections.",
        "NSL is maintained at CCMD level for geographic AORs per . For IDX 26 (V Corps Estonia), V Corps inherits / coordinates with the USEUCOM NSL for the AOR.",
        "NSL ↔ HPTL deconfliction: NSL entries CANNOT appear on the JIPTL / HPTL. The HPTL row-derivation step must drop any candidate that overlaps with NSL geometry by location_mgrs + entity identity.",
        "NSL ↔ RTL deconfliction ('8. Conflicts with NSL.' / '9. Conflicts with RTL.' are required pre-engagement validation checks): both lists are inputs to target validation in JTC Phase 4.",
        "Protected status can be LOST when the enemy uses the entity for military/combat purposes — but removal from the NSL still requires the named override authority's action; do not encode automatic removal in the workflow.",
        "Sensitive-target overlap: NSL entries that, if struck, would have high diplomatic / political consequence require Presidential or SecDef approval under the Sensitive Target Approval and Review (STAR) process.",
        "Humanitarian notification systems are a typical NSLnomination input — ICRC, OCHA, NGO registrations. Treat any humanitarian-notified entity as NSL-default-on.",
        "Per IDX 26 organizer requirement: every protected-entity claim cites the controlling treaty/convention/ROE serial nr. / humanitarian-notification record id in _provenance."],
    "hard_rules": [
        "Never include an NSL entry on the HPTL, JIPTL, or any nomination list. NSL-flagged entries are dropped at HPTL row derivation.",
        "Every entry must cite at least one PROTECTION_SOURCE_ENUM authority AND a concrete controlling instrument (treaty article / ROE serial nr. / humanitarian-notification record) in _provenance.",
        "Per : an NSL entry is REMOVED before a strike can be lawfully authorized. Encode this as a hard pre-engagement gate — never as an inline override at the strike-package level.",
        "Protected-entity categories restricted to the PROTECTED_ENTITY_CATEGORY_ENUM. Use 'other_protected_entity' only with explicit protection_rationale + controlling instrument cited.",
        "Override conditions describe when protected status MAY be lost — they do NOT remove the entity from the NSL automatically. Removal is an explicit documented act by the override_authority.",
        "Per IDX 26: every protected-entity entry has _provenance for entity identity AND protection basis.",
        "EACH PROTECTED-SITE ROW MUST CITE ITS SOURCE CIVIL ENTITY BY C-### ID in _provenance. "
        "Format: `get_civil.<ascope_layer>.C-###` (e.g., `get_civil.structures.C-005` for "
        "Tartu power substation, `get_civil.structures.C-006` for Tartu University, "
        "`get_civil.organizations.C-009` for ICRC field team, `get_civil.people.C-010` "
        "for Mayor Tamme). Use ONLY IDs present in the get_civil payload. "
        "NEVER invent C-### IDs — a row without a matching C-### in the get_civil response "
        "is invalid output and must not be emitted.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Protected entities in AO: list_protected_entities() / kg_protected_entities query",
        "Civil-military overlay: get_project_doc(tag='OE Definition') civil-considerations section",
        "Civil considerations LOAC-protected list (now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Sustainment overlay LOAC-protected medical / Class VIII (MTF / Class VIII points are protected medical facilities under LOAC; MSR/ASR proximity for routing constraints): get_spatial_overlay()",
        "Humanitarian notifications: get_project_doc(tag='humanitarian_notifications') when available",
        "OPORD §3.d targeting guidance / protected-list paragraphs: get_project_doc(tag='OPORD')",
        "Latest FRAGO with NSL updates: list_project_docs(filter={type:'FRAGO'}) then get_project_doc",
        "Prior NSL (regen / continuity): list_project_docs(filter={type:'NSL'}) then get_project_doc(tag=<latest>)",
        "SJA legal review notes: get_project_doc(tag='SJA_review') when available"],
    "post_emit_summary": "artifact_id, row count, categories represented, any humanitarian-notification entries, count of entries with override conditions",
}
