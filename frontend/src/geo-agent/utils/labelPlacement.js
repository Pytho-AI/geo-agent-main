/**
 * Label collision avoidance registry.
 *
 * Ports `_placeRectsInit`, `_placeRectAdd`, `_placeRectsOverlap`,
 * `_placeRectAnyOverlap`, `_placeRectInsideCanvas`,
 * `_placeRectClampToCanvas`, `_placeTextBBox`, `_placeFindBest`
 * from geo-agent/backend/app/static/render.html (~1424-1541).
 *
 * In render.html these live as free functions reading
 * `window.__graphicsPlacedRects` / `window.__graphicsCanvasW` /
 * `window.__graphicsCanvasH`. Here we wrap them in a class so each
 * MapGraphicsLayer instance owns its own registry — multiple maps on
 * one page (analyst preview + headless export) don't collide.
 *
 * Coordinate system: canvas pixels, origin top-left. Same as the
 * SVG-overlay coordinate space used by every drawX function.
 */

/**
 * Estimate an SVG-text bounding box.
 *
 * Heuristic from render.html: width ≈ chars * fontSize * 0.62, height ≈
 * fontSize * 1.2. SVG text y is the baseline, so the bbox extends
 * fontSize above and ~0.2 fontSize below.
 *
 * @param {string} text
 * @param {number} fontSize - In CSS pixels (matches SVG font-size attr).
 * @param {number} x
 * @param {number} y - Baseline y in the SVG coord system.
 * @param {'start'|'middle'|'end'} anchor
 * @returns {{x:number,y:number,w:number,h:number}}
 */
export function estimateTextBBox(text, fontSize, x, y, anchor) {
  const w = (text || '').length * fontSize * 0.62
  const h = fontSize * 1.2
  let bx = x
  if (anchor === 'middle') bx = x - w / 2
  else if (anchor === 'end') bx = x - w
  return { x: bx, y: y - fontSize, w, h }
}

function rectsOverlap(a, b) {
  return !(
    a.x + a.w < b.x ||
    b.x + b.w < a.x ||
    a.y + a.h < b.y ||
    b.y + b.h < a.y
  )
}

export class LabelPlacementRegistry {
  /**
   * @param {{width:number, height:number, margin?:number}} opts
   */
  constructor({ width = 1600, height = 1200, margin = 10 } = {}) {
    this.rects = []
    this.width = width
    this.height = height
    this.margin = margin
  }

  /**
   * Reset rectangles + redetect canvas dimensions from a map instance.
   *
   * @param {Object} [map] - MapLibre map; reads getContainer().clientWidth/Height.
   */
  reset(map) {
    this.rects = []
    if (map && typeof map.getContainer === 'function') {
      const c = map.getContainer()
      if (c) {
        this.width = c.clientWidth || this.width
        this.height = c.clientHeight || this.height
      }
    }
  }

  /** Register a placed rectangle. */
  add(rect) {
    if (!rect) return
    this.rects.push(rect)
  }

  /**
   * NO DYNAMIC LABEL PLACEMENT (user ruling 2026-07-17). A label paints
   * at its geometry-derived anchor — on-screen or off — never slid,
   * spiraled, grid-scanned, dropped, or clamped into the viewport. The
   * old avoidance walked a label whose anchor was OFF-SCREEN through a
   * full-canvas grid scan and parked it in the top-left corner of the
   * map. The three predicates below are neutralized (not deleted) so
   * every candidate loop in the drawers accepts its FIRST — doctrinal —
   * candidate unconditionally; rect bookkeeping stays for callers that
   * only register footprints.
   */

  /** Neutralized — overlap never moves or drops a label. */
  anyOverlap() {
    return false
  }

  /** Neutralized — off-canvas labels paint at their true anchor (the
   *  SVG overlay renders with overflow visible, so they appear the
   *  moment a pan brings them in — no pop-in, no re-placement). */
  insideCanvas() {
    return true
  }

  /** Neutralized — labels are never pulled into the viewport. */
  clampToCanvas(r) {
    return r
  }

  /**
   * FIXED placement: the first candidate IS the label position.
   *
   * @param {string} text
   * @param {number} fontSize
   * @param {Array<{x:number,y:number,anchor?:string}>} candidates
   * @returns {{x:number,y:number,anchor:string,rect:object}}
   */
  findBest(text, fontSize, candidates) {
    const cand = candidates[0]
    const anchor = cand.anchor || 'start'
    const r = estimateTextBBox(text, fontSize, cand.x, cand.y, anchor)
    return { ...cand, anchor, rect: r }
  }
}

/**
 * Build a placement registry pre-seeded with rectangles describing the
 * in-frame cartographic chrome footprints (legend, north arrow, scale
 * bar) so no map labels land underneath them. The exact dimensions
 * track MapCartographicChrome's stylesheet output.
 *
 * The classification banners, title block, prepared-by, and AOI locator
 * inset used to be seeded here; they have moved to the document layer
 * (exporter._render_header_block) and no longer obstruct the map frame.
 *
 * @param {Object} map - MapLibre map instance.
 * @param {string} productType - Product type for chrome gating.
 * @returns {LabelPlacementRegistry}
 */
export function createSeededRegistry(map, productType) {
  const reg = new LabelPlacementRegistry()
  reg.reset(map)
  if (!productType) return reg
  const W = reg.width
  const H = reg.height

  // Legend strip — full-width bar across the bottom of the map frame.
  // ATP 2-01.3 fig 4-9: legend prints inside the map.
  reg.add({ x: 12, y: H - 120, w: W - 24, h: 108 })

  // North arrow on the TOP-RIGHT corner.
  reg.add({ x: W - 96, y: 12, w: 84, h: 92 })

  // Scale bar on the BOTTOM-RIGHT corner, just above the legend.
  reg.add({ x: W - 180, y: H - 200, w: 160, h: 60 })

  return reg
}
