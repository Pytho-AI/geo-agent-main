#!/usr/bin/env python3
"""Render docs/API.md (human-readable) from docs/openapi.json.

The repo carries the FULL API surface as readable markdown so nobody
needs a running instance to read it. Regenerate after touching routes:

    # refresh the spec from a running instance (or spark):
    curl -sS http://localhost:9845/openapi.json | python3 -m json.tool > docs/openapi.json
    # re-render the markdown:
    python3 scripts/generate_api_docs.py

Output style: grouped by tag, one section per operation, parameters and
schemas as indented bullets (no markdown tables), request/response
bodies as resolved field listings.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "openapi.json"
OUT = ROOT / "docs" / "API.md"

spec = json.loads(SPEC.read_text())
components = spec.get("components", {}).get("schemas", {})


def deref(schema: dict, depth: int = 0) -> dict:
    if not isinstance(schema, dict):
        return {}
    if "$ref" in schema and depth < 8:
        name = schema["$ref"].split("/")[-1]
        return deref(components.get(name, {}), depth + 1)
    return schema


def type_of(schema: dict) -> str:
    schema = schema or {}
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "anyOf" in schema:
        parts = [type_of(s) for s in schema["anyOf"]]
        return " | ".join(p for p in parts if p != "null") or "any"
    t = schema.get("type", "any")
    if t == "array":
        return f"array of {type_of(schema.get('items', {}))}"
    if t == "object" and schema.get("additionalProperties"):
        return "object (free-form)"
    if "enum" in schema:
        return " | ".join(repr(v) for v in schema["enum"])
    if schema.get("format"):
        return f"{t} ({schema['format']})"
    return t


def render_fields(schema: dict, indent: str = "  ", depth: int = 0) -> list[str]:
    """Bullet list of an object schema's fields, one level of nesting."""
    schema = deref(schema)
    lines: list[str] = []
    if "anyOf" in schema:
        # Union (e.g. the GeoOps op union) — render each variant.
        for variant in schema["anyOf"]:
            v = deref(variant)
            title = v.get("title") or type_of(variant)
            lines.append(f"{indent}- **{title}**:")
            lines += render_fields(variant, indent + "  ", depth + 1)
        return lines
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    for name, ps in props.items():
        req = "required" if name in required else "optional"
        desc = (ps.get("description") or deref(ps).get("description") or "").strip()
        default = ps.get("default")
        bits = [type_of(ps), req]
        if default not in (None, "", [], {}):
            bits.append(f"default `{json.dumps(default)}`")
        line = f"{indent}- `{name}` — {', '.join(bits)}"
        if desc:
            line += f". {desc.splitlines()[0]}"
        lines.append(line)
        # One nesting level for inline object fields (not named refs —
        # those get their own definition where first used).
        inner = deref(ps)
        if depth < 1 and inner.get("properties") and "$ref" not in ps:
            lines += render_fields(inner, indent + "  ", depth + 1)
    return lines


def params_block(op: dict) -> list[str]:
    lines = []
    params = op.get("parameters", [])
    if params:
        lines.append("Parameters:")
        for p in params:
            req = "required" if p.get("required") else "optional"
            desc = (p.get("description") or "").strip()
            line = (f"- `{p['name']}` ({p.get('in','query')}) — "
                    f"{type_of(p.get('schema', {}))}, {req}")
            if desc:
                line += f". {desc}"
            lines.append(line)
        lines.append("")
    return lines


def body_block(op: dict) -> list[str]:
    rb = op.get("requestBody")
    if not rb:
        return []
    content = rb.get("content", {})
    for ctype, media in content.items():
        schema = media.get("schema", {})
        label = type_of(schema)
        lines = [f"Request body (`{ctype}`{', ' + label if label not in ('object','any') else ''}):"]
        fields = render_fields(schema)
        lines += fields or ["  - (see schema)"]
        lines.append("")
        return lines
    return []


def response_block(op: dict) -> list[str]:
    lines = []
    responses = op.get("responses", {})
    ok = responses.get("200") or responses.get("201")
    if not ok:
        return lines
    content = ok.get("content", {})
    for ctype, media in content.items():
        schema = media.get("schema", {})
        label = type_of(schema)
        if ctype != "application/json":
            lines.append(f"Response: `{ctype}`")
            lines.append("")
            return lines
        if label in ("object", "any") and not deref(schema).get("properties"):
            return lines
        lines.append(f"Response (`{label}`):")
        fields = render_fields(schema)
        if fields:
            lines += fields
        lines.append("")
        return lines
    return lines


# Group operations by tag, preserving spec order.
by_tag: dict[str, list[tuple[str, str, dict]]] = {}
for path, methods in spec.get("paths", {}).items():
    for method, op in methods.items():
        if method not in ("get", "post", "put", "delete", "patch"):
            continue
        tag = (op.get("tags") or ["untagged"])[0]
        by_tag.setdefault(tag, []).append((method.upper(), path, op))

out: list[str] = []
info = spec.get("info", {})
out.append(f"# {info.get('title', 'Geo-Agent')} — full API")
out.append("")
out.append("Generated from the FastAPI OpenAPI spec — do not hand-edit.")
out.append("Regenerate with `scripts/generate_api_docs.py` (see its")
out.append("docstring). All paths are under the backend's single public")
out.append("surface, port 9845; through a consumer's nginx they appear")
out.append("with the `/geo-api` prefix in place of `/api`.")
out.append("")
out.append("The EXTERNAL integration surface is deliberately tiny — see")
out.append("README.md \"External API\". Everything else here is the")
out.append("embedded map UI's internal API, documented for people working")
out.append("ON geo-agent.")
out.append("")

for tag in sorted(by_tag):
    out.append(f"## {tag}")
    out.append("")
    for method, path, op in by_tag[tag]:
        summary = (op.get("summary") or "").strip()
        out.append(f"### `{method} {path}`")
        out.append("")
        if summary:
            out.append(summary)
            out.append("")
        desc = (op.get("description") or "").strip()
        if desc and desc != summary:
            out.append(desc)
            out.append("")
        out += params_block(op)
        out += body_block(op)
        out += response_block(op)

OUT.write_text("\n".join(out).rstrip() + "\n")
print(f"wrote {OUT} ({len(OUT.read_text().splitlines())} lines, "
      f"{sum(len(v) for v in by_tag.values())} operations)")
