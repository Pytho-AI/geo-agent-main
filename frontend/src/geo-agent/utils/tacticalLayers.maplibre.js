/**
 * Doctrinal control-measure paint (MapLibre source/layer pipeline).
 *
 * Reused by every product that paints doctrinal control measures —
 * MCOO, SITEMP, Threat Overlay, GRINTSUM, TMP, Threat COA Statement. (Originally ported from
 * `addMcooLayers` in geo-agent/backend/app/static/render.html ~850-1239.)
 *
 * The `graphics-*` source / layer / image IDs are legacy wire format — kept
 * stable so the harness / parity probes (which queryRenderedFeatures by
 * layer id) keep working through the rename pass.
 *
 * Splits overlay features by `properties.kind` and paints each into its
 * own MapLibre source + layer set with discrete doctrinal styling.
 *
 * Splits handled here (everything paintable via MapLibre style — no SVG
 * overlay):
 *
 *   restricted_terrain / mobility_slow_go    light-green base + diagonal hatch
 *   severely_restricted_terrain / mobility_no_go  deep-green base + cross hatch
 *                                                 (extra alpha for subkind=water)
 *   mobility_go                              thin dashed green outline
 *   hydrology_obstacle                       white halo + dark-blue cased + lighter-blue body
 *   road                                     delegated to applyDoctrinalRoadLayers
 *   urban_area                               black-X hatch pattern + black outline
 *   engagement_area (polygon)                hostile=red dashed / friendly=black outline
 *   objective (polygon)                      thin black outline
 *   named_area_of_interest (polygon)         thin black outline
 *   targeted_area_of_interest (polygon)      thin black DASHED outline
 *   phase_line                               heavy black line
 *   obstacle_belt                            heavy black line (chevron teeth painted via SVG overlay)
 *   intervisibility_line                     dashed black line
 *   boundary                                 white halo + black line w/ FLOT/FEBA dashes
 *   battle_position                          translucent fill + 3.2px line, side-keyed (hostile=red/friendly=blue)
 *   fire_support_coord_measure               white halo + dashed black line
 *   assembly_area (polygon)                  2.2px black outline
 *   restricted_op_zone (polygon)             2.4px dashed black outline
 *
 * Point-geometry features for engagement_area / objective /
 * named_area_of_interest / targeted_area_of_interest are stashed on the
 * map for the SVG overlay pass (see tacticalGraphics.svg.js) which paints
 * doctrinal box / kidney / hex glyphs at the centroid.
 *
 * Also stashes feature lists for the SVG overlay pass under
 * choke_point, obstacle_point, direction_of_attack, strong_point,
 * decision_point, air_corridor, phase_line, boundary, battle_position,
 * fire_support_coord_measure, assembly_area, restricted_op_zone, and
 * the urban_area centroid label list).
 */

import { registerTerrainHatches } from './terrainHatches'
import { applyDoctrinalRoadLayers, removeDoctrinalRoadLayers } from './doctrinalRoadPaint'

// Every source we own. Used by the idempotent remove pass before re-add.
const MCOO_SOURCE_IDS = [
  'graphics-restricted',
  'graphics-severe',
  'graphics-go',
  'graphics-hydro',
  'graphics-urban',
  'graphics-ea',
  'graphics-obj',
  'graphics-nai',
  'graphics-tai',
  'graphics-pl',
  'graphics-obs-belt',
  'graphics-iv',
  'graphics-bnd',
  'graphics-bp',
  'graphics-fscm',
  'graphics-aaarea',
  'graphics-roz',
  // Unified invisible click-hit source for every point-glyph feature
  // whose visual is painted in MapDoctrinalPaint's SVG layer (NAI/TAI/
  // OBJ/EA points, key terrain, choke points, obstacle points, strong
  // points, decision points). Without this, the editor's
  // queryRenderedFeatures call in useMapEvents wouldn't see these
  // features because the SVG paint has pointer-events: none and the
  // tactical-graphics pipeline only ingests features that carry a
  // SIDC. See useMapEvents.js overlayLayers list.
  'graphics-points-hit-target',
]

// Every layer we own.
const MCOO_LAYER_IDS = [
  'graphics-restricted-base',
  'graphics-restricted-fill',
  'graphics-restricted-line',
  'graphics-severe-base',
  'graphics-severe-fill',
  'graphics-severe-line',
  'graphics-go-line',
  'graphics-hydro-halo',
  'graphics-hydro-casing',
  'graphics-hydro-body',
  'graphics-urban-fill',
  'graphics-urban-line',
  'graphics-ea-fill',
  'graphics-ea-line',
  'graphics-ea-line-hostile',
  'graphics-obj-line',
  'graphics-nai-line',
  'graphics-tai-line',
  'graphics-pl-line',
  'graphics-obs-belt-line',
  'graphics-iv-line',
  'graphics-bnd-halo',
  'graphics-bnd-line',
  'graphics-bnd-line-flot',
  'graphics-bp-fill',
  'graphics-bp-line',
  'graphics-fscm-halo',
  'graphics-fscm-line',
  'graphics-aaarea-line',
  'graphics-roz-line',
  'graphics-points-hit-target',
]

// Stash keys we attach to the map instance for the SVG overlay pass.
// Listed here so removeDoctrinalControlMeasures can clear them in one place.
const STASH_KEYS = [
]

/**
 * Apply doctrinal control-measure paint to the given map, replacing any
 * prior set. Reused by MCOO, SITEMP, Threat Overlay, GRINTSUM, TMP, Threat COA Statement.
 *
 * @param {Object} map - MapLibre map instance.
 * @param {Array} features - Overlay GeoJSON features (full feature list;
 *   we split on properties.kind internally).
 */
export function applyDoctrinalControlMeasures(map, features) {
  if (!map) return

  removeDoctrinalControlMeasures(map)

  // Patterns must be registered before any fill-pattern layer references them.
  registerTerrainHatches(map)

  // Bucket by kind, folding legacy mobility_no_go / mobility_slow_go aliases
  // into the modern doctrinal terms.
  const LINE_KINDS = new Set([
    'phase_line', 'boundary', 'fire_support_coord_measure',
    'main_supply_route', 'alternate_supply_route', 'route', 'air_corridor',
  ])
  const byKind = {}
  for (const f of features || []) {
    let k = f.properties && f.properties.kind
    if (!k) continue
    // Nothing to render -> nothing to stash: a feature with no geometry
    // must never reach a MapLibre source or an SVG drawer.
    if (!f.geometry || f.geometry.coordinates == null) continue
    // A line kind with non-line geometry never enters the stream: a
    // Point's [lon, lat] passes length checks and feeds a bare number
    // into map.project inside the label drawers (the FSCL-endpoint
    // crash that killed map interaction). Closed shapes (Polygon /
    // MultiPolygon) are NOT drawn here either — the catalog stamps a
    // polygon-class primitive (`primitive_polygon`, e.g.
    // closed_polygon_with_label on boundary and
    // fire_support_coord_measure) and the SVG primitive dispatch owns
    // the complete drawing, ring and label. A polygon kind that does
    // not paint gets a primitive in constants/overlays.py — never a
    // geometry-conversion fallback in this layer.
    if (LINE_KINDS.has(k) && f.geometry.type !== 'LineString'
        && f.geometry.type !== 'MultiLineString') continue
    if (k === 'mobility_no_go') k = 'severely_restricted_terrain'
    else if (k === 'mobility_slow_go') k = 'restricted_terrain'
    ;(byKind[k] = byKind[k] || []).push(f)
  }

  // -- Restricted terrain (light green base + diagonal hatch) --
  if (byKind.restricted_terrain) {
    map.addSource('graphics-restricted', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.restricted_terrain },
    })
    map.addLayer({
      id: 'graphics-restricted-base',
      source: 'graphics-restricted',
      type: 'fill',
      paint: { 'fill-color': '#4a9a4d', 'fill-opacity': 0.22 },
    })
    map.addLayer({
      id: 'graphics-restricted-fill',
      source: 'graphics-restricted',
      type: 'fill',
      paint: { 'fill-pattern': 'graphics-pat-restricted', 'fill-opacity': 0.88 },
    })
    map.addLayer({
      id: 'graphics-restricted-line',
      source: 'graphics-restricted',
      type: 'line',
      paint: { 'line-color': '#1a4d1f', 'line-width': 1.0, 'line-opacity': 0.9 },
    })
  }

  // -- Severely restricted terrain (deeper green base + crossed hatch).
  // subkind=water gets extra base alpha + full hatch alpha so lakes read
  // as NO-GO over the basemap blue.
  if (byKind.severely_restricted_terrain) {
    map.addSource('graphics-severe', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.severely_restricted_terrain },
    })
    map.addLayer({
      id: 'graphics-severe-base',
      source: 'graphics-severe',
      type: 'fill',
      paint: {
        'fill-color': [
          'case',
          ['==', ['get', 'subkind'], 'water'], '#2c5f3a',
          '#3f7c40',
        ],
        'fill-opacity': [
          'case',
          ['==', ['get', 'subkind'], 'water'], 0.62,
          0.30,
        ],
      },
    })
    map.addLayer({
      id: 'graphics-severe-fill',
      source: 'graphics-severe',
      type: 'fill',
      paint: {
        'fill-pattern': 'graphics-pat-severe',
        'fill-opacity': [
          'case',
          ['==', ['get', 'subkind'], 'water'], 1.0,
          0.85,
        ],
      },
    })
    map.addLayer({
      id: 'graphics-severe-line',
      source: 'graphics-severe',
      type: 'line',
      paint: { 'line-color': '#143f17', 'line-width': 1.4, 'line-opacity': 0.95 },
    })
  }

  // -- GO (unrestricted) terrain: dashed outline only --
  if (byKind.mobility_go) {
    map.addSource('graphics-go', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.mobility_go },
    })
    map.addLayer({
      id: 'graphics-go-line',
      source: 'graphics-go',
      type: 'line',
      paint: {
        'line-color': '#0f5223',
        'line-width': 1,
        'line-opacity': 0.4,
        'line-dasharray': [3, 3],
      },
    })
  }

  // -- Hydrology obstacles (rivers). White halo + dark-blue casing + lighter blue body.
  // Painted before roads + urban so transportation/urban X-fill sit on top.
  if (byKind.hydrology_obstacle) {
    map.addSource('graphics-hydro', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.hydrology_obstacle },
    })
    map.addLayer({
      id: 'graphics-hydro-halo',
      source: 'graphics-hydro',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#fff', 'line-width': 8, 'line-opacity': 0.7 },
    })
    map.addLayer({
      id: 'graphics-hydro-casing',
      source: 'graphics-hydro',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#0a3a8a', 'line-width': 5 },
    })
    map.addLayer({
      id: 'graphics-hydro-body',
      source: 'graphics-hydro',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#3b82f6', 'line-width': 3 },
    })
  }

  // -- Roads (delegated; widening order ensures casing stack is correct). --
  //
  // MCOO is a terrain-analysis product — every road class is doctrinally
  // significant for mobility classification, so paint all four classes
  // (major/secondary/minor/track). For SITEMP / Threat Overlay / Event_Template /
  // DST / GRINTSUM, the doctrinal focus is enemy disposition + decision
  // points, NOT the road network — the omt-sitemp basemap already shows
  // motorway/trunk for movement context. Painting the full 4-class
  // doctrinal road stack on top creates the "spiderweb of paved/dirt
  // roads" visual clutter the analyst sees on a SITEMP. Skip the road
  // overlay entirely for products where roads are context-only.
  // Road overlay: paint if road features made it through the schema
  // filter at the backend. SITEMP-style products that omit "road" from
  // map_overlay_kinds receive nothing and the overlay stays off.
  if (byKind.road) {
    applyDoctrinalRoadLayers(map, byKind.road)
  }

  // -- Urban built-up areas (bold black X cells over white tint) --
  // Painted after roads so urban X-fill sits on top of road casings inside towns.
  if (byKind.urban_area) {
    map.addSource('graphics-urban', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.urban_area },
    })
    map.addLayer({
      id: 'graphics-urban-fill',
      source: 'graphics-urban',
      type: 'fill',
      paint: { 'fill-pattern': 'graphics-pat-urban', 'fill-opacity': 1.0 },
    })
    map.addLayer({
      id: 'graphics-urban-line',
      source: 'graphics-urban',
      type: 'line',
      paint: { 'line-color': '#000', 'line-width': 2 },
    })
  }

  // -- Engagement areas (polygon path; hostile=red translucent / friendly=black outline). --
  // Point-geometry EAs stashed for SVG overlay drawer.
  if (byKind.engagement_area) {
    const eaPolys = byKind.engagement_area.filter(isPolygonLike)
    const eaPoints = byKind.engagement_area.filter(isPointLike)
    if (eaPolys.length) {
      map.addSource('graphics-ea', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: eaPolys },
      })
      map.addLayer({
        id: 'graphics-ea-fill',
        source: 'graphics-ea',
        type: 'fill',
        paint: {
          'fill-color': ['case', ['==', ['get', 'side'], 'hostile'], '#dc2626', '#000'],
          // Reference SITEMP (ATP 2-01.3 Fig 6-3) shows hostile EAs as
          // medium-red translucent fills — about 30-40% opacity, well
          // above the basemap but transparent enough that units/labels
          // inside the EA stay readable. 0.08 prior was barely visible.
          'fill-opacity': ['case', ['==', ['get', 'side'], 'hostile'], 0.35, 0.0],
        },
      })
      // maplibre-gl v3 rejects data expressions on `line-dasharray` ("data
      // expressions not supported"), which aborts the WHOLE style load —
      // every basemap render through MapDoctrinalPaint silently times out
      // until the offending layer is excised. Split into two filtered
      // layers, each with a literal dasharray:
      //   graphics-ea-line          - non-hostile EAs, solid black
      //   graphics-ea-line-hostile  - hostile EAs, red dashed [4,2]
      // (data expressions on `line-dasharray` land in maplibre-gl v4+, but
      // we're on ^3.6.2 — splitting layers is the only path that keeps
      // visual fidelity AND the headless render alive.)
      map.addLayer({
        id: 'graphics-ea-line',
        source: 'graphics-ea',
        type: 'line',
        filter: ['!=', ['get', 'side'], 'hostile'],
        paint: {
          'line-color': '#000',
          'line-width': 2.4,
        },
      })
      map.addLayer({
        id: 'graphics-ea-line-hostile',
        source: 'graphics-ea',
        type: 'line',
        filter: ['==', ['get', 'side'], 'hostile'],
        paint: {
          'line-color': '#b91c1c',
          'line-width': 2.4,
          'line-dasharray': [4, 2],
        },
      })
    }
  }

  // -- Objectives (polygon outline; point geometry routed to overlay). --
  if (byKind.objective) {
    const objPolys = byKind.objective.filter(isPolygonLike)
    const objPoints = byKind.objective.filter(isPointLike)
    if (objPolys.length) {
      map.addSource('graphics-obj', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: objPolys },
      })
      map.addLayer({
        id: 'graphics-obj-line',
        source: 'graphics-obj',
        type: 'line',
        paint: { 'line-color': '#000', 'line-width': 2.5 },
      })
    }
  }

  // -- Threat objective (filled red circle) — distinct from `objective`
  // (friendly seizure) per ATP 2-01.3. Points only (no polygon path).
  if (byKind.threat_objective) {
    const points = byKind.threat_objective.filter(isPointLike)
  }

  // -- Range fan (concentric red rings) per ATP 2-01.3 Fig 6-3. SVG-only
  // (no MapLibre layer); the SVG re-paint draws variable-radius rings
  // from props.radius_m or props.bands.
  //
  // Reset on every call — the upstream filter (useMapInstance
  // _filterBySource) may exclude all range_fan features (e.g. when no
  // unit is selected and the kind:range_fan disabledSubtype is on, or
  // when click-to-show-range-fans has hidden everyone but the selected
  // unit's fans). Without the unconditional reset the SVG paint pass
  // reads a stale stash and the old fans linger after the filter
  // narrows. Empty stash = empty paint = no stale fans.
  const _fanPoints = (byKind.range_fan || []).filter(isPointLike)

  // -- Named Areas of Interest — solid black square (polygon path). --
  if (byKind.named_area_of_interest) {
    const naiPolys = byKind.named_area_of_interest.filter(isPolygonLike)
    const naiPoints = byKind.named_area_of_interest.filter(isPointLike)
    if (naiPolys.length) {
      map.addSource('graphics-nai', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: naiPolys },
      })
      map.addLayer({
        id: 'graphics-nai-line',
        source: 'graphics-nai',
        type: 'line',
        paint: { 'line-color': '#000', 'line-width': 1.8 },
      })
    }
  }

  // -- Targeted Areas of Interest — dashed black square (polygon path). --
  if (byKind.targeted_area_of_interest) {
    const taiPolys = byKind.targeted_area_of_interest.filter(isPolygonLike)
    const taiPoints = byKind.targeted_area_of_interest.filter(isPointLike)
    if (taiPolys.length) {
      map.addSource('graphics-tai', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: taiPolys },
      })
      map.addLayer({
        id: 'graphics-tai-line',
        source: 'graphics-tai',
        type: 'line',
        paint: {
          'line-color': '#000',
          'line-width': 1.8,
          'line-dasharray': [4, 2],
        },
      })
    }
  }

  // -- Phase lines (heavy black line; PL label drawn in SVG overlay) --
  if (byKind.phase_line) {
    map.addSource('graphics-pl', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.phase_line },
    })
    map.addLayer({
      id: 'graphics-pl-line',
      source: 'graphics-pl',
      type: 'line',
      paint: { 'line-color': '#000', 'line-width': 2 },
    })
  }

  // Stash control-measure features for the overlay drawer to label.
  const cm = []
    .concat(byKind.named_area_of_interest || [])
    .concat(byKind.targeted_area_of_interest || [])
    .concat(byKind.engagement_area || [])
    .concat(byKind.objective || [])

  // -- Obstacle belts (heavy black line; teeth chevron painted in overlay) --
  if (byKind.obstacle_belt) {
    map.addSource('graphics-obs-belt', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.obstacle_belt },
    })
    map.addLayer({
      id: 'graphics-obs-belt-line',
      source: 'graphics-obs-belt',
      type: 'line',
      paint: { 'line-color': '#000', 'line-width': 3 },
    })
  }

  // -- Intervisibility lines (dashed black line) --
  if (byKind.intervisibility_line) {
    map.addSource('graphics-iv', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.intervisibility_line },
    })
    map.addLayer({
      id: 'graphics-iv-line',
      source: 'graphics-iv',
      type: 'line',
      paint: { 'line-color': '#000', 'line-width': 1.2, 'line-dasharray': [2, 2] },
    })
  }

  // Stash features that paint exclusively in the SVG overlay pass.

  // -- Boundaries (FLOT/FEBA dashed, LD/LOA solid; black w/ white halo) --
  if (byKind.boundary) {
    map.addSource('graphics-bnd', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.boundary },
    })
    map.addLayer({
      id: 'graphics-bnd-halo',
      source: 'graphics-bnd',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#fff', 'line-width': 6, 'line-opacity': 0.75 },
    })
    // Split by subkind for the same maplibre-gl v3 limitation noted on
    // graphics-ea-line above — data expressions on `line-dasharray` blow up
    // the entire style. Solid for hard boundaries; dashed [3,2] for the
    // forward-line / FEBA flavor.
    map.addLayer({
      id: 'graphics-bnd-line',
      source: 'graphics-bnd',
      type: 'line',
      filter: ['!', ['any',
        ['==', ['get', 'subkind'], 'flot'],
        ['==', ['get', 'subkind'], 'feba']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#000',
        'line-width': 3.0,
      },
    })
    map.addLayer({
      id: 'graphics-bnd-line-flot',
      source: 'graphics-bnd',
      type: 'line',
      filter: ['any',
        ['==', ['get', 'subkind'], 'flot'],
        ['==', ['get', 'subkind'], 'feba']],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#000',
        'line-width': 3.0,
        'line-dasharray': [3, 2],
      },
    })
  }

  // axis_of_advance — wide blue hatched chevron per ATP 6-0.5 / Annex C.
  // Separate bucket from direction_of_attack so the two render distinctly
  // (DoA = thin red arrow, AoA = wide hatched blue corridor with arrowhead).

  // -- Battle positions: side-keyed translucent fill + bold outline --
  if (byKind.battle_position) {
    map.addSource('graphics-bp', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.battle_position },
    })
    map.addLayer({
      id: 'graphics-bp-fill',
      source: 'graphics-bp',
      type: 'fill',
      paint: {
        'fill-color': ['case', ['==', ['get', 'side'], 'hostile'], '#b91c1c', '#1e40af'],
        'fill-opacity': 0.06,
      },
    })
    map.addLayer({
      id: 'graphics-bp-line',
      source: 'graphics-bp',
      type: 'line',
      paint: {
        'line-color': ['case', ['==', ['get', 'side'], 'hostile'], '#7f1d1d', '#1e3a8a'],
        'line-width': 3.2,
      },
    })
  }


  // -- Fire support coord measures: white halo + dashed black line --
  if (byKind.fire_support_coord_measure) {
    map.addSource('graphics-fscm', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.fire_support_coord_measure },
    })
    map.addLayer({
      id: 'graphics-fscm-halo',
      source: 'graphics-fscm',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#fff', 'line-width': 5, 'line-opacity': 0.7 },
    })
    map.addLayer({
      id: 'graphics-fscm-line',
      source: 'graphics-fscm',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#000',
        'line-width': 2.2,
        'line-dasharray': [5, 3],
      },
    })
  }

  // -- Assembly areas: 2.2px black outline --
  if (byKind.assembly_area) {
    map.addSource('graphics-aaarea', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.assembly_area },
    })
    map.addLayer({
      id: 'graphics-aaarea-line',
      source: 'graphics-aaarea',
      type: 'line',
      paint: { 'line-color': '#000', 'line-width': 2.2 },
    })
  }

  // TEMP iter 11: defensible_terrain MapLibre layer removed to confirm
  // the regression cause. Tracks back as a SVG stash so MapDoctrinalPaint
  // can paint it via the closed_polygon primitive on the SVG overlay
  // (same as engagement_area's polygon branch).
  if (byKind.defensible_terrain) {
  }


  // -- Restricted operation zone / no-fire area: 2.4px dashed black outline --
  if (byKind.restricted_op_zone) {
    map.addSource('graphics-roz', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: byKind.restricted_op_zone },
    })
    map.addLayer({
      id: 'graphics-roz-line',
      source: 'graphics-roz',
      type: 'line',
      paint: {
        'line-color': '#000',
        'line-width': 2.4,
        'line-dasharray': [3, 2],
      },
    })
  }

  // -- Unified invisible point hit-target -------------------------------
  // SVG-painted point glyphs (NAI / TAI / OBJ / EA point variants, key
  // terrain, choke points, obstacle points, strong points, decision
  // points) have no MapLibre fill/line layer behind them because their
  // visual is constructed by the SVG drawers in MapDoctrinalPaint. The
  // SVG has pointer-events: none so clicks fall through to the canvas;
  // without a backing layer the editor's queryRenderedFeatures would
  // miss the click. We add one invisible circle layer with a generous
  // radius (~22px — matches the kidney/hex/box outer extent at z9) so
  // useMapEvents's existing overlay-pick path picks the source feature.
  //
  // Per-feature properties.kind is preserved so handleOverlaySelect can
  // route to the right edit panel. feature.id is also preserved by the
  // GeoJSON source so moveOverlayRef/loadMapState can address it. Stamp
  // overlayId + originalGeometry on every feature so the drag mouseup
  // handler can compute the delta and call api.updateOverlay. Without
  // these the moveOverlay path bails with "No geometry available for
  // move", PUT never fires, the subsequent loadMapState refetch reverts
  // tactical-graphics to the server's unchanged geom, and the glyph
  // snaps back to the original position on release.
  const pointHitFeatures = []
    .concat(byKind.named_area_of_interest || [])
    .concat(byKind.targeted_area_of_interest || [])
    .concat(byKind.objective || [])
    .concat(byKind.engagement_area || [])
    .concat(byKind.key_terrain || [])
    .concat(byKind.choke_point || [])
    .concat(byKind.obstacle_point || [])
    .concat(byKind.strong_point || [])
    .concat(byKind.decision_point || [])
    .filter(isPointLike)
    .map((f) => ({
      ...f,
      properties: {
        ...(f.properties || {}),
        overlayId: f.id || f.properties?.id,
        originalGeometry: JSON.stringify(f.geometry),
      },
    }))
  if (pointHitFeatures.length) {
    map.addSource('graphics-points-hit-target', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: pointHitFeatures },
    })
    map.addLayer({
      id: 'graphics-points-hit-target',
      source: 'graphics-points-hit-target',
      type: 'circle',
      paint: {
        'circle-radius': 22,
        'circle-color': '#000',
        'circle-opacity': 0,
      },
    })
  }
}

// Catalog of every OMT-basemap layer id any product can toggle. Any id
// in this catalog that's NOT in the per-render `allowedSet` passed to
// applyOmtBasemapPreset gets visibility='none'.
const OMT_BASEMAP_LAYER_IDS = [
  'omt-water', 'omt-waterway',
  'omt-landcover-wood', 'omt-landcover-grass', 'omt-landuse-urban',
  'omt-road-motorway', 'omt-road-trunk', 'omt-road-primary',
  'omt-road-secondary', 'omt-road-tertiary', 'omt-road-minor',
  'omt-road-path',
  'omt-road-name', 'omt-place-label',
  'place-label-maaamet', 'place-label-english',
]

/**
 * Hide / show the OMT basemap layers per schema preset. Pass the set of
 * MapLibre layer ids that should be VISIBLE for this render; anything
 * in OMT_BASEMAP_LAYER_IDS NOT in the set is set to visibility='none'.
 *
 * Pass `null` (no preset, analyst-edit mode) to leave every layer
 * visible. The schema-driven set is sourced from each product's
 * `map_basemap_layer_visibility` field (templates/products/*.py) and
 * forwarded by the backend as the `basemap_layers` URL param.
 *
 * No product-type switches here --- the doctrinal decision lives in
 * the schema, this is purely a primitive applier.
 */
export function applyOmtBasemapPreset(map, allowedSet) {
  if (!map) return
  for (const id of OMT_BASEMAP_LAYER_IDS) {
    if (!map.getLayer(id)) continue
    const visible = !allowedSet || allowedSet.has(id) ? 'visible' : 'none'
    if ((map.getLayoutProperty(id, 'visibility') || 'visible') !== visible) {
      map.setLayoutProperty(id, 'visibility', visible)
    }
  }
}

/**
 * Apply a per-render layer-visibility preset to the doctrinal MapLibre
 * layers added by applyDoctrinalControlMeasures. Pass the set of layer
 * ids that should be VISIBLE; everything in MCOO_LAYER_IDS NOT in the
 * set is hidden via setLayoutProperty('visibility', 'none').
 *
 * Pass `null` (no preset, analyst-edit mode) to leave every layer
 * visible. The schema-driven set is sourced from each product's
 * `map_doctrinal_layer_visibility` field and forwarded by the backend
 * as the `doctrinal_layers` URL param.
 *
 * Idempotent; safe to call after every loadMapState. No product-type
 * switches here.
 */
export function applyProductLayerPreset(map, allowedSet) {
  if (!map) return
  for (const id of MCOO_LAYER_IDS) {
    if (!map.getLayer(id)) continue
    const visible = !allowedSet || allowedSet.has(id)
    try {
      const want = visible ? 'visible' : 'none'
      if ((map.getLayoutProperty(id, 'visibility') || 'visible') !== want) {
        map.setLayoutProperty(id, 'visibility', want)
      }
    } catch {
      /* layer may have been torn down between getLayer and setLayoutProperty */
    }
  }
}


/**
 * Idempotent teardown: remove every layer + source + stash we created.
 */
export function removeDoctrinalControlMeasures(map) {
  if (!map) return
  removeDoctrinalRoadLayers(map)
  for (const id of MCOO_LAYER_IDS) {
    if (map.getLayer(id)) map.removeLayer(id)
  }
  for (const id of MCOO_SOURCE_IDS) {
    if (map.getSource(id)) map.removeSource(id)
  }
  for (const key of STASH_KEYS) {
    if (key in map) delete map[key]
  }
}

function isPolygonLike(f) {
  const t = f && f.geometry && f.geometry.type
  return t === 'Polygon' || t === 'MultiPolygon'
}

function isPointLike(f) {
  const t = f && f.geometry && f.geometry.type
  return t === 'Point' || t === 'MultiPoint'
}
