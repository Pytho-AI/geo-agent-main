/**
 * Route-related constants and shared utilities.
 */

// --- Layer / source IDs ---
export const ROUTE_LINE_ID = 'route-line'
export const ROUTE_EDIT_PREVIEW_ID = 'route-edit-preview'
export const SAVED_ROUTE_PREFIX = 'saved-route-'
export const MAX_SAVED_ROUTE_LAYERS = 20
export const MAX_WEATHER_SEGS_PER_ROUTE = 20

// --- Colors ---
// Routes must read as ROUTES, never as hydrography. Blue solid lines
// along terrain ARE rivers to an analyst's eye (the "river down the
// avenue of approach" complaint, twice). Magenta + dashes is the
// unmistakably-synthetic overlay treatment: no natural feature on the
// basemap is dashed magenta.
export const ROUTE_COLOR = '#c026d3'
export const ROUTE_EDIT_PREVIEW_COLOR = '#f59e0b'
export const ROUTE_DIMMED_COLOR = '#666'
export const ROUTE_START_MARKER_COLOR = '#16a34a'
export const ROUTE_END_MARKER_COLOR = '#dc2626'
export const ROUTE_DASHARRAY = [2.2, 1.6]

// --- Route line paint ---
export const ROUTE_LINE_PAINT = {
  'line-color': ROUTE_COLOR,
  'line-width': 3.5,
  'line-opacity': 0.9,
  'line-dasharray': ROUTE_DASHARRAY,
}

export const ROUTE_LINE_LAYOUT = {
  // NOT 'round': round caps visually fuse the dashes back into a solid
  // river-like line at narrow widths.
  'line-cap': 'butt',
  'line-join': 'round',
}

// --- Edit control-point config ---
export const CP_MIN = 6
export const CP_MAX = 30
export const CP_DIVISOR = 8        // coords.length / CP_DIVISOR = number of handles
export const EDIT_DEBOUNCE_MS = 600

// Empty GeoJSON used to clear a source without removing it (must be valid GeoJSON)
const EMPTY_GEOJSON = { type: 'FeatureCollection', features: [] }

// --- Saved-route painter (2026-07-06, provenance rule: every route in
// the map's route stream is analyst-authored — pipelines delete their
// planning scratch routes at the source — so this painter draws ALL
// stream routes, on the live map AND in headless/product renders, with
// zero renderer-side filtering.)
//
// Structure: ONE geojson source + ONE data-driven line layer for every
// saved route (per-feature `color` carries the weather-segment
// coloring), plus one invisible wide hit layer for click-to-open-panel.
// Three layers TOTAL regardless of route count — never per-slot layer
// grids (an earlier port pre-created 440 empty slot layers at init;
// that design is banned).

export const SAVED_ROUTES_SOURCE = 'saved-routes'
export const SAVED_ROUTES_LAYER = 'saved-routes-lines'
export const SAVED_ROUTES_NAME_LAYER = 'saved-routes-names'
export const SAVED_ROUTES_HIT_SOURCE = 'saved-routes-hit'
export const SAVED_ROUTES_HIT_LAYER = 'saved-routes-hit-lines'
export const SAVED_ROUTES_ENDPOINT_SOURCE = 'saved-routes-endpoints'
export const SAVED_ROUTES_ENDPOINT_LAYER = 'saved-routes-endpoint-markers'
export const SAVED_ROUTES_ENDPOINT_LABEL_LAYER = 'saved-routes-endpoint-labels'

/**
 * Create the saved-route source + layers once at map init and bind the
 * click-to-open-panel handler once. updateSavedRouteLayers only ever
 * calls setData afterward. The click handler resolves the clicked
 * feature's routeIndex against map.__savedRoutes (refreshed on every
 * update) so handlers never need rebinding.
 */
export function initSavedRouteLayers(map, callbacks = {}) {
  map.__savedRoutes = []
  map.__savedRouteCallbacks = callbacks

  map.addSource(SAVED_ROUTES_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
  // Dashed synthetic-overlay line — deliberately NOT a solid blue
  // stroke (reads as a river along terrain-following paths; the user
  // has flagged that illusion twice). Weather-segment coloring still
  // rides per-feature `color`; the dash pattern applies regardless.
  map.addLayer({
    id: SAVED_ROUTES_LAYER, type: 'line', source: SAVED_ROUTES_SOURCE,
    paint: {
      'line-color': ['coalesce', ['get', 'color'], ROUTE_COLOR],
      'line-width': 3.5,
      'line-opacity': 0.9,
      'line-dasharray': ROUTE_DASHARRAY,
    },
    layout: { 'line-cap': 'butt', 'line-join': 'round' },
  })
  // Route name repeated along the line so the graphic self-identifies.
  map.addLayer({
    id: SAVED_ROUTES_NAME_LAYER, type: 'symbol', source: SAVED_ROUTES_SOURCE,
    layout: {
      'symbol-placement': 'line',
      'text-field': ['coalesce', ['get', 'name'], 'ROUTE'],
      'text-font': ['Noto Sans Regular'],
      'text-size': 11,
      'text-letter-spacing': 0.05,
      'symbol-spacing': 300,
    },
    paint: {
      'text-color': ROUTE_COLOR,
      'text-halo-color': '#ffffff',
      'text-halo-width': 1.6,
    },
  })

  map.addSource(SAVED_ROUTES_HIT_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
  map.addLayer({
    id: SAVED_ROUTES_HIT_LAYER, type: 'line', source: SAVED_ROUTES_HIT_SOURCE,
    paint: { 'line-color': 'transparent', 'line-width': 16, 'line-opacity': 0 },
  })

  // Explicit START / END markers — a route has endpoints; a river does
  // not. Green ring = start, red ring = end, with the word written
  // under the marker so nobody has to guess.
  map.addSource(SAVED_ROUTES_ENDPOINT_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
  map.addLayer({
    id: SAVED_ROUTES_ENDPOINT_LAYER, type: 'circle', source: SAVED_ROUTES_ENDPOINT_SOURCE,
    paint: {
      'circle-radius': 6,
      'circle-color': '#ffffff',
      'circle-stroke-width': 3,
      'circle-stroke-color': ['case',
        ['==', ['get', 'role'], 'start'], ROUTE_START_MARKER_COLOR,
        ROUTE_END_MARKER_COLOR],
    },
  })
  map.addLayer({
    id: SAVED_ROUTES_ENDPOINT_LABEL_LAYER, type: 'symbol', source: SAVED_ROUTES_ENDPOINT_SOURCE,
    layout: {
      'text-field': ['get', 'label'],
      'text-font': ['Noto Sans Regular'],
      'text-size': 10,
      'text-offset': [0, 1.3],
      'text-anchor': 'top',
      'text-allow-overlap': true,
    },
    paint: {
      'text-color': ['case',
        ['==', ['get', 'role'], 'start'], ROUTE_START_MARKER_COLOR,
        ROUTE_END_MARKER_COLOR],
      'text-halo-color': '#ffffff',
      'text-halo-width': 1.6,
    },
  })

  map.on('click', SAVED_ROUTES_HIT_LAYER, (e) => {
    const f = e.features && e.features[0]
    if (!f) return
    const idx = f.properties && f.properties.routeIndex
    const route = (map.__savedRoutes || [])[idx]
    const cb = map.__savedRouteCallbacks || {}
    if (route) {
      cb.setRouteResult?.(route)
      cb.setShowRoutePanel?.(true)
      cb.setRouteEditMode?.(true)
    }
  })
  map.on('mouseenter', SAVED_ROUTES_HIT_LAYER, () => { map.getCanvasContainer().style.cursor = 'pointer' })
  map.on('mouseleave', SAVED_ROUTES_HIT_LAYER, () => { map.getCanvasContainer().style.cursor = '' })
}

/**
 * Update the saved-route source with fresh data from the API. setData
 * only — no layer churn. Weather-segmented routes contribute one
 * feature per segment (per-feature color); plain routes contribute one
 * full-geometry feature.
 *
 * @param {Object} map - MapLibre map instance
 * @param {Array} routes - Route objects from the API (data.routes)
 * @param {Object} callbacks - { setRouteResult, setShowRoutePanel, setRouteEditMode }
 */
export function updateSavedRouteLayers(map, routes, callbacks) {
  map.__savedRoutes = routes || []
  if (callbacks) map.__savedRouteCallbacks = callbacks

  const lineFeatures = []
  const hitFeatures = []
  const endpointFeatures = []

  ;(routes || []).forEach((route, idx) => {
    const path = route?.paths?.[0]
    const coords = path?.geom?.coordinates
    if (!coords || coords.length < 2) return
    const segments = path?.analysis?.weather?.segments
    const routeName = (route?.name || '').trim() || 'ROUTE'

    hitFeatures.push({
      type: 'Feature',
      geometry: path.geom,
      properties: { routeIndex: idx },
    })

    endpointFeatures.push(
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: coords[0] },
        properties: { routeIndex: idx, role: 'start', label: 'START' },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: coords[coords.length - 1] },
        properties: { routeIndex: idx, role: 'end', label: 'END' },
      },
    )

    if (segments && segments.length > 0) {
      const cumDist = buildCumDist(coords)
      for (const seg of segments) {
        const segCoords = extractSegmentCoords(coords, cumDist, seg.start_mi, seg.end_mi)
        if (segCoords && segCoords.length >= 2) {
          lineFeatures.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: segCoords },
            properties: { routeIndex: idx, color: seg.color || ROUTE_COLOR, name: routeName },
          })
        }
      }
    } else {
      lineFeatures.push({
        type: 'Feature',
        geometry: path.geom,
        properties: { routeIndex: idx, color: ROUTE_COLOR, name: routeName },
      })
    }
  })

  map.getSource(SAVED_ROUTES_SOURCE)?.setData({ type: 'FeatureCollection', features: lineFeatures })
  map.getSource(SAVED_ROUTES_HIT_SOURCE)?.setData({ type: 'FeatureCollection', features: hitFeatures })
  map.getSource(SAVED_ROUTES_ENDPOINT_SOURCE)?.setData({ type: 'FeatureCollection', features: endpointFeatures })
}

// --- Helpers ---

function buildCumDist(coords) {
  const toRad = (d) => d * Math.PI / 180
  const cumDist = [0]
  for (let i = 1; i < coords.length; i++) {
    const [lon1, lat1] = coords[i - 1]
    const [lon2, lat2] = coords[i]
    const dLat = toRad(lat2 - lat1)
    const dLon = toRad(lon2 - lon1)
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
    const m = 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
    cumDist.push(cumDist[i - 1] + m / 1609.344)
  }
  return cumDist
}

function extractSegmentCoords(coords, cumDist, startMi, endMi) {
  let startIdx = 0, endIdx = coords.length - 1
  for (let i = 0; i < cumDist.length; i++) {
    if (cumDist[i] >= startMi) { startIdx = Math.max(0, i - 1); break }
  }
  for (let i = cumDist.length - 1; i >= 0; i--) {
    if (cumDist[i] <= endMi) { endIdx = Math.min(coords.length - 1, i + 1); break }
  }
  if (endIdx <= startIdx) endIdx = Math.min(startIdx + 1, coords.length - 1)
  return coords.slice(startIdx, endIdx + 1)
}

// --- Utility: safely remove a layer + source pair ---
export function safeRemoveLayerAndSource(map, layerId, sourceId) {
  if (map.getLayer(layerId)) map.removeLayer(layerId)
  if (map.getSource(sourceId || layerId)) map.removeSource(sourceId || layerId)
}

// --- Utility: clear all route visuals on a map (for full map reset) ---
// Removes active/edit preview layers, clears persistent saved-route sources to empty.
export function cleanupRouteLayers(map) {
  if (!map) return

  // Active route line (transient — remove entirely)
  safeRemoveLayerAndSource(map, ROUTE_LINE_ID)

  // Edit preview (transient — remove entirely)
  safeRemoveLayerAndSource(map, ROUTE_EDIT_PREVIEW_ID)

  // Weather segment layers from drawRoute (transient — remove entirely)
  for (let wi = 0; wi < MAX_WEATHER_SEGS_PER_ROUTE; wi++) {
    safeRemoveLayerAndSource(map, `route-weather-seg-${wi}`)
  }

  // Saved route layers are persistent — clear their data instead of removing
  updateSavedRouteLayers(map, [])
}
