"""
THE unified agent chat — POST /api/v1/chat.

One chat over the reference libraries: the WEG catalog and the doctrine
library, retrieved through the SAME tool implementations the MCP server
exposes (never a parallel retrieval stack). The shell's agent surfaces
(the Worldwide Equipment Guide page today; the doctrine chat once this
is a strict superset of it) all talk to this endpoint. The map chat
(/nl/chat) is deliberately still its own surface — folding map
operations into this agent is a planned refactor, not part of this
endpoint yet.

Latency contract: retrieval is ONE tool turn (two at most, for
correcting a miss) because the search tools inline everything — full
sheets on catalog searches, full page text on doctrine searches — and
the response STREAMS over SSE: tool activity the moment it happens,
answer tokens as the model emits them. A blocking JSON mode remains for
non-streaming callers (stream: false / omitted).

Every exchange persists to analyst_events (event_type `chat.exchange`)
with the full agent trace — question, answer, per-turn tool calls and
timings, token usage, citations — so conversations and agent behavior
are auditable after the fact, not just in scrollback.
"""

import asyncio
import json
import logging
import time
import uuid as _uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.db.session import async_session
from app.models.analyst_event import AnalystEvent
from app.services.llm.base import Message, Tool

logger = logging.getLogger(__name__)

router = APIRouter()

_CHAT_SYSTEM = (
    "You are the reference assistant for a military training "
    "simulation, answering from two libraries: the Worldwide Equipment "
    "Guide catalog (equipment systems) and the doctrine library (US and "
    "allied publications). These are your ONLY sources — use the tools "
    "before answering. Choose the library the question needs, and use "
    "both when a question spans them (a system's employment is "
    "doctrine; its figures are the catalog).\n"
    "NAME THE SUBJECT IN query — every catalog search item carries the "
    "system, designation, or topic words as free text (query: 'B-2 "
    "Spirit bomber'); origin/operator/category only narrow a query and "
    "find nothing on their own.\n"
    "RETRIEVE IN ONE TURN. You have at most TWO tool turns before you "
    "must answer, and one is the norm: issue EVERY retrieval the "
    "question needs together, in parallel, in your FIRST turn. "
    "Searches come back complete — catalog searches inline the full "
    "sheets and doctrine searches inline the full page text (both on "
    "by default) — so a search needs no follow-up read. Reserve the "
    "second turn for correcting an actual miss: a designation that did "
    "not resolve, a page the search did not cover. Never spend a turn "
    "re-reading what a search already returned.\n"
    "CITATIONS ARE WOVEN INTO THE PROSE: the mention of a system or "
    "publication IS the link — 'The [B-2 Spirit](E1) has a maximum "
    "speed of 1,010 km/h', 'per [ATP 3-20.97 p.130](D3) the frontage "
    "is...'. The ref is the short TAG the tool result carries on that "
    "system or passage (catalog systems E1, E2, ...; doctrine passages "
    "D1, D2, ...). Link the FIRST mention in each answer; never append "
    "a bracketed citation after a sentence, never park references at "
    "the end, never cite a copied id, path or URL, no footnote-style "
    "cites ([^...]). The label is the short display name or "
    "publication + page. When neither library covers something, say so "
    "plainly — never invent figures.\n"
    "GROUND EVERY CLAIM in a retrieved passage or sheet value, and cite "
    "it inline.\n"
    "WHEN DOCTRINE GIVES A FORMULA, COMPUTE THE ANSWER. Take the "
    "variables from the same passage (weapon range, vehicle count, "
    "terrain factor, flank security), substitute them, show the "
    "substitution on its own line, and state the result in metres AND "
    "kilometres. If a variable needs a system's figure, look it up in "
    "the catalog. Answering 'doctrine does not state a value' when the "
    "passage carries a formula and its factors is a WRONG ANSWER — the "
    "analyst asked for the number. Say a figure is unavailable only "
    "when neither a stated value nor a computable formula exists.\n"
    "Every formula, substitution, and calculation goes inside a "
    "Markdown code block — ``` fenced for multi-line workings, `inline "
    "code` for a single expression — written as plain text "
    "(W = (0.375 x R x N x T) + F). Never LaTeX, never dollar-sign "
    "math, never a formula loose in prose.\n"
    "Keep answers concise, quantitative and factual; use the stated "
    "units. origin means who built a system; operators means who "
    "fields it."
)

_CHAT_TOOLS: Optional[List[Tool]] = None

# Tool results are the model's working set; the one-turn contract makes
# them big by design (full sheets + full pages). Cap the serialized
# payload well above any sane retrieval, low enough that a runaway
# 40-match sheets sweep cannot blow the context.
_PAYLOAD_CHAR_CAP = 60000


def _chat_tools() -> List[Tool]:
    """The reference slice of the MCP tool surface, as native LLM
    function tools — the SAME implementations the MCP server exposes."""
    global _CHAT_TOOLS
    if _CHAT_TOOLS is None:
        _CHAT_TOOLS = [
            Tool(name="search_equipment",
                 description=("Search the catalog. origin = who built "
                              "it; operator = who fields it "
                              "(proliferation). Matches come back WITH "
                              "their full sheets — no follow-up read "
                              "needed."),
                 parameters={"type": "object", "properties": {
                     "queries": {"type": "array", "minItems": 1, "items": {
                         "type": "object",
                         "additionalProperties": False,
                         "properties": {
                             "query": {"type": "string",
                                       "description": ("REQUIRED free text — the "
                                                       "system/designation/topic "
                                                       "words; matches name, "
                                                       "designation, aliases, and "
                                                       "sheet content. Filters "
                                                       "only NARROW a query.")},
                             "origin": {"type": "string"},
                             "operator": {"type": "string"},
                             "class": {"type": "string"},
                             "domain": {"type": "string",
                                        "enum": ["land", "air", "sea"]},
                             "category": {"type": "string"},
                             "year_min": {"type": "integer"},
                             "year_max": {"type": "integer"},
                             "limit": {"type": "integer"}},
                         "required": ["query"]}}},
                     "required": ["queries"]}),
            Tool(name="get_equipment_sheets",
                 description=("Correction-turn read: full WEG sheets by "
                              "weg_id, for a sheet a search did not "
                              "already inline."),
                 parameters={"type": "object", "properties": {
                     "weg_ids": {"type": "array", "items": {"type": "string"}}},
                     "required": ["weg_ids"]}),
            Tool(name="search_doctrine",
                 description=("Search the doctrine library. Hits carry "
                              "pub_id, page, content, a "
                              "'doctrine:<doc_id>:<page>' link to cite, "
                              "the FULL page text (page_text) on the top "
                              "pages, and a citation tag (ref: D1) — "
                              "cite [PUB p.N](D1)."),
                 parameters={"type": "object", "properties": {
                     "queries": {"type": "array", "minItems": 1, "items": {
                         "type": "object",
                         "additionalProperties": False,
                         "properties": {
                             "question": {"type": "string",
                                          "description": "what to retrieve"},
                             "k": {"type": "integer"}},
                         "required": ["question"]}}},
                     "required": ["queries"]}),
            Tool(name="get_doctrine_pages",
                 description=("Correction-turn read: full doctrine pages "
                              "for a page a search did not already "
                              "inline. Copy doc_id verbatim from a hit."),
                 parameters={"type": "object", "properties": {
                     "pages": {"type": "array", "items": {
                         "type": "object", "properties": {
                             "doc_id": {"type": "string"},
                             "page": {"type": "integer"}},
                         "required": ["doc_id", "page"]}}},
                     "required": ["pages"]}),
            Tool(name="resolve_equipment",
                 description=("Resolve designations/nomenclatures to "
                              "catalog systems (exact matching; misses "
                              "return near_matches). Resolved systems "
                              "come back WITH their full sheets."),
                 parameters={"type": "object", "properties": {
                     "nomenclatures": {"type": "array",
                                       "items": {"type": "string"}}},
                     "required": ["nomenclatures"]}),
        ]
    return _CHAT_TOOLS


def _pub_label(doc_id: str) -> str:
    """'Army/ATP 3-20.97 - Cavalry Troop.pdf' -> 'ATP 3-20.97'."""
    name = (doc_id or "").rsplit("/", 1)[-1]
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return name.split(" - ")[0].strip() or name


def _tool_status(name: str, args: Dict[str, Any]) -> str:
    """One analyst-readable activity line per tool call — what the agent
    is doing right now, in the analyst's terms, never internal ids."""
    args = args or {}
    if name == "search_equipment":
        qs = []
        for q in args.get("queries") or []:
            label = (q or {}).get("query") or (q or {}).get("category") \
                or (q or {}).get("class") or (q or {}).get("operator") \
                or (q or {}).get("origin")
            if label:
                qs.append(str(label))
        return "Searching the catalog" + (f": {', '.join(qs[:3])}" if qs else "")
    if name == "get_equipment_sheets":
        n = len(args.get("weg_ids") or [])
        return f"Reading {n} equipment sheet{'s' if n != 1 else ''}"
    if name == "resolve_equipment":
        names = [str(n) for n in (args.get("nomenclatures") or [])][:4]
        return "Looking up " + ", ".join(names) if names else "Looking up designations"
    if name == "search_doctrine":
        qs = [str((q or {}).get("question") or "")
              for q in (args.get("queries") or [])]
        qs = [q for q in qs if q]
        return "Searching doctrine" + (f": {qs[0]}" if qs else "")
    if name == "get_doctrine_pages":
        parts = []
        for p in (args.get("pages") or [])[:4]:
            parts.append(f"{_pub_label(str((p or {}).get('doc_id') or ''))} "
                         f"p.{(p or {}).get('page')}")
        return "Reading " + ", ".join(parts) if parts else "Reading doctrine pages"
    return "Working"


def _harvest_strings(value) -> List[str]:
    """Every string anywhere in a (possibly hallucinated) args shape —
    the model has emitted queries:[] with the real text parked in
    invented side keys ({"queries": [], "queries_param_value":
    ["B-2 Spirit bomber"]}); the text is salvaged wherever it sits."""
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, list):
        return [s for item in value for s in _harvest_strings(item)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _harvest_strings(v)]
    return []


_EMPTY_CALL_GUIDANCE = (
    "the call carried NO query items — call again with "
    "queries=[{{\"{field}\": \"<the system designation or topic words>\"}}]")


async def _dispatch_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one tool call against the shared implementations. The
    one-turn defaults live HERE: chat searches inline sheets and pages
    unless the model explicitly turns them off. Empty or mis-shaped
    calls come back with corrective guidance, never a silent empty
    result — silence taught the model 'the library has nothing'."""
    from app.services.graph_ingest import tools as t
    args = args or {}

    def prepared_items(field: str, default_flag: str):
        items = list(args.get("queries") or [])
        if not items:
            items = _harvest_strings(args)
        out = []
        for q in items:
            if isinstance(q, dict):
                q = dict(q)
                q.setdefault(default_flag, True)
                out.append(q)
            elif str(q).strip():
                out.append({field: str(q).strip(), default_flag: True})
        return out

    try:
        if name == "search_equipment":
            queries = prepared_items("query", "sheets")
            if not queries:
                return {"results": [], "guidance":
                        _EMPTY_CALL_GUIDANCE.format(field="query")}
            return await t.tool_search_equipment(queries)
        if name == "get_equipment_sheets":
            return await t.tool_get_equipment_sheets(args.get("weg_ids") or [])
        if name == "resolve_equipment":
            return await t.tool_resolve_equipment(
                args.get("nomenclatures") or [], include_sheets=True)
        if name == "search_doctrine":
            queries = prepared_items("question", "pages")
            if not queries:
                return {"results": [], "guidance":
                        _EMPTY_CALL_GUIDANCE.format(field="question")}
            return await t.tool_search_doctrine(queries)
        if name == "get_doctrine_pages":
            return await t.tool_get_doctrine_pages(args.get("pages") or [])
        return {"error": f"unknown tool {name}"}
    except Exception as exc:
        logger.exception("chat tool %s failed", name)
        return {"error": str(exc)}


class _RefRegistry:
    """Engine-assigned citation handles for one exchange. Structured
    ids NEVER round-trip through the writer LLM — the model cites a
    two-character tag stamped on the tool result (E1, D3), and the
    SYSTEM expands the tag to the real target after the loop. Hand-
    copied ids corrupted five different ways in live testing; a tag
    has nothing to corrupt."""

    def __init__(self):
        self.by_target: Dict[str, str] = {}
        self.to_target: Dict[str, str] = {}
        self.label: Dict[str, str] = {}
        self._counts = {"E": 0, "D": 0}

    def tag(self, kind: str, target: str, label: str = "") -> str:
        existing = self.by_target.get(target)
        if existing:
            if label and not self.label.get(existing):
                self.label[existing] = label
            return existing
        self._counts[kind] += 1
        t = f"{kind}{self._counts[kind]}"
        self.by_target[target] = t
        self.to_target[t] = target
        if label:
            self.label[t] = label
        return t


def _collect_sources(payload: Dict[str, Any], references: List[str],
                     citations: List[dict], seen: set,
                     refs: _RefRegistry) -> None:
    """Pull weg references and doctrine citations out of a tool result —
    the citations feed the panel's chips in the exact shape the shell
    already renders (doc_id / pub_id / title / page / snippet) — and
    stamp every system/passage with its citation TAG (mutating the
    payload the model is about to read)."""
    for item in (payload.get("results") or []):
        wid = item.get("weg_id")
        if wid and "error" not in item:
            references.append(wid)
            item["ref"] = refs.tag("E", f"weg:{wid}", str(item.get("name") or ""))
        for m2 in item.get("matches") or []:
            if m2.get("weg_id"):
                references.append(m2["weg_id"])
                m2["ref"] = refs.tag("E", f"weg:{m2['weg_id']}", str(m2.get("name") or ""))
        sheet = item.get("sheet") or {}
        if sheet.get("weg_id"):
            references.append(sheet["weg_id"])
            sheet["ref"] = refs.tag("E", f"weg:{sheet['weg_id']}", str(sheet.get("name") or ""))
        for nm in item.get("near_matches") or []:
            if nm.get("weg_id"):
                nm["ref"] = refs.tag("E", f"weg:{nm['weg_id']}", str(nm.get("name") or ""))
        hits = item.get("hits") or []
        if item.get("doc_id") and item.get("page") is not None \
                and "text" in item:
            hits = hits + [{"doc_id": item["doc_id"],
                            "page": item["page"],
                            "content": item.get("text", "")}]
            item["ref"] = refs.tag(
                "D", f"doctrine:{item['doc_id']}:{item['page']}",
                f"{_pub_label(str(item['doc_id']))} p.{item['page']}")
        for h in hits:
            if h.get("doc_id") and h.get("page") is not None:
                h["ref"] = refs.tag(
                    "D", f"doctrine:{h['doc_id']}:{h['page']}",
                    f"{_pub_label(str(h['doc_id']))} p.{h['page']}")
            key = f"{h.get('doc_id')}#{h.get('page')}"
            if not h.get("doc_id") or key in seen:
                continue
            seen.add(key)
            citations.append({
                "doc_id": h.get("doc_id"),
                "pub_id": h.get("pub_id"),
                "title": h.get("title"),
                "page": h.get("page"),
                "snippet": (h.get("content") or "")[:400],
            })


def _expand_ref_tags(answer: str, refs: _RefRegistry) -> str:
    """Every tag form the model emits becomes a real link, so a tag
    never reaches the analyst: [Label](E1) -> [Label](target);
    bare [E1] or (E1) in prose -> [Known Label](target)."""
    import re as _re

    def link_target(m):
        target = refs.to_target.get(m.group(1))
        return f"({target})" if target else m.group(0)

    # [Label](E1) — the taught form.
    answer = _re.sub(r"(?<=\])\(([ED]\d{1,3})\)", link_target, answer)

    def bare(m):
        t = m.group(1)
        target = refs.to_target.get(t)
        if not target:
            return m.group(0)
        # SHORT label — the designation, not the full catalog title
        # ("B-2 Spirit", never "B-2 Spirit (Stealth Bomber) American
        # Heavy Strategic Bomber" bolted onto a sentence).
        label = (refs.label.get(t) or t).split(" (")[0].split(",")[0][:48]
        return f"[{label}]({target})"

    # [E1] / (E1) as a citation marker in prose.
    answer = _re.sub(r"\[([ED]\d{1,3})\](?!\()", bare, answer)
    return _re.sub(r"\(([ED]\d{1,3})\)", bare, answer)


def _fit_payload(payload: Dict[str, Any]) -> str:
    """Serialize a tool result under the working-set cap by trimming
    STRUCTURE, never by cutting the JSON string mid-token: ranked lists
    lose their bottom half first (results are relevance-ordered, so the
    top survives), then inlined page texts shorten, and only a payload
    that is still oversized after both falls back to a hard cut."""
    serialized = json.dumps(payload)
    while len(serialized) > _PAYLOAD_CHAR_CAP:
        trimmed = False
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            for key in ("matches", "hits", "near_matches"):
                lst = item.get(key)
                if isinstance(lst, list) and len(lst) > 2:
                    del lst[max(2, len(lst) // 2):]
                    item[f"{key}_trimmed"] = ("bottom of the ranked list "
                                              "dropped to fit; refine the "
                                              "query for more")
                    trimmed = True
            for h in item.get("hits") or []:
                if isinstance(h, dict) and len(h.get("page_text") or "") > 8000:
                    h["page_text"] = h["page_text"][:8000]
                    trimmed = True
        if not trimmed:
            return serialized[:_PAYLOAD_CHAR_CAP]
        serialized = json.dumps(payload)
    return serialized


def _repair_link_targets(answer: str, references: List[str],
                         citations: List[dict]) -> str:
    """Rewrite model-corrupted scheme targets to the real ids.

    Ids never round-trip through a writer LLM intact — live testing
    produced (weg:2023utilityuavspirit) for 2023_utility_uav_spirit,
    which no renderer can resolve, so the raw markdown leaked at the
    analyst. Every weg:/doctrine: target is checked against what the
    tools actually returned THIS exchange and, when it isn't a known
    id, matched punctuation-folded and rewritten. An unmatchable target
    stays as written (the renderer's tolerant patterns are the last
    line)."""
    import re as _re

    def fold(s):
        return _re.sub(r"[^a-z0-9]", "", str(s).lower())

    ref_by_fold = {fold(r): r for r in references}
    cite_by_fold = {}
    for c in citations:
        doc_id, page = c.get("doc_id"), c.get("page")
        if doc_id and page is not None:
            cite_by_fold[fold(f"{doc_id}{page}")] = f"{doc_id}:{page}"
            cite_by_fold.setdefault(fold(doc_id), f"{doc_id}:{page}")

    def fix_weg(m):
        target = m.group(1).strip()
        if target in references:
            return m.group(0)
        real = ref_by_fold.get(fold(target))
        return f"(weg:{real})" if real else m.group(0)

    def fix_doctrine(m):
        target = m.group(1).strip()
        known = any(f"{c.get('doc_id')}:{c.get('page')}" == target
                    for c in citations)
        if known:
            return m.group(0)
        real = cite_by_fold.get(fold(target))
        return f"(doctrine:{real})" if real else m.group(0)

    # A hallucinated URL prefix on a scheme ((https://weg:...)) strips
    # before the fix passes so the target still validates and renders.
    answer = _re.sub(r"\(https?://(weg:|doctrine:)", r"(\1", answer)
    answer = _re.sub(r"\(weg:([^)]+)\)", fix_weg, answer)
    return _re.sub(r"\(doctrine:([^)]+)\)", fix_doctrine, answer)


async def _persist_exchange(surface: str, user_id: Optional[str],
                            detail: Dict[str, Any]) -> None:
    """One durable chat.exchange row per Q&A — the stored history and
    agent trace. Fire-and-forget: storage failure must never break the
    analyst's answer."""
    try:
        async with async_session() as db:
            db.add(AnalystEvent(
                occurred_at_ms=detail.get("started_at_ms"),
                received_at_ms=int(time.time() * 1000),
                user_id=(str(user_id)[:255] if user_id else None),
                surface=(surface or "chat")[:64],
                event_type="chat.exchange",
                detail=detail,
            ))
            await db.commit()
    except Exception:
        logger.exception("chat.exchange persistence failed")


async def _chat_events(body: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
    """The agent loop as an event stream. Events:
      {"event": "status", "text"}  — tool/reasoning activity, live
      {"event": "delta", "text"}   — answer tokens as the model emits them
      {"event": "reset"}           — discard streamed text (it was
                                      pre-tool preamble, not the answer)
      {"event": "done", ...}       — the complete exchange (also the
                                      blocking JSON response body)
      {"event": "error", "detail"} — terminal failure
    Two tool rounds maximum; the third call carries no tools, forcing
    prose. Every exchange persists with its full trace."""
    from app.services.llm.client import get_llm_client

    message = str(body.get("message") or "").strip()
    history = body.get("history") or []
    session_id = str(body.get("session_id") or _uuid.uuid4())
    surface = str(body.get("surface") or "chat")
    user_id = body.get("user_id")

    messages = [Message(role=m.get("role", "user"),
                        content=str(m.get("content", "")))
                for m in history[-8:] if m.get("content")]
    messages.append(Message(role="user", content=message))

    llm = get_llm_client()
    references: List[str] = []
    citations: List[dict] = []
    seen_citations: set = set()
    refs = _RefRegistry()
    trace: List[dict] = []
    started_at_ms = int(time.time() * 1000)
    started = time.monotonic()
    answer = ""
    error: Optional[str] = None

    try:
        for round_no in range(3):
            tools = _chat_tools() if round_no < 2 else None
            turn_started = time.monotonic()
            final = None
            streamed_any = False
            reasoning_flagged = False
            async for kind, item in llm.chat_stream(
                    messages, system=_CHAT_SYSTEM, tools=tools,
                    max_tokens=1200, temperature=0.2):
                if kind == "delta":
                    streamed_any = True
                    yield {"event": "delta", "text": item}
                elif kind == "reasoning" and not reasoning_flagged:
                    reasoning_flagged = True
                    yield {"event": "status",
                           "text": "Reasoning over the retrieved material"}
                elif kind == "response":
                    final = item
            turn_entry = {
                "turn": round_no + 1,
                "elapsed_ms": int((time.monotonic() - turn_started) * 1000),
                "usage": (final.usage if final else {}) or {},
                "content": ((final.content if final else "") or "")[:2000],
                "reasoning": ((final.reasoning if final else "") or "")[:2000],
                "tool_calls": [],
            }
            trace.append(turn_entry)
            if final is None or not final.tool_calls:
                answer = (final.content if final else "") or ""
                break
            if streamed_any:
                # Whatever streamed this turn was tool-call preamble.
                yield {"event": "reset"}
            messages.append(Message(role="assistant",
                                    content=final.content or "",
                                    tool_calls=final.tool_calls))
            for tc in final.tool_calls:
                yield {"event": "status",
                       "text": _tool_status(tc.name, tc.arguments)}
            exec_started = time.monotonic()
            payloads = await asyncio.gather(
                *(_dispatch_tool(tc.name, tc.arguments or {})
                  for tc in final.tool_calls))
            exec_ms = int((time.monotonic() - exec_started) * 1000)
            for tc, payload in zip(final.tool_calls, payloads):
                _collect_sources(payload, references, citations,
                                 seen_citations, refs)
                serialized = _fit_payload(payload)
                turn_entry["tool_calls"].append({
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments or {})[:2000],
                    "result_chars": len(serialized),
                    "error": payload.get("error"),
                    "elapsed_ms": exec_ms,
                })
                messages.append(Message(role="tool", tool_call_id=tc.id,
                                        content=serialized))
        else:
            answer = ("The lookup did not converge — try a more specific "
                      "question.")
    except Exception as exc:
        logger.exception("unified chat failed")
        error = str(exc)
        yield {"event": "error",
               "detail": "The assistant could not process that request."}

    # The done event replaces the streamed bubble in every consumer, so
    # the repaired answer is what the analyst reads even though the raw
    # deltas streamed first.
    answer = _expand_ref_tags(answer, refs)
    answer = _repair_link_targets(answer, sorted(set(references)),
                                  citations)
    done = {
        "event": "done",
        "answer": answer,
        "references": sorted(set(references)),
        "citations": citations,
        "session_id": session_id,
    }
    await _persist_exchange(surface, user_id, {
        "session_id": session_id,
        "question": message,
        "answer": answer[:20000],
        "history_len": len(history),
        "references": sorted(set(references)),
        "citations": citations,
        "turns": trace,
        "total_ms": int((time.monotonic() - started) * 1000),
        "started_at_ms": started_at_ms,
        "error": error,
    })
    if error is None:
        yield done


async def _sse(events: AsyncIterator[Dict[str, Any]]) -> AsyncIterator[str]:
    async for ev in events:
        yield f"data: {json.dumps(ev)}\n\n"


@router.post("/chat")
async def unified_chat(body: dict):
    """THE unified agent chat (see module docstring). `stream: true`
    returns SSE (status / delta / reset / done / error events); without
    it, the complete exchange as JSON — same fields as the done event."""
    if not str(body.get("message") or "").strip():
        raise HTTPException(400, "message required")
    if body.get("stream"):
        return StreamingResponse(
            _sse(_chat_events(body)),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                # nginx would buffer the stream to death otherwise —
                # every proxied deployment (intel, beta) fronts this
                # with nginx.
                "X-Accel-Buffering": "no",
            })
    final: Optional[Dict[str, Any]] = None
    async for ev in _chat_events(body):
        if ev.get("event") == "done":
            final = ev
        elif ev.get("event") == "error":
            raise HTTPException(502, ev.get("detail") or "chat failed")
    if final is None:
        raise HTTPException(502, "chat produced no answer")
    final.pop("event", None)
    return JSONResponse(content=final)
