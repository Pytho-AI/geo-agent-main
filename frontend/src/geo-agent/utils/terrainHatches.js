/**
 * Doctrinal terrain hatch patterns (FM 1-02.2 / ATP 2-01.3 fig 4-9).
 *
 * Reused by every product whose paint pipeline overlays restricted /
 * severely restricted / urban terrain — currently MCOO, SITEMP, Threat Overlay,
 * GRINTSUM, TMP, Threat COA Statement. (Originally lifted from
 * geo-agent/backend/app/static/render.html `registerMcooPatterns` +
 * `drawRestrictedPattern` + `drawSeverePattern` + `drawUrbanPattern`.)
 *
 * Three canvas-painted tiles are generated and registered as MapLibre
 * sprite images via `map.addImage`. The fill-pattern paint expressions in
 * tacticalLayers.maplibre.js then reference these image IDs.
 *
 *   graphics-pat-restricted  green 45° diagonal hatch  (28x28)
 *   graphics-pat-severe      green cross hatch        (22x22)
 *   graphics-pat-urban       black X cells            (36x36)
 *
 * The `graphics-pat-*` image IDs are legacy wire format — kept stable so the
 * harness / parity probes (which queryRenderedFeatures by paint-image id)
 * keep working through the rename pass.
 *
 * Idempotent: skips images that already exist on the style.
 */

const PATTERNS = [
  { id: 'graphics-pat-restricted', draw: drawRestrictedPattern, size: 28 },
  { id: 'graphics-pat-severe', draw: drawSeverePattern, size: 22 },
  { id: 'graphics-pat-urban', draw: drawUrbanPattern, size: 36 },
]

/**
 * Generate the canvas pattern images used by 'fill-pattern' paint, then
 * register them with the MapLibre style under known image IDs.
 *
 * @param {Object} map - MapLibre map instance.
 */
export function registerTerrainHatches(map) {
  if (!map) return
  for (const p of PATTERNS) {
    if (map.hasImage(p.id)) continue
    const tileSize = p.size
    const canvas = document.createElement('canvas')
    canvas.width = tileSize
    canvas.height = tileSize
    const ctx = canvas.getContext('2d')
    p.draw(ctx, tileSize)
    const data = ctx.getImageData(0, 0, tileSize, tileSize)
    const bytes = new Uint8Array(data.data.buffer.slice(0))
    map.addImage(
      p.id,
      { width: tileSize, height: tileSize, data: bytes },
      { pixelRatio: 1 },
    )
  }
}

/**
 * Render a hatch pattern to a small standalone canvas and return its data
 * URL. Used by legend swatches that need to match the on-map pattern
 * pixel-for-pixel.
 *
 * @param {string} patId - One of graphics-pat-restricted / graphics-pat-severe / graphics-pat-urban.
 * @returns {string} A data URL, or empty string if pattern id unknown / no DOM.
 */
export function makePatternSwatchDataUrl(patId) {
  if (typeof document === 'undefined') return ''
  const p = PATTERNS.find(x => x.id === patId)
  if (!p) return ''
  const canvas = document.createElement('canvas')
  canvas.width = p.size
  canvas.height = p.size
  const ctx = canvas.getContext('2d')
  p.draw(ctx, p.size)
  return canvas.toDataURL('image/png')
}

function drawRestrictedPattern(ctx, n) {
  // Doctrinal fig 4-9 "restricted terrain" hatching: WIDELY-spaced thin
  // dark-green diagonal strokes on transparent (the green base fill is
  // painted by a separate layer beneath).
  ctx.clearRect(0, 0, n, n)
  ctx.strokeStyle = '#0a3a14'
  ctx.lineWidth = 1.4
  ctx.lineCap = 'square'
  const step = n / 2
  for (let i = -n; i < n * 2; i += step) {
    ctx.beginPath()
    ctx.moveTo(i, 0)
    ctx.lineTo(i + n, n)
    ctx.stroke()
  }
}

function drawSeverePattern(ctx, n) {
  // Doctrinal fig 4-9 "severely restricted" cross-hatch.
  ctx.clearRect(0, 0, n, n)
  ctx.strokeStyle = '#0d4a1a'
  ctx.lineWidth = 1.3
  ctx.lineCap = 'square'
  const step = n / 3
  for (let i = -n; i < n * 2; i += step) {
    ctx.beginPath()
    ctx.moveTo(i, 0)
    ctx.lineTo(i + n, n)
    ctx.stroke()
  }
  for (let i = -n; i < n * 2; i += step) {
    ctx.beginPath()
    ctx.moveTo(i, n)
    ctx.lineTo(i + n, 0)
    ctx.stroke()
  }
}

function drawUrbanPattern(ctx, n) {
  // Doctrinal fig 4-9 / 4-10 "urban terrain": pattern of black X cells.
  ctx.clearRect(0, 0, n, n)
  ctx.fillStyle = 'rgba(255,255,255,0.55)'
  ctx.fillRect(0, 0, n, n)
  ctx.strokeStyle = '#000'
  ctx.lineWidth = 1.4
  ctx.lineCap = 'square'
  ctx.strokeRect(0.5, 0.5, n - 1, n - 1)
  ctx.beginPath()
  ctx.moveTo(1, 1)
  ctx.lineTo(n - 1, n - 1)
  ctx.moveTo(n - 1, 1)
  ctx.lineTo(1, n - 1)
  ctx.stroke()
}
