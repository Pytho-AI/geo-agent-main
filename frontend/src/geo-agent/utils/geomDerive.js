/**
 * Doctrinal geometry derivation (FM 1-02.2 / MIL-STD 2525E).
 *
 * Reused by every product whose stored geometry differs from the
 * rendered polygon (AA chevrons, point-glyph OBJ kidney / EA hex / NAI /
 * TAI). MCOO, SITEMP, Threat Overlay, GRINTSUM, TMP, Threat COA Statement.
 *
 * For doctrinal shapes whose visible polygon is NOT what the analyst stores
 * — the analyst edits a centerline / control points / centroid, and the
 * displayed shape is derived from that — this module computes the rendered
 * vertices in geographic (lng/lat) space so MapLibre can paint them as
 * native polygons.
 *
 * Doctrinal kinds with derivation:
 *
 *   avenue_of_approach   stored as LineString centerline + width_class;
 *                         derived to a smoothed catmull-rom-offset polygon
 *                         with arrowhead and open rear (chevron).
 *   mobility_corridor    stored as LineString centerline + width_class;
 *                         rendered as line layers with line-offset for the
 *                         BN/BDE double-arrow case (no polygon derivation
 *                         required — MapLibre's line-offset handles it).
 *   objective (Point)    stored as Point centroid + size; derived to a
 *                         kidney-shaped polygon centered on the point.
 *   engagement_area      stored as Point centroid + size; derived to a
 *                         regular hexagon.
 *   named_area_of_interest / targeted_area_of_interest (Point)
 *                         stored as Point centroid + size; derived to a
 *                         square.
 *   direction_of_attack  stored as LineString; arrowhead derived as an
 *                         additional Point feature for symbol layer.
 *
 * Why pre-derived polygons rather than runtime SVG paint? Because once the
 * polygon lives in a MapLibre source, the analyst can click any vertex /
 * edge to select the feature. SVG overlays paint a screen-space silhouette
 * that the analyst can SEE but cannot CLICK; the underlying feature is
 * unreachable.
 *
 * When the analyst drags the centerline control points or resizes a glyph,
 * the source feature's stored geometry is updated (centerline / centroid)
 * and the derived polygon is recomputed via this module. The displayed
 * polygon is therefore always a function of the editable source.
 */

// ---- Catmull-Rom helpers (ported from tacticalGraphics.svg.js) ----

/**
 * Densely sample a centripetal Catmull-Rom spline through a polyline of
 * {x,y} points. Returns samples with unit tangent + perp + arclength t.
 */
function catmullRomSample(pts, samplesPerSegment, tension) {
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
  return samples
}

// ---- Width-class → kilometres lookup ----

function widthKmFromClass(sizeStr) {
  const s = String(sizeStr || '').toLowerCase()
  if (s.includes('div') || s.includes('division')) return 30
  if (s.includes('bde') || s.includes('brigade')) return 13
  if (s.includes('bn') || s.includes('battalion')) return 7
  if (s.includes('co') || s.includes('company')) return 3.5
  return 2.0
}

// ---- AA chevron polygon (closed) in geographic coordinates ----

/**
 * Build the closed AA chevron polygon as a GeoJSON ring of [lng, lat]
 * coordinates. The chevron is symmetric about the centerline, smoothed via
 * catmull-rom, with an arrowhead at the last sample and the rear left open
 * to match doctrine (TC 2-50.5 fig 3-15-style avenue-of-approach symbol).
 *
 * @param {Array<[number, number]>} centerline - LngLat polyline.
 * @param {string} sizeClass - Unit-size keyword (div, bde, bn, co, plt).
 * @returns {Array<[number, number]>|null} closed ring (lng/lat), or null if too few points.
 */
export function deriveAaChevronRing(centerline, sizeClass) {
  if (!centerline || centerline.length < 2) return null
  // Operate in a local equirectangular projection (km from start) so widths
  // can be expressed in kilometres. Convert back to lng/lat at the end.
  const lat0 = centerline[0][1]
  const cosLat = Math.cos((lat0 * Math.PI) / 180)
  const kmPerDegLat = 111.32
  const kmPerDegLng = 111.32 * cosLat
  const toLocal = ([lng, lat]) => ({
    x: (lng - centerline[0][0]) * kmPerDegLng,
    y: (lat - lat0) * kmPerDegLat,
  })
  const toLngLat = p => [
    centerline[0][0] + p.x / kmPerDegLng,
    lat0 + p.y / kmPerDegLat,
  ]

  const localPts = centerline.map(toLocal)
  const widthKm = widthKmFromClass(sizeClass)
  const halfW = widthKm / 2

  const sampled = catmullRomSample(localPts, 24, 0.4)
  if (sampled.length < 2) return null
  const left = []
  const right = []
  for (const s of sampled) {
    left.push({ x: s.x + s.nx * halfW, y: s.y + s.ny * halfW })
    right.push({ x: s.x - s.nx * halfW, y: s.y - s.ny * halfW })
  }

  // Arrowhead at the tip end.
  const tipSample = sampled[sampled.length - 1]
  const tipReach = widthKm * 1.05
  const tip = {
    x: tipSample.x + tipSample.tx * tipReach,
    y: tipSample.y + tipSample.ty * tipReach,
  }
  const headW = halfW * 1.55
  const headShoulderL = {
    x: tipSample.x + tipSample.nx * headW,
    y: tipSample.y + tipSample.ny * headW,
  }
  const headShoulderR = {
    x: tipSample.x - tipSample.nx * headW,
    y: tipSample.y - tipSample.ny * headW,
  }

  // The body polygon: trace down the left rail (minus the last sample
  // because the tip shoulder replaces it), out to the head shoulder, in to
  // the tip, out to the right head shoulder, down the right rail in reverse.
  const ring = []
  for (let i = 0; i < left.length - 1; i++) ring.push(toLngLat(left[i]))
  ring.push(toLngLat(headShoulderL))
  ring.push(toLngLat(tip))
  ring.push(toLngLat(headShoulderR))
  for (let i = right.length - 2; i >= 0; i--) ring.push(toLngLat(right[i]))
  ring.push(ring[0]) // closed
  return ring
}

// ---- OBJ kidney polygon ----

/**
 * Build a closed kidney-shaped polygon ring centred on `center` (lng/lat).
 *
 * The kidney is rendered as a series of catmull-rom-sampled bezier vertices
 * matching the SVG drawer's appearance. Width/height in metres are chosen
 * so the shape is visible at typical MCOO product zoom.
 *
 * @param {[number, number]} center - LngLat of the OBJ centroid.
 * @param {number} [widthM] - Width in metres (default 6000).
 * @param {number} [heightM] - Height in metres (default 3600).
 * @returns {Array<[number, number]>} closed ring (lng/lat).
 */
export function deriveObjKidneyRing(center, widthM = 6000, heightM = 3600) {
  const [lng, lat] = center
  const kmPerDegLng = 111.32 * Math.cos((lat * Math.PI) / 180)
  const kmPerDegLat = 111.32
  const w = widthM / 1000 // km
  const h = heightM / 1000 // km
  // Bezier control points relative to centre (matches tacticalGraphics.svg.js
  // drawPointObjKidney path, scaled by the geographic conversion).
  // We sample each of the four cubic-bezier arcs into 24 segments to get a
  // smooth polygon ring.
  const bezSegments = [
    [
      { x: -w * 0.4, y: -h * 0.35 },
      { x: -w * 0.15, y: -h * 0.55 },
      { x: w * 0.15, y: -h * 0.55 },
      { x: w * 0.4, y: -h * 0.35 },
    ],
    [
      { x: w * 0.4, y: -h * 0.35 },
      { x: w * 0.55, y: -h * 0.1 },
      { x: w * 0.55, y: h * 0.1 },
      { x: w * 0.4, y: h * 0.35 },
    ],
    [
      { x: w * 0.4, y: h * 0.35 },
      { x: w * 0.15, y: h * 0.05 },
      { x: -w * 0.15, y: h * 0.05 },
      { x: -w * 0.4, y: h * 0.35 },
    ],
    [
      { x: -w * 0.4, y: h * 0.35 },
      { x: -w * 0.55, y: h * 0.1 },
      { x: -w * 0.55, y: -h * 0.1 },
      { x: -w * 0.4, y: -h * 0.35 },
    ],
  ]
  const N = 24
  const ring = []
  for (const [p0, c1, c2, p3] of bezSegments) {
    for (let i = 0; i < N; i++) {
      const t = i / N
      const mt = 1 - t
      const x =
        mt * mt * mt * p0.x +
        3 * mt * mt * t * c1.x +
        3 * mt * t * t * c2.x +
        t * t * t * p3.x
      const y =
        mt * mt * mt * p0.y +
        3 * mt * mt * t * c1.y +
        3 * mt * t * t * c2.y +
        t * t * t * p3.y
      ring.push([lng + x / kmPerDegLng, lat + y / kmPerDegLat])
    }
  }
  ring.push(ring[0])
  return ring
}

// ---- EA hexagon ----

/**
 * Build a regular flat-top hexagon ring centred on `center`.
 *
 * @param {[number, number]} center - LngLat.
 * @param {number} [radiusM] - Outer radius in metres (default 3200).
 * @returns {Array<[number, number]>} closed ring.
 */
export function deriveEaHexRing(center, radiusM = 3200) {
  const [lng, lat] = center
  const kmPerDegLng = 111.32 * Math.cos((lat * Math.PI) / 180)
  const kmPerDegLat = 111.32
  const r = radiusM / 1000
  const ring = []
  for (let i = 0; i < 6; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 3
    ring.push([
      lng + (r * Math.cos(a)) / kmPerDegLng,
      lat + (r * Math.sin(a)) / kmPerDegLat,
    ])
  }
  ring.push(ring[0])
  return ring
}

// ---- NAI / TAI square ----

/**
 * Build an axis-aligned square ring centred on `center`.
 *
 * @param {[number, number]} center
 * @param {number} [sideM]
 * @returns {Array<[number, number]>} closed ring.
 */
export function deriveNaiSquareRing(center, sideM = 3600) {
  const [lng, lat] = center
  const kmPerDegLng = 111.32 * Math.cos((lat * Math.PI) / 180)
  const kmPerDegLat = 111.32
  const half = sideM / 2 / 1000
  const dlng = half / kmPerDegLng
  const dlat = half / kmPerDegLat
  return [
    [lng - dlng, lat - dlat],
    [lng + dlng, lat - dlat],
    [lng + dlng, lat + dlat],
    [lng - dlng, lat + dlat],
    [lng - dlng, lat - dlat],
  ]
}

// ---- Direction-of-attack arrowhead point ----

/**
 * Return the tip-end position of a direction-of-attack centerline, plus the
 * bearing angle in degrees clockwise from north. The map renders the
 * arrowhead via a `symbol` layer with `icon-image` + `icon-rotate` on this
 * point feature.
 *
 * @param {Array<[number, number]>} coords
 * @returns {{ point: [number, number], bearingDeg: number }|null}
 */
export function deriveDirAttackArrowhead(coords) {
  if (!coords || coords.length < 2) return null
  const tip = coords[coords.length - 1]
  const prev = coords[coords.length - 2]
  const lat0 = (tip[1] + prev[1]) / 2
  const cosLat = Math.cos((lat0 * Math.PI) / 180)
  const dx = (tip[0] - prev[0]) * 111.32 * cosLat
  const dy = (tip[1] - prev[1]) * 111.32
  // MapLibre `icon-rotate` is degrees clockwise from north (up). atan2 here
  // is east/north so we convert: bearing = atan2(east, north).
  const bearingRad = Math.atan2(dx, dy)
  return {
    point: tip,
    bearingDeg: (bearingRad * 180) / Math.PI,
  }
}

// ---- Helpers exposed for tests / introspection ----

export const _internal = {
  catmullRomSample,
  widthKmFromClass,
}
