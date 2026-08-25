#!/usr/bin/env python3
"""Generate the `topo` sprite sheet for the topo tileserver style.

One pattern image: `topo-pat-wetland` — the topographic-sheet wetland
tussock signature (a short horizontal ground stroke with grass ticks
fanning up from its center, staggered half-tile so the repeat reads as
scattered marsh symbols rather than a grid). Drawn in the same blue as
the style's stream strokes.

Writes infra/tileserver/sprites/topo.json + topo.png and the @2x pair.
Rerun after any pattern change; the outputs are checked in (tileserver
serves them by name via the style's "sprite": "topo" key).

Usage: python3 scripts/generate_topo_sprite.py
"""

import json
import os

from PIL import Image, ImageDraw

TILE = 28          # matches the mcoo sprite tile scale
BLUE = (74, 134, 189, 255)  # #4a86bd — stream blue

SPRITES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "infra", "tileserver", "sprites",
)


def draw_tussock(draw: ImageDraw.ImageDraw, cx: int, cy: int, s: float) -> None:
    """One tussock: ground line + three grass ticks, centered at (cx, cy).

    `s` scales stroke geometry for the @2x sheet.
    """
    w = max(1, round(s))
    # Ground line
    draw.line([(cx - 4 * s, cy), (cx + 4 * s, cy)], fill=BLUE, width=w)
    # Grass ticks: center tallest, sides splayed
    draw.line([(cx, cy), (cx, cy - 4 * s)], fill=BLUE, width=w)
    draw.line([(cx - 2 * s, cy), (cx - 3 * s, cy - 3 * s)], fill=BLUE, width=w)
    draw.line([(cx + 2 * s, cy), (cx + 3 * s, cy - 3 * s)], fill=BLUE, width=w)


def build_sheet(scale: int) -> Image.Image:
    size = TILE * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = scale
    # Two tussocks per tile, offset half-tile for a staggered repeat.
    draw_tussock(draw, size // 4, size // 4 + 2 * s, s)
    draw_tussock(draw, (size * 3) // 4, (size * 3) // 4 + 2 * s, s)
    return img


def write_sheet(scale: int, suffix: str) -> None:
    img = build_sheet(scale)
    png_path = os.path.join(SPRITES_DIR, f"topo{suffix}.png")
    json_path = os.path.join(SPRITES_DIR, f"topo{suffix}.json")
    img.save(png_path)
    index = {
        "topo-pat-wetland": {
            "width": TILE * scale,
            "height": TILE * scale,
            "x": 0,
            "y": 0,
            "pixelRatio": scale,
        }
    }
    with open(json_path, "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")
    print(f"wrote {png_path} + {json_path}")


if __name__ == "__main__":
    write_sheet(1, "")
    write_sheet(2, "@2x")
