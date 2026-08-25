/**
 * Military symbol generation and rendering utilities
 * Uses mil-sym-ts for MIL-STD-2525D/E rendering and milsymbol for previews
 * 
 * NOTE: Symbol search is handled by the backend /api/v1/config/symbols endpoints.
 * Use GeoAgentProvider's findBestSymbolMatch() and searchSymbols() for symbol lookups.
 */

import { 
  MilStdIconRenderer, 
  WebRenderer, 
  MilStdAttributes,
  Modifiers
} from '@armyc2.c5isr.renderer/mil-sym-ts-web'
import ms from 'milsymbol'

/**
 * Create milsymbol preview SVG for symbol picker
 * @param {string} entityCode - 6-digit entity code
 * @param {Object} options - Options: { size, symbolSet }
 * @returns {string|null} SVG string or null on error
 * 
 * SIDC structure (20 chars):
 * - 10: version (2525D)
 * - 0: context (reality)
 * - 3: standard identity (friend)
 * - SS: symbol set (2 chars)
 * - 0: status (present)
 * - 0: HQ/TF/Dummy (not applicable)
 * - 00: amplifier/descriptor (no echelon for preview)
 * - XXXXXX: entity code (6 chars)
 * - 0000: modifiers
 */
export const createMilsymbolPreview = (entityCode, options = {}) => {
  try {
    const symbolSet = options.symbolSet || '10'
    // Follow reference: 1003 + symbolSet + 0000 + entityCode + 0000
    const sidc = `1003${symbolSet}0000${entityCode}0000`
    const symbol = new ms.Symbol(sidc, {
      size: options.size || 35
    })
    return symbol.asSVG()
  } catch (err) {
    console.error('Error creating milsymbol preview:', err)
    return null
  }
}

/**
 * Generate military symbol SVG from SIDC using mil-sym-ts
 * @param {string} sidc - 20-character SIDC
 * @param {Object} options - Symbol options (designation, heading, size)
 * @returns {string|null} SVG string or null on error
 */
// Return: { svg, size: {width, height}, anchor: {x, y} } | null
//
// milsymbol returns an SVG larger than the requested `size` because echelon
// modifiers (XX for BDE, XXX for DIV, etc.) and the affiliation frame add
// padding above the symbol. For size=40 hostile units the SVG is 60.8 × 76.8
// with the doctrinal icon center (`anchor`) at (30.4, 46.4) — NOT at the
// SVG bbox center. Callers MUST use `anchor` to position the icon so that
// the icon center lands at the unit's projected ground coordinate; placing
// the SVG by its bbox center introduces a ~26px southward offset that
// looks like the unit is meters/kilometers off its real position at map
// scale.
// MIL-STD-2525C operational-condition amplifier characters at SIDC
// position 3 (0-indexed). Set from the OOB disposition string per
// FM 3-60 Fig 2-7 — DESTROYED prints the red X over the symbol;
// DAMAGED / DEGRADED / SUPPRESSED render the operational-condition
// status modifier. Anything else (NORMAL / FULL / READY / blank) stays
// at the default 'A' (Anticipated/Planned… but more importantly the
// "no special condition" character that milsymbol leaves alone).
const _OP_CONDITION_BY_DISPOSITION = {
  DESTROYED: 'X',
  DEFEATED: 'X',
  KIA: 'X',
  DAMAGED: 'D',
  DEGRADED: 'D',
  SUPPRESSED: 'B',
  NEUTRALIZED: 'X',
}

function _applyOperationalCondition(sidc, condition) {
  if (!sidc || !condition || sidc.length < 4) return sidc
  return sidc.slice(0, 3) + condition + sidc.slice(4)
}

// Symbol construction is pure in (sidc, options) — and a formation
// placard renders hundreds of IDENTICAL template children. Memoize.
const _symbolCache = new Map()
const _SYMBOL_CACHE_MAX = 600

export const createMilSymbol = (sidc, options = {}) => {
  const cacheKey = sidc + '|' + JSON.stringify(options)
  const hit = _symbolCache.get(cacheKey)
  if (hit !== undefined) return hit
  const result = _createMilSymbolUncached(sidc, options)
  if (_symbolCache.size >= _SYMBOL_CACHE_MAX) _symbolCache.clear()
  _symbolCache.set(cacheKey, result)
  return result
}

const _createMilSymbolUncached = (sidc, options = {}) => {
  try {
    if (!sidc) {
      return null
    }
    // Apply the operational-condition amplifier (destroyed X, damaged D,
    // etc.) from the OOB disposition before instantiating the symbol
    // so milsymbol renders the doctrinal modifier directly.
    const condition = options.condition
      || _OP_CONDITION_BY_DISPOSITION[String(options.disposition || '').trim().toUpperCase()]
      || null
    const finalSidc = condition ? _applyOperationalCondition(sidc, condition) : sidc
    const opts = {
      size: options.size || 40,
      uniqueDesignation: options.designation,
      fillOpacity: 1.0,
      frame: true,
    }
    if (options.heading && Number(options.heading) !== 0) {
      opts.direction = Number(options.heading)
    }
    const symbol = new ms.Symbol(finalSidc, opts)
    return {
      svg: symbol.asSVG(),
      size: symbol.getSize(),
      anchor: symbol.getAnchor(),
      // Center of the symbol FRAME (octagon). For HQ-staff symbols the
      // ground anchor is the staff TIP, well below the frame — labels
      // and hit-tests must work off the frame, not the anchor.
      octagonAnchor: symbol.getOctagonAnchor(),
    }
  } catch (err) {
    console.error('Error creating military symbol:', err)
    return null
  }
}

/**
 * Generate tactical graphic using mil-sym-ts WebRenderer
 * For multi-point control measures (lines, areas)
 * 
 * @param {string} sidc - SIDC for the tactical graphic
 * @param {Array} coordinates - Array of [lon, lat] coordinates
 * @param {Object} options - Options including id, name, designation, affiliation, description
 * @param {Object} mapInstance - MapLibre map instance for bounds/zoom
 * @returns {Object|null} Parsed GeoJSON or null on error
 */
export const createTacticalGraphic = (sidc, coordinates, options = {}, mapInstance = null) => {
  // Validate inputs
  if (!sidc || !coordinates || !Array.isArray(coordinates)) {
    return null
  }
  
  // Flatten coordinates if nested
  const flatCoords = coordinates
    .map(coord => Array.isArray(coord[0]) ? coord[0] : coord)
    .filter(coord => Array.isArray(coord) && coord.length >= 2)
  
  // Most tactical graphics need at least 2 points for lines, 3 for areas
  if (flatCoords.length < 2) {
    return null
  }
  
  try {
    // Format coordinates as "lon1,lat1 lon2,lat2 ..."
    const controlPoints = flatCoords
      .map(([lon, lat]) => `${lon},${lat}`)
      .join(' ')
    
    // Get map bounds for rendering
    const bounds = mapInstance?.getBounds?.()
    const bbox = bounds 
      ? `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`
      : '-180,-90,180,90'
    
    // Calculate scale from map zoom (scale ≈ 591657550.5 / 2^zoom at equator)
    const zoom = mapInstance?.getZoom?.() || 10
    const scale = Math.round(591657550.5 / Math.pow(2, zoom))
    
    // Empty modifiers/attributes - labels are stripped in post-processing
    const modifiers = new Map()
    const attributes = new Map()
    
    // Render as GeoJSON - pass empty strings for name/description to minimize labels
    const result = WebRenderer.RenderSymbol(
      options.id || 'graphic-1',
      '',
      '',
      sidc,
      controlPoints,
      'clampToGround',
      scale,
      bbox,
      modifiers,
      attributes,
      WebRenderer.OUTPUT_FORMAT_GEOJSON
    )
    
    // Check for error response from WebRenderer
    if (result) {
      const parsed = JSON.parse(result)
      if (parsed.type === 'error') {
        console.warn('WebRenderer error:', parsed.error)
        return null
      }
      return parsed
    }
    return null
  } catch (err) {
    console.error('Error creating tactical graphic:', err)
    return null
  }
}

/**
 * Render unit symbol icon using mil-sym-ts
 * For unit/equipment symbols, NOT control measures
 * 
 * @param {string} sidc - SIDC for the unit
 * @param {Object} options - Options including designation, size
 * @returns {string|null} SVG string or null on error
 */
export const createUnitIcon = (sidc, options = {}) => {
  try {
    const renderer = MilStdIconRenderer.getInstance()
    if (!renderer.isReady() || !renderer.CanRender(sidc)) {
      return null
    }
    
    const modifiers = new Map()
    if (options.designation) modifiers.set(Modifiers.T_UNIQUE_DESIGNATION_1, options.designation)
    
    const attributes = new Map()
    attributes.set(MilStdAttributes.PixelSize, String(options.size || 40))
    
    const symbolInfo = renderer.RenderSVG(sidc, modifiers, attributes)
    return symbolInfo?.getSVG?.() || null
  } catch (err) {
    console.error('Error creating unit icon:', err)
    return null
  }
}

/**
 * Check if the mil-sym-ts renderer is ready
 * @returns {boolean}
 */
export const isMilSymRendererReady = () => {
  try {
    const renderer = MilStdIconRenderer.getInstance()
    return renderer.isReady()
  } catch {
    return false
  }
}

/**
 * Get the MilStdIconRenderer instance
 * @returns {Object} Renderer instance
 */
export const getMilStdIconRenderer = () => {
  return MilStdIconRenderer.getInstance()
}
