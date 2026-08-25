/**
 * Doctrinal road overlay paint (FM 1-02.2 topo-cartographic conventions).
 *
 * Reused by every product that ships transportation paint — MCOO, SITEMP,
 * Threat Overlay, GRINTSUM, TMP, Threat COA Statement. (Originally ported from
 * geo-agent/backend/app/static/render.html `addRoadLayers` ~1259-1326.)
 *
 * The `graphics-road-*` source/layer IDs are legacy wire format — kept stable
 * so the harness / parity probes addressing layers by name keep working
 * through the rename pass.
 *
 * OSM-derived roads grouped into 4 doctrinal classes:
 *
 *   major       motorway/trunk/primary   7px black casing + 4.5px yellow body
 *   secondary   secondary/tertiary       4.5px black casing + 2.8px white body
 *   minor       residential/unclassified 2.4px solid grey
 *   track       track                    1.8px dashed brown
 *
 * Stacking order: track + minor go down first so they sit UNDER secondary
 * and major. Within each class casing-then-body so the body covers the
 * casing's interior. All caps + joins round to mimic topo-map cartography.
 *
 * No road labels at corps view: the label-collision registry only tracks
 * point glyphs (units, key terrain, choke points). Adding ~20k line-label
 * candidates would either explode the registry or produce stacked,
 * unreadable text. Roads are visually identifiable by class color alone.
 */

const SOURCE_IDS = [
  'graphics-road-track',
  'graphics-road-minor',
  'graphics-road-secondary',
  'graphics-road-major',
]

const LAYER_IDS = [
  'graphics-road-track-line',
  'graphics-road-minor-line',
  'graphics-road-secondary-casing',
  'graphics-road-secondary-body',
  'graphics-road-major-casing',
  'graphics-road-major-body',
]

/**
 * Add the four-class doctrinal road paint stack to a MapLibre map.
 * Idempotent: removes any prior road sources/layers before recreating.
 *
 * @param {Object} map - MapLibre map instance.
 * @param {Array} features - GeoJSON features with property `highway_class`
 *   in {major, secondary, minor, track}.
 */
export function applyDoctrinalRoadLayers(map, features) {
  if (!map) return

  removeDoctrinalRoadLayers(map)

  const byClass = { major: [], secondary: [], minor: [], track: [] }
  for (const f of features || []) {
    const c = f.properties && f.properties.highway_class
    if (byClass[c]) byClass[c].push(f)
  }

  // -- Track (dashed brown, narrow) — UNDER everything --
  if (byClass.track.length) {
    map.addSource('graphics-road-track', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byClass.track },
    })
    map.addLayer({
      id: 'graphics-road-track-line',
      source: 'graphics-road-track',
      type: 'line',
      layout: { 'line-cap': 'butt', 'line-join': 'round' },
      paint: {
        'line-color': '#6b4423',
        'line-width': 1.8,
        'line-dasharray': [3, 2],
        'line-opacity': 1.0,
      },
    })
  }

  // -- Minor (solid grey, narrow) --
  if (byClass.minor.length) {
    map.addSource('graphics-road-minor', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byClass.minor },
    })
    map.addLayer({
      id: 'graphics-road-minor-line',
      source: 'graphics-road-minor',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#4a4a4a',
        'line-width': 2.4,
        'line-opacity': 1.0,
      },
    })
  }

  // -- Secondary (black casing + white body) --
  if (byClass.secondary.length) {
    map.addSource('graphics-road-secondary', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byClass.secondary },
    })
    map.addLayer({
      id: 'graphics-road-secondary-casing',
      source: 'graphics-road-secondary',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#000000', 'line-width': 4.5 },
    })
    map.addLayer({
      id: 'graphics-road-secondary-body',
      source: 'graphics-road-secondary',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#ffffff', 'line-width': 2.8 },
    })
  }

  // -- Major (black casing + warm yellow body) — TOP of road stack --
  if (byClass.major.length) {
    map.addSource('graphics-road-major', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byClass.major },
    })
    map.addLayer({
      id: 'graphics-road-major-casing',
      source: 'graphics-road-major',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#000000', 'line-width': 7.0 },
    })
    map.addLayer({
      id: 'graphics-road-major-body',
      source: 'graphics-road-major',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#fff8c4', 'line-width': 4.5 },
    })
  }
}

/**
 * Remove all road layers and sources, idempotent.
 */
export function removeDoctrinalRoadLayers(map) {
  if (!map) return
  for (const id of LAYER_IDS) {
    if (map.getLayer(id)) map.removeLayer(id)
  }
  for (const id of SOURCE_IDS) {
    if (map.getSource(id)) map.removeSource(id)
  }
}
