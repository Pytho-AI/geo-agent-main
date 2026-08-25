/**
 * Doctrinal point-glyph icon atlas (FM 1-02.2 / MIL-STD 2525E).
 *
 * Reused by every product that paints doctrinal point glyphs — MCOO,
 * SITEMP, Threat Overlay, GRINTSUM, TMP, Threat COA Statement. The `graphics-icon-*` image IDs are
 * legacy wire format and stay stable.
 *
 * Each glyph is painted to an offscreen canvas, then registered with the
 * MapLibre style via `map.addImage(id, image, { pixelRatio })`. Symbol
 * layers in `tacticalLayers.maplibre.js` reference these IDs through `icon-image`.
 *
 * Glyphs covered:
 *
 *   graphics-icon-key-terrain      Purple K-in-circle on a white casing.
 *   graphics-icon-strong-point     Blue S-in-circle on a white casing.
 *   graphics-icon-decision-point   DP in a black-stroked diamond on a white pad.
 *   graphics-icon-choke-point      Black X glyph on a white rounded pad.
 *   graphics-icon-obstacle-<kind>  Subkind-keyed obstacle glyph on a white pad.
 *   graphics-icon-target-priority-{1,2,3,4,5}  Priority-coded red dots.
 *
 * Subkinds for obstacle:
 *   block   minefield   blown_bridge   bridge   ford   abatis   crater   ferry
 *
 * Painted at 2x to keep edges crisp on retina displays. `pixelRatio: 2` is
 * passed to `addImage` so MapLibre downscales when needed.
 *
 * Idempotent: every glyph checks `map.hasImage(id)` before re-painting.
 */

// Single point of truth for the visual size of every glyph (in CSS px at 1x).
// Symbol layers reference this in `icon-size` (kept at 1; the canvas is
// already drawn at 2x for retina sharpness).
const GLYPH_SIZE = 44 // 44x44 CSS px → 88x88 canvas pixels at pixelRatio 2

const OBSTACLE_SUBKINDS = [
  'block',
  'minefield',
  'blown_bridge',
  'bridge',
  'ford',
  'abatis',
  'crater',
  'ferry',
  'default',
]

const TARGET_PRIORITIES = [1, 2, 3, 4, 5]

/**
 * Register every MCOO doctrinal point-glyph icon on the given map.
 *
 * @param {Object} map - MapLibre map instance.
 */
export function registerMcooIcons(map) {
  if (!map) return
  if (typeof document === 'undefined') return

  registerIcon(map, 'graphics-icon-key-terrain', drawKeyTerrainGlyph)
  registerIcon(map, 'graphics-icon-strong-point', drawStrongPointGlyph)
  registerIcon(map, 'graphics-icon-decision-point', drawDecisionPointGlyph)
  registerIcon(map, 'graphics-icon-choke-point', drawChokePointGlyph)

  for (const sub of OBSTACLE_SUBKINDS) {
    registerIcon(map, `graphics-icon-obstacle-${sub}`, ctx =>
      drawObstacleGlyph(ctx, sub),
    )
  }

  for (const p of TARGET_PRIORITIES) {
    registerIcon(map, `graphics-icon-target-priority-${p}`, ctx =>
      drawTargetDot(ctx, p),
    )
  }

  // Cluster frame icons (rendered as MapLibre icons rather than polygons so the
  // analyst can click the underlying cluster cell). Per-affiliation shape.
  for (const aff of ['friend', 'hostile', 'neutral', 'unknown']) {
    registerIcon(map, `graphics-icon-cluster-${aff}`, ctx =>
      drawClusterFrame(ctx, aff),
    )
  }
}

function registerIcon(map, id, drawFn) {
  if (map.hasImage(id)) return
  const dpr = 2
  const W = GLYPH_SIZE * dpr
  const H = GLYPH_SIZE * dpr
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.scale(dpr, dpr)
  drawFn(ctx, GLYPH_SIZE)
  const data = ctx.getImageData(0, 0, W, H)
  const bytes = new Uint8Array(data.data.buffer.slice(0))
  map.addImage(id, { width: W, height: H, data: bytes }, { pixelRatio: dpr })
}

// ---- Glyph drawers (all operate at logical 1x; size is the GLYPH_SIZE) ----

function drawKeyTerrainGlyph(ctx, size) {
  const cx = size / 2
  const cy = size / 2
  // White casing under the purple stroke for visibility on dark basemaps.
  ctx.beginPath()
  ctx.arc(cx, cy, 19, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.beginPath()
  ctx.arc(cx, cy, 17, 0, Math.PI * 2)
  ctx.lineWidth = 3.2
  ctx.strokeStyle = '#7c3aed'
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = '#7c3aed'
  ctx.font = '900 19px "Helvetica Neue", Helvetica, Arial, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('K', cx, cy + 1)
}

function drawStrongPointGlyph(ctx, size) {
  const cx = size / 2
  const cy = size / 2
  ctx.beginPath()
  ctx.arc(cx, cy, 20, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.beginPath()
  ctx.arc(cx, cy, 17, 0, Math.PI * 2)
  ctx.lineWidth = 3.0
  ctx.strokeStyle = '#1e3a8a'
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = '#1e3a8a'
  ctx.font = '900 19px "Helvetica Neue", Helvetica, Arial, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('S', cx, cy + 1)
}

function drawDecisionPointGlyph(ctx, size) {
  const cx = size / 2
  const cy = size / 2
  // Light white pad behind the diamond so the glyph reads on dark basemaps.
  ctx.fillStyle = 'rgba(255,255,255,0.88)'
  roundRect(ctx, cx - 24, cy - 24, 48, 48, 4)
  ctx.fill()

  const dh = 17
  ctx.beginPath()
  ctx.moveTo(cx, cy - dh)
  ctx.lineTo(cx + dh, cy)
  ctx.lineTo(cx, cy + dh)
  ctx.lineTo(cx - dh, cy)
  ctx.closePath()
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.lineWidth = 3.0
  ctx.strokeStyle = '#000000'
  ctx.stroke()
  ctx.fillStyle = '#000000'
  ctx.font = '900 12px "Helvetica Neue", Helvetica, Arial, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('DP', cx, cy + 1)
}

function drawChokePointGlyph(ctx, size) {
  const cx = size / 2
  const cy = size / 2
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  roundRect(ctx, cx - 11, cy - 11, 22, 22, 3)
  ctx.fill()
  const r = 8
  ctx.lineWidth = 2.6
  ctx.lineCap = 'round'
  ctx.strokeStyle = '#000000'
  ctx.beginPath()
  ctx.moveTo(cx - r, cy - r)
  ctx.lineTo(cx + r, cy + r)
  ctx.moveTo(cx + r, cy - r)
  ctx.lineTo(cx - r, cy + r)
  ctx.stroke()
}

function drawObstacleGlyph(ctx, subkind) {
  const cx = GLYPH_SIZE / 2
  const cy = GLYPH_SIZE / 2
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  roundRect(ctx, cx - 11, cy - 11, 22, 22, 3)
  ctx.fill()

  ctx.save()
  ctx.translate(cx, cy)
  ctx.strokeStyle = '#000000'
  ctx.fillStyle = '#000000'
  ctx.lineWidth = 1.8
  ctx.lineCap = 'round'

  if (subkind === 'minefield') {
    for (const [dx, dy] of [
      [-6, -3],
      [6, -3],
      [0, 6],
    ]) {
      ctx.beginPath()
      ctx.arc(dx, dy, 2.8, 0, Math.PI * 2)
      ctx.fill()
    }
  } else if (subkind === 'blown_bridge') {
    ctx.beginPath()
    ctx.moveTo(-8, -5)
    ctx.lineTo(8, -5)
    ctx.moveTo(-8, 5)
    ctx.lineTo(8, 5)
    ctx.moveTo(-7, -7)
    ctx.lineTo(7, 7)
    ctx.moveTo(7, -7)
    ctx.lineTo(-7, 7)
    ctx.stroke()
  } else if (subkind === 'bridge') {
    ctx.lineWidth = 2.4
    ctx.beginPath()
    ctx.moveTo(-8, -5)
    ctx.lineTo(8, -5)
    ctx.moveTo(-8, 5)
    ctx.lineTo(8, 5)
    ctx.stroke()
  } else if (subkind === 'ford') {
    ctx.lineWidth = 2.2
    ctx.beginPath()
    ctx.moveTo(-8, -3)
    ctx.lineTo(-2, -3)
    ctx.moveTo(-1, 0)
    ctx.lineTo(5, 0)
    ctx.moveTo(6, 3)
    ctx.lineTo(8, 3)
    ctx.stroke()
  } else if (subkind === 'block') {
    ctx.beginPath()
    ctx.moveTo(0, -7)
    ctx.lineTo(7, 5)
    ctx.lineTo(-7, 5)
    ctx.closePath()
    ctx.fill()
  } else if (subkind === 'abatis') {
    ctx.lineWidth = 2.2
    ctx.lineJoin = 'miter'
    ctx.beginPath()
    ctx.moveTo(-7, 5)
    ctx.lineTo(0, -7)
    ctx.lineTo(7, 5)
    ctx.stroke()
  } else if (subkind === 'crater') {
    ctx.beginPath()
    ctx.arc(0, 0, 8, 0, Math.PI * 2)
    ctx.fillStyle = '#ffffff'
    ctx.fill()
    ctx.lineWidth = 1.8
    ctx.stroke()
    ctx.strokeStyle = '#000000'
    ctx.beginPath()
    ctx.moveTo(-5, -5)
    ctx.lineTo(5, 5)
    ctx.moveTo(5, -5)
    ctx.lineTo(-5, 5)
    ctx.stroke()
  } else if (subkind === 'ferry') {
    ctx.beginPath()
    ctx.arc(0, 0, 8, 0, Math.PI * 2)
    ctx.fillStyle = '#ffffff'
    ctx.fill()
    ctx.lineWidth = 1.8
    ctx.stroke()
    ctx.fillStyle = '#000000'
    ctx.font = '800 12px "Helvetica Neue", Helvetica, Arial, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('F', 0, 0)
  } else {
    // default: X
    ctx.lineWidth = 2.2
    ctx.beginPath()
    ctx.moveTo(-7, -7)
    ctx.lineTo(7, 7)
    ctx.moveTo(7, -7)
    ctx.lineTo(-7, 7)
    ctx.stroke()
  }
  ctx.restore()
}

function drawTargetDot(ctx, priority) {
  const cx = GLYPH_SIZE / 2
  const cy = GLYPH_SIZE / 2
  const r = priority <= 1 ? 14 : priority <= 2 ? 10 : priority <= 3 ? 8 : 7
  ctx.beginPath()
  ctx.arc(cx, cy, r + 1, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fillStyle = priority <= 1 ? '#b91c1c' : priority <= 3 ? '#dc2626' : '#f97316'
  ctx.fill()
  ctx.lineWidth = 1.2
  ctx.strokeStyle = '#7f1d1d'
  ctx.stroke()
}

function drawClusterFrame(ctx, affiliation) {
  const cx = GLYPH_SIZE / 2
  const cy = GLYPH_SIZE / 2
  // The glyph is rendered AS A SYMBOL ICON on the map. The cluster-count text
  // is layered on as a sibling `text-field` on the same source feature (see
  // tacticalLayers.maplibre.js cluster-frame-symbols layer), so we draw frame only here.
  let fill = '#cccccc'
  let stroke = '#333333'
  if (affiliation === 'friend') {
    fill = '#80e0ff'
    stroke = '#003a66'
  } else if (affiliation === 'hostile') {
    fill = '#ff9999'
    stroke = '#800000'
  } else if (affiliation === 'neutral') {
    fill = '#a8ffa8'
    stroke = '#006400'
  } else {
    fill = '#ffe680'
    stroke = '#806600'
  }
  ctx.fillStyle = '#ffffff'
  ctx.globalAlpha = 0.92
  ctx.beginPath()
  if (affiliation === 'friend') {
    roundRect(ctx, cx - 18, cy - 13, 36, 26, 2)
  } else if (affiliation === 'hostile') {
    ctx.moveTo(cx, cy - 17)
    ctx.lineTo(cx + 17, cy)
    ctx.lineTo(cx, cy + 17)
    ctx.lineTo(cx - 17, cy)
    ctx.closePath()
  } else if (affiliation === 'neutral') {
    ctx.rect(cx - 16, cy - 16, 32, 32)
  } else {
    ctx.arc(cx, cy, 16, 0, Math.PI * 2)
  }
  ctx.fill()
  ctx.globalAlpha = 1.0

  ctx.beginPath()
  if (affiliation === 'friend') {
    roundRect(ctx, cx - 16, cy - 11, 32, 22, 2)
  } else if (affiliation === 'hostile') {
    ctx.moveTo(cx, cy - 15)
    ctx.lineTo(cx + 15, cy)
    ctx.lineTo(cx, cy + 15)
    ctx.lineTo(cx - 15, cy)
    ctx.closePath()
  } else if (affiliation === 'neutral') {
    ctx.rect(cx - 14, cy - 14, 28, 28)
  } else {
    ctx.arc(cx, cy, 14, 0, Math.PI * 2)
  }
  ctx.fillStyle = fill
  ctx.fill()
  ctx.lineWidth = 2.5
  ctx.strokeStyle = stroke
  ctx.stroke()
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

/**
 * Map an obstacle feature's subkind property to the corresponding atlas id.
 * Recognised subkinds fall through to `graphics-icon-obstacle-default`.
 *
 * @param {string} subkind
 * @returns {string}
 */
export function obstacleIconId(subkind) {
  const s = String(subkind || '').toLowerCase()
  if (s === 'mined_area') return 'graphics-icon-obstacle-minefield'
  if (s === 'bridge_blown' || s === 'demolished_bridge')
    return 'graphics-icon-obstacle-blown_bridge'
  if (s === 'ford_easy' || s === 'ford_difficult')
    return 'graphics-icon-obstacle-ford'
  if (s === 'road_block') return 'graphics-icon-obstacle-block'
  if (OBSTACLE_SUBKINDS.includes(s)) return `graphics-icon-obstacle-${s}`
  return 'graphics-icon-obstacle-default'
}

/**
 * Map a target's priority (1-5, lower is higher priority) to the atlas id.
 *
 * @param {number} priority
 * @returns {string}
 */
export function targetIconId(priority) {
  const p = Math.max(1, Math.min(5, Math.round(Number(priority) || 5)))
  return `graphics-icon-target-priority-${p}`
}

/**
 * Map a cluster affiliation to the atlas id.
 *
 * @param {string} affiliation
 * @returns {string}
 */
export function clusterIconId(affiliation) {
  const a = String(affiliation || '').toLowerCase()
  if (a === 'friend' || a === 'hostile' || a === 'neutral') {
    return `graphics-icon-cluster-${a}`
  }
  return 'graphics-icon-cluster-unknown'
}
