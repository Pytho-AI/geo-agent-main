"""Shared walker helpers — the exporter.py conventions that every
format lane consumes (ported; HTML-specific machinery dead).

Carries: the classification palette (DoDM 5200.01), the banner text
convention, filename resolution (title_field recipe), the humanizer +
enum-label discipline, the doctrinal enum cell-color triplets, the
column-width heuristic, matrix normalization (writer-drift absorber),
and the FootnoteRegistry (per-claim markers + the numbered Sources
section, citations resolved from the CLOSED retrieval set's stored
quotes — never internal plumbing names).
"""
import json
import re
from typing import Any, Optional

BANNER_TEXT = "UNCLASSIFIED//FOR EXERCISE USE ONLY"

# DoDM 5200.01 (Vol 2, Encl 3) banner palette.
CLASSIFICATION_COLORS = {
    "UNCLASSIFIED":    {"fill": "007A33", "text": "FFFFFF"},
    "CUI":             {"fill": "522D80", "text": "FFFFFF"},
    "CONFIDENTIAL":    {"fill": "0033A0", "text": "FFFFFF"},
    "SECRET":          {"fill": "C8102E", "text": "FFFFFF"},
    "TOP SECRET":      {"fill": "FF8C00", "text": "000000"},
    "TOP SECRET//SCI": {"fill": "FFD700", "text": "000000"},
}


def classification_colors(marking: Optional[str]) -> dict:
    m = (marking or "UNCLASSIFIED").strip().upper()
    if m in CLASSIFICATION_COLORS:
        return CLASSIFICATION_COLORS[m]
    base = m.split("//", 1)[0].strip()
    return CLASSIFICATION_COLORS.get(base,
                                     CLASSIFICATION_COLORS["UNCLASSIFIED"])


# Doctrinal color triplets for assessment/status enums (WEM Fig 4-17,
# mobility classes, trafficability).
ENUM_CELL_COLORS = {
    "favorable":           "D8EFD0",
    "marginal":            "FDF3C4",
    "unfavorable":         "F6CFCB",
    "unrestricted":        "D8EFD0",
    "restricted":          "FDF3C4",
    "severely_restricted": "F6CFCB",
    "go":                  "D8EFD0",
    "slow_go":             "FDF3C4",
    "slow-go":             "FDF3C4",
    "no_go":               "F6CFCB",
    "no-go":               "F6CFCB",
}


def cell_fill_for(raw_value: Any, spec: Optional[dict]) -> Optional[str]:
    if not isinstance(raw_value, str):
        return None
    key = raw_value.strip().lower()
    if not key:
        return None
    if spec and isinstance(spec, dict):
        custom = spec.get("enum_colors") or {}
        c = custom.get(raw_value) or custom.get(key)
        if c:
            return c.lstrip("#")
    return ENUM_CELL_COLORS.get(key)


_SAFE_DICT_RE = re.compile(r"[-_/]{2,}|^[-_/ ]+|[-_/ ]+$|^\s*$")


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def artifact_filename_base(artifact_type: str, schema: dict,
                           structured_content: dict,
                           artifact_id: str) -> str:
    """title_field recipe: prefer the live default-template resolution
    over the stored value; reject half-resolved forms ('INTSUM--');
    filesystem hygiene; fall back to the artifact id."""
    header = (structured_content or {}).get("header") or {}
    title_field = (schema or {}).get("title_field")
    candidate = ""
    if title_field:
        hspecs = (schema.get("header_fields") or {})
        tdef = ((hspecs.get(title_field) or {}).get("default") or "")
        if isinstance(tdef, str) and tdef:
            try:
                c = tdef.format_map(_SafeDict(
                    {k: ("" if v is None else v) for k, v in header.items()}))
            except (ValueError, IndexError):
                c = tdef
            if not _SAFE_DICT_RE.search(c):
                candidate = c
        if not candidate:
            stored = str(header.get(title_field) or "").strip()
            if stored and not _SAFE_DICT_RE.search(stored):
                candidate = stored
    if not candidate:
        candidate = artifact_id or "artifact"
    cleaned = re.sub(r'[\\/:"*?<>|\x00-\x1f]', "_", candidate).strip(" .")
    return cleaned or "artifact"


# ---------------------------------------------------------------------------
# Humanize + labels (the exporter's discipline)
# ---------------------------------------------------------------------------

_ACRONYMS = {
    "mgrs", "dtg", "coa", "ao", "aoi", "aor", "bda", "fda", "pda", "mea",
    "hpt", "hvt", "tle", "ada", "c2", "cema", "ew", "uas", "isr", "cas",
    "nvg", "oakoc", "pir", "mlcoa", "mdcoa", "nstr", "rtl", "nsl", "tst",
    "agm", "tsm", "icsm", "ascope", "pmesii", "mcoo", "wem", "tem", "cca",
    "tmp", "intsum", "grintsum", "sitemp", "sitrep", "carver", "hptl",
    "hvtl", "frago", "opord", "id", "swo", "nai", "tai", "loc", "los",
    "qrf", "fscm", "fscl", "rfl", "nfa", "sam", "io", "ecm", "emcon",
    "oob", "cbrn", "scada", "atgm", "ifv", "apc", "mbt", "rpg", "ied",
    "oe",
    "sigint", "humint", "geoint", "imint", "masint", "osint", "elint",
    "comint", "ngo", "un", "ihl", "loac", "unesco", "icrc", "nato", "eu",
    "hq", "bn", "bde", "regt", "div", "corps", "bty", "plt", "co", "det",
    "g2", "g3", "g4", "g9", "s2", "s3",
}
_STOP_WORDS = {"and", "or", "of", "the", "to", "in", "on", "for", "with",
               "by", "at", "a", "an", "vs", "via", "per", "but", "as"}


def humanize(field: str) -> str:
    """snake_case → display, with acronym/stop-word/weapon-designator
    handling (the exporter's rules)."""
    def _split_digit_letter(s: str) -> list:
        if s.isalpha() or s.isdigit():
            return [s]
        return [p for p in re.split(
            r'(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)', s) if p]

    def _format_mixed(s: str) -> str:
        parts = _split_digit_letter(s)
        if len(parts) == 1:
            return s
        if (parts[0].isalpha() and len(parts[0]) <= 2
                and len(parts) >= 2 and parts[1].isdigit()):
            return "-".join(p.upper() if p.isalpha() else p for p in parts)
        out = []
        for i, p in enumerate(parts):
            if p.isalpha():
                out.append(p.upper() if i == 0 else p.lower())
            else:
                out.append(p)
        return "".join(out)

    def _token(s: str, *, is_first: bool) -> str:
        if not s:
            return s
        if len(s) >= 2 and s.isalpha() and s.isupper():
            return s
        if any(c.isupper() for c in s) and any(c.isdigit() for c in s):
            return s
        low = s.lower()
        if low in _ACRONYMS:
            return s.upper()
        # Plural acronym forms ("aos" -> "AOs", "pirs" -> "PIRs") —
        # the exporter's own label humanization, never writer output.
        if low.endswith("s") and low[:-1] in _ACRONYMS:
            return low[:-1].upper() + "s"
        if low in _STOP_WORDS:
            return s.title() if is_first else low
        if not s.isalpha() and not s.isdigit():
            return _format_mixed(s)
        if s.isalpha():
            return s.title()
        return s

    parts = (field or "").replace("_", " ").split()
    if not parts:
        return field or ""
    out = []
    first_emitted = False
    for p in parts:
        if "-" in p:
            segments = [s for s in p.split("-") if s]
            any_digit = any(any(c.isdigit() for c in seg) for seg in segments)
            rendered = []
            for i, seg in enumerate(segments):
                rendered.append(_token(seg, is_first=(not first_emitted and i == 0)))
                first_emitted = True
            out.append(("-" if any_digit else " ").join(rendered))
        else:
            out.append(_token(p, is_first=not first_emitted))
            first_emitted = True
    return " ".join(out)


def label_for_field(field: str, spec: Optional[dict]) -> str:
    if spec and isinstance(spec, dict) and spec.get("render_label"):
        return spec["render_label"]
    return humanize(field)


_SNAKE_CASE_VALUE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
_CITATION_BRACKET_RE = re.compile(
    r"\s*\[\d+(?:\s*,\s*\d+)*\](?=[\s.,;:)\]'\"]|$)")


def strip_inline_citations(s: str) -> str:
    if not s:
        return s
    prev = None
    while prev != s:
        prev = s
        s = _CITATION_BRACKET_RE.sub("", s)
    return s


def humanize_enum_value(v: Any, spec: Optional[dict]):
    """enum_labels ALWAYS win (even out-of-enum); snake_case leaks run
    through the humanizer; everything else passes through."""
    if not isinstance(v, str):
        return v
    vs = strip_inline_citations(v).strip()
    if not vs:
        return vs
    if spec and isinstance(spec, dict):
        labels = spec.get("enum_labels") or {}
        if vs in labels:
            return labels[vs]
        enum = spec.get("enum")
        if enum and vs in enum:
            return labels.get(vs) or humanize(vs)
    if _SNAKE_CASE_VALUE_RE.match(vs):
        return humanize(vs)
    return vs


def display_scalar(v: Any) -> str:
    """List/dict-tolerant scalar rendering (the Python-repr leak
    guard): 1-element lists unwrap, scalar lists comma-join, dicts
    JSON-dump."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        if len(v) == 0:
            return ""
        if len(v) == 1:
            return display_scalar(v[0])
        if all(isinstance(x, (str, int, float)) for x in v):
            return ", ".join(display_scalar(x) for x in v)
        return json.dumps(v, default=str)
    if isinstance(v, dict):
        return json.dumps(v, default=str)
    return strip_inline_citations(str(v))


_MGRS_LATLON_RE = re.compile(
    r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def is_mgrs_column(spec: Optional[dict], name: str = "") -> bool:
    if isinstance(spec, dict):
        if "MGRS" in (spec.get("render_label") or ""):
            return True
        name = spec.get("name") or name
    return bool(name) and (name == "mgrs" or name.endswith("_mgrs")
                           or name == "location_mgrs")


def coerce_mgrs_value(v: Any, spec: Optional[dict], name: str = ""):
    """Render-layer safety net: writer-emitted 'lat,lon' in an MGRS
    column converts to MGRS."""
    if not is_mgrs_column(spec, name) or not isinstance(v, str):
        return v
    m = _MGRS_LATLON_RE.match(v)
    if not m:
        return v
    try:
        from app.utils.mgrs_utils import latlon_to_mgrs
        return latlon_to_mgrs(float(m.group(1)), float(m.group(2)))
    except Exception:
        return v


# ---------------------------------------------------------------------------
# Doctrine-ref scrubbing (headings must never leak publication refs)
# ---------------------------------------------------------------------------

_DOCTRINE_PAREN_RE = re.compile(
    r"\s*\(\s*(?:per\s+)?"
    r"(?:fig(?:ure)?\b|tbl|table\b|atp\b|fm\b|jp\b|adp\b|tc\b|tm\b|ar\b|"
    r"ch\b|chap\b|chapter\b|para\b|paragraph\b|app\b|appendix\b)"
    r"[^()]*\)\s*$",
    re.IGNORECASE,
)
_DOCTRINE_SUFFIX_RE = re.compile(
    r"\s*[–—\-:;,]\s*(?:per\s+)?"
    r"(?:fig(?:ure)?|tbl|table|atp|fm|jp|adp|tc|tm|ar|ch|chap|chapter|"
    r"para|paragraph|app|appendix)\b[^()]*$",
    re.IGNORECASE,
)


def strip_doctrine_refs(s: str) -> str:
    if not s:
        return s
    prev = None
    while prev != s:
        prev = s
        s = _DOCTRINE_PAREN_RE.sub("", s)
        s = _DOCTRINE_SUFFIX_RE.sub("", s)
    return s.rstrip()


# Scaffold tokens that leak from schema render_labels.
def strip_scaffold_tokens(label: str) -> str:
    for tok in (" (M-####)", "(M-####)", " (M-XXXX)", "(M-XXXX)",
                " [M-####]", "[M-####]"):
        label = label.replace(tok, "")
    return label


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------

def published_row_fields(schema: dict) -> list[tuple[str, dict]]:
    out = []
    for name, spec in (schema.get("row_fields") or {}).items():
        if (spec or {}).get("view", "published") == "published":
            out.append((name, spec or {}))
    return out


def workpaper_row_fields(schema: dict) -> list[tuple[str, dict]]:
    return [(f, s or {}) for f, s in (schema.get("row_fields") or {}).items()
            if (s or {}).get("view") == "workpaper"]


def published_paragraph_fields(schema: dict) -> list[dict]:
    fields = [p for p in (schema.get("paragraph_fields") or [])
              if isinstance(p, dict)
              and (p.get("view", "published")) == "published"]
    # Schema-declared render order (BLUF products: the OED leads with
    # its summary, the MCOO leads with the map). Listed names render
    # first in the listed order; everything else keeps SPEC order.
    order = schema.get("paragraph_render_order") or []
    if order:
        rank = {n: i for i, n in enumerate(order)}
        fields = sorted(
            fields,
            key=lambda f: (rank.get(f.get("name"), len(order)),
                           0 if f.get("name") in rank
                           else fields.index(f)))
    return fields


# ---------------------------------------------------------------------------
# Column width heuristic (DXA weights; lanes convert to their units)
# ---------------------------------------------------------------------------

_ULTRA_NARROW = {"score", "priority", "rank", "pri", "criticality_score",
                 "accessibility_score", "recuperability_score",
                 "vulnerability_score", "effect_score",
                 "recognizability_score"}
_NARROW = {"uic", "code", "echelon", "size", "side", "type", "hvi_id",
           "target_number", "answered", "precedence"}
_MEDIUM_NARROW = {"id", "doi", "dtg", "mgrs", "location_mgrs", "location",
                  "total", "composite_total_score"}
_MEDIUM = {"parameter", "assessment", "factor", "protection_basis"}
_WIDE = {"narrative", "rationale", "justification", "activity",
         "activity_description", "statement", "description", "summary",
         "threshold", "favorable_threshold", "unfavorable_threshold",
         "current_forecast_value", "explanation", "guidance",
         "requirement_text"}


def column_weights(names: list[str]) -> list[float]:
    weights = []
    for name in names:
        n = (name or "").lower()
        if any(k in n for k in _WIDE):
            w = 3.0
        elif n in _MEDIUM or any(n.endswith("_" + k) for k in _MEDIUM):
            w = 2.1
        elif n in _MEDIUM_NARROW or any(n.endswith("_" + k)
                                        for k in _MEDIUM_NARROW):
            w = 1.5
        elif any(n == k or n.endswith("_" + k) for k in _ULTRA_NARROW):
            w = 0.55
        elif any(n == k or n.startswith(k + "_") or n.endswith("_" + k)
                 for k in _NARROW):
            w = 1.1
        else:
            w = 1.9
        weights.append(w)
    return weights


# ---------------------------------------------------------------------------
# Matrix normalization — the writer-drift absorber (ported whole)
# ---------------------------------------------------------------------------

_ROW_ID_FIELDS = ("id", "row_id", "row", "name", "pir", "function",
                  "warfighting_function", "wff", "hpt", "hpt_id",
                  "target", "target_id", "unit")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)```\s*$",
                            re.DOTALL | re.IGNORECASE)
_MD_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_MD_SEP_LINE = re.compile(r"^\s*\|[\s:|\-]+\|\s*$")


def parse_markdown_table(text: str):
    """(headers, rows) from a markdown table string; ([], []) when the
    string is not one. The writer-drift absorber both format lanes
    share."""
    if not isinstance(text, str) or "|" not in text:
        return [], []
    lines = [ln for ln in text.splitlines() if _MD_TABLE_LINE.match(ln)]
    data = [ln for ln in lines if not _MD_SEP_LINE.match(ln)]
    if len(data) < 2:
        return [], []

    def _split(ln):
        return [re.sub(r"\*+", "", c).strip()
                for c in ln.strip().strip("|").split("|")]

    headers = _split(data[0])
    rows = [_split(ln) for ln in data[1:]]
    width = len(headers)
    return headers, [(r + [""] * (width - len(r)))[:width] for r in rows]


def _snake_fold(k: str) -> str:
    if not isinstance(k, str):
        return ""
    s = k.strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return re.sub(r"_+", "_", s).strip("_")


def maybe_parse_fenced_json(value):
    if not isinstance(value, str):
        return value
    s = value.strip()
    m = _JSON_FENCE_RE.match(s)
    inner = m.group(1).strip() if m else s
    if not (inner.startswith("{") or inner.startswith("[")):
        return value
    try:
        return json.loads(inner)
    except Exception:
        return value


def _parse_row_col_lines(text: str, row_axis: Optional[list],
                         col_axis: Optional[list]) -> dict:
    """Absorb the flat "Row-Col: value; Row-Col: value" writer drift.
    Only axis-matching "<row>-<col>:" pairs anchor, so values containing
    hyphens or semicolons survive intact."""
    if not (isinstance(text, str) and row_axis and col_axis):
        return {}
    rows = {_snake_fold(r): r for r in row_axis}
    cols = {_snake_fold(c): c for c in col_axis}
    seg_re = re.compile(r"([A-Za-z_ ]+?)\s*[-\u2013/]\s*([A-Za-z_ ]+?)\s*:\s*")
    anchors = []
    for m in seg_re.finditer(text):
        if _snake_fold(m.group(1)) in rows and _snake_fold(m.group(2)) in cols:
            anchors.append((m.start(), m.end(), m.group(1), m.group(2)))
    grid: dict = {}
    for i, (s0, e0, r, c) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < len(anchors) else len(text)
        val = text[e0:end].strip().rstrip(";.").strip()
        if val:
            grid.setdefault(rows[_snake_fold(r)], {})[
                cols[_snake_fold(c)]] = val
    return grid


def normalize_matrix(matrix, row_axis: Optional[list] = None,
                     col_axis: Optional[list] = None) -> dict:
    """Coerce every observed writer matrix shape into canonical
    {row: {col: scalar}}: fenced/bare JSON strings, list-of-dicts with
    a row-id field, rows[]/cols[] positional form, wrapped cells dicts
    (nested or flat '<row>_<col>' keys), and prose-key folding against
    the declared axes."""
    if isinstance(matrix, str):
        matrix = maybe_parse_fenced_json(matrix)
        if isinstance(matrix, str):
            # A markdown table in a string cell — parse and re-enter so
            # the declared-axis folding below applies.
            headers, md_rows = parse_markdown_table(matrix)
            if headers and md_rows:
                grid: dict = {}
                for r in md_rows:
                    label = (r[0] or "").strip()
                    if not label:
                        continue
                    grid[label] = {h: v for h, v in zip(headers[1:], r[1:])
                                   if h and v}
                if grid:
                    return normalize_matrix(grid, row_axis, col_axis)
            flat = _parse_row_col_lines(matrix, row_axis, col_axis)
            if flat:
                return normalize_matrix(flat, row_axis, col_axis)
            return {}
    if isinstance(matrix, list):
        grid: dict = {}
        for r in matrix:
            if not isinstance(r, dict):
                continue
            rid = None
            rid_field = None
            for f in _ROW_ID_FIELDS:
                v = r.get(f)
                if v not in (None, "", [], {}):
                    rid, rid_field = v, f
                    break
            if not rid:
                continue
            grid[str(rid)] = {k: v for k, v in r.items() if k != rid_field}
        return grid
    if not isinstance(matrix, dict):
        return {}
    rows_field = matrix.get("rows")
    if isinstance(rows_field, list) and col_axis:
        grid = {}
        prov_flat = (matrix.get("_provenance")
                     if isinstance(matrix.get("_provenance"), dict) else None)
        for r in rows_field:
            if not isinstance(r, dict):
                continue
            rid = r.get("row_id") or r.get("row") or r.get("name")
            if not rid:
                continue
            cols_val = r.get("cols") or r.get("values") or []
            row_dict: dict = {}
            for idx, col_name in enumerate(col_axis):
                row_dict[col_name] = (cols_val[idx]
                                      if idx < len(cols_val) else None)
            if prov_flat is not None:
                inner = {}
                for col_name in col_axis:
                    key = f"{rid}_{col_name}"
                    if prov_flat.get(key):
                        v = prov_flat[key]
                        inner[col_name] = (", ".join(v)
                                           if isinstance(v, list) else v)
                if inner:
                    row_dict["_provenance"] = inner
            grid[rid] = row_dict
        if grid:
            return grid
    if matrix and "cells" not in matrix:
        # Prose-key folding against declared axes.
        if row_axis or col_axis:
            def _resolve(k, axis):
                if not axis or k in axis:
                    return k
                folded = _snake_fold(k)
                for tok in axis:
                    if _snake_fold(tok) == folded:
                        return tok
                return k
            normalized: dict = {}
            for rk, rv in matrix.items():
                if rk == "_provenance":
                    normalized[rk] = rv
                    continue
                new_rk = _resolve(rk, row_axis)
                if isinstance(rv, dict) and col_axis:
                    new_rv: dict = {}
                    for ck, cv in rv.items():
                        if ck == "_provenance" and isinstance(cv, dict):
                            new_rv[ck] = {_resolve(pk, col_axis): pv
                                          for pk, pv in cv.items()}
                        else:
                            new_rv[_resolve(ck, col_axis)] = cv
                    normalized[new_rk] = new_rv
                else:
                    normalized[new_rk] = rv
            return normalized
        return matrix
    cells = matrix.get("cells")

    def _cell_to_str(val):
        if val in (None, "", [], {}):
            return ""
        if isinstance(val, (int, float, bool)):
            return str(val)
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            name = (val.get("name") or val.get("title") or val.get("label")
                    or val.get("id"))
            details = (val.get("details") or val.get("description")
                       or val.get("text") or val.get("value"))
            if name and details:
                return f"{name} ({details})"
            return str(name or details or "")
        if isinstance(val, list):
            parts = [_cell_to_str(it) for it in val]
            return "; ".join(p for p in parts if p)
        return str(val)

    if isinstance(cells, dict):
        if row_axis and col_axis:
            grid = {r: {} for r in row_axis}
            prov_flat = (matrix.get("_provenance")
                         if isinstance(matrix.get("_provenance"), dict)
                         else None)
            for flat_key, val in cells.items():
                for r in sorted(row_axis, key=len, reverse=True):
                    if flat_key == r or flat_key.startswith(r + "_"):
                        rest = flat_key[len(r):].lstrip("_")
                        if rest in col_axis:
                            cv = _cell_to_str(val)
                            if cv:
                                grid[r][rest] = cv
                            if prov_flat and prov_flat.get(flat_key):
                                grid[r].setdefault(
                                    "_provenance", {})[rest] = prov_flat[flat_key]
                        break
            return grid
        return cells
    if isinstance(cells, list):
        grid = {}
        for c in cells:
            if not isinstance(c, dict):
                continue
            r, col = c.get("row"), c.get("col")
            if r is None or col is None:
                continue
            v = _cell_to_str(c.get("value"))
            existing = grid.setdefault(r, {}).get(col)
            grid[r][col] = f"{existing}; {v}" if existing and v else (existing or v)
        return grid
    return {}


# ---------------------------------------------------------------------------
# Footnote registry — Sources rendered from the closed set's citations
# ---------------------------------------------------------------------------

_NONCITE_NORMALIZED = {
    "operations expert directive", "operator directive",
    "no significant activity reported.", "no significant activity reported",
    "no reporting this period.", "no reporting this period",
    "no update this period.", "no update this period",
    "no_activity", "no activity", "n/a", "none", "(none)", "dtg", "nstr",
}


def _normalize_citation(c: str) -> str:
    if not c:
        return ""
    s = str(c).strip()
    s = re.sub(r"\s*@\s*\d{6,}Z?\b.*$", "", s)
    s = re.sub(r"\s*\(\s*\d{6,}Z?\b[^)]*\)\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


class FootnoteRegistry:
    """Per-claim markers + the numbered Sources section. Citations
    come from the CLOSED retrieval set's resolved records (clause
    quotes / entity names / document filenames) — dedupe by normalized
    text; filler provenance dropped."""

    def __init__(self):
        self.footnotes: list[tuple[int, str]] = []
        self.seen: dict[str, int] = {}

    def register(self, citation: str) -> int:
        if not citation:
            return 0
        c = _normalize_citation(citation)
        if not c or c.lower() in _NONCITE_NORMALIZED:
            return 0
        if c in self.seen:
            return self.seen[c]
        n = len(self.footnotes) + 1
        self.seen[c] = n
        self.footnotes.append((n, c))
        return n
