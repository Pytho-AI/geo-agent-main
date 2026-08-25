/**
 * Shared client-side contour source + the two contour treatments.
 *
 * ONE elevation source feeds every contour surface: maplibre-contour
 * computes contour vector tiles in the browser (in its own worker)
 * from the same Mapterhorn Terrarium DEM that drives the basemaps'
 * baked hillshade, fetched through this service's own
 * /tiles/dem/{z}/{x}/{y}.webp proxy (same-origin, tilecache-backed —
 * identical air-gap story to every other tile shape). Global
 * coverage at every zoom; this replaced the pregenerated
 * area-of-operations-scoped GeoJSON (files/contours_smooth_final
 * .geojson), which was blank outside the one AO it was built for.
 *
 * Two treatments, one source:
 *
 *   'topo'      — brown topographic-sheet linework. Rides the `topo`
 *                 basemap: GeoAgentMap shows/hides it with the
 *                 basemap selection (live view AND headless product
 *                 renders — the render target drives the same map).
 *   'doctrinal' — the black SITEMP treatment (near-white basemap,
 *                 black rings, labeled index contours). Headless
 *                 renders gate it on the product schema's
 *                 `map_show_topographic_contours` primitive (the
 *                 ?contours= URL param); the live/edit surface gates
 *                 it on the analyst's Contours layer toggle
 *                 (layerVisibility.contours, default ON), which
 *                 product edit sessions initialize from the map's
 *                 stored render spec (GET /render/spec/{map_uuid}).
 *
 * Interval tiers follow the doctrine contour-interval ↔ map-scale
 * mapping the SITEMP overlay documented (and then contradicted with
 * a z≥11 floor that sat ABOVE product-render zooms — the AO-bbox
 * SITEMP render is ~z9.3, which is why exported products never
 * showed a single contour). Contours exist at EVERY zoom — there is
 * no minzoom floor; zooming out coarsens the interval instead of
 * dropping the layer (the second time a zoom floor silently blanked
 * this surface, so: intervals scale, floors are banned):
 *
 *   Z 0–3   (global):      2000 m
 *   Z 3–5   (continental): 1000 m, index 2000 m
 *   Z 5–7   (theater):      500 m, index 1000 m
 *   Z 7–9   (operational):  100 m
 *   Z 9–11  (1:500k–130k):   50 m, index 100 m
 *   Z 11–13 (1:130k–33k):    20 m, index 100 m
 *   Z ≥ 13  (tactical):      10 m, index 50 m
 */

import maplibregl from 'maplibre-gl'
import mlcontour from 'maplibre-contour'
import { API_BASE } from './mapStyles'

export const CONTOUR_SOURCE_ID = 'dem-contours'
const CONTOUR_SOURCE_LAYER = 'contours'
export const CONTOUR_MINZOOM = 0

// Doctrine-mapped [minor, major] interval tiers (see module comment).
// Keyed from z0 so the layer never blanks — wide views get coarse
// intervals (only major relief draws rings), tight views get fine ones.
const THRESHOLDS = {
  0: [2000, 2000],
  3: [1000, 2000],
  5: [500, 1000],
  7: [100, 100],
  9: [50, 100],
  11: [20, 100],
  13: [10, 50],
}

// Singleton DemSource — one worker, one DEM tile cache, shared by
// every map instance and both treatments.
let _demSource = null

function demSource() {
  if (!_demSource) {
    _demSource = new mlcontour.DemSource({
      url: `${API_BASE}/tiles/dem/{z}/{x}/{y}.webp`,
      encoding: 'terrarium',
      maxzoom: 12,
      worker: true,
    })
    _demSource.setupMaplibre(maplibregl)
  }
  return _demSource
}

/** Add the shared contour vector source to a map (idempotent). */
export function ensureContourSource(map) {
  if (map.getSource(CONTOUR_SOURCE_ID)) return
  map.addSource(CONTOUR_SOURCE_ID, {
    type: 'vector',
    tiles: [
      demSource().contourProtocolUrl({
        thresholds: THRESHOLDS,
        contourLayer: CONTOUR_SOURCE_LAYER,
        elevationKey: 'ele',
        levelKey: 'level',
        extent: 4096,
        buffer: 1,
        // DEM maxzoom is 12; subsample overzoomed parent tiles so the
        // 10 m tactical tier stays smooth instead of pixel-stepped.
        subsampleBelow: 100,
      }),
    ],
    maxzoom: 15,
  })
}

// Per-treatment styling. Line widths/opacities interpolate so the
// operational view stays quiet and the tactical view reads like a
// printed sheet.
const TREATMENTS = {
  topo: {
    line: '#a87f5a',
    index: '#8a6543',
    label: '#8a6543',
    halo: 'rgba(247,244,236,0.85)', // topo paper white
    lineWidth: 0.5,
    indexWidth: 1.0,
    lineOpacity: 0.7,
    indexOpacity: 0.9,
  },
  // Deliberately faint: contours are BACKDROP on the bland default
  // basemap — the analyst read "way too prominent" at the original
  // 0.6/0.9 opacities, and a terrain readout must never compete with
  // unit symbols or control measures.
  doctrinal: {
    line: '#3a3a3a',
    index: '#2a2a2a',
    label: '#3a3a3a',
    halo: 'rgba(255,255,255,0.9)',
    lineWidth: 0.4,
    indexWidth: 0.75,
    lineOpacity: 0.3,
    indexOpacity: 0.5,
  },
}

export function contourLayerIds(kind) {
  return [
    `contours-${kind}-line`,
    `contours-${kind}-index`,
    `contours-${kind}-label`,
  ]
}

/**
 * Add one treatment's layer set (idempotent) and set its visibility.
 *
 * `beforeId` (optional) anchors the linework below chrome layers —
 * callers pass the first place-label layer so contours never sit on
 * top of text or tactical symbols.
 */
export function ensureContourLayers(map, kind, visible, beforeId = undefined) {
  const t = TREATMENTS[kind]
  if (!t) throw new Error(`unknown contour treatment: ${kind}`)
  ensureContourSource(map)
  const [lineId, indexId, labelId] = contourLayerIds(kind)
  const before = beforeId && map.getLayer(beforeId) ? beforeId : undefined

  if (!map.getLayer(lineId)) {
    map.addLayer({
      id: lineId,
      type: 'line',
      source: CONTOUR_SOURCE_ID,
      'source-layer': CONTOUR_SOURCE_LAYER,
      minzoom: CONTOUR_MINZOOM,
      filter: ['==', ['get', 'level'], 0],
      layout: { 'line-join': 'round' },
      paint: {
        'line-color': t.line,
        'line-width': t.lineWidth,
        'line-opacity': t.lineOpacity,
      },
    }, before)
  }
  if (!map.getLayer(indexId)) {
    map.addLayer({
      id: indexId,
      type: 'line',
      source: CONTOUR_SOURCE_ID,
      'source-layer': CONTOUR_SOURCE_LAYER,
      minzoom: CONTOUR_MINZOOM,
      filter: ['>', ['get', 'level'], 0],
      layout: { 'line-join': 'round' },
      paint: {
        'line-color': t.index,
        'line-width': t.indexWidth,
        'line-opacity': t.indexOpacity,
      },
    }, before)
  }
  if (!map.getLayer(labelId)) {
    map.addLayer({
      id: labelId,
      type: 'symbol',
      source: CONTOUR_SOURCE_ID,
      'source-layer': CONTOUR_SOURCE_LAYER,
      minzoom: CONTOUR_MINZOOM,
      filter: ['>', ['get', 'level'], 0],
      layout: {
        'symbol-placement': 'line',
        'text-field': ['concat', ['to-string', ['get', 'ele']], ' m'],
        'text-font': ['Noto Sans Italic'],
        'text-size': 10,
        'symbol-spacing': 350,
        'text-padding': 4,
      },
      paint: {
        'text-color': t.label,
        'text-halo-color': t.halo,
        'text-halo-width': 1.4,
      },
    }, before)
  }
  setContourVisibility(map, kind, visible)
}

/** Toggle one treatment's layers (no-op for layers not yet added). */
export function setContourVisibility(map, kind, visible) {
  for (const id of contourLayerIds(kind)) {
    if (map.getLayer(id)) {
      const want = visible ? 'visible' : 'none'
      // Idempotent: an unchanged setLayoutProperty still dirties the
      // style and forces a render - inside the repaint path that is a
      // self-sustaining idle render loop (GPU at 100% on a still map).
      if ((map.getLayoutProperty(id, 'visibility') || 'visible') !== want) {
        map.setLayoutProperty(id, 'visibility', want)
      }
    }
  }
}
