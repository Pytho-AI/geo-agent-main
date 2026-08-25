"""
MIL-STD-2525E SIDC construction — geo-agent owns symbol coding.

Consumers (pytho-app sync producers, scenario ingest, NL agent, manual
API callers) send unit SEMANTICS (affiliation, echelon, category); this
module turns them into a renderable 2525E SIDC. A row that already
carries a SIDC keeps it untouched — upstream knowledge graphs may
encode finer branch detail (howitzer vs MLRS) than the category token
retains, and legacy 2525C letter codes still render.

Branch codes verified against backend/app/data/milstd/2525E 10
land-unit.json (imported from the MIL-STD-2525E tables by
backend/scripts/import_milstd_2525e.py).
"""

from typing import Optional

from app.constants.types import SIDC_AFFILIATION, SIDC_ECHELON

# FM 3-60 category token -> representative 2525E Land Unit entity code.
# The category is a coarser statement than a full branch, so each maps
# to the most generic icon of its family.
ENTITY_CODE_FOR_CATEGORY = {
    "command_and_control": "110000",                    # Command and Control
    "fire_support": "130300",                           # Fires > Field Artillery
    "air_defense_artillery": "130100",                  # Fires > Air Defense
    "maneuver": "121000",                               # Movement and Maneuver > Combined Arms
    "engineer": "140700",                               # Protection > Engineer
    "reconnaissance_and_surveillance": "121300",        # M&M > Reconnaissance/Cavalry/Scout
    "cyberspace_electromagnetic_activities": "150500",  # Intelligence > Electronic Warfare
    "sustainment": "160200",                            # Sustainment > All Classes of Supply
    "lift": "120600",                                   # M&M > Army Aviation/Rotary Wing
    "chemical_biological_radiological_nuclear": "140100",  # Protection > CBRN Defense
    "information": "110400",                            # C2 > Information Operations
    "line_of_communication": "163600",                  # Sustainment > Transportation
}

# Tolerant echelon lookup: sync rows carry "Battalion"; analyst tools
# and roll-up state use the doctrinal abbreviations.
_ECHELON_ALIASES = {
    "PLT": "Platoon", "CO": "Company", "TRP": "Company", "BTRY": "Company",
    "BN": "Battalion", "SQDN": "Battalion", "RGT": "Regiment",
    "BDE": "Brigade", "BCT": "Brigade", "DIV": "Division",
}


def _echelon_code(echelon: Optional[str]) -> str:
    if not echelon:
        return "00"
    name = str(echelon).strip()
    canonical = (
        name if name in SIDC_ECHELON
        else _ECHELON_ALIASES.get(name.upper(), name.title())
    )
    return SIDC_ECHELON.get(canonical, "00")


def build_land_unit_sidc(
    affiliation: Optional[str],
    echelon: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """20-character 2525E SIDC (symbol set 10) from unit semantics.

    Version 13 = MIL-STD-2525E (milsymbol 3.x renders it natively).
    Unknown category -> 000000 (plain frame): an unclassified unit
    renders as a frame, never as a wrong branch icon.
    """
    identity = SIDC_AFFILIATION.get(str(affiliation or "").strip().title(), "1")
    entity_code = ENTITY_CODE_FOR_CATEGORY.get(
        str(category or "").strip().lower(), "000000")
    # version(2)=13, context(1)=0, identity(1), set(2)=10, status(1)=0,
    # hqtfd(1)=0, echelon(2), entity(6), mod1(2)=00, mod2(2)=00 — 20 chars.
    return f"130{identity}1000{_echelon_code(echelon)}{entity_code}0000"


# ── 2525C letter → 2525E numeric conversion ─────────────────────────
# ONE symbol format lives in this system: 2525E numeric. Letters are
# converted at the ingest boundary (sync/create/update) and by the
# one-time migration (backend/scripts/migrate_sidcs_to_2525e.py);
# interior code (renderers, legend, filters) never sees them.
#
# Function-ID table: every ID observed in production data, named from
# the MIL-STD-2525C ground-unit table (spatialillusions mil-std-2525)
# and mapped to the E land-unit entity with the same meaning —
# verified against backend/app/data/milstd/2525E 10 land-unit.json.
_LETTER_FN_TO_E_ENTITY = {
    # fn ID: entity(6) or entity+mod1+mod2(10). 2525E moved weapon
    # specifics into the modifier digits (MRL = mod1 41, Target
    # Acquisition = mod1 67, Construction = mod1 12, rotary Attack /
    # Utility = mod2 54 / 56) — conversions carry them so a rocket
    # battalion keeps its rocket glyph. E has NO howitzer modifier at
    # unit level: howitzer units are Field Artillery, per the standard.
    "UCFHE-": "130300",      # FA howitzer self-propelled -> Field Artillery
    "UCFT--": "1303006700",  # FA target acquisition      -> FA + TA mod
    "UCFR--": "1303004100",  # FA rocket                  -> FA + MRL mod
    "UCFRM-": "1303004100",  # FA multiple rocket launcher-> FA + MRL mod
    "UCFRMR": "1303004100",  # FA MRL truck               -> FA + MRL mod
    "UCFRL-": "1303004100",  # FA rocket light            -> FA + MRL mod
    "UCIM--": "121104",      # Infantry motorized         -> Infantry > Motorized
    "UCIZ--": "121102",      # Infantry mechanized        -> Infantry > Armored/Mech/Tracked
    "UCII--": "121105",      # Infantry fighting vehicle  -> Infantry > IFV
    "UCIA--": "121100",      # Infantry airborne          -> Infantry
    "UCI---": "121100",      # Infantry
    "UCAT--": "120500",      # Armor tracked              -> Armor/Mechanized
    "UCATW-": "120502",      # Armor tracked amphibious   -> Armor > Amphibious
    "UCA---": "120500",      # Armor
    "UCAA--": "120400",      # Antiarmor                  -> Antitank/Antiarmor
    "UCDML-": "130102",      # ADA missile light          -> Air Defense > Missile
    "UCDM--": "130102",      # ADA missile                -> Air Defense > Missile
    "UCDS--": "130102",      # ADA short range            -> Air Defense > Missile
    "UCDC--": "130100",      # ADA composite              -> Air Defense
    "UCEC--": "140700",      # Engineer combat            -> Engineer
    "UCEN--": "1407001200",  # Engineer construction      -> Engineer + Construction mod
    "UCRVA-": "120501",      # Recon cavalry armored      -> Armor > Recon/Cav/Scout
    "UCRR--": "121300",      # Recon (marine)             -> Recon/Cavalry/Scout
    "UCVRA-": "1206000054",  # Attack rotary wing         -> Army Aviation + Attack mod
    "UCVR--": "120600",      # Rotary wing                -> Army Aviation
    "UCVRU-": "1206000056",  # Utility rotary wing        -> Army Aviation + Utility mod
    "UCVA--": "1206000054",  # Aviation (attack)          -> Army Aviation + Attack mod
    "UCS---": "141700",      # Internal security forces   -> Security
    "UCSS--": "141700",      # Internal security (var.)   -> Security
    "UCSM--": "141702",      # ISF wheeled mechanized     -> Security > Motorized
    "UUS---": "111000",      # Signal
    "UUA---": "140100",      # CBRN
    "UUL---": "141200",      # Law enforcement            -> Military Police
    "UUMA--": "151000",      # MI aerial exploitation     -> Military Intelligence
    "UUMSE-": "150500",      # Electronic warfare
    "US----": "160600",      # Combat service support
    "UST---": "163600",      # Transportation
    "USX---": "161100",      # Maintenance
    "USM---": "161300",      # Medical
    "USS3--": "162000",      # Supply class III           -> NATO Supply Class III
    "U-----": "000000",      # Generic unit -> plain frame
}
# Family-prefix fallback for letter IDs outside the observed set —
# longest prefix wins.
_LETTER_PREFIX_TO_E_ENTITY = [
    ("UCD", "130100"), ("UCF", "130300"), ("UCE", "140700"),
    ("UCR", "121300"), ("UCV", "120600"), ("UCA", "120500"),
    ("UCI", "121100"), ("UCS", "141700"), ("UUS", "111000"),
    ("UUE", "150500"), ("UUM", "151000"), ("UUA", "140100"),
    ("UUL", "141200"), ("US", "160600"), ("UC", "121000"),
    ("UU", "110000"), ("U", "000000"),
]
_LETTER_AFFILIATION = {
    "F": "3", "A": "3", "M": "3",          # friend / assumed friend / exercise
    "H": "6", "J": "6", "K": "6", "S": "6", # hostile / joker / faker / suspect
    "N": "4", "L": "4",                    # neutral / exercise neutral
}
# 2525C size code (position 12) -> E echelon amplifier.
_LETTER_ECHELON = {
    "A": "11", "B": "12", "C": "13", "D": "14", "E": "15", "F": "16",
    "G": "17", "H": "18", "I": "21", "J": "22", "K": "23", "L": "24",
    "M": "25", "N": "26",
}


def to_2525e_sidc(sidc: Optional[str]) -> Optional[str]:
    """Normalize any SIDC to 2525E numeric. None/empty passes through.

    - 2525E numeric: unchanged.
    - Older numeric versions (10/11 = 2525D era): version bumped to 13;
      the 20-char layout is identical.
    - 2525C 15-char letters: converted via the function-ID table above
      (affiliation, status, echelon preserved; country/order dropped).
    - Anything unrecognized: returned as-is (caller decides) — but the
      migration script reports these so they never linger silently.
    """
    if not sidc:
        return sidc
    s = str(sidc).strip().upper()
    # Numeric: 20 = the standard SIDC; 30 = the 2525E long form with
    # trailing originator fields (mil-sym-ts emits these) — the first
    # 20 digits ARE the standard SIDC, so the canonical stored form
    # keeps them and drops the tail.
    if s.isdigit() and len(s) in (20, 30):
        s = s[:20]
        return s if s.startswith("13") else "13" + s[2:]
    # Letters: 15 = well-formed 2525C; shorter S*G* strings are
    # truncated legacy rows — function ID is still at 4:10, echelon is
    # unrecoverable.
    if len(s) >= 10 and s[0] == "S" and s[2] == "G":
        fn = s[4:10].ljust(6, "-")
        entity = _LETTER_FN_TO_E_ENTITY.get(fn)
        if entity is None:
            for prefix, code in _LETTER_PREFIX_TO_E_ENTITY:
                if fn.startswith(prefix):
                    entity = code
                    break
        if entity is None:
            entity = "000000"
        mods = entity[6:] if len(entity) == 10 else "0000"
        entity = entity[:6]
        identity = _LETTER_AFFILIATION.get(s[1], "1")
        status = "1" if s[3] == "A" else "0"
        echelon = _LETTER_ECHELON.get(s[11], "00") if len(s) == 15 else "00"
        return f"130{identity}10{status}0{echelon}{entity}{mods}"
    return sidc


def ensure_mil_unit_sidc(attrs: dict) -> dict:
    """Normalize or build attrs.sidc for a mil_unit row.

    Mutates and returns attrs. A provided SIDC is normalized to 2525E
    numeric (letters converted, old numeric versions bumped); a missing
    one is built from affiliation/echelon/category.
    """
    if attrs.get("sidc"):
        attrs["sidc"] = to_2525e_sidc(attrs["sidc"])
    else:
        attrs["sidc"] = build_land_unit_sidc(
            attrs.get("affiliation"),
            attrs.get("echelon"),
            attrs.get("category"),
        )
    return attrs
