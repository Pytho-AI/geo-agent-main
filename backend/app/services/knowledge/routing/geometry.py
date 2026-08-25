"""Convert A* node path to drawing coordinates."""

from typing import Dict, List, Tuple

from .models import Node, MacroTile


def collect_path_geometry(
    path: list,
    draw_data: Dict[Tuple[Node, Node], List[Tuple[float, float]]],
    node_pos: Dict[Node, Tuple[float, float]],
    tile_grid: List[List[MacroTile]],
    start_lat: float, start_lon: float,
    end_lat: float, end_lon: float,
) -> List[Tuple[float, float]]:
    """Convert A* node path to (lon, lat) drawing coordinates."""
    if not path:
        return []

    coords = [(start_lon, start_lat)]

    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        edge_key = (a, b)

        if edge_key in draw_data:
            coords.extend(draw_data[edge_key])
        elif a.kind == "tile" and b.kind == "tile":
            t = tile_grid[b.row][b.col]
            coords.append((t.center_lon, t.center_lat))
        elif a.kind == "road" and b.kind == "tile":
            t = tile_grid[b.row][b.col]
            coords.append((t.center_lon, t.center_lat))
        elif a.kind == "tile" and b.kind == "road":
            pos = node_pos.get(b)
            if pos:
                coords.append(pos)
        else:
            pos = node_pos.get(b)
            if pos:
                coords.append(pos)

    coords.append((end_lon, end_lat))
    return coords
