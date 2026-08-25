"""Schema-to-DAG parser — the IBL runtime/dag_parser.py ported onto the
world-model read grammar (build-log cont 36v step 1; fifth edition §2.10).

Reads a product SPEC dict (templates/products/<name>.py) and emits a
list of Node objects with explicit depends_on edges. The DAG is derived
from data already in the schema:

  - consumes_artifacts            -> upstream:<Name> nodes
  - row_source                    -> a single world-model read node
                                     (rows depend on it)
  - header_fields[*].source       -> source-token vocabulary parser
  - row_fields[*].source          -> same vocabulary
  - header_fields[*].depends_on   -> explicit read-token /
                                     upstream:<Name> entries
  - row_fields[*].depends_on      -> read tokens / upstream:<Name> /
                                     sibling row_field / header field
  - paragraph_fields[*].depends_on-> read tokens / upstream:<Name> /
                                     sibling paragraph name
  - paragraph_fields[*].item_subfields[*].depends_on -> per-subfield
                                     attachments (informational —
                                     paragraph_row_field nodes for DAG
                                     inspection only)

The cougaar tool vocabulary is DEAD. Explicit depends_on is the ONLY
dep mechanism (IBL removed its guidance-prose regex fallback 2026-05-26
after schema migration; the rewritten SPECs declare world-model tokens
directly — deb934e).

Node id convention:
  - read:<token>            e.g. read:entities:units, read:clauses:episodic,
                            read:map:render, read:weather
  - upstream:<Name>         e.g. upstream:WEM (the APPROVED edition)
  - <Product>.header.<field>
  - <Product>.row_field.<field>
  - <Product>.paragraph.<name>
  - <Product>.submit
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# The world-model read-token vocabulary (templates/__init__.py grammar).
# A depends_on entry matching one of these prefixes (or exact tokens)
# becomes a read node. The token itself is the reader dispatch key —
# retrieval.py resolves each token against the project world model.
READ_TOKEN_PREFIXES: tuple[str, ...] = (
    "entities:",        # entities:<kind> / entities:units[:hostile|:friendly]
                        # / entities:civil / entities:marked
    "clauses:",         # clauses:episodic[:kind]
    "document:",        # document:<TAG> — one source document's clause set
    "map:",             # map:state | map:config | map:render
    "matrix:",          # matrix:ascope_pmesii — the mechanical
                        # ASCOPE x PMESII tag join (2026-07-27 ruling)
)
READ_TOKEN_EXACT: tuple[str, ...] = (
    "documents",        # the project's ingested source documents (clause sets)
    "weather",          # the two-branch weather read (knob-resolved)
    "anchors",          # temporal anchors / phases
)


def is_read_token(token: str) -> bool:
    if not isinstance(token, str) or not token:
        return False
    if token in READ_TOKEN_EXACT:
        return True
    return any(token.startswith(p) for p in READ_TOKEN_PREFIXES)


# row_source token -> the read node the rows iterate over. factor_list is
# a SPEC-internal constant (the TEM's OAKOC rows) — no world-model read.
ROW_SOURCE_READS: dict[str, str] = {
    "entities:units:hostile": "entities:units:hostile",
    "entities:units": "entities:units",
    "entities:marked": "entities:marked",
}


@dataclass
class Node:
    """A DAG node. id is unique within a single product DAG.

    type is one of:
      "read"                — a world-model read (the closed retrieval
                              set's members come from these)
      "upstream_dep"        — an upstream product's APPROVED edition
      "header_field"
      "row_field"
      "paragraph_field"
      "paragraph_row_field" — informational only; never dispatched (the
                              paragraph's one emit authors the whole
                              list_of_dicts); carries subfield→read
                              inheritance for DAG inspection
      "submit"
    """
    id: str
    type: str
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _read_node_id(token: str) -> str:
    return f"read:{token}"


def _upstream_node_id(name: str) -> str:
    return f"upstream:{name}"


# -----------------------------------------------------------------------------
# Source-token vocabulary parser
# -----------------------------------------------------------------------------

def parse_source_token(src: str, consumes: list[str]) -> list[str]:
    """Map one `source: "..."` string to the dep node ids it implies.

      "session" / "session.user"  -> []  (engine context)
      "analytical"                -> []  (LLM-emit; deps come from the
                                          field's explicit depends_on)
      "constant" / "default"      -> []  (literal value)
      "computed"                  -> []  (engine post-merge backfill)
      "entity:<field>"            -> []  (mechanical read off the row's
                                          entity — the row_source dep is
                                          attached at the row-field level)
      "derive:<token>"            -> []  (engine mechanical derivation)
      "producer:auto"             -> []  (post-merge mechanical producer)
      "upstream:<Name>[...]"      -> ["upstream:<Name>"]
      "map:render"                -> ["read:map:render"]
      "header_alias:<f>"          -> sibling header signal (caller
                                     resolves the node id)

    For upstream:<Name>, `consumes` is the sanity list — a ref outside
    consumes_artifacts still gets the edge but the node is flagged
    (surfaces schema gaps at seed-time validation).
    """
    if not src or not isinstance(src, str):
        return []
    src = src.strip()
    if src in ("session", "session.user", "analytical", "constant",
               "default", "computed"):
        return []
    if src.startswith("entity:"):
        return []
    if src.startswith("derive:"):
        return []
    if src.startswith("producer:"):
        return []
    if src.startswith("clause:"):
        # Mechanical scoped clause pull (the writer-involvement law:
        # verbatim fields are engine-resolved, no model runs) — the
        # writer resolves it directly; no read node.
        return []
    if src.startswith("graphic:"):
        # Mechanical graphic-entity field pull — same law.
        return []
    if src.startswith("upstream:"):
        body = src[len("upstream:"):].strip()
        # upstream:<Name> or upstream:<Name>.<path> / upstream:<Name>[...]
        name = body.split(".", 1)[0].split("[", 1)[0].strip()
        if name:
            return [_upstream_node_id(name)]
        return []
    if src.startswith("header_alias:"):
        alias = src[len("header_alias:"):].strip()
        return [f"__header_alias__:{alias}"]
    if is_read_token(src):
        return [_read_node_id(src)]
    # Unknown source token — surface as a sentinel; never silently drop.
    return [f"__unknown_source__:{src}"]


# -----------------------------------------------------------------------------
# Main parser entry
# -----------------------------------------------------------------------------

def parse_dag_from_schema(
    product_type: str,
    schema: dict,
    known_products: set[str] | None = None,
) -> list[Node]:
    """Build the per-product DAG from a SPEC dict.

    Returns nodes in deterministic emit order: read nodes -> upstream
    deps -> header fields -> row fields -> paragraph fields -> submit.
    compute_waves re-sorts topologically.
    """
    if known_products is None:
        known_products = set()

    nodes: list[Node] = []
    seen_ids: set[str] = set()

    def add(node: Node) -> None:
        if node.id in seen_ids:
            for existing in nodes:
                if existing.id == node.id:
                    for d in node.depends_on:
                        if d not in existing.depends_on:
                            existing.depends_on.append(d)
                    existing.metadata.setdefault("merged_from", []).append(
                        node.metadata,
                    )
                    return
        nodes.append(node)
        seen_ids.add(node.id)

    def ensure_dep_node(dep_entry: str, source_label: str) -> str | None:
        """Mint the read/upstream node a depends_on entry names and
        return its node id; None when the entry isn't a read/upstream
        token (caller handles siblings/sentinels)."""
        if dep_entry.startswith("upstream:"):
            name = dep_entry[len("upstream:"):].strip()
            nid = _upstream_node_id(name)
            if nid not in seen_ids:
                add(Node(
                    id=nid, type="upstream_dep", depends_on=[],
                    metadata={"upstream_name": name,
                              "source": source_label,
                              "declared": name in consumes},
                ))
            return nid
        if is_read_token(dep_entry):
            nid = _read_node_id(dep_entry)
            if nid not in seen_ids:
                add(Node(
                    id=nid, type="read", depends_on=[],
                    metadata={"token": dep_entry, "source": source_label},
                ))
            return nid
        return None

    consumes: list[str] = list(schema.get("consumes_artifacts") or [])

    # 1. Upstream deps: one node per consumes entry, plus every
    #    upstream:<Name> source token whose target is NOT in consumes
    #    (flagged — surfaces schema gaps; the engine's hard-refuse only
    #    covers registry depends_on, so an undeclared upstream ref is a
    #    seed-time warning).
    upstream_from_sources: set[str] = set()
    for _fname, fspec in (schema.get("header_fields") or {}).items():
        if isinstance(fspec, dict):
            src = fspec.get("source", "")
            if isinstance(src, str) and src.startswith("upstream:"):
                body = src[len("upstream:"):].strip()
                name = body.split(".", 1)[0].split("[", 1)[0].strip()
                if name:
                    upstream_from_sources.add(name)
    for _fname, fspec in (schema.get("row_fields") or {}).items():
        if isinstance(fspec, dict):
            src = fspec.get("source", "")
            if isinstance(src, str) and src.startswith("upstream:"):
                body = src[len("upstream:"):].strip()
                name = body.split(".", 1)[0].split("[", 1)[0].strip()
                if name:
                    upstream_from_sources.add(name)
    all_upstreams = list(consumes)
    for name in sorted(upstream_from_sources):
        if name not in all_upstreams:
            all_upstreams.append(name)
    for name in all_upstreams:
        src_label = ("consumes_artifacts" if name in consumes
                     else "source_token_orphan")
        add(Node(
            id=_upstream_node_id(name),
            type="upstream_dep",
            depends_on=[],
            metadata={"upstream_name": name, "source": src_label,
                      "declared": name in consumes},
        ))

    # 2. row_source -> read node (when it maps to a world-model read).
    row_source = schema.get("row_source")
    row_source_read_dep: str | None = None
    if row_source and row_source in ROW_SOURCE_READS:
        token = ROW_SOURCE_READS[row_source]
        nid = _read_node_id(token)
        add(Node(
            id=nid, type="read", depends_on=[],
            metadata={"token": token, "source": "row_source",
                      "row_source": row_source},
        ))
        row_source_read_dep = nid

    # 3. Header fields.
    header_fields: dict = schema.get("header_fields") or {}
    header_field_ids: dict[str, str] = {
        fname: f"{product_type}.header.{fname}" for fname in header_fields
    }

    for fname, fspec in header_fields.items():
        if not isinstance(fspec, dict):
            continue
        node_id = header_field_ids[fname]
        src = fspec.get("source", "")
        deps = parse_source_token(src, consumes)
        resolved_deps: list[str] = []
        for d in deps:
            if d.startswith("__header_alias__:"):
                alias = d.split(":", 1)[1]
                if alias in header_field_ids:
                    resolved_deps.append(header_field_ids[alias])
                else:
                    resolved_deps.append(f"__unresolved_header_alias__:{alias}")
            elif d.startswith("upstream:") or d.startswith("read:"):
                # Ensure the node exists (source-token minted upstreams
                # were pre-minted above; read tokens may not be).
                nid = ensure_dep_node(
                    d[len("read:"):] if d.startswith("read:") else d,
                    f"source:{node_id}")
                resolved_deps.append(nid or d)
            else:
                resolved_deps.append(d)
        guidance = fspec.get("guidance", "") or ""
        for dep_entry in fspec.get("depends_on", []) or []:
            if not isinstance(dep_entry, str) or not dep_entry:
                continue
            nid = ensure_dep_node(dep_entry, f"depends_on:{node_id}")
            if nid is not None:
                if nid not in resolved_deps:
                    resolved_deps.append(nid)
            elif dep_entry in header_field_ids and dep_entry != fname:
                sib = header_field_ids[dep_entry]
                if sib not in resolved_deps:
                    resolved_deps.append(sib)
            else:
                resolved_deps.append(f"__unresolved_header_dep__:{dep_entry}")
        add(Node(
            id=node_id,
            type="header_field",
            depends_on=resolved_deps,
            metadata={
                "field_name": fname,
                "source_token": src,
                "required": fspec.get("required", False),
                "guidance_brief": (guidance[:80] + "...") if len(guidance) > 80 else guidance,
            },
        ))

    # 4. Row fields — one node per row_field; the executor fans out
    #    across rows at run time.
    row_fields: dict = schema.get("row_fields") or {}
    for fname, fspec in row_fields.items():
        if not isinstance(fspec, dict):
            continue
        node_id = f"{product_type}.row_field.{fname}"
        src = fspec.get("source", "")
        deps = [d for d in parse_source_token(src, consumes)
                if not d.startswith("__")]
        # Ensure source-token nodes exist.
        ensured: list[str] = []
        for d in deps:
            nid = ensure_dep_node(
                d[len("read:"):] if d.startswith("read:") else d,
                f"source:{node_id}")
            ensured.append(nid or d)
        deps = ensured
        # Every row_field implicitly depends on the row_source read.
        if row_source_read_dep and row_source_read_dep not in deps:
            deps.append(row_source_read_dep)
        guidance = fspec.get("guidance", "") or ""
        for dep_entry in (fspec.get("depends_on") or []):
            if not isinstance(dep_entry, str) or not dep_entry:
                continue
            nid = ensure_dep_node(dep_entry, f"depends_on:{node_id}")
            if nid is not None:
                if nid not in deps:
                    deps.append(nid)
            elif dep_entry in row_fields:
                sibling_id = f"{product_type}.row_field.{dep_entry}"
                if sibling_id not in deps:
                    deps.append(sibling_id)
            elif dep_entry in header_fields:
                # Cross-shape dep — a row_field waits on a header field
                # (the HVTL selection gate). Header node id format is
                # `{product_type}.header.{fname}`.
                header_id = f"{product_type}.header.{dep_entry}"
                if header_id not in deps:
                    deps.append(header_id)
            else:
                deps.append(f"__unresolved_row_field_dep__:{dep_entry}")
        add(Node(
            id=node_id,
            type="row_field",
            depends_on=deps,
            metadata={
                "field_name": fname,
                "source_token": src,
                "required": fspec.get("required", False),
                "view": fspec.get("view"),
                "guidance_brief": (guidance[:80] + "...") if len(guidance) > 80 else guidance,
                # The parser MUST propagate batch_group or the executor
                # never co-fires (the HVTL six-serial-calls lesson).
                "batch_group": fspec.get("batch_group") or "",
            },
        ))

    # 5. Paragraph fields.
    paragraph_fields = schema.get("paragraph_fields") or []
    paragraph_ids: dict[str, str] = {}
    for pf in paragraph_fields:
        if isinstance(pf, dict) and pf.get("name"):
            paragraph_ids[pf["name"]] = f"{product_type}.paragraph.{pf['name']}"

    def _walk_item_subfields(item_subfields: list,
                             parent_path: str,
                             parent_inherited_deps: list[str],
                             ) -> tuple[list[tuple[str, str, str, list[str]]], list[str]]:
        """Recursively walk item_subfields; children inherit parent deps;
        child deps roll UP into the parent. Returns (row_specs,
        all_deps_seen_in_tree)."""
        row_specs: list[tuple[str, str, str, list[str]]] = []
        tree_deps: list[str] = list(parent_inherited_deps)
        if not item_subfields:
            return row_specs, tree_deps
        for sf in item_subfields:
            if not isinstance(sf, dict):
                continue
            sf_name = sf.get("name") or ""
            if not sf_name:
                continue
            sf_guidance = sf.get("guidance", "") or ""
            sf_own_deps: list[str] = []
            for dep_entry in (sf.get("depends_on") or []):
                if not isinstance(dep_entry, str) or not dep_entry:
                    continue
                nid = ensure_dep_node(
                    dep_entry, f"depends_on:{parent_path}.row.{sf_name}")
                if nid is not None:
                    sf_own_deps.append(nid)
                elif dep_entry in header_fields:
                    # Cross-shape: item subfield waits on a header field
                    # (CA engagement rows gate on the BDA selection).
                    sf_own_deps.append(f"{product_type}.header.{dep_entry}")
                else:
                    sf_own_deps.append(
                        f"__unresolved_item_subfield_dep__:{dep_entry}")
            sf_aggregated = list(parent_inherited_deps)
            for d in sf_own_deps:
                if d not in sf_aggregated:
                    sf_aggregated.append(d)
            child_specs, child_tree_deps = _walk_item_subfields(
                sf.get("item_subfields") or [],
                parent_path + "." + sf_name,
                sf_aggregated,
            )
            for d in child_tree_deps:
                if d not in sf_aggregated:
                    sf_aggregated.append(d)
            sf_node_id = f"{parent_path}.row.{sf_name}"
            row_specs.append((sf_node_id, sf_name, sf_guidance, sf_aggregated))
            row_specs.extend(child_specs)
            for d in sf_aggregated:
                if d not in tree_deps:
                    tree_deps.append(d)
        return row_specs, tree_deps

    for pf in paragraph_fields:
        if not isinstance(pf, dict):
            continue
        pname = pf.get("name")
        if not pname:
            continue
        node_id = paragraph_ids[pname]
        para_guidance = pf.get("guidance", "") or ""
        row_specs, _ = _walk_item_subfields(
            pf.get("item_subfields") or [], node_id, [],
        )
        deps: list[str] = []
        for dep_entry in pf.get("depends_on", []) or []:
            if not isinstance(dep_entry, str):
                continue
            nid = ensure_dep_node(dep_entry, f"depends_on:{node_id}")
            if nid is not None:
                if nid not in deps:
                    deps.append(nid)
                continue
            # Sibling paragraph — bare name or the explicit
            # "paragraph.<name>" form some SPECs write.
            sib_name = dep_entry
            if sib_name.startswith("paragraph."):
                sib_name = sib_name[len("paragraph."):]
            if sib_name in paragraph_ids:
                sib_id = paragraph_ids[sib_name]
                if sib_id not in deps:
                    deps.append(sib_id)
            elif dep_entry in header_fields:
                # Cross-shape dep — paragraph waits on a header field
                # (CA's selected_bda_artifact_ids selection gate; the
                # same class as the row_field→header HVTL fix).
                header_id = f"{product_type}.header.{dep_entry}"
                if header_id not in deps:
                    deps.append(header_id)
            else:
                deps.append(f"__unresolved_paragraph_dep__:{dep_entry}")
        add(Node(
            id=node_id,
            type="paragraph_field",
            depends_on=deps,
            metadata={
                "field_name": pname,
                "shape": pf.get("shape"),
                "required": pf.get("required", False),
                "guidance_brief": (para_guidance[:120] + "...") if len(para_guidance) > 120 else para_guidance,
                # Same-batch paragraphs co-fire as ONE LLM call.
                "batch_group": pf.get("batch_group") or "",
            },
        ))
        # Informational per-subfield nodes (never dispatched).
        for row_node_id, row_name, row_guidance, row_deps in row_specs:
            sf_deps: list[str] = [node_id]
            for d in row_deps:
                if d not in sf_deps:
                    sf_deps.append(d)
            add(Node(
                id=row_node_id,
                type="paragraph_row_field",
                depends_on=sf_deps,
                metadata={
                    "field_name": row_name,
                    "parent_paragraph": pname,
                    "guidance_brief": (row_guidance[:120] + "...") if len(row_guidance) > 120 else row_guidance,
                },
            ))

    # 6. Terminal submit node.
    submit_deps: list[str] = [
        n.id for n in nodes
        if n.type in ("header_field", "row_field", "paragraph_field")
    ]
    add(Node(
        id=f"{product_type}.submit",
        type="submit",
        depends_on=submit_deps,
        metadata={"product": product_type},
    ))

    return nodes


# -----------------------------------------------------------------------------
# Validation + wave helpers (ported as-is)
# -----------------------------------------------------------------------------

def validate_dag(nodes: list[Node]) -> list[str]:
    """Return warning strings. Empty list = clean DAG. Cycles are the
    caller's hard error (the executor raises on them)."""
    warnings: list[str] = []
    ids = {n.id for n in nodes}
    for n in nodes:
        for d in n.depends_on:
            if d.startswith("__"):
                warnings.append(f"{n.id}: sentinel dep {d!r}")
            elif d not in ids:
                warnings.append(f"{n.id}: dangling dep {d!r}")
    indeg: dict[str, int] = {n.id: 0 for n in nodes}
    for n in nodes:
        for d in n.depends_on:
            if d in indeg:
                indeg[n.id] += 1
    queue = [nid for nid, deg in indeg.items() if deg == 0]
    visited = 0
    while queue:
        cur = queue.pop()
        visited += 1
        for n in nodes:
            if cur in n.depends_on:
                indeg[n.id] -= 1
                if indeg[n.id] == 0:
                    queue.append(n.id)
    if visited != len(nodes):
        warnings.append(f"cycle detected (visited {visited}/{len(nodes)})")
    return warnings


def compute_waves(nodes: list[Node]) -> list[list[str]]:
    """Wave k contains every node whose deps are all in waves 0..k-1."""
    by_id = {n.id: n for n in nodes}
    placed: dict[str, int] = {}
    waves: list[list[str]] = []
    remaining = set(by_id.keys())
    while remaining:
        wave: list[str] = []
        for nid in list(remaining):
            n = by_id[nid]
            internal_deps = [d for d in n.depends_on if d in by_id]
            if all(d in placed for d in internal_deps):
                wave.append(nid)
        if not wave:
            break
        for nid in wave:
            placed[nid] = len(waves)
            remaining.discard(nid)
        waves.append(sorted(wave))
    return waves


def read_tokens(nodes: list[Node]) -> list[str]:
    """The distinct world-model read tokens this DAG needs — the
    registry's declared_fact_classes cross-check and the retrieval
    dispatch list."""
    out: list[str] = []
    for n in nodes:
        if n.type == "read":
            token = n.metadata.get("token") or n.id[len("read:"):]
            if token not in out:
                out.append(token)
    return out


def upstream_names(nodes: list[Node]) -> list[str]:
    out: list[str] = []
    for n in nodes:
        if n.type == "upstream_dep":
            name = n.metadata.get("upstream_name") or n.id[len("upstream:"):]
            if name not in out:
                out.append(name)
    return out
