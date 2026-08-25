"""Reference-walk derivation — templated subordinates and default WEG
holdings APPEAR AT RENDER, derived from the reference catalog, never written
into the project (oob-design S15 step 7; tool-surface-consolidation invariant
4 + S15 step 8).

A template body is ordinary graph_nodes / graph_holdings rows scoped by
`template_id` with NO project and NO maps row (oob-design S3.1/S9.435-444).
A project unit that carries `template_key` therefore has a doctrinal subtree
and an authorized equipment table available by reference. Those defaults are
NOT project facts: the week-1 documents never state a battery's vehicle count,
so under invariant 4 they can never become provenance-bearing project
entities. They are reference knowledge, and reference knowledge is projected —
exactly like the SIDC composed at paint time and the parent centroid derived
from placed children (decision 11, "derived at paint time like every other
derivation").

What this module returns is therefore virtual: derived holdings keyed to the
real project node, and derived subordinate units with synthetic ids that never
enter graph_nodes. Each carries `derived_from_template` so the analyst sees
what is doctrine and what is recorded, and every derived unit paints with the
anticipated (dashed) frame its templated position warrants.

Suppression rules — the record always wins over doctrine:
- A unit whose OWN holdings are recorded gets no derived holdings (the source
  stated its equipment; `holdings_complete` semantics).
- A derived subordinate whose name matches a recorded project unit is dropped
  (that subordinate is real and already painted).

Suppression is PER SUBORDINATE, never per formation. An earlier version
dropped a formation's whole doctrinal subtree as soon as ONE child was
recorded, which hid five of six troops the moment a headquarters troop was
extracted. The name check above is what keeps the record authoritative; a
subordinate the source never mentioned is exactly the doctrine this walk
exists to show.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import ForceTemplate, GraphHolding, GraphNode

log = logging.getLogger(__name__)


def _fold(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


# Multiplicity marker anywhere in the trailing parenthetical: "(x3)",
# "(x2-5, task organized)" — count, optional range, optional qualifier.
# The range keeps its LOWER bound (the doctrinally guaranteed force; the
# upper bound is task organization the source does not commit to).
_MULTIPLICITY = re.compile(
    r"\s*\(\s*(?:x|×)\s*(\d+)(?:\s*[-–]\s*\d+)?\s*(?:,[^)]*)?\)\s*$", re.I)
# A bare variable marker — "(x, assigned)", "(x)" — states that copies
# exist without stating how many. Nothing paintable can be derived from
# it; the row is skipped rather than fabricating a count.
_MULTIPLICITY_UNSTATED = re.compile(
    r"\s*\(\s*(?:x|×)\s*(?:,[^)]*)?\)\s*$", re.I)
# A template may instead number its copies inline — "Combat Squadron (1)",
# "Combat Squadron (2)". That is one unit each, already numbered.
_INSTANCE_NO = re.compile(r"^(.*?)\s*\((\d{1,2})\)\s*$")
_ORDINALS = ("1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th",
             "10th", "11th", "12th")


def expand_multiplicity(name: str) -> List[str]:
    """A template body encodes repeated subunits in the name — "Tank Battalion
    (x3)" is THREE tank battalions, not one unit called "(x3)". Expand it into
    individually numbered units ("1st Tank Battalion", ...) so the ORBAT and
    the placard show the doctrinal force, not a multiplicity token.

    "(x2-5, task organized)" expands its stated minimum. "(x, assigned)"
    states no count at all and expands to NOTHING — a fabricated copy of
    an unstated multiplicity is not doctrine. A name without any marker
    returns itself unchanged.
    """
    if _MULTIPLICITY_UNSTATED.search(name or ""):
        return []
    m = _MULTIPLICITY.search(name or "")
    if not m:
        inst = _INSTANCE_NO.match(name or "")
        if inst:
            base, n = inst.group(1).strip(), int(inst.group(2))
            if 1 <= n <= len(_ORDINALS):
                return [f"{_ORDINALS[n - 1]} {base}"]
        return [name]
    base = _MULTIPLICITY.sub("", name).strip()
    n = int(m.group(1))
    if n < 1 or n > 12:
        return [base]
    if n == 1:
        return [base]
    return [f"{_ORDINALS[i]} {base}" for i in range(n)]


# Paint-time arraying lives in the disposition engine's pure core
# (plan_disposition in graph_ingest/disposition.py) — the walk projects
# THE SAME posture-shaped, role-placed, threat-facing doctrinal layout
# the instantiate-time engine writes, never a second layout dialect.
# map_state drives it per painted parent.


async def load_template_bodies(
    db: AsyncSession, template_keys: set,
) -> Dict[str, dict]:
    """Load each template's body (its unit subtree + authorized holdings)
    from the reference scope. Returns {template_key: {"root": node|None,
    "units": [nodes], "holdings": {node_id: [(GraphHolding, WegEquipment)]}}}.

    Reference read only — these rows have template_id set and project_id
    NULL, so they are invisible to every project query.
    """
    if not template_keys:
        return {}
    from app.models.reference import WegEquipment

    tpls = (await db.execute(
        select(ForceTemplate).where(ForceTemplate.key.in_(template_keys))
    )).scalars().all()
    if not tpls:
        return {}
    by_id = {t.id: t for t in tpls}
    nodes = (await db.execute(
        select(GraphNode).where(GraphNode.template_id.in_(list(by_id))))
    ).scalars().all()
    node_ids = [n.id for n in nodes]
    holds: Dict[UUID, list] = {}
    if node_ids:
        for h, cat in (await db.execute(
            select(GraphHolding, WegEquipment)
            .outerjoin(WegEquipment, WegEquipment.weg_id == GraphHolding.weg_id)
            .where(GraphHolding.node_id.in_(node_ids))
        )).all():
            holds.setdefault(h.node_id, []).append((h, cat))

    out: Dict[str, dict] = {}
    for tpl in tpls:
        body = [n for n in nodes if n.template_id == tpl.id]
        # The template root is the body node with no parent inside the body
        # (or, defensively, the one whose echelon matches the header).
        ids = {n.id for n in body}
        roots = [n for n in body
                 if not n.organic_parent_id or n.organic_parent_id not in ids]
        out[tpl.key] = {
            "root": roots[0] if roots else None,
            "units": body,
            "holdings": holds,
        }
    return out


def derive_for_unit(
    node: GraphNode,
    body: dict,
    *,
    has_own_holdings: bool,
    has_own_children: bool,
    recorded: Dict[str, dict],
) -> Tuple[Dict[str, list], list]:
    """Derive one project unit's virtual holdings and subordinates from its
    template body. Returns (derived_holdings, derived_units).

    derived_holdings: {node_id_str: [(GraphHolding, WegEquipment|None)]} —
    shaped exactly like real holdings rows so the paint loop's rollup, fan,
    and detection-ring code needs no special case. Keys are THIS node and any
    RECORDED subordinate whose doctrinal twin carried equipment (the record
    wins on structure, but a recorded unit with no recorded equipment still
    has its doctrinal table — dropping it blanked exactly the extracted,
    named units the analyst clicks first).

    An unresolved holding (no WEG match, catalog None) is CARRIED, not
    dropped: the source stated the system by name, and hiding it told the
    analyst the unit had no equipment at all. It lists by nomenclature and
    simply draws no range ring.

    derived_units: [dict] describing a virtual subordinate.
    """
    root = body.get("root")
    holds_by_node = body.get("holdings") or {}
    derived_holdings: Dict[str, list] = {}
    derived_units: list = []
    nid = str(node.id)

    # 1. Root holdings -> this unit's authorized equipment table.
    if not has_own_holdings and root is not None:
        rows = list(holds_by_node.get(root.id, []))
        if rows:
            derived_holdings[nid] = rows

    # 2. The subtree -> virtual subordinates. Recorded subordinates are
    # matched INDIVIDUALLY by the name check below; a formation that had one
    # child extracted still shows the rest of its doctrinal structure. A
    # match suppresses the doctrinal TWIN, transfers its equipment table to
    # the recorded unit (when the record states none), and re-parents the
    # twin's own doctrinal children onto the recorded unit so the deeper
    # structure survives extraction.
    if root is not None:
        units = body.get("units") or []
        by_parent: Dict[UUID, list] = {}
        for u in units:
            if u.organic_parent_id:
                by_parent.setdefault(u.organic_parent_id, []).append(u)
        # Breadth-first from the root; keep the template's own hierarchy so a
        # regiment's battalions nest under it, not under the division.
        stack = [(c, nid) for c in by_parent.get(root.id, [])]
        while stack:
            tnode, parent_ref = stack.pop(0)
            names = expand_multiplicity(tnode.name)
            holds = list(holds_by_node.get(tnode.id, []))
            for idx, uname in enumerate(names):
                rec = recorded.get(_fold(uname))
                if rec is not None:
                    # A real extracted project unit — already painted from
                    # the record; doctrine must not double it.
                    if holds and not rec["has_holdings"]:
                        derived_holdings.setdefault(
                            rec["id"], []).extend(holds)
                    if idx == 0:
                        stack.extend((c, rec["id"])
                                     for c in by_parent.get(tnode.id, []))
                    continue
                vid = (f"tpl:{node.id}:{tnode.id}"
                       + (f":{idx}" if len(names) > 1 else ""))
                derived_units.append({
                    "virtual_id": vid,
                    "parent_ref": parent_ref,
                    "name": uname,
                    "echelon": tnode.echelon,
                    "unit_type": tnode.unit_type,
                    "entity_type": tnode.entity_type or "unit",
                    "affiliation": node.affiliation,
                    "category": tnode.category,
                    "symbol_set": tnode.symbol_set,
                    "symbol_entity_code": tnode.symbol_entity_code,
                    "symbol_mod1": tnode.symbol_mod1,
                    "symbol_mod2": tnode.symbol_mod2,
                    # Each instance carries the template row's equipment: the
                    # holdings are ONE battalion's table, and (x3) means three
                    # such battalions.
                    "holdings": holds,
                })
                # Deeper template levels nest under the FIRST instance only —
                # the body states one subtree, not one per copy.
                if idx == 0:
                    stack.extend((c, vid) for c in by_parent.get(tnode.id, []))
    return derived_holdings, derived_units


async def derive_reference_walk(
    db: AsyncSession,
    pairs: List[tuple],
    by_node: Dict[str, list],
    children: Dict[str, list],
) -> Tuple[Dict[str, list], List[dict]]:
    """The whole reference walk for one map_state call.

    pairs: [(GraphNode, geojson_or_None)] — every project node.
    by_node: recorded holdings, {node_id_str: [(GraphHolding, WegEquipment)]}.
    children: recorded organic children, {parent_id_str: [GraphNode]}.

    Returns (derived_holdings_by_node, derived_units). Fails OPEN: a template
    read problem must never blank the laydown.
    """
    try:
        keys = {n.template_key for n, _ in pairs if n.template_key}
        if not keys:
            return {}, []
        bodies = await load_template_bodies(db, keys)
        if not bodies:
            return {}, []
        recorded = {_fold(n.name): {"id": str(n.id),
                                    "has_holdings": bool(by_node.get(str(n.id)))}
                    for n, _ in pairs}
        derived_holdings: Dict[str, list] = {}
        derived_units: List[dict] = []
        for n, _ in pairs:
            body = bodies.get(n.template_key or "")
            if not body:
                continue
            nid = str(n.id)
            dh, du = derive_for_unit(
                n, body,
                has_own_holdings=bool(by_node.get(nid)),
                has_own_children=bool(children.get(nid)),
                recorded=recorded)
            for k, rows in dh.items():
                derived_holdings.setdefault(k, []).extend(rows)
            derived_units.extend(du)
        return derived_holdings, derived_units
    except Exception:
        log.warning("reference walk failed open", exc_info=True)
        return {}, []
