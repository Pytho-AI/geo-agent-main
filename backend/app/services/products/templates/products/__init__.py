"""Per-product schemas. Each module exports a `SPEC` dict.

This module assembles them into PRODUCT_SCHEMAS, the public map keyed by product
name. Library is 31 entries per the 2026-05-13 audit (scratch/ibl/
product-audit-2026-05-13.md):

  - TMO / JDPI removed; TMO is a coordinate-generation process, JDPI is folded
    into TMP per CJCSI 3505.01E para 4.f.
  - MEA / Reattack Recommendation folded into Combat Assessment per FM 3-60
    paras 2-70 – 2-82.
  - Threat Template folded into Threat Model per ATP 2-01.3 para 5-45 (Threat
    Template is one of the three Threat Model activities, not a standalone).
  - File `oe_definition.py` renamed to `operational_environment_definition.py`;
    registry key changed from "OE Definition" to "Operational Environment
    Definition". ATP 2-01.3 publishes no acronym for the Step-1 product.
  - File `thrt.py` renamed to `threat_overlay.py`; registry key changed from
    "THRT" to "Threat Overlay". Both the abbreviation and the key were
    Pytho-side inventions; doctrinal name is "Threat Overlay" with no
    published acronym (ATP 2-01.3 para 4-6 / Fig 4-2).
  - 17 other acronym-named .py files renamed to full doctrinal names; registry
    keys stay as published acronyms (WEM, TEM, MCOO, CCA, Threat COA Statement, SITEMP, HVTL,
    CARVER, HPTL, TSS, AGM, TSM, TMP, BDA, INTSUM, GRINTSUM, SITREP).
"""
from .weather_effects_matrix import SPEC as _wem_SPEC
from .terrain_effects_matrix import SPEC as _tem_SPEC
from .modified_combined_obstacle_overlay import SPEC as _mcoo_SPEC
from .civil_considerations_assessment import SPEC as _cca_SPEC
from .threat_overlay import SPEC as _threat_overlay_SPEC
from .enemy_course_of_action import SPEC as _threat_coa_statement_SPEC
from .situation_template import SPEC as _sitemp_SPEC
from .threat_coas import SPEC as _threat_coas_SPEC
from .high_value_target_list import SPEC as _hvtl_SPEC
from .carver_target_value_analysis import SPEC as _carver_SPEC
from .high_payoff_target_list import SPEC as _hptl_SPEC
from .target_selection_standards import SPEC as _tss_SPEC
from .attack_guidance_matrix import SPEC as _agm_SPEC
from .target_synchronization_matrix import SPEC as _tsm_SPEC
from .target_material_production import SPEC as _tmp_SPEC
from .target_intelligence_data import SPEC as _tidat_SPEC
from .battle_damage_assessment import SPEC as _bda_SPEC
from .intelligence_summary import SPEC as _intsum_SPEC
from .graphic_intelligence_summary import SPEC as _grintsum_SPEC
from .situation_report import SPEC as _sitrep_SPEC
from .threat_model import SPEC as _threat_model_SPEC
from .threat_capability_statement import SPEC as _threat_capability_statement_SPEC
from .operational_environment_definition import SPEC as _oed_SPEC
from .event_template import SPEC as _event_template_SPEC
from .decision_support_template import SPEC as _decision_support_template_SPEC
# Red (threat-perspective) mirror of the Decision Support Template — templates
# the THREAT commander's decision points (enemy decisions triggered BY friendly
# activity). Independent product; see red_decision_support_template.py.
from .red_decision_support_template import SPEC as _red_decision_support_template_SPEC
from .information_collection_matrix import SPEC as _information_collection_matrix_SPEC
# ATP 2-33.4 intel estimates (companion to INTSUM/GRINTSUM — App. E paras E-5 – E-9).
from .intelligence_estimate import SPEC as _intelligence_estimate_SPEC
from .intelligence_running_estimate import SPEC as _intelligence_running_estimate_SPEC
# FM 3-60 Aug 2023 Ch. 2 + JP 3-60 App. C Assess-phase closure (after BDA).
# MEA + Reattack Recommendation are folded into Combat Assessment per FM 3-60
# para 2-70 — they are CA elements, not standalone deliverables.
from .combat_assessment import SPEC as _combat_assessment_SPEC
# Target System Analysis (TSA) ARCHIVED 2026-06-08 — see
# templates/products/_archived/README.md. Per JP 3-60 Ch. II ¶3 (Joint
# Targeting Cycle Phase 2 — Target Development), TSA is authored at
# theater J-2 / DIA / JIOC, NOT during the corps MDMP / IPOE / D3A
# cycle. Corps consumes pre-published TSAs as reference material;
# they're not a corps-authored product. HVTL is the actual intel→
# targeting bridge and does not require TSA as a dep.
# JP 3-60 + CJCSI 3122.06 / 3160.01D legal/ROE pre-strike gates.
from .no_strike_list import SPEC as _no_strike_list_SPEC
from .restricted_target_list import SPEC as _restricted_target_list_SPEC
from .collateral_damage_estimate import SPEC as _collateral_damage_estimate_SPEC
# Tier 1 single-INT analytical products.
#
# Scope: KLIEGLIGHT (the doctrinal perishable SIGINT atomic — USSID SE 4001,
# event-driven via the Cougaar KG poller), the three discipline rollups
# (SIGSUM / HUMINTSUM / OSIR), and the two terrain-derived geospatial
# products (CCM / LOS).
#
# Sensor-message atomics (TACELINT, IIR (GEOINT), HUMINT IIR, RECCEXREP,
# INTREP) are intentionally NOT modeled as schemas — they are USMTF / IIR
# message records already present in the Cougaar KG (IDXTacElintReport,
# IDXSignalOfInterestReport, IDXImageIirReport, IDXImageIirItem,
# IDXImageryReport, IDXHumintReport, IDXTacticalReport, etc.) and consumed
# directly by Tier 1 rollups + Tier 2 fusion via the cougaar_adapters
# `get_recent_intel()` path. They are sensor outputs, not analyst-authored
# documents.
#
# Tactical OSINT Tipper / BIIR / Knowledgeability Brief intentionally
# dropped: OSINT is delivered as Word doc injects ingested into
# projectdocs (analyst reads inject content directly without an
# intermediate published Tipper artifact); BIIR was a fabricated
# acronym and biographic intelligence (DIAM 58-13) is not a deliverable
# in the IDX 26 scope; Knowledgeability Brief requires collector
# interview notes not in the data dumps.
from .signals_intelligence_summary import SPEC as _sigsum_SPEC
from .kliegl_light_report import SPEC as _kliegl_light_SPEC
from .cross_country_mobility import SPEC as _ccm_SPEC
from .line_of_sight import SPEC as _los_SPEC
from .humint_intelligence_summary import SPEC as _humintsum_SPEC
from .open_source_intelligence_report import SPEC as _osir_SPEC
# Tier 2 fused additions surfaced by the FINAL_DOCTRINE_AUDIT discovery
# pass: ICSM + DSM. TIF/ETF intentionally NOT a product — it's a per-target
# COLLECTION (folder of linked artifacts), expressed via target_id metadata
# on existing artifacts and queried via list_project_docs(filter={target_id}),
# not generated as a singular .docx/.pptx.
from .information_collection_synchronization_matrix import SPEC as _icsm_SPEC
from .decision_support_matrix import SPEC as _dsm_SPEC
# Priority Intelligence Requirements — ATP 2-01 + ATP 2-01.3 + FM 6-0 CCIR.
# Parent of the collection-planning chain (PIR → ICM → Event Matrix → DST).
# Standalone XLSX product, not folded into OPORD free-text.
from .priority_intelligence_requirements import SPEC as _pir_SPEC
# XLSX spin-off siblings of hybrid products (EXCEL_DOCTRINAL_ALIGNMENT.md §3).
# Each is its own generation — independent of the parent — and emits XLSX only.
# Parent hybrid products (CCA, CA, Event Template, Decision Support Template,
# Threat Overlay) continue to render their existing DOCX/PPTX outputs.
from .cca_matrix import SPEC as _cca_matrix_SPEC
from .ca_engagements import SPEC as _ca_engagements_SPEC
from .event_matrix import SPEC as _event_matrix_SPEC
from .dst_matrix import SPEC as _dst_matrix_SPEC
from .threat_description_table import SPEC as _threat_description_table_SPEC

PRODUCT_SCHEMAS = {
    # Step-1 IPOE (ATP 2-01.3 Ch. 3). Keyed by full doctrinal name; ATP 2-01.3
    # publishes no acronym for it and the schema must not invent one.
    "Operational Environment Definition": _oed_SPEC,
    "WEM": _wem_SPEC,
    "TEM": _tem_SPEC,
    "MCOO": _mcoo_SPEC,
    "CCA": _cca_SPEC,
    # Step-2 threat overlay — ATP 2-01.3 para 4-6 / Fig 4-2. Doctrinal name
    # is "Threat Overlay" with no published acronym; key is the full name.
    "Threat Overlay": _threat_overlay_SPEC,
    "Threat COA Statement": _threat_coa_statement_SPEC,
    "SITEMP": _sitemp_SPEC,
    # Step-4 commander-facing deliverable. Combines Threat COA Statement's analytical
    # per-COA descriptions with the per-COA SITEMP graphic into one
    # landscape PPTX — one slide per COA. Downstream of Threat COA Statement + SITEMP.
    "Threat COAs": _threat_coas_SPEC,
    "HVTL": _hvtl_SPEC,
    "CARVER": _carver_SPEC,
    "HPTL": _hptl_SPEC,
    # FM 3-60 (Aug 2023) Decide-phase targeting trio. Doctrinal acronyms per
    # App. D Tables D-2 (TSS), D-3 (AGM), D-4 (TSM). HPTL → TSS → AGM → TSM
    # is the doctrinal chain (the targeting working group's deliverable set
    # per ATP 3-09.90 Fig 3-2 wargaming output). TSM also consumes the
    # Step-4 Information Collection Matrix per FM 3-60 App. D Fig D-1 + D-10.
    "TSS": _tss_SPEC,
    "AGM": _agm_SPEC,
    "TSM": _tsm_SPEC,
    # TMP contains JDPI graphic + data sheet per CJCSI 3505.01E para 4.f.
    "TMP": _tmp_SPEC,
    "TIDAT": _tidat_SPEC,
    "BDA": _bda_SPEC,
    "INTSUM": _intsum_SPEC,
    "GRINTSUM": _grintsum_SPEC,
    "SITREP": _sitrep_SPEC,
    # ATP 2-01.3 Step-3 threat product family (Ch. 5 paras 5-45 – 5-71).
    # Keyed by the full doctrinal name — these have no doctrinal acronym
    # and the schema must not invent one. Threat Template is one of the three
    # Threat Model activities per para 5-45 (graphic + tactics + HVT-ID) and
    # is folded into Threat Model as a section.
    "Threat Model":                _threat_model_SPEC,
    "Threat Capability Statement": _threat_capability_statement_SPEC,
    # ATP 2-01.3 Step-4 IC trio (Ch. 6 paras 6-64 – 6-72; Figs 6-11 – 6-15).
    # PIR is the PARENT — feeds ICM (cross-tab against assets), Event
    # Template (NAI × time × DP), and DST (decision points whose triggers
    # ARE PIR-answered conditions).
    "PIR":                           _pir_SPEC,
    "Event Template":                _event_template_SPEC,
    "Decision Support Template":     _decision_support_template_SPEC,
    # Red (threat-perspective) DST — independent product mirroring the
    # Decision Support Template from the threat commander's seat (enemy
    # decisions triggered BY friendly activity).
    "Threat Decision Support Template": _red_decision_support_template_SPEC,
    "Information Collection Matrix": _information_collection_matrix_SPEC,
    # ATP 2-33.4 App. E intel estimates (paras E-5 – E-9, Figs E-2/E-3). These
    # are MDMP and continuous-ops staff products — companions to INTSUM/GRINTSUM
    # rather than chain-internal IPOE products. No doctrinal acronyms.
    "Intelligence Estimate":         _intelligence_estimate_SPEC,
    "Intelligence Running Estimate": _intelligence_running_estimate_SPEC,
    # FM 3-60 Aug 2023 Ch. 2 + JP 3-60 App. C Assess-phase closure (paras 2-70
    # – 2-82). CA is the rollup; MEA findings + Reattack Recommendation are
    # CA sections per FM 3-60 para 2-70 (CA = BDA + MEA + RR).
    "CA":  _combat_assessment_SPEC,
    # TSA ARCHIVED 2026-06-08 — theater/J-2 product, not corps-authored.
    # See templates/products/_archived/target_system_analysis.py + README.md.
    # JP 3-60 + CJCSI 3122.06 / 3160.01D legal/ROE pre-strike gates.
    "NSL": _no_strike_list_SPEC,
    "RTL": _restricted_target_list_SPEC,
    "CDE": _collateral_damage_estimate_SPEC,
    # Tier 1 single-INT analytical products.
    # SIGINT cell — KLIEGLIGHT is the perishable atomic (event-driven from
    # Cougaar KG poller). SIGSUM is the end-of-cycle rollup.
    "SIGSUM":               _sigsum_SPEC,
    "KLIEGLIGHT":           _kliegl_light_SPEC,
    # GEOINT cell — terrain-derived (CCM / LOS). IIR (GEOINT) and RECCEXREP
    # are USMTF message records in the KG, not analyst-authored documents.
    "CCM":                  _ccm_SPEC,
    "LOS":                  _los_SPEC,
    # HUMINT cell — HUMINTSUM rollup only; HUMINT IIR records live in the KG.
    "HUMINTSUM":            _humintsum_SPEC,
    # OSINT cell — OSIR is the per-event single-source report (FM 2-0 §1-82).
    # One OSIR per IDXOpenSourceReport row; handlers/osir_autofire.py fires
    # on each new cougaar / scenario-fixture OSINT row mirroring KLIEGLIGHT.
    # The rollup happens in INTSUM (multi-INT), not in a separate OSINT-only
    # product — FM 2-0 does not define an "OSINT summary".
    "OSIR":                 _osir_SPEC,
    # Tier 2 fused additions surfaced by FINAL_DOCTRINE_AUDIT + per-target
    # audit-trail product.
    "ICSM":                 _icsm_SPEC,
    "DSM":                  _dsm_SPEC,
    # XLSX spin-off siblings of hybrid products. Each is its own standalone
    # generation; parent products (CCA / CA / Event Template / Decision
    # Support Template / Threat Overlay) continue to render their existing
    # DOCX/PPTX outputs untouched.
    "CCA-Matrix":                _cca_matrix_SPEC,
    "CA-Engagements":            _ca_engagements_SPEC,
    "Event-Matrix":              _event_matrix_SPEC,
    "DST-Matrix":                _dst_matrix_SPEC,
    "Threat-Description-Table":  _threat_description_table_SPEC,
}

PRODUCTS = list(PRODUCT_SCHEMAS.keys())

__all__ = ["PRODUCT_SCHEMAS", "PRODUCTS"]
