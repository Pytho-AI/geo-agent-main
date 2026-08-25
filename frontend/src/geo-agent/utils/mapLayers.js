/**
 * Map layer definitions for entities, military units, and tactical graphics
 */

/**
 * Add all map layers for entities and tactical graphics
 * @param {Object} map - MapLibre map instance
 */
export function addMapLayers(map) {
  addEntityLayers(map)
  addTacticalGraphicsLayers(map)
}

/**
 * Add drawing preview layers (shows tactical graphic while drawing)
 * Called AFTER MapboxDraw is initialized so they appear on top
 * @param {Object} map - MapLibre map instance
 */
export function addDrawingPreviewLayers(map) {
  // Preview fill (for area overlays)
  map.addLayer({
    id: 'drawing-preview-fill',
    type: 'fill',
    source: 'drawing-preview',
    filter: ['==', '$type', 'Polygon'],
    paint: {
      'fill-color': ['coalesce', ['get', 'fillColor'], '#0000FF'],
      'fill-opacity': 0.15
    }
  })

  // Preview lines
  map.addLayer({
    id: 'drawing-preview-lines',
    type: 'line',
    source: 'drawing-preview',
    filter: ['any', ['==', '$type', 'LineString'], ['==', '$type', 'Polygon']],
    paint: {
      'line-color': ['coalesce', ['get', 'strokeColor'], '#0000FF'],
      'line-width': 3
    }
  })

  // Preview symbols (for patterns like wire obstacles)
  map.addLayer({
    id: 'drawing-preview-symbols',
    type: 'symbol',
    source: 'drawing-preview',
    filter: ['==', '$type', 'Point'],
    layout: {
      'icon-image': ['get', 'iconId'],
      'icon-size': 1,
      'icon-allow-overlap': true
    }
  })
}

/**
 * Add entity layers (points, polygons, labels)
 */
function addEntityLayers(map) {
  // Entity points layer (skip custom_symbol — painted as HTML <img> markers)
  map.addLayer({
    id: 'entities-points',
    type: 'circle',
    source: 'entities',
    filter: ['all', ['==', '$type', 'Point'], ['!=', 'kind', 'custom_symbol']],
    paint: {
      'circle-radius': 8,
      'circle-color': '#3B82F6',
      'circle-stroke-width': 2,
      'circle-stroke-color': '#fff'
    }
  })

  // Entity point labels
  map.addLayer({
    id: 'entities-labels',
    type: 'symbol',
    source: 'entities',
    filter: ['all', ['==', '$type', 'Point'], ['!=', 'kind', 'custom_symbol']],
    layout: {
      'text-field': ['coalesce', ['get', 'name'], ['get', 'kind']],
      // Protomaps glyph server ships Noto Sans, not Open Sans.
      'text-font': ['Noto Sans Regular'],
      'text-size': 12,
      'text-offset': [0, 1.5],
      'text-anchor': 'top',
      'text-max-width': 10
    },
    paint: {
      'text-color': '#ffffff',
      'text-halo-color': '#16213e',
      'text-halo-width': 2
    }
  })

  // Entity polygons layer - exclude country/state (they clutter the map)
  map.addLayer({
    id: 'entities-polygons',
    type: 'fill',
    source: 'entities',
    filter: ['all',
      ['==', '$type', 'Polygon'],
      ['!in', 'kind', 'country', 'state']
    ],
    paint: {
      'fill-color': ['match', ['get', 'kind'],
        'lake', '#4a90d9',
        '#3B82F6'
      ],
      'fill-opacity': ['match', ['get', 'kind'],
        'lake', 0.6,
        0.3
      ]
    }
  })

  // Entity polygon outlines - exclude country/state
  map.addLayer({
    id: 'entities-polygons-outline',
    type: 'line',
    source: 'entities',
    filter: ['all',
      ['==', '$type', 'Polygon'],
      ['!in', 'kind', 'country', 'state']
    ],
    paint: {
      'line-color': ['match', ['get', 'kind'],
        'lake', '#2d6ba3',
        '#3B82F6'
      ],
      'line-width': 1
    }
  })

  // Invisible-but-hit-testable layer for the mil-units source. The
  // visible mil-unit paint lives in the doctrinal SVG (MapDoctrinalPaint
  // dispatches createMilSymbol via PRIMITIVE_DRAWERS, painted as
  // ATP 2-01.3 focal-point glyphs above every other layer). MapLibre
  // doesn't paint the symbol itself, but useMapEvents binds
  // `mousedown` to a layer id `mil-units-symbols` for drag-to-move, and
  // `map.on('mousedown', layerId, ...)` requires the layer to EXIST in
  // the style or the listener never matches. This circle covers each
  // unit point at the milsymbol icon's footprint (~size=40 = 60×76 px)
  // with circle-opacity 0 so the SVG glyph is visible underneath.
  map.addLayer({
    id: 'mil-units-symbols',
    type: 'circle',
    source: 'mil-units',
    filter: ['==', '$type', 'Point'],
    paint: {
      // FALLBACK hit target only — the drawn frame boxes
      // (map.__milUnitHitBoxes, tested first in useMapEvents) are the
      // authoritative targets. 30 px circles overlapped neighboring
      // symbols in dense clusters and claimed their clicks.
      'circle-radius': 16,
      'circle-opacity': 0,
      'circle-stroke-width': 0,
    },
  })
}

/**
 * Add tactical graphics layers (fills, lines, labels, symbols)
 */
function addTacticalGraphicsLayers(map) {
  // Invisible hit-target layer for lines (wide transparent area for easier clicking)
  map.addLayer({
    id: 'tactical-graphics-hit-target',
    type: 'line',
    source: 'tactical-graphics',
    filter: ['any', ['==', '$type', 'LineString'], ['==', '$type', 'Polygon']],
    paint: {
      'line-color': 'transparent',
      'line-width': 24  // Wide hit area for easy clicking
    }
  })

  // @deprecated — MOVEMENT_ARROW_REDESIGN.md §2.3 + step 3.
  // All visible paint moved to SVG paintTacticalGraphics. These layers are
  // kept (definitions, source binding) so hit-testing / source attachment
  // stays consistent, but they paint nothing. Final removal happens in the
  // step-6 cleanup pass once SVG coverage is verified across every product.
  map.addLayer({
    id: 'tactical-graphics-fill',
    type: 'fill',
    source: 'tactical-graphics',
    filter: ['==', '$type', 'Polygon'],
    paint: { 'fill-opacity': 0 }
  })

  // @deprecated — replaced by SVG primitives (filled_corridor_with_arrowhead,
  // hollow_outline_arrow, single_shaft_line, phase_line, paired_aviation_rails,
  // bowtie_bounded_polyline, closed_polygon_with_label).
  map.addLayer({
    id: 'tactical-graphics-lines',
    type: 'line',
    source: 'tactical-graphics',
    filter: ['any', ['==', '$type', 'LineString'], ['==', '$type', 'Polygon']],
    paint: { 'line-opacity': 0 }
  })

  // @deprecated — folded into drawClosedPolygonWithLabel.
  map.addLayer({
    id: 'tactical-graphics-area-type-labels',
    type: 'symbol',
    source: 'tactical-graphics',
    filter: ['==', '$type', 'LineString'],
    layout: { 'text-field': '' },
    paint: { 'text-opacity': 0 }
  })

  // @deprecated — folded into drawClosedPolygonWithLabel.
  map.addLayer({
    id: 'tactical-graphics-area-name-labels',
    type: 'symbol',
    source: 'tactical-graphics',
    filter: ['==', '$type', 'Point'],
    layout: { 'text-field': '' },
    paint: { 'text-opacity': 0 }
  })

  // @deprecated — folded into drawClosedPolygonWithLabel + drawClosedGlyph.
  map.addLayer({
    id: 'tactical-graphics-polygon-labels',
    type: 'symbol',
    source: 'tactical-graphics',
    filter: ['==', '$type', 'Polygon'],
    layout: { 'text-field': '' },
    paint: { 'text-opacity': 0 }
  })

  // @deprecated — folded into drawClosedPolygonWithLabel.
  map.addLayer({
    id: 'tactical-graphics-polygon-type-labels',
    type: 'symbol',
    source: 'tactical-graphics',
    filter: ['==', '$type', 'Polygon'],
    layout: { 'text-field': '' },
    paint: { 'text-opacity': 0 }
  })

  // @deprecated — replaced by drawMarkerGlyph / drawClosedGlyph.
  map.addLayer({
    id: 'tactical-graphics-symbols',
    type: 'symbol',
    source: 'tactical-graphics',
    filter: ['==', '$type', 'Point'],
    layout: {},
    paint: { 'icon-opacity': 0 }
  })
}
