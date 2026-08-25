/**
 * Map style configuration for MapLibre.
 *
 * Basemap sources are server-rendered rasters (JPG for opaque basemaps,
 * PNG for the label overlay) served by geo-agent's unified map API:
 *   GET /geo-api/v1/basemaps                          → catalog metadata
 *   GET /geo-api/v1/tiles/basemap/{id}/{z}/{x}/{y}.jpg → rendered basemap
 *   GET /geo-api/v1/tiles/labels/{z}/{x}/{y}.png       → English labels
 *
 * Basemap flavors: `default` (SITEMP-doctrine bland — trunk/motorway
 * + hydrology + boundaries + hillshade), `terrain` (MCOO-doctrine
 * hatched restricted-/severely-restricted-/urban_area terrain +
 * hillshade), `satellite` (ESRI World Imagery via nginx proxy_cache).
 *
 * Underneath: tileserver-gl v5 range-fetches vector features from
 * Protomaps' public planet PMTiles + terrain-dem raster from Mapterhorn,
 * bakes hillshade into the rendered raster. Frontend never sees vector
 * `.pbf`, glyph `.pbf`, or the underlying tile schema — just pre-rendered
 * rasters + a small JSON catalog. Overlay features (mil units, EAs, AAs,
 * PLs, NAIs, range fans, threat overlays, control measures) continue to
 * flow as GeoJSON through /api/v1/map/state and paint client-side on top
 * of whichever basemap the analyst selected.
 */

// Base URL for geo-agent's unified map API. Defaults to /geo-api/v1
// (nginx proxies to geo-agent's /api/v1). Must be absolute — MapLibre
// fetches tiles from web workers which lack page origin.
const _api = import.meta.env.VITE_GEO_AGENT_API_URL || '/geo-api/v1'
export const API_BASE = _api.startsWith('/') ? `${window.location.origin}${_api}` : _api

// Hardcoded catalog mirroring geo-agent GET /api/v1/basemaps. Backend
// endpoint stays the canonical source of truth for external consumers
// (LayerSwitcher UI can fetch it); frontend uses these constants so
// MAP_STYLE stays synchronous and the map renders without a network
// round-trip on first paint.
const BASEMAP_CATALOG = [
  { id: 'default',   name: 'Default',   minzoom: 0, maxzoom: 14 },
  { id: 'terrain',   name: 'Terrain',   minzoom: 0, maxzoom: 14 },
  { id: 'topo',      name: 'Topo',      minzoom: 0, maxzoom: 14 },
  { id: 'satellite', name: 'Satellite', minzoom: 0, maxzoom: 19 },
]

// Per-basemap background paint — the color that shows in tile-load
// gaps and beyond each raster's maxzoom. GeoAgentMap swaps it on
// basemap switch so the paper-white topo sheet doesn't flash cream
// (and satellite doesn't flash paper) while tiles stream in. Keys
// match BASEMAP_CATALOG ids; the style ships with the default.
export const BASEMAP_BACKGROUNDS = {
  default: '#f0e4d4',
  terrain: '#f0e4d4',
  topo: '#f7f4ec',
  satellite: '#0b0b0b',
}

// Client-side place labels read from a VECTOR source (the same Protomaps
// basemap PMTiles, served raw by tileserver-gl at /data/basemap/*.pbf and
// proxied + disk-cached by nginx at /geo-api/v1/tiles/vector/basemap/).
// This replaces the retired server-rendered raster labels overlay: raster
// labels are baked into the tile and rotate with it (unreadable when the
// analyst rotates the map), whereas MapLibre symbol layers keep their text
// upright and reposition on rotation. Decluttering is driven by Protomaps'
// own `min_zoom` importance ranking (big cities carry a low min_zoom and
// appear early; villages a high one and appear only when zoomed in), so
// the operational view stays doctrinally bland without hundreds of village
// names.
const PLACES_VECTOR_SOURCE_ID = 'places-vector'
const PLACES_VECTOR_TILE_URL = `${API_BASE}/tiles/vector/basemap/{z}/{x}/{y}.pbf`

// BASE_MAP_SOURCES + DEFAULT_BASE_MAP retain their historical shape so
// LayerSwitcher + GeoAgentProvider callers don't need to change: the
// object is keyed by basemap id, each entry has { id, name, tiles,
// tileSize, minzoom, maxzoom }.
const BASE_MAPS = Object.fromEntries(
  BASEMAP_CATALOG.map(b => [b.id, {
    id: b.id,
    name: b.name,
    type: 'raster',
    tiles: [`${API_BASE}/tiles/basemap/${b.id}/{z}/{x}/{y}.jpg`],
    tileSize: 256,
    minzoom: b.minzoom,
    maxzoom: b.maxzoom,
  }])
)

export const BASE_MAP_SOURCES = BASE_MAPS
export const DEFAULT_BASE_MAP = 'default'

// Basemap MapLibre sources block. One raster source per basemap; only
// the active one is visible at any moment (LayerSwitcher toggles the
// `visibility` layout property on the corresponding layer).
const basemapSources = Object.fromEntries(
  BASEMAP_CATALOG.map(b => [b.id, {
    type: 'raster',
    tiles: [`${API_BASE}/tiles/basemap/${b.id}/{z}/{x}/{y}.jpg`],
    tileSize: 256,
    minzoom: b.minzoom,
    maxzoom: b.maxzoom,
  }])
)

// Vector source feeding the client-side place-label symbol layers.
const placesVectorSource = {
  type: 'vector',
  tiles: [PLACES_VECTOR_TILE_URL],
  minzoom: 0,
  maxzoom: 15,
}

// Client-side place-label symbol layers, filtered by Protomaps'
// `min_zoom` prominence rank (countries/capitals carry small values,
// villages large ones — Osaka is ~3, a hamlet ~12). The LayerSwitcher
// "Labels" master toggle gates both layers' visibility; the label
// DETAIL SLIDER caps prominence via setFilter with these builders —
// one source of truth for the filter shapes, so the style's initial
// filters and the runtime slider rebuilds can never drift.
export const LABEL_DETAIL_MAX = 15  // slider "All" — no prominence cap

const _REGION_MINZOOM = ['coalesce', ['to-number', ['get', 'min_zoom']], 0]
const _LOCALITY_MINZOOM = ['coalesce', ['to-number', ['get', 'min_zoom']], 15]

// detailCap: only places at least this prominent (min_zoom <= cap)
// render. The per-layer zoom gates (region: natural min_zoom; locality:
// min_zoom - 1 bias) keep the current-zoom declutter regardless of cap.
export function placeLabelFilters(detailCap = LABEL_DETAIL_MAX) {
  return {
    'places-region-labels': ['all',
      ['match', ['get', 'kind'], ['country', 'region'], true, false],
      ['<=', _REGION_MINZOOM, ['zoom']],
      ['<=', _REGION_MINZOOM, detailCap],
    ],
    'places-locality-labels': ['all',
      ['==', ['get', 'kind'], 'locality'],
      ['<=', _LOCALITY_MINZOOM, ['-', ['zoom'], 1]],
      ['<=', _LOCALITY_MINZOOM, detailCap],
    ],
  }
}

const _INITIAL_LABEL_FILTERS = placeLabelFilters()

export const PLACE_LABEL_LAYERS = [
  {
    id: 'places-region-labels',
    type: 'symbol',
    source: PLACES_VECTOR_SOURCE_ID,
    'source-layer': 'places',
    filter: _INITIAL_LABEL_FILTERS['places-region-labels'],
    layout: {
      'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
      'text-font': ['Noto Sans Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 3, 11, 7, 14, 10, 17],
      'text-transform': 'uppercase',
      'text-letter-spacing': 0.08,
      'text-max-width': 8,
    },
    paint: {
      'text-color': '#6a6a6a',
      'text-halo-color': 'rgba(255,255,255,0.85)',
      'text-halo-width': 1.2,
    },
  },
  {
    id: 'places-locality-labels',
    type: 'symbol',
    source: PLACES_VECTOR_SOURCE_ID,
    'source-layer': 'places',
    filter: _INITIAL_LABEL_FILTERS['places-locality-labels'],
    layout: {
      'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
      'text-font': ['Noto Sans Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 6, 11, 10, 13, 14, 16],
      'text-max-width': 7,
      'text-padding': 3,
    },
    paint: {
      'text-color': '#2a2a2a',
      'text-halo-color': 'rgba(255,255,255,0.85)',
      'text-halo-width': 1.2,
    },
  },
]

// --- Exports ---

export const MAP_STYLE = {
  version: 8,
  // Protomaps' public glyph server. Required by any symbol layer that
  // sets `text-field` (analyst chrome uses this for the tidat-pushed-
  // badges 'T' badge). Without it, MapLibre queues the layers' text
  // fetches against an undefined URL and never marks the style loaded
  // (`isStyleLoaded()` stays false forever) — the map then never
  // fires its initial repaint and the analyst sees the empty
  // background color instead of the basemap.
  glyphs: 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
  sources: {
    ...basemapSources,
    [PLACES_VECTOR_SOURCE_ID]: placesVectorSource,
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#f0e4d4' } },
    // Basemap raster layers — LayerSwitcher toggles `visibility` on these
    // to swap between default / terrain / satellite. Only `default` is
    // visible on first load.
    ...BASEMAP_CATALOG.map(b => ({
      id: b.id,
      type: 'raster',
      source: b.id,
      layout: { visibility: b.id === DEFAULT_BASE_MAP ? 'visible' : 'none' },
      paint: { 'raster-fade-duration': 0 },
    })),
    // Client-side vector place labels on top — upright + rotating,
    // decluttered by Protomaps min_zoom. Replaces the retired raster
    // labels PNG overlay.
    ...PLACE_LABEL_LAYERS,
  ],
}

// Estonia AO (south Estonia — Voru/Valga/Pikasilla/Tartu, 35V MGRS).
export const DEFAULT_CENTER = [26.82, 57.96]
export const DEFAULT_ZOOM = 8

// MapboxDraw styles for overlay drawing
export const DRAW_STYLES = [
  { id: 'gl-draw-polygon-fill',   type: 'fill',   filter: ['all', ['==', '$type', 'Polygon'],    ['!=', 'mode', 'static']], paint: { 'fill-color': '#0000FF', 'fill-opacity': 0.15 } },
  { id: 'gl-draw-polygon-stroke', type: 'line',   filter: ['all', ['==', '$type', 'Polygon'],    ['!=', 'mode', 'static']], paint: { 'line-color': '#0000FF', 'line-width': 3 } },
  { id: 'gl-draw-line',           type: 'line',   filter: ['all', ['==', '$type', 'LineString'], ['!=', 'mode', 'static']], paint: { 'line-color': '#0000FF', 'line-width': 4 } },
  { id: 'gl-draw-point',          type: 'circle', filter: ['all', ['==', '$type', 'Point'], ['==', 'meta', 'feature']],     paint: { 'circle-radius': 8, 'circle-color': '#0000FF' } },
  { id: 'gl-draw-polygon-and-line-vertex-active', type: 'circle', filter: ['all', ['==', 'meta', 'vertex'],   ['==', '$type', 'Point']], paint: { 'circle-radius': 6, 'circle-color': '#ffffff', 'circle-stroke-color': '#0000FF', 'circle-stroke-width': 2 } },
  { id: 'gl-draw-polygon-midpoint',               type: 'circle', filter: ['all', ['==', 'meta', 'midpoint'], ['==', '$type', 'Point']], paint: { 'circle-radius': 4, 'circle-color': '#0000FF', 'circle-opacity': 0.7 } },
]

// Affiliation colors for tactical graphics
export const AFFILIATION_COLORS = {
  Friend:  '#0000FF',
  Hostile: '#FF0000',
  Neutral: '#00FF00',
  Unknown: '#FFFF00',
}

export const AFFILIATION_POPUP_COLORS = {
  Friend:  '#80e0ff',
  Hostile: '#ff8080',
  Neutral: '#80ff80',
  Unknown: '#ffff80',
}
