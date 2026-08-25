/**
 * MapDoctrinalPaint — Doctrinal SVG paint layered INSIDE the MapLibre
 * canvas container.
 *
 * Replaces the previous MilGraphicsLayer sibling-DOM overlay. The SVG
 * element is appended to `map.getCanvasContainer()` so it lives in the
 * same DOM stack as MapLibre's WebGL canvas — visually inside the map's
 * rendering pipeline. `pointer-events: none` lets every click pass
 * through to the underlying MapLibre canvas, where the analyst's edit
 * tool picks the real source feature via MapLibre's native hit-test.
 *
 * Painted for any map whose `attrs.product_type` is in {MCOO, SITEMP,
 * Threat Overlay}. Repaints on every MapLibre `idle` event from the kind-
 * segregated stashes attached by `applyDoctrinalControlMeasures`.
 *
 * Mounted by BOTH OperationsMap (analyst editor) and OperationsMapHeadless
 * (export render) — same paint everywhere. Analyst still drags/edits
 * features through the standard MapLibre + MapboxDraw click pipeline;
 * the SVG paint is purely visual.
 *
 * ----------------------------------------------------------------------
 * Drawer dispatch table — what kind goes to which tacticalGraphics.svg.js
 * drawer. Read this BEFORE iterating on a kind so you know which drawer
 * to edit. All drawers live verbatim in `utils/tacticalGraphics.svg.js`
 * (ported from render.html). The actual dispatch happens inside
 * `paintTacticalGraphics` plus the entity / cluster / target tail below.
 *
 *   stash key                          drawer (tacticalGraphics.svg.js)
 *   ---------------------------------  ----------------------------------
 *   __milUnitFeatures (clustered)  clusterMilUnits +
 *                                      drawClusterFrame / drawEntityLabel
 *   __threatOverlayTargets             drawTargetLabel     (Threat Overlay only)
 *
 * Suppressed in render.html v32 because stacking a mobility-corridor
 * arrow inside the parent AA chevron produced a doubled-arrow visual;
 * per ATP 2-01.3 fig 4-9 the AA chevron alone conveys the avenue when a
 * single mobility corridor exists. The drawer (drawMobilityCorridor)
 * is kept callable for multi-corridor scenarios — re-enable here and
 * in render.html together if that day comes.
 *
 * MapLibre source-layer paint (NOT here, in `utils/tacticalLayers.maplibre.js`):
 * polygon-variant kinds (NAI/TAI/OBJ/EA poly, BP, AA-area, FSCM line,
 * boundary line, phase-line line, urban fill, restricted/severe-restricted
 * terrain, hydrology, ROZ, obstacle belt, intervisibility line) all paint
 * through MapLibre `graphics-*` layers. The SVG drawers above only paint
 * the label / point glyph / chevron-body that MapLibre's expression
 * paint cannot reproduce.
 *
 * Click-through: SVG root has `pointer-events: none`. Hit-test on
 * point-glyph kinds runs against the unified `graphics-points-hit-target`
 * circle layer that `applyDoctrinalControlMeasures` adds (see useMapEvents.js
 * OVERLAY_LAYERS).
 * ----------------------------------------------------------------------
 */

import React, { useEffect, useRef } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { hiddenUnitNameFactions } from '../utils/featureVisibility'
import {
  paintTacticalGraphics,
  drawTargetLabel,
} from '../utils/tacticalGraphics.svg'
import { createSeededRegistry } from '../utils/labelPlacement'
import { ensureContourLayers } from '../utils/contours'

// ---------------------------------------------------------------------------
// Spot-height refresh. MODULE-scoped deliberately (components and
// helpers defined inside a render body are re-created per render).
//
// Peaks come from GET /terrain/peaks?bbox — the backend decodes the
// z11 planet tiles covering the viewport (peaks only EXIST in tiles
// from z11, so a client at operational render zooms has no peak data
// in the tiles it loads — this is what killed spot heights on product
// renders when they briefly read the pois layer directly) and joins
// elevations from the shared DEM in the same response. One fetch per
// viewport signature, cached on the map instance; never overlapping
// (inflight flag); fire-and-forget (a failure retries on the next
// doctrinal repaint).
// ---------------------------------------------------------------------------
function _refreshSpotHeights(map) {
  if (map.__spotHeightsInflight) return
  // Never fetch mid-gesture: zoom now repaints per FRAME, and the
  // 4-decimal viewport signature changes every frame — unguarded this
  // fired a peaks request per animation frame.
  if (typeof map.isMoving === 'function' && map.isMoving()) return
  const b = map.getBounds()
  // Quantized viewport signature — repaints without real movement
  // (and sub-pixel pans) reuse the previous fetch. FOUR decimals
  // (~11 m), never two: at deep zoom a viewport spans less than 0.01°,
  // so a 2-decimal signature collapsed the bbox to a degenerate box
  // and every peak vanished exactly when the analyst zoomed IN on one.
  const sig = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
    .map(v => v.toFixed(4)).join(',')
  if (sig === map.__spotHeightsSig) return
  map.__spotHeightsInflight = true
  fetch(`/geo-api/v1/terrain/peaks?bbox=${sig}`)
    .then(r => (r.ok ? r.json() : null))
    .then(body => {
      if (!body) return
      const src = map.getSource('terrain-spot-heights')
      if (!src) return
      src.setData({
        type: 'FeatureCollection',
        features: (body.peaks || []).map(p => ({
          type: 'Feature',
          properties: {
            name: p.name,
            elev: p.elevation_m,
            label: p.elevation_m != null
              ? `${Math.round(p.elevation_m)} m  ${p.name}`
              : p.name,
          },
          geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
        })),
      })
      map.__spotHeightsSig = sig
    })
    .catch(() => { /* retried on the next repaint */ })
    .finally(() => { map.__spotHeightsInflight = false })
}

// Products whose schema declares map_overlay_kinds get the doctrinal
// paint pipeline; the URL `layers` primitive (forwarded by
// intel_agent.tool_render_map from the schema) drives WHAT paints
// at runtime. This set is the analyst-editor fallback list — when
// there's no render config (i.e. the analyst is editing rather than
// rendering), we still need to know whether to mount the SVG paint
// layer. Mirrors which product schemas declare map_overlay_kinds in
// pytho-app/app/app/templates/products/*.py.
const PRODUCT_TYPES_WITH_OVERLAYS = new Set([
  'MCOO', 'SITEMP', 'THREAT_OVERLAY', 'THREAT_MODEL',
  'EVENT_TEMPLATE', 'DECISION_SUPPORT_TEMPLATE', 'GRINTSUM',
  'CCM', 'LOS', 'CDE', 'THREAT_COA_STATEMENT', 'TMP',
  // Live operations-map surface — no product context. Paint everything
  // (live_oob mil_units with SIDC glyphs, scenario_terrain MCOO overlays,
  // and any per-product mirrors landed on the master map via
  // _push_overlays_to_master_map). Without this token the SVG paint
  // pass bails on the analyst's live view and units only render as
  // transparent hit-target circles — the canvas shows OSM base + tactical
  // graphics fills but no doctrinal unit glyphs.
  'OPERATIONS_MAP',
])
const SVG_NS = 'http://www.w3.org/2000/svg'

/**
 * @param {Object} props
 * @param {Object} props.mapMeta - { attrs: { product_type } }
 */
export function MapDoctrinalPaint({ mapMeta }) {
  const { mapRef, mapLoaded, milSymRendererReady, productType: ctxProductType, hiddenTypes, layerVisibility, baseMapStyle } = useGeoAgent()
  const svgRef = useRef(null)
  // productType resolution order: (1) GeoAgentProvider context — set by
  // embedded mounts (DocEditor EditMap overlay) which have no URL
  // product_type to forward; (2) URL ?product_type= for the headless
  // render route; (3) mapMeta.attrs.product_type saved on the geo-agent
  // map record; (4) ''. Multi-word values are whitespace-normalized to
  // underscore form so 'Threat Model' / 'Threat Overlay' / 'Event
  // Template' / 'Decision Support Template' match the underscore keys
  // in PRODUCT_TYPES_WITH_OVERLAYS.
  let _urlProductType = ''
  try {
    if (typeof window !== 'undefined' && window.location) {
      const params = new URLSearchParams(window.location.search)
      _urlProductType = (params.get('product_type') || '').toUpperCase()
    }
  } catch { /* SSR */ }
  const _resolved = (
    (ctxProductType || '').toUpperCase()
    || _urlProductType
    || (mapMeta?.attrs?.product_type || '').toUpperCase()
  ).replace(/\s+/g, '_')
  // Live operations-map surface has no product context — substitute the
  // OPERATIONS_MAP sentinel so the SVG paint pass mounts and paints the
  // live_oob mil_units + scenario_terrain + per-product mirrors instead
  // of bailing on empty productType. Edit-deep-link (?from_artifact)
  // and headless render paths set _resolved to the artifact's product
  // type and bypass this default.
  const productType = _resolved || 'OPERATIONS_MAP'
  const enabled = PRODUCT_TYPES_WITH_OVERLAYS.has(productType)

  useEffect(() => {
    if (!enabled) return
    const map = mapRef?.current
    if (!map || !mapLoaded) return

    // Mount the SVG inside MapLibre's canvas container. Sitting in the
    // same DOM parent as the WebGL canvas means our paint scrolls / pans
    // with the canvas correctly and (with pointer-events: none) clicks
    // pass through to MapLibre's hit-test.
    const container = map.getCanvasContainer()
    if (!container) return
    const svg = document.createElementNS(SVG_NS, 'svg')
    svg.setAttribute('xmlns', SVG_NS)
    svg.style.position = 'absolute'
    svg.style.left = '0'
    svg.style.top = '0'
    svg.style.width = '100%'
    svg.style.height = '100%'
    svg.style.pointerEvents = 'none'
    // Render outside the viewport too: the paint pass draws EVERY
    // feature (whole-map fetch), so a pan simply reveals already-drawn
    // content instead of popping it in on the settle repaint.
    svg.style.overflow = 'visible'
    // Doctrinal paint sits between the MapLibre canvas (z 0) and any
    // MapboxDraw overlay (default z 100+). Drag handles still receive
    // pointer events because pointer-events: none on this element makes
    // the browser hit-test fall through to whatever is underneath.
    svg.style.zIndex = '2'
    svg.classList.add('map-doctrinal-paint')
    container.appendChild(svg)
    svgRef.current = svg

    let cancelled = false

    // Camera state at the moment of the last full repaint — the CSS
    // transform during pan/zoom is computed RELATIVE to this. See
    // onMove below.
    let paintCam = null
    const stashPaintCam = () => {
      paintCam = {
        zoom: map.getZoom(),
        center: map.getCenter(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
        centerPx: map.project(map.getCenter()),
      }
    }

    const repaint = () => {
      if (cancelled) return
      const svgEl = svgRef.current
      if (!svgEl || !map) return
      const c = map.getContainer()
      if (c) {
        svgEl.setAttribute('width', String(c.clientWidth))
        svgEl.setAttribute('height', String(c.clientHeight))
        svgEl.setAttribute(
          'viewBox',
          `0 0 ${c.clientWidth} ${c.clientHeight}`,
        )
      }
      // A fresh paint IS the camera truth — drop any interim transform
      // and re-anchor the tracking baseline.
      svgEl.style.transform = ''
      stashPaintCam()
      while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild)
      // Stash the per-faction "Names" legend state on the map instance
      // (same pattern as map.__renderConfig / map.__productType) so
      // drawMilUnit can gate each unit's designation label by its OWN
      // affiliation without threading a new arg through
      // paintTacticalGraphics' primitive dispatch. Empty/undefined =>
      // every label shows (headless renders + embeds never set it).
      map.__hiddenUnitNameFactions = hiddenUnitNameFactions(hiddenTypes)
      const registry = createSeededRegistry(map, productType)
      paintTacticalGraphics(map, svgEl, registry, { productType })

      // Schema-driven render config (stashed on the map instance by
      // HeadlessRenderConfigStash from URL primitives forwarded by
      // intel_agent.tool_render_map). null when running in the analyst
      // editor — every gate below falls through to its editor default.
      const renderConfig = map.__renderConfig || null
      const inHeadlessRender = !!renderConfig

      // Topographic contour overlay — the black SITEMP treatment
      // (per ATP 2-01.3 Fig 6-3: BLACK rings on the near-white
      // basemap, labeled index contours, spot heights at named
      // peaks). Two gate paths:
      //   headless render → the ?contours= URL primitive ONLY
      //                     (renderConfig, forwarded by
      //                     tool_render_map from the product schema's
      //                     `map_show_topographic_contours`) — no
      //                     product-type switch; the schema field IS
      //                     the gate, and the live-view toggle below
      //                     never leaks into exported artifacts.
      //   live/edit map   → the analyst's Contours layer toggle
      //                     (layerVisibility.contours, DEFAULT ON —
      //                     the plain operations map shows the terrain
      //                     readout with no product context). Product
      //                     edit sessions initialize the toggle from
      //                     the map's stored render spec
      //                     (OperationsMap RenderSpecStash) so the
      //                     editor starts matching its export. Skipped
      //                     on the topo basemap, whose brown sheet
      //                     contours (GeoAgentMap) already carry the
      //                     same linework from the same source.
      // Linework comes from the shared client-side DEM contour source
      // (utils/contours.js — maplibre-contour over the Mapterhorn
      // Terrarium DEM through this service's own /tiles/dem proxy).
      // This replaced the pregenerated smoothed-GeoJSON overlay,
      // which was (a) blank outside the one area of operations it was
      // built for and (b) floored at Z ≥ 11 while the AO-bbox product
      // render sits near Z 9.3 — exported products never showed a
      // single contour. Interval tiers now follow the doctrine
      // contour-interval ↔ map-scale mapping down to operational zoom
      // (utils/contours.js THRESHOLDS).
      const showContours = inHeadlessRender
        ? renderConfig.showContours === true
        : (layerVisibility?.contours !== false && baseMapStyle !== 'topo')
      try {
        ensureContourLayers(map, 'doctrinal', showContours, 'places-region-labels')
      } catch (e) { console.warn('[CONTOURS] setup failed:', e) }
      // Spot heights carry their OWN layer toggle on the live surface
      // (layerVisibility.spotHeights — a sparse point readout the
      // analyst may want independent of contour linework). Headless
      // renders keep them welded to the contour primitive: the SITEMP
      // treatment ships both or neither.
      // Explicit opt-in on the live surface: the peaks feed is a
      // multi-second server-side decode, and the default-on gate fired
      // it before layer prefs even hydrated - starving interactive
      // fetches (the placard) behind a request nobody asked for.
      const showSpotHeights = inHeadlessRender
        ? renderConfig.showContours === true
        : layerVisibility?.spotHeights === true
      if (showSpotHeights) {
        try {
          // Spot heights at named peaks — GLOBAL, from data. The
          // backend's /terrain/peaks endpoint decodes the planet
          // tiles' pois peaks for the current viewport (works at ANY
          // view zoom — see _refreshSpotHeights) and joins elevations
          // from the same Mapterhorn DEM the hillshade + contours
          // read, so the number can never contradict our own contour
          // linework. The previous implementation was five peaks
          // hard-coded to one area of operations, which is why spot
          // heights existed nowhere else.
          if (!map.getSource('terrain-spot-heights')) {
            map.addSource('terrain-spot-heights', {
              type: 'geojson',
              data: { type: 'FeatureCollection', features: [] },
            })
          }
          if (!map.getLayer('terrain-spot-heights-dot')) {
            map.addLayer({
              id: 'terrain-spot-heights-dot',
              source: 'terrain-spot-heights',
              minzoom: 8,
              type: 'circle',
              paint: {
                'circle-radius': 3,
                'circle-color': '#1a1a1a',
                'circle-stroke-color': '#ffffff',
                'circle-stroke-width': 1.5,
              },
            })
            map.addLayer({
              id: 'terrain-spot-heights-label',
              source: 'terrain-spot-heights',
              type: 'symbol',
              minzoom: 8,
              layout: {
                'text-field': ['get', 'label'],
                'text-font': ['Noto Sans Italic'],
                'text-size': 11,
                'text-offset': [0.8, 0],
                'text-anchor': 'left',
                'text-justify': 'left',
                // Collision-decluttered (the fixture era allowed
                // overlap — fine for five labels, unreadable over a
                // global peak field).
                'text-allow-overlap': false,
                'text-padding': 2,
              },
              paint: {
                'text-color': '#1a1a1a',
                'text-halo-color': '#ffffff',
                'text-halo-width': 2,
              },
            })
          }
          for (const id of ['terrain-spot-heights-dot', 'terrain-spot-heights-label']) {
            if (map.getLayer(id)
                && (map.getLayoutProperty(id, 'visibility') || 'visible') !== 'visible') {
              map.setLayoutProperty(id, 'visibility', 'visible')
            }
          }
          _refreshSpotHeights(map)
        } catch (e) { console.warn('[CONTOURS] spot heights failed:', e) }
      } else {
        // Spot Heights toggle off — hide the point chrome.
        for (const id of ['terrain-spot-heights-dot', 'terrain-spot-heights-label']) {
          try {
            if (map.getLayer(id)
                && (map.getLayoutProperty(id, 'visibility') || 'visible') !== 'none') {
              map.setLayoutProperty(id, 'visibility', 'none')
            }
          } catch { /* layer not ready — nothing to hide */ }
        }
      }

      // Mil-unit icons + cluster frames + designation labels are painted
      // by the PRIMITIVE_DRAWERS dispatch inside paintTacticalGraphics
      // (mil_unit primitive, PAINT_TIER 4 = painted last so icons sit on
      // top of every other graphic per ATP 2-01.3 focal-point rule).
      // _getMilUnitStream applies the SITEMP hostile-only filter + the
      // `map_cluster_mil_units` schema gate. Nothing to do here.
      for (const f of map.__threatOverlayTargets || [])
        drawTargetLabel(map, svgEl, f, registry)

      // Signal to the headless render's ready-wait that the doctrinal
      // SVG paint pass has produced visible output at least once with
      // real data. waitForFullPaint can settle on idle (which fires
      // before tile loads complete + before applyDoctrinalControlMeasures
      // stashes features), so it needs this explicit "I have actually
      // drawn something" signal to know the SVG isn't going to be empty
      // at screenshot time. Only flip the flag when there's something
      // on canvas (children > 0) so a "painted-but-empty" first pass
      // doesn't fool the waiter.
      if (svgEl.children.length > 0) {
        try {
          window.__doctrinalPainted = true
        } catch { /* not in a window context (SSR) — no-op */ }
      }
    }

    const onIdle = () => {
      repaint()
    }

    // Camera tracking, two regimes — both synchronous inside the
    // `move` event so the overlay NEVER lags the WebGL canvas:
    //  - pure PAN: a translate-only CSS transform (exact; the SVG
    //    renders with overflow visible, so panning reveals content
    //    that was painted beyond the old viewport — no pop-in).
    //  - ZOOM (or rotate/pitch): full synchronous repaint per frame,
    //    so lines re-project and symbols/labels keep their true
    //    constant screen size THROUGH the gesture instead of scaling
    //    with the map and snap-resizing on settle. The milsymbol SVG
    //    cache is map-scoped (drawMilUnit), so per-frame repaints are
    //    DOM assembly only.
    let isMoving = false
    const onMoveStart = () => {
      isMoving = true
      if (!paintCam) stashPaintCam()
    }
    const onMove = () => {
      const svgEl = svgRef.current
      if (!svgEl || !paintCam) return
      const zoomed = Math.abs(map.getZoom() - paintCam.zoom) > 1e-9
      const turned = map.getBearing() !== paintCam.bearing
        || map.getPitch() !== paintCam.pitch
      // The translate-only trick is exact ONLY for a flat top-down
      // mercator pan. Under pitch or 3D terrain, projection is
      // non-uniform across the viewport - translating the whole SVG
      // by the center's delta makes symbols DRIFT off their anchors
      // until moveend snaps them back. Repaint per frame instead
      // (drawMilUnit's SVG cache makes it DOM assembly only).
      const nonUniform = map.getPitch() > 0
        || (typeof map.getTerrain === 'function' && !!map.getTerrain())
      if (zoomed || turned || nonUniform) {
        repaint()
        return
      }
      const p1 = map.project(paintCam.center)
      svgEl.style.transformOrigin = '0 0'
      svgEl.style.transform =
        `translate(${(p1.x - paintCam.centerPx.x).toFixed(2)}px, `
        + `${(p1.y - paintCam.centerPx.y).toFixed(2)}px)`
    }
    const onMoveEnd = () => {
      isMoving = false
      repaint()
    }

    // Also listen for sourcedata so we repaint after applyDoctrinalControlMeasures /
    // loadMapState pushes new features into the stashes. Without this the
    // editor route has a race window: MapDoctrinalPaint's useEffect re-runs
    // when productType arrives (enabled flips false→true), runs its initial
    // repaint() with empty stashes, and — if no camera movement triggers a
    // fresh idle — never repaints again. Gating on `sourcedataloaded` ensures
    // every data load gets a paint pass.
    //
    // NO isMoving skip: at mount time, fitBounds (duration=0) triggers
    // movestart+move+moveend synchronously while loadMapState is still in
    // flight. If the /map/state response arrived during the fit, the
    // sourcedata event fired with isMoving=true and was skipped — analyst
    // saw an empty map until they manually dragged the camera. rAF coalesce
    // on the visible paint side handles frame budget; one extra repaint
    // when data lands during a fit is harmless.
    const onSourceData = (e) => {
      // Only care about top-level source data loads, not every tile-level
      // event. Skip metadata-only events and tile loads.
      if (e?.sourceDataType === 'metadata') return
      if (e?.tile) return
      if (!e?.isSourceLoaded) return
      repaint()
    }

    // Custom event fired by useMapInstance.loadMapState after every
    // setData call completes. Bulletproofs the headless render: when
    // mil-sym-ts's isReady() poll runs long (up to 15s), the useEffect
    // attaches its listeners AFTER loadMapState's sourcedata events
    // have already fired. Events don't replay; sourcedata never
    // triggers another repaint until the analyst manually drags the
    // camera — that was the "unit symbols only appear after you drag
    // the map" headless bug. Subscribing to pytho:data-loaded
    // guarantees a repaint AFTER the per-product map's units / targets
    // / overlays have been pushed, regardless of which side of the
    // milSymRendererReady transition the data load landed on.
    const onDataLoaded = () => repaint()

    // Placard equipment hover sets map.__ringHighlight and fires this
    // so the matching range ring repaints hot immediately.
    const onRingHighlight = () => repaint()
    map.on('pytho:ring-highlight', onRingHighlight)

    map.on('idle', onIdle)
    map.on('movestart', onMoveStart)
    map.on('move', onMove)
    map.on('moveend', onMoveEnd)
    map.on('sourcedata', onSourceData)
    map.on('pytho:data-loaded', onDataLoaded)

    // Defensive ResizeObserver: when the editor route mounts the map inside
    // DefaultPageLayout's flex chain, MapLibre can initialize its internal
    // canvas-container element BEFORE the React parent has resolved its final
    // pixel height. Result: `.maplibregl-canvas-container` is stuck at 0px
    // tall even after parents reflow, and the doctrinal SVG paint runs against
    // a zero-height container so labels/glyphs project off-screen. The
    // headless route (position:fixed; inset:0; viewport units) never hits this
    // because the container always has its size when MapLibre mounts. Fix:
    // observe the React-bound map container, and whenever its size changes,
    // call map.resize() so MapLibre re-syncs its internal canvas-container +
    // gl viewport, then repaint the SVG against the new size.
    const mapContainer = map.getContainer()
    let resizeObserver = null
    if (mapContainer && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        if (cancelled) return
        try {
          map.resize()
        } catch {
          /* map may be torn down */
        }
        repaint()
      })
      resizeObserver.observe(mapContainer)
    }

    // Initial paint after a microtask in case data already loaded.
    repaint()

    return () => {
      cancelled = true
      try {
        map.off('idle', onIdle)
        map.off('movestart', onMoveStart)
        map.off('move', onMove)
        map.off('moveend', onMoveEnd)
        map.off('sourcedata', onSourceData)
        map.off('pytho:data-loaded', onDataLoaded)
        map.off('pytho:ring-highlight', onRingHighlight)
      } catch {
        /* ignore */
      }
      if (resizeObserver) {
        try {
          resizeObserver.disconnect()
        } catch {
          /* ignore */
        }
      }
      if (svgRef.current && svgRef.current.parentNode) {
        svgRef.current.parentNode.removeChild(svgRef.current)
      }
      svgRef.current = null
    }
  }, [enabled, mapRef, mapLoaded, milSymRendererReady, productType, hiddenTypes, layerVisibility, baseMapStyle])

  // The SVG element is appended imperatively to map.getCanvasContainer();
  // this component renders nothing in React's tree.
  return null
}

export default MapDoctrinalPaint
