#!/usr/bin/env python3
"""
Import MIL-STD-2525E symbol tables from the spatialillusions
`milstandard-e` repository (MIT) into the backend symbol catalog.

Source of truth: https://github.com/spatialillusions/milstandard-e
(TSV tables transcribed from MIL-STD-2525E). Run this whenever the
upstream tables change:

    python3 backend/scripts/import_milstd_2525e.py [path-to-milstandard-e]

Writes one JSON per symbol set to backend/app/data/milstd/ in the shape
`constants/symbols.py` loads:

    { "symbolset": "10", "name": "Land Unit",
      "main icon":  [{entity, entity type?, entity subtype?, code, remarks}, ...],
      "modifier 1": [{modifier, category, code, remarks}, ...],
      "modifier 2": [...] }

Main-icon rows forward-fill Entity / Entity Type context exactly like
the upstream tsv2json.js so subtype rows carry their full lineage.
"""

import json
import sys
from pathlib import Path

# Symbol set code -> (display name, TSV base name). Set 27 (Dismounted
# Individual) is new in 2525E.
SETS = {
    "01": ("Air", "Air"),
    "02": ("Air Missile", "Air missile"),
    "05": ("Space", "Space"),
    "06": ("Space Missile", "Space missile"),
    "10": ("Land Unit", "Land unit"),
    "11": ("Land Civilian", "Land civilian"),
    "15": ("Land Equipment", "Land equipment"),
    "20": ("Land Installation", "Land installation"),
    "25": ("Control Measure", "Control Measures"),
    "27": ("Dismounted Individual", "Dismounted individual"),
    "30": ("Sea Surface", "Sea surface"),
    "35": ("Sea Subsurface", "Sea subsurface"),
    "36": ("Mine Warfare", "Mine warfare"),
    "40": ("Activities", "Activities"),
    "50": ("Signals Intelligence", "Signals intelligence"),
    "60": ("Cyberspace", "Cyberspace"),
}


def read_tsv(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").replace("\r", "").split("\n"):
        if line == "":
            continue
        rows.append(line.split("\t"))
    return rows


def clean(value: str) -> str:
    return (value or "").strip()


def parse_main_icon(path: Path) -> list[dict]:
    rows = read_tsv(path)
    header = rows[0]
    icons = []
    entity = ""
    entity_type = ""
    for values in rows[1:]:
        row = {header[i]: values[i] if i < len(values) else "" for i in range(len(header))}
        e = clean(row.get("Entity"))
        et = clean(row.get("Entity Type"))
        est = clean(row.get("Entity Subtype"))
        code = clean(row.get("Code"))
        remarks = clean(row.get("Remarks"))
        if not code:
            continue
        if e:
            entity = e
            entity_type = ""
        if et:
            entity_type = et
        icon = {"entity": entity}
        if et or est:
            icon["entity type"] = entity_type
        if est:
            icon["entity subtype"] = est
        # Control Measures carry a per-icon geometry (Point/Line/Area)
        # the picker uses to route the draw flow.
        geometry = clean(row.get("Geometric Rendering"))
        if geometry:
            icon["geometry"] = geometry
        icon["code"] = code
        icon["remarks"] = remarks
        icons.append(icon)
    if not icons or icons[0].get("code") != "000000":
        icons.insert(0, {"entity": "Unspecified", "code": "000000", "remarks": ""})
    return icons


def parse_modifiers(path: Path) -> list[dict]:
    if not path.exists():
        return [{"modifier": "Unspecified", "category": "", "code": "00", "remarks": ""}]
    rows = read_tsv(path)
    header = rows[0]
    mods = []
    for values in rows[1:]:
        row = {header[i]: values[i] if i < len(values) else "" for i in range(len(header))}
        name = clean(row.get("First Modifier") or row.get("Second Modifier") or row.get("Modifier"))
        code = clean(row.get("Code"))
        if not code:
            continue
        mods.append({
            "modifier": name,
            "category": clean(row.get("Category")),
            "code": code,
            "remarks": clean(row.get("Remarks")),
        })
    if not mods or mods[0].get("code") != "00":
        mods.insert(0, {"modifier": "Unspecified", "category": "", "code": "00", "remarks": ""})
    return mods


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[3] / "scratch" / "oss" / "milstandard-e")
    tsv_dir = source / "tsv-tables"
    if not tsv_dir.is_dir():
        print(f"milstandard-e tsv-tables not found at {tsv_dir}", file=sys.stderr)
        return 1
    out_dir = Path(__file__).resolve().parents[1] / "app" / "data" / "milstd"
    out_dir.mkdir(parents=True, exist_ok=True)

    for code, (name, base) in sorted(SETS.items()):
        main_icon = parse_main_icon(tsv_dir / f"{base}.tsv")
        doc = {
            "symbolset": code,
            "name": name,
            "main icon": main_icon,
            "modifier 1": parse_modifiers(tsv_dir / f"{base} sector 1.tsv"),
            "modifier 2": parse_modifiers(tsv_dir / f"{base} sector 2.tsv"),
        }
        out = out_dir / f"2525E {code} {base.lower().replace(' ', '-')}.json"
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{out.name}: {len(main_icon)} icons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
