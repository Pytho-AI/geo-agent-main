"""The DOCX walker — python-docx NATIVE (no HTML layer, no convert.js;
user ruling 2026-07-23). Follows exporter.py's render_artifact_html
walk order and conventions as the REFERENCE, emitting python-docx
objects directly:

  - Classification banner in the SECTION HEADER + FOOTER (two-line
    gray Arial centered — the DocEditor/page-chrome convention; the
    body-strip banner was IBL-era duplication and does not port).
  - Title = doctrinal long name (registry label) uppercased; the
    title_field recipe overrides; flush-left (AR 25-50 memo head).
  - AR 25-50 stacked header block (bold label: value paragraphs, NOT
    a kv table); paired-DTG ranges combine into one line; REQUIRED-
    but-empty renders the [ANALYST INPUT REQUIRED] badge; internal-
    view and spatial_overlay fields never render.
  - Per-shape walk: row / lines / matrix / paragraph / structured /
    header_only — schema-generic, zero product branches.
  - Section headings = plain ALL-CAPS bold body-size (weight + case
    convey hierarchy, never fills or size jumps); doctrine refs
    scrubbed from every visible heading.
  - list_of_dicts tables with the column-width heuristic, enum
    humanize, doctrinal cell fills, MGRS coercion; nested-shape items
    render sectioned (per-item bar + kv + child tables); dict shapes
    with subfields render as lettered subparagraphs (a. b. c.).
  - Map paragraph_fields embed the RENDERED BYTES (figure_jpg) with
    no heading (full-width figure); the map_embeds sidecar entry is
    the caller's concern (engine records artifact metadata).
  - Sources section LAST from the resolved citation map (quote-
    bearing clause citations from the closed set).
"""
import io
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.products.walkers.common import (
    FootnoteRegistry, artifact_filename_base, cell_fill_for,
    coerce_mgrs_value, column_weights, display_scalar, humanize,
    humanize_enum_value, label_for_field, maybe_parse_fenced_json,
    normalize_matrix, published_paragraph_fields, published_row_fields,
    strip_doctrine_refs, strip_scaffold_tokens, workpaper_row_fields,
)

log = logging.getLogger(__name__)

_ANALYST_BADGE = "[ANALYST INPUT REQUIRED]"

_HEADER_EXCLUDE_KEYS = {
    "classification", "owner_user_id", "user_id", "session_id",
    "project_id", "artifact_id", "turn_id", "trace_id", "status",
}

_PAIRED_DTG_RANGES = {
    "period_start_dtg": ("period_end_dtg", "Reporting Period"),
    "valid_window_start_dtg": ("valid_window_end_dtg", "Valid Window"),
    "reporting_period_start_z": ("reporting_period_end_z", "Reporting Period"),
    "reporting_period_start": ("reporting_period_end", "Reporting Period"),
    "engagement_window_start": ("engagement_window_end", "Engagement Window"),
    "engagement_window_start_dtg": ("engagement_window_end_dtg",
                                    "Engagement Window"),
}


def _set_cell_shading(cell, hex_fill: str):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _add_banner(doc, classification: str):
    """Two-line page header + footer banner (the convert.js header
    convention, now native): line 1 = classification, line 2 =
    exercise marking; 11pt Arial gray centered, no fill."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor
    marking = (classification or "UNCLASSIFIED").upper()
    lines = [marking, "FOR EXERCISE USE ONLY"]
    for container in (doc.sections[0].header, doc.sections[0].footer):
        para = container.paragraphs[0]
        para.text = ""
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for i, line in enumerate(lines):
            run = para.add_run(("\n" if i else "") + line)
            run.font.size = Pt(11)
            run.font.name = "Arial"
            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)


def _heading(doc, text: str, level: int = 2):
    """ALL-CAPS bold body-size heading (AR 25-50 — weight + case,
    never fills or size jumps). level>=3 keeps mixed case bold."""
    from docx.shared import Pt
    p = doc.add_paragraph()
    label = strip_doctrine_refs(text or "")
    run = p.add_run(label.upper() if level <= 2 else label)
    run.bold = True
    run.font.size = Pt(12) if level <= 2 else Pt(10)
    p.paragraph_format.space_before = Pt(14 if level <= 2 else 10)
    p.paragraph_format.space_after = Pt(6)
    return p


def _badge_run(p):
    from docx.shared import Pt, RGBColor
    run = p.add_run(_ANALYST_BADGE)
    run.bold = True
    run.italic = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0xB0, 0x00, 0x20)
    return run


def _marker(footnotes: FootnoteRegistry, p, citation: str):
    """Superscript numbered marker after the value."""
    n = footnotes.register(citation)
    if not n:
        return
    from docx.shared import Pt, RGBColor
    run = p.add_run(str(n))
    run.font.superscript = True
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x00, 0x33, 0xAA)


def _provenance_for(parent: Optional[dict], field: str) -> str:
    if not isinstance(parent, dict):
        return ""
    prov = parent.get("_provenance")
    if isinstance(prov, dict):
        v = prov.get(field)
        if isinstance(v, list):
            return "; ".join(str(x) for x in v)
        return v or ""
    if isinstance(prov, str):
        return prov
    return ""


def _citation_text(cid: str, citations: dict) -> str:
    c = citations.get(str(cid))
    if isinstance(c, dict):
        return c.get("citation") or c.get("text") or str(cid)
    return str(cid)


def _row_citation(parent: Optional[dict], field: str,
                  citations: dict) -> str:
    """Resolve a row/field _provenance entry — id lists resolve
    through the citation map; strings pass through."""
    raw = _provenance_for(parent, field)
    if not raw:
        # Whole-row provenance (list of ids on the row).
        prov = parent.get("_provenance") if isinstance(parent, dict) else None
        if isinstance(prov, list):
            return " | ".join(_citation_text(x, citations) for x in prov[:4])
        return ""
    if isinstance(raw, str) and raw in citations:
        return _citation_text(raw, citations)
    return raw


def _kv_paragraphs(doc, items: list, parent: Optional[dict],
                   footnotes: FootnoteRegistry, citations: dict,
                   indent_pt: int = 0):
    from docx.shared import Pt
    for it in items:
        label, value, fname = (it if len(it) == 3 else (it[0], it[1], ""))
        p = doc.add_paragraph()
        if indent_pt:
            p.paragraph_format.left_indent = Pt(indent_pt)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(strip_doctrine_refs(str(label)) + ": ")
        run.bold = True
        if value == _ANALYST_BADGE:
            _badge_run(p)
        else:
            p.add_run(display_scalar(value) or "—")
        if fname:
            cite = _row_citation(parent, fname, citations)
            if cite:
                _marker(footnotes, p, cite)


def _table(doc, cols: list[tuple[str, str, dict]], rows: list[dict],
           footnotes: FootnoteRegistry, citations: dict):
    """Flat list_of_dicts table with heuristic widths + fills."""
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Inches, Pt
    if not rows or not cols:
        doc.add_paragraph("—")
        return
    usable_in = 7.0  # 8.5" letter − 0.75" margins
    weights = column_weights([c[0] for c in cols])
    total_w = sum(weights) or 1.0
    widths = [usable_in * w / total_w for w in weights]
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0]
    for i, (name, lbl, _spec) in enumerate(cols):
        cell = hdr.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(strip_doctrine_refs(lbl))
        run.bold = True
        run.font.size = Pt(9)
        _set_cell_shading(cell, "D9D9D9")
        try:
            cell.width = Inches(widths[i])
        except Exception:
            pass
    for r in rows:
        if not isinstance(r, dict):
            continue
        row_cells = table.add_row().cells
        for i, (name, _lbl, spec) in enumerate(cols):
            raw = r.get(name)
            raw = coerce_mgrs_value(raw, spec, name)
            val = humanize_enum_value(raw, spec)
            cell = row_cells[i]
            cell.text = ""
            p = cell.paragraphs[0]
            if val == _ANALYST_BADGE:
                _badge_run(p)
            elif (spec or {}).get("lead_sentence_bold") and isinstance(
                    val, str) and val.strip():
                # Briefing convention: the cell opens with the bolded
                # "so what" sentence; supporting detail follows.
                text = display_scalar(val)
                cut = text.find(". ")
                nl = text.find("\n")
                if 0 <= nl < cut or (cut == -1 and nl != -1):
                    cut = nl
                if cut == -1:
                    lead, rest = text, ""
                else:
                    lead, rest = text[:cut + 1], text[cut + 1:]
                lead_run = p.add_run(lead)
                lead_run.bold = True
                lead_run.font.size = Pt(9)
                if rest:
                    run = p.add_run(rest)
                    run.font.size = Pt(9)
            else:
                run = p.add_run(display_scalar(val))
                run.font.size = Pt(9)
            fill = cell_fill_for(raw if isinstance(raw, str) else None, spec)
            if fill:
                _set_cell_shading(cell, fill)
            cite = _row_citation(r, name, citations)
            if cite:
                _marker(footnotes, p, cite)
            try:
                cell.width = Inches(widths[i])
            except Exception:
                pass


def _visible_cols(item_subfields: list) -> list[tuple[str, str, dict]]:
    cols = []
    for f in item_subfields:
        if isinstance(f, dict):
            if f.get("name") == "_provenance":
                continue
            if f.get("shape") in ("list_of_dicts", "dict"):
                continue
            if (f.get("view") or "published") not in ("published", None):
                continue
            cols.append((f["name"], label_for_field(f["name"], f), f))
        elif isinstance(f, str) and f != "_provenance":
            cols.append((f, humanize(f), {}))
    return cols


def _has_nested(item_subfields: list) -> bool:
    return any(isinstance(f, dict) and f.get("shape") in
               ("list_of_dicts", "dict") for f in item_subfields or [])


def _sectioned_items(doc, value: list, item_subfields: list,
                     footnotes: FootnoteRegistry, citations: dict,
                     level: int = 3):
    """Per-item sections: bar titled by the first scalar subfield,
    scalar kv block, child tables/dicts as sub-blocks."""
    title_field = None
    scalars, bodies = [], []
    for f in item_subfields:
        if not isinstance(f, dict):
            continue
        if f.get("shape") in ("list_of_dicts", "dict"):
            bodies.append(f)
        else:
            scalars.append(f)
            if title_field is None:
                title_field = f
    for idx, it in enumerate(value):
        if not isinstance(it, dict):
            doc.add_paragraph(display_scalar(it))
            continue
        title_val = it.get(title_field["name"]) if title_field else None
        display = None
        if title_val:
            labels = (title_field or {}).get("enum_labels") or {}
            display = labels.get(str(title_val)) or humanize(str(title_val))
            coa_id = it.get("coa_id") or it.get("id")
            lbl = it.get("label")
            if coa_id and (title_field or {}).get("name") != "coa_id":
                display = (f"{humanize(str(coa_id))} — {humanize(str(lbl))}"
                           if lbl else humanize(str(coa_id)))
        if display:
            _heading(doc, display, level=3)
        kv = []
        for sf in scalars:
            if title_field and sf is title_field:
                continue
            v = it.get(sf["name"])
            if v in (None, "", False):
                continue
            kv.append((label_for_field(sf["name"], sf),
                       humanize_enum_value(coerce_mgrs_value(v, sf), sf),
                       sf["name"]))
        if kv:
            _kv_paragraphs(doc, kv, it, footnotes, citations, indent_pt=18)
        for sf in bodies:
            v = it.get(sf["name"])
            if v in (None, "", [], {}):
                continue
            if len(bodies) > 1:
                _heading(doc, label_for_field(sf["name"], sf), level=4)
            if sf.get("shape") == "list_of_dicts" and isinstance(v, list):
                nested_cols = _visible_cols(sf.get("item_subfields") or [])
                if not nested_cols and v and isinstance(v[0], dict):
                    nested_cols = [(k, humanize(k), {}) for k in v[0]
                                   if not k.startswith("_")]
                _table(doc, nested_cols, v, footnotes, citations)
            elif sf.get("shape") == "dict" and isinstance(v, dict):
                keys = (None if sf.get("strict_subfields") is False
                        else sf.get("subfields"))
                items = [(humanize(k), v.get(k), k)
                         for k in (keys or list(v.keys()))
                         if not str(k).startswith("_")
                         and v.get(k) not in (None, "", [], {})]
                _kv_paragraphs(doc, items, v, footnotes, citations,
                               indent_pt=18)


def _paragraph_field(doc, spec: dict, value, parent: dict,
                     footnotes: FootnoteRegistry, citations: dict,
                     figures: Optional[dict] = None, level: int = 2):
    """One schema-declared paragraph_field (the exporter's dispatch)."""
    from docx.shared import Inches, Pt
    name = spec.get("name", "")
    label = strip_scaffold_tokens(spec.get("render_label") or humanize(name))
    shape = spec.get("shape", "string")

    if shape == "map":
        fig = (figures or {}).get(name)
        if fig:
            doc.add_picture(io.BytesIO(fig), width=Inches(6.5))
            cap = doc.add_paragraph()
            run = cap.add_run(f"Figure. {label}")
            run.italic = True
            run.font.size = Pt(8.5)
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        return

    _heading(doc, label, level=level)
    head_cite = _row_citation(parent, name, citations)
    if head_cite and shape not in ("string", ""):
        # Non-string shapes carry the paragraph-level marker on a thin
        # sources line under the heading (tables have no prose tail).
        p = doc.paragraphs[-1]
        _marker(footnotes, p, head_cite)

    if value in (None, "", [], {}):
        doc.add_paragraph("—")
        return

    if shape in ("string", ""):
        if isinstance(value, dict) and "text" in value:
            value = value.get("text")
        if isinstance(value, (list, tuple)):
            for x in value:
                doc.add_paragraph(display_scalar(x), style="List Bullet")
            return
        p = doc.add_paragraph(display_scalar(value))
        if head_cite:
            _marker(footnotes, p, head_cite)
        return

    if shape == "list_of_dicts":
        items = value if isinstance(value, list) else []
        subs = spec.get("item_subfields") or []
        if _has_nested(subs) or spec.get("render_sectioned"):
            _sectioned_items(doc, items, subs, footnotes, citations)
            return
        cols = _visible_cols(subs)
        if not cols and items and isinstance(items[0], dict):
            cols = [(k, humanize(k), {}) for k in items[0]
                    if not k.startswith("_")]
        _table(doc, cols, items, footnotes, citations)
        return

    if shape == "dict":
        sub = spec.get("subfields")
        subfield_specs = spec.get("subfield_specs") or {}
        if isinstance(value, dict):
            nested_present = any(isinstance(v, (dict, list))
                                 for v in value.values())
            if sub or nested_present:
                keys = [k for k in (sub or list(value.keys()))
                        if k in value and not str(k).startswith("_")
                        and value[k] not in (None, "", [], {}, False)]
                for idx, k in enumerate(keys):
                    letter = chr(ord("a") + idx) if idx < 26 else str(idx + 1)
                    sub_label = f"{letter}. {humanize(k)}"
                    raw_v = value[k]
                    sf_meta = subfield_specs.get(k) or {}
                    if isinstance(raw_v, str) and sf_meta.get("enum"):
                        raw_v = humanize_enum_value(raw_v, sf_meta)
                    child_shape = ("list_of_dicts"
                                   if isinstance(raw_v, list)
                                   and raw_v and isinstance(raw_v[0], dict)
                                   else "dict" if isinstance(raw_v, dict)
                                   else "string")
                    _paragraph_field(
                        doc, {"name": k, "shape": child_shape,
                              "render_label": sub_label},
                        raw_v, value, footnotes, citations,
                        figures=figures, level=level + 1)
                return
            items = []
            for k in (sub or list(value.keys())):
                if str(k).startswith("_"):
                    continue
                raw = value.get(k)
                sf_spec = subfield_specs.get(k) or {}
                items.append((humanize(k),
                              humanize_enum_value(raw, sf_spec)
                              if sf_spec.get("enum") else raw, k))
            _kv_paragraphs(doc, items, value, footnotes, citations)
            return
        doc.add_paragraph(display_scalar(value))
        return

    if shape == "grid_table":
        matrix = normalize_matrix(value)
        if isinstance(matrix, dict) and matrix:
            row_axis = list(matrix.keys())
            col_axis: list[str] = []
            for v in matrix.values():
                if isinstance(v, dict):
                    for k in v:
                        if k not in col_axis and not k.startswith("_"):
                            col_axis.append(k)
            _grid(doc, matrix, row_axis, col_axis, footnotes, citations)
            return
        doc.add_paragraph(display_scalar(value))
        return

    # Inferred fallback.
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            cols = [(k, humanize(k), {}) for k in value[0]
                    if not k.startswith("_")]
            _table(doc, cols, value, footnotes, citations)
        else:
            for x in value:
                doc.add_paragraph(display_scalar(x), style="List Bullet")
    elif isinstance(value, dict):
        items = [(humanize(k), v, k) for k, v in value.items()
                 if not str(k).startswith("_")]
        _kv_paragraphs(doc, items, value, footnotes, citations)
    else:
        doc.add_paragraph(display_scalar(value))


def _grid(doc, matrix: dict, row_axis: list, col_axis: list,
          footnotes: FootnoteRegistry, citations: dict):
    from docx.shared import Pt
    table = doc.add_table(rows=1, cols=len(col_axis) + 1)
    table.style = "Table Grid"
    hdr = table.rows[0]
    hdr.cells[0].text = ""
    _set_cell_shading(hdr.cells[0], "D9D9D9")
    for j, c in enumerate(col_axis, start=1):
        cell = hdr.cells[j]
        cell.text = ""
        run = cell.paragraphs[0].add_run(humanize(c))
        run.bold = True
        run.font.size = Pt(9)
        _set_cell_shading(cell, "D9D9D9")
    for rname in row_axis:
        rval = matrix.get(rname) or {}
        cells = table.add_row().cells
        cells[0].text = ""
        run = cells[0].paragraphs[0].add_run(humanize(rname))
        run.bold = True
        run.font.size = Pt(9)
        _set_cell_shading(cells[0], "F2F2F2")
        for j, c in enumerate(col_axis, start=1):
            cv = rval.get(c) if isinstance(rval, dict) else ""
            cell = cells[j]
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(display_scalar(cv))
            run.font.size = Pt(9)
            cite = _row_citation(rval if isinstance(rval, dict) else None,
                                 c, citations)
            if cite:
                _marker(footnotes, p, cite)


def _header_block(doc, header: dict, schema: dict,
                  footnotes: FootnoteRegistry, citations: dict,
                  skip_keys: set):
    header_specs = schema.get("header_fields") or {}
    items: list = []
    pair_seen: set = set()
    for f, spec in header_specs.items():
        if f in _HEADER_EXCLUDE_KEYS or f.startswith("_"):
            continue
        if (spec or {}).get("view") not in ("header", None):
            continue
        if f.startswith("spatial_overlay") or f in skip_keys or f in pair_seen:
            continue
        if f in _PAIRED_DTG_RANGES:
            end_key, combined_label = _PAIRED_DTG_RANGES[f]
            if end_key in header_specs:
                v_start = header.get(f) or ""
                v_end = header.get(end_key) or ""
                pair_seen.add(end_key)
                if v_start or v_end:
                    combined = (f"{v_start} – {v_end}"
                                if v_start and v_end else (v_start or v_end))
                    items.append((combined_label, combined, f))
                    continue
                if ((spec or {}).get("required")
                        or (header_specs.get(end_key) or {}).get("required")):
                    items.append((combined_label, _ANALYST_BADGE, f))
                continue
        v = header.get(f)
        if v in (None, ""):
            spec_default = (spec or {}).get("default")
            if isinstance(spec_default, str) and spec_default:
                from app.services.products.walkers.common import _SafeDict, _SAFE_DICT_RE
                try:
                    substituted = spec_default.format_map(_SafeDict(
                        {k: ("" if val is None else val)
                         for k, val in header.items()}))
                except (ValueError, IndexError):
                    substituted = spec_default
                if substituted and not _SAFE_DICT_RE.search(substituted):
                    items.append((label_for_field(f, spec), substituted, f))
                    continue
            if (spec or {}).get("required"):
                items.append((label_for_field(f, spec), _ANALYST_BADGE, f))
            continue
        items.append((label_for_field(f, spec), v, f))
    for k, v in header.items():
        if (k in _HEADER_EXCLUDE_KEYS or k.startswith("_")
                or k.startswith("spatial_overlay") or k in header_specs
                or k in skip_keys or v in (None, "")):
            continue
        items.append((humanize(k), v, k))
    _kv_paragraphs(doc, items, header, footnotes, citations)


def render_docx(artifact_type: str, schema: dict,
                structured_content: dict, citations: dict,
                figures: Optional[dict] = None,
                project_name: str = "",
                registry_label: str = "") -> bytes:
    """Walk one product into DOCX bytes. `figures` maps map-shape
    paragraph_field names -> rendered JPG bytes. `citations` is the
    resolved closed-set map (id -> {kind, text, citation})."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    sc = structured_content or {}
    header = sc.get("header") or {}
    footnotes = FootnoteRegistry()

    doc = Document()
    for section in doc.sections:
        from docx.shared import Inches
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)

    _add_banner(doc, header.get("classification") or "UNCLASSIFIED")

    long_name = registry_label or schema.get("name", artifact_type)
    title = long_name.upper()
    skip_keys: set = set()
    title_field = schema.get("title_field")
    if title_field:
        base = artifact_filename_base(artifact_type, schema, sc, "")
        if base and base != "artifact":
            title = base.upper()
            skip_keys.add(title_field)

    h1 = doc.add_paragraph()
    run = h1.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
    sub = doc.add_paragraph()
    sub_run = sub.add_run(
        f"{project_name} — generated "
        + datetime.now(timezone.utc).strftime("%d %b %Y %H:%MZ"))
    sub_run.italic = True
    sub_run.font.size = Pt(9)

    _header_block(doc, header, schema, footnotes, citations, skip_keys)

    # Default operational-picture figure: products with NO map-shape
    # paragraph_field still embed the rendered current-picture bytes
    # (the engine passes them under "_figure") right below the header —
    # the OED's map, per the 1b ruling that the OED needs a map too.
    map_field_names = {p.get("name") for p in
                       (schema.get("paragraph_fields") or [])
                       if isinstance(p, dict) and p.get("shape") == "map"}
    default_fig = (figures or {}).get("_figure")
    if default_fig and not map_field_names:
        _heading(doc, "Operational Area")
        doc.add_picture(io.BytesIO(default_fig), width=Inches(6.5))
        cap = doc.add_paragraph()
        cap_run = cap.add_run("Figure. Operational area — current picture "
                              "at generation time")
        cap_run.italic = True
        cap_run.font.size = Pt(8.5)
        from docx.enum.text import WD_ALIGN_PARAGRAPH as _WAP
        cap.alignment = _WAP.CENTER

    shape = schema.get("shape", "")
    paragraph_fields = published_paragraph_fields(schema)
    matrix_spec = schema.get("matrix_spec") or {}

    if shape == "row":
        rows = sc.get("rows") or []
        _heading(doc, schema.get("published_section_title") or "Entries")
        cols = [(f, label_for_field(f, s), s)
                for f, s in published_row_fields(schema)]
        keep = [c for c in cols
                if any(r.get(c[0]) not in (None, "", False)
                       for r in rows if isinstance(r, dict))] or cols
        group_by = schema.get("group_by")
        if group_by and rows:
            collapse = schema.get("group_collapse_map") or {}
            labels = schema.get("group_collapse_labels") or {}
            order = schema.get("group_collapse_order") or []
            buckets: dict = {}
            seen_order: list = []
            for r in rows:
                raw = (r or {}).get(group_by)
                key = collapse.get(raw, raw) if raw else None
                if key is None and raw:
                    key = "other"
                key = key or "(unspecified)"
                if key not in buckets:
                    buckets[key] = []
                    seen_order.append(key)
                buckets[key].append(r)
            if order:
                ordered = [k for k in order if k in buckets]
                ordered += [k for k in seen_order if k not in ordered]
                seen_order = ordered
            body_cols = [c for c in keep if c[0] != group_by]
            for key in seen_order:
                _heading(doc, labels.get(key) or humanize(str(key)), level=3)
                _table(doc, body_cols, buckets[key], footnotes, citations)
        else:
            _table(doc, keep, rows, footnotes, citations)
        # Workpaper appendix (analyst working notes).
        wp = workpaper_row_fields(schema)
        if wp and rows:
            emitted_head = False
            for r in rows:
                if not isinstance(r, dict):
                    continue
                items = [(label_for_field(f, s), r.get(f), f)
                         for f, s in wp if r.get(f) not in (None, "", False)]
                if not items:
                    continue
                if not emitted_head:
                    _heading(doc, "Analyst Workpaper")
                    emitted_head = True
                rid = r.get("id") or ""
                nm = r.get("name") or r.get("identity") or ""
                _heading(doc, rid + (f" — {nm}" if nm and nm != rid else ""),
                         level=3)
                _kv_paragraphs(doc, items, r, footnotes, citations)
        for p in paragraph_fields:
            v = sc.get(p.get("name"))
            if p.get("shape") != "map" and v in (None, "", [], {}):
                continue
            _paragraph_field(doc, p, v, sc, footnotes, citations,
                             figures=figures)

    elif shape == "lines":
        _heading(doc, "Report Lines")
        line_keys = [p["name"] for p in paragraph_fields
                     if p.get("name", "").startswith("line_")]
        items = [(label_for_field(k, next(
            (p for p in paragraph_fields if p.get("name") == k), {})),
            sc.get(k), k) for k in line_keys]
        _kv_paragraphs(doc, items, sc, footnotes, citations)

    elif shape == "matrix":
        mfield = matrix_spec.get("field")
        if mfield:
            matrix = normalize_matrix(sc.get(mfield),
                                      matrix_spec.get("row_axis"),
                                      matrix_spec.get("col_axis"))
            if matrix:
                mlabel = next(
                    (p.get("render_label") or humanize(mfield)
                     for p in paragraph_fields if p.get("name") == mfield),
                    humanize(mfield))
                _heading(doc, mlabel)
                _grid(doc, matrix,
                      matrix_spec.get("row_axis") or list(matrix.keys()),
                      matrix_spec.get("col_axis")
                      or sorted({k for v in matrix.values()
                                 if isinstance(v, dict) for k in v
                                 if not k.startswith("_")}),
                      footnotes, citations)
        for p in paragraph_fields:
            if p.get("name") == mfield:
                continue
            v = sc.get(p.get("name"))
            if p.get("shape") != "map" and v in (None, "", [], {}):
                continue
            _paragraph_field(doc, p, v, sc, footnotes, citations,
                             figures=figures)

    elif shape == "header_only" and not paragraph_fields:
        for f, spec in (schema.get("header_fields") or {}).items():
            if (spec or {}).get("view") != "published":
                continue
            v = header.get(f)
            items = [(label_for_field(f, spec),
                      v if v not in (None, "") else _ANALYST_BADGE, f)]
            _kv_paragraphs(doc, items, header, footnotes, citations)

    else:
        # paragraph / structured (and header_only WITH paragraphs).
        if paragraph_fields:
            for p in paragraph_fields:
                v = sc.get(p.get("name"))
                if p.get("shape") != "map" and v in (None, "", [], {}):
                    continue
                _paragraph_field(doc, p, v, sc, footnotes, citations,
                                 figures=figures)
        else:
            skip = {"header", "rows"}
            for k, v in sc.items():
                if k in skip or str(k).startswith("_"):
                    continue
                _heading(doc, humanize(k))
                if isinstance(v, str):
                    doc.add_paragraph(v)
                else:
                    _paragraph_field(doc, {"name": k, "shape": ""},
                                     v, sc, footnotes, citations)

    # Sources — register every closed-set citation cited anywhere in
    # the content (the writer's _provenance ids resolved), then render
    # the numbered section.
    def _register_all(v):
        if isinstance(v, dict):
            prov = v.get("_provenance")
            if isinstance(prov, list):
                for cid in prov:
                    footnotes.register(_citation_text(cid, citations))
            elif isinstance(prov, dict):
                for pv in prov.values():
                    if isinstance(pv, str):
                        footnotes.register(
                            _citation_text(pv, citations)
                            if pv in citations else pv)
            for vv in v.values():
                _register_all(vv)
        elif isinstance(v, list):
            for vv in v:
                _register_all(vv)
    _register_all(sc)
    for cid in sorted(citations):
        footnotes.register(_citation_text(cid, citations))

    if footnotes.footnotes:
        _heading(doc, "Sources")
        intro = doc.add_paragraph(
            "Every analytical claim above rests on the cited project "
            "records below (the citation contract: the writer draws "
            "from a closed retrieval set and cites by id).")
        intro.runs[0].font.size = Pt(8)
        for n, c in footnotes.footnotes:
            p = doc.add_paragraph(style="List Number")
            run = p.add_run(c)
            run.font.size = Pt(8)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
