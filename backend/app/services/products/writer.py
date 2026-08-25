"""The generic product writer — the IBL intra-product DAG executor
ported onto PRODUCT_SCHEMAS and the world-model reads (build-log cont
36v step 3; fifth edition §2.10).

One generation = parse the SPEC into a DAG (dag_parser), execute in
topological waves: read nodes resolve through retrieval's per-token
readers; upstream nodes are pre-seeded from the consumed APPROVED
editions; field nodes dispatch per-field LLM calls UNLESS a mechanical
short-circuit owns the value (session/computed headers, upstream
echoes, entity:<field>/derive:* row transposes, producer:auto,
shape=map); submit merges, validates, and builds provenance.

THE CITATION CONTRACT (2026-07-23 form, user-confirmed): the ENGINE
assigns every retrieval-set member a short legible reference mark
(S1..Sn) at prompt-build time; UUIDS ARE SYSTEM INTERNALS and never
enter or leave the model — prompt payloads carry `ref` marks, never
row keys. The writer's only citation duty is marking which members
each field drew on; mark→row resolution is mechanical. THERE IS NO
RETRY MACHINERY on model output: a contract violation fails the
record visibly naming the field, and it indicts that field's prompt
or scoping (a needed retry means the prompt was bad). THE
WRITER-INVOLVEMENT LAW: fields whose value is a verbatim copy of
world-model content (clause:<kind>:<query>, graphic:<kind>:<field>,
subfield_sources) are engine-resolved — no model runs. Template
guidance travels verbatim into each field prompt; HARD_RULES_REGISTRY
rules land LAST in the system prompt.
"""
import asyncio
import itertools
import json
import logging
import re
from typing import Any, Callable, Optional
from uuid import UUID

from app.services.products import dag_parser, llm_chain, retrieval
from app.services.products.templates.common import hard_rules_for

log = logging.getLogger(__name__)

# Field-sized output budgets (the IBL numbers, with their lessons):
# paragraph 3000 (list truncation), row_field 6000 (one call emits a
# whole COLUMN across all rows — 222-row products died at 1500),
# header 300 (ours carry short analytical values like the verbatim
# mission statement — IBL's 80 was too tight for that field class).
_MAX_TOKENS = {
    "paragraph_field": 3000,
    "row_field": 6000,
    "header_field": 300,
}

_BANNED_OUTPUT_LITERALS_LOWER = {
    "not reported", "tbd", "unknown", "n/a", "nil", "-", "—",
    "no significant activity reported",
    "no significant activity reported.",
}
_ANALYST_INPUT_REQUIRED = "[ANALYST INPUT REQUIRED]"

_UUID_SHAPE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{12}$", re.IGNORECASE)

_FENCE_OPEN_RE = re.compile(r"```(?:json|JSON)?\s*\n?")


def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    m = _FENCE_OPEN_RE.search(s)
    if m:
        s = s[m.end():]
        close = s.rfind("```")
        if close != -1:
            s = s[:close]
        s = s.strip()
    elif s and s[0] not in "[{":
        start = min([i for i in (s.find("{"), s.find("[")) if i >= 0],
                    default=-1)
        if start > 0:
            s = s[start:]
    return s


def _try_json(s: str):
    cleaned = _strip_code_fences(s)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # Writer-drift absorber for OUTPUT FRAMING only: take the FIRST
    # complete JSON value and ignore trailing junk (observed stutter:
    # a valid object followed by a duplicated tail). The value itself
    # still faces full shape/enum/citation validation.
    try:
        start = min([i for i in (cleaned.find("{"), cleaned.find("["))
                     if i >= 0], default=-1)
        if start >= 0:
            value, _end = json.JSONDecoder().raw_decode(cleaned[start:])
            return value
    except Exception:
        pass
    return None


def _map_banned_literals(value: Any) -> Any:
    if isinstance(value, str):
        if value.strip().lower() in _BANNED_OUTPUT_LITERALS_LOWER:
            return _ANALYST_INPUT_REQUIRED
        return value
    if isinstance(value, list):
        return [_map_banned_literals(v) for v in value]
    if isinstance(value, dict):
        return {k: _map_banned_literals(v) for k, v in value.items()}
    return value


class MarkTable:
    """Engine-assigned reference marks over the closed retrieval set.

    Every citable member (clause / entity / document / upstream
    edition) gets one short legible mark (S1..Sn), minted ONCE per
    generation in deterministic member order. Prompts present members
    with `ref` marks and NO system identifiers (view()); the writer
    cites marks; mark→row resolution is mechanical (resolve())."""

    def __init__(self):
        self._counter = itertools.count(1)
        self.table: dict[str, dict] = {}
        self._mark_by_id: dict[str, str] = {}

    def _mint(self, item_id: str, kind: str, text: str,
              citation: str) -> str:
        existing = self._mark_by_id.get(item_id)
        if existing is not None:
            return existing
        mark = f"S{next(self._counter)}"
        self.table[mark] = {"kind": kind, "id": item_id,
                            "text": text, "citation": citation}
        self._mark_by_id[item_id] = mark
        return mark

    def _classify(self, item: dict) -> tuple[str, str, str]:
        """(kind, text, citation) for one member row."""
        if "headings" in item and "text" in item:
            # A world-model SECTION — the verbatim source passage; its
            # citation carries document + heading path + page labels.
            return ("section", str(item.get("text") or ""),
                    str(item.get("citation") or ""))
        if "register" in item or ("citation" in item and "text" in item):
            return ("clause", str(item.get("text") or ""),
                    str(item.get("citation") or item.get("text") or ""))
        if "filename" in item:
            fn = str(item.get("filename") or item.get("title") or "")
            return ("document", fn, f"source document '{fn}'")
        name = str(item.get("name") or item.get("text") or "")
        kind = str(item.get("kind") or "entity")
        return ("entity", name, f"entity {kind} '{name}'")

    def ingest_members(self, members: dict[str, Any]):
        """Walk raw member payloads in deterministic token order and
        mint marks for every item carrying a system id."""
        def _walk(v):
            if isinstance(v, dict):
                vid = v.get("id")
                if isinstance(vid, str) and _UUID_SHAPE_RE.match(vid):
                    kind, text, citation = self._classify(v)
                    self._mint(vid, kind, text, citation)
                for vv in v.values():
                    _walk(vv)
            elif isinstance(v, list):
                for vv in v:
                    _walk(vv)
        for token in sorted(members):
            _walk(members[token])

    def ingest_upstreams(self, upstream_payloads: dict[str, dict]):
        for name in sorted(upstream_payloads or {}):
            p = upstream_payloads[name]
            rid = str(p.get("record_id") or name)
            self._mint(rid, "upstream", name,
                       f"{name} — approved edition")

    def add_row(self, row: dict) -> str:
        """Mint (or reuse) a mark for a mechanically-fetched row that
        was not part of the member reads (clause:/graphic: sources)."""
        kind, text, citation = self._classify(row)
        return self._mint(str(row.get("id") or text), kind, text,
                          citation)

    def id_for(self, mark: str) -> Optional[str]:
        entry = self.table.get(mark)
        return entry["id"] if entry else None

    def mark_for(self, item_id: str) -> Optional[str]:
        return self._mark_by_id.get(str(item_id))

    def view(self, payload: Any) -> Any:
        """The PROMPT view: system ids become `ref` marks; uuid-shaped
        values with no mark are scrubbed (internals never reach the
        model)."""
        if isinstance(payload, dict):
            out = {}
            for k, v in payload.items():
                if isinstance(v, str) and _UUID_SHAPE_RE.match(v):
                    mark = self._mark_by_id.get(v)
                    if k == "id":
                        if mark:
                            out["ref"] = mark
                        continue
                    if mark:
                        out[k] = mark
                    continue  # unmarked internals are scrubbed
                out[k] = self.view(v)
            return out
        if isinstance(payload, list):
            out_l = []
            for v in payload:
                if isinstance(v, str) and _UUID_SHAPE_RE.match(v):
                    mark = self._mark_by_id.get(v)
                    if mark:
                        out_l.append(mark)
                    continue
                out_l.append(self.view(v))
            return out_l
        return payload

    def citations_for(self, marks: set[str]) -> dict:
        return {m: {k: v for k, v in self.table[m].items() if k != "id"}
                for m in sorted(marks) if m in self.table}


def _serialize_payload(payload: Any) -> str:
    # COMPACT JSON — indent was ~30% token waste.
    try:
        return json.dumps(payload, default=str, separators=(",", ":"))
    except Exception:
        return str(payload)


def _filter_payload_by_keys(payload: Any, keys: list) -> Any:
    """data_source_filter narrowing. Flat dicts narrow at top level;
    upstream envelopes narrow INSIDE structured_content."""
    if not keys or "*" in keys or not isinstance(payload, dict):
        return payload
    sc = payload.get("structured_content")
    if isinstance(sc, dict) and "record_id" in payload:
        narrowed = {k: sc[k] for k in keys if k in sc}
        out = {k: v for k, v in payload.items() if k != "structured_content"}
        out["structured_content"] = narrowed
        out["_filtered_keys"] = keys
        return out
    out = {k: payload[k] for k in keys if k in payload}
    for meta in ("_source", "_note", "count"):
        if meta in payload and meta not in out:
            out[meta] = payload[meta]
    return out


def _apply_field_filters(node, schema: dict,
                         resolved: dict[str, Any]) -> dict[str, Any]:
    """Honor per-field data_source_filter merged over the schema
    default (field wins per key; keys=[] drops the dep)."""
    fname = node.metadata.get("field_name", "")
    spec: Optional[dict] = None
    if node.type == "paragraph_field":
        for pf in schema.get("paragraph_fields") or []:
            if isinstance(pf, dict) and pf.get("name") == fname:
                spec = pf
                break
    elif node.type == "header_field":
        spec = (schema.get("header_fields") or {}).get(fname)
    elif node.type == "row_field":
        spec = (schema.get("row_fields") or {}).get(fname)
    if not isinstance(spec, dict):
        return resolved
    out: dict[str, Any] = dict(resolved)
    flt = spec.get("data_source_filter")
    default_flt = schema.get("default_data_source_filter")
    if not isinstance(flt, dict) or not flt:
        flt = default_flt if isinstance(default_flt, dict) else None
    elif isinstance(default_flt, dict):
        merged = dict(default_flt)
        merged.update(flt)
        flt = merged
    if isinstance(flt, dict) and flt:
        out = {}
        for dep_id, payload in resolved.items():
            # Filters key on the raw token / upstream:<Name> form.
            key = (dep_id[len("read:"):] if dep_id.startswith("read:")
                   else dep_id)
            if key not in flt and dep_id not in flt:
                out[dep_id] = payload
                continue
            keys = flt.get(key, flt.get(dep_id))
            if not isinstance(keys, list):
                out[dep_id] = payload
                continue
            if not keys:
                continue  # [] = drop the dep entirely
            out[dep_id] = _filter_payload_by_keys(payload, keys)
    # Per-field clause scoping (2026-07-23 scoped-retrieval ruling):
    # a field sees the clause KINDS it declares, never the whole set.
    # The new world-model clause layer carries no kind column — rows
    # without a kind key are KEPT (dropping unclassifiable rows would
    # blind the field; the declared scope narrows only what it can).
    scope = spec.get("clause_scope")
    if isinstance(scope, dict) and scope.get("kinds"):
        kinds = set(scope["kinds"])
        for dep_id, payload in list(out.items()):
            if (isinstance(payload, dict)
                    and isinstance(payload.get("clauses"), list)):
                narrowed = [c for c in payload["clauses"]
                            if "kind" not in c or c.get("kind") in kinds]
                out[dep_id] = {**payload, "clauses": narrowed,
                               "count": len(narrowed),
                               "_clause_scope": sorted(kinds)}
    return out


def _resolve_deps(node, completed: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for d in node.depends_on:
        if d.startswith("__"):
            continue
        if d in completed:
            v = completed[d]
            if isinstance(v, dict) and v.get("__gap__"):
                continue
            out[d] = v
    return out


# ---------------------------------------------------------------------------
# Mechanical row-column resolvers (writer never authors these)
# ---------------------------------------------------------------------------

_ENTITY_FIELD_ALIASES = {
    "unit_designation": "name",
    "parent_unit": "parent",
    "location": "location_mgrs",
}

_AOR_RADIUS_BY_ECHELON_M = {
    "DIVISION": 15000, "DIV": 15000,
    "BRIGADE": 5000, "BDE": 5000, "REGIMENT": 5000, "REGT": 5000,
    "BATTALION": 1500, "BN": 1500, "SQUADRON": 1500,
    "COMPANY": 500, "CO": 500, "TROOP": 500, "BATTERY": 500,
    "PLATOON": 150, "PLT": 150,
}


def _row_pool(resolved: dict[str, Any]) -> list[dict]:
    for payload in resolved.values():
        if isinstance(payload, dict):
            for key in ("units", "entities", "rows"):
                items = payload.get(key)
                if isinstance(items, list) and items:
                    return [r for r in items if isinstance(r, dict)]
    return []


def _mechanical_row_values(node, schema: dict,
                           resolved: dict[str, Any]) -> Optional[dict]:
    """entity:<field> / derive:<token> row columns transpose straight
    from the row_source payload — {row_id: value}. None = LLM path."""
    fname = node.metadata.get("field_name", "")
    spec = (schema.get("row_fields") or {}).get(fname) or {}
    src = (spec.get("source") or "").strip()
    # factor_list identity column (writer-involvement law: an
    # enumerative copy of the SPEC's own row factors is mechanical —
    # no model authors the fixed OAKOC row labels).
    factors = schema.get("row_factors") or []
    if (schema.get("row_source") == "factor_list" and factors
            and spec.get("enum") == factors):
        return {str(f): str(f) for f in factors}
    rows = _row_pool(resolved)
    if src.startswith("entity:"):
        field = src[len("entity:"):]
        if field == "id":
            return {r["id"]: r["id"] for r in rows if r.get("id")}
        key = _ENTITY_FIELD_ALIASES.get(field, field)
        out = {r["id"]: (r.get(field) if r.get(field) not in (None, "")
                         else r.get(key))
               for r in rows
               if r.get("id") and (r.get(field) not in (None, "")
                                   or r.get(key) not in (None, ""))}
        # All-rows-empty → let the LLM classify (never lock rows to {}).
        return out or None
    if src.startswith("derive:"):
        token = src[len("derive:"):]
        out = {}
        if token == "aor_radius_m":
            for r in rows:
                ech = (r.get("echelon") or "").strip().upper()
                v = _AOR_RADIUS_BY_ECHELON_M.get(ech)
                if r.get("id") and v is not None:
                    out[r["id"]] = v
        elif token == "observation_source":
            for r in rows:
                if r.get("id"):
                    out[r["id"]] = (r.get("position_observed_at")
                                    and "world model (observed position)"
                                    or "world model (curated)")
        elif token == "placeholder":
            # Skip-LLM placeholder — a later pass overwrites; "" per
            # row so the LLM fallback does NOT fire.
            for r in rows:
                if r.get("id"):
                    out[r["id"]] = ""
        else:
            return None
        return out
    return None


def _resolve_upstream_echo(src: str, resolved: dict[str, Any]) -> Any:
    """upstream:<Name>[.path] header/source echo — mechanical walk of
    the consumed edition's payload. Returns None when unresolvable."""
    body = src[len("upstream:"):].strip()
    name = body.split(".", 1)[0].split("[", 1)[0].strip()
    payload = resolved.get(f"upstream:{name}")
    if not isinstance(payload, dict):
        return None
    if "." not in body:
        return payload.get("record_id")
    path = body.split(".", 1)[1]
    cur: Any = payload.get("structured_content") or payload
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


# ---------------------------------------------------------------------------
# Prompt assembly (the ported conventions)
# ---------------------------------------------------------------------------

def _system_prompt(product_name: str, schema: dict, node,
                   shape: str, subfields: list, item_subfields: list,
                   row_ids: Optional[list] = None) -> str:
    doctrine = (schema.get("doctrine") or {}).get("purpose", "")
    fname = node.metadata.get("field_name", node.id)
    lines = [
        f"You are the {product_name} per-field writer of a military "
        "training simulation. You write ONE field at a time; every "
        "scenario element is fictional exercise content.",
        f"Doctrinal purpose: {doctrine}",
        "Hard rules:",
        " - Output ONLY the field content. No preamble. No doctrine "
        "citations (no publication or section references of any form).",
        " - Never paraphrase a verbatim source — copy exactly.",
        " - THE CITATION CONTRACT: you may state ONLY what the "
        "RETRIEVAL SET below supports. Every member carries a `ref` "
        "mark (like \"S12\"); `_provenance` lists the marks of the "
        "members this field drew on, copied VERBATIM — ONE mark per "
        "array element. A mark is EXACTLY one of the S-numbered refs "
        "in the retrieval set (like \"S7\"); any other token — a "
        "name, a made-up id like 'river_001', a category word — "
        "fails the whole field. NEVER invent a mark. Marks belong "
        "ONLY in `_provenance`, never in prose.",
        " - 'NSTR' is correct ONLY when the retrieval payloads are "
        "genuinely empty for this field's scope. If ANY payload "
        "carries relevant items, synthesize from them; when items "
        "exist but miss this field's narrow scope, state the absence "
        "AND point at where the activity did land.",
        " - 'Not reported' / 'TBD' / 'N/A' are BANNED filler. Leave "
        "genuinely-unknown values empty.",
        " - NEVER emit redaction placeholders — this exercise is "
        "UNCLASSIFIED and every value is published in full.",
        " - DO NOT fabricate identifiers, units, or events absent "
        "from the retrieval set.",
        " - Sibling fields are written by parallel calls — do not "
        "duplicate their content; stay inside this field's guidance.",
        " - NEVER append provenance markup inline in prose values; "
        "`_provenance` is its own key.",
    ]
    if node.type == "paragraph_field":
        others = [p.get("name") for p in (schema.get("paragraph_fields") or [])
                  if isinstance(p, dict) and p.get("name") and p.get("name") != fname]
        lines.append(f"You are writing field `{fname}`. Sibling fields "
                     f"covered in parallel: {', '.join(others)}.")
        if shape == "dict":
            lines.append(
                "Return JSON: an object with EXACTLY these keys, in "
                "this order, verbatim (no synonyms, no additions, no "
                "omissions): " + ", ".join(subfields)
                + ', plus "_provenance": ["<ref mark>", ...].')
            lines.append("Return ONLY the JSON object.")
        elif shape == "list_of_dicts":
            keys = [sf.get("name") for sf in item_subfields
                    if isinstance(sf, dict)]
            lines.append(
                'Return JSON: {"items": [{'
                + ", ".join(f'"{k}": ...' for k in keys)
                + ', "_provenance": ["<ref mark>", ...]}, ...]}. '
                "Each item uses EXACTLY these keys verbatim.")
            enums = {sf["name"]: sf["enum"] for sf in item_subfields
                     if isinstance(sf, dict) and sf.get("enum")}
            if enums:
                lines.append("ENUM CONSTRAINTS (exact tokens, no "
                             "synonyms, no display labels): "
                             + json.dumps(enums))
        elif shape == "grid_table":
            lines.append(
                'Return JSON: {"<row>": {"<col>": ["<ref mark>", ...], '
                "...}, ...} using EXACTLY the declared row and column "
                "keys. EVERY cell value is an ARRAY OF REF MARKS — the "
                "retrieval-set members that belong in that cell "
                "(selection is your judgment; an empty cell is []). "
                "A mark is EXACTLY an S-numbered ref (like \"S97\") "
                "copied from the retrieval set — NEVER a name, never "
                "a description. NEVER restate names or details — the "
                "engine expands the marks to the full records.")
        else:
            lines.append('Return JSON: {"text": "...", "_provenance": '
                         '["<ref mark>", ...]}.')
    elif node.type == "header_field":
        lines.append(f"You are filling header field `{fname}`.")
        lines.append('Return JSON: {"text": "<the value — typically a '
                     'short string>", "_provenance": ["<ref mark>", '
                     '...]}.')
    elif node.type == "row_field":
        lines.append(f"You are filling column `{fname}` for ALL rows.")
        if row_ids:
            lines.append(
                f"Emit a JSON object with EXACTLY these {len(row_ids)} "
                "keys (the selected row `ref` marks, verbatim): "
                + ", ".join(f'"{r}"' for r in row_ids)
                + ". Empty string for a no-value row — never filler.")
        else:
            lines.append(
                "Emit a JSON object mapping each row's `ref` mark "
                "(copied VERBATIM from the row payload) to this "
                "column's value. Never invent marks; omit rows you "
                "have nothing for.")
        spec = (schema.get("row_fields") or {}).get(fname) or {}
        if spec.get("enum"):
            lines.append("Values MUST be one of these exact tokens: "
                         + ", ".join(repr(v) for v in spec["enum"]) + ".")
        lines.append(
            'Additionally include the key "_provenance": ["<ref mark>", '
            "...] listing the retrieval-set marks this column drew on "
            "(marks only, copied verbatim; it is not a row).")
        lines.append("Return ONLY the JSON object.")
    note = _config_note(schema)
    if note:
        lines.append(note)
    # Registry + per-product hard rules LAST — freshest in attention.
    rules = hard_rules_for(schema.get("name", product_name),
                           schema.get("hard_rules") or [])
    if rules:
        lines.append("")
        lines.append("---")
        lines.append("HARD RULES — read these LAST, apply to every "
                     "field you emit:")
        for r in rules:
            lines.append("")
            lines.append(r)
    return "\n".join(lines)


def _field_spec_for(node, schema: dict) -> dict:
    fname = node.metadata.get("field_name", "")
    if node.type == "header_field":
        return (schema.get("header_fields") or {}).get(fname) or {}
    if node.type == "row_field":
        return (schema.get("row_fields") or {}).get(fname) or {}
    for pf in schema.get("paragraph_fields") or []:
        if isinstance(pf, dict) and pf.get("name") == fname:
            return pf
    return {}


def _user_prompt(node, schema: dict, resolved: dict[str, Any],
                 marks: "MarkTable",
                 prior_fields: Optional[dict] = None,
                 prefilled: Optional[dict] = None) -> str:
    """SHARED -> PER-FIELD block order (prefix-cache discipline):
    (1) dep payloads sorted by dep id — presented through the MARKS
    VIEW (`ref` marks, no system identifiers), (2) prior sibling
    fields for wave-2 synthesis, (3) FIELD GUIDANCE, (4) subfield
    guidance, (5) the write-now tail."""
    fname = node.metadata.get("field_name", node.id)
    spec = _field_spec_for(node, schema)
    parts: list[str] = []
    filtered = _apply_field_filters(node, schema, resolved)
    if filtered:
        parts.append("=== RETRIEVAL SET (the closed set you may cite, "
                     "by `ref` mark) ===")
        for dep_id in sorted(filtered):
            parts.append(
                f"# {dep_id}\n"
                f"{_serialize_payload(marks.view(filtered[dep_id]))}")
    if prefilled:
        parts.append("=== SUBFIELDS ALREADY RESOLVED BY THE ENGINE "
                     "(do NOT emit these keys) ===")
        parts.append(_serialize_payload(prefilled))
    if prior_fields:
        parts.append("=== FIELDS ALREADY WRITTEN (context for synthesis; "
                     "cite retrieval ids, never field names) ===")
        parts.append(_serialize_payload(prior_fields))
    guidance = spec.get("guidance", "") or ""
    if guidance:
        parts.append(f"=== FIELD GUIDANCE ({fname}) ===\n{guidance}")
    sub_g = spec.get("subfield_guidance")
    if isinstance(sub_g, dict) and sub_g:
        parts.append("SUBFIELD GUIDANCE: " + json.dumps(sub_g))
    for sf in (spec.get("item_subfields") or []):
        if not isinstance(sf, dict):
            continue
        line = (f"- `{sf.get('name')}` ({sf.get('render_label', '')}, "
                f"required={sf.get('required', True)}): "
                f"{sf.get('guidance', '')}")
        parts.append(line)
        nested = sf.get("subfields") or []
        if nested:
            strict = sf.get("strict_subfields", True)
            if strict:
                parts.append(
                    f"  Inside `{sf.get('name')}`: a JSON object with "
                    f"EXACTLY these keys verbatim: {', '.join(nested)}")
            else:
                parts.append(
                    f"  Inside `{sf.get('name')}`: pick the doctrinally-"
                    f"applicable subset of this EXACT key vocabulary "
                    f"(omit inapplicable keys entirely, never empty "
                    f"strings): {', '.join(nested)}")
            for nk, ng in (sf.get("subfield_guidance") or {}).items():
                parts.append(f"    - `{nk}`: {ng}")
    parts.append(f"=== WRITE THE VALUE FOR `{fname}` NOW ===")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Per-field execution
# ---------------------------------------------------------------------------

async def _call_llm(sys_p: str, user_p: str, max_tokens: int) -> tuple[str, str]:
    return await llm_chain.complete(user_p, sys_p, max_tokens=max_tokens)


def _parse_field(node, schema: dict, content: str):
    """Parse per the field's declared shape. Malformed structured JSON
    returns the EMPTY container (never the raw string downstream)."""
    spec = _field_spec_for(node, schema)
    shape = spec.get("shape", "string")
    if node.type == "row_field":
        parsed = _try_json(content)
        return parsed if isinstance(parsed, dict) else None
    parsed = _try_json(content)
    if parsed is None:
        return None
    return parsed


_MARK_SPLIT_RE = re.compile(r"[,\s]+")
_MARK_LIST_RE = re.compile(r"S\d+(?:[,\s]+S\d+)*")


def _split_marks(entries) -> list[str]:
    """Writer-drift absorber for LIST ENCODING only: a valid mark list
    sometimes arrives comma-joined inside one string ("S6, S61"). Split
    to individual tokens — validation against the closed set stays
    strict, so an invented mark still fails the field."""
    out: list[str] = []
    for x in entries:
        for tok in _MARK_SPLIT_RE.split(str(x)):
            if tok:
                out.append(tok)
    return out


def _field_provenance(data: Any) -> list[str]:
    prov: list[str] = []
    if isinstance(data, dict):
        p = data.get("_provenance")
        if isinstance(p, list):
            prov.extend(_split_marks(p))
        items = data.get("items")
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    ip = it.get("_provenance")
                    if isinstance(ip, list):
                        prov.extend(_split_marks(ip))
    return prov


def _validate_field(node, schema: dict, data: Any) -> Optional[str]:
    """Shape/enum/required validation. Returns an error string or None."""
    spec = _field_spec_for(node, schema)
    shape = spec.get("shape", "string")
    fname = node.metadata.get("field_name", node.id)
    if node.type == "row_field":
        if not isinstance(data, dict):
            return f"column {fname}: not a JSON object of row values"
        return None
    if node.type == "header_field":
        if not isinstance(data, dict) or not str(
                data.get("text") or "").strip():
            return f"header {fname}: empty text"
        return None
    if shape == "dict":
        if not isinstance(data, dict):
            return f"field {fname}: not a JSON object"
        missing = [s for s in (spec.get("subfields") or [])
                   if not str(data.get(s) or "").strip()]
        if missing and spec.get("required", True):
            return f"field {fname}: missing subfields {missing}"
        return None
    if shape == "grid_table":
        if not isinstance(data, dict):
            return f"field {fname}: not a JSON grid object"
        return None
    if shape == "list_of_dicts":
        items = data.get("items") if isinstance(data, dict) else None
        if items is None and isinstance(data, list):
            items = data
        if not isinstance(items, list) or (spec.get("required", True)
                                           and not items):
            return f"field {fname}: no items"
        for it in items or []:
            if not isinstance(it, dict):
                continue
            for sf in (spec.get("item_subfields") or []):
                if not isinstance(sf, dict) or "enum" not in sf:
                    continue
                v = it.get(sf["name"])
                if v not in (None, "") and v not in sf["enum"]:
                    return (f"field {fname}: illegal enum value {v!r} "
                            f"for {sf['name']}")
        return None
    # string shape
    if isinstance(data, dict) and not str(data.get("text") or "").strip():
        return f"field {fname}: empty text"
    return None


async def _resolve_mechanical_source(src: str, project_id: UUID,
                                     marks: "MarkTable"
                                     ) -> tuple[str, str]:
    """clause:<kind>:<query> / graphic:<kind>:<field> — the
    writer-involvement law's engine-resolved sources. Returns
    (value, mark). Resolving nothing is an INGEST GAP and fails
    visibly."""
    from app.services.products import retrieval
    if src.startswith("clause:"):
        body = src[len("clause:"):]
        kind, _, query = body.partition(":")
        row = await retrieval.fetch_clause(
            project_id, kind or None, query)
        if row is None:
            raise ValueError(
                f"mechanical source {src!r} resolved no clause — "
                "ingest gap: mint the clause in the world model")
        return str(row.get("text") or ""), marks.add_row(row)
    if src.startswith("graphic:"):
        body = src[len("graphic:"):]
        kind, _, field = body.partition(":")
        row = await retrieval.fetch_graphic(project_id, kind)
        if row is None:
            raise ValueError(
                f"mechanical source {src!r} resolved no {kind} "
                "graphic — the project map does not carry one")
        value = row.get(field or "name")
        if value in (None, ""):
            raise ValueError(
                f"mechanical source {src!r}: the {kind} graphic "
                f"carries no '{field}'")
        return str(value), marks.add_row(row)
    raise ValueError(f"unknown mechanical source {src!r}")


def _resolve_name_tokens(txt: str, marks: "MarkTable"):
    """Closed-set name resolution: a token (or a compound joined with
    '/' or ';') resolves ONLY when every part matches exactly one
    member's text (case-insensitive, leading article stripped).
    Returns the mark list or None — nothing outside the set can ever
    resolve."""
    # Marks embedded ANYWHERE in the token win — the model cited them,
    # wrapped in prose ("Name (annotation) (S126, S184)"). Extraction
    # is mechanical; downstream validation still enforces the set.
    embedded = re.findall(r"\bS\d+\b", txt)
    if embedded:
        return embedded
    parts = [p.strip() for p in re.split(r"[/;]", txt) if p.strip()]
    if not parts:
        return None
    out = []
    for part in parts:
        norm = part.lower().removeprefix("the ").strip()
        matches = [m for m, e in marks.table.items()
                   if (e.get("text") or "").strip().lower()
                   .removeprefix("the ").strip() == norm]
        if len(matches) != 1:
            return None
        out.append(matches[0])
    return out


async def _finish_grid_field(node, schema: dict, data: dict,
                             marks: "MarkTable", fname: str,
                             tier, append_log) -> tuple[Any, Any]:
    """Shared grid finisher: ref-cell expansion (marks -> member text,
    exact-unique name resolution inside the closed set), per-cell
    provenance, validation, and the citation contract."""
    expanded: dict[str, Any] = {}
    cell_prov: dict[str, Any] = {}
    for rk, rv in data.items():
        if rk == "_provenance":
            expanded[rk] = rv
            continue
        if not isinstance(rv, dict):
            expanded[rk] = rv
            continue
        row_out: dict[str, Any] = {}
        row_prov: dict[str, Any] = {}
        for ck, cv in rv.items():
            if ck == "_provenance":
                row_out[ck] = cv
                continue
            raw_elems = (cv if isinstance(cv, list)
                         else [cv] if isinstance(cv, str)
                         and cv.strip() else [])
            refs: list = []
            for elem in raw_elems:
                txt = str(elem).strip()
                if re.fullmatch(r"[\[\]{}()\s,\-]*", txt):
                    continue  # bracket/punctuation noise = empty
                if _MARK_LIST_RE.fullmatch(txt):
                    refs.extend(_MARK_SPLIT_RE.split(txt))
                    continue
                # Names are what a language model produces (the
                # 36ac lesson). An EXACT, UNIQUE match to a
                # closed-set member's text resolves to its mark —
                # mechanical, deterministic, and nothing outside
                # the set can ever resolve. Anything else surfaces
                # verbatim in the violation.
                resolved_parts = _resolve_name_tokens(txt, marks)
                if resolved_parts is not None:
                    refs.extend(resolved_parts)
                else:
                    refs.append(txt)
            refs = [r for r in refs if r]
            if refs:
                bad_refs = [m for m in refs if m not in marks.table]
                if bad_refs:
                    raise ValueError(
                        f"field {fname}: cell {rk}/{ck} cites "
                        f"marks outside the retrieval set "
                        f"{bad_refs[:5]}")
                row_out[ck] = "; ".join(
                    (marks.table[m]["text"] or "")[:80] or m
                    for m in refs)
                row_prov[ck] = refs
            elif isinstance(cv, str):
                row_out[ck] = cv
        if row_prov:
            row_out["_provenance"] = row_prov
            cell_prov[rk] = row_prov
        expanded[rk] = row_out
    if cell_prov:
        all_cell_marks = sorted({m for r in cell_prov.values()
                                 for refs in r.values()
                                 for m in refs})
        existing = expanded.get("_provenance")
        if isinstance(existing, list):
            existing.extend(m for m in all_cell_marks
                            if m not in existing)
        else:
            expanded["_provenance"] = all_cell_marks
    data = expanded
    verr = _validate_field(node, schema, data)
    if verr is not None:
        raise ValueError(verr)
    prov = _field_provenance(data)
    bad = [p2 for p2 in prov if p2 not in marks.table]
    if bad:
        raise ValueError(
            f"field {fname}: cited marks outside the retrieval set "
            f"{bad[:5]}")
    await append_log(f"field {fname}: grid expanded from ref cells")
    return _map_banned_literals(data), tier


async def _run_item_rows_field(node, schema: dict, product_name: str,
                               project_id: UUID,
                               resolved: dict[str, Any],
                               marks: "MarkTable",
                               prior_fields: dict,
                               append_log: Callable) -> tuple[Any, str]:
    """A paragraph list field with `item_rows`: the ENGINE builds the
    item skeletons mechanically from the retrieval rows (names, grids,
    identifiers pass through — the writer-involvement law), and the
    model emits ONLY the analytical columns, keyed by the rows' ref
    marks. Selection is the model's judgment: a row it omits is not in
    the product. Output per row is tiny; nothing structured is ever
    transcribed by the model."""
    fname = node.metadata.get("field_name", node.id)
    spec = _field_spec_for(node, schema)
    cfg = spec.get("item_rows") or {}
    reads = cfg.get("reads") or []
    mech_map = cfg.get("mechanical") or {}
    analytical = [a for a in (cfg.get("analytical") or [])]
    sub_by_name = {sf.get("name"): sf
                   for sf in (spec.get("item_subfields") or [])
                   if isinstance(sf, dict)}

    pool: list[dict] = []
    seen_ids: set = set()
    for token in reads:
        payload = resolved.get(f"read:{token}")
        if not isinstance(payload, dict):
            continue
        for key in ("entities", "units", "rows"):
            for row in (payload.get(key) or []):
                rid = str((row or {}).get("id") or "")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    pool.append(row)
    by_ref = {}
    for row in pool:
        ref = marks.mark_for(row.get("id"))
        if ref:
            by_ref[ref] = row
    if not by_ref:
        await append_log(f"field {fname}: item_rows pool is empty — "
                         "nothing to classify")
        return {"items": [], "_provenance": []}, None

    lines = [
        f"You are the {product_name} per-field writer of a military "
        "training simulation. Every scenario element is fictional "
        "exercise content.",
        f"The engine has ALREADY built the rows for `{fname}` from the "
        "retrieval set. Your ONLY job is judgment: decide WHICH "
        "candidate rows belong in this section, and fill the "
        "analytical columns for those rows. Never restate names, "
        "grids, or identifiers — the engine carries them.",
        'Return JSON: {"<ref mark>": {'
        + ", ".join(f'"{a}": ...' for a in analytical)
        + ', "_provenance": ["<ref mark>", ...]}, ...} — one entry per '
        "row you SELECT (omit rows that do not belong; omission is a "
        "judgment, not an error). Keys are the candidate rows' `ref` "
        "marks copied VERBATIM; a mark is EXACTLY one of the "
        "S-numbered refs (like \"S7\").",
    ]
    enums = {a: sub_by_name[a]["enum"] for a in analytical
             if a in sub_by_name and sub_by_name[a].get("enum")}
    if enums:
        lines.append("ENUM CONSTRAINTS (exact tokens): "
                     + json.dumps(enums))
    for a in analytical:
        g = (sub_by_name.get(a) or {}).get("guidance")
        if g:
            lines.append(f"- `{a}`: {g}")
    note = _config_note(schema)
    if note:
        lines.append(note)
    rules = hard_rules_for(schema.get("name", product_name),
                           schema.get("hard_rules") or [])
    if rules:
        lines.append("HARD RULES:")
        lines.extend(rules)
    sys_p = "\n".join(lines)

    parts = ["=== CANDIDATE ROWS (select + classify by `ref`) ==="]
    parts.append(_serialize_payload(
        {ref: marks.view(row) for ref, row in sorted(by_ref.items())}))
    guidance = spec.get("guidance", "") or ""
    if guidance:
        parts.append(f"=== FIELD GUIDANCE ({fname}) ===\n{guidance}")
    if prior_fields:
        parts.append("=== FIELDS ALREADY WRITTEN ===")
        parts.append(_serialize_payload(prior_fields))
    parts.append(f"=== SELECT AND CLASSIFY FOR `{fname}` NOW ===")
    user_p = "\n\n".join(parts)

    raw, tier = await _call_llm(sys_p, user_p, 2000)
    data = _try_json(raw)
    if not isinstance(data, dict):
        raise ValueError(
            f"field {fname}: unparseable writer output — fix the "
            "field's prompt or scoping (retries are banned)")
    bad = [k for k in data if k not in by_ref]
    if bad:
        raise ValueError(
            f"field {fname}: selected marks outside the candidate set "
            f"{bad[:5]} — the field's prompt or scoping is wrong")

    prefix = cfg.get("ordinal_id_prefix")
    items: list[dict] = []
    all_marks: list[str] = []
    for i, (ref, cols) in enumerate(sorted(data.items()), start=1):
        if not isinstance(cols, dict):
            continue
        row = by_ref[ref]
        item: dict[str, Any] = {}
        if prefix:
            item["id"] = f"{prefix}{i}"
        for out_key, row_key in mech_map.items():
            v = row.get(row_key)
            if v not in (None, ""):
                item[out_key] = v
        for a in analytical:
            v = cols.get(a)
            if v not in (None, ""):
                item[a] = v
        prov = [ref] + [m for m in _split_marks(cols.get("_provenance")
                                                or []) if m != ref]
        bad_p = [m for m in prov if m not in marks.table]
        if bad_p:
            raise ValueError(
                f"field {fname}: cited marks outside the retrieval "
                f"set {bad_p[:5]}")
        item["_provenance"] = prov
        all_marks.extend(prov)
        items.append(item)
    merged = {"items": items, "_provenance": sorted(set(all_marks))}
    verr = _validate_field(node, schema, merged)
    if verr is not None:
        raise ValueError(verr)
    await append_log(
        f"field {fname}: {len(items)}/{len(by_ref)} rows selected; "
        "mechanical columns engine-filled")
    return _map_banned_literals(merged), tier


async def run_field_node(node, schema: dict, product_name: str,
                         project_id: UUID,
                         resolved: dict[str, Any],
                         marks: "MarkTable",
                         prior_fields: dict,
                         append_log: Callable,
                         row_ids: Optional[list] = None,
                         ) -> tuple[Any, Optional[str]]:
    """Execute one field node. Returns (value, tier|None). Mechanical
    resolution first (the writer-involvement law — no model where no
    judgment); ONE model call where the field is genuinely analytical;
    every contract violation fails visibly (no retries — a needed
    retry means the prompt was bad)."""
    fname = node.metadata.get("field_name", node.id)
    spec = _field_spec_for(node, schema)
    src = (spec.get("source") or "").strip()

    # ---- mechanical resolution (no model runs) -------------------------
    if src.startswith(("clause:", "graphic:")):
        value, mark = await _resolve_mechanical_source(
            src, project_id, marks)
        await append_log(f"field {fname}: engine-resolved "
                         f"({src.split(':', 1)[0]} source)")
        return {"text": value, "_provenance": [mark]}, None
    if node.type == "header_field":
        if src in ("session", "session.user", "constant", "default",
                   "computed", "producer:auto"):
            return None, None  # the engine's header resolver fills these
        if src.startswith("upstream:"):
            return _resolve_upstream_echo(src, resolved), None
        if src.startswith("map:"):
            return None, None  # runner-filled from the render call
    if node.type == "paragraph_field":
        if spec.get("shape") == "map":
            return None, None  # post-merge render owns it
        if spec.get("producer") == "auto":
            return None, None  # mechanical backfill is the producer
        if isinstance(spec.get("item_rows"), dict):
            return await _run_item_rows_field(
                node, schema, product_name, project_id, resolved,
                marks, prior_fields, append_log)
    if node.type == "row_field":
        mech = _mechanical_row_values(node, schema, resolved)
        if mech is not None:
            return mech, None
        if src.startswith("upstream:"):
            echo = _resolve_upstream_echo(src, resolved)
            if echo is not None:
                return echo, None

    # Engine-resolved subfields of a dict field (subfield_sources) —
    # prefilled before the model sees the field; the writer emits only
    # the analytical remainder.
    prefilled: dict[str, Any] = {}
    pre_marks: list[str] = []
    sub_sources = spec.get("subfield_sources") or {}
    if node.type == "paragraph_field" and isinstance(sub_sources, dict):
        for sname, stoken in sub_sources.items():
            value, mark = await _resolve_mechanical_source(
                stoken, project_id, marks)
            prefilled[sname] = value
            pre_marks.append(mark)
        if prefilled:
            await append_log(
                f"field {fname}: {len(prefilled)} subfield(s) "
                "engine-resolved: " + ", ".join(sorted(prefilled)))

    # THE WEM EXEMPLAR FORECAST GRID (2026-07-27 ruling: WEM looks like
    # the exemplar, full stop): the element grid is Open-Meteo data the
    # engine already shaped — the writer never sees or copies it.
    if (node.type == "paragraph_field"
            and spec.get("engine_grid") == "wem_forecast"):
        wx = next((v for v in resolved.values()
                   if isinstance(v, dict)
                   and ("forecast_grid" in v
                        or "forecast_grid_skeleton" in v)), {})
        grid = wx.get("forecast_grid")
        if grid and grid.get("periods"):
            # LIVE branch: the grid is forecast data, engine-shaped.
            prov = []
            snap = wx.get("snapshot") or {}
            m = (marks.mark_for(str(snap.get("id")))
                 if snap.get("id") else None)
            if m:
                prov.append(m)
            await append_log(
                f"field {fname}: engine-constructed (forecast grid; "
                f"{len(grid['periods'])} periods from "
                f"{grid.get('source')})")
            return {"periods": grid["periods"],
                    "as_of_local": grid.get("as_of_local"),
                    "timezone": grid.get("timezone"),
                    "source": grid.get("source"),
                    "_provenance": prov}, None
        # AUTHORED branch (2026-07-27 ruling — nothing invented): the
        # skeleton arrives with climatology baseline cells; the writer
        # OVERLAYS only what the STATED exercise weather supports,
        # citing marks; cells neither source covers render NOT STATED.
        skeleton = wx.get("forecast_grid_skeleton")
        if not skeleton or not skeleton.get("periods"):
            raise ValueError(
                f"field {fname}: no forecast grid and no authored "
                "skeleton resolved — the weather read is broken")
        if wx.get("climatology_unavailable"):
            await append_log(
                f"field {fname}: historical averages UNAVAILABLE "
                f"({wx['climatology_unavailable']}) — baseline cells "
                "empty, stated overlay only")
        periods = skeleton["periods"]
        period_keys = [p["key"] for p in periods]
        member_lines = []
        for group in ("conditions", "clauses", "sections"):
            for r in wx.get(group) or []:
                m = marks.mark_for(str(r.get("id")))
                if m:
                    txt = (r.get("text") or r.get("name")
                           or "").replace("\n", " ")[:120]
                    member_lines.append(f"{m}: {txt}")
        element_rows = [
            ("winds", "WINDS"),
            ("min_ceiling", "MIN CEILINGS"),
            ("min_visibility", "MIN VISIBILITY"),
            ("present_weather", "PRESENT WEATHER"),
            ("temperature", "TEMPERATURE"),
            ("wind_chill_heat_index", "WIND CHILL / HEAT INDEX"),
        ]
        all_marks: list[str] = []
        for ekey, elabel in element_rows:
            sys_r = "\n".join([
                f"You are the {product_name} per-field writer of a "
                "military training simulation OVERLAYING the STATED "
                f"exercise weather onto the `{elabel}` row of a "
                "planning grid whose baseline is historical averages.",
                'Return JSON: {"cells": {"<period key>": "<short '
                'slide cell>", ...}, "_provenance": ["<ref mark>", '
                "...]}. Include ONLY periods the stated weather "
                "actually covers for this element (recurring stated "
                "patterns like morning fog apply to every matching "
                "period) — NEVER invent a value the statements do "
                "not support; omit everything else. Cells are short "
                "slide text (like 'FOG 0500-0800L' or '1-2 MILES'). "
                "_provenance lists the ref marks of the statements "
                "used; an overlay with no marks is invalid."
                + _config_note(schema),
            ])
            raw_r, _tier = await _call_llm(
                sys_r,
                "=== STATED EXERCISE WEATHER (cite by ref mark) ===\n"
                + "\n".join(member_lines)
                + "\n\n=== PERIODS ===\n" + ", ".join(period_keys)
                + f"\n\n=== OVERLAY THE `{elabel}` ROW NOW ===", 500)
            row_data = _try_json(raw_r) or {}
            cells = (row_data.get("cells")
                     if isinstance(row_data, dict) else {}) or {}
            row_marks = [m for m in (row_data.get("_provenance") or [])
                         if isinstance(row_data, dict)]
            bad_keys = [k for k in cells if k not in period_keys]
            if bad_keys:
                raise ValueError(
                    f"field {fname}: element {ekey} emitted unknown "
                    f"period keys {bad_keys[:4]}")
            bad_marks = [m for m in row_marks if m not in marks.table]
            if bad_marks:
                raise ValueError(
                    f"field {fname}: element {ekey} cited marks "
                    f"outside the retrieval set {bad_marks[:4]}")
            if cells and not row_marks:
                raise ValueError(
                    f"field {fname}: element {ekey} overlaid cells "
                    "with no marks cited")
            for p in periods:
                if p["key"] in cells and str(cells[p["key"]]).strip():
                    p[ekey] = str(cells[p["key"]]).strip()
            all_marks.extend(m for m in row_marks
                             if m not in all_marks)
        filled = 0
        for p in periods:
            for ekey, _ in element_rows:
                if not p[ekey]:
                    p[ekey] = "NOT STATED"
                else:
                    filled += 1
        await append_log(
            f"field {fname}: authored grid — climatology baseline + "
            f"stated overlay; {filled} cells carry values, the rest "
            "NOT STATED")
        return {"periods": periods,
                "as_of_local": skeleton.get("as_of_local"),
                "timezone": None,
                "source": skeleton.get("source"),
                "_provenance": all_marks}, "primary"

    # WEM judgment cells (enum_grid): one small call per category ROW
    # returning {period_key: code} against the mechanical element grid
    # — enum-locked, closed period keys, nothing to paraphrase.
    if (node.type == "paragraph_field"
            and isinstance(spec.get("enum_grid"), dict)):
        eg = spec["enum_grid"]
        wx = next((v for v in resolved.values()
                   if isinstance(v, dict) and "forecast_grid" in v), {})
        # The FILLED grid: the sibling forecast_grid field's output
        # (both branches land there — live forecast or authored
        # climatology + stated overlay); raw payload as fallback.
        sibling = (prior_fields or {}).get("forecast_grid")
        grid = (sibling if isinstance(sibling, dict)
                and sibling.get("periods")
                else (wx.get("forecast_grid") or {}))
        periods = grid.get("periods") or []
        if not periods:
            raise ValueError(
                f"field {fname}: enum_grid requires the forecast "
                "grid and none resolved")
        period_keys = [p["key"] for p in periods]
        ctx_lines = [
            f"{p['key']} ({p['day_label']} {p['period_label']}): "
            f"winds {p['winds']}; ceiling {p['min_ceiling']}; "
            f"vis {p['min_visibility']}; wx {p['present_weather']}; "
            f"{p['temperature']}"
            + (f"; {p['wind_chill_heat_index']}"
               if p.get("wind_chill_heat_index") else "")
            for p in periods]
        codes = list(eg.get("codes") or [])
        meanings = eg.get("code_meanings") or {}
        code_help = "; ".join(
            f"'{c}' = {meanings.get(c, c)}" for c in codes)
        out_grid: dict[str, Any] = {}
        tier = None
        for rk in eg.get("rows") or []:
            row_label = (eg.get("row_labels") or {}).get(rk, rk)
            sys_r = "\n".join([
                f"You are the {product_name} per-field writer of a "
                "military training simulation coding ONE ROW of the "
                f"`{fname}` matrix: `{row_label}`.",
                "Return JSON mapping EVERY period key to one code: {"
                + ", ".join(f'"{k}": "<code>"' for k in period_keys)
                + f"}}. Codes (emit the code EXACTLY): {code_help}. "
                "Judge each period's forecast against what the "
                f"`{row_label}` row needs. "
                + (spec.get("guidance") or "") + _config_note(schema),
            ])
            raw_r, tier = await _call_llm(
                sys_r,
                "=== FORECAST PERIODS ===\n" + "\n".join(ctx_lines)
                + f"\n\n=== CODE THE `{row_label}` ROW NOW ===", 400)
            row_data = _try_json(raw_r)
            if not isinstance(row_data, dict):
                raise ValueError(
                    f"field {fname}: row {rk} unparseable writer "
                    "output — fix the prompt or scoping")
            bad_keys = [k for k in row_data if k not in period_keys]
            if bad_keys:
                raise ValueError(
                    f"field {fname}: row {rk} emitted unknown period "
                    f"keys {bad_keys[:4]}")
            bad_codes = [v for v in row_data.values()
                         if v not in codes]
            if bad_codes:
                raise ValueError(
                    f"field {fname}: row {rk} emitted non-enum codes "
                    f"{bad_codes[:4]} (allowed: {codes})")
            out_grid[rk] = {k: row_data.get(k, codes[0])
                            for k in period_keys}
        prov = []
        snap = wx.get("snapshot") or {}
        m = marks.mark_for(str(snap.get("id"))) if snap.get("id") else None
        if m:
            prov.append(m)
        out_grid["_provenance"] = prov
        await append_log(
            f"field {fname}: {len(eg.get('rows') or [])} rows coded "
            f"over {len(period_keys)} periods (enum grid)")
        return out_grid, tier

    # THE MECHANICAL MATRIX (2026-07-27 ruling): a survey grid's cell
    # content is the ASCOPE x PMESII tag JOIN — entities tagged with
    # the column category that are subjects of clauses tagged with the
    # row facet. No model runs: no model can cite outside the set when
    # no model writes the cells. Display = entity names; provenance =
    # each entity's mark plus its supporting clauses' marks.
    if (node.type == "paragraph_field"
            and spec.get("shape") == "grid_table"
            and spec.get("engine_join") == "ascope_pmesii"):
        mspec = (schema.get("matrix_spec")
                 or spec.get("matrix_spec") or {})
        row_axis = list(mspec.get("row_axis") or [])
        col_axis = list(mspec.get("col_axis") or [])
        # The read node's payload key may carry the read: prefix
        # depending on dep normalization — find the join payload by
        # SHAPE, not by key (the 0/48 lesson: a key miss here renders
        # an empty grid silently).
        payload: dict = {}
        for v in resolved.values():
            if isinstance(v, dict) and "join" in v:
                payload = v
                break
        if not payload.get("join"):
            raise ValueError(
                f"field {fname}: the ascope x pmesii join resolved "
                "EMPTY — tags missing (backfill/ingestion) or the "
                "matrix:ascope_pmesii read is not wired into this "
                "field's deps; an all-empty survey grid is never "
                "silently correct")
        names = {e.get("id"): e.get("name") or ""
                 for e in payload.get("entities") or []}
        by_cell: dict[tuple, list] = {}
        for entry in payload.get("join") or []:
            by_cell.setdefault(
                (entry.get("facet"), entry.get("category")),
                []).append(entry)
        expanded: dict[str, Any] = {}
        filled = 0
        for rk in row_axis:
            row_out: dict[str, Any] = {}
            row_prov: dict[str, list] = {}
            for ck in col_axis:
                labels: list[str] = []
                cell_marks: list[str] = []
                for entry in by_cell.get((rk, ck)) or []:
                    em = marks.mark_for(entry.get("entity_id") or "")
                    if em is None:
                        continue
                    labels.append(names.get(entry.get("entity_id"), ""))
                    cell_marks.append(em)
                    for cid in entry.get("clause_ids") or []:
                        cm = marks.mark_for(cid)
                        if cm is not None and cm not in cell_marks:
                            cell_marks.append(cm)
                if labels:
                    row_out[ck] = "; ".join(labels)
                    row_prov[ck] = cell_marks
                    filled += 1
            if row_prov:
                row_out["_provenance"] = row_prov
            expanded[rk] = row_out
        expanded["_provenance"] = sorted(
            {m for r in expanded.values() if isinstance(r, dict)
             for refs in (r.get("_provenance") or {}).values()
             for m in refs},
            key=lambda m: int(m[1:]))
        verr = _validate_field(node, schema, expanded)
        if verr is not None:
            raise ValueError(verr)
        await append_log(
            f"field {fname}: engine-constructed (ascope x pmesii "
            f"join; {filled}/{len(row_axis) * len(col_axis)} cells "
            "populated)")
        return _map_banned_literals(expanded), None

    # grid_table fields emit PER ROW (the structured-data law: small
    # judgment outputs of refs only; the 48-cell single emission
    # produced one loose token per run at length).
    if (node.type == "paragraph_field"
            and spec.get("shape") == "grid_table"):
        mspec = (schema.get("matrix_spec")
                 or spec.get("matrix_spec") or {})
        row_axis = list(mspec.get("row_axis") or [])
        col_axis = list(mspec.get("col_axis") or [])
        if row_axis and col_axis:
            grid: dict[str, Any] = {}
            # A SELECTION task gets a compact candidate INDEX (ref ->
            # short text), never the full payload — the mark-to-item
            # pairing is unmissable and the model has nothing to
            # paraphrase from.
            index_lines = [
                f"{m}: [{e.get('kind')}] "
                + (e.get("text") or "").replace("\n", " ")[:90]
                for m, e in sorted(
                    marks.table.items(),
                    key=lambda kv: int(kv[0][1:]))]
            guidance = spec.get("guidance", "") or ""
            base_user = ("=== CANDIDATE INDEX (cite by the ref mark "
                         "at the line start; texts are previews) ===\n"
                         + "\n".join(index_lines)
                         + (f"\n\n=== FIELD GUIDANCE ===\n{guidance}"
                            if guidance else ""))
            for rk in row_axis:
                sys_r = "\n".join([
                    f"You are the {product_name} per-field writer of a "
                    "military training simulation filling ONE ROW of "
                    f"the `{fname}` matrix: the `{rk}` lens.",
                    'Return JSON: {'
                    + ", ".join(f'"{c}": ["<ref mark>", ...]'
                                for c in col_axis)
                    + "} — EXACTLY these keys. Every cell is an ARRAY "
                    "OF REF MARKS: the retrieval-set members that "
                    "belong in that cell for this lens (an empty cell "
                    "is []). A mark is EXACTLY an S-numbered ref "
                    "(like \"S97\") copied from the retrieval set — "
                    "NEVER a name, description, or paraphrase. The "
                    "engine expands marks to the full records. If no "
                    "candidate covers a concept, OMIT it — an "
                    "incomplete cell beats an invented reference.",
                ])
                raw_r, tier = await _call_llm(
                    sys_r, base_user
                    + f"\n\n=== FILL THE `{rk}` ROW NOW ===", 900)
                row_data = _try_json(raw_r)
                if not isinstance(row_data, dict):
                    raise ValueError(
                        f"field {fname}: row {rk} unparseable writer "
                        "output — fix the prompt or scoping")
                grid[rk] = {k: v for k, v in row_data.items()
                            if k in col_axis}
            data = grid
            # Falls through to the shared grid expansion + validation.
            return await _finish_grid_field(
                node, schema, data, marks, fname, tier,
                append_log)

    # ---- the ONE model call --------------------------------------------
    shape = spec.get("shape", "string")
    subfields = [s for s in (spec.get("subfields") or [])
                 if s not in prefilled]
    item_subfields = spec.get("item_subfields") or []
    sys_p = _system_prompt(product_name, schema, node, shape,
                           subfields, item_subfields, row_ids=row_ids)
    user_p = _user_prompt(node, schema, resolved, marks, prior_fields,
                          prefilled=prefilled or None)
    max_tokens = spec.get("max_tokens") if isinstance(
        spec.get("max_tokens"), int) else _MAX_TOKENS.get(node.type, 400)

    raw, tier = await _call_llm(sys_p, user_p, max_tokens)
    data = _parse_field(node, schema, raw)
    if data is None:
        raise ValueError(
            f"field {fname}: unparseable writer output — fix the "
            "field's prompt or scoping (retries are banned)")
    if prefilled and isinstance(data, dict):
        data.update(prefilled)
        prov = data.get("_provenance")
        if isinstance(prov, list):
            prov.extend(m for m in pre_marks if m not in prov)
        else:
            data["_provenance"] = list(pre_marks)
    # grid_table ref-cell expansion (single-call legacy path).
    if (node.type == "paragraph_field" and shape == "grid_table"
            and isinstance(data, dict)):
        return await _finish_grid_field(
            node, schema, data, marks, fname, tier, append_log)
    verr = _validate_field(node, schema, data)
    if verr is not None:
        raise ValueError(verr)
    # THE CITATION CONTRACT: every cited entry is an engine-assigned
    # mark from the closed set; provenance_required fields must cite.
    prov = _field_provenance(data)
    bad = [p for p in prov if p not in marks.table]
    if bad:
        raise ValueError(
            f"field {fname}: cited marks outside the retrieval set "
            f"{bad[:5]} — the field's prompt or scoping is wrong")
    if spec.get("provenance_required") and not prov:
        raise ValueError(
            f"field {fname}: provenance_required but no marks cited")
    return _map_banned_literals(data), tier


# ---------------------------------------------------------------------------
# The generation entry point
# ---------------------------------------------------------------------------

def _config_note(schema: dict) -> str:
    """The analyst-selected knob block appended to every analytical
    prompt (stashed on the schema copy by write_product). Empty when
    the product declares no knobs."""
    return schema.get("_generation_config_note") or ""


async def write_product(project_id: UUID, product_type_key: str,
                        schema_name: str, schema: dict,
                        upstream_payloads: dict[str, dict],
                        append_log: Callable,
                        record_id: Optional[UUID] = None,
                        generation_config: Optional[dict] = None) -> dict:
    """Run every field of one product. Returns {structured_content,
    citations, tiers, read_tokens}. Raises ValueError (writer_invalid)
    on contract violations; RuntimeError from reads propagates as
    upstream_failed by the engine. record_id scopes record-layer
    capture (the live weather snapshot)."""
    # The knob note travels ON the schema copy so every prompt
    # builder (generic + the custom grid/item paths) can append it
    # without threading a parameter through every call chain.
    declared_knobs = schema.get("config_fields") or {}
    if declared_knobs and generation_config:
        lines = []
        for key, spec in declared_knobs.items():
            val = generation_config.get(key, spec.get("default"))
            labels = {o.get("value"): o.get("label")
                      for o in (spec.get("options") or [])}
            if isinstance(val, list):
                shown = ", ".join(labels.get(v, str(v)) for v in val)
            else:
                shown = labels.get(val, str(val))
            lines.append(f"{spec.get('render_label', key)}: {shown}")
        schema = {**schema, "_generation_config_note": (
            "\nGENERATION CONFIGURATION (analyst-selected): "
            + "; ".join(lines)
            + ". THIS CONFIGURATION IS THE LENS FOR THE WHOLE "
            "PRODUCT: every effect, evaluation criterion, and "
            "conclusion is assessed from this perspective (what "
            "THIS configuration cares about in the terrain, "
            "weather, and threat picture), not from a generic "
            "combined-arms view.")}
        await append_log(
            "generation config: " + "; ".join(lines))
    nodes = dag_parser.parse_dag_from_schema(schema_name, schema)
    warnings = dag_parser.validate_dag(nodes)
    cycles = [w for w in warnings if w.startswith("cycle")]
    if cycles:
        raise RuntimeError(f"DAG cycle in {schema_name}: {cycles}")
    for w in warnings:
        await append_log(f"DAG warning: {w}")
    waves = dag_parser.compute_waves(nodes)
    by_id = {n.id: n for n in nodes}

    completed: dict[str, Any] = {}
    tiers: dict[str, str] = {}

    # Pre-seed upstream deps from the consumed APPROVED editions.
    for n in nodes:
        if n.type != "upstream_dep":
            continue
        name = n.metadata.get("upstream_name", "")
        payload = upstream_payloads.get(name)
        if payload is not None:
            completed[n.id] = payload
        else:
            completed[n.id] = {"_empty": True, "upstream_name": name}
            await append_log(f"upstream {name}: no approved edition "
                             "payload (undeclared ref or optional)")

    # Resolve the read tokens up front (one retrieval pass — the
    # closed set), then distribute per node id. `completed` keeps the
    # RAW payloads (engine-internal, mechanical resolvers key on real
    # ids); prompts render through the marks view.
    tokens = dag_parser.read_tokens(nodes)
    ret = await retrieval.build_retrieval(project_id, tokens,
                                          record_id=record_id)
    for note in ret.get("truncated", []):
        await append_log(f"retrieval: {note}")
    for token, payload in (ret.get("members") or {}).items():
        completed[f"read:{token}"] = payload
    marks = MarkTable()
    marks.ingest_members(ret.get("members") or {})
    marks.ingest_upstreams(upstream_payloads)
    await append_log(
        f"retrieval set marked: {len(marks.table)} citable members")

    product_name = schema.get("name", schema_name)
    row_ids: Optional[list] = None
    sel_field = (schema.get("row_id_selection_field") or "").strip()

    header_out: dict[str, Any] = {}
    rows_by_id: dict[str, dict] = {}
    content: dict[str, Any] = {}
    all_prov: set[str] = set()

    # factor_list products (the TEM's OAKOC rows): the row universe is
    # the SPEC's own closed factor list — row ids ARE the factor
    # tokens, pre-seeded in the SPEC's fixed order so the rendered
    # table keeps it, and every row exists even where a column omits
    # a value.
    row_factors = schema.get("row_factors") or []
    if schema.get("row_source") == "factor_list" and row_factors:
        row_ids = [str(f) for f in row_factors]
        for f in row_ids:
            rows_by_id[f] = {"id": f}

    for wave in waves:
        pending = [nid for nid in wave
                   if nid not in completed and not nid.endswith(".submit")]
        field_nodes = [by_id[nid] for nid in pending
                       if by_id[nid].type in ("header_field", "row_field",
                                              "paragraph_field")]
        info_nodes = [by_id[nid] for nid in pending
                      if by_id[nid].type == "paragraph_row_field"]
        for n in info_nodes:
            completed[n.id] = {"_subfield_info_only": True}
        for n in field_nodes:
            resolved = _resolve_deps(n, completed)
            value, tier = await run_field_node(
                n, schema, product_name, project_id, resolved, marks,
                content, append_log, row_ids=row_ids)
            # LLM row columns come back keyed by `ref` marks — translate
            # to system row ids for the merge (mechanical transposes
            # already carry real ids and marks are never row ids).
            if (n.type == "row_field" and tier is not None
                    and isinstance(value, dict)):
                value = {(marks.id_for(k) or k): v
                         for k, v in value.items()}
            completed[n.id] = value
            fname = n.metadata.get("field_name", n.id)
            if tier:
                tiers[fname] = tier
                await append_log(f"field {fname}: written (tier {tier})")
            # Merge into the emit shape.
            if n.type == "header_field":
                if value is not None:
                    text = (value.get("text") if isinstance(value, dict)
                            else value)
                    if text not in (None, ""):
                        header_out[fname] = text
                    prov = _field_provenance(value) if isinstance(
                        value, dict) else []
                    all_prov.update(prov)
            elif n.type == "row_field":
                if isinstance(value, dict):
                    all_prov.update(_field_provenance(value))
                    for row_id, cell in value.items():
                        # The column-level _provenance list is field
                        # metadata, never a row.
                        if row_id == "_provenance" or cell in (None, ""):
                            continue
                        row = rows_by_id.setdefault(
                            str(row_id), {"id": str(row_id)})
                        row[fname] = cell
            elif n.type == "paragraph_field":
                if value is None:
                    continue
                if isinstance(value, dict) and "items" in value:
                    content[fname] = value.get("items")
                elif isinstance(value, dict) and set(value) <= {"text", "_provenance"}:
                    content[fname] = value.get("text")
                else:
                    content[fname] = value
                all_prov.update(_field_provenance(value))
        # Harvest the writer-selected row list as soon as its header
        # field lands (the HVTL selection gate). Selections are `ref`
        # marks (the writer never sees system ids); they stay marks
        # here because the row-column contract keys on marks too.
        if sel_field and not row_ids:
            sel_val = header_out.get(sel_field)
            if isinstance(sel_val, list):
                row_ids = [str(v) for v in sel_val if v]
            elif isinstance(sel_val, str) and sel_val.strip():
                s = sel_val.strip()
                parsed = _try_json(s) if s.startswith("[") else None
                if isinstance(parsed, list):
                    row_ids = [str(v) for v in parsed if v]
                else:
                    row_ids = [x.strip() for x in s.split(",") if x.strip()]
            if row_ids:
                await append_log(
                    f"row selection: {len(row_ids)} marks from "
                    f"{sel_field}")

    # Engine-computed headers (the writer-involvement law: a value the
    # engine can compute never touches the model). Products generate
    # against the CURRENT picture (§2.8), so the validity window ends
    # at generation time and opens cadence_hours before it.
    computed_headers = {
        name for name, spec in (schema.get("header_fields") or {}).items()
        if isinstance(spec, dict)
        and (spec.get("source") or "").strip() == "computed"}
    if computed_headers:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        cadence = schema.get("cadence_hours") or 24

        def _dtg(dt):
            return dt.strftime("%d%H%MZ %b %Y").upper()

        computed_values = {
            "valid_window_end_dtg": _dtg(now),
            "valid_window_start_dtg": _dtg(now - timedelta(hours=cadence)),
        }
        for name in sorted(computed_headers):
            if name in computed_values and not header_out.get(name):
                header_out[name] = computed_values[name]
                await append_log(f"header {name}: engine-computed")

    if rows_by_id:
        content["rows"] = list(rows_by_id.values())
    if header_out:
        content["header"] = header_out

    # The Sources footer resolves straight off the mark table —
    # mechanical, in-memory, no id round trip. Per-field validation
    # already guaranteed membership.
    return {
        "structured_content": content,
        "citations": marks.citations_for(all_prov),
        "tiers": tiers,
        "read_tokens": tokens,
    }
