"""Symbol composition for entity-graph nodes — the ONE place a SIDC is
built for the record (design decision 11: composed at paint time, never
stored, never parsed back, never in an API contract).

Branches (decision 21):
- analyst override columns set -> compose from them verbatim;
- equipment instance (weg_id set) -> set 15, catalog symbol columns;
- fixed type (entity_types.is_fixed) -> set 20, type-row mapping;
- movable unit -> set 10, dominant holdings class + echelon.
Unknown anything -> plain frame, never a wrong branch.
"""
from typing import Optional

from app.utils.sidc import SIDC_AFFILIATION, _echelon_code

# Dominant-holdings-class -> set-10 land-unit entity(+mods). Codes are
# the ones already verified against "2525E 10 land-unit.json" in
# app.utils.sidc's letter-conversion table.
_CLASS_TO_UNIT_ENTITY = {
    "armor": ("120500", "00", "00"),
    "ifv": ("121105", "00", "00"),
    "apc": ("121102", "00", "00"),
    "indirect_fire": ("130300", "00", "00"),
    "mlrs": ("130300", "41", "00"),
    "ballistic_missile": ("130700", "00", "00"),
    "cruise_missile": ("130700", "00", "00"),
    "ada": ("130102", "00", "00"),
    "antitank": ("120400", "00", "00"),
    "radar": ("130300", "67", "00"),
    "ew": ("150500", "00", "00"),
    "command_post": ("110000", "00", "00"),
    "communications": ("111000", "00", "00"),
    "reconnaissance": ("121300", "00", "00"),
    "mine": ("140700", "00", "00"),
    "engineer": ("140700", "00", "00"),
    "rotary": ("120600", "00", "00"),
    "logistics": ("160000", "00", "00"),
}

# Unit BRANCH / warfighting function -> set-10 land-unit entity (main icon
# inside the frame). Codes verified against "2525E 10 land-unit.json".
# Ordered specific-first; first keyword hit in the name+unit_type wins.
# This is what stops a unit from rendering as an empty affiliation frame:
# a narrative OOB gives no equipment holdings, so the dominant-class path
# is empty and the branch must come from what the unit IS called.
# Ordered specific-first; first hit wins. Cavalry, anti-tank, and
# armor sit ABOVE the broad mechanized/motorized rows so a compound
# descriptor like unit_type "Armor /Mechanized" resolves to its
# primary arm (armor) instead of the modifier. Anti-tank stays above
# armor so "Anti-Tank" never matches the bare "tank" token; cavalry
# stays above armor so "Armored Cavalry" reads as reconnaissance.
_UNIT_BRANCH: list = [
    (("combined arms",), "121000"),
    (("infantry fighting vehicle", "ifv"), "121105"),
    (("cavalry", "reconnaissance", "recon", "scout"), "121300"),
    (("anti-tank", "antitank", "anti tank", "antiarmor", "anti-armor"), "120400"),
    (("armor", "armour", "armored", "armoured", "tank"), "120500"),
    (("mechanized infantry", "mechanised infantry", "mechanized rifle", "mech infantry", "mechanized", "mechanised"), "121102"),
    (("motor rifle", "motorized rifle", "motorised rifle", "motorized infantry", "motorised infantry", "motorized", "motorised"), "121104"),
    (("air assault",), "120100"),
    (("airborne", "parachute", "paratroop"), "121100"),
    (("special forces", "special purpose", "spetsnaz", "commando", "ranger", "special operations", " sof "), "121700"),
    (("air defense", "air defence", "anti-aircraft", "antiaircraft", " sam ", "surface-to-air", "air and missile defense", "air and missile defence"), "130100"),
    (("electronic warfare", "radio electronic", " ew "), "150500"),
    (("missile", "ssm", "iskander", "ballistic"), "130700"),
    (("field artillery", "artillery", "howitzer", "fires", "rocket", "mlrs"), "130300"),
    (("aviation", "helicopter", "rotary"), "120600"),
    (("signal", "communications"), "111000"),
    (("engineer", "sapper"), "140700"),
    (("chemical", "cbrn", "nbc", "biological"), "140100"),
    (("transportation", "transport"), "163600"),
    (("sustainment", "logistics", "supply", "quartermaster", "maintenance", "medical", "service support", "support"), "160000"),
    (("infantry", "rifle"), "121100"),
]


def _unit_branch(name, unit_type) -> Optional[str]:
    # Match the unit's OWN designation only — names are written
    # "Designation, Parent, Grandparent", and matching the full string
    # let the PARENT's branch hijack the icon ("Air Defense Regiment,
    # 83rd Motorized Rifle Division" hit 'motorized' before 'air
    # defense' and painted as motorized rifle; every subordinate of a
    # mech/motorized formation got its parent's icon).
    own = str(name or "").split(",")[0]
    text = f" {own} {(unit_type or '')} ".lower()
    for keys, code in _UNIT_BRANCH:
        if any(k in text for k in keys):
            return code
    return None


def _compose(identity: str, symbol_set: str, echelon2: str,
             entity6: str, mod1: str, mod2: str, hq_tf: str = "0",
             status: str = "0") -> str:
    # version(2)=13, context(1)=0, identity(1), set(2), status(1),
    # hqtfd(1), echelon(2), entity(6), mod1(2), mod2(2) — 20 chars.
    # status: 0 present, 1 planned/anticipated — an ANTICIPATED unit
    # (position templated by the doctrinal disposition, or derived)
    # draws the doctrinal DASHED frame; a stated position draws solid.
    # hqtfd: 0 none, 2 headquarters, 4 task force, 6 task-force HQ —
    # milsymbol draws the HQ staff flag from it. A formation whose
    # command post is the entity on the map (corps/army HQ with its
    # subordinates elsewhere) carries the HQ indicator so it reads as a
    # headquarters, not a whole formation sitting in one grid.
    return (f"130{identity}{symbol_set}{status}{hq_tf}"
            f"{echelon2}{entity6}{mod1}{mod2}")


def _hq_tf_indicator(node) -> str:
    """HQ/TF amplifier from the unit's role. A command-and-control
    formation (its CP is what sits on the map) → headquarters; a task
    force → TF; both → task-force HQ."""
    t = f"{(node.name or '')} {(node.unit_type or '')}".lower()
    is_tf = ("task force" in t or t.strip().startswith("tf ")
             or " tf " in t)
    # Explicit HQ words apply at any echelon. Formation-title cues
    # ("combined arms army", "corps") apply ONLY when the node ITSELF
    # is that echelon — a subordinate that carries its parent army's
    # name ("7th Combined Arms Army Electronic Warfare Companies") is
    # not a headquarters.
    # An HQ is a SEPARATE ELEMENT. A formation is never its own HQ —
    # only units that ARE headquarters elements (by name or C2
    # category) carry the staff indicator (user ruling 2026-07-20;
    # the old corps/army formation-title branch is dead).
    is_hq = (str(node.category or "") == "command_and_control"
             or any(w in t for w in (
                 "headquarters", " hq", "command post", " cp",
                 "operations center")))
    if is_tf and is_hq:
        return "6"
    if is_tf:
        return "4"
    if is_hq:
        return "2"
    return "0"


def compose_node_sidc(
    node,
    entity_type_row,
    dominant_class: Optional[str] = None,
    catalog_row=None,
    anticipated: bool = False,
) -> str:
    """node: GraphNode; entity_type_row: EntityType; dominant_class:
    the holdings class with the largest count (units only); catalog_row:
    WegEquipment for equipment instances; anticipated: the governing
    position is templated (doctrinal disposition) or derived — the
    symbol frame draws dashed."""
    identity = SIDC_AFFILIATION.get(str(node.affiliation or "").strip().title(), "1")
    status = "1" if anticipated else "0"

    # Analyst picker override wins wholesale.
    if node.symbol_set and node.symbol_entity_code:
        return _compose(
            identity, node.symbol_set, _echelon_code(node.echelon),
            node.symbol_entity_code.ljust(6, "0")[:6],
            (node.symbol_mod1 or "00")[:2], (node.symbol_mod2 or "00")[:2],
            status=status)

    # Equipment instance: set 15, symbol from its catalog row.
    if node.weg_id:
        entity = (catalog_row.symbol_entity_code if catalog_row and catalog_row.symbol_entity_code else "000000")
        m1 = (catalog_row.symbol_mod1 if catalog_row and catalog_row.symbol_mod1 else "00")
        m2 = (catalog_row.symbol_mod2 if catalog_row and catalog_row.symbol_mod2 else "00")
        return _compose(identity, "15", "00", entity.ljust(6, "0")[:6], m1, m2,
                        status=status)

    # Fixed infrastructure: set 20 from the type row's mapping.
    if entity_type_row is not None and entity_type_row.is_fixed:
        if entity_type_row.symbol_set and entity_type_row.symbol_entity_code:
            return _compose(
                identity, entity_type_row.symbol_set, "00",
                entity_type_row.symbol_entity_code.ljust(6, "0")[:6],
                "00", "00", status=status)
        return _compose(identity, "20", "00", "000000", "00", "00",
                        status=status)

    # Movable unit: set 10. BOTH signals feed the symbol, not one or the
    # other. The unit's NAME/type gives its branch (authoritative for its
    # designated role — a Field Artillery Brigade is artillery) and, for
    # infantry, the mechanized/motorized/IFV variant. Its dominant
    # EQUIPMENT class (fed by force-template holdings) confirms the branch,
    # specialises a generic infantry icon (name says "infantry", the IFVs
    # make it an IFV icon), and supplies the mobility/type MODIFIERS. Name
    # leads the main icon; equipment specialises or fills it; equipment
    # always carries its modifiers. A combined-arms icon is the last
    # resort so a maneuver formation is never a bare frame.
    name_entity = _unit_branch(node.name, node.unit_type)
    eq_entity, m1, m2 = _CLASS_TO_UNIT_ENTITY.get(dominant_class or "", (None, "00", "00"))
    if name_entity == "121100" and eq_entity in ("121105", "121102", "121104"):
        entity = eq_entity                      # equipment specialises generic infantry
    else:
        entity = name_entity or (eq_entity if eq_entity and eq_entity != "000000" else None) or "121000"
    return _compose(identity, "10", _echelon_code(node.echelon), entity, m1, m2,
                    hq_tf=_hq_tf_indicator(node), status=status)
