#!/usr/bin/env python3
"""Build the MCOO doctrinal hatch sprite sheet used by infra/tileserver/styles/omt-mcoo.json.

Ports the three canvas-generated patterns from pytho-app/ui/src/geo-agent/utils/terrainHatches.js
(`drawRestrictedPattern`, `drawSeverePattern`, `drawUrbanPattern`) to static PNGs packed into a
single sprite sheet so tileserver-gl's server-side renderer can resolve `fill-pattern` references
without a browser canvas runtime. The patterns themselves are tiny (28x28, 22x22, 36x36) so the
sheet packs to a single horizontal strip --- no rectangle-packing logic needed.

Output layout matches the MapLibre/Mapbox sprite convention so tileserver-gl picks it up via the
`sprite:` entry in tileserver-config.json:

  infra/tileserver/sprites/mcoo.png      packed sheet
  infra/tileserver/sprites/mcoo.json     { "<icon-id>": {x, y, width, height, pixelRatio} ... }
  infra/tileserver/sprites/mcoo@2x.png   2x sheet for HiDPI clients (same artwork, 2x bitmap)
  infra/tileserver/sprites/mcoo@2x.json  manifest with pixelRatio=2 entries

Icon IDs match `terrainHatches.js` PATTERNS[] so the omt-mcoo.json style references the same
string-ids the client-side hatching pipeline uses. Keeping the names aligned makes the legend /
parity probes (which queryRenderedFeatures by paint-image id) keep working without a rename pass.

Usage: python scripts/build_mcoo_sprite.py
Idempotent. Overwrites prior outputs. Requires Pillow.
"""
from __future__ import annotations

import json
from pathlib import Path
from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "infra" / "tileserver" / "sprites"

# (id, size_px, draw_fn) ---- size matches terrainHatches.js PATTERNS exactly so the visual
# scale of the basemap-painted MCOO matches the client-side overlay painting that's been
# tuned across many render iterations.
PATTERNS: list[tuple[str, int, str]] = [
    ("mcoo-pat-restricted", 28, "restricted"),
    ("mcoo-pat-severe",     22, "severe"),
    # Urban was at 36px which made each X-cell ~3x the linear scale of the
    # restricted-hatch step (and ~9x the area). At 18px each X-cell is
    # roughly the same on-screen footprint as one diagonal stripe of the
    # restricted hatch, which is what fig 4-9 calls for: the urban marker
    # should READ as a distinct pattern, not dominate the basemap.
    ("mcoo-pat-urban",      18, "urban"),
]


def _draw_restricted(img: Image.Image, n: int) -> None:
    """Fig 4-9 restricted-terrain: widely-spaced thin dark-green diagonals on transparent.
    Mirrors drawRestrictedPattern in terrainHatches.js verbatim --- same color, same lineWidth,
    same step (n/2), same direction (top-left to bottom-right)."""
    d = ImageDraw.Draw(img)
    step = n // 2 or 1
    # Range and slope match the JS: moveTo(i, 0) -> lineTo(i + n, n).
    # i sweeps from -n to 2n in `step` increments so both wrap-around edges are filled.
    for i in range(-n, 2 * n + 1, step):
        d.line([(i, 0), (i + n, n)], fill=(10, 58, 20, 255), width=1)


def _draw_severe(img: Image.Image, n: int) -> None:
    """Fig 4-9 severely-restricted: cross-hatch on transparent (both diagonals)."""
    d = ImageDraw.Draw(img)
    step = n // 3 or 1
    color = (13, 74, 26, 255)
    # forward diagonals
    for i in range(-n, 2 * n + 1, step):
        d.line([(i, 0), (i + n, n)], fill=color, width=1)
    # back diagonals
    for i in range(-n, 2 * n + 1, step):
        d.line([(i, n), (i + n, 0)], fill=color, width=1)


def _draw_urban(img: Image.Image, n: int) -> None:
    """Fig 4-9 / 4-10 urban: translucent-white cell with black square outline + X across it.
    The JS uses rgba(255,255,255,0.55) for the cell fill --- preserve that opacity so the
    pattern dims the basemap underneath without occluding it."""
    d = ImageDraw.Draw(img)
    d.rectangle([(0, 0), (n - 1, n - 1)], fill=(255, 255, 255, 140))  # 0.55 * 255 = 140
    d.rectangle([(0, 0), (n - 1, n - 1)], outline=(0, 0, 0, 255), width=1)
    d.line([(1, 1), (n - 2, n - 2)], fill=(0, 0, 0, 255), width=1)
    d.line([(n - 2, 1), (1, n - 2)], fill=(0, 0, 0, 255), width=1)


_DRAWERS = {
    "restricted": _draw_restricted,
    "severe":     _draw_severe,
    "urban":      _draw_urban,
}


def _render_pattern(kind: str, size: int, scale: int = 1) -> Image.Image:
    """Render one pattern tile at the given scale. scale=2 doubles dimensions for @2x sheet."""
    n = size * scale
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    _DRAWERS[kind](img, n)
    return img


def _build_sheet(scale: int) -> tuple[Image.Image, dict]:
    """Pack all patterns into a single horizontal-strip PNG and emit the matching manifest.
    Horizontal strip is the simplest packing that satisfies the sprite-sheet spec; the
    patterns are too small (max 72px at 2x) for fancier packing to matter."""
    tiles = [(pid, size * scale, _render_pattern(kind, size, scale)) for pid, size, kind in PATTERNS]
    sheet_w = sum(t.width for _, _, t in tiles)
    sheet_h = max(t.height for _, _, t in tiles)
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    manifest: dict = {}
    x = 0
    for pid, _, t in tiles:
        sheet.paste(t, (x, 0))
        manifest[pid] = {
            "x": x,
            "y": 0,
            "width": t.width,
            "height": t.height,
            "pixelRatio": scale,
        }
        x += t.width
    return sheet, manifest


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1x sheet
    sheet, manifest = _build_sheet(scale=1)
    sheet.save(OUT_DIR / "mcoo.png", format="PNG", optimize=True)
    (OUT_DIR / "mcoo.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # 2x sheet for HiDPI / headless renders that bump pixel_ratio to 1.5 or 2
    sheet2, manifest2 = _build_sheet(scale=2)
    sheet2.save(OUT_DIR / "mcoo@2x.png", format="PNG", optimize=True)
    (OUT_DIR / "mcoo@2x.json").write_text(json.dumps(manifest2, indent=2) + "\n")

    print(f"wrote {OUT_DIR / 'mcoo.png'} ({sheet.size[0]}x{sheet.size[1]})")
    print(f"wrote {OUT_DIR / 'mcoo.json'} (3 patterns)")
    print(f"wrote {OUT_DIR / 'mcoo@2x.png'} ({sheet2.size[0]}x{sheet2.size[1]})")
    print(f"wrote {OUT_DIR / 'mcoo@2x.json'} (3 patterns)")


if __name__ == "__main__":
    main()
