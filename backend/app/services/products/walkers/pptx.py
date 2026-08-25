"""The PPTX walker — IBL render_artifact_pptx ported as-is MINUS the
importer machinery (no hidden marker slides, no per-paragraph marker
runs, no notes slides). python-pptx native throughout. Keeps: the
13.33x7.5 deck, cover slide + header kv, per-shape slide dispatch,
empty-column suppression, group banding w/ collapse maps, scored-
matrix (CARVER) summary+detail layout, full-bleed aspect-preserved map
slides, the cell-border XML diet (the 30-45s Collabora load lesson),
Liberation Sans (Latvian glyph coverage), and the Sources slide.
"""
import io
import logging
from typing import Any, Optional

from app.services.products.walkers.common import (
    FootnoteRegistry, cell_fill_for, coerce_mgrs_value, column_weights,
    display_scalar, humanize, humanize_enum_value, label_for_field,
    normalize_matrix, published_paragraph_fields, published_row_fields,
    strip_doctrine_refs, strip_scaffold_tokens,
)

log = logging.getLogger(__name__)

_FONT = "Liberation Sans"


def _rgb(hexstr: str):
    from pptx.dml.color import RGBColor
    return RGBColor.from_string(hexstr)


def _citation_text(cid, citations: dict) -> str:
    c = citations.get(str(cid))
    if isinstance(c, dict):
        return c.get("citation") or c.get("text") or str(cid)
    return str(cid)


def _set_cell(cell, text, *, bold=False, size=10, fill="FFFFFF"):
    from pptx.util import Pt
    from pptx.oxml.ns import qn
    cell.fill.solid()
    cell.fill.fore_color.rgb = _rgb(fill)
    tf = cell.text_frame
    tf.margin_top = Pt(6)
    tf.margin_bottom = Pt(6)
    tf.margin_left = Pt(10)
    tf.margin_right = Pt(10)
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = "—" if text in (None, "", False) else str(text)
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.name = _FONT
    r.font.color.rgb = _rgb("000000")
    # Cell-border XML diet: replace python-pptx's default white-fill
    # borders with w=0 noFill (a 211x10 table carried ~700KB of
    # invisible border XML = the slow-Collabora-open bug).
    try:
        tcPr = cell._tc.get_or_add_tcPr()
        for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
            ln = tcPr.find(qn(tag))
            if ln is None:
                ln = tcPr.makeelement(qn(tag), {})
                tcPr.insert(0, ln)
            for child in list(ln):
                ln.remove(child)
            ln.set("w", "0")
            ln.append(ln.makeelement(qn("a:noFill"), {}))
    except Exception:
        pass


def _render_period_matrix_slide(schema: dict, sc: dict,
                                citations: dict,
                                registry_label: str) -> bytes:
    """The exemplar planning-weather slide (2026-07-27 ruling): one
    16:9 shape-grid slide — element grid, impact codes, warfighting-
    function codes, legend, source footer — plus the Sources slide.
    Layout mirrors the analyst best-practice exemplar shape-for-shape;
    all content arrives engine-shaped in structured_content."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    render = schema.get("render") or {}
    code_colors = render.get("code_colors") or {}
    legend = render.get("legend") or []
    header = sc.get("header") or {}
    grid = sc.get("forecast_grid") or {}
    periods = grid.get("periods") or []
    impact = {k: v for k, v in (sc.get("impact_assessment") or {}).items()
              if k != "_provenance"}
    wff = {k: v for k, v in (sc.get("wff_assessment") or {}).items()
           if k != "_provenance"}

    row_labels: dict[str, str] = {}
    for f in schema.get("paragraph_fields") or []:
        eg = f.get("enum_grid") or {}
        row_labels.update(eg.get("row_labels") or {})

    pres = Presentation()
    pres.slide_width = Inches(13.33)
    pres.slide_height = Inches(7.5)
    slide = pres.slides.add_slide(pres.slide_layouts[6])

    def _box(x, y, w, h, text, *, fill="FFFFFF", size=8, bold=False,
             color="000000", align=PP_ALIGN.CENTER, line="BFBFBF"):
        shp = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w),
            Inches(h))
        shp.fill.solid()
        shp.fill.fore_color.rgb = _rgb(fill)
        shp.shadow.inherit = False
        if line:
            shp.line.color.rgb = _rgb(line)
            shp.line.width = Pt(0.4)
        else:
            shp.line.fill.background()
        tf = shp.text_frame
        tf.word_wrap = True
        tf.margin_top = Pt(1)
        tf.margin_bottom = Pt(1)
        tf.margin_left = Pt(2)
        tf.margin_right = Pt(2)
        p = tf.paragraphs[0]
        p.alignment = align
        for i, seg in enumerate(str(text or "").split("\n")):
            pp = p if i == 0 else tf.add_paragraph()
            pp.alignment = align
            r = pp.add_run()
            r.text = seg
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.name = _FONT
            r.font.color.rgb = _rgb(color)
        return shp

    label_x, label_w = 0.08, 2.10
    col_w = 1.105
    col_x = [label_x + label_w + i * col_w for i in range(10)]

    classification = str(header.get("classification")
                         or "UNCLASSIFIED").upper()
    _box(0, 0, 13.33, 0.18, classification, fill="00B050", size=9,
         bold=True, color="FFFFFF", line=None)
    ao = strip_doctrine_refs(str(header.get("area_of_interest") or
                                 registry_label)).upper()
    _box(0, 0.18, 13.33, 0.42, f"{ao}  -  5 DAY PLANNING WEATHER",
         fill="0B1220", size=16, bold=True, color="FFFFFF",
         align=PP_ALIGN.LEFT, line=None)
    swo = strip_doctrine_refs(str(header.get("swo_attribution") or ""))
    _box(0, 0.60, 13.33, 0.25,
         f"AS OF {grid.get('as_of_local') or ''}  |  WARFIGHTING "
         f"FUNCTIONS ASSESSMENT  |  {swo}",
         fill="0B1220", size=9, bold=False, color="D9D9D9",
         align=PP_ALIGN.LEFT, line=None)

    _box(label_x, 0.90, label_w, 0.46, ao, fill="1F3864", size=9,
         bold=True, color="FFFFFF")
    for pair in range(5):
        idx = pair * 2
        if idx >= len(periods):
            break
        _box(col_x[idx], 0.90, col_w * 2, 0.26,
             periods[idx].get("day_label") or "", fill="1F3864",
             size=9, bold=True, color="FFFFFF")
    for i, p in enumerate(periods[:10]):
        _box(col_x[i], 1.16, col_w, 0.20, p.get("period_label") or "",
             fill="D9D9D9", size=8, bold=True)

    element_rows = [
        ("WINDS", "winds", 0.22),
        ("MIN CEILINGS", "min_ceiling", 0.22),
        ("MIN VISIBILITY", "min_visibility", 0.22),
        ("PRESENT WEATHER", "present_weather", 0.30),
        ("TEMPERATURE", "temperature", 0.22),
        ("WIND CHL/HT INDEX", "wind_chill_heat_index", 0.22),
    ]
    y = 1.36
    for label, key, h in element_rows:
        _box(label_x, y, label_w, h, label, fill="EDEDED", size=8.5,
             bold=True, align=PP_ALIGN.LEFT)
        for i, p in enumerate(periods[:10]):
            _box(col_x[i], y, col_w, h, p.get(key) or "", size=7.5)
        y += h

    def _code_section(title, rows_map, row_keys, y0, row_h):
        _box(label_x, y0, 13.33 - 2 * label_x, 0.20, title,
             fill="404040", size=9, bold=True, color="FFFFFF",
             align=PP_ALIGN.LEFT)
        yy = y0 + 0.20
        for rk in row_keys:
            _box(label_x, yy, label_w, row_h,
                 row_labels.get(rk, rk), fill="EDEDED", size=8.5,
                 bold=True, align=PP_ALIGN.LEFT)
            codes = rows_map.get(rk) or {}
            for i, p in enumerate(periods[:10]):
                code = str(codes.get(p.get("key")) or "")
                _box(col_x[i], yy, col_w, row_h, code,
                     fill=code_colors.get(code, "FFFFFF"), size=9,
                     bold=True)
            yy += row_h
        return yy

    impact_keys = []
    wff_keys = []
    for f in schema.get("paragraph_fields") or []:
        eg = f.get("enum_grid") or {}
        if f.get("name") == "impact_assessment":
            impact_keys = list(eg.get("rows") or [])
        if f.get("name") == "wff_assessment":
            wff_keys = list(eg.get("rows") or [])
    y = _code_section("AVIATION / GROUND OPS IMPACT", impact, impact_keys,
                      2.92, 0.22)
    y = _code_section("WARFIGHTING FUNCTIONS ASSESSMENT", wff, wff_keys,
                      y + 0.10, 0.32)

    lx = label_x
    for code, meaning in legend:
        _box(lx, 6.72, 0.34, 0.20, code,
             fill=code_colors.get(code, "FFFFFF"), size=8, bold=True)
        _box(lx + 0.34, 6.72, 1.42, 0.20, meaning, size=7.5,
             align=PP_ALIGN.LEFT, line=None)
        lx += 1.84
    _box(label_x, 7.00, 13.33 - 2 * label_x, 0.22,
         f"Source: {swo}  |  {grid.get('source') or ''}"
         + (f"  ({grid.get('timezone')})" if grid.get("timezone")
            else ""),
         size=8, color="595959", align=PP_ALIGN.LEFT, line=None)

    # Sources slide (the provenance footer law: every product carries
    # its sources).
    marks = sorted({m for v in (sc.get("forecast_grid"),
                                sc.get("impact_assessment"),
                                sc.get("wff_assessment"))
                    if isinstance(v, dict)
                    for m in (v.get("_provenance") or [])})
    src_slide = pres.slides.add_slide(pres.slide_layouts[6])
    tb = src_slide.shapes.add_textbox(Inches(0.4), Inches(0.3),
                                      Inches(12.5), Inches(6.5))
    tf = tb.text_frame
    tf.word_wrap = True
    p0 = tf.paragraphs[0]
    r0 = p0.add_run()
    r0.text = "SOURCES"
    r0.font.size = Pt(18)
    r0.font.bold = True
    r0.font.name = _FONT
    for n, m in enumerate(marks, start=1):
        pp = tf.add_paragraph()
        rr = pp.add_run()
        rr.text = f"{n}. {_citation_text(m, citations)}"
        rr.font.size = Pt(11)
        rr.font.name = _FONT

    buf = io.BytesIO()
    pres.save(buf)
    return buf.getvalue()


def render_pptx(artifact_type: str, schema: dict,
                structured_content: dict, citations: dict,
                figures: Optional[dict] = None,
                project_name: str = "",
                registry_label: str = "") -> bytes:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    if ((schema.get("render") or {}).get("render_shape")
            == "period_matrix_slide"):
        return _render_period_matrix_slide(
            schema, structured_content or {}, citations,
            registry_label or schema.get("name", artifact_type))

    sc = structured_content or {}
    header = sc.get("header") or {}
    rows = sc.get("rows") or []
    fn = FootnoteRegistry()
    long_name = registry_label or schema.get("name", artifact_type)
    paragraph_fields = published_paragraph_fields(schema)
    matrix_spec = schema.get("matrix_spec") or {}

    pres = Presentation()
    pres.slide_width = Inches(13.33)
    pres.slide_height = Inches(7.5)
    SLIDE_W, SLIDE_H = pres.slide_width, pres.slide_height

    def _blank_slide():
        return pres.slides.add_slide(pres.slide_layouts[6])

    def _section_bar(slide, text):
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.4), Inches(0.2),
            SLIDE_W - Inches(0.8), Inches(0.4))
        bar.line.color.rgb = _rgb("000000")
        bar.line.width = Pt(0.5)
        bar.fill.solid()
        bar.fill.fore_color.rgb = _rgb("404040")
        bar.shadow.inherit = False
        tf = bar.text_frame
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = strip_doctrine_refs(str(text)).upper()
        r.font.size = Pt(15)
        r.font.bold = True
        r.font.name = _FONT
        r.font.color.rgb = _rgb("FFFFFF")

    def _new_slide(title: Optional[str] = None):
        slide = _blank_slide()
        if title is not None:
            _section_bar(slide, title)
        return slide

    def _render_string(slide, value, parent, field):
        tx = slide.shapes.add_textbox(Inches(0.5), Inches(0.85),
                                      Inches(12.3), Inches(6.2))
        tf = tx.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = "—" if value in (None, "", False) else str(value)
        r.font.size = Pt(13)
        r.font.name = _FONT

    def _render_kv(slide, items, parent=None, top=None):
        if not items:
            return
        top = top or Inches(0.85)
        n = len(items)
        row_h = int(min(Inches(0.65), max(Inches(0.42), Inches(5.9) / n)))
        t = slide.shapes.add_table(n, 2, Inches(0.5), top,
                                   Inches(12.3), row_h * n).table
        t.columns[0].width = Inches(3.2)
        t.columns[1].width = Inches(9.1)
        for i, it in enumerate(items):
            k, v = it[0], it[1]
            t.rows[i].height = row_h
            _set_cell(t.cell(i, 0), k, bold=True, fill="F2F2F2", size=12)
            _set_cell(t.cell(i, 1), display_scalar(v), size=12)

    def _visible_cols(item_subfields):
        cols = []
        for f in item_subfields or []:
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

    def _absent(v):
        if v in (None, "", False):
            return True
        return str(v).strip().lower() in ("", "n/a", "—", "-", "nstr", "tbd")

    def _render_table(slide, value, item_subfields, *, group_by=None,
                      collapse_map=None, collapse_order=None,
                      collapse_labels=None):
        if not value:
            return
        cols = _visible_cols(item_subfields)
        if not cols:
            seen = []
            for it in value:
                if isinstance(it, dict):
                    for k in it:
                        if k not in seen and not k.startswith("_"):
                            seen.append(k)
            cols = [(k, humanize(k), {}) for k in seen]
        if not cols:
            return
        # Empty-column suppression (required + score columns immune).
        keep = []
        for name, lbl, spec in cols:
            spec = spec or {}
            if spec.get("required") is True or "score" in name.lower():
                keep.append((name, lbl, spec))
                continue
            if any(not _absent((it or {}).get(name))
                   for it in value if isinstance(it, dict)):
                keep.append((name, lbl, spec))
        cols = keep or cols
        grouping = bool(group_by) and any(
            isinstance(it, dict) and it.get(group_by) for it in value)
        bucket_for_row: list = []
        seen_cats: list = []
        if grouping:
            for it in value:
                raw = (it or {}).get(group_by) if isinstance(it, dict) else None
                if collapse_map:
                    bk = collapse_map.get(raw)
                    if bk is None and raw:
                        bk = "other"
                else:
                    bk = raw or "—"
                bucket_for_row.append(bk)
                if bk and bk not in seen_cats:
                    seen_cats.append(bk)
            if collapse_order:
                ordered = [k for k in collapse_order if k in seen_cats]
                ordered += [k for k in seen_cats if k not in ordered]
                seen_cats = ordered
            cols = [c for c in cols if c[0] != group_by]
        n_data = len([it for it in value if isinstance(it, dict)])
        n_groups = len(seen_cats) if grouping else 0
        n_rows = 1 + n_groups + n_data
        header_h = int(Inches(0.42))
        group_h = int(Inches(0.36)) if grouping else 0
        body_rem = int(Inches(6.2)) - header_h - group_h * n_groups
        body_h = int(max(Inches(0.32), min(Inches(0.7),
                                           body_rem / max(n_data, 1))))
        total_h = header_h + group_h * n_groups + body_h * n_data
        t = slide.shapes.add_table(
            n_rows, len(cols), Inches(0.4), Inches(0.85),
            SLIDE_W - Inches(0.8), total_h).table
        from pptx.util import Emu
        total_emu = int(SLIDE_W - Inches(0.8))
        weights = column_weights([c[0] for c in cols])
        wsum = sum(weights) or 1.0
        for j, w in enumerate(weights):
            t.columns[j].width = Emu(int(total_emu * w / wsum))
        t.rows[0].height = header_h
        for j, (_, lbl, _s) in enumerate(cols):
            _set_cell(t.cell(0, j), strip_doctrine_refs(lbl), bold=True,
                      fill="D9D9D9", size=11)
        body_font = 10 if len(cols) <= 8 else (9 if len(cols) <= 12 else 8)
        row_idx = 1

        def _emit_row(it):
            nonlocal row_idx
            t.rows[row_idx].height = body_h
            for j, (k, _l, spec) in enumerate(cols):
                raw = it.get(k)
                raw = coerce_mgrs_value(raw, spec, k)
                v = humanize_enum_value(raw, spec)
                fill = cell_fill_for(raw if isinstance(raw, str) else None,
                                     spec) or "FFFFFF"
                _set_cell(t.cell(row_idx, j), display_scalar(v),
                          size=body_font, fill=fill)
            row_idx += 1

        if grouping:
            for cat in seen_cats:
                t.rows[row_idx].height = group_h
                label = ((collapse_labels or {}).get(cat)
                         or ("Other" if cat == "other" else humanize(str(cat))))
                first = t.cell(row_idx, 0)
                if len(cols) > 1:
                    first.merge(t.cell(row_idx, len(cols) - 1))
                _set_cell(first, label, bold=True, fill="C8D8E8", size=11)
                row_idx += 1
                for idx, it in enumerate(value):
                    if isinstance(it, dict) and bucket_for_row[idx] == cat:
                        _emit_row(it)
        else:
            for it in value:
                if isinstance(it, dict):
                    _emit_row(it)

    def _render_grid(slide, matrix, row_axis, col_axis):
        from pptx.util import Pt as _Pt
        if not matrix:
            return
        col_axis = col_axis[:6]
        n_rows = len(row_axis) + 1
        n_cols = len(col_axis) + 1
        row_h = int(max(_Pt(20), Inches(6.2) / max(n_rows, 1)))
        t = slide.shapes.add_table(
            n_rows, n_cols, Inches(0.4), Inches(0.85),
            SLIDE_W - Inches(0.8), row_h * n_rows).table
        _set_cell(t.cell(0, 0), "", bold=True, fill="D9D9D9", size=9)
        for j, c in enumerate(col_axis, 1):
            _set_cell(t.cell(0, j), humanize(c), bold=True,
                      fill="D9D9D9", size=9)
        for i, rname in enumerate(row_axis, 1):
            rval = matrix.get(rname) or {}
            _set_cell(t.cell(i, 0), humanize(rname), bold=True,
                      fill="F2F2F2", size=9)
            for j, c in enumerate(col_axis, 1):
                cv = rval.get(c) if isinstance(rval, dict) else ""
                _set_cell(t.cell(i, j), display_scalar(cv), size=8)

    def _emit_map_slide(field_name, p_spec):
        fig = (figures or {}).get(field_name)
        if not fig:
            return
        slide = _blank_slide()
        try:
            from PIL import Image as _PIL
            with _PIL.open(io.BytesIO(fig)) as img:
                src_w, src_h = img.size
            src_aspect = src_w / max(src_h, 1)
        except Exception:
            src_aspect = 16 / 9
        slide_aspect = SLIDE_W / SLIDE_H
        if src_aspect >= slide_aspect:
            w = SLIDE_W
            h = int(SLIDE_W / src_aspect)
        else:
            h = SLIDE_H
            w = int(SLIDE_H * src_aspect)
        left = (SLIDE_W - w) // 2
        top = (SLIDE_H - h) // 2
        try:
            slide.shapes.add_picture(io.BytesIO(fig), left, top,
                                     width=w, height=h)
        except Exception:
            pass

    def _sectioned_item_slides(value, item_subfields, prefix=""):
        scalars, bodies, title_field = [], [], None
        for f in item_subfields or []:
            if not isinstance(f, dict) or f.get("name") == "_provenance":
                continue
            if f.get("shape") in ("list_of_dicts", "dict"):
                bodies.append(f)
            else:
                scalars.append(f)
                if title_field is None:
                    title_field = f
        for it in value:
            if not isinstance(it, dict):
                continue
            title_val = it.get(title_field["name"]) if title_field else None
            ident = (it.get("id") or it.get("coa_id")
                     or (str(title_val) if title_val else "Item"))
            base = f"{prefix}{ident}".strip(" —")
            kv = []
            for sf in scalars:
                v = it.get(sf["name"])
                if v in (None, "", False):
                    continue
                kv.append((label_for_field(sf["name"], sf),
                           humanize_enum_value(v, sf)))
            if kv:
                slide = _new_slide(f"{base} — Overview" if bodies else base)
                _render_kv(slide, kv, parent=it)
            for sf in bodies:
                v = it.get(sf["name"])
                if v in (None, "", [], {}):
                    continue
                sub_label = label_for_field(sf["name"], sf)
                slide = _new_slide(f"{base} — {sub_label}")
                if sf.get("shape") == "list_of_dicts" and isinstance(v, list):
                    _render_table(slide, v, sf.get("item_subfields") or [])
                elif isinstance(v, dict):
                    keys = (None if sf.get("strict_subfields") is False
                            else sf.get("subfields"))
                    items = [(humanize(k), v.get(k))
                             for k in (keys or list(v.keys()))
                             if not str(k).startswith("_")
                             and v.get(k) not in (None, "", [], {})]
                    _render_kv(slide, items, parent=v)

    def _paragraph_slide(p, value):
        name = p.get("name")
        title = strip_scaffold_tokens(p.get("render_label") or humanize(name))
        cite_ids = []
        prov = sc.get("_provenance")
        if isinstance(prov, dict) and prov.get(name):
            v = prov[name]
            for cid in (v if isinstance(v, list) else [v]):
                fn.register(_citation_text(cid, citations)
                            if str(cid) in citations else str(cid))
        sh = p.get("shape")
        if sh == "map":
            _emit_map_slide(name, p)
            return
        if sh == "list_of_dicts":
            isf = p.get("item_subfields") or []
            items = value if isinstance(value, list) else []
            if any(isinstance(f, dict) and f.get("shape") in
                   ("list_of_dicts", "dict") for f in isf) and items:
                _sectioned_item_slides(items, isf, prefix=f"{title} — ")
                return
            slide = _new_slide(title)
            _render_table(slide, items, isf)
            return
        if sh == "string":
            slide = _new_slide(title)
            _render_string(slide, display_scalar(value), sc, name)
            return
        if sh == "dict":
            if isinstance(value, dict):
                items = []
                for k in (p.get("subfields") or list(value.keys())):
                    if str(k).startswith("_"):
                        continue
                    vv = value.get(k)
                    if _absent(vv):
                        continue
                    items.append((humanize(k), vv))
                if not items:
                    return
                slide = _new_slide(title)
                _render_kv(slide, items, parent=value)
            else:
                slide = _new_slide(title)
                _render_string(slide, display_scalar(value), sc, name)
            return
        if sh == "grid_table":
            matrix = normalize_matrix(value)
            if isinstance(matrix, dict) and matrix:
                row_axis = list(matrix.keys())
                col_axis = []
                for v in matrix.values():
                    if isinstance(v, dict):
                        for k in v:
                            if k not in col_axis and not k.startswith("_"):
                                col_axis.append(k)
                slide = _new_slide(title)
                _render_grid(slide, matrix, row_axis, col_axis)
            return
        # inferred
        if isinstance(value, str):
            slide = _new_slide(title)
            _render_string(slide, value, sc, name)
        elif isinstance(value, list):
            slide = _new_slide(title)
            _render_table(slide, value, [])
        elif isinstance(value, dict):
            items = [(humanize(k), v) for k, v in value.items()
                     if not str(k).startswith("_")]
            if items:
                slide = _new_slide(title)
                _render_kv(slide, items, parent=value)

    # ---- Cover slide ----
    slide = _blank_slide()
    tx = slide.shapes.add_textbox(Inches(0.5), Inches(2.4),
                                  Inches(12.3), Inches(1.3))
    tf = tx.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = long_name.upper()
    r.font.size = Pt(40)
    r.font.bold = True
    r.font.name = _FONT
    kv_items = []
    for fname, spec in (schema.get("header_fields") or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("view") not in ("header", None):
            continue
        if fname.startswith("spatial_overlay") or fname == "classification":
            continue
        val = header.get(fname)
        if val in (None, "", False):
            continue
        kv_items.append((label_for_field(fname, spec), str(val)))
    if kv_items:
        _render_kv(slide, kv_items[:8], parent=header, top=Inches(4.0))

    # ---- Per-shape deck ----
    shape = schema.get("shape", "")
    if shape == "row":
        published = published_row_fields(schema)
        score_fields = [f for f, _ in published if f.endswith("_score")
                        and f != "composite_total_score"]
        rationale_fields = [f for f, _ in published
                            if f.endswith("_rationale")]
        scored_matrix = (len(score_fields) >= 3 and any(
            f.replace("_score", "_rationale") in rationale_fields
            for f in score_fields))
        specs_by_name = dict(published)
        if scored_matrix and rows:
            summary = [f for f, _ in published if f not in rationale_fields]
            slide = _new_slide(schema.get("published_section_title")
                               or "Entries")
            synth = [{"name": f,
                      "render_label": label_for_field(f, specs_by_name.get(f)),
                      **(specs_by_name.get(f) or {})} for f in summary]
            _render_table(slide, rows, synth,
                          group_by=schema.get("group_by"),
                          collapse_map=schema.get("group_collapse_map"),
                          collapse_order=schema.get("group_collapse_order"),
                          collapse_labels=schema.get("group_collapse_labels"))
            for r_ in rows:
                if not isinstance(r_, dict):
                    continue
                ident = r_.get("id") or ""
                nm = r_.get("name") or ""
                items = []
                for sf in score_fields:
                    base = sf[:-len("_score")]
                    rat = r_.get(f"{base}_rationale")
                    sv = r_.get(sf)
                    if sv in (None, "", False) and rat in (None, "", False):
                        continue
                    disp = "—" if sv in (None, "", False) else str(sv)
                    items.append((f"{humanize(base)} ({disp})", rat))
                cs = r_.get("composite_total_score")
                if cs not in (None, "", False):
                    items.append(("Total Composite Score", cs))
                if items:
                    slide = _new_slide(
                        ident + (f" — {nm}" if nm and nm != ident else ""))
                    _render_kv(slide, items, parent=r_)
        elif rows and published:
            slide = _new_slide(schema.get("published_section_title")
                               or "Entries")
            keep = [f for f, _ in published
                    if any(r_.get(f) not in (None, "", False)
                           for r_ in rows if isinstance(r_, dict))]
            synth = [{"name": f,
                      "render_label": label_for_field(f, specs_by_name.get(f)),
                      **(specs_by_name.get(f) or {})} for f in keep]
            _render_table(slide, rows, synth,
                          group_by=schema.get("group_by"),
                          collapse_map=schema.get("group_collapse_map"),
                          collapse_order=schema.get("group_collapse_order"),
                          collapse_labels=schema.get("group_collapse_labels"))
        for p_ in paragraph_fields:
            v = sc.get(p_.get("name"))
            if p_.get("shape") != "map" and v in (None, "", [], {}):
                continue
            _paragraph_slide(p_, v)
    elif shape == "lines":
        slide = _new_slide("Report Lines")
        line_keys = [p_["name"] for p_ in paragraph_fields
                     if p_.get("name", "").startswith("line_")]
        items = [(label_for_field(k, next(
            (p_ for p_ in paragraph_fields if p_.get("name") == k), {})),
            sc.get(k)) for k in line_keys]
        _render_kv(slide, items, parent=sc)
    elif shape == "matrix":
        mfield = matrix_spec.get("field")
        if mfield:
            matrix = normalize_matrix(sc.get(mfield),
                                      matrix_spec.get("row_axis"),
                                      matrix_spec.get("col_axis"))
            if matrix:
                title = next((p_.get("render_label") or humanize(mfield)
                              for p_ in paragraph_fields
                              if p_.get("name") == mfield),
                             humanize(mfield))
                slide = _new_slide(title)
                row_axis = matrix_spec.get("row_axis") or list(matrix.keys())
                col_axis = matrix_spec.get("col_axis") or sorted(
                    {k for v in matrix.values() if isinstance(v, dict)
                     for k in v if not k.startswith("_")})
                _render_grid(slide, matrix, row_axis, col_axis)
        for p_ in paragraph_fields:
            if p_.get("name") == mfield:
                continue
            v = sc.get(p_.get("name"))
            if p_.get("shape") != "map" and v in (None, "", [], {}):
                continue
            _paragraph_slide(p_, v)
    else:
        if paragraph_fields:
            for p_ in paragraph_fields:
                v = sc.get(p_.get("name"))
                if p_.get("shape") != "map" and v in (None, "", [], {}):
                    continue
                _paragraph_slide(p_, v)
        else:
            for k, v in sc.items():
                if k in ("header", "rows") or str(k).startswith("_"):
                    continue
                if isinstance(v, str):
                    slide = _new_slide(humanize(k))
                    _render_string(slide, v, sc, k)
                elif isinstance(v, dict):
                    items = [(humanize(kk), vv) for kk, vv in v.items()
                             if not str(kk).startswith("_")]
                    if items:
                        slide = _new_slide(humanize(k))
                        _render_kv(slide, items, parent=v)
                elif isinstance(v, list):
                    slide = _new_slide(humanize(k))
                    _render_table(slide, v, [])

    # ---- Sources slide ----
    for cid in sorted(citations):
        fn.register(_citation_text(cid, citations))
    if fn.footnotes:
        slide = _new_slide("Sources")
        tx = slide.shapes.add_textbox(Inches(0.5), Inches(0.85),
                                      Inches(12.3), Inches(6.2))
        tf = tx.text_frame
        tf.word_wrap = True
        for i, (num, cite) in enumerate(fn.footnotes):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(4)
            r1 = p.add_run()
            r1.text = f"{num}. "
            r1.font.size = Pt(11)
            r1.font.bold = True
            r1.font.name = _FONT
            r2 = p.add_run()
            r2.text = cite
            r2.font.size = Pt(11)
            r2.font.name = _FONT

    buf = io.BytesIO()
    pres.save(buf)
    return buf.getvalue()
