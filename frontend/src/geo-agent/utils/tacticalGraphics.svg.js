/**
 * Tactical-graphics SVG drawers (FM 1-02.2 / MIL-STD 2525E).
 *
 * Reused by every product that paints doctrinal point glyphs + labels —
 * MCOO, SITEMP, Threat Overlay, GRINTSUM, TMP, Threat COA Statement.
 * (Originally ported from the per-feature SVG paint helpers in
 * geo-agent/backend/app/static/render.html ~2154-3823.) Framework-agnostic
 * so both the editor and the React headless renderer drive the same code.
 *
 * Font-size policy (ATP 2-01.3 + FM 1-02.2 marginalia requirement):
 * doctrinal label sizes target 10-12 pt at ~178 DPI embed scale (DOCX
 * landscape map area ~10x5.5", PPTX 16:9 slide). CSS px ≈ pt × (178/72),
 * so a 22 px CSS label prints ~11 pt. Major labels (AA designations) sit
 * at 24-26 px (~13 pt); generic labels (PL/OBJ/NAI/TAI/EA) at 20-22 px
 * (~11 pt); secondary sub-labels at 16-18 px (~9 pt). The internal `graphics*`
 * stash key names are legacy wire format — kept stable to avoid breaking
 * tacticalLayers.maplibre.js's stash contract.
 *
 * Every drawer accepts `(map, svg, feature, registry, options)` where:
 *   - map      : MapLibre instance (for map.project lng/lat → px).
 *   - svg      : SVG element to append child nodes into.
 *   - feature  : GeoJSON Feature.
 *   - registry : LabelPlacementRegistry instance (collision-avoiding label
 *                placement). Each drawer that paints a label calls
 *                registry.findBest + registry.add.
 *   - options  : Optional { productType } for product-aware drawers.
 *
 * Functions covered:
 *   - drawAvenueChevron               (avenue of approach hollow chevron)
 *   - drawMobilityCorridor        (single/double thin arrow)
 *   - drawKeyTerrain              (purple K-in-circle)
 *   - drawChokePoint              (black X glyph)
 *   - drawObstaclePoint           (subkind-keyed obstacle glyphs)
 *   - drawDirectionOfAttack       (red filled arrow)
 *   - drawStrongPoint             (blue S-in-circle)
 *   - drawDecisionPoint           (DP diamond)
 *   - drawAirCorridor             (paired blue rails)
 *   - drawFscmLabel               (CFL/FSCL/RFL/NFA midpoint label)
 *   - drawBoundaryLabel           (FLOT/FEBA/LD/LOA label)
 *   - drawBattlePositionLabel     (BP label, side-keyed)
 *   - drawAssemblyAreaLabel       (AA label)
 *   - drawRozLabel                (ROZ/NFA label)
 *   - drawPointNaiBox             (NAI/TAI doctrinal point square)
 *   - drawPointObjKidney          (OBJ doctrinal point kidney)
 *   - drawPointEaHex              (EA doctrinal point hex)
 *   - drawPhaseLineLabel          (PL label, one-per-line)
 *   - drawControlMeasureLabel     (NAI/TAI/EA/OBJ adjacent text label)
 *   - drawUrbanLabel              (city-name centroid label)
 *   - drawEntityLabel             (mil-unit designation under icon)
 *   - drawClusterFrame            (per-affiliation cluster frame + ×N)
 *   - clusterMilUnits             (greedy single-zoom clustering)
 */

import { estimateTextBBox } from './labelPlacement'
import { createMilSymbol } from './symbols'

const SVG_NS = 'http://www.w3.org/2000/svg'

// Cluster knobs — match render.html constants exactly.
export const CLUSTER_RADIUS_PX = 150
export const CLUSTER_MIN_POINTS = 2

// ---- Doctrinal affiliation colors (FM 1-02.2 Ch. 2 / MIL-STD-2525E) ----
// Single source of truth for affiliation-coded line / fill colors across
// every doctrinal-graphic drawer. Earlier painter code inlined ad-hoc
// hex (#7f1d1d / #1e3a8a / #b91c1c / #1e40af) which drifted from the
// FM 1-02.2 palette and produced visible per-product color inconsistency.
// `resolveAffiliationColor(feature)` reads feature.properties.side /
// .affiliation and returns the doctrinal hex; default = neutral black.
export const AFFILIATION_COLORS = Object.freeze({
  friendly: '#0064c8',  // FM 1-02.2 Ch. 2 friendly blue
  hostile:  '#dc323c',  // FM 1-02.2 Ch. 2 hostile red
  neutral:  '#000000',  // FM 1-02.2 Ch. 2 neutral black
  unknown:  '#ffeb3b',  // FM 1-02.2 Ch. 2 unknown yellow
})

export function resolveAffiliationColor(feature) {
  const raw = String(
    (feature && feature.properties
      && (feature.properties.side || feature.properties.affiliation)) || '',
  ).toLowerCase()
  if (raw === 'friendly' || raw === 'blue' || raw === 'friend' || raw === 'blufor') {
    return AFFILIATION_COLORS.friendly
  }
  if (raw === 'threat' || raw === 'hostile' || raw === 'red' || raw === 'enemy' || raw === 'opfor') {
    return AFFILIATION_COLORS.hostile
  }
  if (raw === 'unknown' || raw === 'unk' || raw === 'pending') {
    return AFFILIATION_COLORS.unknown
  }
  return AFFILIATION_COLORS.neutral
}

// ---- SIDC parsing helpers (matches render.html) ----
const SIDC_AFFILIATION_REVERSE = {
  '3': 'Friend',
  '6': 'Hostile',
  '4': 'Neutral',
  '1': 'Unknown',
}
const SIDC_DOMAIN_MAP = {
  '10': 'land',
  '15': 'land',
  '30': 'sea',
  '35': 'sea',
  '01': 'air',
  '05': 'air',
}
function affiliationFromSidc(sidc) {
  if (!sidc || sidc.length < 4) return 'Unknown'
  return SIDC_AFFILIATION_REVERSE[sidc[3]] || 'Unknown'
}
function domainFromSidc(sidc) {
  if (!sidc || sidc.length < 6) return 'land'
  return SIDC_DOMAIN_MAP[sidc.substring(4, 6)] || 'land'
}

// ---- Catmull-Rom helpers (matches render.html ~2471-2570) ----

/**
 * Densely sample a centripetal-style Catmull-Rom spline through a
 * polyline of {x,y} points. Returns samples with unit tangent, perp,
 * and a normalized arclength t in [0,1].
 */
export function catmullRomSample(pts, samplesPerSegment, tension) {
  if (!pts || pts.length < 2) return []
  if (pts.length === 2) {
    const a = pts[0]
    const b = pts[1]
    const dx = b.x - a.x
    const dy = b.y - a.y
    const L = Math.hypot(dx, dy) || 1
    const tx = dx / L
    const ty = dy / L
    const nx = -ty
    const ny = tx
    const N = Math.max(8, samplesPerSegment)
    const out = []
    for (let i = 0; i <= N; i++) {
      const u = i / N
      out.push({ x: a.x + dx * u, y: a.y + dy * u, tx, ty, nx, ny, t: u })
    }
    return out
  }
  const ext = pts.slice()
  const p0 = pts[0]
  const p1 = pts[1]
  ext.unshift({ x: 2 * p0.x - p1.x, y: 2 * p0.y - p1.y })
  const pN = pts[pts.length - 1]
  const pNm1 = pts[pts.length - 2]
  ext.push({ x: 2 * pN.x - pNm1.x, y: 2 * pN.y - pNm1.y })

  const tau = tension
  const samples = []
  for (let seg = 1; seg < ext.length - 2; seg++) {
    const P0 = ext[seg - 1]
    const P1 = ext[seg]
    const P2 = ext[seg + 1]
    const P3 = ext[seg + 2]
    const N = samplesPerSegment
    const isLastSeg = seg === ext.length - 3
    const jMax = isLastSeg ? N : N - 1
    for (let j = 0; j <= jMax; j++) {
      const u = j / N
      const u2 = u * u
      const u3 = u2 * u
      const c0 = -tau * u3 + 2 * tau * u2 - tau * u
      const c1 = (2 - tau) * u3 + (tau - 3) * u2 + 1
      const c2 = (tau - 2) * u3 + (3 - 2 * tau) * u2 + tau * u
      const c3 = tau * u3 - tau * u2
      const x = c0 * P0.x + c1 * P1.x + c2 * P2.x + c3 * P3.x
      const y = c0 * P0.y + c1 * P1.y + c2 * P2.y + c3 * P3.y
      const d0 = -3 * tau * u2 + 4 * tau * u - tau
      const d1 = 3 * (2 - tau) * u2 + 2 * (tau - 3) * u
      const d2 = 3 * (tau - 2) * u2 + 2 * (3 - 2 * tau) * u + tau
      const d3 = 3 * tau * u2 - 2 * tau * u
      let tx = d0 * P0.x + d1 * P1.x + d2 * P2.x + d3 * P3.x
      let ty = d0 * P0.y + d1 * P1.y + d2 * P2.y + d3 * P3.y
      const tlen = Math.hypot(tx, ty) || 1
      tx /= tlen
      ty /= tlen
      samples.push({ x, y, tx, ty, nx: -ty, ny: tx, t: 0 })
    }
  }
  let total = 0
  const cum = [0]
  for (let i = 1; i < samples.length; i++) {
    total += Math.hypot(
      samples[i].x - samples[i - 1].x,
      samples[i].y - samples[i - 1].y,
    )
    cum.push(total)
  }
  if (total > 0) {
    for (let i = 0; i < samples.length; i++) samples[i].t = cum[i] / total
  }
  return samples
}

/**
 * Analyst-selectable geometry smoothing (feature property `smoothing`
 * === 'bezier', set from the overlay edit panel): densify a LineString
 * or Polygon through the SAME centripetal Catmull-Rom sampler the
 * axis-of-advance drawer uses, so a smoothed control measure and a
 * smoothed axis read identically. Runs in coordinate space (lon/lat)
 * BEFORE the features reach the MapLibre sources and SVG drawers, so
 * every paint path sees one geometry. Polygon rings sample CLOSED
 * (cyclic anchors across the seam). Returns a NEW geometry, or the
 * input untouched when there is nothing to smooth.
 */
export function smoothGeometryCoords(geometry, samplesPerSegment = 10) {
  if (!geometry || !geometry.coordinates) return geometry
  const openLine = (coords) => {
    if (!Array.isArray(coords) || coords.length < 3) return coords
    const pts = coords.map(([x, y]) => ({ x, y }))
    const sampled = catmullRomSample(pts, samplesPerSegment, 0.5)
    return sampled.length >= 2 ? sampled.map(p => [p.x, p.y]) : coords
  }
  const closedRing = (ring) => {
    if (!Array.isArray(ring) || ring.length < 4) return ring
    // GeoJSON rings repeat the first vertex last — drop the repeat,
    // extend cyclically so the spline is smooth across the seam, then
    // trim the extension back off and re-close.
    const base = ring.slice(0, -1)
    if (base.length < 3) return ring
    const ext = [base[base.length - 1], ...base, base[0], base[1]]
    const pts = ext.map(([x, y]) => ({ x, y }))
    const sampled = catmullRomSample(pts, samplesPerSegment, 0.5)
    if (sampled.length < 4) return ring
    // Trim one segment's worth of samples from each end (the cyclic
    // padding), then close.
    const per = Math.max(1, Math.round(sampled.length / (ext.length - 1)))
    const core = sampled.slice(per, sampled.length - per)
    if (core.length < 3) return ring
    const out = core.map(p => [p.x, p.y])
    out.push(out[0])
    return out
  }
  if (geometry.type === 'LineString') {
    return { type: 'LineString', coordinates: openLine(geometry.coordinates) }
  }
  if (geometry.type === 'MultiLineString') {
    return { type: 'MultiLineString',
             coordinates: geometry.coordinates.map(openLine) }
  }
  if (geometry.type === 'Polygon') {
    return { type: 'Polygon', coordinates: geometry.coordinates.map(closedRing) }
  }
  if (geometry.type === 'MultiPolygon') {
    return { type: 'MultiPolygon',
             coordinates: geometry.coordinates.map(rings => rings.map(closedRing)) }
  }
  return geometry
}

/**
 * Convert a list of {x,y} samples into a smooth cubic-bezier "M ... C ..."
 * path. Tension factor 1/6 reproduces canonical Catmull-Rom.
 */
export function catmullRomToBezierPath(pts) {
  if (!pts || pts.length === 0) return ''
  if (pts.length === 1) {
    return 'M ' + pts[0].x.toFixed(1) + ',' + pts[0].y.toFixed(1)
  }
  let d = 'M ' + pts[0].x.toFixed(1) + ',' + pts[0].y.toFixed(1)
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || pts[i + 1]
    const cp1x = p1.x + (p2.x - p0.x) / 6
    const cp1y = p1.y + (p2.y - p0.y) / 6
    const cp2x = p2.x - (p3.x - p1.x) / 6
    const cp2y = p2.y - (p3.y - p1.y) / 6
    d +=
      ' C ' + cp1x.toFixed(1) + ',' + cp1y.toFixed(1) +
      ' ' + cp2x.toFixed(1) + ',' + cp2y.toFixed(1) +
      ' ' + p2.x.toFixed(1) + ',' + p2.y.toFixed(1)
  }
  return d
}

// ---- Common helpers ----

function polyCentroid(geom) {
  if (!geom) return null
  let ring = null
  if (geom.type === 'Polygon') ring = geom.coordinates[0]
  else if (geom.type === 'MultiPolygon')
    ring = geom.coordinates[0] && geom.coordinates[0][0]
  if (!ring || ring.length < 3) return null
  let sx = 0
  let sy = 0
  let n = 0
  for (const [lng, lat] of ring) {
    sx += lng
    sy += lat
    n++
  }
  return [sx / n, sy / n]
}

function makeSvg(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag)
  for (const k in attrs) el.setAttribute(k, attrs[k])
  return el
}

/**
 * Render a haloed SVG text label at a screen point using the collision
 * registry's placement search. Matches render.html `_drawHaloedLabel`.
 *
 * @param {SVGElement} svg
 * @param {{x:number,y:number}} px
 * @param {string} lblText
 * @param {object} opts - { fontSize, dy, fill, registry }
 */
// Polygon-tolerant anchor coordinate for point-glyph drawers. Several
// overlay kinds carry AREA geometry in their geo-agent push but render
// as a single point glyph (red circle, K-in-circle, EA box, etc.) at
// the area's anchor. Per the SITEMP writer manifest in pytho-app
// intel_agent._WRITER_GEOMETRY_MANIFEST the threat_objective kind is
// emitted as Polygon (4-point AOI around the named place); the
// catalog still maps it to primitive=closed_glyph which dispatches to
// the Point-shaped drawer drawThreatObjective.
//
// When that Point-shaped drawer ran `map.project(feature.geometry.
// coordinates)` against a Polygon, the coordinates array
// `[[[lng,lat], ...]]` failed LngLatLike validation and threw. The
// throw propagated through paintTacticalGraphics's dispatch loop and
// halted ALL subsequent drawer calls — including every mil_unit at
// the tail of the paint-tier sort. Net symptom: per-product SITEMP
// PNGs rendered with EAs / NAIs / chevrons but ZERO unit icons, then
// snapped the icons in the moment the analyst panned the camera
// (a fresh repaint ran far enough this time because the polygons
// had been re-iterated under different timing).
//
// The fix: every point-glyph drawer reads its anchor through this
// helper instead of `feature.geometry.coordinates`. Point passes
// through unchanged; Polygon collapses to the outer-ring vertex
// average; MultiPolygon collapses to the first ring's average;
// LineString collapses to the midpoint. The vertex average is not
// a true geographic centroid but is visually indistinguishable from
// one at our 1:1M+ render scales for the 4 km-wide AO polygons.
function _pointAnchor(geom) {
  if (!geom || !geom.coordinates) return null
  if (geom.type === 'Point') return geom.coordinates
  if (geom.type === 'Polygon') {
    const ring = geom.coordinates[0]
    if (!Array.isArray(ring) || !ring.length) return null
    let sx = 0, sy = 0
    for (const c of ring) { sx += c[0]; sy += c[1] }
    return [sx / ring.length, sy / ring.length]
  }
  if (geom.type === 'MultiPolygon') {
    const ring = geom.coordinates[0] && geom.coordinates[0][0]
    if (!Array.isArray(ring) || !ring.length) return null
    let sx = 0, sy = 0
    for (const c of ring) { sx += c[0]; sy += c[1] }
    return [sx / ring.length, sy / ring.length]
  }
  if (geom.type === 'LineString') {
    const coords = geom.coordinates
    if (!Array.isArray(coords) || !coords.length) return null
    return coords[Math.floor(coords.length / 2)]
  }
  return null
}

export function drawHaloedLabel(svg, px, lblText, opts) {
  if (!lblText) return null
  const registry = opts && opts.registry
  if (!registry) return null
  // Per user feedback the old 20+ pt baseline (~11+ pt embed) was twice
  // as large as the labels on the FM 1-02.2 reference Army map and made
  // every render unreadable. New baseline 11 CSS px ≈ 6 pt at 178 DPI —
  // matches the small adjacent labels in the reference. Callers can
  // upsize via opts.fontSize for major place names (drawUrbanLabel).
  const fontSize = (opts && opts.fontSize) || 11
  const dy = (opts && opts.dy) || 0
  const candidates = [
    { x: px.x + 10, y: px.y + 4 + dy, anchor: 'start' },
    { x: px.x - 10, y: px.y + 4 + dy, anchor: 'end' },
    { x: px.x, y: px.y + 18 + dy, anchor: 'middle' },
    { x: px.x, y: px.y - 10 + dy, anchor: 'middle' },
    { x: px.x + 10, y: px.y + 18 + dy, anchor: 'start' },
    { x: px.x - 10, y: px.y - 10 + dy, anchor: 'end' },
  ]
  const best = registry.findBest(lblText, fontSize, candidates)
  registry.add(best.rect)
  const t = makeSvg('text', {
    x: best.x.toFixed(1),
    y: best.y.toFixed(1),
    'text-anchor': best.anchor,
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '600',
    'font-size': String(fontSize),
    fill: (opts && opts.fill) || '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.5',
    'stroke-linejoin': 'round',
  })
  t.textContent = lblText
  svg.appendChild(t)
  return best.rect
}

// ---- AA chevron ----

/**
 * Draw the doctrinal avenue-of-approach hollow chevron.
 */
// Paint a tactical-arrow designation label at the midpoint of the arrow
// body, rotated to follow the local tangent (right-reading). Stacks an
// optional amplifier prefix (FM 1-02.2 §5 tactical-mission task
// amplifier — 'ME' / 'CATK' / 'DEM' / 'FEINT') in smaller font ahead
// of the ID, then the ID (e.g. "AA1") large, then an optional
// description ("Valga corridor") smaller on the line below. All
// rotated together to stay aligned with the corridor.
//
// opts:
//   - fill: text fill color (defaults to '#000').
//   - amplifier: optional tactical-mission task amplifier string (e.g.
//     'ME', 'CATK', 'DEM', 'FEINT'). When present, rendered ahead of
//     the ID in smaller font per FM 1-02.2 §5.
function drawArrowPathLabel(svg, outline, lblText, registry, opts) {
  if (!outline || !outline.midSamples || outline.midSamples.length === 0) return
  const fillColor = (opts && opts.fill) || '#000'
  const amplifier = (opts && opts.amplifier) ? String(opts.amplifier).trim() : ''
  // Split "AA1 — description" into ID + description for stacked display.
  // Doctrine renders the AA ID large + bold; the descriptor is a
  // supporting subline.
  const str = String(lblText || '')
  let idText = str
  let descText = ''
  const m = str.match(/^([A-Za-z]+\d+)\s*[—\-:]\s*(.+)$/)
  if (m) {
    idText = m[1]
    descText = m[2]
  }
  const idFontSize = 16
  const descFontSize = 9
  const ampFontSize = 11
  // Midpoint of the densified samples (stashed by buildArrowOutline).
  const samples = outline.midSamples
  const midIdx = Math.floor(samples.length / 2)
  const mid = samples[midIdx]
  // Right-reading: flip rotation if tangent points west-ish.
  let angleDeg = Math.atan2(mid.ty, mid.tx) * 180 / Math.PI
  let flipped = false
  if (angleDeg > 90) { angleDeg -= 180; flipped = true }
  else if (angleDeg < -90) { angleDeg += 180; flipped = true }
  const xform = `rotate(${angleDeg.toFixed(1)} ${mid.x.toFixed(1)} ${mid.y.toFixed(1)})`
  // Amplifier line (FM 1-02.2 §5 tactical-mission task amplifier — 'ME',
  // 'CATK', 'DEM', 'FEINT'): rendered ABOVE the ID in a smaller font so
  // it reads as a doctrinal prefix without dominating the unit
  // designation.
  if (amplifier) {
    const ampDy = (descText ? -idFontSize * 0.35 : 0) - idFontSize * 0.85
    const ampEl = makeSvg('text', {
      x: mid.x.toFixed(1),
      y: (mid.y + ampDy).toFixed(1),
      'text-anchor': 'middle',
      'dominant-baseline': 'middle',
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '900',
      'font-size': String(ampFontSize),
      fill: fillColor,
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '3',
      'stroke-linejoin': 'round',
      transform: xform,
    })
    ampEl.textContent = amplifier
    svg.appendChild(ampEl)
  }
  // ID line: centered on midpoint, offset slightly above the centerline.
  const idDy = descText ? -idFontSize * 0.35 : 0
  const idEl = makeSvg('text', {
    x: mid.x.toFixed(1),
    y: (mid.y + idDy).toFixed(1),
    'text-anchor': 'middle',
    'dominant-baseline': 'middle',
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '900',
    'font-size': String(idFontSize),
    fill: fillColor,
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '4',
    'stroke-linejoin': 'round',
    transform: xform,
  })
  idEl.textContent = idText
  svg.appendChild(idEl)
  if (descText) {
    const descDy = idFontSize * 0.55
    const descEl = makeSvg('text', {
      x: mid.x.toFixed(1),
      y: (mid.y + descDy).toFixed(1),
      'text-anchor': 'middle',
      'dominant-baseline': 'middle',
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '600',
      'font-size': String(descFontSize),
      fill: fillColor,
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '2.5',
      'stroke-linejoin': 'round',
      transform: xform,
    })
    descEl.textContent = descText
    svg.appendChild(descEl)
  }
  if (registry) {
    const w = Math.max(idText.length, descText.length, amplifier.length) * idFontSize * 0.6
    const ampH = amplifier ? ampFontSize + 2 : 0
    registry.add({
      x: mid.x - w / 2,
      y: mid.y - idFontSize - ampH,
      w: w,
      h: idFontSize + ampH + (descText ? descFontSize + 4 : 0),
      _src: 'arrow-path-label',
    })
  }
}

// Shared arrow-corridor outline builder for drawAvenueChevron + drawAxisOfAdvance.
// Walks input waypoints (already projected to screen coords), then DENSIFIES
// via centripetal Catmull-Rom sampling so multi-bend axes (Cimza→Valga→Kopu,
// Smiltene→Rongu, etc.) get smooth rounded corners instead of the V-shaped
// kinks that came out of pure piecewise-linear offsets. Catmull-rom samples
// supply per-point tangent + normal already; we just offset ±halfW for the
// body chains and stitch on a triangular arrowhead at the tip. NOT the
// older bezier-from-control-points path (catmullRomToBezierPath) which
// produced wobble — this is sample-based offsetting with low tension (0.5)
// so the centerline is geometrically faithful but visually smooth.
//
// Returns { path, tip, headL, headR, lastSegment, halfW } where `path` is
// an SVG `d` string that closes the outline. `lastSegment` carries the
// tangent of the final segment so callers can place labels along it.
function buildArrowOutline(waypoints, widthPx) {
  if (!waypoints || waypoints.length < 2) return null
  const halfW = widthPx / 2

  // Decimate input waypoints to AT MOST 10 anchors before Catmull-Rom.
  // Terrain-snapped routes from the A* planner return 15-25 waypoints
  // with sub-km zig-zags around obstacles; Catmull-Rom interpolation
  // amplifies those into the snake-wobble the user called out. But
  // dropping to 6 anchors made the corridor look wedge-shaped because
  // adjacent normals could rotate too far between widely-spaced samples.
  // 10 anchors hits the sweet spot — gentle terrain-following curves
  // without high-freq jitter.
  let anchors = waypoints
  if (waypoints.length > 10) {
    const N = 10
    anchors = []
    for (let i = 0; i < N; i++) {
      const idx = Math.round(i * (waypoints.length - 1) / (N - 1))
      anchors.push(waypoints[idx])
    }
  }

  // Densify via Catmull-Rom over the simplified anchor set. 12 samples
  // per segment + tension 0.4 gives a gently-curved corridor through
  // the anchors without overshoot. 2-point straight axes short-circuit
  // to a clean linear path inside catmullRomSample.
  const samples = catmullRomSample(anchors, 12, 0.4)
  if (!samples || samples.length < 2) return null
  const M = samples.length

  // Standard tactical arrow geometry per FM 1-02.2: rectangular body
  // joined to a triangular head that flares OUTWARD perpendicular at
  // the body/head junction before tapering to the tip.
  //
  // Key invariant for visual symmetry: the BODY's last edge must be
  // COLINEAR with the HEAD's centerline axis so the body meets the
  // head's perpendicular shoulder at a clean 90°. Otherwise the chevron
  // looks "lopsided" --- one body edge sweeps into the shoulder at a
  // shallow angle, the other at a steep angle. We fix this by:
  //
  //   1. Compute the head axis as the CHORD from samples[bodyLast] to
  //      `last` (not the catmullRom tangent at the very last sample).
  //      `approachT` is the unit chord direction. Reproducible from
  //      two well-separated points so curve wobble at the endpoint
  //      doesn't perturb it.
  //   2. Replace samples[bodyLast+1 .. M-1] with linearly-interpolated
  //      points on this straight chord, with their normals set to
  //      approachN. The body's last region is now a straight corridor
  //      along approachT, edges offset by ±approachN*halfW.
  //   3. The head sits at the end of this straight chord: tip = last -
  //      approachT * tipPullback; baseExact = tip - approachT * headLen.
  //   4. Head shoulders at baseExact ± approachN * headOuter form an
  //      isoceles triangle (headL, tip, headR) around the chord axis.
  //
  // The body samples 0..bodyLast still follow the polyline curve (using
  // their own per-sample normals), so the chevron continues to track
  // terrain in the earlier segment. The transition at bodyLast is the
  // single kink in the geometry; choosing bodyLast as the sample where
  // the head zone starts (cum arc-length from end >= tipPullback + headLen)
  // keeps that kink small and pushed UPSTREAM from the visible head.
  const headLen = halfW * 2.4
  const headOuter = halfW * 1.55  // was 2.2 (top-heavy); 1.55 reads
                                  // doctrinally without dominating the body
  const tipPullback = halfW * 1.4

  // (1) Find bodyLast = last polyline sample BEFORE the head zone.
  const last = samples[M - 1]
  let bodyLast = 0
  let cum = 0
  for (let i = M - 1; i > 0; i--) {
    cum += Math.hypot(samples[i].x - samples[i-1].x, samples[i].y - samples[i-1].y)
    if (cum >= tipPullback + headLen) { bodyLast = Math.max(0, i - 1); break }
  }

  // (2) Head axis = chord from samples[bodyLast] to `last`.
  const _chordDx = last.x - samples[bodyLast].x
  const _chordDy = last.y - samples[bodyLast].y
  const _chordLen = Math.hypot(_chordDx, _chordDy) || 1
  const approachT = { tx: _chordDx / _chordLen, ty: _chordDy / _chordLen }
  const approachN = { nx: -approachT.ty, ny: approachT.tx }

  // (3) Replace samples[bodyLast .. M-1] with straight-line points
  // along the chord, with their tx/ty/nx/ny normalized to the chord
  // axis. The body's offset edges in this range will then be parallel
  // to approachT and meet baseExact's perpendicular cap at 90°.
  //
  // IMPORTANT: bodyLast itself is also overwritten (not just bodyLast+1
  // onward). Without that, the last walked body sample (samples[bodyLast])
  // still carries the per-sample polyline normal, the segment from
  // samples[bodyLast]±n*halfW to baseExact±approachN*halfW is tilted, and
  // that tilted segment BLEEDS into the head shoulder triangle (visible as
  // a stray line crossing the head outline on bendier corridors).
  for (let i = bodyLast; i <= M - 1; i++) {
    const u = (i - bodyLast) / (M - 1 - bodyLast)
    samples[i] = {
      x: samples[bodyLast].x + _chordDx * u,
      y: samples[bodyLast].y + _chordDy * u,
      tx: approachT.tx, ty: approachT.ty,
      nx: approachN.nx, ny: approachN.ny,
      t: samples[i].t,
    }
  }

  // (4) Tip + baseExact on the chord axis, head shoulders perpendicular.
  const tip = { x: last.x - approachT.tx * tipPullback, y: last.y - approachT.ty * tipPullback }
  const baseExact = { x: tip.x - approachT.tx * headLen, y: tip.y - approachT.ty * headLen }
  const headL = { x: baseExact.x + approachN.nx * headOuter, y: baseExact.y + approachN.ny * headOuter }
  const headR = { x: baseExact.x - approachN.nx * headOuter, y: baseExact.y - approachN.ny * headOuter }

  // Body chains: samples 0..bodyLast at their own halfW offsets (polyline-
  // following the terrain curve), then the perpendicular cap at baseExact.
  // Samples bodyLast+1..M-1 are NOT walked --- they exist only to keep the
  // chord-tangent computation honest. baseExact sits exactly headLen behind
  // the tip; if we kept walking past bodyLast we'd hit `last` (== samples
  // [M-1]) which is tipPullback + headLen FURTHER than baseExact, overshoot
  // the head shoulder, then jump backward to baseExact and produce a closed
  // polygon whose fill extends past the arrowhead.
  //
  // Self-intersection cleaning (AA3 / Grundzāle-Osula bug): when the
  // centerline curves tighter than `halfW` (e.g. terrain-planned routes
  // around wetlands), the INSIDE-bend offset polyline self-intersects ---
  // the offset point at sample i lands BEHIND the offset point at sample
  // i-1 (relative to the centerline direction), producing an X-crossing
  // in the rendered body lines.
  //
  // Classical fix from polygon-offset literature (Clipper2, CGAL):
  // after generating offsets, walk forward and drop any offset point
  // whose forward segment runs OPPOSITE to the centerline forward
  // direction. The check: dot product of (offset[i]-offset[i-1]) with
  // (centerline[i]-centerline[i-1]). Negative ⇒ reversal ⇒ drop.
  // OUTSIDE-bend offsets always have positive dot product (the outside
  // expands), so this only trims the pinched INSIDE side.
  const _rawLeft = []
  const _rawRight = []
  for (let i = 0; i <= bodyLast; i++) {
    const s = samples[i]
    _rawLeft.push({ x: s.x + s.nx * halfW, y: s.y + s.ny * halfW, cx: s.x, cy: s.y })
    _rawRight.push({ x: s.x - s.nx * halfW, y: s.y - s.ny * halfW, cx: s.x, cy: s.y })
  }
  const _cleanOffset = raw => {
    if (raw.length === 0) return []
    const out = [raw[0]]
    for (let i = 1; i < raw.length; i++) {
      const prev = out[out.length - 1]
      const cdx = raw[i].cx - prev.cx
      const cdy = raw[i].cy - prev.cy
      const odx = raw[i].x - prev.x
      const ody = raw[i].y - prev.y
      if (cdx * odx + cdy * ody < 0) continue  // reversed → inside-bend pinch
      out.push(raw[i])
    }
    return out
  }
  // Decimate the cleaned offset to ~12 points before smoothing.
  // Dense catmull-rom samples (12 per centerline segment) leave Q-segments
  // only 1-2 px long after smoothing --- quadratic-through-midpoints does
  // its job (tangent continuity at midpoints) but the rendered curve still
  // reads as a polyline because each Q is too short to show curvature.
  // Decimating to ~12 evenly-spaced points along arc-length gives each Q
  // segment 15-40 px of room to actually curve.
  const _decimate = (pts, N) => {
    if (pts.length <= N) return pts
    // Build cumulative arc length, then sample N points at equal arc-length.
    const cum = [0]
    for (let i = 1; i < pts.length; i++) {
      cum.push(cum[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y))
    }
    const total = cum[cum.length - 1]
    if (total === 0) return [pts[0], pts[pts.length - 1]]
    const out = []
    let j = 0
    for (let k = 0; k < N; k++) {
      const target = (k / (N - 1)) * total
      while (j < pts.length - 1 && cum[j + 1] < target) j++
      const segLen = cum[j + 1] - cum[j] || 1
      const u = (target - cum[j]) / segLen
      out.push({
        x: pts[j].x + (pts[j + 1].x - pts[j].x) * u,
        y: pts[j].y + (pts[j + 1].y - pts[j].y) * u,
      })
    }
    return out
  }
  const leftPts = _decimate(_cleanOffset(_rawLeft).map(p => ({ x: p.x, y: p.y })), 12)
  const rightPts = _decimate(_cleanOffset(_rawRight).map(p => ({ x: p.x, y: p.y })), 12)
  leftPts.push({ x: baseExact.x + approachN.nx * halfW, y: baseExact.y + approachN.ny * halfW })
  rightPts.push({ x: baseExact.x - approachN.nx * halfW, y: baseExact.y - approachN.ny * halfW })
  const toLine = pts => pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' L ')
  // Quadratic-through-midpoints smoothing. catmullRomToBezierPath on
  // already-dense samples produces individual C-segments so short their
  // curvature is invisible --- the rendered output reads as a polyline
  // even though it's technically a bezier. This algorithm instead places
  // a Q (quadratic) control point at EACH polyline vertex and routes
  // the visible path through the MIDPOINTS of adjacent edges. The
  // tangent at every midpoint is exactly the chord direction between
  // the two adjacent vertices, so the curve is C1-continuous everywhere
  // and shows NO visible corners regardless of sample density.
  //
  // Tradeoff: the curve no longer passes through interior vertices ---
  // it passes through midpoints. For terrain-following body offsets
  // this is acceptable and visually superior (the curve still tracks
  // the polyline path within halfW/2 of every vertex).
  //
  // bodyPathOpen returns "M x,y Q x,y x,y Q x,y x,y ..." suitable for
  // stroking. bodyPathContinue swaps the leading 'M' for 'L' so it
  // can be appended to an existing path (used for the closed-fill
  // polygon: left body forward → head triangle → right body reversed).
  const smoothPath = pts => {
    if (!pts || pts.length === 0) return ''
    if (pts.length === 1) return `M ${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`
    if (pts.length === 2)
      return `M ${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)} L ${pts[1].x.toFixed(1)},${pts[1].y.toFixed(1)}`
    let d = `M ${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i].x + pts[i + 1].x) / 2
      const my = (pts[i].y + pts[i + 1].y) / 2
      d += ` Q ${pts[i].x.toFixed(1)},${pts[i].y.toFixed(1)} ${mx.toFixed(1)},${my.toFixed(1)}`
    }
    const last = pts[pts.length - 1]
    d += ` L ${last.x.toFixed(1)},${last.y.toFixed(1)}`
    return d
  }
  const bodyPathOpen = pts => smoothPath(pts)
  const bodyPathContinue = pts => smoothPath(pts).replace(/^M /, 'L ')
  // Doctrinal AA per ATP 2-01.3 Fig 6-3: arrow is OPEN at the tail (no
  // closing edge) so two parallel body lines run independently from the
  // tail and join the arrowhead at the shoulder. We emit:
  //   - leftBody:  smooth bezier along the left edge from tail to shoulder
  //   - rightBody: smooth bezier along the right edge from tail to shoulder
  //   - head:      closed triangle (headL → tip → headR) at the front
  // The leftBody/rightBody are stroked (no fill); the head is stroked +
  // optionally lightly filled by the caller via `paint`.
  const leftBodyPath = bodyPathOpen(leftPts)
  const rightBodyPath = bodyPathOpen(rightPts)
  // Head includes the body→shoulder transition lines so the head reads
  // continuously with the body edges. headPath = leftPts[end] → headL →
  // tip → headR → rightPts[end].
  const headPath =
    'M ' + leftPts[leftPts.length - 1].x.toFixed(1) + ',' + leftPts[leftPts.length - 1].y.toFixed(1) +
    ' L ' + headL.x.toFixed(1) + ',' + headL.y.toFixed(1) +
    ' L ' + tip.x.toFixed(1) + ',' + tip.y.toFixed(1) +
    ' L ' + headR.x.toFixed(1) + ',' + headR.y.toFixed(1) +
    ' L ' + rightPts[rightPts.length - 1].x.toFixed(1) + ',' + rightPts[rightPts.length - 1].y.toFixed(1)

  return {
    // Legacy `path` (closed) kept for callers that still want a single
    // path with fill. Open-tail callers should use leftBodyPath /
    // rightBodyPath / headPath instead. Smooth-bezier edges so the
    // opacity-wash polygon matches the stroked body curves.
    path:
      bodyPathOpen(leftPts) +
      ' L ' + headL.x.toFixed(1) + ',' + headL.y.toFixed(1) +
      ' L ' + tip.x.toFixed(1) + ',' + tip.y.toFixed(1) +
      ' L ' + headR.x.toFixed(1) + ',' + headR.y.toFixed(1) +
      ' ' + bodyPathContinue(rightPts.slice().reverse()) +
      ' Z',
    leftBodyPath,
    rightBodyPath,
    headPath,
    tip,
    headL,
    headR,
    halfW,
    tangentAtTip: approachT,
    normalAtTip: approachN,
    midSamples: samples,
  }
}


/**
 * Draw the doctrinal avenue-of-approach (AA) hollow chevron.
 *
 * Per FM 1-02.2: AA is a NEUTRAL terrain-analysis symbol — hollow chevron
 * with thin black outline. Affiliation does not apply (it's a terrain
 * feature describing where any force could maneuver). For SITEMP /
 * Threat Overlay the AA layer is gated off by the caller (drawn only
 * on MCOO/CONOP).
 */
export function drawAvenueChevron(map, svg, feature, registry, opts) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  // Compact AA label gate: schema-driven via the active product's
  // `map_compact_aa_labels` primitive (stashed as map.__renderConfig
  // .compactAaLabels by HeadlessRenderConfigStash from the URL param
  // forwarded by intel_agent.tool_render_map). Editor mode
  // (renderConfig=null) defaults to the non-compact label form.
  // opts.productType is kept as an opaque tag for downstream draw
  // helpers; no decision logic switches on it here.
  const productType = (opts && opts.productType) || ''
  const isSitempLike = map?.__renderConfig?.compactAaLabels === true

  const sizeStr = String(
    feature.properties.size || feature.properties.width_class
      || feature.properties.echelon || 'bde',
  ).toLowerCase()
  // Echelon → corridor width (km). Cut from prior 30/13/7 doctrine-of-
  // analyst-convention values because at SITEMP zoom those rendered as
  // unreadable blobs that drowned the underlying units. Fig 6-3's AAs
  // are visibly narrower than the EAs/OBJs they connect — the chevron's
  // job is to show DIRECTION, not occupy the corridor's full geometric
  // width. New tiers: DIV=12 / BDE=6 / BN=3.5 / CO=2 / PLT=1.5 km.
  // `cavalry` / `cav` / `regiment` are unit TYPES, not echelons — but
  // when they appear in the echelon field they should map to a sensible
  // size tier. Cav doing a screen is brigade-equivalent (6 km).
  // Regiment ≈ brigade. Squadron ≈ battalion. Troop ≈ company.
  const widthKm = sizeStr.includes('div')
    ? 12
    : sizeStr.includes('bde') || sizeStr.includes('brigade')
        || sizeStr.includes('cav') || sizeStr.includes('regt') || sizeStr.includes('regiment')
      ? 6
      : sizeStr.includes('bn') || sizeStr.includes('battalion') || sizeStr.includes('squadron')
        ? 3.5
        : sizeStr.includes('co') || sizeStr.includes('company') || sizeStr.includes('troop')
          ? 2.0
          : 1.5

  // Doctrinal avenue of approach per ATP 2-01.3 Fig 4-6 / Fig 4-9:
  // side-keyed color via the shared AFFILIATION_COLORS palette
  // (FM 1-02.2 Ch. 2). Earlier code inlined ad-hoc hex literals that
  // drifted from the doctrinal palette; the shared resolver eliminates
  // drift across the painter.
  const outlineColor = resolveAffiliationColor(feature)

  // Doctrinal hollow chevron per FM 1-02.2 / ATP 2-01.3 Fig 4-13/4-14:
  // open-tail arrow shape with side-keyed outline. The chevron IS the
  // avenue envelope (the "Mobility Corridors -> Group into AA" hollow
  // arrow in the analyst-drawn doctrinal examples — the chevron's
  // width encloses the constituent mobility corridors that paint as
  // separate `>-||-<` features inside it).
  //
  // The chevron's CENTERLINE polyline is feature.geometry.coordinates,
  // which for synthesized avenues is the simplified central-axis route
  // from origin KT to objective KT (intel_agent's
  // _synthesize_mcoo_via_terrain_circuit stamps it). For legacy
  // scenario-pushed avenues it's the planner-routed polyline from
  // _push_scenario_terrain_to_geo_agent.
  const waypoints = coords.map(c => {
    const p = map.project(c)
    return { x: p.x, y: p.y, lng: c[0], lat: c[1] }
  })
  const meanLat = (waypoints[0].lat + waypoints[waypoints.length - 1].lat) / 2
  const dLatPerKm = 1 / 110.574
  const dLngPerKm = 1 / (111.32 * Math.cos((meanLat * Math.PI) / 180))
  const probeNorth = map.project([waypoints[0].lng, waypoints[0].lat + dLatPerKm])
  const probeEast = map.project([waypoints[0].lng + dLngPerKm, waypoints[0].lat])
  const pxPerKm = Math.hypot(
    probeEast.x - waypoints[0].x, probeNorth.y - waypoints[0].y,
  ) / Math.SQRT2
  const minPx = isSitempLike ? 14 : 75
  const maxPx = isSitempLike ? 50 : 280
  const widthPx = Math.max(minPx, Math.min(widthKm * pxPerKm, maxPx))
  const outline = buildArrowOutline(waypoints, widthPx)
  if (!outline) return

  // Hollow outline only per ATP 2-01.3 Fig 4-13/4-14 — AAs do NOT
  // carry an interior fill. The prior translucent white fill obscured
  // the terrain beneath and competed with the per-COA axis_of_advance
  // arrows the SITEMP overlays on top of the same polyline.
  for (const d of [outline.leftBodyPath, outline.rightBodyPath, outline.headPath]) {
    svg.appendChild(
      makeSvg('path', {
        d,
        fill: 'none',
        stroke: outlineColor,
        'stroke-width': '2.4',
        'stroke-linejoin': 'round',
        'stroke-linecap': 'round',
      }),
    )
  }
  // Designation label ALONG the arrow path. Per ATP 2-01.3 Fig 4-6 the
  // alphanumeric identifier (e.g. AA1, AA2, AA3) runs along the corridor
  // body at its midpoint, color-matched to the arrow outline.
  if (!registry) return
  // Never fall back to properties.id — DB-backed features carry a raw
  // uuid there, and a uuid is system internals painted onto the map.
  // No label beats a wrong label.
  const lblText =
    feature.properties.designation || feature.properties.name || ''
  if (lblText) {
    drawArrowPathLabel(svg, outline, lblText, registry, { fill: outlineColor })
  }
}


// ---- Mobility corridor ----

// Doctrinal mobility-corridor symbol per FM 1-02.2 Table 4-4 / ATP 2-01.3
// ¶4-24. NOT a 2525E predrawn glyph — the hand-rolled painter is the right
// path (overlay constants set sidc: None, source_doctrine: ATP_2_01_3).
//
// Visual: `>-||-<`
//   - Centerline polyline traces the corridor's geographic extent
//   - Each end: outward-pointing chevron (apex outside the corridor,
//     legs opening BACK toward the centerline at ±45°)
//   - Midpoint: echelon hash marks PERPENDICULAR to local tangent
//
// Echelon hash-mark count per corridor class (per handoff spec):
//   company    → 1 perpendicular bar
//   battalion  → 2 parallel bars
//   brigade    → 3 parallel bars
//   division   → X (two crossing bars at ±45° to perpendicular axis)
//
// Class comes from feature.properties.class (set by corridor_discovery in
// geo-agent), with fallback to width_class / size.
export function drawMobilityCorridor(map, svg, feature) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return

  const classRaw = String(
    feature.properties.class
      || feature.properties.width_class
      || feature.properties.size
      || 'battalion',
  ).toLowerCase()
  let echelon
  if (classRaw.includes('div')) echelon = 'division'
  else if (classRaw.includes('bde') || classRaw.includes('brig')) echelon = 'brigade'
  else if (classRaw.includes('regt') || classRaw.includes('regi')) echelon = 'brigade'
  else if (classRaw.includes('bn') || classRaw.includes('batt')) echelon = 'battalion'
  else if (classRaw.includes('co') || classRaw.includes('comp')) echelon = 'company'
  else if (classRaw.includes('sub')) echelon = 'company'
  else echelon = 'battalion'

  const screen = coords.map(c => {
    const p = map.project(c)
    return { x: p.x, y: p.y }
  })
  const samples = catmullRomSample(screen, 14, 0.5)
  if (!samples || samples.length < 2) return

  // 1. Centerline as a single smooth stroked path (the `-` parts of `>-||-<`).
  svg.appendChild(
    makeSvg('path', {
      d: catmullRomToBezierPath(samples),
      fill: 'none',
      stroke: '#000',
      'stroke-width': '1.8',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  )

  // 2. Outward-pointing chevrons at each end.
  //
  // signedOutward = -1 at start (apex points opposite tangent, i.e. AWAY
  // from the corridor interior). signedOutward = +1 at end (apex points
  // along tangent, also AWAY from the corridor interior).
  const drawEndChevron = (sample, signedOutward) => {
    const dx = sample.tx * signedOutward
    const dy = sample.ty * signedOutward
    const apexOffset = 6.5
    const legLen = 10
    const vx = sample.x + dx * apexOffset
    const vy = sample.y + dy * apexOffset
    const c45 = Math.SQRT1_2
    const e1x = vx + legLen * (-dx * c45 + sample.nx * c45)
    const e1y = vy + legLen * (-dy * c45 + sample.ny * c45)
    const e2x = vx + legLen * (-dx * c45 - sample.nx * c45)
    const e2y = vy + legLen * (-dy * c45 - sample.ny * c45)
    svg.appendChild(
      makeSvg('path', {
        d: `M ${e1x.toFixed(1)},${e1y.toFixed(1)} L ${vx.toFixed(1)},${vy.toFixed(1)} L ${e2x.toFixed(1)},${e2y.toFixed(1)}`,
        fill: 'none',
        stroke: '#000',
        'stroke-width': '2.4',
        'stroke-linecap': 'round',
        'stroke-linejoin': 'round',
      }),
    )
  }
  drawEndChevron(samples[0], -1)
  drawEndChevron(samples[samples.length - 1], +1)

  // 3. Echelon hash marks at the centerline midpoint, perpendicular to
  // local tangent. White halo behind each mark so they read cleanly over
  // the centerline stroke.
  const midIdx = Math.floor(samples.length / 2)
  const mid = samples[midIdx]
  const hashHalfLen = 8
  const hashSpacing = 5

  const drawPerpBar = (offsetAlongTangent) => {
    const cx = mid.x + mid.tx * offsetAlongTangent
    const cy = mid.y + mid.ty * offsetAlongTangent
    const x1 = cx + mid.nx * hashHalfLen
    const y1 = cy + mid.ny * hashHalfLen
    const x2 = cx - mid.nx * hashHalfLen
    const y2 = cy - mid.ny * hashHalfLen
    // Halo first (wider white stroke under the black bar).
    svg.appendChild(
      makeSvg('line', {
        x1: x1.toFixed(1), y1: y1.toFixed(1),
        x2: x2.toFixed(1), y2: y2.toFixed(1),
        stroke: '#fff',
        'stroke-width': '4.5',
        'stroke-linecap': 'round',
      }),
    )
    svg.appendChild(
      makeSvg('line', {
        x1: x1.toFixed(1), y1: y1.toFixed(1),
        x2: x2.toFixed(1), y2: y2.toFixed(1),
        stroke: '#000',
        'stroke-width': '2.4',
        'stroke-linecap': 'round',
      }),
    )
  }

  const drawDiagonalBar = (signRotate) => {
    // Bar rotated ±45° from the perpendicular axis (produces an X when
    // called once with +1 and once with -1).
    const c45 = Math.SQRT1_2
    const ux = mid.nx * c45 + signRotate * mid.tx * c45
    const uy = mid.ny * c45 + signRotate * mid.ty * c45
    const x1 = mid.x + ux * hashHalfLen
    const y1 = mid.y + uy * hashHalfLen
    const x2 = mid.x - ux * hashHalfLen
    const y2 = mid.y - uy * hashHalfLen
    svg.appendChild(
      makeSvg('line', {
        x1: x1.toFixed(1), y1: y1.toFixed(1),
        x2: x2.toFixed(1), y2: y2.toFixed(1),
        stroke: '#fff',
        'stroke-width': '4.5',
        'stroke-linecap': 'round',
      }),
    )
    svg.appendChild(
      makeSvg('line', {
        x1: x1.toFixed(1), y1: y1.toFixed(1),
        x2: x2.toFixed(1), y2: y2.toFixed(1),
        stroke: '#000',
        'stroke-width': '2.4',
        'stroke-linecap': 'round',
      }),
    )
  }

  if (echelon === 'company') {
    drawPerpBar(0)
  } else if (echelon === 'battalion') {
    drawPerpBar(-hashSpacing / 2)
    drawPerpBar(+hashSpacing / 2)
  } else if (echelon === 'brigade') {
    drawPerpBar(-hashSpacing)
    drawPerpBar(0)
    drawPerpBar(+hashSpacing)
  } else if (echelon === 'division') {
    drawDiagonalBar(+1)
    drawDiagonalBar(-1)
  }

  // 4. Designation label, offset perpendicular to the centerline so it
  // doesn't overlap the hash marks. For corridors whose perpendicular
  // axis is mostly HORIZONTAL (i.e., the corridor itself runs mostly
  // north-south, so mid.nx dominates), the label would otherwise share
  // the midpoint's Y coord and intrude into the hash-mark region — flip
  // text-anchor to 'start' or 'end' so the text extends AWAY from the
  // centerline instead of straddling it.
  const lblText = (
    feature.properties.designation ||
    feature.properties.name ||
    ''
  ).replace(/^MC\s*/i, '')
  if (lblText) {
    const lblOffsetPerp = 22
    const lx = mid.x - mid.nx * lblOffsetPerp
    const ly = mid.y - mid.ny * lblOffsetPerp
    let anchor = 'middle'
    if (Math.abs(mid.nx) > Math.abs(mid.ny) * 1.5) {
      // Perpendicular axis is mostly horizontal: label sits to one side
      // of the corridor on the SAME screen Y as the hash marks. Pick
      // the anchor edge that keeps the text from extending back across
      // the centerline.
      anchor = mid.nx > 0 ? 'end' : 'start'
    }
    const txt = makeSvg('text', {
      x: lx.toFixed(1),
      y: ly.toFixed(1),
      'text-anchor': anchor,
      'dominant-baseline': 'middle',
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '700',
      'font-size': '12',
      fill: '#000',
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '2.5',
      'stroke-linejoin': 'round',
    })
    txt.textContent = 'MC ' + lblText
    svg.appendChild(txt)
  }
}

// ---- Key terrain (purple K-circle) ----

export function drawKeyTerrain(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)

  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: '13',
      fill: '#fff',
      stroke: 'none',
    }),
  )
  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: '11',
      fill: '#fff',
      stroke: '#7c3aed',
      'stroke-width': '2.2',
    }),
  )
  const k = makeSvg('text', {
    x: px.x.toFixed(1),
    y: (px.y + 4).toFixed(1),
    'text-anchor': 'middle',
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '900',
    'font-size': '13',
    fill: '#7c3aed',
  })
  k.textContent = 'K'
  svg.appendChild(k)

  const lblText = feature.properties.name || ''
  if (lblText && registry) {
    // Match the reference-image label tier (was 20pt, now 11pt).
    const fontSize = 11
    const candidates = [
      { x: px.x + 16, y: px.y + 4, anchor: 'start' },
      { x: px.x - 16, y: px.y + 4, anchor: 'end' },
      { x: px.x, y: px.y + 26, anchor: 'middle' },
      { x: px.x, y: px.y - 18, anchor: 'middle' },
      { x: px.x + 16, y: px.y + 26, anchor: 'start' },
      { x: px.x - 16, y: px.y + 26, anchor: 'end' },
      { x: px.x + 16, y: px.y - 18, anchor: 'start' },
      { x: px.x - 16, y: px.y - 18, anchor: 'end' },
    ]
    const best = registry.findBest(lblText, fontSize, candidates)
    registry.add(best.rect)
    const t = makeSvg('text', {
      x: best.x.toFixed(1),
      y: best.y.toFixed(1),
      'text-anchor': best.anchor,
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '600',
      'font-size': String(fontSize),
      fill: '#000',
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '2.5',
      'stroke-linejoin': 'round',
    })
    t.textContent = lblText
    svg.appendChild(t)
  }
}

// ---- Choke point ----

export function drawChokePoint(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  const r = 8

  svg.appendChild(
    makeSvg('rect', {
      x: (px.x - 11).toFixed(1),
      y: (px.y - 11).toFixed(1),
      width: '22',
      height: '22',
      rx: '3',
      fill: '#fff',
      opacity: '0.92',
    }),
  )
  svg.appendChild(
    makeSvg('path', {
      d:
        `M ${px.x - r} ${px.y - r} L ${px.x + r} ${px.y + r} ` +
        `M ${px.x + r} ${px.y - r} L ${px.x - r} ${px.y + r}`,
      stroke: '#000',
      'stroke-width': '2.6',
      'stroke-linecap': 'round',
    }),
  )

  if (!registry) return
  const cpLbl = 'CP ' + (feature.properties.name || '')
  // Matches reference-image label tier (was 20pt, now 11pt).
  const cpFontSize = 11
  const cpCandidates = [
    { x: px.x + 12, y: px.y + 4, anchor: 'start' },
    { x: px.x - 12, y: px.y + 4, anchor: 'end' },
    { x: px.x, y: px.y + 20, anchor: 'middle' },
    { x: px.x, y: px.y - 12, anchor: 'middle' },
  ]
  const cpBest = registry.findBest(cpLbl, cpFontSize, cpCandidates)
  registry.add(cpBest.rect)
  const t = makeSvg('text', {
    x: cpBest.x.toFixed(1),
    y: cpBest.y.toFixed(1),
    'text-anchor': cpBest.anchor,
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '600',
    'font-size': String(cpFontSize),
    fill: '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.5',
    'stroke-linejoin': 'round',
  })
  t.textContent = cpLbl
  svg.appendChild(t)
}

// ---- Obstacle point ----

export function drawObstaclePoint(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  const subkind = String(
    feature.properties.subkind || feature.properties.obstacle_type || 'block',
  ).toLowerCase()

  svg.appendChild(
    makeSvg('rect', {
      x: (px.x - 11).toFixed(1),
      y: (px.y - 11).toFixed(1),
      width: '22',
      height: '22',
      rx: '3',
      fill: '#fff',
      stroke: 'none',
      opacity: '0.92',
    }),
  )

  const g = makeSvg('g', { transform: `translate(${px.x},${px.y})` })

  if (subkind === 'minefield' || subkind === 'mined_area') {
    for (const [dx, dy] of [[-6, -3], [6, -3], [0, 6]]) {
      g.appendChild(
        makeSvg('circle', {
          cx: String(dx),
          cy: String(dy),
          r: '2.8',
          fill: '#000',
        }),
      )
    }
  } else if (
    subkind === 'blown_bridge' ||
    subkind === 'bridge_blown' ||
    subkind === 'demolished_bridge'
  ) {
    g.appendChild(
      makeSvg('path', {
        d: 'M -8 -5 L 8 -5 M -8 5 L 8 5 M -7 -7 L 7 7 M 7 -7 L -7 7',
        stroke: '#000',
        'stroke-width': '1.8',
        'stroke-linecap': 'round',
      }),
    )
  } else if (subkind === 'bridge') {
    g.appendChild(
      makeSvg('path', {
        d: 'M -8 -5 L 8 -5 M -8 5 L 8 5',
        stroke: '#000',
        'stroke-width': '2.4',
        'stroke-linecap': 'round',
      }),
    )
  } else if (
    subkind === 'ford' ||
    subkind === 'ford_easy' ||
    subkind === 'ford_difficult'
  ) {
    g.appendChild(
      makeSvg('path', {
        d: 'M -8 -3 L -2 -3 M -1 0 L 5 0 M 6 3 L 8 3',
        stroke: '#000',
        'stroke-width': '2.2',
        'stroke-linecap': 'round',
      }),
    )
  } else if (subkind === 'road_block' || subkind === 'block') {
    g.appendChild(makeSvg('path', { d: 'M 0 -7 L 7 5 L -7 5 Z', fill: '#000' }))
  } else if (subkind === 'abatis') {
    g.appendChild(
      makeSvg('path', {
        d: 'M -7 5 L 0 -7 L 7 5',
        stroke: '#000',
        fill: 'none',
        'stroke-width': '2.2',
        'stroke-linejoin': 'miter',
      }),
    )
  } else if (subkind === 'crater') {
    g.appendChild(
      makeSvg('circle', {
        r: '8',
        fill: '#fff',
        stroke: '#000',
        'stroke-width': '1.8',
      }),
    )
    g.appendChild(
      makeSvg('path', {
        d: 'M -5 -5 L 5 5 M 5 -5 L -5 5',
        stroke: '#000',
        'stroke-width': '1.8',
      }),
    )
  } else if (subkind === 'ferry') {
    g.appendChild(
      makeSvg('circle', {
        r: '8',
        fill: '#fff',
        stroke: '#000',
        'stroke-width': '1.8',
      }),
    )
    const t = makeSvg('text', {
      'text-anchor': 'middle',
      y: '4',
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '800',
      'font-size': '12',
    })
    t.textContent = 'F'
    g.appendChild(t)
  } else {
    g.appendChild(
      makeSvg('path', {
        d: 'M -7 -7 L 7 7 M 7 -7 L -7 7',
        stroke: '#000',
        'stroke-width': '2.2',
      }),
    )
  }
  svg.appendChild(g)

  if (!registry) return
  const lblText = feature.properties.name || subkind.toUpperCase()
  if (!lblText) return
  // Matches reference-image label tier (was 20pt, now 11pt).
  const fontSize = 11
  const candidates = [
    { x: px.x + 11, y: px.y + 4, anchor: 'start' },
    { x: px.x - 11, y: px.y + 4, anchor: 'end' },
    { x: px.x, y: px.y + 22, anchor: 'middle' },
    { x: px.x, y: px.y - 14, anchor: 'middle' },
    { x: px.x + 11, y: px.y + 20, anchor: 'start' },
    { x: px.x - 11, y: px.y + 20, anchor: 'end' },
    { x: px.x + 11, y: px.y - 14, anchor: 'start' },
    { x: px.x - 11, y: px.y - 14, anchor: 'end' },
  ]
  const best = registry.findBest(lblText, fontSize, candidates)
  registry.add(best.rect)
  const t = makeSvg('text', {
    x: best.x.toFixed(1),
    y: best.y.toFixed(1),
    'text-anchor': best.anchor,
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '600',
    'font-size': String(fontSize),
    fill: '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.5',
    'stroke-linejoin': 'round',
  })
  t.textContent = lblText
  svg.appendChild(t)
}

// ---- Direction of attack (red filled chevron) ----

// ---- Axis of Advance ----
// Per FM 1-02.2 Ch 5 (axis of advance control measure) + FM 3-90 (May
// 2023) forms-of-the-offense taxonomy: open-tail broad-arrow whose
// geometry is identical across all tactical-mission-task roles. The
// role is communicated via FM 1-02.2 §5 text amplifiers (`ME` /
// `CATK` / `DEM` / `FEINT`) and — for feint specifically — the APP-6
// field AB Feint / Dummy Indicator Line (dashed inverted V above the
// arrow body midpoint per FM 1-02.2 Table 5-15).
//
// Per-role treatment (this drawer):
//   - main_effort:    solid body, standard width, `ME` amplifier.
//   - supporting:     solid body, standard width, no amplifier.
//   - feint:          SOLID body (NOT dashed), standard width, plus
//                     APP-6 field AB inverted-V dummy-indicator
//                     overlay above the arrow body midpoint per
//                     FM 1-02.2 Table 5-15.
//   - demonstration:  solid body, standard width, `DEM` amplifier;
//                     tip stops short of enemy frontage (writer's
//                     polyline responsibility — painter renders what
//                     it receives).
//   - counter_attack: DASHED body per FM 1-02.2 §5-6 (dashed is
//                     intrinsic to the counter-attack control measure,
//                     not a planned-status indicator), `CATK`
//                     amplifier.
//   - (no role):      solid body, standard width, no amplifier.
//
// Earlier per-role stroke-width modulation (main_effort 4.5 vs feint
// 1.5 vs supporting 2.0) was a Pytho-coined painter invention not
// found in FM 1-02.2 — the doctrinal differentiator is the amplifier
// text and the feint indicator overlay, not stroke thickness. Earlier
// translucent fill under main_effort was likewise invented; FM 1-02.2
// axis-of-advance is hollow outline only.
export function drawAxisOfAdvance(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return

  // Echelon → axis corridor width (km). Annex C visual: DIV main effort
  // ~8 km corridor at corps zoom, not the 20+ km block of pre-clamp days.
  const sizeStr = String(
    feature.properties.echelon || feature.properties.size || 'div',
  ).toLowerCase()
  // Same echelon-type mapping as drawAvenueChevron: cav/regt → brigade size,
  // squadron → battalion size, troop → company size.
  const widthKm = sizeStr.includes('div')
    ? 8
    : sizeStr.includes('bde') || sizeStr.includes('brigade')
        || sizeStr.includes('cav') || sizeStr.includes('regt') || sizeStr.includes('regiment')
      ? 5
      : sizeStr.includes('bn') || sizeStr.includes('battalion') || sizeStr.includes('squadron')
        ? 3
        : sizeStr.includes('co') || sizeStr.includes('company') || sizeStr.includes('troop')
          ? 2
          : 2

  const waypoints = coords.map(c => {
    const p = map.project(c)
    return { x: p.x, y: p.y, lng: c[0], lat: c[1] }
  })
  const meanLat = (waypoints[0].lat + waypoints[waypoints.length - 1].lat) / 2
  const dLatPerKm = 1 / 110.574
  const dLngPerKm = 1 / (111.32 * Math.cos((meanLat * Math.PI) / 180))
  const probeNorth = map.project([waypoints[0].lng, waypoints[0].lat + dLatPerKm])
  const probeEast = map.project([waypoints[0].lng + dLngPerKm, waypoints[0].lat])
  const pxPerKm = Math.hypot(
    probeEast.x - waypoints[0].x, probeNorth.y - waypoints[0].y,
  ) / Math.SQRT2
  // Width clamp 30-110 px so the axis is readable but doesn't dominate
  // a tight-bbox Kopu render. Slimmer than before (was 40-180) — earlier
  // sizes hid the underlying terrain + units the analyst is supposed to
  // be reading the axis AGAINST.
  const widthPx = Math.max(30, Math.min(widthKm * pxPerKm, 110))

  // Affiliation color via the shared AFFILIATION_COLORS palette
  // (FM 1-02.2 Ch. 2). axis_of_advance IS the friendly/threat plan;
  // unlike AAs it never reads as neutral.
  const strokeColor = resolveAffiliationColor(feature)

  const outline = buildArrowOutline(waypoints, widthPx)
  if (!outline) return

  // Role-driven amplifier + dash per FM 1-02.2 §5 + Table 5-15. The
  // writer emits an axis_role_assignments row per arrow tagging the
  // COA-specific role; backend builds the axis_of_advance overlay
  // with attrs.role. Geometry + stroke width are uniform across
  // roles; the doctrinal differentiator is the amplifier text and,
  // for feint, the dummy-indicator overlay.
  const role = String(feature.properties && feature.properties.role || '').toLowerCase()
  const isCounterAttack = role === 'counter_attack'
  const isFeint = role === 'feint'

  // Standard stroke width applies to every role per FM 1-02.2 — main
  // effort does NOT carry a thicker stroke (that's the unit amplifier's
  // job).
  const bodyStrokeWidth = 2.5
  // counter_attack body is dashed per FM 1-02.2 §5-6 (the dash IS the
  // counter-attack control measure, not a status indicator). Every
  // other role — including feint and demonstration — paints solid.
  const bodyDashArray = isCounterAttack ? '6,4' : null

  // Amplifier text per FM 1-02.2 §5 tactical-mission task amplifier
  // convention. Drawn ahead of the unit designation by
  // drawArrowPathLabel in a smaller font.
  const amplifier =
    role === 'main_effort'    ? 'ME'    :
    role === 'counter_attack' ? 'CATK'  :
    role === 'demonstration'  ? 'DEM'   :
    ''  // supporting + feint + no-role carry no amplifier text
        // (feint differentiates via the dummy-indicator overlay).

  // OPEN-tail axis_of_advance per FM 1-02.2 Ch 5 — two body strokes +
  // arrowhead, no closing edge at the tail. Hollow outline only; the
  // earlier translucent fill under main_effort was a Pytho painter
  // invention not in doctrine.
  for (const d of [outline.leftBodyPath, outline.rightBodyPath, outline.headPath]) {
    const pathAttrs = {
      d,
      fill: 'none',
      stroke: strokeColor,
      'stroke-width': String(bodyStrokeWidth),
      'stroke-linejoin': 'round',
      'stroke-linecap': 'round',
    }
    if (bodyDashArray) pathAttrs['stroke-dasharray'] = bodyDashArray
    svg.appendChild(makeSvg('path', pathAttrs))
  }

  // feint role: paint the FM 1-02.2 Table 5-15 / APP-6 field AB
  // Feint / Dummy Indicator Line — dashed inverted V centered above
  // the arrow body midpoint. The indicator glyph (NOT a text
  // amplifier) is the doctrinal differentiator between feint and
  // supporting / demonstration.
  if (isFeint) {
    drawFeintDummyIndicator(svg, outline, strokeColor)
  }

  // Axis name label ALONG the corridor at midpoint, rotated to tangent.
  // Amplifier (when set) renders ahead of the label in smaller font.
  // The backend `_extract_writer_axis_role_assignments` composes the
  // feature.name as "<ROLE LABEL> <unit_designation>" for legacy
  // consumers (e.g. legend). Now that we paint the doctrinal amplifier
  // separately, strip the leading role-label prefix from the rendered
  // label when the amplifier already carries it — otherwise the arrow
  // reads "ME / MAIN EFFORT 60 MECH IFV DIV" which double-states the
  // role.
  let lblText =
    feature.properties.name || feature.properties.designation || ''
  if (amplifier && lblText) {
    const rolePrefix = role.toUpperCase().replace(/_/g, ' ') + ' '
    if (lblText.toUpperCase().startsWith(rolePrefix)) {
      lblText = lblText.slice(rolePrefix.length)
    }
  }
  if ((lblText || amplifier) && registry) {
    drawArrowPathLabel(svg, outline, lblText, registry, {
      fill: strokeColor,
      amplifier,
    })
  }
}

// FM 1-02.2 Table 5-15 / APP-6 field AB Feint / Dummy Indicator Line.
// Dashed inverted-V drawn ABOVE the arrow body midpoint, sized
// proportional to the body width so it reads as a doctrinal overlay
// rather than a stray glyph. The vertex points UP relative to the
// arrow tangent (i.e. on the "left" side of motion direction per the
// FM convention — implemented here as the +normal side from
// buildArrowOutline's perp).
function drawFeintDummyIndicator(svg, outline, strokeColor) {
  if (!outline || !outline.midSamples || outline.midSamples.length === 0) return
  const samples = outline.midSamples
  const mid = samples[Math.floor(samples.length / 2)]
  // Indicator size: legs ~3x body half-width; offset above body by
  // ~1.5x body half-width so the vertex sits clear of the centerline.
  // Falls back to a fixed size if outline didn't stash widthPx.
  const halfW = (outline.halfW && outline.halfW > 0)
    ? outline.halfW
    : 12
  const legLen = halfW * 1.6
  const baseOffset = halfW * 1.5
  // Base of the V sits centered on the midpoint, lifted along the
  // tangent's perpendicular (mid.nx, mid.ny) by baseOffset.
  const bx = mid.x + mid.nx * baseOffset
  const by = mid.y + mid.ny * baseOffset
  // Two legs sweep from the base outward (-tx and +tx) and DOWN
  // toward the arrow body (the "inverted V" — vertex on top, legs
  // diverging toward the body). Per FM 1-02.2 the indicator's apex
  // is on the FAR side from the body; legs point BACK toward the
  // arrow.
  const apexX = bx
  const apexY = by + mid.ny * (legLen * 0.5)  // pull apex slightly further out
  // Actually the doctrinal glyph is a peak: vertex on top, legs
  // descending. Compute two leg endpoints at ± angle from apex,
  // sweeping along the tangent and back toward the body's normal.
  const apexNX = mid.nx
  const apexNY = mid.ny
  const apexTX = mid.tx
  const apexTY = mid.ty
  // Apex sits at base + further-out offset along normal.
  const ax = bx + apexNX * (legLen * 0.4)
  const ay = by + apexNY * (legLen * 0.4)
  // Leg endpoints: from apex, sweep ±tangent (legLen on tangent
  // axis), and INWARD along -normal (legLen on normal axis).
  const leftX  = ax - apexTX * legLen - apexNX * legLen
  const leftY  = ay - apexTY * legLen - apexNY * legLen
  const rightX = ax + apexTX * legLen - apexNX * legLen
  const rightY = ay + apexTY * legLen - apexNY * legLen
  const d = `M ${leftX.toFixed(1)},${leftY.toFixed(1)} `
          + `L ${ax.toFixed(1)},${ay.toFixed(1)} `
          + `L ${rightX.toFixed(1)},${rightY.toFixed(1)}`
  svg.appendChild(
    makeSvg('path', {
      d,
      fill: 'none',
      stroke: strokeColor,
      'stroke-width': '2',
      'stroke-dasharray': '4,3',
      'stroke-linejoin': 'round',
      'stroke-linecap': 'round',
    }),
  )
  // Suppress unused-var lint for the geometric helpers retained for
  // future readability.
  void apexX
  void apexY
}


// Supply/route line (MSR/ASR/route) — a labeled route corridor, NOT a
// direction-of-attack arrow. Honors the catalog modifiers: stroke
// color (default saddle-brown), dash pattern (solid MSR / dashed ASR),
// width, and the route designation. The designation rides a boxed
// label at both ends and at the midpoint so a long corridor is
// readable end to end (FM 1-02.2 route-marking convention).
export function drawSupplyRoute(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  const mods = feature.properties.modifiers || {}
  const pts = _saneScreenPts(map, coords)
  const lineD = _brokenPathD(pts)
  if (!lineD) return
  // FM 1-02.2 para 5-3: friendly control measures are BLACK (or blue),
  // hostile RED — never a terrain-feature color (the old saddle-brown
  // default was indistinguishable from the topo basemap's roads). An
  // explicit hex modifier still wins for analyst-authored styling.
  const side = String(feature.properties.side
    || feature.properties.affiliation || '').toLowerCase()
  const color = (typeof mods.stroke_color === 'string' && mods.stroke_color.startsWith('#'))
    ? mods.stroke_color
    : (side === 'hostile' || side === 'enemy' ? '#b91c1c' : '#000000')
  const width = Number(mods.width_px) || 3
  // Dashing is STATUS (planned/suspected), never route class (FM
  // 1-02.2 para 5-6) — it applies only when the feature says so.
  const dashed = mods.dash_pattern === 'dashed'
    || /planned|suspected/i.test(String(feature.properties.status || ''))

  // White casing for contrast over terrain, then the route line.
  svg.appendChild(makeSvg('path', {
    d: lineD, fill: 'none', stroke: '#fff',
    'stroke-width': String(width + 4), 'stroke-linecap': 'round',
    'stroke-linejoin': 'round', opacity: '0.7',
  }))
  svg.appendChild(makeSvg('path', {
    d: lineD, fill: 'none', stroke: color,
    'stroke-width': String(width), 'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    ...(dashed ? { 'stroke-dasharray': '10 7' } : {}),
  }))

  // "MSR <name>" ABOVE the line, set along it (FM 1-02.2 table 5-17:
  // the designation prints above the line). A road-following route
  // WIGGLES, so a label rotated to one segment's bearing crosses back
  // over the line repeatedly. Placement (user prescription
  // 2026-07-17): take the sub-path spanning ONE TEXT-WIDTH of arc
  // around the station, use its CHORD as the label bearing, and lift
  // perpendicular to that chord by the window's maximum deviation
  // from it plus clearance — the label rides beside the route and
  // never intersects it. Fixed stations, no dynamic movement.
  const _rname = (feature.properties.name || feature.properties.designation || '')
  const _ann = mods.annotation ? String(mods.annotation) : ''
  const desig = ((_ann && !new RegExp(`^${_ann}\\b`, 'i').test(_rname.trim()))
    ? `${_ann} ${_rname}` : _rname).trim()
  if (!desig) return
  // STATIC placement (user ruling: no dynamic label movement — a label
  // must not change position OR bearing with zoom). Everything that
  // determines the label — station points, chord windows, bearings —
  // is computed ONCE from the route's GEOGRAPHIC coordinates and
  // cached on the feature. The earlier screen-pixel chord window
  // spanned different ground at every zoom, so the label visibly
  // rotated between zooms. Only the perpendicular lift (which must
  // clear the wiggle at the CURRENT projection) and the projection of
  // the fixed anchors happen per paint; under pure pan/zoom a
  // Mercator-projected fixed chord keeps a constant screen bearing.
  const fontSize = 11
  let plan = feature.__routeLabelPlan
  if (!plan) {
    const kx = 111.32 * Math.cos((coords[0][1] || 0) * Math.PI / 180)
    const ky = 110.57
    const cumKm = [0]
    for (let i = 1; i < coords.length; i++) {
      cumKm.push(cumKm[i - 1] + Math.hypot(
        (coords[i][0] - coords[i - 1][0]) * kx,
        (coords[i][1] - coords[i - 1][1]) * ky))
    }
    const totalKm = cumKm[cumKm.length - 1]
    const at = (sKm) => {
      const sc = Math.max(0, Math.min(totalKm, sKm))
      let i = 1
      while (i < cumKm.length - 1 && cumKm[i] < sc) i++
      const a = coords[i - 1]
      const b = coords[i]
      const seg = cumKm[i] - cumKm[i - 1] || 1
      const f = (sc - cumKm[i - 1]) / seg
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
    }
    // Fixed-ground chord window per station: a fraction of the route,
    // clamped — deterministic per feature, zoom-independent.
    const winKm = Math.max(5, Math.min(60, totalKm * 0.18))
    const fractions = totalKm > 150 ? [0.25, 0.5, 0.75] : [0.5]
    const stations = []
    for (const f of fractions) {
      const sMid = f * totalKm
      const s0 = sMid - winKm / 2
      const s1 = sMid + winKm / 2
      if (s0 < 0 || s1 > totalKm) continue
      const g0 = at(s0)
      const g1 = at(s1)
      const chordKm = Math.hypot((g1[0] - g0[0]) * kx, (g1[1] - g0[1]) * ky)
      // Hairpin window: no honest chord — skip the station for good.
      if (chordKm < winKm * 0.6) continue
      // Window vertices for the paint-time deviation check.
      const winPts = []
      for (let i = 0; i < coords.length; i++) {
        if (cumKm[i] >= s0 && cumKm[i] <= s1) winPts.push(coords[i])
      }
      stations.push({ g0, g1, winPts })
    }
    plan = { stations }
    feature.__routeLabelPlan = plan
  }
  for (const st of plan.stations) {
    const p0 = map.project(st.g0)
    const p1 = map.project(st.g1)
    let dx = p1.x - p0.x
    let dy = p1.y - p0.y
    const L = Math.hypot(dx, dy) || 1
    dx /= L; dy /= L
    let angle = Math.atan2(dy, dx) * 180 / Math.PI
    let flip = false
    if (angle > 90 || angle < -90) { angle += 180; flip = true }
    let nx = flip ? -dy : dy
    let ny = flip ? dx : -dx
    if (ny > 0) { nx = -nx; ny = -ny }
    let maxDev = 0
    for (const g of st.winPts) {
      const p = map.project(g)
      const dev = Math.abs((p.x - p0.x) * nx + (p.y - p0.y) * ny)
      if (dev > maxDev) maxDev = dev
    }
    const lift = maxDev + width / 2 + 7
    const ax = (p0.x + p1.x) / 2 + nx * lift
    const ay = (p0.y + p1.y) / 2 + ny * lift
    const t2 = makeSvg('text', {
      x: ax.toFixed(1),
      y: ay.toFixed(1),
      'text-anchor': 'middle',
      transform: `rotate(${angle.toFixed(1)}, ${ax.toFixed(1)}, ${ay.toFixed(1)})`,
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '700',
      'font-size': String(fontSize),
      fill: color,
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '3',
      'stroke-linejoin': 'round',
    })
    t2.textContent = desig
    svg.appendChild(t2)
  }
}


export function drawDirectionOfAttack(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  const pts = _saneScreenPts(map, coords)
  const doaD = _brokenPathD(pts)
  if (!doaD) return

  svg.appendChild(
    makeSvg('path', {
      d: doaD,
      fill: 'none',
      stroke: '#fff',
      'stroke-width': '9',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      opacity: '0.75',
    }),
  )
  svg.appendChild(
    makeSvg('path', {
      d: doaD,
      fill: 'none',
      stroke: '#b91c1c',
      'stroke-width': '4.5',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
  )

  const tip = pts[pts.length - 1]
  const prev = pts[pts.length - 2]
  if (!tip._sane || !prev._sane) return
  let dx = tip.x - prev.x
  let dy = tip.y - prev.y
  const mag = Math.hypot(dx, dy) || 1
  dx /= mag
  dy /= mag
  const nx = -dy
  const ny = dx
  const HEAD_LEN = 26
  const HEAD_W = 16
  const base = { x: tip.x - dx * HEAD_LEN, y: tip.y - dy * HEAD_LEN }
  const L = { x: base.x + nx * HEAD_W, y: base.y + ny * HEAD_W }
  const R = { x: base.x - nx * HEAD_W, y: base.y - ny * HEAD_W }
  svg.appendChild(
    makeSvg('polygon', {
      points: `${tip.x.toFixed(1)},${tip.y.toFixed(1)} ${L.x.toFixed(1)},${L.y.toFixed(1)} ${R.x.toFixed(1)},${R.y.toFixed(1)}`,
      fill: '#b91c1c',
      stroke: '#7f1d1d',
      'stroke-width': '1.5',
    }),
  )

  const lblText =
    feature.properties.name || feature.properties.designation || ''
  if (lblText && registry) {
    drawHaloedLabel(svg, { x: tip.x, y: tip.y }, lblText, {
      fontSize: 11,
      fill: '#7f1d1d',
      dy: 6,
      registry,
    })
  }
}

// ---- Strong point ----

export function drawStrongPoint(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: '14',
      fill: '#fff',
      opacity: '0.92',
    }),
  )
  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: '11',
      fill: '#fff',
      stroke: '#1e3a8a',
      'stroke-width': '2.2',
    }),
  )
  const s = makeSvg('text', {
    x: px.x.toFixed(1),
    y: (px.y + 4).toFixed(1),
    'text-anchor': 'middle',
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '900',
    'font-size': '13',
    fill: '#1e3a8a',
  })
  s.textContent = 'S'
  svg.appendChild(s)
  drawHaloedLabel(svg, px, feature.properties.name || '', {
    fontSize: 11,
    dy: 16,
    registry,
  })
}

// ---- Decision point (5-point red star, per ATP 2-01.3 Fig 6-3) ----

export function drawDecisionPoint(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  // Doctrinal DP per ATP 2-01.3 / FM 1-02.2 = unfilled (or thin-filled)
  // 5-point RED STAR — NOT the black diamond with "DP" inside we had.
  // Star geometry: 5 outer points at r=14, 5 inner points at r=6, top
  // point straight up (rotate -π/2 to put first vertex at 12-o'clock).
  const rOuter = 13
  const rInner = 5.5
  const pts = []
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5
    const r = i % 2 === 0 ? rOuter : rInner
    pts.push(`${(px.x + r * Math.cos(a)).toFixed(1)},${(px.y + r * Math.sin(a)).toFixed(1)}`)
  }
  svg.appendChild(
    makeSvg('polygon', {
      points: pts.join(' '),
      fill: '#fff',
      opacity: '0.85',
    }),
  )
  svg.appendChild(
    makeSvg('polygon', {
      points: pts.join(' '),
      fill: 'none',
      stroke: '#b91c1c',
      'stroke-width': '2.2',
      'stroke-linejoin': 'round',
    }),
  )
  drawHaloedLabel(
    svg,
    px,
    feature.properties.name || feature.properties.designation || '',
    { fontSize: 11, fill: '#7f1d1d', dy: 16, registry },
  )
}

// ---- Air corridor ----

export function drawAirCorridor(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  const pts = _saneScreenPts(map, coords).filter(p => p._sane)
  if (pts.length < 2) return
  const WIDTH_PX = 14
  const left = []
  const right = []
  for (let i = 0; i < pts.length; i++) {
    let tx = 0
    let ty = 0
    if (i < pts.length - 1) {
      tx += pts[i + 1].x - pts[i].x
      ty += pts[i + 1].y - pts[i].y
    }
    if (i > 0) {
      tx += pts[i].x - pts[i - 1].x
      ty += pts[i].y - pts[i - 1].y
    }
    const mag = Math.hypot(tx, ty) || 1
    tx /= mag
    ty /= mag
    const nx = -ty
    const ny = tx
    left.push({ x: pts[i].x + nx * WIDTH_PX, y: pts[i].y + ny * WIDTH_PX })
    right.push({ x: pts[i].x - nx * WIDTH_PX, y: pts[i].y - ny * WIDTH_PX })
  }
  const toStr = a => a.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  for (const rail of [left, right]) {
    svg.appendChild(
      makeSvg('polyline', {
        points: toStr(rail),
        fill: 'none',
        stroke: '#fff',
        'stroke-width': '4.5',
        opacity: '0.75',
      }),
    )
    svg.appendChild(
      makeSvg('polyline', {
        points: toStr(rail),
        fill: 'none',
        stroke: '#0ea5e9',
        'stroke-width': '2.2',
      }),
    )
  }
  const midIdx = Math.floor(pts.length / 2)
  const lblText =
    feature.properties.name ||
    (feature.properties.subkind || 'AIR CORR').toUpperCase()
  drawHaloedLabel(svg, pts[midIdx], lblText, {
    fontSize: 11,
    fill: '#0c4a6e',
    registry,
  })
}

// ---- FSCM label ----

export function drawFscmLabel(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  const midIdx = Math.floor(coords.length / 2)
  const px = map.project(coords[midIdx])
  const sub = String(feature.properties.subkind || 'FSCM').toUpperCase()
  let name = String(feature.properties.name || '')
  const nameUpper = name.toUpperCase()
  if (nameUpper.startsWith(sub + ' ')) name = name.slice(sub.length + 1)
  else if (nameUpper === sub) name = ''
  const lblText = name ? `${sub} ${name}` : sub
  drawHaloedLabel(svg, px, lblText, {
    fontSize: 11,
    fill: '#000',
    dy: -8,
    registry,
  })
}

// ---- Boundary label ----

export function drawBoundaryLabel(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  if (!registry) return
  const sub = String(feature.properties.subkind || 'BNDRY').toUpperCase()
  const name = String(feature.properties.name || '')
  const nameUpper = name.toUpperCase()
  let trimmedName = name
  if (nameUpper.startsWith(sub + ' ')) trimmedName = name.slice(sub.length + 1)
  else if (nameUpper === sub) trimmedName = ''
  const lblText = trimmedName ? `${sub} ${trimmedName}` : sub
  // Per FM 1-02.2 / FM 6-99: boundary labels render at BOTH endpoints of
  // the line. text-anchor MUST match the side — at the start cap the
  // text grows RIGHT (anchor=start), at the end cap the text grows LEFT
  // into the cap (anchor=end) so the right edge of the text aligns with
  // the line cap instead of starting past it.
  const fontSize = 10
  const startPx = map.project(coords[0])
  const endPx = map.project(coords[coords.length - 1])

  const candidatesAtStart = px => [
    { x: px.x + 6, y: px.y - 6, anchor: 'start' },
    { x: px.x + 6, y: px.y + 12, anchor: 'start' },
    { x: px.x - 6, y: px.y - 6, anchor: 'end' },
    { x: px.x - 6, y: px.y + 12, anchor: 'end' },
  ]
  const candidatesAtEnd = px => [
    { x: px.x - 6, y: px.y - 6, anchor: 'end' },
    { x: px.x - 6, y: px.y + 12, anchor: 'end' },
    { x: px.x + 6, y: px.y - 6, anchor: 'start' },
    { x: px.x + 6, y: px.y + 12, anchor: 'start' },
  ]

  const tryPlace = cands => {
    for (const c of cands) {
      const r = estimateTextBBox(lblText, fontSize, c.x, c.y, c.anchor)
      if (registry.insideCanvas(r) && !registry.anyOverlap(r)) {
        return { ...c, rect: r }
      }
    }
    return null
  }

  const paintLabel = pick => {
    if (!pick) return
    registry.add(pick.rect)
    const t = makeSvg('text', {
      x: pick.x.toFixed(1),
      y: pick.y.toFixed(1),
      'text-anchor': pick.anchor,
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '600',
      'font-size': String(fontSize),
      fill: '#000',
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '2.5',
      'stroke-linejoin': 'round',
    })
    t.textContent = lblText
    svg.appendChild(t)
  }

  paintLabel(tryPlace(candidatesAtStart(startPx)))
  paintLabel(tryPlace(candidatesAtEnd(endPx)))
}

// ---- Battle position label ----

// FM 1-02.2 Table 5-5 battle-position label. Echelon prefix per
// Table 5-2 field B (e.g. "Company BP MARS"), state amplifier per
// Table 5-5 example captions (e.g. "Company BP MARS planned but not
// prepared"). Color follows the shared AFFILIATION_COLORS resolver.
//
// bp_state values per FM 1-02.2 Table 5-5:
//   'occupied'           (default) — solid outline + chevron; no amplifier.
//   'prepared_unoccupied'         — solid outline + "prepared but not occupied" amplifier.
//   'planned_not_prepared'        — dashed outline + "planned but not prepared" amplifier.
//
// The polygon stroke pattern (solid vs dashed) is controlled by the
// MapLibre layer paint expression on `bp_state` in tacticalLayers
// .maplibre.js; this SVG drawer only handles the text label + state
// amplifier. The polygon outline shape is invariant across states
// per FM 1-02.2 Table 5-5 — same physical BP, different occupancy.
export function drawBattlePositionLabel(map, svg, feature, registry) {
  const c = polyCentroid(feature.geometry)
  if (!c) return
  const px = map.project(c)
  const props = feature.properties || {}
  const name = props.name || props.designation || ''
  const echelon = String(props.echelon || '').trim()
  const bpState = String(props.bp_state || 'occupied').toLowerCase()
  // Echelon prefix per FM 1-02.2 Table 5-2 field B. Title-cased so
  // labels read naturally (e.g. "Company BP MARS"). Drop if absent —
  // preserves behavior for features without an echelon hint.
  const echelonPrefix = echelon ? `${_titleCaseEchelon(echelon)} ` : ''
  // State amplifier per FM 1-02.2 Table 5-5 example captions. The
  // default 'occupied' carries no amplifier.
  const stateAmplifier =
    bpState === 'planned_not_prepared' ? ' planned but not prepared'  :
    bpState === 'prepared_unoccupied'  ? ' prepared but not occupied' :
    ''
  const base = name ? `BP ${name}` : 'BP'
  const lblText = `${echelonPrefix}${base}${stateAmplifier}`
  drawHaloedLabel(svg, px, lblText, {
    fontSize: 11,
    fill: resolveAffiliationColor(feature),
    registry,
  })
}

// Capitalize the first letter of an echelon word for label display.
// Accepts canonical schema tokens ('company' / 'battalion' /
// 'brigade' / 'division' / 'regiment' / 'squadron' / 'troop' /
// 'platoon') and returns the title-cased form. Unknown values pass
// through unchanged (allows the schema to evolve without label
// breakage).
function _titleCaseEchelon(s) {
  if (!s) return ''
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
}

// ---- Assembly area label ----

export function drawAssemblyAreaLabel(map, svg, feature, registry) {
  const c = polyCentroid(feature.geometry)
  if (!c) return
  const px = map.project(c)
  const name = feature.properties.name || feature.properties.designation || ''
  const lblText = name ? `AA ${name}` : 'AA'
  drawHaloedLabel(svg, px, lblText, { fontSize: 11, registry })
}

// ---- Point NAI / TAI ----

export function drawPointNaiBox(map, svg, feature, registry, isTai) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  const half = 14
  // Doctrinal NAI/TAI per FM 1-02.2 = transparent outlined rectangle, not
  // a white-filled square. Terrain + units below the box should remain
  // readable through it; the white-fill version was a legibility hack
  // that broke that. The text gets its own halo for legibility against
  // whatever shows through.
  const box = makeSvg('rect', {
    x: (px.x - half).toFixed(1),
    y: (px.y - half).toFixed(1),
    width: String(half * 2),
    height: String(half * 2),
    fill: 'none',
    stroke: '#000',
    'stroke-width': '1.8',
  })
  if (isTai) box.setAttribute('stroke-dasharray', '4,2')
  svg.appendChild(box)
  // "NAI" or "TAI" centered inside the box plus the designation (if any)
  // appended (e.g. "NAI 3"). Earlier renders showed empty boxes because
  // the tag label was only painted by drawControlMeasureLabel when an
  // associated control_measure feature existed; bare Points had no
  // associated CM and the box stayed blank.
  const designation = String(
    feature.properties.designation || feature.properties.name || '',
  ).replace(/^(NAI|TAI)\s*/i, '').trim()
  const tag = isTai ? 'TAI' : 'NAI'
  const inner = designation ? `${tag} ${designation}` : tag
  const tx = makeSvg('text', {
    x: px.x.toFixed(1),
    y: (px.y + 3).toFixed(1),
    'text-anchor': 'middle',
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '700',
    'font-size': '9',
    fill: '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.2',
    'stroke-linejoin': 'round',
  })
  tx.textContent = inner
  svg.appendChild(tx)
  if (registry) {
    registry.add({
      x: px.x - half,
      y: px.y - half,
      w: half * 2,
      h: half * 2,
      _src: isTai ? 'tai-box' : 'nai-box',
    })
  }
}

// ---- Point OBJ (annular circle, per ATP 2-01.3 Fig 6-3) ----

export function drawPointObjKidney(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  // Doctrinal OBJ per ATP 2-01.3 = open circle ringed in red with the
  // designation adjacent. Was a kidney — doctrine treats the kidney as
  // optional/older; the circle is what Fig 6-3 uses ("OBJ Alpha" /
  // "OBJ Bravo"). The annular ring keeps any unit symbol inside visible.
  const r = 16
  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: String(r),
      fill: '#fff',
      opacity: '0.7',
    }),
  )
  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: String(r),
      fill: 'none',
      stroke: '#b91c1c',
      'stroke-width': '2.4',
    }),
  )
  // "OBJ Name" label adjacent to the circle (right side preferred, then
  // below / above / left as collision avoidance).
  const designation = String(
    feature.properties.designation || feature.properties.name || '',
  ).replace(/^OBJ\s+/i, '').trim()
  const label = designation ? `OBJ ${designation}` : 'OBJ'
  if (registry) {
    drawHaloedLabel(svg, px, label, {
      fontSize: 11,
      fill: '#7f1d1d',
      dy: 0,
      registry,
    })
    registry.add({
      x: px.x - r,
      y: px.y - r,
      w: r * 2,
      h: r * 2,
      _src: 'obj-circle',
    })
  }
}

// ---- Range fan (concentric red circles around enemy weapon, per
// ATP 2-01.3 Fig 6-3 "3,500 meters" rings) ----

// ── Horizon-safe projection ─────────────────────────────────────────
// Under pitch, ground points at/behind the horizon project to screen
// coordinates in the millions; a single such vertex smears linework
// across the whole scene. Project with a sanity tag and build paths
// that BREAK across insane spans, drawing only the visible portion.
function _saneScreenPts(map, coords) {
  const cw = (map.getContainer && map.getContainer().clientWidth) || 1920
  const ch = (map.getContainer && map.getContainer().clientHeight) || 1080
  return coords.map(c => {
    const p = map.project(c)
    p._sane = Number.isFinite(p.x) && Number.isFinite(p.y)
      && p.x > -cw * 2 && p.x < cw * 3 && p.y > -ch * 2 && p.y < ch * 3
    return p
  })
}
function _brokenPathD(pts, close = false) {
  let d = ''
  let pen = false
  let broke = false
  for (const p of pts) {
    if (!p._sane) { pen = false; broke = true; continue }
    d += `${pen ? 'L' : 'M'} ${p.x.toFixed(1)} ${p.y.toFixed(1)} `
    pen = true
  }
  if (!d) return ''
  return (close && !broke) ? d + 'Z' : d
}

export function drawRangeFan(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  // Pixel-per-km probe at the feature's latitude (matches drawAvenueChevron
  // pattern so the ring scales correctly under zoom/pan). Heuristic
  // ONLY (label-fit checks): under pitch this length depends on
  // bearing, so nothing geometric may derive from it.
  const dLatPerKm = 1 / 110.574
  const probeNorth = map.project([c[0], c[1] + dLatPerKm])
  const pxPerKm = Math.abs(probeNorth.y - px.y)
  const coslatRing = Math.cos((c[1] * Math.PI) / 180) || 1e-9
  // A range ring is a GROUND circle. Project the actual geographic
  // circle point-by-point: top-down it is today's circle; under pitch
  // it is the correct ground ellipse; under rotation it is CONSTANT.
  // (The old constant-pixel-radius <circle> breathed with bearing
  // because the north-probe's screen length changes as the map turns.)
  const ringPointAt = (radiusM, bearingRad) => map.project([
    c[0] + (radiusM * Math.sin(bearingRad)) / (111320 * coslatRing),
    c[1] + (radiusM * Math.cos(bearingRad)) / 111320,
  ])
  // Under pitch, ground points at/behind the horizon project to
  // absurd screen coordinates (millions of px) — a single such vertex
  // smears the ring across the whole scene. Clip to a padded screen
  // region and BREAK the path across insane spans, drawing only the
  // visible portion of the ring.
  const _rcw = (map.getContainer && map.getContainer().clientWidth) || 1920
  const _rch = (map.getContainer && map.getContainer().clientHeight) || 1080
  const ringPtSane = (pt) => Number.isFinite(pt.x) && Number.isFinite(pt.y)
    && pt.x > -_rcw * 2 && pt.x < _rcw * 3
    && pt.y > -_rch * 2 && pt.y < _rch * 3
  const groundRingPath = (radiusM, n = 72) => {
    let d = ''
    let pen = false
    let broke = false
    for (let i = 0; i <= n; i++) {
      const pt = ringPointAt(radiusM, (2 * Math.PI * i) / n)
      if (!ringPtSane(pt)) { pen = false; broke = true; continue }
      d += `${pen ? 'L' : 'M'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)} `
      pen = true
    }
    if (!d) return ''
    return broke ? d : d + 'Z'
  }
  // Bands: either explicit `bands: [{radius_m, label?}, ...]` for
  // multi-ring weapon envelopes, OR a single `radius_m` shortcut. Skip
  // silently if neither is present (no-op for features that aren't
  // range fans but get accidentally bucketed here).
  const props = feature.properties || {}
  const bands = Array.isArray(props.bands) && props.bands.length
    ? props.bands
    : (props.radius_m
        ? [{ radius_m: props.radius_m, label: props.range_label }]
        : [])
  if (bands.length === 0) return
  // Per-weapon-class style. Analysts repeatedly complained that "the
  // range circles all look too similar" — they couldn't tell at a
  // glance which envelope was air-defense vs artillery vs ATGM. This
  // routine maps the label/subkind to a distinct stroke color +
  // pattern + width so each weapon family reads visually distinct.
  // Five doctrinal classes:
  //   ADA / air-defense       SA-*, S-*, Patriot, Stinger, HAWK, NASAMS
  //                           — RED dashed, thin (existing convention)
  //   Long-range / cruise     Iskander, Kalibr, SS-21, SCUD, Tochka
  //                           — DEEP RED dash-dot, heavy
  //   Indirect fire / artillery BM-21, BM-27, BM-30, MRL, FA, HOW, MLRS
  //                           — ORANGE-RED solid, thick
  //   Direct fire / AT        Kornet, Konkurs, AT-*, ATGM
  //                           — DARK RED short-dot, medium
  //   Default                 anything else — RED solid medium
  // Labels carry the weapon designator (SA-17 / BM-21 / Kornet) so the
  // class is identifiable. The label-tag stroke matches the ring color
  // so the visual link is obvious.
  const subkind = String(props.subkind || '').toLowerCase()
  function _rangeFanStyle(label, subkind) {
    const lbl = String(label || '').toLowerCase()
    // Long-range / cruise — distinct from ADA (different shape) and
    // artillery (different reach) so it gets the most distinct pattern.
    if (subkind === 'long_range' || subkind === 'cruise'
        || /\b(iskander|kalibr|ss-21|scud|tochka)/i.test(label)) {
      return { stroke: '#991b1b', width: '2.8',
                dash: '14,4,3,4', subclass: 'long_range' }
    }
    if (subkind === 'ada' || subkind === 'air_defense'
        || /^(sa-|s-\d|patriot|stinger|hawk|nasams|igla|verba|tor|tunguska|pantsir)/i.test(label)) {
      return { stroke: '#b91c1c', width: '1.8',
                dash: '8,4', subclass: 'ada' }
    }
    if (subkind === 'indirect_fire' || subkind === 'artillery' || subkind === 'mlrs'
        || /\b(bm-?21|bm-?27|bm-?30|grad|smerch|uragan|mrl|mlrs|fa[\s-]bde|how|2s\d|tornado)/i.test(label)) {
      return { stroke: '#ea580c', width: '2.8',
                dash: null, subclass: 'indirect_fire' }
    }
    if (subkind === 'antitank' || subkind === 'atgm'
        || /\b(konkurs|kornet|fagot|metis|at-\d|9m\d)/i.test(label)) {
      return { stroke: '#7f1d1d', width: '2.2',
                dash: '3,4', subclass: 'antitank' }
    }
    return { stroke: '#b91c1c', width: '2.2', dash: null,
              subclass: 'default' }
  }
  // Distribute curved range-distance labels around the upper arc so
  // multiple bands stay readable without colliding. Pick distinct anchor
  // angles per band — the innermost band gets ~30deg E-of-N, the next
  // ~60deg, the outermost ~340deg, etc. Angles measured CW from
  // 12-o'clock so the labels read in their natural orientation.
  const _bandAnchorAngles = [50, 75, 30, 100, 10, 130, 350]
  // Stable id base for textPath xlink:href references. SVG textPath only
  // works when the <path> has an id; build one per fan instance.
  const fanInstanceId = `rf-${(props.id || props.kbid || props.name || Math.round(px.x) + '_' + Math.round(px.y)).replace(/[^a-zA-Z0-9_-]/g, '_')}-${Math.round(Math.random() * 1e6)}`
  // Pre-sort bands by radius so the inner→outer mapping to anchor angles
  // is deterministic regardless of input ordering.
  const sortedBands = bands
    .map((b, idx) => ({ ...b, _origIdx: idx, _rPx: (Number(b.radius_m) / 1000) * pxPerKm }))
    .filter(b => isFinite(b._rPx) && b._rPx > 0)
    .sort((a, b) => a._rPx - b._rPx)
  for (let bandIx = 0; bandIx < sortedBands.length; bandIx++) {
    const band = sortedBands[bandIx]
    const rPx = band._rPx
    const label = String(band.label || '')
    const style = _rangeFanStyle(label, subkind)
    const ringD = groundRingPath(Number(band.radius_m))
    if (!ringD) continue
    const circleAttrs = {
      d: ringD,
      fill: 'none',
      stroke: style.stroke,
      'stroke-width': style.width,
      opacity: '0.92',
    }
    if (style.dash) circleAttrs['stroke-dasharray'] = style.dash
    // Placard-hover highlight: hovering an equipment row sets
    // map.__ringHighlight = {name, bearerId?}; the matching band
    // paints hot (thicker, full opacity, soft halo underlay). With
    // bearerId set (per-subordinate equipment rows) ONLY that unit's
    // ring lights — several units can field the same system.
    const hl = map.__ringHighlight
    const hlBearerOk = !hl || !hl.bearerId
      || String(props.bearer_id || props.bearer_unit_kg_id || '') === String(hl.bearerId)
    if (hl && hl.name && hlBearerOk && label
        && label.toLowerCase().startsWith(String(hl.name).toLowerCase())) {
      const { 'stroke-dasharray': _d, ...haloAttrs } = circleAttrs
      svg.appendChild(makeSvg('path', {
        ...haloAttrs,
        stroke: '#fde047',
        'stroke-width': String(parseFloat(style.width) + 6),
        opacity: '0.55',
      }))
      circleAttrs['stroke-width'] = String(parseFloat(style.width) + 2)
      circleAttrs.opacity = '1'
    }
    // The band OUTLINE is the doctrinal max-range ring — the projected
    // GROUND circle, always. Terrain-masked reach is carried by the 3D
    // envelope volume (crest-carved mesh) — never by mangling the
    // ring outline into a viewshed polygon; that starburst read as
    // garbage on every laydown it touched.
    svg.appendChild(makeSvg('path', circleAttrs))
    // Ring click target: clicking a band opens its bearer's placard
    // (useMapEvents hit-tests these before map-layer picks). Stored in
    // GROUND terms — screen-space center+radius is wrong under pitch.
    if (!map.__rangeRingHits) map.__rangeRingHits = []
    map.__rangeRingHits.push({
      lng: c[0], lat: c[1], radius_m: Number(band.radius_m),
      bearerId: String(props.bearer_unit_kg_id || props.bearer_id || ''),
    })

    // ===== Curved range-distance label along the circumference =====
    // Doctrinal requirement: every range ring carries its range value
    // (km) rendered tangent to the arc so the analyst can read distances
    // off the map at a glance. Distinct from the existing flat
    // designator tag-box at -pi/4 (kept for the outermost band only so
    // it doesn't double-label every ring).
    const rangeKm = Number(band.radius_m) / 1000
    const anchorDeg = _bandAnchorAngles[bandIx % _bandAnchorAngles.length]
    const aRad = (anchorDeg * Math.PI) / 180
    const p0 = ringPointAt(Number(band.radius_m), aRad)
    const p1 = ringPointAt(Number(band.radius_m), aRad + Math.PI / 90)
    if (rangeKm >= 0.5 && rPx >= 28 && ringPtSane(p0) && ringPtSane(p1)) {
      // Skip when ring is too small to fit a readable label (< 28 px).
      const rangeLabel = rangeKm >= 10
        ? `${Math.round(rangeKm)} KM`
        : `${rangeKm.toFixed(1)} KM`
      // Anchor angle for this band — deg CW from 12-o'clock per the
      // distribution table above. Wrap modulo the table length so we
      // never run out of slots even with many bands.
      // The label rides the PROJECTED ground ring (correct under pitch
      // and rotation). Estimate the local screen length per degree of
      // arc at the anchor bearing, size the arc to the label, and
      // build the path from sampled ring points.
      const pxPerTwoDeg = Math.hypot(p1.x - p0.x, p1.y - p0.y) || 1
      const chars = rangeLabel.length
      const arcPx = chars * 8.5
      const arcDeg = Math.min(63, (arcPx / pxPerTwoDeg) * 2)
      const steps = 10
      let pathD = ''
      for (let k = 0; k <= steps; k++) {
        const th = ((anchorDeg - arcDeg / 2 + (arcDeg * k) / steps) * Math.PI) / 180
        const pt = ringPointAt(Number(band.radius_m), th)
        pathD += `${k === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)} `
      }
      const pathId = `${fanInstanceId}-b${bandIx}`
      const pathEl = makeSvg('path', {
        id: pathId,
        d: pathD,
        fill: 'none',
        stroke: 'none',
      })
      svg.appendChild(pathEl)
      // White stroke + ring-color fill for legibility on any terrain.
      const txt = makeSvg('text', {
        'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
        'font-weight': '700',
        'font-size': '11',
        fill: style.stroke,
        stroke: '#ffffff',
        'stroke-width': '3',
        'paint-order': 'stroke',
        'stroke-linejoin': 'round',
      })
      const tp = makeSvg('textPath', {
        href: `#${pathId}`,
        'xlink:href': `#${pathId}`,
        'text-anchor': 'middle',
        startOffset: '50%',
      })
      tp.textContent = rangeLabel
      txt.appendChild(tp)
      svg.appendChild(txt)
      if (registry) {
        // Approximate the curved text's bounding box for the collision
        // registry: a small box at the anchor point. Curved labels
        // hugging the circumference rarely collide with other glyphs;
        // the registry box is just enough to prevent the flat
        // designator tag (below) from overlapping.
        const anchorPt = ringPointAt(Number(band.radius_m), aRad)
        registry.add({
          x: anchorPt.x - arcPx / 2,
          y: anchorPt.y - 9,
          w: arcPx,
          h: 14,
          _src: 'range-fan-curved-label',
        })
      }
    }

    // Outermost band keeps the flat designator tag-box (weapon
    // designator) per the existing convention so analysts immediately
    // know what system the rings belong to. Inner bands rely on the
    // curved range-distance label only — the designator carries through
    // visually because all bands share the stroke color.
    const isOutermost = bandIx === sortedBands.length - 1
    if (label && isOutermost) {
      // Position the designator tag at the SW arc (-3*pi/4) so it
      // doesn't compete with the curved range labels in the upper
      // hemisphere. Format: "<designator>" e.g. "SA-22 PANTSIR-S1".
      const dAnchorPt = ringPointAt(Number(band.radius_m),
        (225 * Math.PI) / 180)  // SW
      const lx = dAnchorPt.x
      const ly = dAnchorPt.y
      // For the outermost band, label is the FULL designator + range
      // combo authored by the writer ("SA-17 22 km") — but with curved
      // range labels on every ring, the designator alone is enough.
      // Strip a trailing " <N> km" / " <N>km" suffix to avoid double-
      // labeling the range.
      // SHORT designator (the name up to its first parenthetical —
      // catalog names carry long NATO/descriptive suffixes that have
      // no place on the map), rendered ALONG the arc like the range
      // labels, never as a flat box crossing the ring.
      const designatorOnly = (label.replace(/\s+\d+(?:\.\d+)?\s*km\.?$/i, '')
        .split('(')[0].trim() || label).slice(0, 28)
      // Arc along the PROJECTED ground ring (constant under rotation,
      // correct ellipse under pitch), sized from the local screen
      // length at the SW anchor. Bearing runs high->low so the path
      // reads left-to-right in the lower hemisphere.
      const dA = ringPointAt(Number(band.radius_m), (225 * Math.PI) / 180)
      const dB = ringPointAt(Number(band.radius_m), (227 * Math.PI) / 180)
      if (!ringPtSane(dA) || !ringPtSane(dB)) continue
      const dPxPerTwoDeg = Math.hypot(dB.x - dA.x, dB.y - dA.y) || 1
      const arcPxD = designatorOnly.length * 8.5
      const arcDegD = Math.min(80, (arcPxD / dPxPerTwoDeg) * 2)
      const dSteps = 12
      let dPath = ''
      for (let k = 0; k <= dSteps; k++) {
        const thD = ((225 + arcDegD / 2 - (arcDegD * k) / dSteps) * Math.PI) / 180
        const pt = ringPointAt(Number(band.radius_m), thD)
        dPath += `${k === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)} `
      }
      const dPathId = `${fanInstanceId}-designator`
      svg.appendChild(makeSvg('path', {
        id: dPathId,
        d: dPath,
        fill: 'none', stroke: 'none',
      }))
      const dTxt = makeSvg('text', {
        'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
        'font-weight': '700',
        'font-size': '11',
        fill: style.stroke,
        stroke: '#ffffff',
        'stroke-width': '3',
        'paint-order': 'stroke',
        'stroke-linejoin': 'round',
      })
      const dTp = makeSvg('textPath', {
        href: `#${dPathId}`, 'xlink:href': `#${dPathId}`,
        'text-anchor': 'middle', startOffset: '50%',
      })
      dTp.textContent = designatorOnly
      dTxt.appendChild(dTp)
      svg.appendChild(dTxt)
      if (registry) {
        registry.add({
          x: lx - arcPxD / 2, y: ly - 9, w: arcPxD, h: 14,
          _src: 'range-fan-designator',
        })
      }
    }
  }
}

// ---- Threat objective (filled red circle, per FM 1-02.2) ----

export function drawThreatObjective(map, svg, feature, registry) {
  const geom = feature.geometry
  if (!geom || !geom.coordinates) return

  // Threat objectives ship in two shapes per the SITEMP writer manifest
  // and the scenario_terrain push:
  //   - Polygon: writer-authored area-to-occupy (most common — every
  //     COA's objectives.polygon emits as Polygon per
  //     pytho-app/app/app/handlers/intel_agent.py
  //     _WRITER_GEOMETRY_MANIFEST['SITEMP']). Paint the polygon as a
  //     filled translucent red shape with a dark red outline + the
  //     "THR OBJ <name>" label centered inside. This is the IPB Step-3
  //     doctrinal treatment per ATP 2-01.3 Fig 6-3 — the threat
  //     objective is an AREA the enemy intends to seize / hold, drawn
  //     with its actual footprint, NOT a point glyph at the centroid.
  //     A centroid-only glyph silently throws away the area data and
  //     was the root of the "WHY ARENT YOU DRAWING THE POLYGON" bug.
  //   - Point: legacy / scenario_terrain shorthand (single MGRS).
  //     Paint the simplified doctrinal glyph (filled red circle) at
  //     that point.
  //
  // Either shape gets the same "THR OBJ <name>" label, anchored at
  // the centroid for polygon and at the point for point.
  // Strip every prefix the writer / scenario can legitimately emit before
  // we paint the doctrinal "THR OBJ <designation>" label. Without this the
  // backend's "THR OBJ HOLD Osula" name + drawer's "THR OBJ " prepend
  // double-stamped as "THR OBJ THR OBJ HOLD Osula". Old regex only matched
  // "THREAT" or bare "OBJ" — missed the "THR " abbreviation the SITEMP
  // writer emits per the prompt examples. Now matches THR / THREAT
  // (optional) + OBJ + whitespace, all case-insensitive.
  const designation = String(
    feature.properties.designation || feature.properties.name || '',
  ).replace(/^(?:THR(?:EAT)?\s+)?OBJ\s+/i, '').trim()
  const label = designation ? `THR OBJ ${designation}` : 'THR OBJ'
  const FILL = 'rgba(220,38,38,0.30)'
  const STROKE = '#7f1d1d'

  if (geom.type === 'Polygon') {
    const ring = geom.coordinates[0]
    if (!Array.isArray(ring) || ring.length < 3) return
    const projected = _saneScreenPts(map, ring).filter(p => p._sane)
    if (projected.length < 3) return
    const pathD = 'M ' + projected.map(p =>
      `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' L ') + ' Z'
    svg.appendChild(makeSvg('path', {
      d: pathD,
      fill: FILL,
      'fill-opacity': '1',
      stroke: STROKE,
      'stroke-width': '2.2',
      'stroke-linejoin': 'round',
      'stroke-linecap': 'round',
    }))
    if (label && registry) {
      const centroid = polyCentroid(geom)
      if (centroid) {
        const cpx = map.project(centroid)
        drawHaloedLabel(svg, cpx, label, {
          fontSize: 11,
          fill: STROKE,
          dy: 0,
          registry,
        })
      }
    }
    return
  }

  // Point fall-through: doctrinal point glyph (filled red circle)
  // anchored at the single coordinate.
  const c = _pointAnchor(geom)
  if (!c) return
  const px = map.project(c)
  const r = 14
  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: String(r + 2),
      fill: '#fff',
      opacity: '0.75',
    }),
  )
  svg.appendChild(
    makeSvg('circle', {
      cx: px.x.toFixed(1),
      cy: px.y.toFixed(1),
      r: String(r),
      fill: 'rgba(220,38,38,0.55)',
      stroke: STROKE,
      'stroke-width': '2.2',
    }),
  )
  if (registry) {
    drawHaloedLabel(svg, px, label, {
      fontSize: 11,
      fill: STROKE,
      dy: 0,
      registry,
    })
    registry.add({
      x: px.x - r,
      y: px.y - r,
      w: r * 2,
      h: r * 2,
      _src: 'threat-obj',
    })
  }
}

// ---- Point EA (red rectangle, per ATP 2-01.3 Fig 6-3) ----

export function drawPointEaHex(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  // Doctrinal EA per ATP 2-01.3 Fig 6-3 = red-outlined RECTANGLE labeled
  // "EAn" (same family as the NAI/TAI box, but red and red-text). Was a
  // hexagon — that's not in current FM 1-02.2. Rectangle reads as the
  // engagement area "box" the planner draws on the map.
  const halfW = 22
  const halfH = 12
  const box = makeSvg('rect', {
    x: (px.x - halfW).toFixed(1),
    y: (px.y - halfH).toFixed(1),
    width: String(halfW * 2),
    height: String(halfH * 2),
    fill: 'none',
    stroke: '#b91c1c',
    'stroke-width': '2.0',
  })
  svg.appendChild(box)
  // "EAn" centered inside the rectangle. Designation prefers a short
  // number / name (EA 1, EA Strike) over verbose alt names.
  const designation = String(
    feature.properties.designation || feature.properties.name || '',
  ).replace(/^EA\s*/i, '').trim()
  const inner = designation ? `EA${designation}` : 'EA'
  const tx = makeSvg('text', {
    x: px.x.toFixed(1),
    y: (px.y + 4).toFixed(1),
    'text-anchor': 'middle',
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '700',
    'font-size': '11',
    fill: '#b91c1c',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.5',
    'stroke-linejoin': 'round',
  })
  tx.textContent = inner
  svg.appendChild(tx)
  if (registry) {
    registry.add({
      x: px.x - halfW,
      y: px.y - halfH,
      w: halfW * 2,
      h: halfH * 2,
      _src: 'ea-rect',
    })
  }
}

// ---- ROZ label ----

export function drawRozLabel(map, svg, feature, registry) {
  const c = polyCentroid(feature.geometry)
  if (!c) return
  const px = map.project(c)
  const sub = String(feature.properties.subkind || 'ROZ').toUpperCase()
  let name = String(feature.properties.name || '')
  const nameUpper = name.toUpperCase()
  if (nameUpper.startsWith(sub + ' ')) name = name.slice(sub.length + 1)
  else if (nameUpper === sub) name = ''
  const lblText = name ? `${sub} ${name}` : sub
  drawHaloedLabel(svg, px, lblText, { fontSize: 11, registry })
}

// ---- Phase line label ----

export function drawPhaseLineLabel(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 1) return
  if (!registry) return
  // Banner-box H+N treatment per ATP 2-01.3 Fig 6-3 ("H+5", "H+6", "H+7"
  // boxes at the line start): when feature.properties.h_hour is set,
  // paint a black-filled rectangle with white text inside, at the line
  // start only. Falls back to the old "PL Name" plain-text dual-endpoint
  // treatment when h_hour is absent.
  const hHour = String(feature.properties.h_hour || '').trim()
  const fontSize = 10
  const startPx = map.project(coords[0])
  const endPx = map.project(coords[coords.length - 1])

  if (hHour) {
    // H+N banner: black rect with white sans-serif text per ATP 2-01.3
    // Fig 6-3. Doctrinal phase lines carry the label at BOTH endpoints
    // so the reader sees "H+12" no matter which end of the AO they
    // scan first.
    const textW = estimateTextBBox(hHour, fontSize, 0, 0, 'start').w
    const padX = 5
    const padY = 3
    const bannerW = textW + padX * 2
    const bannerH = fontSize + padY * 2
    const paintBannerAt = (anchorPx, growsRight) => {
      const bx = growsRight ? anchorPx.x - 2 : anchorPx.x - bannerW + 2
      const by = anchorPx.y - bannerH - 2
      const rect = { x: bx, y: by, w: bannerW, h: bannerH, _src: 'pl-banner' }
      if (!registry.insideCanvas(rect) || registry.anyOverlap(rect)) {
        const altRect = { x: bx, y: anchorPx.y + 2, w: bannerW, h: bannerH, _src: 'pl-banner' }
        if (registry.insideCanvas(altRect) && !registry.anyOverlap(altRect)) {
          rect.y = altRect.y
        } else if (!registry.insideCanvas(rect)) {
          return
        }
      }
      registry.add(rect)
      svg.appendChild(makeSvg('rect', {
        x: rect.x.toFixed(1),
        y: rect.y.toFixed(1),
        width: rect.w.toFixed(1),
        height: rect.h.toFixed(1),
        fill: '#000',
      }))
      svg.appendChild(Object.assign(makeSvg('text', {
        x: (rect.x + padX).toFixed(1),
        y: (rect.y + rect.h - padY - 1).toFixed(1),
        'text-anchor': 'start',
        'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
        'font-weight': '700',
        'font-size': String(fontSize),
        fill: '#fff',
      }), { textContent: hHour }))
    }
    // Phase lines often extend beyond the visible bbox (scenario
    // enemy_advance_lines run lon 24.5→28.2; SITEMP bbox is 25.5→28.0).
    // The raw projected x can be off-canvas left or right, which the
    // registry rejects. Clamp each endpoint to the canvas edge so the
    // banner sits at the visible end of the line, not off-screen.
    const canvasW = registry?.width
    const isStartLeft = startPx.x <= endPx.x
    const rawLeftPx  = isStartLeft ? startPx : endPx
    const rawRightPx = isStartLeft ? endPx   : startPx
    const leftCap = {
      x: typeof canvasW === 'number' ? Math.max(0, Math.min(canvasW, rawLeftPx.x)) : rawLeftPx.x,
      y: rawLeftPx.y,
    }
    const rightCap = {
      x: typeof canvasW === 'number' ? Math.max(0, Math.min(canvasW, rawRightPx.x)) : rawRightPx.x,
      y: rawRightPx.y,
    }
    paintBannerAt(leftCap, true)
    paintBannerAt(rightCap, false)
    return
  }

  // "PL <NAME>" at both endpoints, the text set ALONG the line (FM
  // 1-02.2 phase-line labeling — the designation follows the line, not
  // the screen axes). This primitive is for PHASE LINES ONLY; boundary
  // and FSCM line kinds have their own primitives/drawers.
  const text = 'PL ' + (feature.properties.name || '').replace(/^PL\s+/i, '')
  drawLineFollowingEndLabels(map, svg, coords, text, registry, { fontSize })
}

/**
 * Shared line-following end labels: the text sits just off each end of
 * the line, ROTATED to the end segment's screen bearing, offset to the
 * upper side so it reads along the graphic. Used by phase lines,
 * boundaries, and FSCM lines — their designation follows the line.
 */
function drawLineFollowingEndLabels(map, svg, coords, text, registry, opts) {
  const fontSize = (opts && opts.fontSize) || 10
  const paintAt = (endIdx, neighborIdx) => {
    const pEnd = map.project(coords[endIdx])
    const pIn = map.project(coords[neighborIdx])
    let dx = pEnd.x - pIn.x
    let dy = pEnd.y - pIn.y
    const len = Math.hypot(dx, dy) || 1
    dx /= len; dy /= len
    let angle = Math.atan2(dy, dx) * 180 / Math.PI
    // Never paint text upside-down: flip the run direction instead.
    let anchor = 'start'
    if (angle > 90 || angle < -90) {
      angle += 180
      anchor = 'end'
    }
    // Anchor just beyond the cap along the line, lifted to the upper
    // side (perpendicular offset) so the text rides the line.
    const off = 8
    const px = pEnd.x + dx * off - dy * 5
    const py = pEnd.y + dy * off + dx * 5
    // Collision registry works in axis-aligned boxes — register the
    // unrotated estimate at the anchor as an approximation.
    const r = estimateTextBBox(text, fontSize, px, py, anchor)
    if (registry) {
      if (!registry.insideCanvas(r)) return
      registry.add(r)
    }
    const t = makeSvg('text', {
      x: px.toFixed(1),
      y: py.toFixed(1),
      'text-anchor': anchor,
      transform: `rotate(${angle.toFixed(1)}, ${px.toFixed(1)}, ${py.toFixed(1)})`,
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '600',
      'font-size': String(fontSize),
      fill: '#000',
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '2.5',
      'stroke-linejoin': 'round',
    })
    t.textContent = text
    svg.appendChild(t)
  }
  paintAt(0, 1)
  paintAt(coords.length - 1, coords.length - 2)
}

// Echelon → boundary garnish marks per FM 1-02.2 (echelon amplifier on
// the boundary line names the echelon of the units it separates).
const BOUNDARY_ECHELON_MARKS = {
  COMPANY: 'I', TROOP: 'I', BATTERY: 'I',
  BATTALION: 'II', SQUADRON: 'II',
  REGIMENT: 'III', GROUP: 'III',
  BRIGADE: 'X',
  DIVISION: 'XX',
  CORPS: 'XXX',
  ARMY: 'XXXX',
}

/**
 * boundary — FM 1-02.2 figure 5-6 composition: the adjacent units'
 * designations (Field T) sit immediately ABOVE and BELOW the line at
 * its midpoint; the echelon amplifier (Field B, optional) BREAKS the
 * line at that same center; hostile boundaries carry "ENY" (Field N)
 * at both termini. MapLibre paints the line itself (kind-keyed graphics
 * layer); this drawer paints the amplifier text. All positions are
 * FIXED, derived from the geometry — no dynamic placement.
 *
 * Names of the form "A / B" split across the line (A one side, B the
 * other, geographically assigned when the tokens are cardinal sector
 * names); a single name paints above the line at midpoint.
 */
export function drawBoundary(map, svg, feature, registry, modifiers) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  const props = feature.properties || {}

  // Midpoint pose (point + upright angle + unit normal) by length walk.
  const pts = _saneScreenPts(map, coords).filter(p => p._sane)
  if (pts.length < 2) return
  const seglen = []
  let total = 0
  for (let i = 1; i < pts.length; i++) {
    const d = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)
    seglen.push(d)
    total += d
  }
  if (total < 1) return
  let want = total / 2
  let mi = 0
  for (; mi < seglen.length - 1 && want > seglen[mi]; mi++) want -= seglen[mi]
  const f = seglen[mi] ? want / seglen[mi] : 0
  const A = pts[mi]
  const B = pts[mi + 1]
  const mx = A.x + (B.x - A.x) * f
  const my = A.y + (B.y - A.y) * f
  let dx = (B.x - A.x) / (seglen[mi] || 1)
  let dy = (B.y - A.y) / (seglen[mi] || 1)
  let angle = Math.atan2(dy, dx) * 180 / Math.PI
  if (angle > 90 || angle < -90) {
    angle += 180
    dx = -dx
    dy = -dy
  }
  // Screen-space normal of the (upright) line direction: nUp points to
  // the visual "above" side of the text run.
  const nUpX = dy
  const nUpY = -dx

  const _text = (x, y, str, size, weight) => {
    const t = makeSvg('text', {
      x: x.toFixed(1),
      y: y.toFixed(1),
      'text-anchor': 'middle',
      transform: `rotate(${angle.toFixed(1)}, ${x.toFixed(1)}, ${y.toFixed(1)})`,
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': weight || '600',
      'font-size': String(size || 10),
      fill: '#000',
      'paint-order': 'stroke',
      stroke: '#fff',
      'stroke-width': '3.5',
      'stroke-linejoin': 'round',
    })
    t.textContent = str
    svg.appendChild(t)
  }

  // Anchors offset along the line's TRUE screen normal (nUp), then
  // rotated about themselves. The previous screen-vertical pre-
  // rotation lifts were NOT along the normal on diagonal lines — the
  // two designations sheared apart along the line and the lower one
  // sat ON the line. Baseline geometry: the above text's baseline
  // clears the line by ~5 px; the below text's cap-height clears it
  // on the other side.
  const liftAbove = 8
  const dropBelow = 16

  const name = String(props.name || '').trim()
  const parts = name.split('/').map(s => s.trim()).filter(Boolean)
  if (parts.length === 2) {
    // Two flanking designations, one each side of the line, in
    // DOCUMENT ORDER (first above, second below) — fig 5-6's layout is
    // the author's statement of which unit is which side. Never infer
    // sides from the names themselves: sector names are designations,
    // not compass positions relative to the line (the 2CR "SOUTH"
    // sector sits geographically northeast of this boundary, and a
    // cardinal-word heuristic inverted the labels).
    const [above, below] = parts
    _text(mx + nUpX * liftAbove, my + nUpY * liftAbove, above, 10, '700')
    _text(mx - nUpX * dropBelow, my - nUpY * dropBelow, below, 10, '700')
  } else if (name) {
    _text(mx + nUpX * liftAbove, my + nUpY * liftAbove, name, 10, '700')
  }

  // Echelon amplifier (OPTIONAL — paints only when the data states it;
  // doctrine gives no rule for inventing one) breaks the line at center.
  const echelon = String(
    (modifiers && modifiers.echelon) || props.echelon || '',
  ).trim().toUpperCase()
  const marks = BOUNDARY_ECHELON_MARKS[echelon]
  if (marks) {
    // White plate masks the line so the glyph visually BREAKS it.
    const plateW = marks.length * 9 + 8
    const plate = makeSvg('rect', {
      x: (mx - plateW / 2).toFixed(1),
      y: (my - 7).toFixed(1),
      width: String(plateW),
      height: '14',
      fill: '#fff',
      transform: `rotate(${angle.toFixed(1)}, ${mx.toFixed(1)}, ${my.toFixed(1)})`,
    })
    svg.appendChild(plate)
    _text(mx, my + 4, marks, 11, '700')
  }

  // Hostile boundaries: "ENY" at both termini (FM 1-02.2 fig 5-6
  // Field N; required when red is unavailable, correct with it).
  const side = String(props.side || props.affiliation || '').toLowerCase()
  if (side === 'hostile' || side === 'enemy') {
    drawLineFollowingEndLabels(map, svg, coords, 'ENY', registry, { fontSize: 10 })
  }
}

// FSCM line kind → doctrinal designator (the label prefix along the
// line). These are FIRES coordination measures, not phase lines.
const FSCM_LINE_DESIGNATORS = {
  coordinated_fire_line: 'CFL',
  fire_support_coordination_line: 'FSCL',
  no_fire_line: 'NFL',
  restrictive_fire_line: 'RFL',
  intelligence_coordination_line: 'ICL',
}

/**
 * fscm_line — CFL/FSCL/NFL/RFL and kin. MapLibre paints the line; the
 * designator + name follow the line at both ends (never "PL").
 */
export function drawFscmLine(map, svg, feature, registry) {
  const coords = (feature.geometry && feature.geometry.coordinates) || []
  if (coords.length < 2) return
  const kind = String(
    feature.properties.kind || feature.properties.entity_type || '')
  const sub = String(
    feature.properties.subkind || FSCM_LINE_DESIGNATORS[kind] || 'FSCM',
  ).toUpperCase()
  let name = String(feature.properties.name || '')
  const nameUpper = name.toUpperCase()
  if (nameUpper.startsWith(sub + ' ')) name = name.slice(sub.length + 1)
  else if (nameUpper === sub) name = ''
  const text = name ? `${sub} ${name}` : sub
  drawLineFollowingEndLabels(map, svg, coords, text, registry, { fontSize: 10 })
}

// ---- Control measure label (NAI/TAI/EA/OBJ adjacent text) ----

export function drawControlMeasureLabel(map, svg, feature, registry) {
  const geom = feature.geometry
  if (!geom || !geom.coordinates) return
  if (!registry) return
  let sx, sy, minX, minY, maxX, maxY
  if (geom.type === 'Point') {
    const p = map.project(geom.coordinates)
    const half = 32
    minX = p.x - half
    minY = p.y - half
    maxX = p.x + half
    maxY = p.y + half
    sx = p.x
    sy = p.y
  } else {
    const ring =
      geom.type === 'Polygon'
        ? geom.coordinates[0]
        : geom.type === 'MultiPolygon'
          ? geom.coordinates[0][0]
          : null
    if (!ring) return
    sx = 0
    sy = 0
    minX = Infinity
    minY = Infinity
    maxX = -Infinity
    maxY = -Infinity
    for (const c of ring) {
      const p = map.project(c)
      sx += p.x
      sy += p.y
      if (p.x < minX) minX = p.x
      if (p.y < minY) minY = p.y
      if (p.x > maxX) maxX = p.x
      if (p.y > maxY) maxY = p.y
    }
    sx /= ring.length
    sy /= ring.length
  }
  const tag =
    {
      named_area_of_interest: 'NAI',
      targeted_area_of_interest: 'TAI',
      engagement_area: 'EA',
      objective: 'OBJ',
    }[feature.properties.kind] || ''
  // Was 22pt — shrunk to 11pt to match the reference Army map graphic.
  // NAI/TAI/EA/OBJ adjacent text is a secondary label, not a hero label.
  const fontSize = 11
  let designation = feature.properties.designation || feature.properties.name || ''
  if (tag && designation.toUpperCase().startsWith(tag + ' ')) {
    designation = designation.slice(tag.length + 1)
  }
  const firstTok = designation.split(/\s+/)[0] || ''
  if (/^\d+/.test(firstTok)) designation = firstTok
  const text = (tag ? tag + ' ' : '') + designation
  const isPointCm = geom.type === 'Point'
  // For point CMs the box drawer already paints the tag INSIDE the box
  // (drawPointNaiBox), so skip the adjacent text — it doubles up.
  if (isPointCm) return
  const candidates = []
  candidates.push(
    { x: sx, y: minY - 6, anchor: 'middle' },
    { x: sx, y: maxY + fontSize + 4, anchor: 'middle' },
    { x: maxX + 6, y: sy + 3, anchor: 'start' },
    { x: minX - 6, y: sy + 3, anchor: 'end' },
    { x: minX + 6, y: minY - 6, anchor: 'start' },
    { x: maxX - 6, y: minY - 6, anchor: 'end' },
    { x: minX + 6, y: maxY + fontSize + 4, anchor: 'start' },
    { x: maxX - 6, y: maxY + fontSize + 4, anchor: 'end' },
  )
  const best = registry.findBest(text, fontSize, candidates)
  registry.add(best.rect)
  const t = makeSvg('text', {
    x: best.x.toFixed(1),
    y: best.y.toFixed(1),
    'text-anchor': best.anchor,
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '700',
    'font-size': String(fontSize),
    fill: '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.5',
    'stroke-linejoin': 'round',
  })
  t.textContent = text
  svg.appendChild(t)
}

// ---- Urban label ----

export function drawUrbanLabel(map, svg, feature, registry) {
  const geom = feature.geometry
  if (!geom || !geom.coordinates) return
  if (!registry) return
  const ring =
    geom.type === 'Polygon'
      ? geom.coordinates[0]
      : geom.type === 'MultiPolygon'
        ? geom.coordinates[0][0]
        : null
  if (!ring) return
  let sx = 0
  let sy = 0
  for (const c of ring) {
    const p = map.project(c)
    sx += p.x
    sy += p.y
  }
  sx /= ring.length
  sy /= ring.length
  const lblText = (feature.properties.name || '').toUpperCase()
  if (!lblText) return
  if (/^BUILTUP\s+\d+$/i.test(lblText)) return
  // Major place-name tier (RIGA, VALGA, TARTU): 13pt — still hierarchically
  // larger than the secondary 11pt designation labels, but no longer the
  // 24pt giant they were before.
  const fontSize = 13
  const candidates = [
    { x: sx, y: sy, anchor: 'middle' },
    { x: sx, y: sy - 18, anchor: 'middle' },
    { x: sx, y: sy + 18, anchor: 'middle' },
    { x: sx - 40, y: sy, anchor: 'end' },
    { x: sx + 40, y: sy, anchor: 'start' },
  ]
  const best = registry.findBest(lblText, fontSize, candidates)
  registry.add(best.rect)
  const t = makeSvg('text', {
    x: best.x.toFixed(1),
    y: best.y.toFixed(1),
    'text-anchor': best.anchor,
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '800',
    'font-size': String(fontSize),
    fill: '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '3',
    'stroke-linejoin': 'round',
  })
  t.textContent = lblText
  svg.appendChild(t)
}

// ---- Entity / target labels ----

export function drawEntityLabel(map, svg, feature, registry, opts) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  if (!registry) return
  const px = map.project(c)
  const label = (
    feature.properties.designation ||
    feature.properties.name ||
    ''
  ).trim()
  if (!label) return
  // Entity designation (towns, lakes, named terrain features that aren't
  // urban areas). 11pt to match the reference Army map graphic.
  // Compact gate is schema-driven via map.__renderConfig.compactLegendLabels
  // (from active product's `map_compact_legend_labels` field). No
  // product-type switch.
  const fontSize = 11
  const isCompact = map?.__renderConfig?.compactLegendLabels === true
  const ax = isCompact ? 22 : 30
  const diag = isCompact ? 18 : 24
  const candidates = [
    { x: px.x + ax, y: px.y + 4, anchor: 'start' },
    { x: px.x - ax, y: px.y + 4, anchor: 'end' },
    { x: px.x, y: px.y + ax + 4, anchor: 'middle' },
    { x: px.x, y: px.y - ax, anchor: 'middle' },
    { x: px.x + diag, y: px.y + ax, anchor: 'start' },
    { x: px.x - diag, y: px.y + ax, anchor: 'end' },
    { x: px.x + diag, y: px.y - (ax - 6), anchor: 'start' },
    { x: px.x - diag, y: px.y - (ax - 6), anchor: 'end' },
  ]
  const best = registry.findBest(label, fontSize, candidates)
  registry.add(best.rect)
  const t = makeSvg('text', {
    x: best.x.toFixed(1),
    y: best.y.toFixed(1),
    'text-anchor': best.anchor,
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '600',
    'font-size': String(fontSize),
    fill: '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.5',
    'stroke-linejoin': 'round',
  })
  t.textContent = label
  svg.appendChild(t)
}

export function drawTargetLabel(map, svg, feature, registry) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  if (!registry) return
  const px = map.project(c)
  const props = feature.properties || {}
  const designator = (props.designator || props.name || '').trim()
  const priority = Number(props.priority || 5)
  const status = String(props.status || '').toUpperCase()
  const isDefeated = status.includes('DEFEATED')
  const dotR = priority <= 1 ? 14 : priority <= 2 ? 10 : 7

  if (isDefeated) {
    const r = dotR + 2
    svg.appendChild(
      makeSvg('line', {
        x1: (px.x - r).toFixed(1),
        y1: (px.y - r).toFixed(1),
        x2: (px.x + r).toFixed(1),
        y2: (px.y + r).toFixed(1),
        stroke: '#7f1d1d',
        'stroke-width': '3',
        'stroke-linecap': 'round',
      }),
    )
  }
  if (!designator) return
  const fontSize = 11
  const off = dotR + 10
  const candidates = [
    { x: px.x + off, y: px.y + 4, anchor: 'start' },
    { x: px.x - off, y: px.y + 4, anchor: 'end' },
    { x: px.x, y: px.y - off, anchor: 'middle' },
    { x: px.x, y: px.y + off + 6, anchor: 'middle' },
    { x: px.x + off, y: px.y - off, anchor: 'start' },
    { x: px.x - off, y: px.y - off, anchor: 'end' },
    { x: px.x + off + 10, y: px.y + 4, anchor: 'start' },
    { x: px.x - off - 10, y: px.y + 4, anchor: 'end' },
  ]
  const best = registry.findBest(designator, fontSize, candidates)
  registry.add(best.rect)
  const t = makeSvg('text', {
    x: best.x.toFixed(1),
    y: best.y.toFixed(1),
    'text-anchor': best.anchor,
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '700',
    'font-size': String(fontSize),
    fill: isDefeated ? '#7f1d1d' : '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '2.5',
    'stroke-linejoin': 'round',
  })
  t.textContent = designator
  svg.appendChild(t)
}

// ---- Echelon roll-up (live analyst view) ----

// MIL-STD-2525 echelon ladder, lowest to highest. Each echelon appears
// under BOTH its short code and its full word (BN and BATTALION) because
// the live unit rows carry both spellings — different emit-site eras
// wrote different tokens. echelonRank() is a plain lookup of the ladder
// position for either spelling.
const ECHELON_RANK = {
  TM: 0, TEAM: 0, CREW: 0,
  SQD: 1, SQUAD: 1,
  SEC: 2, SECTION: 2,
  PLT: 3, PLATOON: 3, DET: 3, DETACHMENT: 3,
  CO: 4, COMPANY: 4, BATTERY: 4, BTRY: 4, TROOP: 4,
  BN: 5, BATTALION: 5, SQUADRON: 5,
  REGT: 6, REGIMENT: 6, GROUP: 6,
  BDE: 7, BRIGADE: 7,
  DIV: 8, DIVISION: 8,
  CORPS: 9,
  ARMY: 10,
}

export function echelonRank(echelon) {
  const r = ECHELON_RANK[String(echelon || '').trim().toUpperCase()]
  return (r === undefined) ? -1 : r
}

/**
 * TRUE OOB-hierarchy roll-up for the live analyst view. The slider is a
 * CLUSTERING GRANULARITY, never a filter (user ruling 2026-07-17):
 *
 *  - A unit AT or BELOW the tier is represented by the TOPMOST painted
 *    ancestor whose echelon is still at/below the tier — subordinates
 *    collapse INTO their real parent formation symbol (its own
 *    position, its own designation; no synthetic frames, no ×N
 *    badges — one brigade symbol is one brigade).
 *  - A unit ABOVE the tier (or off the ladder) DECOMPOSES: when any of
 *    its descendants paint, the aggregate symbol hides and the
 *    descendants carry its presence at the finer granularity. The
 *    formation's own CP presence is its command-post subordinate, not
 *    the aggregate icon.
 *  - A unit with no painted descendants ALWAYS paints, whatever its
 *    echelon — there is nothing finer to decompose into, and a view
 *    transform never hides data. Slider at max shows each unit at the
 *    highest AVAILABLE parent (a brigade with no division parent shows
 *    as the brigade); slider at min shows the finest available laydown.
 *
 * `tiers` is either one echelon token applied uniformly, or a
 * per-faction map {affiliation: echelon} (the Tactical Overlays
 * sidebar's per-faction sliders). A faction with no entry rolls
 * nothing up.
 *
 * Distinct from the render path's pixel clustering
 * (clusterMilUnits + map_cluster_mil_units) — this never runs in
 * headless/product renders.
 *
 * Returns a NEW feature array; representatives that absorbed members
 * carry isRollup (drag guard + placard affordance). No count badge.
 */
export function rollupByEchelon(features, tiers, exemptIds) {
  if (!Array.isArray(features) || !features.length) return features
  const uniformRank = (typeof tiers === 'string') ? echelonRank(tiers) : null
  const rankByFaction = (tiers && typeof tiers === 'object') ? tiers : null
  if (uniformRank === null && !rankByFaction) return features
  if (uniformRank !== null && uniformRank < 0) return features
  // Hover exemption: a unit the analyst is pointing at in a placard
  // paints AS ITSELF regardless of the tier (hovering a rolled-up
  // subordinate must SHOW it on the map, not just mark its
  // representative).
  const exempt = exemptIds && exemptIds.size ? exemptIds : null

  // A feature's tier rank comes from its own faction's slider (or the
  // uniform tier). rank < 0 = this faction never rolls up.
  const tierRankFor = (props) => (
    uniformRank !== null
      ? uniformRank
      : echelonRank(rankByFaction[props.affiliation])
  )

  const unitId = (p) => p.source_kbid || p.kg_id || p.id || null
  const parentId = (p) => p.parent || p.parent_kg_id || null

  const byUnitId = new Map()
  const paintedChildren = new Map()   // parent id → count of painted children
  for (const f of features) {
    const p = f.properties || {}
    const id = unitId(p)
    if (id) byUnitId.set(id, f)
  }
  for (const f of features) {
    const pid = parentId(f.properties || {})
    if (pid && byUnitId.has(pid)) {
      paintedChildren.set(pid, (paintedChildren.get(pid) || 0) + 1)
    }
  }

  // Topmost painted ancestor whose echelon ranks at/below the tier —
  // the highest AVAILABLE representation. Unranked ancestors (alliances,
  // aggregate rosters) are transparent pass-throughs. Cycle-guarded.
  const topmostEligibleAncestor = (props, tierRank) => {
    let current = props
    let best = null
    const visited = new Set()
    for (let hop = 0; hop < 20; hop++) {
      const pid = parentId(current)
      if (!pid || visited.has(pid)) break
      visited.add(pid)
      const parentFeature = byUnitId.get(pid)
      if (!parentFeature) break
      const parentProps = parentFeature.properties || {}
      const pRank = echelonRank(parentProps.echelon)
      if (pRank >= 0 && pRank <= tierRank) best = parentFeature
      current = parentProps
    }
    return best
  }

  const absorbedInto = new Map()      // representative id → [member ids]
  const out = []
  for (const f of features) {
    const props = f.properties || {}
    if (exempt && exempt.has(String(unitId(props)))) {
      out.push(f)                     // hover exemption — always itself
      continue
    }
    const tierRank = tierRankFor(props)
    if (tierRank < 0) { out.push(f); continue }   // faction not rolling
    const ownRank = echelonRank(props.echelon)
    if (ownRank >= 0 && ownRank <= tierRank) {
      // At/below the tier: collapse into the topmost eligible painted
      // ancestor; with none, the unit IS its own highest representation.
      const rep = topmostEligibleAncestor(props, tierRank)
      if (rep) {
        const rid = unitId(rep.properties || {})
        if (!absorbedInto.has(rid)) absorbedInto.set(rid, [])
        absorbedInto.get(rid).push(String(unitId(props)))
      } else out.push(f)
      continue
    }
    // Above the tier (or unranked): decompose when descendants paint;
    // paint as-is when there is nothing finer to show. EXCEPTION: a
    // formation whose symbol carries the HQ amplifier (SIDC 8th char
    // 2/6) is a COMMAND POST — a real element on the ground, not an
    // aggregate icon — and stays painted at every granularity
    // (headquarters is a separate thing; user ruling 2026-07-17).
    const sidc = String(props.sidc || '')
    const isHqSymbol = sidc.length >= 8 && (sidc[7] === '2' || sidc[7] === '6')
    if (paintedChildren.get(unitId(props)) && !isHqSymbol) continue
    out.push(f)
  }

  return out.map(f => {
    const props = f.properties || {}
    const members = absorbedInto.get(unitId(props))
    if (!members) return f
    // rollupMemberIds: placard hover on a rolled-up subordinate glows
    // the representative that absorbed it (the subordinate itself is
    // not painted at this tier).
    return { ...f, properties: { ...props, isRollup: true,
                                 rollupMemberIds: members } }
  })
}

// ---- Cluster (greedy single-zoom) + frame ----

/**
 * Cluster mil-unit point features by pixel distance, grouped by
 * affiliation+domain. Returns { clusters, singletons }.
 *
 * Matches render.html `clusterMilUnits` exactly.
 */
export function clusterMilUnits(map, features) {
  const buckets = {}
  const noSidc = []
  for (const f of features) {
    const sidc = f.properties && f.properties.sidc
    if (!sidc) {
      noSidc.push(f)
      continue
    }
    const affiliation = f.properties.affiliation || affiliationFromSidc(sidc)
    const domain = domainFromSidc(sidc)
    const key = `${affiliation}::${domain}`
    if (!buckets[key]) buckets[key] = { affiliation, domain, items: [] }
    const c = f.geometry.coordinates
    const px = map.project(c)
    buckets[key].items.push({ feature: f, px, lng: c[0], lat: c[1] })
  }

  const clusters = []
  const singletons = [...noSidc]

  for (const { affiliation, domain, items } of Object.values(buckets)) {
    if (items.length < CLUSTER_MIN_POINTS) {
      for (const it of items) singletons.push(it.feature)
      continue
    }
    const used = new Array(items.length).fill(false)
    for (let i = 0; i < items.length; i++) {
      if (used[i]) continue
      const seed = items[i]
      const members = [seed]
      used[i] = true
      let cx = seed.px.x
      let cy = seed.px.y
      for (let j = i + 1; j < items.length; j++) {
        if (used[j]) continue
        const dx = items[j].px.x - cx
        const dy = items[j].px.y - cy
        if (dx * dx + dy * dy <= CLUSTER_RADIUS_PX * CLUSTER_RADIUS_PX) {
          members.push(items[j])
          used[j] = true
          cx = (cx * (members.length - 1) + items[j].px.x) / members.length
          cy = (cy * (members.length - 1) + items[j].px.y) / members.length
        }
      }
      if (members.length >= CLUSTER_MIN_POINTS) {
        const meanLng = members.reduce((s, m) => s + m.lng, 0) / members.length
        const meanLat = members.reduce((s, m) => s + m.lat, 0) / members.length
        clusters.push({
          centroid: [meanLng, meanLat],
          affiliation,
          domain,
          count: members.length,
          members: members.map(m => m.feature),
        })
      } else {
        singletons.push(seed.feature)
      }
    }
  }
  return { clusters, singletons }
}

/**
 * Draw a doctrinal MIL-STD-2525D affiliation frame for a cluster.
 *
 * Frame shapes:
 *   Friend     → cyan rectangle
 *   Hostile    → red diamond
 *   Neutral    → green square
 *   Unknown    → yellow circle (quatrefoil approximation)
 *
 * Centered `×N` count, white halo casing outside the frame.
 */
export function drawClusterFrame(map, svg, cluster) {
  const c = cluster.centroid
  const px = map.project(c)
  const W = 110
  const H = 110
  const cx = px.x
  const cy = px.y

  let pathD = ''
  let haloD = ''
  let fill = '#cccccc'
  let stroke = '#333'

  switch (cluster.affiliation) {
    case 'Friend': {
      const w = W * 0.55
      const h = H * 0.4
      pathD =
        `M ${cx - w} ${cy - h} L ${cx + w} ${cy - h} ` +
        `L ${cx + w} ${cy + h} L ${cx - w} ${cy + h} Z`
      const hw = w + 6
      const hh = h + 6
      haloD =
        `M ${cx - hw} ${cy - hh} L ${cx + hw} ${cy - hh} ` +
        `L ${cx + hw} ${cy + hh} L ${cx - hw} ${cy + hh} Z`
      fill = '#80e0ff'
      stroke = '#003a66'
      break
    }
    case 'Hostile': {
      const a = W * 0.55
      const b = H * 0.55
      pathD =
        `M ${cx} ${cy - b} L ${cx + a} ${cy} ` +
        `L ${cx} ${cy + b} L ${cx - a} ${cy} Z`
      const ha = a + 8
      const hb = b + 8
      haloD =
        `M ${cx} ${cy - hb} L ${cx + ha} ${cy} ` +
        `L ${cx} ${cy + hb} L ${cx - ha} ${cy} Z`
      fill = '#ff9999'
      stroke = '#800000'
      break
    }
    case 'Neutral': {
      const s = W * 0.5
      pathD =
        `M ${cx - s} ${cy - s} L ${cx + s} ${cy - s} ` +
        `L ${cx + s} ${cy + s} L ${cx - s} ${cy + s} Z`
      const hs = s + 6
      haloD =
        `M ${cx - hs} ${cy - hs} L ${cx + hs} ${cy - hs} ` +
        `L ${cx + hs} ${cy + hs} L ${cx - hs} ${cy + hs} Z`
      fill = '#a8ffa8'
      stroke = '#006400'
      break
    }
    default: {
      const r = W * 0.5
      pathD =
        `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx} ${cy + r} A ${r} ${r} 0 1 1 ${cx} ${cy - r} Z`
      const hr = r + 6
      haloD =
        `M ${cx} ${cy - hr} A ${hr} ${hr} 0 1 1 ${cx} ${cy + hr} A ${hr} ${hr} 0 1 1 ${cx} ${cy - hr} Z`
      fill = '#ffe680'
      stroke = '#806600'
      break
    }
  }

  svg.appendChild(
    makeSvg('path', {
      d: haloD,
      fill: '#fff',
      stroke: 'none',
      opacity: '0.92',
    }),
  )
  svg.appendChild(
    makeSvg('path', {
      d: pathD,
      fill,
      stroke,
      'stroke-width': '4.5',
      'stroke-linejoin': 'round',
    }),
  )

  const cnt = makeSvg('text', {
    x: cx.toFixed(1),
    y: (cy + 6).toFixed(1),
    'text-anchor': 'middle',
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
    'font-weight': '900',
    'font-size': '14',
    fill: '#000',
    'paint-order': 'stroke',
    stroke: '#fff',
    'stroke-width': '3',
    'stroke-linejoin': 'round',
  })
  cnt.textContent = '×' + cluster.count
  svg.appendChild(cnt)
}

// ---- Orchestrator: paint every doctrinal SVG overlay from stashes ----

/**
 * Drive the full SVG overlay paint pass over the kind-segregated feature
 * stashes that `applyDoctrinalControlMeasures` attaches to the map.
 * Matches the orchestration block in render.html `injectMarginalia`
 * (~1977-2135). Reused by MCOO, SITEMP, Threat Overlay, GRINTSUM,
 * TMP, Threat COA Statement.
 *
 * Caller is responsible for clearing svg.innerHTML and resetting the
 * placement registry before re-invoking. Marginalia footprints should be
 * pre-seeded into the registry (via createSeededRegistry) so labels
 * don't land underneath the panels.
 */
// =============================================================================
// PRIMITIVE DISPATCH (per redesign doc §2.4)
// =============================================================================
//
// Tier order: 1 = polygons (paint first, bottom of z-stack); 2 = path/point
// primary geometry; 3 = strike-through decoration (needs primary bbox);
// 4 = mil units (always on top per ATP 2-01.3 / FM 6-99 focal-point rule).
const PAINT_TIER = {
  closed_polygon_with_label:      1,
  filled_corridor_with_arrowhead: 2,
  hollow_outline_arrow:           2,
  bowtie_bounded_polyline:        2,
  single_shaft_line:              2,
  phase_line:                     2,
  paired_aviation_rails:          2,
  bracket:                        2,
  radial:                         2,
  closed_glyph:                   2,
  marker_glyph:                   2,
  strike_through:                 3,
  supply_route:                   2,
  boundary:                       2,
  fscm_line:                      2,
  // Per-kind glyph primitives (each kind with its own doctrinal drawer
  // dispatches by its own primitive name, stamped by the catalog).
  range_fan:                      0,
  decision_point_glyph:           1,
  key_terrain_glyph:              3,
  choke_point_glyph:              3,
  strong_point_glyph:             3,
  threat_objective_glyph:         3,
  // Point-form primitives — the catalog resolves a Point-geometry
  // objective/NAI/TAI/EA/BP/AA/ROZ/urban to these at emit time.
  objective_point:                3,
  nai_point:                      3,
  tai_point:                      3,
  ea_point:                       3,
  battle_position_point:          4,
  assembly_area_point:            4,
  roz_point:                      4,
  urban_point:                    4,
  // Units paint LAST — the focal-point rule, as an INVARIANT.
  mil_unit:                       1000,
}

// EVERY key in PRIMITIVE_DRAWERS must have an explicit PAINT_TIER
// entry — registering a drawer without a tier is a bug (supply_route
// shipped that way and its untiered default floated the MSR line ON
// TOP of unit symbols). The fallback here is a loud console error and
// a tier BELOW units, never above.
function paintTierOf(primitive) {
  const t = PAINT_TIER[primitive]
  if (t !== undefined) return t
  console.error(
    `[tacticalGraphics] primitive "${primitive}" registered without a `
    + 'PAINT_TIER entry — add it to the table; painting it below units')
  return 50
}

// Side / affiliation color resolution per ATP 2-01.3 Table 4-4 +
// MIL-STD-2525E affiliation vocab.
function _resolveSideColor(feature, fallback) {
  const v = String(
    (feature.properties && (feature.properties.side || feature.properties.affiliation)) || 'neutral',
  ).toLowerCase()
  if (v === 'friendly' || v === 'friend' || v === 'blue') return '#0064c8'
  if (v === 'threat' || v === 'hostile' || v === 'red') return '#dc323c'
  return fallback || '#000000'
}

// Stub renderer: paint a 1-px dashed empty box at the feature's screen extent
// with the kind label centered. Used for primitives whose doctrinal paint
// is not yet implemented (bracket, radial mission-task variants, strike_through,
// the closed_glyph mission-task verbs occupy/retain/secure).
function _paintStubExtent(svg, map, feature, primitive) {
  const geom = feature.geometry
  if (!geom) return
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const visit = (coord) => {
    if (typeof coord[0] === 'number') {
      const p = map.project(coord)
      if (p.x < minX) minX = p.x; if (p.y < minY) minY = p.y
      if (p.x > maxX) maxX = p.x; if (p.y > maxY) maxY = p.y
    } else for (const c of coord) visit(c)
  }
  if (Array.isArray(geom.coordinates)) visit(geom.coordinates)
  if (!isFinite(minX)) return
  if (geom.type === 'Point') { minX -= 18; maxX += 18; minY -= 12; maxY += 12 }
  svg.appendChild(makeSvg('rect', {
    x: minX.toFixed(1), y: minY.toFixed(1),
    width: (maxX - minX).toFixed(1), height: (maxY - minY).toFixed(1),
    fill: 'none', stroke: '#000', 'stroke-width': '1', 'stroke-dasharray': '2,2',
  }))
  const t = makeSvg('text', {
    x: ((minX + maxX) / 2).toFixed(1), y: ((minY + maxY) / 2).toFixed(1),
    'text-anchor': 'middle', 'dominant-baseline': 'middle',
    'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif", 'font-size': '10',
    fill: '#000', 'paint-order': 'stroke', stroke: '#fff', 'stroke-width': '2',
  })
  t.textContent = feature.properties.kind || primitive
  svg.appendChild(t)
  if (!_paintStubExtent._warned) _paintStubExtent._warned = new Set()
  if (!_paintStubExtent._warned.has(primitive)) {
    // eslint-disable-next-line no-console
    console.warn(`[tactical-graphics] primitive '${primitive}' rendered as stub (kind='${feature.properties.kind}')`)
    _paintStubExtent._warned.add(primitive)
  }
}

// closed_polygon_with_label — polygon outline + optional fill + centroid label.
// Modifier bundle: {fill, stroke_color, stroke_pattern, stroke_width, fill_opacity, label_position}
function drawClosedPolygonWithLabel(map, svg, feature, registry, modifiers) {
  const geom = feature.geometry
  if (!geom || geom.type !== 'Polygon') return
  const ring = geom.coordinates[0]
  if (!ring || ring.length < 3) return
  const projected = _saneScreenPts(map, ring).filter(p => p._sane)
  if (projected.length < 3) return
  const path = 'M ' + projected.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' L ') + ' Z'
  const mods = modifiers || {}

  // Resolve fill: 'affiliation_translucent' → side color w/ opacity; '#RRGGBB' → literal; 'none' → no fill
  let fillColor = 'none'
  let fillOpacity = mods.fill_opacity != null ? mods.fill_opacity : 0.25
  if (typeof mods.fill === 'string' && mods.fill.startsWith('#')) {
    fillColor = mods.fill
  } else if (mods.fill === 'affiliation_translucent') {
    fillColor = _resolveSideColor(feature)
  }

  // Resolve stroke: literal '#RRGGBB' or affiliation-keyed
  const stroke = (typeof mods.stroke_color === 'string' && mods.stroke_color.startsWith('#'))
    ? mods.stroke_color
    : _resolveSideColor(feature)
  const strokeWidth = mods.stroke_width || 2
  const dashArray = mods.stroke_pattern === 'dashed' ? '6,4'
                    : mods.stroke_pattern === 'dotted' ? '2,3' : null

  const attrs = {
    d: path, fill: fillColor, 'fill-opacity': String(fillOpacity),
    stroke, 'stroke-width': String(strokeWidth),
    'stroke-linejoin': 'round', 'stroke-linecap': 'round',
  }
  if (dashArray) attrs['stroke-dasharray'] = dashArray
  svg.appendChild(makeSvg('path', attrs))

  if (registry) {
    const centroid = polyCentroid(geom)
    if (centroid) {
      const cpx = map.project(centroid)
      // No properties.id fallback — uuid labels are system internals.
      const lbl = feature.properties.name || feature.properties.designation || ''
      if (lbl) drawHaloedLabel(svg, cpx, String(lbl), { fontSize: 11, fill: stroke, registry })
    }
  }
}

// closed_glyph — point-anchored closed shape with letter / label, painted
// entirely from catalog modifiers (glyph_shape / fill / stroke_color /
// annotation). Kinds with their own doctrinal drawers dispatch by their
// own primitives (decision_point_glyph, key_terrain_glyph, ...) — no kind
// logic here.
function drawClosedGlyph(map, svg, feature, registry, modifiers) {
  _paintGenericClosedGlyph(map, svg, feature, modifiers || {})
}

function _paintGenericClosedGlyph(map, svg, feature, mods) {
  const c = _pointAnchor(feature.geometry)
  if (!c) return
  const px = map.project(c)
  const shape = mods.glyph_shape || 'circle'
  const fill = (typeof mods.fill === 'string' && mods.fill.startsWith('#')) ? mods.fill : 'none'
  const stroke = (typeof mods.stroke_color === 'string' && mods.stroke_color.startsWith('#'))
    ? mods.stroke_color : _resolveSideColor(feature)
  // No properties.id fallback — uuid labels are system internals.
  const ann = mods.annotation || feature.properties.name || feature.properties.designation || ''
  if (shape === 'diamond') {
    svg.appendChild(makeSvg('path', {
      d: `M ${px.x} ${px.y - 14} L ${px.x + 14} ${px.y} L ${px.x} ${px.y + 14} L ${px.x - 14} ${px.y} Z`,
      fill, stroke, 'stroke-width': '2',
    }))
  } else if (shape === 'oval') {
    svg.appendChild(makeSvg('ellipse', { cx: px.x.toFixed(1), cy: px.y.toFixed(1), rx: '20', ry: '11', fill, stroke, 'stroke-width': '2' }))
  } else if (shape === 'hexagon') {
    const r = 14
    const pts = []
    for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3 - Math.PI / 2; pts.push(`${(px.x + r * Math.cos(a)).toFixed(1)},${(px.y + r * Math.sin(a)).toFixed(1)}`) }
    svg.appendChild(makeSvg('polygon', { points: pts.join(' '), fill, stroke, 'stroke-width': '2' }))
  } else if (shape === 'kidney_ring') {
    svg.appendChild(makeSvg('circle', { cx: px.x.toFixed(1), cy: px.y.toFixed(1), r: '14', fill: 'none', stroke, 'stroke-width': '3' }))
  } else {
    // Default: circle
    svg.appendChild(makeSvg('circle', { cx: px.x.toFixed(1), cy: px.y.toFixed(1), r: '12', fill, stroke, 'stroke-width': '2' }))
  }
  if (ann) {
    const t = makeSvg('text', {
      x: px.x.toFixed(1), y: (px.y + 4).toFixed(1),
      'text-anchor': 'middle', 'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '700', 'font-size': '11', fill: stroke,
      'paint-order': 'stroke', stroke: '#fff', 'stroke-width': '2',
    })
    t.textContent = String(ann)
    svg.appendChild(t)
  }
}

// marker_glyph — non-closed line-art at point. Every marker_glyph kind
// (abatis, ferry, raft_site, bridges, fords, roadblocks, obstacle_point)
// is a subkind-keyed obstacle glyph; drawObstaclePoint reads the subkind
// off the feature. choke_point has its own primitive.
function drawMarkerGlyph(map, svg, feature, registry, modifiers) {
  drawObstaclePoint(map, svg, feature, registry)
}

// radial — arcs/rays for the mission-task variants (contain, screen,
// isolate, ...); stubs today. Range/detection rings dispatch by their
// own range_fan primitive.
function drawRadial(map, svg, feature, registry, modifiers) {
  _paintStubExtent(svg, map, feature, 'radial')
}

// bracket / strike_through — stubs (no existing implementations).
function drawBracket(map, svg, feature, registry, modifiers) {
  _paintStubExtent(svg, map, feature, 'bracket')
}
function drawStrikeThrough(map, svg, feature, registry, modifiers) {
  _paintStubExtent(svg, map, feature, 'strike_through')
}

// mil_unit — milsymbol icon + designation label; cluster representatives
// also paint the cluster frame + ×N badge.
function drawMilUnit(map, svg, feature, registry, modifiers) {
  const props = feature.properties || {}
  if (props.isCluster && props._cluster) {
    drawClusterFrame(map, svg, props._cluster)
    // Designation label to the right of the cluster frame, vertically
    // centered. Frame right-edge varies by affiliation (drawClusterFrame
    // uses W=110 and per-affiliation half-widths + halo padding). Use
    // the widest case (hostile diamond, a=W*0.55+halo=8 → 68.5) so the
    // label clears every affiliation without per-shape branching.
    const designation = String(props.designation || '').trim()
    // map.__hiddenUnitNameFactions (stashed by MapDoctrinalPaint) holds
    // the factions whose designation labels the legend hides — per-unit
    // gating by the feature's OWN affiliation. undefined/empty => show
    // (headless/embeds).
    if (designation && !(map.__hiddenUnitNameFactions
        && map.__hiddenUnitNameFactions.has(String(props.affiliation || '').toLowerCase()))) {
      const cx = map.project(feature.geometry.coordinates).x
      const cy = map.project(feature.geometry.coordinates).y
      const labelX = cx + 72
      const t = makeSvg('text', {
        x: labelX.toFixed(1),
        y: (cy + 3).toFixed(1),
        'text-anchor': 'start',
        'dominant-baseline': 'middle',
        'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
        'font-weight': '700', 'font-size': '10', fill: '#111827',
        'paint-order': 'stroke', stroke: '#ffffff', 'stroke-width': '2.5',
        'stroke-linejoin': 'round', 'pointer-events': 'none',
      })
      t.textContent = designation
      svg.appendChild(t)
    }
    return
  }
  _paintSingleMilUnit(map, svg, feature, registry)
}

function _paintSingleMilUnit(map, svg, feature, registry) {
  const props = feature.properties || {}
  const coords = _pointAnchor(feature.geometry)
  const sidc = props.sidc
  if (!coords || !sidc) return
  const heading = Number(props.heading) || 0
  const p = map.project(coords)
  // Selection halo: the analyst must be able to find the selected
  // unit in a sea of red — a bright ring + soft glow under the
  // symbol, keyed off the placard selection.
  const selId = map.__selectedUnitKgId
  if (selId && String(props.id || props.source_kbid || '') === String(selId)) {
    svg.appendChild(makeSvg('circle', {
      cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: '34',
      fill: '#fde047', 'fill-opacity': '0.25',
      stroke: 'none', 'pointer-events': 'none',
    }))
    svg.appendChild(makeSvg('circle', {
      cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: '30',
      fill: 'none', stroke: '#fde047', 'stroke-width': '3.5',
      opacity: '0.95', 'pointer-events': 'none',
    }))
  }
  const z = map.getZoom()
  let scale
  if (z <= 6) scale = 0.7
  else if (z <= 8) scale = 0.7 + (0.6 - 0.7) * (z - 6) / 2
  else if (z <= 10) scale = 0.6 + (0.55 - 0.6) * (z - 8) / 2
  else if (z <= 12) scale = 0.55 + (0.6 - 0.55) * (z - 10) / 2
  else if (z <= 14) scale = 0.6 + (0.7 - 0.6) * (z - 12) / 2
  else scale = 0.7
  const s = scale  // milsymbol returns the icon at size=40 native; we scale it directly

  // BDA-driven operational-condition modifier (FM 3-60 / MIL-STD-2525C).
  // cougaar_adapters._cougaar_to_mil_units stamps disposition →
  // attrs.posture (e.g. 'DESTROYED', 'DEGRADED'); symbols.createMilSymbol
  // applies it to SIDC position 3 so milsymbol renders the doctrinal
  // amplifier (red X for destroyed, status modifier for damaged, etc.).
  // current_activity / disposition / posture all flow into the same
  // attrs.posture field at the backend, so we read whichever survived.
  const disposition = (props.disposition || props.posture || props.unit_status || '').toString()
  // MAP-scoped milsymbol cache (the registry is recreated every
  // repaint, and zoom now repaints per FRAME — a per-registry cache
  // would regenerate every symbol SVG 60 times a second mid-gesture).
  if (!map.__milSymCache) map.__milSymCache = {}
  const cacheKey = `${sidc}|${heading}|${disposition.toUpperCase()}`
  let sym = map.__milSymCache[cacheKey]
  if (!sym) {
    try { sym = createMilSymbol(sidc, { size: 40, heading, disposition }) } catch { /* skip */ }
    if (!sym || !sym.svg) return
    map.__milSymCache[cacheKey] = sym
  }
  // The symbol FRAME is CENTERED on the unit's ground coordinate (user
  // ruling 2026-07-17: "center the fucking symbol"). milsymbol's
  // getAnchor() is the staff TIP for HQ symbols — anchoring there hung
  // the frame a staff-length off the point, and because symbol scale
  // varies with zoom, the frame drifted over DIFFERENT ground at every
  // zoom level. getOctagonAnchor() is the frame center: gluing THAT to
  // the projected coordinate keeps the symbol zoom-stable; the HQ
  // staff dangles below as decoration.
  const oa = sym.octagonAnchor || sym.anchor
  // Placard-hover unit highlight (hovering a subordinate row sets
  // map.__unitHighlight = {id}): soft glow plate behind the frame.
  // A hovered unit that is ROLLED UP at the current tier glows its
  // representative (the symbol that stands for it on the map).
  const matchesUnit = (id) => id != null
    && (String(props.id) === String(id)
        || (Array.isArray(props.rollupMemberIds)
            && props.rollupMemberIds.includes(String(id))))
  const isHovered = matchesUnit(map.__unitHighlight?.id)
  const isSelected = matchesUnit(map.__unitSelected?.id)
  let isLocked = false
  if (map.__unitVisibilityLocks) {
    for (const lockId of map.__unitVisibilityLocks) {
      if (matchesUnit(lockId)) { isLocked = true; break }
    }
  }
  if (isHovered || isSelected || isLocked) {
    // Glow plate behind the frame. Opaque enough to read over pale
    // basemap AND red/blue symbol fills (the old 0.45 wash vanished
    // against urban tint — user-flagged 2026-07-21).
    svg.appendChild(makeSvg('rect', {
      x: (p.x - 26 * s).toFixed(1),
      y: (p.y - 20 * s).toFixed(1),
      width: (52 * s).toFixed(1),
      height: (40 * s).toFixed(1),
      rx: '6',
      fill: '#fde047',
      opacity: isHovered && !isSelected && !isLocked ? '0.5' : '0.7',
    }))
  }
  if (isSelected || isLocked) {
    // Bold amber selection ring around the plate — the marker itself,
    // painted with its unit at the TOP of the symbol stack (the render
    // stream orders exempt units last).
    svg.appendChild(makeSvg('rect', {
      x: (p.x - 28 * s).toFixed(1),
      y: (p.y - 22 * s).toFixed(1),
      width: (56 * s).toFixed(1),
      height: (44 * s).toFixed(1),
      rx: '8',
      fill: 'none',
      stroke: '#f59e0b',
      'stroke-width': '3',
      opacity: '0.95',
    }))
  }
  const wrap = makeSvg('g', {
    transform:
      `translate(${(p.x - oa.x * s).toFixed(1)}, ${(p.y - oa.y * s).toFixed(1)}) ` +
      `scale(${s.toFixed(3)})`,
    'pointer-events': 'none',
  })
  wrap.innerHTML = sym.svg
  svg.appendChild(wrap)

  // Register the FRAME's screen box for click/drag hit-testing — the
  // authoritative targets (useMapEvents checks them before the anchor
  // circle layer). The box is the frame octagon's extent, NOT the full
  // milsymbol SVG bbox: the bbox includes echelon-amplifier padding on
  // every side and overlapped neighboring symbols so badly that
  // clicking one unit's center selected the unit NEXT to it.
  if (map.__milUnitHitBoxes) {
    const frameW = 36 * s
    const frameH = 26 * s
    map.__milUnitHitBoxes.push({
      x: p.x - frameW / 2,
      y: p.y - frameH / 2,
      w: frameW,
      h: frameH,
      cx: p.x,
      cy: p.y,
      feature,
    })
  }

  // Designation label: directly to the right of the icon's right edge,
  // vertically centered on the frame center (= the ground coordinate).
  const designation = (feature.properties && feature.properties.designation) || ''
  // map.__hiddenUnitNameFactions (stashed by MapDoctrinalPaint) holds
  // the factions whose designation labels the legend hides — per-unit
  // gating by the feature's OWN affiliation. undefined/empty => show
  // (headless/embeds).
  const _nameAff = String((feature.properties && feature.properties.affiliation) || '').toLowerCase()
  if (designation && !(map.__hiddenUnitNameFactions
      && map.__hiddenUnitNameFactions.has(_nameAff))) {
    const labelX = p.x + (sym.size.width - oa.x) * s + 6
    const labelY = p.y
    const t = makeSvg('text', {
      x: labelX.toFixed(1),
      y: labelY.toFixed(1),
      'text-anchor': 'start',
      'dominant-baseline': 'central',
      'font-family': "Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', sans-serif",
      'font-weight': '700', 'font-size': '10', fill: '#111827',
      'paint-order': 'stroke', stroke: '#ffffff', 'stroke-width': '2.5',
      'stroke-linejoin': 'round', 'pointer-events': 'none',
    })
    t.textContent = designation
    svg.appendChild(t)
  }
}

// Primitive name → drawer function. Wraps existing drawers as primitive
// targets. New drawers (drawClosedPolygonWithLabel, drawBracket, etc.) are
// defined above.
// The dispatch table IS the whole client-side contract: the backend
// catalog (constants/overlays.py) stamps THE primitive for each
// feature's kind AND geometry class, so no kind logic and no geometry
// heuristics live here.
const PRIMITIVE_DRAWERS = {
  filled_corridor_with_arrowhead: (m, s, f, r) => drawAxisOfAdvance(m, s, f, r),
  hollow_outline_arrow:           (m, s, f, r) => drawAvenueChevron(m, s, f, r),
  bowtie_bounded_polyline:        (m, s, f, r) => drawMobilityCorridor(m, s, f, r),
  single_shaft_line:              (m, s, f, r) => drawDirectionOfAttack(m, s, f, r),
  supply_route:                   (m, s, f, r) => drawSupplyRoute(m, s, f, r),
  phase_line:                     (m, s, f, r) => drawPhaseLineLabel(m, s, f, r),
  // Composites: the kind's line drawer AND its label in ONE registered
  // drawer — labels are part of the kind, never a second dispatch pass.
  boundary:                       (m, s, f, r, mods) => { drawBoundary(m, s, f, r, mods); drawBoundaryLabel(m, s, f, r) },
  fscm_line:                      (m, s, f, r) => { drawFscmLine(m, s, f, r); drawFscmLabel(m, s, f, r) },
  // Per-kind glyph primitives.
  range_fan:                      (m, s, f, r) => drawRangeFan(m, s, f, r),
  decision_point_glyph:           (m, s, f, r) => drawDecisionPoint(m, s, f, r),
  key_terrain_glyph:              (m, s, f, r) => drawKeyTerrain(m, s, f, r),
  choke_point_glyph:              (m, s, f, r) => drawChokePoint(m, s, f, r),
  strong_point_glyph:             (m, s, f, r) => drawStrongPoint(m, s, f, r),
  threat_objective_glyph:         (m, s, f, r) => drawThreatObjective(m, s, f, r),
  // Point-form primitives (geometry-class resolved by the catalog).
  // objective_point branches on affiliation — a styling decision inside
  // ONE kind's drawer, not routing (hostile objectives fill red).
  objective_point:                (m, s, f, r) => {
    const aff = String((f.properties && (f.properties.affiliation || f.properties.side)) || '').toLowerCase()
    if (aff === 'hostile') drawThreatObjective(m, s, f, r)
    else drawPointObjKidney(m, s, f, r)
  },
  nai_point:                      (m, s, f, r) => drawPointNaiBox(m, s, f, r, false),
  tai_point:                      (m, s, f, r) => drawPointNaiBox(m, s, f, r, true),
  ea_point:                       (m, s, f, r) => drawPointEaHex(m, s, f, r),
  battle_position_point:          (m, s, f, r) => drawBattlePositionLabel(m, s, f, r),
  assembly_area_point:            (m, s, f, r) => drawAssemblyAreaLabel(m, s, f, r),
  roz_point:                      (m, s, f, r) => drawRozLabel(m, s, f, r),
  urban_point:                    (m, s, f, r) => {
    const nm = (f.properties && f.properties.name) || ''
    if (!/^builtup\s+\d+$/i.test(nm)) drawUrbanLabel(m, s, f, r)
  },
  paired_aviation_rails:          (m, s, f, r) => drawAirCorridor(m, s, f, r),
  closed_polygon_with_label:      drawClosedPolygonWithLabel,
  bracket:                        drawBracket,
  radial:                         drawRadial,
  closed_glyph:                   drawClosedGlyph,
  marker_glyph:                   drawMarkerGlyph,
  strike_through:                 drawStrikeThrough,
  mil_unit:                       drawMilUnit,
}

function _getOverlayFeatureCollection(map) {
  const src = map.getSource && map.getSource('tactical-graphics')
  const data = src && src._data
  return (data && Array.isArray(data.features)) ? data.features : []
}
// Mil-unit stream — single source of truth for mil-unit features that
// reach paintTacticalGraphics's PRIMITIVE_DRAWERS dispatch. Reads the
// `mil-units` source, applies the active product's doctrinal filters
// (SITEMP = hostile-only per ATP 2-01.3 Fig 6-3), respects the schema's
// `map_cluster_mil_units` gate, and stamps `primitive: 'mil_unit'` on
// every feature so the dispatch routes it to drawMilUnit. Designation
// label is derived from SIDC+echelon when the data carries no name
// (live OOB rows often arrive without a designation).
function _getMilUnitStream(map, opts) {
  const src = map.getSource && map.getSource('mil-units')
  const data = src && src._data
  let features = (data && Array.isArray(data.features)) ? data.features : []
  if (!features.length) return []

  const productType = String(opts?.productType || '').toUpperCase()
  const renderConfig = map.__renderConfig || null

  // SITEMP doctrine (ATP 2-01.3 Fig 6-3): show ONLY enemy units; the
  // friendly side appears as friendly graphics (EAs, OBJs, DPs, PLs),
  // not unit icons. SIDC[1] = 'H' / '6' = Hostile; 'F' / '3' = Friend.
  if (productType === 'SITEMP') {
    features = features.filter(f => {
      const p = f.properties || {}
      const aff = String(p.affiliation || '').toLowerCase()
      if (aff === 'hostile' || aff === 'enemy' || aff === 'threat' || aff === 'opfor') return true
      if (aff === 'friend' || aff === 'friendly' || aff === 'blufor') return false
      const sidc = String(p.sidc || '')
      const c = sidc.length > 1 ? sidc[1].toUpperCase() : ''
      return c === 'H' || c === '6'
    })
  }

  // Derive a display label when the OOB row carries none. Live OOB rows
  // arrive with only SIDC + echelon; derive a "INF BDE" / "ARTY DIV" /
  // etc. label from SIDC function code (pos 6/7) + echelon so the analyst
  // sees something readable next to each icon.
  const _shortType = (sidc) => {
    if (!sidc || sidc.length < 7) return ''
    const c6 = sidc[6], c7 = sidc[7]
    if (c6 === 'I') return 'INF'
    if (c6 === 'A') return c7 === 'T' ? 'ARMR' : c7 === 'A' ? 'AT' : 'ARMR'
    if (c6 === 'F') return 'ARTY'
    if (c6 === 'D') return c7 === 'M' ? 'MIN' : 'ENG'
    if (c6 === 'C') return 'CAV'
    if (c6 === 'N') return 'ADA'
    if (c6 === 'S') return 'SVC'
    return ''
  }
  const _displayLabel = (props) => {
    // A roll-up representative is ONE real formation — its own symbol,
    // its own designation, no ×N multiplier (a brigade that absorbed
    // its battalions is still one brigade, not eight). Member detail
    // lives in the placard's subordinate tree.
    const explicit = String(
      props.designation || props.unit_short_name || props.name || ''
    ).trim()
    if (explicit) return explicit
    const echelon = String(props.echelon || '').toUpperCase()
    const type = _shortType(String(props.sidc || ''))
    if (type && echelon) return `${type} ${echelon}`
    return type || echelon || ''
  }

  // Schema-driven cluster gate. SITEMP / Threat Overlay / Threat COA
  // Statement show every templated threat unit individually
  // (`map_cluster_mil_units: False`); MCOO clusters for readability.
  // Analyst-edit mode (no renderConfig) defaults to non-clustered so
  // individual units are clickable.
  const shouldCluster = renderConfig
    ? renderConfig.clusterUnits === true
    : false

  const out = []
  if (!shouldCluster) {
    for (const f of features) {
      const props = f.properties || {}
      out.push({
        ...f,
        properties: {
          ...props,
          primitive: 'mil_unit',
          designation: _displayLabel(props),
          isCluster: false,
        },
      })
    }
    return out
  }

  const { clusters, singletons } = clusterMilUnits(map, features)
  for (const sf of singletons) {
    const props = sf.properties || {}
    out.push({
      ...sf,
      properties: {
        ...props,
        primitive: 'mil_unit',
        designation: _displayLabel(props),
        isCluster: false,
      },
    })
  }
  for (const cl of clusters) {
    const protoProps = (cl.members && cl.members[0] && cl.members[0].properties) || {}
    out.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: cl.centroid },
      properties: {
        ...protoProps,
        kind: 'mil_unit_cluster',
        primitive: 'mil_unit',
        isCluster: true,
        clusterCount: cl.count,
        designation: _displayLabel(protoProps),
        _cluster: cl,
      },
    })
  }
  return out
}

export function paintTacticalGraphics(map, svg, registry, opts) {
  // PHASE 1 — primitive-based dispatch. Overlay features are stamped with
  // `primitive` by the backend (geo-agent map_state.py + overlays.py);
  // mil-units are stamped client-side by _getMilUnitStream which applies
  // the per-product hostile-only filter (SITEMP) and the `clusterUnits`
  // schema gate. Both sets flow through the SAME PRIMITIVE_DRAWERS table,
  // so mil_unit icons paint identically to every other tactical graphic.
  const overlays = _getOverlayFeatureCollection(map)
  const milUnits = _getMilUnitStream(map, opts)
  const allFeatures = overlays.concat(milUnits)

  // Fresh per-paint hit-target boxes for unit symbols — drawMilUnit
  // pushes the exact screen box of every frame it draws; useMapEvents
  // hit-tests these before the anchor-centered MapLibre circle layer.
  map.__milUnitHitBoxes = []
  map.__rangeRingHits = []

  // Pre-register decision-point + battle-position bboxes so subsequent
  // labels avoid them (placement-collision registry).
  //
  // Decision points arrive as Polygon (AOI footprint) from the SITEMP / IPB
  // writer manifest; legacy scenario shorthand emits Point. Either shape
  // collapses to a single anchor via _pointAnchor. Reading
  // f.geometry.coordinates directly on a Polygon yields `[[[lng,lat],...]]`
  // — passing that to map.project throws LngLatLike and halts ALL
  // subsequent paint in this function (the symptom that wiped 100+ unit
  // icons + AAs + axes off the SITEMP renders).
  for (const f of overlays) {
    const k = f.properties && f.properties.kind
    if (k === 'decision_point') {
      const c = _pointAnchor(f.geometry)
      if (c) {
        const p = map.project(c)
        registry.add({ x: p.x - 28, y: p.y - 28, w: 56, h: 56, _src: 'decision-point' })
      }
    } else if (k === 'battle_position') {
      const ring = f.geometry && f.geometry.type === 'Polygon' && f.geometry.coordinates[0]
      if (ring) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
        for (const c of ring) {
          const p = map.project(c)
          if (p.x < minX) minX = p.x; if (p.y < minY) minY = p.y
          if (p.x > maxX) maxX = p.x; if (p.y > maxY) maxY = p.y
        }
        registry.add({ x: minX - 6, y: minY - 6, w: maxX - minX + 12, h: maxY - minY + 12, _src: 'battle-position' })
      }
    }
  }

  // Sort all primitive-stamped features by paint tier. mil_unit lives in
  // the last tier so unit icons sit on top of every other graphic (FM 6-99
  // / ATP 2-01.3 focal-point rule — the unit symbol must never be obscured
  // by axis chevrons, OBJ kidneys, EA fills, or phase lines).
  const primitiveFeatures = allFeatures.filter(f => f.properties && f.properties.primitive)
  primitiveFeatures.sort((a, b) => (
    paintTierOf(a.properties.primitive) - paintTierOf(b.properties.primitive)
  ))

  // Dumb dispatch: the stamped primitive IS the geometry-class-correct
  // drawer (the catalog resolved it at emit time). The only client-side
  // guard is null geometry — data can be null, and a null coordinate
  // inside map.project throws in the render loop and kills map
  // interaction.
  for (const f of primitiveFeatures) {
    const drawer = PRIMITIVE_DRAWERS[f.properties.primitive]
    if (!drawer) continue
    if (!f.geometry || f.geometry.coordinates == null) continue
    drawer(map, svg, f, registry, f.properties.modifiers || {})
  }

}


