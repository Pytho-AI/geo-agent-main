/**
 * GeoAgentMap - Main map component with full map initialization and event handling
 */

import React, { useEffect, useCallback } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import MapboxDraw from '@mapbox/mapbox-gl-draw'
import '@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css'

import { useGeoAgent } from '../GeoAgentProvider'
import { useMapInstance } from '../hooks/useMapInstance'
import { useEntities } from '../hooks/useEntities'
import { useOverlays } from '../hooks/useOverlays'
import { useMapEvents } from '../hooks/useMapEvents'
import { useUndoStack } from '../hooks/useUndoStack'
import { useRoutePlanning } from '../hooks/useRoutePlanning'
import { useRouteEditing } from '../hooks/useRouteEditing'
import { MAP_STYLE, DRAW_STYLES, AFFILIATION_COLORS, BASE_MAP_SOURCES, BASEMAP_BACKGROUNDS, API_BASE } from '../utils/mapStyles'
import { ensureContourLayers } from '../utils/contours'
import { getMilStdIconRenderer, createTacticalGraphic } from '../utils/symbols'
import { generateMGRSGrid, MGRS_GRID_LAYERS } from '../utils/mgrsGrid'
import { addMapLayers, addDrawingPreviewLayers } from '../utils/mapLayers'
import { createApiClient } from '../utils/api'
import { initSavedRouteLayers } from '../utils/routeConstants'

import { MapControls } from './MapControls'
import { CUSTOM_SYMBOL_DRAG_MIME, CustomSymbolLibrary } from './CustomSymbolLibrary'
import { ConfirmModal } from './ConfirmModal'
import TimelineScrubber from './TimelineScrubber'
import { useCustomSymbols } from '../hooks/useCustomSymbols'

// Helper to get overlay type info from appConfig
const getOverlayTypeInfo = (kind, overlayTypes) => {
  if (!overlayTypes) return null
  const allTypes = [...(overlayTypes.line || []), ...(overlayTypes.polygon || []), ...(overlayTypes.point || [])]
  return allTypes.find(t => t.value === kind)
}
import { AllBanners, MeasureBanner } from './Banners'
import { StatusBar } from './StatusBar'
import { EntityPanel } from './EntityPanel'
import { UnitMetadataPanel } from './UnitMetadataPanel'
import { OverlayMetadataPanel } from './OverlayMetadataPanel'
import { OverlayToolbar } from './OverlayToolbar'
import { OverlayPanel } from './OverlayPanel'
import { SymbolPicker } from './SymbolPicker'
import { LayerSwitcher } from './LayerSwitcher'
import { RoutePlannerPanel } from './RoutePlannerPanel'
import { RouteFailureModal } from './RouteFailureModal'
import { SignalReportPanel } from './SignalReportPanel'

/**
 * GeoAgentMap - Main map component
 * @param {Object} props
 * @param {[number, number]} props.center - Initial map center [lng, lat]
 * @param {number} props.zoom - Initial zoom level
 * @param {Array<number>} props.bounds - [west, south, east, north] fit-bounds override (headless)
 * @param {Function} props.onEntityClick - Callback when entity is clicked
 * @param {Function} props.onOverlayCreate - Callback when overlay is created
 * @param {Function} props.onMapLoad - Callback when map is loaded
 */
export function GeoAgentMap({
  center,
  zoom,
  bounds,
  onEntityClick,
  onOverlayCreate,
  onMapLoad
}) {
  const {
    mapRef,
    mapContainerRef,
    drawRef,
    defaultCenter,
    defaultZoom,
    apiUrl,
    mapId,
    savedViewport,
    viewportLoaded,
    setMapLoaded,
    setMilSymRendererReady,
    addActivity,
    placementMode,
    pendingOverlay,
    overlayForm,
    selectedOverlayType,
    setSelectedOverlayType,
    overlayDrawMode,
    overlayDrawModeRef,
    showOverlayPanel,
    appConfig,
    regionBounds,
    configLoaded,
    mapRefreshTrigger,
    measureMode,
    measurePoints,
    baseMapStyle,
    layerVisibility,
    mapLoaded,
    // Geometry editing
    geometryEditMode,
    // Route (only what the banner + CSS classes need)
    routePlanMode,
    routeStart,
    routeEnd,
    routeResult,
    routeLoading,
    routeEditMode,
    headless,
    productType: ctxProductType,
    editEnabled,
    enabledLayers,
    hiddenTypes,
    setSelectedSignalReport,
    // Pulled in so the loadMapState re-fire useEffect below can watch
    // selectedUnitMeta and re-apply the click-to-show-range-fans filter
    // in useMapInstance._filterBySource (which gates range_fan features
    // by bearer_unit_kg_id against the selected unit's source_kbid).
    // Without this dep, clicking a unit updates context but never
    // re-fires loadMapState — the filter has no chance to run.
    selectedUnitMeta,
    // Timeline scrub — a change re-fires loadMapState with ?as_of so
    // the whole graph stream re-resolves from the position tracks.
    timelineAsOf,
    // Weather overlay (OpenWeatherMap forecast tiles via this service's
    // own /tiles/weather proxy — ported from the pytho-vite copy).
    weatherVisible,
    weatherLayer,
    weatherHour,
  } = useGeoAgent()

  const api = createApiClient(apiUrl)

  // --- Route hooks (extracted) ---
  const { drawRoute, replanRoute } = useRoutePlanning()
  const { getRouteEditCoords } = useRouteEditing()

  // Stable ref so RoutePlannerPanel can always call the latest version
  const getRouteEditCoordsRef = React.useRef(getRouteEditCoords)
  React.useEffect(() => { getRouteEditCoordsRef.current = getRouteEditCoords }, [getRouteEditCoords])

  // Ref to track selected overlay type for use in event handlers
  const selectedOverlayTypeRef = React.useRef(selectedOverlayType)
  React.useEffect(() => {
    selectedOverlayTypeRef.current = selectedOverlayType
  }, [selectedOverlayType])

  // Ref to track appConfig for use in event handlers
  const appConfigRef = React.useRef(appConfig)
  React.useEffect(() => {
    appConfigRef.current = appConfig
  }, [appConfig])

  const { loadMapState, zoomIn, zoomOut, resetView } = useMapInstance()
  const { updateEntityPosition, updateEntityAttrs, deleteEntity, createNewEntity, selectEntity } = useEntities()
  const {
    getSidcForOverlayType,
    updateOverlay,
    deleteOverlay,
    handleDrawCreate,
    savePendingOverlay,
    cancelOverlayCreation,
    restartOverlayDraw,
    startOverlayDraw,
    exitOverlayDrawMode,
    saveGeometryEdit,
    cancelGeometryEdit
  } = useOverlays()

  // Wrapped loadMapState that passes callbacks
  const loadMapStateWithCallbacks = useCallback(() => {
    loadMapState(selectEntity, updateEntityPosition)
  }, [loadMapState, selectEntity, updateEntityPosition])

  // Ref mirror so the once-registered moveend viewport-refresh handler
  // (setupViewportRefresh) always calls the LATEST loadMapStateWithCallbacks
  // — i.e. one bound to the current enabledLayers. Without this, panning
  // re-renders with the enabledLayers value frozen at map-load time
  // ({live_oob}), dropping any COA/SITEMP overlay toggled on afterward.
  const loadMapStateCbRef = React.useRef(loadMapStateWithCallbacks)
  React.useEffect(() => {
    loadMapStateCbRef.current = loadMapStateWithCallbacks
  }, [loadMapStateWithCallbacks])

  // Track the last processed refresh trigger to prevent duplicate refreshes
  const lastRefreshTriggerRef = React.useRef(0)

  // --- TIDAT-pushed badge layer. The TIDAT artifact is a header_only DOCX
  //     per target with no overlay output — the badge layer is the
  //     analyst's "this red unit has a TIDAT pushed" indicator. Data
  //     source: client-side query of
  //     /api/products/records?product_type=TIDAT, deduplicated by
  //     source_metadata.target_entity_id, joined against the mil-units
  //     source features by their KNOWLEDGE-GRAPH id (`source_kbid` —
  //     the same value the right-click generate sends as
  //     target_entity_id; geo-agent's own entity row uuid `props.id` is
  //     a different namespace and joining on it matched nothing, which
  //     is why the badge never appeared). Re-queried on every
  //     mapRefreshTrigger bump (which fires on TIDAT finalize via the
  //     IntelAgentWs product_records broadcast that GeoAgentProvider's
  //     refresh logic surfaces). Always visible — TIDAT is a per-target
  //     product (right-click flow), not a togglable overlay layer; the
  //     badge is a status indicator anchored to the Live Units layer.
  //     See FM 34-25-3 Ch 5 for the TIDAT target-binding model.
  React.useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return

    const SRC_ID = 'tidat-pushed-badges-src'
    const LAYER_ID = 'tidat-pushed-badges'

    // Lazily create the source + layer the first time we touch the map.
    if (!map.getSource(SRC_ID)) {
      try {
        map.addSource(SRC_ID, {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        })
        map.addLayer({
          id: LAYER_ID,
          type: 'symbol',
          source: SRC_ID,
          layout: {
            'text-field': 'T',
            // Protomaps' glyph server (set as MAP_STYLE.glyphs) ships
            // `Noto Sans Regular`; MapLibre's default `Open Sans
            // Regular` returns 404 there and blocks style.load.
            'text-font': ['Noto Sans Regular'],
            'text-size': 11,
            'text-offset': [1.2, -1.2],
            'text-anchor': 'left',
            'text-allow-overlap': true,
            'text-ignore-placement': true,
            'symbol-z-order': 'source',
          },
          paint: {
            'text-color': '#ffffff',
            'text-halo-color': '#1f6feb',
            'text-halo-width': 3,
          },
        })
      } catch (err) {
        console.warn('[tidat-pushed-badges] addLayer failed:', err)
      }
    }

    let cancelled = false
    const queryAndRender = async () => {
      try {
        // /api/products/records is the unified product-chain endpoint.
        // Response shape: { chains: [ChainRow, ...] }. Each chain row
        // carries source_metadata.target_entity_id when the chain was
        // initiated by the operations-map right-click (the autodraft
        // sweep path leaves source_metadata empty).
        const res = await fetch(`/api/products/records?product_type=TIDAT`)
        if (!res.ok) return
        const body = await res.json()
        if (cancelled) return
        const rawList = Array.isArray(body?.chains) ? body.chains : []

        // Dedup by target_entity_id, keeping the latest completed chain
        // per target. Skip chains with no target binding (sweep-only
        // emissions land here without a target_entity_id; the writer's
        // gap-notice path produces them and they have no badge meaning).
        const byTarget = new Map()
        for (const row of rawList) {
          if (!row) continue
          const finalized = row.state === 'complete' && !!row.artifact_id
          if (!finalized) continue
          const targetUnitId = row.source_metadata?.target_entity_id
          if (!targetUnitId) continue
          const ts = row.ended_at_ms || row.latest_started_at_ms || row.started_at_ms || 0
          const prev = byTarget.get(targetUnitId)
          if (!prev || (ts && ts > prev._ts)) {
            byTarget.set(targetUnitId, { ...row, _ts: ts })
          }
        }

        // Join against the rendered mil-units source: emit one badge
        // feature per (target_unit_id, mil_unit) pair, anchored at the
        // unit's coordinates so the badge moves with the unit on OOB
        // OOB updates and disappears when the unit is removed.
        const milSource = map.getSource('mil-units')
        const milFeatures = milSource && milSource._data && milSource._data.features
          ? milSource._data.features
          : []

        const badgeFeatures = []
        for (const unit of milFeatures) {
          const props = unit.properties || {}
          // Join on the KG id — mirrors the right-click send site
          // (useMapEvents) exactly so the two sides can never drift.
          const kgId = props.source_kbid || props.id || props.entity_id || unit.id
          if (!kgId) continue
          if (byTarget.has(kgId)) {
            badgeFeatures.push({
              type: 'Feature',
              geometry: unit.geometry,
              properties: {
                target_unit_id: kgId,
              },
            })
          }
        }

        const src = map.getSource(SRC_ID)
        if (src && !cancelled) {
          src.setData({ type: 'FeatureCollection', features: badgeFeatures })
        }
      } catch (err) {
        console.warn('[tidat-pushed-badges] query failed:', err)
      }
    }
    queryAndRender()
    // Re-join when the mil-units source data lands. The initial
    // queryAndRender above races loadMapState's async setData: on a
    // fresh page load the records fetch resolves against an EMPTY
    // mil-units source, joins zero features, and nothing re-ran until
    // a WS product_records broadcast bumped mapRefreshTrigger — badges
    // never appeared on plain page opens (same race class as the
    // "symbols only appear after you drag the map" SVG-paint bug;
    // pytho:data-loaded is the custom map event loadMapState fires for
    // exactly this).
    const onDataLoaded = () => { queryAndRender() }
    map.on('pytho:data-loaded', onDataLoaded)
    return () => {
      cancelled = true
      try { map.off('pytho:data-loaded', onDataLoaded) } catch { /* map torn down */ }
    }
  }, [mapLoaded, mapRefreshTrigger, mapRef])

  // --- Live signal-report layer (KLIEGLIGHT + OSIR autofire icons).
  //     The autofire loop in handlers/{klieglight,osir}_autofire.py drops
  //     one report artifact per perishable signal that matches the live
  //     HVTL; this layer surfaces those reports as clickable pins at the
  //     intercept / observation MGRS. Click opens the rendered artifact in
  //     a new tab. Sidebar toggles "Live KLIEGLIGHTs" / "Live OSIRs"
  //     (source tokens live_klieglight / live_osir) gate the per-type
  //     visibility. Backend endpoint: /api/operations/recent_signal_reports.
  //     Polled every 10s while either layer is enabled; stops cleanly on
  //     unmount or when both toggles are off.
  React.useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    const showKlieg = enabledLayers && enabledLayers.has('live_klieglight')
    const showOsir  = enabledLayers && enabledLayers.has('live_osir')
    const SRC_ID = 'signal-reports-src'
    const KLIEG_LAYER = 'signal-reports-klieglight'
    const OSIR_LAYER  = 'signal-reports-osir'

    if (!map.getSource(SRC_ID)) {
      try {
        map.addSource(SRC_ID, {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        })
        map.addLayer({
          id: KLIEG_LAYER,
          type: 'symbol',
          source: SRC_ID,
          filter: ['==', ['get', 'kind'], 'KLIEGLIGHT'],
          layout: {
            'text-field': 'KL',
            'text-size': 16,
            'text-allow-overlap': true,
            'text-ignore-placement': true,
            'symbol-z-order': 'source',
          },
          paint: {
            'text-color': '#1f1100',
            'text-halo-color': '#facc15',
            'text-halo-width': 4,
          },
        })
        map.addLayer({
          id: OSIR_LAYER,
          type: 'symbol',
          source: SRC_ID,
          filter: ['==', ['get', 'kind'], 'OSIR'],
          layout: {
            'text-field': 'O',
            'text-size': 13,
            'text-allow-overlap': true,
            'text-ignore-placement': true,
            'symbol-z-order': 'source',
          },
          paint: {
            'text-color': '#ffffff',
            'text-halo-color': '#3b82f6',
            'text-halo-width': 4,
          },
        })
        // Cursor + click. Both layers route to the same handler; the
        // artifact_id (KLIEGLIGHT_... or OSIR_...), summary / mgrs / fired_at,
        // and the autodraft_session_id + format (joined from the product
        // registry server-side) are encoded into the feature's properties at
        // fetch time below. Clicking selects the report into the
        // SignalReportPanel (left-click inspector parallel to
        // UnitMetadataPanel), whose "Open in editor" navigates to the exact
        // same session the dashboard row opens.
        const openArtifact = (e) => {
          const f = e.features && e.features[0]
          if (!f) return
          const p = f.properties || {}
          if (!p.artifact_id) return
          setSelectedSignalReport({
            artifact_id: p.artifact_id,
            kind: p.kind,                       // "KLIEGLIGHT" | "OSIR"
            summary: p.summary || '',
            mgrs: p.mgrs || '',
            fired_at_ms: p.fired_at_ms || 0,
            autodraft_session_id: p.autodraft_session_id || '',
            format: p.format || 'docx',
            coords: f.geometry && f.geometry.coordinates,
          })
        }
        const enterHover = () => { map.getCanvas().style.cursor = 'pointer' }
        const leaveHover = () => { map.getCanvas().style.cursor = '' }
        map.on('click', KLIEG_LAYER, openArtifact)
        map.on('click', OSIR_LAYER,  openArtifact)
        map.on('mouseenter', KLIEG_LAYER, enterHover); map.on('mouseleave', KLIEG_LAYER, leaveHover)
        map.on('mouseenter', OSIR_LAYER,  enterHover); map.on('mouseleave', OSIR_LAYER,  leaveHover)
      } catch (err) {
        console.warn('[signal-reports] layer setup failed:', err)
      }
    }
    // Toggle per-type visibility from sidebar state.
    try {
      if (map.getLayer(KLIEG_LAYER)) {
        map.setLayoutProperty(KLIEG_LAYER, 'visibility', showKlieg ? 'visible' : 'none')
      }
      if (map.getLayer(OSIR_LAYER)) {
        map.setLayoutProperty(OSIR_LAYER, 'visibility', showOsir ? 'visible' : 'none')
      }
    } catch (e) {
      // ignore
    }
    if (!showKlieg && !showOsir) return  // nothing to poll for

    let cancelled = false
    const queryAndRender = async () => {
      try {
        const res = await fetch('/api/operations/recent_signal_reports?max_age_hours=24')
        if (!res.ok) return
        const body = await res.json()
        if (cancelled) return
        const reports = Array.isArray(body?.reports) ? body.reports : []
        const features = []
        for (const r of reports) {
          if (typeof r.lat !== 'number' || typeof r.lon !== 'number') continue
          features.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
            properties: {
              kind: r.type,
              artifact_id: r.artifact_id,
              summary: r.summary || '',
              mgrs: r.mgrs || '',
              fired_at_ms: r.fired_at_ms || 0,
              autodraft_session_id: r.autodraft_session_id || '',
              format: r.format || 'docx',
            },
          })
        }
        const src = map.getSource(SRC_ID)
        if (src && !cancelled) {
          src.setData({ type: 'FeatureCollection', features })
        }
      } catch (err) {
        console.warn('[signal-reports] poll failed:', err)
      }
    }
    queryAndRender()
    const interval = setInterval(queryAndRender, 10000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [mapLoaded, mapRef, enabledLayers])

  // Listen for map refresh trigger from context (e.g., after chat operations)
  useEffect(() => {
    // Only refresh if this is a new trigger value we haven't processed yet
    if (mapRefreshTrigger > 0 && mapRefreshTrigger !== lastRefreshTriggerRef.current && mapRef.current) {
      lastRefreshTriggerRef.current = mapRefreshTrigger
      loadMapState(selectEntity, updateEntityPosition)
    }
  }, [mapRefreshTrigger]) // eslint-disable-line react-hooks/exhaustive-deps

  // Re-run loadMapState when the operations-map sidebar's source toggles
  // change. The filter itself is applied inside loadMapState (see
  // useMapInstance.js, `_filterBySource`); without this effect a toggle
  // would do nothing until the next mapRefreshTrigger bump or viewport
  // pan. mapLoaded gate avoids firing before the map is mounted.
  //
  // Also re-fires on selectedUnitMeta change so the click-to-show-range-
  // fans filter in _filterBySource (gates range_fans by
  // bearer_unit_kg_id against the selected unit's source_kbid) actually
  // runs when the analyst clicks or dismisses a unit. Without
  // selectedUnitMeta in the dep array the click handler updates context
  // but the data fetch never re-fires, so the filter has no chance to
  // include/exclude the unit's fans.
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return
    // Re-fires on enabledLayers OR hiddenTypes OR selectedUnitMeta
    // change. The first two come from the OperationsMap sidebar; the
    // third comes from the mil_unit click handler in useMapEvents. In
    // edit-map mode the sidebar is unmounted (`?from_artifact` deep
    // link) so the first two stay at GeoAgentProvider defaults (null +
    // empty Set) and this effect fires once on mount + on any later
    // selection change.
    loadMapState(selectEntity, updateEntityPosition)
  }, [enabledLayers, hiddenTypes, selectedUnitMeta]) // eslint-disable-line react-hooks/exhaustive-deps

  // Timeline scrub — moving the scrubber (or returning to LIVE) re-fires
  // loadMapState; the as_of rides the /map/state fetch inside it and the
  // whole graph stream re-resolves from the append-only position tracks.
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return
    loadMapState(selectEntity, updateEntityPosition)
  }, [timelineAsOf]) // eslint-disable-line react-hooks/exhaustive-deps

  // Undo/redo stack for drag operations (entity + overlay moves)
  const { pushUndo, undo, redo, canUndo, canRedo } = useUndoStack()

  // Map event handlers
  const { setupEventHandlers } = useMapEvents({
    onEntityClick,
    loadMapStateWithCallbacks,
    pushUndo
  })

  // Custom-symbol drag-drop, marker render, and move/resize/rotate.
  const { handleMapDrop } = useCustomSymbols()

  const handleMapDragOver = useCallback((e) => {
    if (e.dataTransfer.types.includes(CUSTOM_SYMBOL_DRAG_MIME)) {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    }
  }, [])

  // ESC key handler - only for when overlay panel is showing (after drawing complete)
  // The draw.modechange event handles ESC during active drawing
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && showOverlayPanel && pendingOverlay) {
        e.preventDefault()
        restartOverlayDraw(pendingOverlay, selectedOverlayType)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [showOverlayPanel, pendingOverlay, selectedOverlayType, restartOverlayDraw])

  // Measurement visualization - render line and distance label
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return

    const sourceId = 'measure-line'
    const layerId = 'measure-line-layer'
    const pointsLayerId = 'measure-points-layer'

    // Add source if it doesn't exist
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      
      // Add line layer
      map.addLayer({
        id: layerId,
        type: 'line',
        source: sourceId,
        filter: ['==', '$type', 'LineString'],
        paint: {
          'line-color': '#ffcc00',
          'line-width': 3,
          'line-dasharray': [3, 2]
        }
      })
      
      // Add points layer
      map.addLayer({
        id: pointsLayerId,
        type: 'circle',
        source: sourceId,
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 6,
          'circle-color': '#ffcc00',
          'circle-stroke-color': '#000',
          'circle-stroke-width': 2
        }
      })
    }

    // Build features from measurePoints
    const features = []
    
    // Add point markers
    measurePoints.forEach((pt, idx) => {
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [pt.lng, pt.lat] },
        properties: { index: idx }
      })
    })
    
    // Add line if we have 2 points
    if (measurePoints.length === 2) {
      features.push({
        type: 'Feature',
        geometry: {
          type: 'LineString',
          coordinates: [
            [measurePoints[0].lng, measurePoints[0].lat],
            [measurePoints[1].lng, measurePoints[1].lat]
          ]
        },
        properties: {}
      })
    }

    // Update the source
    const source = map.getSource(sourceId)
    if (source) {
      source.setData({ type: 'FeatureCollection', features })
    }
  }, [measurePoints, mapRef])

  // Basemap switching is pure VISIBILITY toggling of the raster
  // basemap layers that ship in MAP_STYLE ('default' / 'terrain' /
  // 'topo' / 'satellite') — the unified architecture has no dynamic
  // basemap sources. The legacy applyBaseMap effect
  // (stamen/offline-mbtiles era: dynamic 'base-map' source +
  // insert-candidate lists of retired layer ids) was deleted
  // 2026-07-06 after its opaque raster inserted ABOVE runtime layers
  // and silently buried the MGRS grid.
  //
  // Two riders on the basemap selection:
  //  - background paint swaps per basemap so tile-load gaps flash the
  //    right paper color (paper-white topo vs cream vs near-black
  //    satellite).
  //  - the topo sheet's brown contour linework paints CLIENT-side from
  //    the shared DEM contour source (utils/contours.js) — it IS the
  //    topo look, so it shows/hides with the basemap selection AND the
  //    analyst's Contours layer toggle (layerVisibility.contours,
  //    default on). Runs in headless renders too: a product that
  //    declares map_basemap: "topo" exports with contours.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    try {
      for (const id of Object.keys(BASE_MAP_SOURCES)) {
        if (map.getLayer(id)) {
          map.setLayoutProperty(
            id, 'visibility', id === baseMapStyle ? 'visible' : 'none')
        }
      }
      if (map.getLayer('background')) {
        map.setPaintProperty(
          'background', 'background-color',
          BASEMAP_BACKGROUNDS[baseMapStyle] || BASEMAP_BACKGROUNDS.default)
      }
      ensureContourLayers(
        map, 'topo',
        baseMapStyle === 'topo' && layerVisibility.contours !== false,
        'places-region-labels')
    } catch (err) {
      console.warn('Failed to switch base map:', err)
    }
  }, [baseMapStyle, layerVisibility, mapLoaded, mapRef])

  // --- Weather overlay (OpenWeatherMap Weather Maps 2.0 forecast tiles,
  // ported from the pytho-vite copy). Tiles ride this service's OWN
  // /tiles/weather proxy (API key stays server-side); ?date= carries the
  // forecast-hour scrub. Analyst-view chrome only — the headless render
  // path never fetches forecast tiles.
  useEffect(() => {
    if (headless) return
    const map = mapRef.current
    if (!map || !mapLoaded) return

    const SRC = 'weather-overlay'
    const LYR = 'weather-overlay-layer'

    // Remove old layer/source on every knob change, then re-add.
    if (map.getLayer(LYR)) map.removeLayer(LYR)
    if (map.getSource(SRC)) map.removeSource(SRC)

    if (!weatherVisible) return

    // Forecast unix timestamp for the 0-72h scrub (0 = current frame).
    const forecastSec = Math.floor(Date.now() / 1000) + weatherHour * 3600
    const dateParam = weatherHour > 0 ? `?date=${forecastSec}` : ''
    const tileUrl = `${API_BASE}/tiles/weather/${weatherLayer}/{z}/{x}/{y}${dateParam}`

    try {
      map.addSource(SRC, {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
      })

      // Insert above the basemap rasters but below place labels, the
      // doctrinal paint hit-targets, and every operational layer. The
      // unified style's first above-basemap layers are the place-label
      // symbols; entities-points is the operational fallback anchor.
      let insertBefore = null
      for (const l of map.getStyle().layers) {
        if (['places-region-labels', 'places-locality-labels',
             'entities-points'].includes(l.id)) {
          insertBefore = l.id
          break
        }
      }

      // Full-coverage layers (temperature, pressure, humidity) need lower
      // opacity so the basemap shows through; sparse layers (precip, wind,
      // clouds) can run stronger.
      const subtle = ['TA2', 'TD2', 'APM', 'HRD0'].includes(weatherLayer)

      map.addLayer({
        id: LYR,
        type: 'raster',
        source: SRC,
        paint: {
          'raster-opacity': subtle ? 0.7 : 0.9,
          'raster-fade-duration': 0,
          'raster-saturation': subtle ? 0.3 : 0.6,
          'raster-contrast': subtle ? 0.1 : 0.3,
          'raster-brightness-min': 0.05,
        },
      }, insertBefore)
    } catch (err) {
      console.warn('Failed to apply weather overlay:', err)
    }
  }, [weatherVisible, weatherLayer, weatherHour, mapLoaded, mapRef, headless])

  // Initialize map (wait for config + saved viewport to load first)
  useEffect(() => {
    if (mapRef.current || !mapContainerRef.current || !viewportLoaded || !configLoaded) return

    let isCleanedUp = false
    let timeout

    try {
      // If offline region bounds are available, compute center from tile coverage
      const bbox = regionBounds?.bbox
      const regionCenter = bbox
        ? [(bbox.west + bbox.east) / 2, (bbox.south + bbox.north) / 2]
        : null

      // Clamp savedViewport to within regionBounds.bbox WHEN a bbox
      // exists. A stale saved viewport from a different deployment /
      // scenario would otherwise stomp on the offline AO and drop the
      // analyst on a blank canvas (this is exactly how the IDX 26 AO
      // ended up centered on California — a dev-era SF row in the maps
      // table outlived the scenario switch). With NO offline region
      // (the online/cloud deployment) there is nothing to clamp
      // against and the saved viewport is authoritative — requiring a
      // bbox here inverted the guard into "never restore" on cloud,
      // and every open re-centered on the frontend default, whose
      // moveend save then clobbered the map's real saved viewport.
      const savedCenterValid = (() => {
        if (!savedViewport?.center) return false
        if (!bbox) return true
        const [lng, lat] = savedViewport.center
        return lng >= bbox.west && lng <= bbox.east
            && lat >= bbox.south && lat <= bbox.north
      })()

      // Per-deployment first-open camera from the backend's /config
      // (settings.default_view env) — the deployment's env owns its AO;
      // the shared frontend carries no event-specific coordinates.
      const configDefaultView = appConfigRef.current?.defaultView || appConfig?.defaultView || null

      // Explicit `bounds` prop takes priority over savedViewport. Callers
      // who pass bounds (headless render, embedded EditMap overlay) want
      // the camera framed on THAT bbox, not on a stale saved center+zoom
      // from a previous session. The savedViewport restoration logic
      // only kicks in when no bounds are passed (legacy analyst route).
      const explicitBounds = Array.isArray(bounds) && bounds.length === 4
      // Use saved viewport from backend if available AND inside AO AND no
      // explicit bounds were passed; otherwise use region center or
      // props/defaults. In headless mode, ignore saved viewport —
      // Playwright drives the framing via explicit `bounds` prop.
      const mapCenter = (!headless && !explicitBounds && savedCenterValid && savedViewport.center)
                     || regionCenter
                     || configDefaultView?.center
                     || center
                     || defaultCenter
      const mapZoom = (!headless && !explicitBounds ? savedViewport?.zoom : undefined)
                   ?? configDefaultView?.zoom
                   ?? zoom
                   ?? defaultZoom

      // Build map options - constrain to tile bounds when offline
      const mapOptions = {
        container: mapContainerRef.current,
        center: mapCenter,
        zoom: mapZoom,
        preserveDrawingBuffer: true,
        attributionControl: false,
        // Label cross-fade OFF. The default 300 ms symbol fade kept
        // the placement pass permanently dirty across this style's
        // symbol-layer stack, so MapLibre re-rendered every frame at
        // full refresh rate FOREVER - 100% GPU with the map sitting
        // still (measured: 115 renders/s idle -> settles with fade 0).
        fadeDuration: 0,
      }
      // Headless render OR explicit-bounds caller (embedded EditMap):
      // pass bounds to fit at init. padding=0 because the headless
      // capture must show the AOR edge-to-edge (any padding adds basemap
      // halo around the doctrinal layer that the exporter embeds). The
      // editor mount uses the same path so the analyst sees exactly the
      // figure they clicked Edit on.
      if (explicitBounds) {
        mapOptions.bounds = bounds
        mapOptions.fitBoundsOptions = { padding: 0, duration: 0 }
      }
      if (headless) {
        mapOptions.interactive = false
      }
      if (bbox && !headless) {
        // maxBounds locks the map's pan/zoom to within regionBounds.bbox.
        // In analyst-editor mode that prevents drifting off the AO. In
        // HEADLESS render mode we want to honor whatever bbox the renderer
        // requested (e.g. wider Annex C polygon to show 60/62/66 Div
        // disposition), so skip the lock.
        mapOptions.maxBounds = [[bbox.west, bbox.south], [bbox.east, bbox.north]]
        const lngSpan = bbox.east - bbox.west
        const latSpan = bbox.north - bbox.south
        const span = Math.max(lngSpan, latSpan)
        if (span > 0) {
          mapOptions.minZoom = Math.max(0, Math.floor(Math.log2(360 / span)) - 1)
        }
      }
      if (regionBounds?.max_zoom) {
        mapOptions.maxZoom = regionBounds.max_zoom
      }

      // Pass style in constructor so MapLibre never has a no-style → has-style
      // transition. Splitting into `new Map()` + `setStyle()` let the first
      // openmaptiles tile fetch fire before the style's `glyphs:` URL was
      // live, causing a 400 on `/fonts/Open Sans Regular/0-255.pbf` that
      // poisoned the tile in MapLibre's cache until the user panned.
      mapOptions.style = MAP_STYLE
      mapRef.current = new maplibregl.Map(mapOptions)

      // UNBRICKABLE RENDER LOOP. MapLibre v3's render TaskQueue.run()
      // has no try/finally: ONE exception escaping any render task —
      // a custom layer, an event handler fired during the frame, any
      // painter — leaves _currentlyRunning set, and every later frame
      // dies with "Attempting to run(), but is already running" until
      // the page reloads. Wrap _render: catch the throw, reset the
      // poisoned queue, log the REAL first error (this is the stack
      // that matters — paste it, not the already-running flood), and
      // let the next frame proceed. One bad frame must never cost the
      // analyst their session.
      {
        const _m = mapRef.current
        const _origRender = _m._render.bind(_m)
        _m._render = (...args) => {
          try {
            return _origRender(...args)
          } catch (err) {
            const q = _m._renderTaskQueue
            if (q && q._currentlyRunning) q._currentlyRunning = false
            console.error('map render frame failed (recovered):', err)
            try { _m.triggerRepaint() } catch { /* torn down */ }
          }
        }
      }

      // Belt-and-suspenders initial repaint. MapLibre v3 in this
      // config (raster-only basemap sources, glyphs URL set, no
      // sprite) sometimes finishes style.load internally but never
      // fires the public style.load event, which means our
      // in-handler triggerRepaint below never runs. Poll for
      // `_loaded === true` on the internal Style object; the moment
      // it flips, force a triggerRepaint. Bounded: caps at 20 checks
      // over 4 seconds, then gives up (letting the analyst pan/zoom
      // as the escape hatch — no worse than the pre-fix behavior).
      // See MapLibre-GL-JS issue thread on _loaded vs isStyleLoaded.
      {
        let ticks = 0
        const kick = setInterval(() => {
          ticks += 1
          const s = mapRef.current && mapRef.current.style
          if (!s) return
          if (s._loaded) {
            try { mapRef.current.triggerRepaint() } catch (_e) {}
            clearInterval(kick)
            return
          }
          if (ticks > 20) clearInterval(kick)
        }, 200)
      }

      // 3D terrain relief on the INTERACTIVE map: the Mapterhorn DEM
      // already in-stack, as a raster-dem source driving MapLibre's
      // native terrain — pitched views stand on real elevation instead
      // of a flat tilted plane, and the envelope volumes anchor at
      // true ground height. Headless product renders stay planimetric
      // (exports are top-down map figures; terrain would displace
      // symbol geometry against the doctrinal SVG pass).
      if (!headless) {
        mapRef.current.once('load', () => {
          const m = mapRef.current
          if (!m || m.getSource('terrain-dem')) return
          try {
            m.addSource('terrain-dem', {
              type: 'raster-dem',
              tiles: [`${window.location.origin}/geo-api/v1/tiles/dem/{z}/{x}/{y}.webp`],
              encoding: 'terrarium',
              tileSize: 256,
              maxzoom: 12,
            })
            // Terrain gates on zoom: MapLibre v3's tile-cover math
            // breaks with terrain enabled when zoomed far out (basemap
            // tiles simply stop loading at continental scale — fixed
            // upstream in v4). Below the gate the map is planimetric;
            // hillshade below carries the relief at every zoom.
            //
            // The flip happens ONLY at true idle: v3's camera chain
            // (_afterEase -> _updateMapTransform -> recalculateZoom)
            // dereferences the terrain object, and setTerrain(null)
            // during an active ease crashes with "can't access
            // property getElevationForLngLatZoom, terrain is null".
            // Hysteresis keeps the boundary from thrashing.
            const TERRAIN_ON_ZOOM = 7.3
            const TERRAIN_OFF_ZOOM = 6.7
            const applyTerrainGate = () => {
              if (m.isMoving() || m.isZooming() || m.isRotating()) return
              const z = m.getZoom()
              const has = !!m.getTerrain()
              try {
                if (!has && z >= TERRAIN_ON_ZOOM) {
                  m.setTerrain({ source: 'terrain-dem', exaggeration: 1.5 })
                } else if (has && z < TERRAIN_OFF_ZOOM) {
                  m.setTerrain(null)
                }
              } catch (err) {
                console.warn('terrain gate flip failed:', err && err.message)
              }
            }
            m.on('idle', applyTerrainGate)
            applyTerrainGate()
            // Hillshade from the same DEM, under the data layers:
            // geometric displacement alone is sub-pixel at
            // operational zooms in gentle terrain - shading is what
            // makes relief READ on a map.
            const firstNonRaster = (m.getStyle().layers
              .find(l => l.type !== 'raster' && l.type !== 'background') || {}).id
            m.addLayer({
              id: 'terrain-hillshade',
              type: 'hillshade',
              source: 'terrain-dem',
              paint: {
                'hillshade-exaggeration': 0.45,
                'hillshade-shadow-color': '#5a4a3a',
              },
            }, firstNonRaster)
          } catch (err) {
            console.warn('terrain unavailable:', err && err.message)
          }
        })
      }

      // Compass control — shows the current bearing and resets to north on
      // click (also restores pitch via visualizePitch). Zoom buttons live in
      // the custom MapControls, so this control carries the compass only.
      // Analyst chrome → skip it on the headless screenshot map.
      if (!headless) {
        mapRef.current.addControl(
          new maplibregl.NavigationControl({
            showZoom: false,
            showCompass: true,
            visualizePitch: true,
          }),
          'bottom-right',
        )
        // Native MapLibre scale bar for the interactive editor (replaces
        // the custom MapCartographicChrome scale box, which is now
        // headless/product-render only). Bottom-RIGHT, added AFTER the
        // compass: MapLibre floats bottom-right controls right-to-left,
        // so the compass keeps the corner and the scale bar sits to its
        // LEFT in the same row (vertical centering via the CSS margin in
        // index.css). The doctrinal RF marginalia still bake into the
        // product export via the headless chrome.
        mapRef.current.addControl(
          new maplibregl.ScaleControl({ maxWidth: 140, unit: 'metric' }),
          'bottom-right',
        )
      }

      // Timeout fallback
      timeout = setTimeout(() => {
        if (isCleanedUp) return
        addActivity('Map load timeout - check console for errors', 'error')
        setMapLoaded(true)
      }, 5000)

      // Error handler. Aborted tile fetches are NORMAL churn — every
      // zoom animation cancels in-flight tiles, and the contour worker
      // surfaces those as tile 'error' events. Logging them at error
      // level buried real failures under dozens of "Map error" lines
      // per gesture; they go to debug. Everything else stays loud.
      mapRef.current.on('error', (e) => {
        const msg = e.error?.message || e.message || 'Unknown'
        const benignAbort = e.tile && /abort/i.test(String(msg))
        if (benignAbort) {
          console.debug('Map tile fetch aborted (zoom churn):', e.sourceId, msg)
          return
        }
        console.error('Map error:', e)
        addActivity(`Map error: ${msg}`, 'error')
      })

      // Style load handler
      mapRef.current.on('style.load', () => {
        if (isCleanedUp) return
        clearTimeout(timeout)
        setMapLoaded(true)
        addActivity('Map loaded', 'success')

        // Force an initial repaint. Without this, the analyst-served
        // iframe (nginx → geo-agent StaticFiles) sometimes loads the
        // style + tiles + textures with no auto-paint kick — the
        // basemap sits blank on `#f0e4d4` (the background layer) until
        // the analyst pans or zooms. Verified on the actual URL
        // 2026-07-02: triggerRepaint here makes the initial view paint
        // the same as after a pan.
        try { mapRef.current.triggerRepaint() } catch (_e) {}

        // Initialize mil-sym-ts renderer
        initMilSymRenderer(setMilSymRendererReady, addActivity)

        // Add MGRS grid
        addMGRSGrid(mapRef.current)

        // Add data sources
        addDataSources(mapRef.current)

        // Persistent saved-route sources + layers (created once; the
        // painter in loadMapState only ever calls setData on them).
        // BEFORE addMapLayers so routes paint beneath entity layers.
        initSavedRouteLayers(mapRef.current)

        // Add layers
        addMapLayers(mapRef.current)

        // Analyst-only: MapboxDraw (for overlay creation) + drawing preview
        // layers. Headless render never draws — skip both to keep the canvas
        // free of editor control DOM.
        if (!headless) {
          initMapboxDraw(mapRef.current, drawRef, handleDrawCreate)
          addDrawingPreviewLayers(mapRef.current)
        }

        // Real-time preview of tactical graphic while drawing.
        // Entire drawing-preview wiring is analyst-only — headless render
        // never draws, never receives a mousemove, and has no MapboxDraw
        // control. Skip the registration to keep the listener list clean.
        if (!headless) {
          const updateDrawingPreview = () => {
            if (!overlayDrawModeRef.current || !drawRef.current) {
              const source = mapRef.current?.getSource('drawing-preview')
              if (source) source.setData({ type: 'FeatureCollection', features: [] })
              return
            }

            const features = drawRef.current.getAll?.()
            if (!features || features.features.length === 0) {
              const source = mapRef.current?.getSource('drawing-preview')
              if (source) source.setData({ type: 'FeatureCollection', features: [] })
              return
            }

            const drawingFeature = features.features[0]
            let coords = []

            if (drawingFeature.geometry.type === 'LineString') {
              coords = drawingFeature.geometry.coordinates
            } else if (drawingFeature.geometry.type === 'Polygon') {
              coords = drawingFeature.geometry.coordinates[0] || []
            } else if (drawingFeature.geometry.type === 'Point') {
              coords = [drawingFeature.geometry.coordinates]
            }

            // Need at least 2 points for a meaningful preview
            if (coords.length < 2) {
              const source = mapRef.current?.getSource('drawing-preview')
              if (source) source.setData({ type: 'FeatureCollection', features: [] })
              return
            }

            // Get overlay type info and SIDC
            const overlayType = selectedOverlayTypeRef.current
            const typeInfo = getOverlayTypeInfo(overlayType, appConfigRef.current?.overlayTypes)
            if (!typeInfo?.sidc) return

            const affiliation = 'Friend'
            const overlayColor = AFFILIATION_COLORS[affiliation] || '#0000FF'

            try {
              const graphicGeoJson = createTacticalGraphic(typeInfo.sidc, coords, {
                affiliation: affiliation
              }, mapRef.current)

              if (graphicGeoJson) {
                const parsed = typeof graphicGeoJson === 'string' ? JSON.parse(graphicGeoJson) : graphicGeoJson
                const previewFeatures = []

                // Process feature: strip labels and add colors
                const processFeature = (f) => {
                  // Skip label-only features
                  if (f.geometry?.type === 'Point' && f.properties?.label && !f.properties?.iconId) return

                  const { label, name, uniqueDesignation, additionalInfo, ...rest } = f.properties || {}
                  previewFeatures.push({
                    ...f,
                    properties: { ...rest, strokeColor: overlayColor, fillColor: overlayColor }
                  })
                }

                if (parsed.features) {
                  parsed.features.forEach(processFeature)
                } else if (parsed.type === 'Feature') {
                  processFeature(parsed)
                }

                const source = mapRef.current?.getSource('drawing-preview')
                if (source) {
                  source.setData({ type: 'FeatureCollection', features: previewFeatures })
                }
              }
            } catch (err) {
              // Preview rendering failed silently
            }
          }

          // Update preview on mouse move and click during drawing
          mapRef.current.on('mousemove', () => {
            if (overlayDrawModeRef.current) {
              updateDrawingPreview()
            }
          })

          mapRef.current.on('click', () => {
            if (overlayDrawModeRef.current) {
              // Delay to let MapboxDraw update its internal state
              setTimeout(updateDrawingPreview, 100)
            }
          })

          // Handle ESC key during drawing - restart draw mode instead of exiting
          mapRef.current.on('draw.modechange', (e) => {
            // Clear preview when mode changes
            if (e.mode === 'simple_select') {
              const source = mapRef.current?.getSource('drawing-preview')
              if (source) source.setData({ type: 'FeatureCollection', features: [] })
            }

            // If mode changed to simple_select while we were in overlay draw mode,
            // check if this is ESC (no features) or completion (has features)
            if (e.mode === 'simple_select' && overlayDrawModeRef.current) {
              // Check if there are any features in the draw control
              // If there are features, a drawing was just completed - don't restart
              const features = drawRef.current?.getAll?.()
              if (features && features.features && features.features.length > 0) {
                // Drawing was completed successfully, don't restart
                return
              }

              // No features means ESC was pressed - restart drawing
              const overlayType = selectedOverlayTypeRef.current
              if (overlayType && drawRef.current) {
                // Small delay to let the mode change complete
                setTimeout(() => {
                  const overlayTypes = appConfigRef.current?.overlayTypes || {}
                  const isLine = (overlayTypes.line || []).some(t => t.value === overlayType)
                  const isPoint = (overlayTypes.point || []).some(t => t.value === overlayType)

                  if (isPoint) {
                    drawRef.current.changeMode('draw_point')
                  } else if (isLine) {
                    drawRef.current.changeMode('draw_line_string')
                  } else {
                    drawRef.current.changeMode('draw_polygon')
                  }
                }, 50)
              }
            }
          })
        }

        // Set up event handlers (analyst-only — headless render never receives events)
        if (!headless) {
          setupEventHandlers(mapRef.current)

          // Set up viewport refresh and async save (analyst-only — headless
          // never moves the camera after fitBounds, and must never write
          // viewport prefs back to the server).
          setupViewportRefresh(mapRef.current, () => loadMapStateCbRef.current(), api, mapId)
        }

        // Load initial data
        loadMapStateWithCallbacks()

        if (onMapLoad) {
          onMapLoad(mapRef.current)
        }
      })

    } catch (err) {
      console.error('Failed to initialize map:', err)
      addActivity(`Map initialization failed: ${err.message}`, 'error')
    }

    return () => {
      isCleanedUp = true
      clearTimeout(timeout)
      if (drawRef.current && mapRef.current) {
        mapRef.current.removeControl(drawRef.current)
        drawRef.current = null
      }
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [viewportLoaded, configLoaded]) // eslint-disable-line react-hooks/exhaustive-deps

  // === Event Handlers ===

  const handleOverlaySave = async () => {
    const result = await savePendingOverlay(pendingOverlay, overlayForm, selectedOverlayType, loadMapStateWithCallbacks)
    if (result && onOverlayCreate) {
      onOverlayCreate(result)
    }
  }

  const handleOverlayEditSave = async (overlay) => {
    const kind = overlay.properties?.kind
    const newSidc = getSidcForOverlayType(kind, overlayForm.affiliation)
    
    // If in geometry edit mode, save geometry first
    if (geometryEditMode) {
      await saveGeometryEdit(null) // Don't reload yet, we'll do it after attrs save
    }
    
    await updateOverlay(overlay.id, {
      name: overlayForm.name || overlayForm.designation,
      attrs: { ...overlayForm, sidc: newSidc }
    })
    loadMapStateWithCallbacks()
  }

  const handleOverlayDelete = async (overlayId) => {
    // Cancel geometry edit if active
    if (geometryEditMode) {
      cancelGeometryEdit(null)
    }
    await deleteOverlay(overlayId)
    loadMapStateWithCallbacks()
  }

  const handleEntitySave = async (entityId, attrs) => {
    await updateEntityAttrs(entityId, attrs)
    loadMapStateWithCallbacks()
  }

  const handleEntityDelete = async (entityId) => {
    await deleteEntity(entityId)
    loadMapStateWithCallbacks()
  }

  const handleEntityCreate = async (coords, formData) => {
    const entity = await createNewEntity(coords, formData)
    if (entity) loadMapStateWithCallbacks()
    return entity
  }

  const handleStartOverlayDraw = (overlayType) => {
    startOverlayDraw(overlayType, setSelectedOverlayType)
  }

  const handleCancelGeometryEdit = () => {
    cancelGeometryEdit(loadMapStateWithCallbacks)
  }

  // === Render ===

  // Headless render: just the bare map canvas. Every panel / banner / control
  // is analyst-only chrome that has no place in the screenshot.
  if (headless) {
    return (
      <div className="map-container map-container-headless">
        <div id="map" ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />
      </div>
    )
  }

  return (
    <div className={`map-container ${placementMode ? 'placement-active' : ''} ${overlayDrawMode ? 'overlay-draw-active' : ''} ${measureMode ? 'measure-active' : ''} ${geometryEditMode ? 'geometry-edit-active' : ''} ${routePlanMode ? 'route-plan-active' : ''} ${routeEditMode ? 'route-edit-active' : ''}`}>
      <div
        id="map"
        ref={mapContainerRef}
        style={{ width: '100%', height: '100%' }}
        onDragOver={handleMapDragOver}
        onDrop={handleMapDrop}
      />

      <MapControls
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onExitOverlayDrawMode={exitOverlayDrawMode}
        replanRoute={replanRoute}
        onUndo={undo}
        onRedo={redo}
        canUndo={canUndo}
        canRedo={canRedo}
        showUndoRedo={true}
      />

      <CustomSymbolLibrary />

      {/* Timeline scrub over the append-only position tracks — shows
          itself only when the project carries 2+ dated observations. */}
      <TimelineScrubber />

      {/* THE confirmation dialog — browser popups are banned; every
          confirm flows through GeoAgentProvider.requestConfirm. */}
      <ConfirmModal />

      <AllBanners
        onExitOverlayDrawMode={exitOverlayDrawMode}
      />

      <MeasureBanner />

      {/* Distance display when measuring */}
      {measurePoints.length === 2 && (
        <MeasureDistanceDisplay points={measurePoints} />
      )}

      {/* Edit affordances — mounted on EVERY surface. The live map is
          editable for analyst-authored content (Place Unit / Draw
          Overlay / drag / edit / delete); pipeline-fed rows stay
          inspect-only there via the provenance boundary in
          useMapEvents.isPipelineOwned. Edit sessions manipulate
          everything. */}
      <EntityPanel
        onCreate={handleEntityCreate}
        onSave={handleEntitySave}
        onDelete={handleEntityDelete}
      />
      <OverlayToolbar onStartDraw={handleStartOverlayDraw} />

      <OverlayPanel
        onSave={handleOverlaySave}
        onCancel={() => cancelOverlayCreation(pendingOverlay)}
        onEditSave={handleOverlayEditSave}
        onDelete={handleOverlayDelete}
        onCancelGeometryEdit={handleCancelGeometryEdit}
      />

      {/* Live ops-map left-click unit inspector. Self-gates on
          selectedUnitMeta (only set by the live-mode click handler), so it
          stays inert in edit mode and headless renders. */}
      <UnitMetadataPanel />

      {/* Control-measure placard — view-mode click inspector for
          tactical graphics. Self-gates on selectedOverlayMeta. */}
      <OverlayMetadataPanel />

      {/* Live ops-map signal-report inspector (KLIEGLIGHT / OSIR markers).
          Self-gates on selectedSignalReport; "Open in editor" promotes the
          autodraft artifact and opens it in LiveEditor. */}
      <SignalReportPanel />

      <SymbolPicker />
      <LayerSwitcher />
      <RoutePlannerPanel
        getRouteEditCoordsRef={getRouteEditCoordsRef}
      />
      <RouteFailureModal />

      {/* Route planning banner */}
      {routePlanMode && !routeResult && (
        <div style={{
          position: 'absolute',
          top: '10px',
          left: '50%',
          transform: 'translateX(-50%)',
          background: routeLoading ? '#1e3a5f' : '#1a1a2e',
          color: routeLoading ? '#60a5fa' : '#3B82F6',
          padding: '8px 20px',
          borderRadius: '20px',
          fontSize: '13px',
          fontWeight: '500',
          border: `1px solid ${routeLoading ? '#2563eb' : '#333'}`,
          zIndex: 500,
          pointerEvents: 'none',
        }}>
          {routeLoading
            ? 'Planning route — fetching roads, terrain & land cover...'
            : !routeStart
              ? 'Click map to set start point'
              : !routeEnd
                ? 'Click map to set end point'
                : 'Planning route...'}
        </div>
      )}

      <StatusBar />
    </div>
  )
}

// === Helper Components ===

/**
 * Calculate haversine distance between two points (great-circle distance)
 * @param {Object} point1 - {lng, lat}
 * @param {Object} point2 - {lng, lat}
 * @returns {number} Distance in kilometers
 */
function haversineDistance(point1, point2) {
  const R = 6371 // Earth radius in km
  const toRad = (deg) => deg * Math.PI / 180
  
  const dLat = toRad(point2.lat - point1.lat)
  const dLon = toRad(point2.lng - point1.lng)
  
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(toRad(point1.lat)) * Math.cos(toRad(point2.lat)) *
            Math.sin(dLon / 2) ** 2
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  
  return R * c
}

/**
 * Format distance for display
 */
function formatDistance(km) {
  if (km < 1) {
    return `${Math.round(km * 1000)} m`
  } else if (km < 10) {
    return `${km.toFixed(2)} km`
  } else {
    return `${km.toFixed(1)} km`
  }
}

/**
 * Display component for measurement distance
 */
function MeasureDistanceDisplay({ points }) {
  if (points.length !== 2) return null
  
  const distanceKm = haversineDistance(points[0], points[1])
  const distanceNm = distanceKm / 1.852 // Convert to nautical miles
  const distanceMi = distanceKm / 1.609 // Convert to statute miles
  
  // Format miles for display
  const formatMiles = (mi) => {
    if (mi < 0.1) {
      return `${Math.round(mi * 5280)} ft`
    } else if (mi < 10) {
      return `${mi.toFixed(2)} mi`
    } else {
      return `${mi.toFixed(1)} mi`
    }
  }
  
  return (
    <div className="measure-distance-display">
      <div className="measure-distance-value">{formatMiles(distanceMi)}</div>
      <div className="measure-distance-alt">
        {formatDistance(distanceKm)} / {distanceNm.toFixed(2)} nm
      </div>
    </div>
  )
}

// === Helper Functions ===

/**
 * Initialize MIL-STD-2525 renderer
 */
function initMilSymRenderer(setMilSymRendererReady, addActivity) {
  // mil-sym-ts loads its symbol catalog asynchronously. Earlier this
  // polled once after 1s and gave up — when the symbol bundle took
  // longer (cold cache, large catalog, or a slow worker thread), the
  // ready flag never flipped and HeadlessReadySignal stalled forever,
  // which timed out every headless map render. Poll every 250ms for up
  // to 15s, then flip the flag anyway so headless captures at least
  // ship the basemap. Console message lets the operator see which path
  // resolved.
  let elapsed = 0
  const stepMs = 250
  const maxMs = 15000
  const tick = () => {
    try {
      if (getMilStdIconRenderer().isReady()) {
        setMilSymRendererReady(true)
        addActivity('MIL-STD-2525 tactical graphics renderer ready', 'success')
        return
      }
    } catch {
      /* keep polling */
    }
    elapsed += stepMs
    if (elapsed >= maxMs) {
      // Force-flip so the headless render at least captures the basemap.
      // The doctrinal SVG overlay may render mil-sym icons as fallback
      // glyphs; that's preferable to an indefinite timeout.
      setMilSymRendererReady(true)
      addActivity('MIL-STD-2525 renderer timeout — proceeding without symbols', 'warn')
      return
    }
    setTimeout(tick, stepMs)
  }
  tick()
}

/**
 * Add MGRS grid source and layers
 */
function addMGRSGrid(map) {
  map.addSource('mgrs-grid', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] }
  })

  MGRS_GRID_LAYERS.forEach(layer => map.addLayer(layer))
  updateMGRSGrid(map)
}

/**
 * Update MGRS grid based on current map view
 */
function updateMGRSGrid(map) {
  if (!map) return

  const bounds = map.getBounds()
  const zoom = map.getZoom()

  const gridData = generateMGRSGrid({
    north: bounds.getNorth(),
    south: bounds.getSouth(),
    east: bounds.getEast(),
    west: bounds.getWest()
  }, zoom)

  const source = map.getSource('mgrs-grid')
  if (source) source.setData(gridData)
}

/**
 * Add GeoJSON data sources
 */
function addDataSources(map) {
  map.addSource('entities', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
    promoteId: 'id'
  })
  map.addSource('tactical-graphics', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] }
  })
  map.addSource('mil-units', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
    promoteId: 'id'
  })
  // Preview source for showing tactical graphic while drawing
  map.addSource('drawing-preview', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] }
  })
}

/**
 * Initialize MapboxDraw control (for overlay creation only)
 */
function initMapboxDraw(map, drawRef, handleDrawCreate) {
  const draw = new MapboxDraw({
    displayControlsDefault: false,
    controls: {},
    styles: DRAW_STYLES
  })

  map.addControl(draw, 'top-left')
  drawRef.current = draw

  map.on('draw.create', handleDrawCreate)
}

/**
 * Set up viewport change refresh and async save to backend
 */
function setupViewportRefresh(map, loadMapStateWithCallbacks, api, mapId) {
  let saveTimeout = null

  map.on('moveend', () => {
    // NO data refetch on camera moves — loadMapState pulls the whole
    // map (see useMapInstance), so every feature is already client-side
    // and MapLibre culls it. Data freshness rides the WebSocket
    // broadcasts + refresh triggers, not the camera.

    // Debounce async save to backend (longer delay to avoid excessive saves)
    if (saveTimeout) clearTimeout(saveTimeout)
    saveTimeout = setTimeout(() => {
      saveViewportToBackend(map, api, mapId)
    }, 1000)

    updateMGRSGrid(map)
  })
}

/**
 * Save viewport state to backend asynchronously
 * Silently fails to avoid disrupting user experience
 */
async function saveViewportToBackend(map, api, mapId) {
  if (!map || !api || !mapId) return
  // Belt-and-suspenders headless guard. setupViewportRefresh is already
  // gated on !headless at its call site, but a regression there has
  // clobbered the analyst's saved AO bbox during a headless render run
  // — once the render's fitBounds fires moveend, this writes the
  // viewport-fitted (smaller) bbox over the saved one. Defense in depth:
  // refuse to write anything from the headless render route. That route
  // is /geo-app/headless in this repo (the pre-move embed lived under
  // an .../operations-map/render path — keep matching '/render' so any
  // legacy embed stays protected too).
  try {
    if (typeof window !== 'undefined' && window.location &&
        (window.location.pathname.includes('/headless') ||
         window.location.pathname.includes('/render'))) {
      return
    }
  } catch { /* SSR / no window */ }

  try {
    const bounds = map.getBounds()
    const center = map.getCenter()
    const zoom = map.getZoom()

    await api.updateMapViewport(mapId, {
      bbox_west: bounds.getWest(),
      bbox_south: bounds.getSouth(),
      bbox_east: bounds.getEast(),
      bbox_north: bounds.getNorth(),
      center_lng: center.lng,
      center_lat: center.lat,
      zoom: zoom
    })
  } catch (err) {
    // Silently fail - this is a background save
    console.warn('Failed to save viewport:', err)
  }
}
