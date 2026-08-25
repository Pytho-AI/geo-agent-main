"""The XLSX walker — IBL xlsx_exporter.py ported MINUS the importer
shadow machinery (no _Header/_FieldMap/_Workpaper sheets, no defined-
name markers). openpyxl native. Keeps: the single-data-sheet layout
(banner row + compact metadata strip), group_by sections w/ collapse
maps + Excel Tables + native row grouping, LIVE FORMULAS (computed
beats asserted — CARVER composite), numeric enum coercion (text cells
make SUM silently 0), compact_dict rendering, the nested cross-join
flatten (the Fig 4-17 WEM layout), matrix sheets w/ payload-derived
column axes + markdown-table fallback, and provenance cell COMMENTS
(analyst-facing value — these stay).
"""
import io
import json
import logging
import re
from typing import Any, Optional

from app.services.products.walkers.common import (
    classification_colors, humanize, label_for_field,
    maybe_parse_fenced_json, normalize_matrix, published_row_fields,
)

log = logging.getLogger(__name__)

SECTION_FILL = "DCE6F1"
TABLE_HEADER_FILL = "D9D9D9"


def _citation_text(cid, citations: dict) -> str:
    c = citations.get(str(cid))
    if isinstance(c, dict):
        return c.get("citation") or c.get("text") or str(cid)
    return str(cid)


def _safe_sheet_name(name: str) -> str:
    bad = set('\\/?*[]:')
    clean = "".join("_" if c in bad else c for c in (name or "Sheet"))
    return clean[:31] or "Sheet"


def _safe_token(name: str) -> str:
    clean = "".join(c if c.isalnum() or c == "_" else "_"
                    for c in (name or "section"))
    if not clean or clean[0].isdigit():
        clean = "s_" + clean
    return clean[:255]


def _build_formula(spec: dict, col_letters: dict, row_number: int):
    if not isinstance(spec, dict):
        return None
    expr = spec.get("formula")
    if not expr or not isinstance(expr, str) or ":" not in expr:
        return None
    fnc, _, args = expr.partition(":")
    refs = [a.strip() for a in args.split(",") if a.strip()]
    cells = [f"{col_letters[r]}{row_number}" for r in refs
             if r in col_letters]
    if not cells:
        return None
    op = {"sum": "SUM", "avg": "AVERAGE", "average": "AVERAGE",
          "min": "MIN", "max": "MAX"}.get(fnc.strip().lower())
    if not op:
        return None
    return f"={op}({','.join(cells)})"


def _display_value(value: Any, spec: dict) -> Any:
    if value is None:
        return ""
    labels = spec.get("enum_labels") if isinstance(spec, dict) else None
    if isinstance(labels, dict) and isinstance(value, str) and value in labels:
        return labels[value]
    enum = spec.get("enum") if isinstance(spec, dict) else None
    if isinstance(enum, (list, tuple)) and enum:
        all_int = all(isinstance(e, int) and not isinstance(e, bool)
                      for e in enum)
        all_num = all(isinstance(e, (int, float))
                      and not isinstance(e, bool) for e in enum)
        if all_num:
            if (isinstance(value, (int, float))
                    and not isinstance(value, bool) and value in enum):
                return int(value) if all_int else value
            if isinstance(value, str):
                try:
                    parsed = int(value) if all_int else float(value)
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None and parsed in enum:
                    return parsed
    if (isinstance(enum, (list, tuple)) and isinstance(value, str)
            and value in enum):
        return value.replace("_", " ").title()
    if (isinstance(spec, dict) and spec.get("render") == "compact_dict"
            and isinstance(value, dict) and value):
        items = sorted(((str(k), v) for k, v in value.items() if v),
                       key=lambda kv: (-kv[1] if isinstance(
                           kv[1], (int, float)) else 0, kv[0]))
        limit = spec.get("render_limit")
        if isinstance(limit, int) and 0 < limit < len(items):
            kept = items[:limit]
            more = len(items) - limit
            return (" / ".join(f"{k} x {v}" for k, v in kept)
                    + f" / (+{more} more)")
        return " / ".join(f"{k} x {v}" for k, v in items)
    if isinstance(value, list):
        if all(isinstance(v, (str, int, float)) for v in value):
            return ", ".join(str(v) for v in value)
        return json.dumps(value, default=str)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return value


def _provenance_summary(prov: Any, citations: dict) -> str:
    if prov is None:
        return ""
    if isinstance(prov, str):
        return (_citation_text(prov, citations)
                if prov in citations else prov)[:240]
    if isinstance(prov, list):
        return "; ".join(
            _citation_text(p, citations) if str(p) in citations else str(p)
            for p in prov if p)[:240]
    if isinstance(prov, dict):
        for k in ("source_doc_tag", "source", "citation", "doc_tag"):
            if prov.get(k):
                return str(prov[k])[:240]
        return json.dumps(prov, default=str)[:240]
    return str(prov)[:240]


from .common import parse_markdown_table as _parse_markdown_table  # noqa: E402


def render_xlsx(artifact_type: str, schema: dict,
                structured_content: dict, citations: dict,
                figures: Optional[dict] = None,
                project_name: str = "",
                registry_label: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    THIN = Side(border_style="thin", color="000000")
    BORDER_ALL = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
    sc = structured_content or {}
    header = sc.get("header") or {}

    wb = Workbook()
    wb.remove(wb.active)

    def _banner_rows(ws, col_span: int) -> int:
        marking = (header.get("classification") or "UNCLASSIFIED").upper()
        sw = classification_colors(marking)
        span = max(col_span, 2)
        ws.merge_cells(start_row=1, start_column=1, end_row=1,
                       end_column=span)
        banner = ws.cell(row=1, column=1, value=f"  {marking}")
        banner.fill = PatternFill("solid", fgColor=sw["fill"])
        banner.font = Font(name="Arial", size=11, bold=True,
                           color=sw["text"])
        banner.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 18
        parts = []
        seen = set()
        for k in ("phase_or_critical_event", "phase", "dtg", "as_of_dtg",
                  "valid_window_start_dtg", "valid_window_end_dtg",
                  "area_of_operations", "area_of_interest",
                  "swo_attribution", "prepared_by",
                  "approving_commander"):
            if k in seen:
                continue
            seen.add(k)
            v = header.get(k)
            if (not v or isinstance(v, (list, dict))
                    or str(v).strip().startswith("TBD")
                    or str(v).startswith("{")):
                continue
            parts.append(str(v).strip())
        ws.merge_cells(start_row=2, start_column=1, end_row=2,
                       end_column=span)
        meta = ws.cell(row=2, column=1, value="  " + "  ·  ".join(parts))
        meta.font = Font(name="Arial", size=9, italic=True, color="595959")
        meta.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[2].height = 14
        ws.row_dimensions[3].height = 4
        return 4

    def _write_cell(ws, row, col, value, *, bold=False, fill=None,
                    comment_text=""):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = Font(name="Arial", size=10, bold=bold)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cell.border = BORDER_ALL
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        if comment_text:
            cell.comment = Comment(comment_text, "Pytho")
        return cell

    data_col_count = 2
    table_idx = 0

    def _row_sheet(sheet_name: str) -> int:
        nonlocal table_idx
        ws = wb.create_sheet(_safe_sheet_name(sheet_name))
        fields = published_row_fields(schema)
        col_count = len(fields)
        rows = list(sc.get("rows") or [])
        group_by = schema.get("group_by")
        next_row = _banner_rows(ws, col_count or 2)
        collapse_map = schema.get("group_collapse_map") or {}
        section_labels = (schema.get("group_collapse_labels")
                          or schema.get("group_labels") or {})
        sections: list = []
        if group_by:
            seen_order: list = []
            bucket: dict = {}
            for row in rows:
                raw = (row or {}).get(group_by)
                key = str(collapse_map.get(raw, raw) if raw else "Unassigned")
                if key not in bucket:
                    bucket[key] = []
                    seen_order.append(key)
                bucket[key].append(row)
            order = (schema.get("group_collapse_order")
                     or schema.get("group_order"))
            if isinstance(order, (list, tuple)) and order:
                ordered = [k for k in order if k in bucket]
                ordered += [k for k in seen_order if k not in ordered]
                seen_order = ordered
            for key in seen_order:
                sections.append((key, bucket[key]))
        else:
            sections.append(("", rows))
        suppress = len(sections) <= 1
        current = next_row
        for section_key, section_rows in sections:
            if not suppress:
                ws.merge_cells(start_row=current, start_column=1,
                               end_row=current,
                               end_column=max(col_count, 1))
                label = (section_labels.get(section_key)
                         or section_key.replace("_", " ").title())
                banner = ws.cell(row=current, column=1, value=label)
                banner.fill = PatternFill("solid", fgColor=SECTION_FILL)
                banner.font = Font(name="Arial", size=11, bold=True)
                banner.alignment = Alignment(horizontal="left",
                                             vertical="center")
                ws.row_dimensions[current].height = 20
                current += 1
            header_row = current
            for i, (name, spec) in enumerate(fields, start=1):
                _write_cell(ws, header_row, i,
                            spec.get("render_label") or name,
                            bold=True, fill=TABLE_HEADER_FILL)
            current += 1
            col_letters = {name: get_column_letter(i)
                           for i, (name, _) in enumerate(fields, start=1)}
            data_start = current
            for row in section_rows:
                for i, (name, spec) in enumerate(fields, start=1):
                    formula = _build_formula(spec, col_letters, current)
                    if formula is not None:
                        value = formula
                    else:
                        value = _display_value((row or {}).get(name), spec)
                    comment = ""
                    if spec.get("provenance_required"):
                        prov = ((row or {}).get("_provenance") or {})
                        comment = _provenance_summary(
                            prov.get(name) if isinstance(prov, dict)
                            else prov, citations)
                    _write_cell(ws, current, i, value,
                                comment_text=comment)
                current += 1
            data_end = current - 1 if section_rows else data_start
            if section_rows:
                table_idx += 1
                ref = (f"{get_column_letter(1)}{header_row}:"
                       f"{get_column_letter(max(col_count, 1))}{data_end}")
                tbl = Table(
                    displayName=f"{_safe_token(section_key or 'tbl')}_{table_idx}",
                    ref=ref)
                tbl.tableStyleInfo = TableStyleInfo(
                    name="TableStyleLight15", showRowStripes=True,
                    showFirstColumn=False, showLastColumn=False,
                    showColumnStripes=False)
                try:
                    ws.add_table(tbl)
                except ValueError:
                    pass
                try:
                    ws.row_dimensions.group(data_start, data_end,
                                            outline_level=1, hidden=False)
                except Exception:
                    pass
            if not suppress:
                current += 1
        for i, (name, spec) in enumerate(fields, start=1):
            label = spec.get("render_label") or name
            ws.column_dimensions[get_column_letter(i)].width = max(
                14, min(40, len(label) + 6))
        return max(col_count, 2)

    def _matrix_sheet(field_name: str, field_spec: dict,
                      sheet_name: str) -> int:
        ws = wb.create_sheet(_safe_sheet_name(sheet_name))
        mspec = (schema.get("matrix_spec")
                 or field_spec.get("matrix_spec") or {})
        raw = sc.get(field_name)
        payload: dict = {}
        md_headers: list = []
        md_rows: list = []
        if isinstance(raw, dict):
            payload = raw
        elif isinstance(raw, str):
            parsed = maybe_parse_fenced_json(raw)
            if isinstance(parsed, dict):
                payload = parsed
            else:
                md_headers, md_rows = _parse_markdown_table(raw)
        if md_headers and md_rows:
            next_row = _banner_rows(ws, len(md_headers))
            for ci, h in enumerate(md_headers, start=1):
                _write_cell(ws, next_row, ci, h, bold=True,
                            fill=TABLE_HEADER_FILL)
            for ri, row in enumerate(md_rows, start=next_row + 1):
                for ci, val in enumerate(row, start=1):
                    _write_cell(ws, ri, ci, val)
            for ci, h in enumerate(md_headers, start=1):
                ws.column_dimensions[get_column_letter(ci)].width = max(
                    14, min(48, len(h) + 12))
            return len(md_headers)
        payload = normalize_matrix(payload, mspec.get("row_axis"),
                                   mspec.get("col_axis"))
        row_axis = list(mspec.get("row_axis") or []) or list(payload.keys())
        col_axis = list(mspec.get("col_axis") or [])
        payload_cols: list = []
        for rk in row_axis:
            sub = payload.get(rk) or {}
            if isinstance(sub, dict):
                for c in sub:
                    if not str(c).startswith("_") and c not in payload_cols:
                        payload_cols.append(c)
        if payload_cols and (not col_axis or not all(
                c in col_axis for c in payload_cols)):
            # The writer keyed by its own columns (the ICSM DP-column
            # lesson) — honor the payload keys.
            col_axis = payload_cols
        if not row_axis or not col_axis:
            next_row = _banner_rows(ws, 2)
            ws.cell(row=next_row, column=1,
                    value="(no matrix data available)")
            return 2
        next_row = _banner_rows(ws, len(col_axis) + 1)
        header_row = next_row
        _write_cell(ws, header_row, 1, "", fill=TABLE_HEADER_FILL)
        for i, col_label in enumerate(col_axis, start=2):
            _write_cell(ws, header_row, i, humanize(str(col_label)),
                        bold=True, fill=TABLE_HEADER_FILL)
        ws.row_dimensions[header_row].height = 28
        for ri, row_label in enumerate(row_axis, start=header_row + 1):
            _write_cell(ws, ri, 1, humanize(str(row_label)), bold=True,
                        fill=SECTION_FILL)
            sub = payload.get(row_label) or {}
            if not isinstance(sub, dict):
                sub = {}
            for ci, col_label in enumerate(col_axis, start=2):
                entries = sub.get(col_label)
                if entries is None:
                    value = ""
                elif isinstance(entries, list):
                    value = "\n".join(f"• {e}" for e in entries if e)
                elif isinstance(entries, dict):
                    value = json.dumps(entries, default=str)
                else:
                    value = str(entries)
                prov = ""
                sp = sub.get("_provenance")
                if isinstance(sp, dict) and sp.get(col_label):
                    prov = _provenance_summary(sp[col_label], citations)
                _write_cell(ws, ri, ci, value, comment_text=prov)
            ws.row_dimensions[ri].height = 60
        ws.column_dimensions["A"].width = 22
        for ci in range(2, len(col_axis) + 2):
            ws.column_dimensions[get_column_letter(ci)].width = 28
        return len(col_axis) + 1

    def _normalize_item_subfields(raw):
        if isinstance(raw, list):
            return {sf.get("name"): sf for sf in raw
                    if isinstance(sf, dict) and sf.get("name")}
        if isinstance(raw, dict):
            return raw
        return {}

    def _list_sheet(field_name: str, field_spec: dict,
                    sheet_name: str) -> Optional[int]:
        items = sc.get(field_name)
        if not isinstance(items, list) or not items:
            return None
        subfields = _normalize_item_subfields(
            field_spec.get("item_subfields"))
        if not subfields:
            subfields = {k: {"render_label": k.replace("_", " ").title()}
                         for k in (items[0] or {}).keys()
                         if not str(k).startswith("_")}
        visible = {n: s for n, s in subfields.items()
                   if (s or {}).get("view") != "internal"}
        if not visible:
            return None
        nested = [n for n, s in visible.items()
                  if (s or {}).get("shape") == "list_of_dicts"]
        use_flatten = len(nested) == 1
        nested_visible: dict = {}
        if use_flatten:
            nspec = visible[nested[0]]
            nsub = _normalize_item_subfields(nspec.get("item_subfields"))
            if not nsub:
                for it in items:
                    if isinstance(it, dict):
                        nl = it.get(nested[0]) or []
                        if nl and isinstance(nl[0], dict):
                            nsub = {k: {"render_label":
                                        k.replace("_", " ").title()}
                                    for k in nl[0]
                                    if not str(k).startswith("_")}
                            break
            nested_visible = {n: s for n, s in nsub.items()
                              if (s or {}).get("view") != "internal"}
            if not nested_visible:
                use_flatten = False
        ws = wb.create_sheet(_safe_sheet_name(sheet_name))
        if use_flatten:
            scalar_cols = [(n, s) for n, s in visible.items()
                           if n != nested[0]]
            cols = scalar_cols + list(nested_visible.items())
            flat_rows: list = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                nl = item.get(nested[0])
                nl = nl if isinstance(nl, list) else []
                scalars = {sn: item.get(sn) for sn, _ in scalar_cols}
                if not nl:
                    merged = dict(scalars)
                    merged["_provenance"] = item.get("_provenance") or {}
                    flat_rows.append(merged)
                    continue
                for subitem in nl:
                    if not isinstance(subitem, dict):
                        continue
                    merged = dict(scalars)
                    for nn in nested_visible:
                        merged[nn] = subitem.get(nn)
                    prov = {}
                    ip = item.get("_provenance") or {}
                    sp = subitem.get("_provenance") or {}
                    if isinstance(ip, dict):
                        prov.update({k: v for k, v in ip.items()
                                     if k in dict(scalar_cols)})
                    if isinstance(sp, dict):
                        prov.update({k: v for k, v in sp.items()
                                     if k in nested_visible})
                    merged["_provenance"] = prov
                    flat_rows.append(merged)
            render_items = flat_rows
        else:
            cols = list(visible.items())
            render_items = [it for it in items if isinstance(it, dict)]
        if not cols:
            return None
        start = _banner_rows(ws, len(cols))
        for i, (name, spec) in enumerate(cols, start=1):
            _write_cell(ws, start, i,
                        (spec or {}).get("render_label") or name,
                        bold=True, fill=TABLE_HEADER_FILL)
        for ri, item in enumerate(render_items, start=start + 1):
            for i, (name, spec) in enumerate(cols, start=1):
                value = _display_value((item or {}).get(name), spec or {})
                comment = ""
                if (spec or {}).get("provenance_required"):
                    prov = (item or {}).get("_provenance") or {}
                    comment = _provenance_summary(
                        prov.get(name) if isinstance(prov, dict) else prov,
                        citations)
                _write_cell(ws, ri, i, value, comment_text=comment)
        try:
            ref = (f"{get_column_letter(1)}{start}:"
                   f"{get_column_letter(len(cols))}"
                   f"{len(render_items) + start}")
            tbl = Table(displayName=_safe_token(f"tbl_{field_name}"),
                        ref=ref)
            tbl.tableStyleInfo = TableStyleInfo(
                name="TableStyleLight15", showRowStripes=True)
            ws.add_table(tbl)
        except Exception:
            pass
        for i, (name, spec) in enumerate(cols, start=1):
            label = (spec or {}).get("render_label") or name
            ws.column_dimensions[get_column_letter(i)].width = max(
                14, min(40, len(label) + 6))
        return len(cols)

    shape = (schema.get("shape") or "").lower()
    if shape == "row":
        data_col_count = _row_sheet(schema.get("name") or artifact_type)
    else:
        any_rendered = False
        primary_rendered = False
        for pf in (schema.get("paragraph_fields") or []):
            pf_shape = (pf or {}).get("shape") or ""
            if pf_shape in ("grid_table", "matrix") and not primary_rendered:
                cc = _matrix_sheet(pf["name"], pf,
                                   pf.get("render_label") or pf["name"])
                data_col_count = max(data_col_count, cc)
                primary_rendered = True
                any_rendered = True
            elif pf_shape == "list_of_dicts":
                cc = _list_sheet(pf["name"], pf,
                                 pf.get("render_label") or pf["name"])
                if cc:
                    data_col_count = max(data_col_count, cc)
                    any_rendered = True
        if not any_rendered:
            ws = wb.create_sheet("Data")
            r = 1
            for k, v in sc.items():
                if str(k).startswith("_"):
                    continue
                from openpyxl.styles import Font as _F
                ws.cell(row=r, column=1, value=k).font = _F(bold=True)
                ws.cell(row=r, column=2,
                        value=(json.dumps(v, default=str)[:300]
                               if isinstance(v, (list, dict)) else str(v)))
                r += 1

    if wb.sheetnames:
        wb.active = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
