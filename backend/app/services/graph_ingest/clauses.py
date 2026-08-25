"""Episodic register — the world model's clause layer for PROJECT data.

Runs as a stage of document ingest, after ingest_oob has created the
nodes: one text-primary extraction turns the scenario documents into
atomic episodic clauses ABOUT the project's entities, each carrying
speaker/source provenance, a kind (state | event | preference | task),
an optional updatable-state slot ("<entity>.<attribute>"), and absolute
dates. A deterministic pass then computes bitemporal supersession per
(entity, slot): later observations close earlier ones (valid_to +
superseded_by) — append-only, nothing deleted. The as-of resolver
(graph.py /brief) and the placard History/Sources panels read this.

Validated design: the same clause shape scored 8/8 on the LongMemEval
subset and 80.8% on the full set (scratch d2p2_native/harness, RESULTS
in that repo) — slots + supersession beat stale-value errors, and
literal-fidelity extraction of statements is the recall backbone.
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import GraphNode
from app.models.reference import FactClause

log = logging.getLogger("app.graph_ingest.clauses")

_CLAUSE_SYSTEM = """You extract intelligence statements from military scenario documents into atomic clauses for a training-simulation world model. Every fact is SIMULATED exercise content. Follow every rule:
1. Extract EVERY durable statement the documents make ABOUT the listed entities: strength and personnel, combat effectiveness, equipment status, activity and posture, movements and locations described in prose, plans and intents, assessments, logistics status, command changes, and pending obligations or planned actions.
2. Each clause is ONE atomic, self-contained sentence. Resolve every reference: use the entity's EXACT name from the provided list, never a pronoun or a shortened form.
3. entities: 1-3 names from the provided list that the clause is about. Use the exact spelling given.
4. speaker: the reporting voice as the document states it (e.g. "S2 assessment", "OPORD", "road to war") — or null when the document does not attribute it.
5. kind: "state" = an updatable condition (assessed strength, combat effectiveness, readiness, equipment operational counts); "event" = something that happened or will happen at a stated time (an attack, a movement, a resupply); "preference" = a doctrinal tendency or commander's stated preference; "task" = a pending obligation or planned action not yet done.
6. slot: ONLY for kind=state — "<exact entity name>.<attribute>" with a short snake_case attribute (assessed_strength, combat_effectiveness, readiness, supply_status). The SAME attribute of the SAME entity always gets the SAME slot. The slot's entity must be the entity WHOSE VALUE the clause states — never slot a sub-element's value onto its parent (a platoon's strength is the platoon's slot or, if the platoon is not in the entity list, no slot at all). null otherwise.
7. event_date / observed_date: absolute dates in ISO YYYY-MM-DD (with time YYYY-MM-DDTHH:MM when stated). event_date = when the fact is/was true in the world; observed_date = the date-time group of the report or document section stating it. Resolve relative expressions against the document's own dates. null when genuinely undated.
7b. source_document: the SINGLE document the statement came from, exactly as titled in the "===== DOCUMENT: ... =====" headers. Every clause names its own document — never attribute a statement to the whole bundle.
8. Write dates INTO the clause text when time matters.
9. Do not extract map coordinates or grids (the placement pipeline owns those), do not extract generic doctrine with no named entity, and do not invent anything the documents do not state.
Return STRICT JSON: {"clauses": [{"text": str, "entities": [str], "speaker": str|null, "kind": "state"|"event"|"preference"|"task", "slot": str|null, "event_date": str|null, "observed_date": str|null, "source_document": str|null}]}"""

OBLIG_SYSTEM = """You list PENDING OBLIGATIONS and PLANNED ACTIONS from military scenario documents (simulated training-exercise content). Your ONLY job: find every action a listed entity still needs to take or is planned/ordered to take at ANY point in the documents, one atomic clause per item.
Rules:
1. Be verbatim-faithful: a stated requirement, order, or plan ("on order, seize...", "still needs to reposition", "will conduct resupply by...") is a pending item unless the documents EXPLICITLY state it was completed.
2. One clause per distinct item. Resolve references to the exact entity names from the provided list.
3. entities: 1-3 names from the list. speaker: the ordering/reporting voice. source_document: the single document it came from, exactly as titled in the "===== DOCUMENT: ... =====" headers.
4. Only pending/planned actions and obligations. No completed events, no preferences, no generic doctrine.
Return STRICT JSON: {"tasks": [{"text": str, "entities": [str], "speaker": str|null, "source_document": str|null}]}"""


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


async def extract_clauses(plain_text: str, entity_names: List[str],
                          source_label: str) -> List[dict]:
    """One text-primary extraction call over the scenario text. Uses the
    same client/JSON plumbing as the OOB stages."""
    from app.services.graph_ingest.extract import _vlm_json, _MAX_OUTPUT_TOKENS
    names = sorted({n for n in entity_names if n})[:200]
    header = ("ENTITIES IN THIS PROJECT (use these exact names):\n"
              + "\n".join(f"- {n}" for n in names)
              + "\n\nDOCUMENTS (verbatim):\n")

    async def _lens(system: str, key: str, text: str):
        """One extraction lens with split-retry graceful degradation
        (prototype v5): an unparseable result splits the text in half
        and extracts each half — a stubborn section never sinks the
        whole document's clauses."""
        parsed = await _vlm_json(system, header + text, [],
                                 max_tokens=_MAX_OUTPUT_TOKENS)
        items = (parsed or {}).get(key)
        if items is not None:
            return items
        if len(text) < 4000:
            log.warning("clause lens %s: unparseable fragment dropped", key)
            return []
        half = len(text) // 2
        return (await _lens(system, key, text[:half]) +
                await _lens(system, key, text[half:]))

    out = []
    for c in (await _lens(_CLAUSE_SYSTEM, "clauses", plain_text)) or []:
        if isinstance(c, dict) and (c.get("text") or "").strip():
            out.append(c)
    # Second derivation lens over the same text: obligations-only
    # (verbatim-faithful pending items — the broad extractor normalizes
    # mixed completed/pending narratives; this lens preserves them).
    seen = {_norm(c["text"]) for c in out}
    for t in (await _lens(OBLIG_SYSTEM, "tasks", plain_text)) or []:
        if not isinstance(t, dict) or not (t.get("text") or "").strip():
            continue
        if _norm(t["text"]) in seen:
            continue
        out.append({"text": t["text"], "entities": t.get("entities") or [],
                    "speaker": t.get("speaker"), "kind": "task",
                    "slot": None, "event_date": None, "observed_date": None,
                    "source_document": t.get("source_document")})
    log.info("clause extraction: %d clauses (two lenses) from %s",
             len(out), source_label)
    return out


async def register_clauses(db: AsyncSession, project_id, clauses: List[dict],
                           source_label: str) -> int:
    """Write extracted clauses as project-scoped episodic FactClause rows.
    about[] carries node UUIDs (exact-name match, case-insensitive
    fallback); a clause whose entities all fail to resolve still lands,
    keyed by the raw names, so no statement is lost (F8)."""
    rows = (await db.execute(
        select(GraphNode.id, GraphNode.name)
        .where(GraphNode.project_id == project_id))).all()
    by_name = {}
    for nid, name in rows:
        if name:
            by_name.setdefault(_norm(name), str(nid))
    added = 0
    now = datetime.now(timezone.utc)
    for c in clauses:
        ents = [e for e in (c.get("entities") or []) if e]
        about = []
        for e in ents:
            about.append(by_name.get(_norm(e), e))
        slot = c.get("slot") or None
        if slot and "." in slot:
            # normalize the slot's entity half onto the resolved id so
            # supersession chains survive name-spelling drift
            ent_part, attr = slot.rsplit(".", 1)
            resolved = by_name.get(_norm(ent_part))
            if resolved:
                slot = f"{resolved}.{_norm(attr).replace(' ', '_')}"
        db.add(FactClause(
            text=c["text"].strip(),
            register="episodic",
            speaker=(c.get("speaker") or None),
            source_kind="document_ingest",
            # Per-clause document attribution — the placard's Sources
            # line names the document the statement came from, never
            # the whole ingest bundle.
            source_locus=(c.get("source_document") or source_label),
            about=about or ["_unresolved"],
            kind=c.get("kind") or None,
            slot=slot,
            valid_from=_parse_dt(c.get("event_date")),
            observed_at=_parse_dt(c.get("observed_date")) or now,
            project_id=project_id,
        ))
        added += 1
    await db.commit()
    return added


async def invalidate_slots(db: AsyncSession, project_id) -> int:
    """Deterministic bitemporal supersession, idempotent over the whole
    project: for each slot, order observations by observed_at; every
    non-latest clause gets valid_to = the next observation's observed_at
    and superseded_by = that clause's id. Nothing is deleted — the chain
    IS the history the placard timeline renders."""
    cs = (await db.execute(
        select(FactClause)
        .where(FactClause.project_id == project_id,
               FactClause.register == "episodic",
               FactClause.slot.isnot(None)))).scalars().all()
    by_slot = {}
    for c in cs:
        by_slot.setdefault(c.slot, []).append(c)
    changed = 0
    floor = datetime.min.replace(tzinfo=timezone.utc)
    for slot, group in by_slot.items():
        group.sort(key=lambda c: (c.observed_at or floor, str(c.id)))
        # Full recompute per slot (idempotent): clear, then chain. A
        # supersession requires a STRICTLY LATER observation — clauses
        # sharing an observed_at came from the same report and are
        # concurrent statements, never updates of each other.
        desired: dict = {}
        for cur in group:
            desired[cur.id] = (None, None)
        for i, cur in enumerate(group):
            for nxt in group[i + 1:]:
                if (cur.observed_at and nxt.observed_at
                        and nxt.observed_at > cur.observed_at
                        and _norm(cur.text) != _norm(nxt.text)):
                    desired[cur.id] = (nxt.observed_at, nxt.id)
                    break
        for cur in group:
            want_to, want_by = desired[cur.id]
            if cur.valid_to != want_to or cur.superseded_by != want_by:
                cur.valid_to = want_to
                cur.superseded_by = want_by
                changed += 1
    if changed:
        await db.commit()
    return changed


async def run_register_stage(db: AsyncSession, project_id,
                             plain_text: Optional[str],
                             source_label: str) -> dict:
    """The ingest hook: extract -> register -> invalidate. Non-fatal by
    design — a clause-stage failure never sinks the document ingest."""
    if not plain_text or not plain_text.strip():
        return {"clauses": 0, "superseded": 0, "note": "no text layer"}
    try:
        names = [n for (n,) in (await db.execute(
            select(GraphNode.name)
            .where(GraphNode.project_id == project_id))).all() if n]
        clauses = await extract_clauses(plain_text, names, source_label)
        added = await register_clauses(db, project_id, clauses, source_label)
        superseded = await invalidate_slots(db, project_id)
        return {"clauses": added, "superseded": superseded}
    except Exception as e:
        log.warning("episodic register stage failed (non-fatal): %s", e)
        return {"clauses": 0, "superseded": 0, "error": str(e)}
