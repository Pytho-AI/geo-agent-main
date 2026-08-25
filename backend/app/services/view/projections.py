"""The render is a camera — the projection family (design §6.9).

Plan view is one camera over the 4D store. These are the others,
each answering the class of question doctrine built it for:

- PROFILE: a vertical slice along a ray — terrain analysis's
  line-of-sight / crest-clearance diagram. DEM sampled along the ray,
  entities near the line marked at their along-line distance.
- ENVELOPE: altitude versus range for a system — the classic
  air-defense envelope chart, read straight from the range-candidate
  columns (§6.7's altitude bands and trajectory classes).

Both are render-time functions over stored data — nothing new is
stored — drawn with PIL so the export is self-contained.
"""
import io
import logging
import math
from typing import List, Optional, Tuple

log = logging.getLogger("app.view.projections")

_W, _H = 1400, 460
_MARGIN_L, _MARGIN_R, _MARGIN_T, _MARGIN_B = 70, 30, 30, 46
_BG = (252, 251, 247)
_INK = (26, 26, 26)
_TERRAIN = (188, 154, 110)
_TERRAIN_FILL = (222, 200, 168)
_GRID = (200, 200, 200)
_LOS = (185, 28, 28)


def _font(size=12):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


async def profile_image(start: Tuple[float, float], end: Tuple[float, float],
                        entities: Optional[List[dict]] = None,
                        samples: int = 240) -> bytes:
    """Terrain profile along the ray start→end ((lat, lon) pairs).
    Entities: [{name, lat, lon}] — marked where they project onto the
    ray (within 5 km lateral). Returns PNG bytes."""
    from PIL import Image, ImageDraw

    from app.services.view.coverage import _elevations

    (la1, lo1), (la2, lo2) = start, end
    pts = [(la1 + (la2 - la1) * k / (samples - 1),
            lo1 + (lo2 - lo1) * k / (samples - 1))
           for k in range(samples)]
    elev = await _elevations(pts)
    prof = [(e if e is not None else 0.0) for e in elev]

    coslat = math.cos(math.radians((la1 + la2) / 2.0)) or 1e-9
    total_km = math.hypot((la2 - la1) * 111.32,
                          (lo2 - lo1) * 111.32 * coslat)
    lo_e = min(prof)
    hi_e = max(prof)
    pad = max(20.0, (hi_e - lo_e) * 0.15)
    lo_e -= pad
    hi_e += pad

    img = Image.new("RGB", (_W, _H), _BG)
    dr = ImageDraw.Draw(img)
    plot_w = _W - _MARGIN_L - _MARGIN_R
    plot_h = _H - _MARGIN_T - _MARGIN_B

    def X(km):
        return _MARGIN_L + plot_w * (km / max(total_km, 1e-6))

    def Y(m):
        return _MARGIN_T + plot_h * (1.0 - (m - lo_e) / max(hi_e - lo_e, 1.0))

    f = _font(12)
    fs = _font(11)
    # Grid + axis labels.
    for gx in range(0, int(total_km) + 1, max(1, int(total_km // 8) or 1)):
        dr.line([(X(gx), _MARGIN_T), (X(gx), _H - _MARGIN_B)],
                fill=_GRID, width=1)
        dr.text((X(gx) - 8, _H - _MARGIN_B + 6), f"{gx} km",
                fill=_INK, font=fs)
    estep = max(10, int((hi_e - lo_e) / 6 // 10 * 10) or 10)
    ge = int(lo_e // estep) * estep
    while ge <= hi_e:
        dr.line([(_MARGIN_L, Y(ge)), (_W - _MARGIN_R, Y(ge))],
                fill=_GRID, width=1)
        dr.text((8, Y(ge) - 7), f"{int(ge)} m", fill=_INK, font=fs)
        ge += estep

    # Terrain surface: filled below the profile.
    line = [(X(total_km * k / (samples - 1)), Y(prof[k]))
            for k in range(samples)]
    dr.polygon(line + [(X(total_km), Y(lo_e)), (X(0), Y(lo_e))],
               fill=_TERRAIN_FILL)

    # LINE OF SIGHT from the start point's eye height: the crest walk
    # (same physics as the coverage viewshed). Every terrain sample is
    # VISIBLE or DEAD SPACE, and the diagram exists to show which —
    # visible ground drawn green, defiladed ground red, the actual
    # grazing sightline drawn to the controlling crest.
    eye = prof[0] + 10.0
    visible = [True] * samples
    max_tan = -math.inf
    for k in range(1, samples):
        d = total_km * 1000.0 * k / (samples - 1)
        t = (prof[k] - eye) / d
        if t < max_tan:
            visible[k] = False
        else:
            max_tan = t
    seg_start = 0
    for k in range(1, samples + 1):
        if k == samples or visible[k] != visible[seg_start]:
            seg = line[seg_start:k]
            if len(seg) >= 2:
                dr.line(seg,
                        fill=((20, 130, 70) if visible[seg_start]
                              else (185, 28, 28)),
                        width=3)
            seg_start = k
    # Grazing rays from the eye over each controlling crest.
    max_tan = -math.inf
    for k in range(1, samples):
        d = total_km * 1000.0 * k / (samples - 1)
        t = (prof[k] - eye) / d
        if t > max_tan:
            max_tan = t
            dr.line([(X(0), Y(eye)),
                     (line[k][0], line[k][1])],
                    fill=(120, 120, 120), width=1)
    dr.ellipse([(X(0) - 4, Y(eye) - 4), (X(0) + 4, Y(eye) + 4)],
               fill=_LOS)
    dr.text((X(0) + 6, Y(eye) - 18), "OBS", fill=_LOS, font=fs)
    # Legend.
    dr.line([(X(total_km) - 300, 14), (X(total_km) - 260, 14)],
            fill=(20, 130, 70), width=3)
    dr.text((X(total_km) - 252, 8), "visible", fill=_INK, font=fs)
    dr.line([(X(total_km) - 180, 14), (X(total_km) - 140, 14)],
            fill=(185, 28, 28), width=3)
    dr.text((X(total_km) - 132, 8), "dead space", fill=_INK, font=fs)

    # Entities projected onto the ray.
    for ent in entities or []:
        dx = (ent["lon"] - lo1) * 111.32 * coslat
        dy = (ent["lat"] - la1) * 111.32
        ux = (lo2 - lo1) * 111.32 * coslat
        uy = (la2 - la1) * 111.32
        t = (dx * ux + dy * uy) / max(total_km ** 2, 1e-9)
        if not (0.0 <= t <= 1.0):
            continue
        lat_off = abs(dx * uy - dy * ux) / max(total_km, 1e-9)
        if lat_off > 5.0:
            continue
        km = t * total_km
        k = min(samples - 1, int(round(t * (samples - 1))))
        ey = Y(prof[k])
        dr.line([(X(km), ey), (X(km), ey - 26)], fill=_INK, width=2)
        dr.ellipse([(X(km) - 4, ey - 34), (X(km) + 4, ey - 26)],
                   outline=_INK, width=2, fill=(240, 90, 90))
        dr.text((X(km) + 6, ey - 40), str(ent.get("name", ""))[:28],
                fill=_INK, font=fs)

    dr.text((_MARGIN_L, 8),
            f"PROFILE  {la1:.4f},{lo1:.4f}  ->  {la2:.4f},{lo2:.4f}  "
            f"({total_km:.1f} km)", fill=_INK, font=f)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def envelope_image(name: str, candidates: List[dict],
                   max_elevation_deg: Optional[float] = None) -> bytes:
    """Altitude-versus-range envelope chart for one system.
    candidates: [{label, range_m, min_altitude_m, max_altitude_m,
    trajectory, is_default, condition}]. For gun systems,
    max_elevation_deg bounds the envelope from above-inside: the
    reachable wedge is h <= x*tan(theta_max) (ceiling derived
    backwards from maximum gun elevation; the region past it is the
    overhead dead zone). Returns PNG bytes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (_W, _H), _BG)
    dr = ImageDraw.Draw(img)
    plot_w = _W - _MARGIN_L - _MARGIN_R
    plot_h = _H - _MARGIN_T - _MARGIN_B
    f = _font(12)
    fs = _font(11)

    max_r = max((c.get("range_m") or 0) for c in candidates) or 1000
    max_a = max(((c.get("max_altitude_m") or 0) for c in candidates),
                default=0)
    if max_a <= 0:
        # Unstated ceilings: chart to a plausible band — with headroom
        # for the parabola of safety's R/2 peak when ballistic.
        ballistic = any((c.get("trajectory") or "").lower() == "ballistic"
                        for c in candidates)
        max_a = max_r * (0.55 if ballistic else 0.4)

    def X(m):
        return _MARGIN_L + plot_w * (m / max_r)

    def Y(m):
        return _MARGIN_T + plot_h * (1.0 - m / max(max_a, 1.0))

    for gx_km in range(0, int(max_r / 1000) + 1,
                       max(1, int(max_r / 1000 // 8) or 1)):
        dr.line([(X(gx_km * 1000), _MARGIN_T),
                 (X(gx_km * 1000), _H - _MARGIN_B)], fill=_GRID)
        dr.text((X(gx_km * 1000) - 10, _H - _MARGIN_B + 6),
                f"{gx_km} km", fill=_INK, font=fs)
    astep = max(1000, int(max_a / 5 // 1000 * 1000) or 1000)
    ga = 0
    while ga <= max_a:
        dr.line([(_MARGIN_L, Y(ga)), (_W - _MARGIN_R, Y(ga))], fill=_GRID)
        dr.text((8, Y(ga) - 7), f"{int(ga)} m", fill=_INK, font=fs)
        ga += astep

    palette = [(185, 28, 28), (30, 90, 180), (20, 130, 70),
               (180, 120, 20), (120, 60, 160)]
    ly = _MARGIN_T + 4
    # The envelope's shape in the (ground range, altitude) plane
    # follows the method of propulsion — never a rectangle:
    # ballistic = the parabola of safety h = (R/2)(1-(x/R)^2) (peaks
    # overhead, returns to the deck at max range); powered missile
    # with a stated ceiling = flat-sided barrel with a superellipse
    # shoulder (the motor holds range up to the ceiling); cruise /
    # loiter = deck-hugging band; unpowered / unstated = the slant
    # dome x^2 + h^2 <= R^2 capped by ceiling and floored at the
    # stated minimum altitude.
    for i, c in enumerate(candidates):
        r = c.get("range_m") or 0
        if r <= 0:
            continue
        traj = (c.get("trajectory") or "").lower()
        floor_a = c.get("min_altitude_m") or 0
        stated_ceil = c.get("max_altitude_m") or 0
        col = palette[i % len(palette)]
        width = 3 if c.get("is_default") else 1
        pts = []
        steps = 48
        if traj == "ballistic":
            # Parabola of safety, deck to deck.
            for j in range(steps + 1):
                x = r * j / steps
                h = (r / 2.0) * (1.0 - (x / r) ** 2)
                pts.append((X(x), Y(min(h, max_a))))
        elif traj in ("cruise", "loiter"):
            ceil_a = min(stated_ceil or 0.02 * r, max_a, r)
            pts.append((X(0), Y(ceil_a)))
            pts.append((X(r), Y(ceil_a)))
            pts.append((X(r), Y(floor_a)))
            pts.append((X(0), Y(floor_a)))
        elif stated_ceil:
            # Powered barrel: r(h) = R * (1 - (h/ceiling)^4)^(1/4).
            ceil_a = min(stated_ceil, max_a, r)
            pts.append((X(0), Y(ceil_a)))
            for j in range(steps + 1):
                h = ceil_a + (floor_a - ceil_a) * j / steps
                x = r * (max(1.0 - (h / ceil_a) ** 4, 0.0)) ** 0.25
                pts.append((X(x), Y(h)))
            pts.append((X(0), Y(floor_a)))
        else:
            ceil_a = min(max_a, r)
            # Along the ceiling from x=0 to the dome intersection,
            # then down the slant arc to the floor.
            x_at_ceil = math.sqrt(max(r * r - ceil_a * ceil_a, 0.0))
            pts.append((X(0), Y(ceil_a)))
            pts.append((X(x_at_ceil), Y(ceil_a)))
            for j in range(1, steps + 1):
                h = ceil_a + (floor_a - ceil_a) * j / steps
                x = math.sqrt(max(r * r - h * h, 0.0))
                pts.append((X(x), Y(h)))
            pts.append((X(0), Y(floor_a)))
        dr.line(pts, fill=col, width=width, joint="curve")
        tag = (c.get("label") or "envelope")
        if c.get("condition"):
            tag += f" [{c['condition']}]"
        if c.get("trajectory"):
            tag += f" ({c['trajectory']})"
        if c.get("is_default"):
            tag += "  *default"
        dr.text((_W - _MARGIN_R - 420, ly), tag[:60], fill=col, font=fs)
        ly += 16

    if max_elevation_deg and 5.0 < max_elevation_deg < 90.0:
        # Elevation stop: reachable only under h = x*tan(theta_max).
        t = math.tan(math.radians(max_elevation_deg))
        x_end = min(max_r, max_a / t if t > 0 else max_r)
        dr.line([(X(0), Y(0)), (X(x_end), Y(min(x_end * t, max_a)))],
                fill=(90, 90, 90), width=2)
        dr.text((X(x_end * 0.45) + 6, Y(x_end * 0.45 * t) - 16),
                f"max elevation {max_elevation_deg:g} deg — overhead "
                "dead zone left of this line", fill=(90, 90, 90),
                font=fs)
    dr.text((_MARGIN_L, 8), f"ENVELOPE  {name}", fill=_INK, font=f)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
