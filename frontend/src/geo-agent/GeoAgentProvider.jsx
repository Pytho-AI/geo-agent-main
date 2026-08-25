import React, { createContext, useContext, useState, useRef, useCallback, useEffect } from 'react'
import { DEFAULT_BASE_MAP } from './utils/mapStyles'
import { useGeoAgentRealtime } from './hooks/useGeoAgentRealtime'
import { logAnalystEvent } from '../lib/analystEvent'

// Create the context
const GeoAgentContext = createContext(null)

// Default configuration. The camera fallback is a NEUTRAL world view —
// ONE image serves every deployment, so no event AO is hardcoded here.
// Resolution order at map init (GeoAgentMap): the map's saved viewport
// (clamped to the offline region when one exists) → offline region
// center → the backend /config defaultView (settings.default_view env,
// "lng,lat,zoom" — each deployment declares its own AO there) → VITE
// build args → these neutral values. The fallback only ever shows for
// a brand-new map on a deployment that set no DEFAULT_VIEW.
const DEFAULT_CONFIG = {
  // Task 6: the geo-agent frontend runs at the ORIGIN of the analyst
  // browser, so `/api/v1` here would collide with pytho-app's own
  // `/api/*` routes. Nginx routes the geo-agent backend under
  // `/geo-api/v1/*` (see Task 5) — same origin, distinct prefix so
  // both services coexist on the same host. Override with
  // VITE_GEO_AGENT_API_URL for dev running the frontend against a
  // standalone geo-agent backend on :9845.
  apiUrl: (import.meta.env.VITE_GEO_AGENT_API_URL || '/geo-api/v1'),
  // Map identity ALWAYS comes from the mounting page (?map_id → prop).
  // There is deliberately no default: maps are scoped per project/event
  // (the map id IS the projectId), and every fallback flavor —
  // per-deployment env, per-user, hardcoded — lands the analyst on the
  // wrong map. Pages guard before mounting the provider.
  mapId: null,
  defaultCenter: [
    parseFloat(import.meta.env.VITE_DEFAULT_CENTER_LON) || 15.0,
    parseFloat(import.meta.env.VITE_DEFAULT_CENTER_LAT) || 35.0,
  ],
  defaultZoom: parseFloat(import.meta.env.VITE_DEFAULT_ZOOM) || 2.5
}

// Initial empty config - will be loaded from backend
const INITIAL_APP_CONFIG = null

/**
 * GeoAgentProvider - Context provider for the Geo-Agent library
 *
 * @param {Object} props
 * @param {string} props.apiUrl - Base URL for the API
 * @param {string} props.mapId - Map identifier (UUID)
 * @param {[number, number]} props.defaultCenter - Default map center [lng, lat]
 * @param {number} props.defaultZoom - Default map zoom level
 * @param {boolean} props.headless - When true, render in headless screenshot mode.
 *   Suppresses analyst UI chrome (panels, toolbars, controls), disables saving
 *   viewport changes back to the backend, and lets the consuming page observe
 *   `mapLoaded` + `milSymRendererReady` to flip a `window.__renderReady` flag
 *   for Playwright. Defaults to false (interactive analyst view).
 * @param {React.ReactNode} props.children - Child components
 */
export function GeoAgentProvider({
  apiUrl = DEFAULT_CONFIG.apiUrl,
  mapId = DEFAULT_CONFIG.mapId,
  // Cognito sub / email of the analyst running this surface. Required for
  // multi-user writes — every /entities, /overlays, /custom-symbols POST
  // appends `?user_id=<userId>` so the geo-agent backend can record the
  // row's `created_by`. Mount sites that don't pass it (e.g. the legacy
  // headless screenshot route) fall back to the empty string and the
  // backend rejects the write with 422 — which is the correct behavior
  // for a multi-user system that needs to track who placed each symbol.
  userId = "",
  defaultCenter = DEFAULT_CONFIG.defaultCenter,
  defaultZoom = DEFAULT_CONFIG.defaultZoom,
  headless = false,
  // Active product type ('SITEMP' | 'MCOO' | 'THREAT_OVERLAY' | etc.) for
  // gates that previously read window.location.search?product_type=.
  // Embedded mounts (e.g. EditMap overlay inside DocEditor) pass it as
  // a prop because the DocEditor URL doesn't carry product_type. Route-
  // mounted consumers (OperationsMap, OperationsMapHeadless) read it
  // from URL themselves and pass it here, or leave undefined and let
  // the legacy URL-read paths fall through.
  productType = "",
  // Edit-mode gate. The operations map page is read-only by default
  // (analyst execution surface). The DocEditor edit-map deep link
  // (?from_artifact=<id>) flips this to true so OverlayToolbar /
  // EntityPanel / OverlayPanel mount and the click+drag edit handlers
  // in useMapEvents activate. The right-click "Generate TIDAT" gesture
  // is unconditional — it works in both modes.
  editEnabled = false,
  // The embedding shell's graph-viewer URL (?graph_viewer_url= on the
  // iframe). Empty = the shell has no graph viewer; deep links to it
  // (UnitMetadataPanel "View data source") stay hidden. geo-agent never
  // hardcodes a consumer's routes.
  shellGraphViewerUrl = '',
  children
}) {
  // Map refs
  const mapRef = useRef(null)
  const mapContainerRef = useRef(null)
  const drawRef = useRef(null)
  const milMarkersRef = useRef([])
  const tacticalGraphicMarkersRef = useRef([])

  // Map state
  const [mapLoaded, setMapLoaded] = useState(false)
  const [milSymRendererReady, setMilSymRendererReady] = useState(false)
  const [coordinates, setCoordinates] = useState({ lng: 0, lat: 0 })

  // App config from backend (source of truth for types, SIDC codes, etc.)
  const [appConfig, setAppConfig] = useState(INITIAL_APP_CONFIG)
  const [configLoaded, setConfigLoaded] = useState(false)
  const [configError, setConfigError] = useState(null)

  // Saved map viewport from backend (restored on page load)
  const [savedViewport, setSavedViewport] = useState(null)
  const [viewportLoaded, setViewportLoaded] = useState(false)

  // Offline region bounds from backend config (tile coverage area)
  const [regionBounds, setRegionBounds] = useState(null)

  // Schema-derived overlay-kind allowlist stashed on the map record's
  // attrs by tool_render_map. Empty array = no filter (analyst view).
  // useMapInstance.loadMapState reads this to filter the /map/state
  // response so the editor only shows the same kinds the static product
  // render did. Editor mode reads from context; the legacy headless
  // /render route still uses the URL `?layers=` param via its own read.
  const [allowedKinds, setAllowedKinds] = useState(null)

  // product_type stashed on the map record's attrs by tool_render_map
  // (intel_agent.py builds `attrs={"product_type": ...}`). Embedded
  // mounts like the DocEditor EditMap overlay don't have a URL
  // ?product_type=, so MapDoctrinalPaint would otherwise leave `enabled`
  // false and paint no units. Falling back to attrs lets the editor
  // discover the product type the way the static render did.
  const [mapAttrsProductType, setMapAttrsProductType] = useState('')

  // Layer switcher state - needs to be declared before the fetch useEffect that uses them
  const [showLayerSwitcher, setShowLayerSwitcher] = useState(false)
  const [baseMapStyle, setBaseMapStyle] = useState(DEFAULT_BASE_MAP)
  // Every key here must map to live layers in the unified style
  // (LayerSwitcher FEATURE_LAYER_MAPPINGS) — a key without a backing
  // layer renders a toggle that does nothing.
  const [layerVisibility, setLayerVisibility] = useState({
    mgrsGrid: true,
    // Master place-label switch (both label layers). Density rides the
    // labelDetail slider below, not extra toggles.
    labels: true,
    // Contour linework (utils/contours.js). ON by default — the live
    // operations map shows the terrain readout without any product
    // context. Governs the black doctrinal treatment on
    // default/terrain/satellite and the brown sheet treatment on the
    // topo basemap. Product EDIT sessions initialize this from the
    // map's stored render spec (OperationsMap RenderSpecStash) so the
    // editor matches the export; headless product renders ignore it
    // and follow the map_show_topographic_contours URL primitive.
    contours: true,
    // Spot heights (named-peak elevation points, MapDoctrinalPaint).
    // Own toggle — a sparse point readout the analyst may want with
    // contours OFF (or vice versa). Headless renders keep them welded
    // to the contour primitive as before.
    // OFF by default: the peaks feed decodes planet tiles server-side
    // (multi-second) - it loads only when the analyst asks for it.
    spotHeights: false,
  })
  // Label detail — prominence cap over Protomaps' min_zoom rank
  // (LABEL_DETAIL_MAX = no cap = every village). Persisted per map.
  const [labelDetail, setLabelDetail] = useState(15)
  // Per-layer opacity (id -> 0..1), persisted with the map attrs.
  const [layerOpacity, setLayerOpacity] = useState({})
  const [layerPrefsLoaded, setLayerPrefsLoaded] = useState(false)

  // Weather overlay state (ported from the pytho-vite copy during the
  // cloud map unification). OpenWeatherMap forecast raster tiles served
  // through this service's own /tiles/weather proxy — the browser never
  // sees the API key. weatherLayer is an OpenWeatherMap layer code
  // (TA2 temperature, PR0 precipitation, PAS0 snow, WS10 wind,
  // CL clouds, APM pressure); weatherHour is the forecast offset in
  // hours (0, 3, 6 … 72) for the scrub slider.
  const [weatherVisible, setWeatherVisible] = useState(false)
  const [weatherLayer, setWeatherLayer] = useState('TA2')
  const [weatherHour, setWeatherHour] = useState(0)

  // PER-FACTION echelon roll-up for the LIVE analyst view: units of a
  // faction below its tier collapse into their ancestor formation at it
  // (true OOB parent-chain roll-up — rollupByEchelon in
  // tacticalGraphics.svg.js). Keyed by affiliation (Hostile / Friend /
  // Neutral / Unknown); a faction with no entry paints every unit
  // individually. The sliders live in the Tactical Overlays sidebar
  // under each faction row (OperationsMap.tsx) — the lowest slider stop
  // is the lowest echelon on the ladder, so "everything shows" needs no
  // separate off position. Distinct from the schema-driven pixel
  // clustering the product RENDER path applies (map_cluster_mil_units) —
  // this knob never affects headless renders.
  const [rollupEchelonByFaction, setRollupEchelonByFaction] = useState({})

  // Timeline scrub — paint the map AS OF a past time by re-resolving
  // every graph feature from its append-only position track
  // (map/state?as_of=). null = live (newest observation wins).
  // trackExtent mirrors meta.track_extent from the last map/state
  // load; the scrubber UI only appears when the project has a real
  // time dimension (2+ dated observations).
  const [timelineAsOf, setTimelineAsOf] = useState(null)
  const [trackExtent, setTrackExtent] = useState(null)
  // Live drag position (epoch ms) while the scrubber thumb moves —
  // resolved CLIENT-SIDE from prefetched track frames per tick (a
  // scrubber tracks the thumb, not a network round trip). null when
  // not dragging; the release commits timelineAsOf (authoritative
  // server re-resolution).
  const [timelineDragMs, setTimelineDragMs] = useState(null)

  // Symbols state (loaded lazily)
  const [symbols, setSymbols] = useState([])
  const [symbolsLoaded, setSymbolsLoaded] = useState(false)
  const [symbolsLoading, setSymbolsLoading] = useState(false)

  // Fetch config and saved map viewport from backend on mount
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await fetch(`${apiUrl}/config`)
        if (!response.ok) {
          throw new Error(`Failed to fetch config: ${response.status}`)
        }
        const data = await response.json()
        setAppConfig(data)
        // Extract offline region bounds if present
        if (data.region?.bbox) {
          setRegionBounds(data.region)
        }
        setConfigLoaded(true)
        setConfigError(null)
      } catch (err) {
        console.warn('Failed to fetch app config, using fallback:', err)
        setConfigError(err.message)
        // Keep using fallback config
        setConfigLoaded(true)
      }
    }

    const fetchSavedViewport = async () => {
      try {
        const response = await fetch(`${apiUrl}/maps/${mapId}`)
        if (response.ok) {
          const mapData = await response.json()
          // Only use saved viewport if center coordinates exist
          if (mapData.center_lng != null && mapData.center_lat != null) {
            setSavedViewport({
              center: [mapData.center_lng, mapData.center_lat],
              zoom: mapData.zoom || defaultZoom,
              bbox: mapData.bbox_west != null ? {
                west: mapData.bbox_west,
                south: mapData.bbox_south,
                east: mapData.bbox_east,
                north: mapData.bbox_north
              } : null
            })
          }
          // Load saved layer preferences from attrs
          const attrs = mapData.attrs || {}
          // Basemap selection: schema-driven primitive forwarded by
          // intel_agent.tool_render_map as the `basemap` URL param. The
          // active product schema's `map_basemap` field is the doctrinal
          // single source of truth (templates/products/<product>.py).
          // The frontend does NOT map product_type → basemap; it reads
          // the param value directly. Editor mode (no ?basemap=) falls
          // through to the analyst-saved base_map_style.
          let urlBasemap = ''
          try {
            if (typeof window !== 'undefined' && window.location) {
              const params = new URLSearchParams(window.location.search)
              urlBasemap = (params.get('basemap') || '').trim()
            }
          } catch { /* SSR / no window */ }
          if (urlBasemap) {
            setBaseMapStyle(urlBasemap)
          } else if (attrs.base_map_style) {
            setBaseMapStyle(attrs.base_map_style)
          }
          // Schema-derived overlay-kind allowlist for editor mode. The
          // tool_render_map writes schema.map_overlay_kinds to attrs at
          // render time so the embedded editor filters /map/state to
          // exactly the kinds the static product render included. No
          // dependency on URL params; works for any mount point.
          if (Array.isArray(attrs.allowed_kinds) && attrs.allowed_kinds.length > 0) {
            setAllowedKinds(new Set(attrs.allowed_kinds))
          }
          if (typeof attrs.product_type === 'string' && attrs.product_type) {
            setMapAttrsProductType(attrs.product_type)
          }
          if (attrs.layer_visibility) {
            // Merge only keys this build still defines — stale backend
            // snapshots carry toggles for retired layers, and merging
            // them back in would resurrect controls with no backing.
            setLayerVisibility(prev => {
              const merged = { ...prev }
              for (const k of Object.keys(prev)) {
                if (typeof attrs.layer_visibility[k] === 'boolean') {
                  merged[k] = attrs.layer_visibility[k]
                }
              }
              return merged
            })
          }
          if (attrs.layer_opacity) {
            setLayerOpacity(prev => ({ ...prev, ...attrs.layer_opacity }))
          }
          if (typeof attrs.label_detail === 'number') {
            setLabelDetail(attrs.label_detail)
          }
        } else if (response.status === 404 || response.status === 422) {
          // Map doesn't exist - create it with default settings
          console.log('[GeoAgentProvider] Map not found, creating with defaults')
          await createMapWithDefaults()
        }
      } catch (err) {
        console.warn('Failed to fetch saved viewport:', err)
      } finally {
        setViewportLoaded(true)
        setLayerPrefsLoaded(true)
      }
    }

    const createMapWithDefaults = async () => {
      try {
        const defaultViewport = {
          center_lng: defaultCenter[0],
          center_lat: defaultCenter[1],
          zoom: defaultZoom
        }
        const createResponse = await fetch(`${apiUrl}/maps/${mapId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(defaultViewport)
        })
        if (createResponse.ok) {
          console.log('[GeoAgentProvider] Created map with default settings')
        }
      } catch (createErr) {
        console.warn('[GeoAgentProvider] Failed to create map:', createErr)
      }
    }

    fetchConfig()
    fetchSavedViewport()
  }, [apiUrl, mapId, defaultZoom])

  // Lazy load symbols when needed
  const loadSymbols = useCallback(async (symbolSet = null) => {
    if (symbolsLoading) return symbols
    if (symbolsLoaded && !symbolSet) return symbols
    
    setSymbolsLoading(true)
    try {
      const url = symbolSet 
        ? `${apiUrl}/config/symbols?symbol_set=${symbolSet}`
        : `${apiUrl}/config/symbols`
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error(`Failed to fetch symbols: ${response.status}`)
      }
      const data = await response.json()
      const loadedSymbols = data.symbols || []
      if (!symbolSet) {
        setSymbols(loadedSymbols)
        setSymbolsLoaded(true)
      }
      setSymbolsLoading(false)
      return loadedSymbols
    } catch (err) {
      console.warn('Failed to fetch symbols:', err)
      setSymbolsLoading(false)
      return []
    }
  }, [apiUrl, symbols, symbolsLoaded, symbolsLoading])

  // Search symbols via backend API
  // Returns { results, bestMatch, count }
  const searchSymbols = useCallback(async (query, symbolSet = null, limit = 50) => {
    if (!query || query.length < 2) return { results: [], bestMatch: null, count: 0 }
    try {
      let url = `${apiUrl}/config/symbols/search?q=${encodeURIComponent(query)}&limit=${limit}`
      if (symbolSet) {
        url += `&symbol_set=${symbolSet}`
      }
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error(`Failed to search symbols: ${response.status}`)
      }
      const data = await response.json()
      return {
        results: data.results || [],
        bestMatch: data.bestMatch || null,
        count: data.count || 0
      }
    } catch (err) {
      console.warn('Failed to search symbols:', err)
      return { results: [], bestMatch: null, count: 0 }
    }
  }, [apiUrl])

  // Find best matching symbol (convenience wrapper for auto-detection)
  const findBestSymbolMatch = useCallback(async (query, symbolSet = null) => {
    const { bestMatch } = await searchSymbols(query, symbolSet, 1)
    return bestMatch
  }, [searchSymbols])

  // Custom symbol library (user-uploaded PNG/SVG, global scope)
  const [customSymbols, setCustomSymbols] = useState([])
  const [customSymbolsLoaded, setCustomSymbolsLoaded] = useState(false)
  const [selectedCustomSymbolEntityId, setSelectedCustomSymbolEntityId] = useState(null)
  const [showCustomSymbolLibrary, setShowCustomSymbolLibrary] = useState(false)
  const customSymbolMarkersRef = useRef(new Map())

  const loadCustomSymbols = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/custom-symbols`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const list = await res.json()
      setCustomSymbols(Array.isArray(list) ? list : [])
      setCustomSymbolsLoaded(true)
      return list
    } catch (err) {
      console.warn('Failed to load custom symbols:', err)
      setCustomSymbolsLoaded(true)
      return []
    }
  }, [apiUrl])

  // Stats
  const [stats, setStats] = useState({ entities: 0, overlays: 0, milUnits: 0 })

  // Activities log
  const [activities, setActivities] = useState([])

  // Mode state
  const [placementMode, setPlacementMode] = useState(false)
  const placementModeRef = useRef(false)
  
  const [overlayDrawMode, setOverlayDrawMode] = useState(false)
  const overlayDrawModeRef = useRef(false)

  // Measure mode state
  const [measureMode, setMeasureMode] = useState(false)
  const measureModeRef = useRef(false)
  const [measurePoints, setMeasurePoints] = useState([]) // [{lng, lat}, {lng, lat}]

  // Entity editing state
  const [selectedEntity, setSelectedEntity] = useState(null)
  const [showEditPanel, setShowEditPanel] = useState(false)
  const [editForm, setEditForm] = useState({ name: '', kind: '', attrs: {} })

  // Live ops-map unit-metadata panel (read-only left-click inspector).
  // Holds { unit, props, coords } for the clicked mil_unit, or null when
  // closed. Distinct from selectedEntity (the edit-mode EntityPanel) — this
  // is the read-only metadata view shown on the live operations map.
  const [selectedUnitMeta, setSelectedUnitMeta] = useState(null)

  // Live ops-map signal-report panel (KLIEGLIGHT / OSIR autofire markers).
  // Holds { artifact_id, kind, summary, mgrs, fired_at_ms, coords } for the
  // clicked marker, or null when closed. Parallel to selectedUnitMeta — the
  // SignalReportPanel reads it and offers "Open in editor".
  const [selectedSignalReport, setSelectedSignalReport] = useState(null)

  // Control-measure placard (read-only inspector for a clicked tactical
  // graphic — boundary, MSR, decision point, objective...). Holds
  // { props, coords } or null. Parallel to selectedUnitMeta.
  const [selectedOverlayMeta, setSelectedOverlayMeta] = useState(null)

  // VIEW / EDIT interaction mode for the live map. View (default):
  // clicking anything opens its placard; nothing is draggable — an
  // analyst can never accidentally move a symbol while reading the
  // map. Edit: the full click-to-edit + drag-to-move model. Edit-map
  // deep-link sessions (editEnabled) are edit mode by definition.
  const [interactionMode, setInteractionMode] = useState('view')

  // Create mode state
  const [pendingLocation, setPendingLocation] = useState(null)
  const [showCreatePanel, setShowCreatePanel] = useState(false)
  const [createForm, setCreateForm] = useState({
    name: '',
    affiliation: 'Friend',
    echelon: 'Battalion',
    status: 'Present',
    unitType: '',
    symbolSet: '10',  // Default to Land Unit
    symbolName: ''    // Display name of the selected symbol
  })

  // Overlay state
  const [selectedOverlayType, setSelectedOverlayType] = useState('phase_line')
  const [pendingOverlay, setPendingOverlay] = useState(null)
  const [showOverlayPanel, setShowOverlayPanel] = useState(false)
  const [showOverlayToolbar, setShowOverlayToolbar] = useState(false)
  const [overlayForm, setOverlayForm] = useState({
    name: '',
    designation: '',
    affiliation: 'Friend',
    echelon: '',
    obstacleEffect: '',
    remarks: ''
  })
  const [selectedOverlay, setSelectedOverlay] = useState(null)
  const [showOverlayEditPanel, setShowOverlayEditPanel] = useState(false)
  const [originalOverlayGeometry, setOriginalOverlayGeometry] = useState(null) // Store original for move operations
  
  // Geometry editing state
  const [geometryEditMode, setGeometryEditMode] = useState(false)
  const geometryEditModeRef = useRef(false)

  // Symbol picker state
  const [showSymbolPicker, setShowSymbolPicker] = useState(false)
  const [symbolPickerSearch, setSymbolPickerSearch] = useState('')
  const [symbolPickerCategory, setSymbolPickerCategory] = useState('all')
  const [symbolPickerTarget, setSymbolPickerTarget] = useState('create')
  const [symbolPickerCallback, setSymbolPickerCallback] = useState(null) // Optional callback for custom handling

  // Loading/error state
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [response, setResponse] = useState(null)
  const [query, setQuery] = useState('')

  // Chat panel state
  const [showChatPanel, setShowChatPanel] = useState(false)

  // Styled confirm dialog — browser popups (window.confirm/alert/prompt)
  // are BANNED everywhere in this UI; every confirmation goes through
  // the one ConfirmModal that reads this state. requestConfirm resolves
  // true on confirm, false on cancel/dismiss.
  const [confirmRequest, setConfirmRequest] = useState(null)
  const requestConfirm = useCallback(({ title = 'Confirm', message, confirmLabel = 'Delete' }) => {
    return new Promise((resolve) => {
      setConfirmRequest({ title, message, confirmLabel, resolve })
    })
  }, [])
  const resolveConfirm = useCallback((result) => {
    setConfirmRequest((req) => {
      req?.resolve?.(result)
      return null
    })
  }, [])
  
  // History panel state
  const [showHistoryPanel, setShowHistoryPanel] = useState(false)

  // Route planning state
  const [routePlanMode, setRoutePlanMode] = useState(false)  // is route planning active
  const routePlanModeRef = useRef(false)
  const [routeMode, setRouteMode] = useState('mixed')  // on_road, off_road, mixed
  const [routeStart, setRouteStart] = useState(null)  // {lng, lat} or null
  const [routeEnd, setRouteEnd] = useState(null)  // {lng, lat} or null
  const [routeResult, setRouteResult] = useState(null)  // full route response from backend
  const [routeLoading, setRouteLoading] = useState(false)
  const [showRoutePanel, setShowRoutePanel] = useState(false)
  const [routePreferences, setRoutePreferences] = useState(null)  // planning preference overrides

  // Route planner modal visibility (lifted so other components can reopen it)
  const [showRouteModeModal, setShowRouteModeModal] = useState(false)

  // Route failure diagnostic (shown when planner returns no path)
  const [routeDiagnostic, setRouteDiagnostic] = useState(null)

  // Route editing state
  const [routeEditMode, setRouteEditMode] = useState(false)  // user is editing a route
  const routeEditModeRef = useRef(false)
  const [routeEditAnalysis, setRouteEditAnalysis] = useState(null)  // live analysis while editing
  const [routeEditLoading, setRouteEditLoading] = useState(false)  // analysis request in flight
  const [routeEditDirty, setRouteEditDirty] = useState(false)  // user has modified the route
  const [routeIsNew, setRouteIsNew] = useState(false)  // route was just planned (not loaded from map)

  // Save layer preferences to backend when they change
  useEffect(() => {
    // Don't save until we've loaded the initial preferences (to avoid overwriting on mount)
    if (!layerPrefsLoaded) return
    // Headless render path is read-only — never write analyst prefs back to the
    // backend from a screenshot session.
    if (headless) return

    const saveLayerPrefs = async () => {
      try {
        await fetch(`${apiUrl}/maps/${mapId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            attrs: {
              base_map_style: baseMapStyle,
              layer_visibility: layerVisibility,
              layer_opacity: layerOpacity,
              label_detail: labelDetail,
            }
          })
        })
      } catch (err) {
        console.warn('Failed to save layer preferences:', err)
      }
    }

    // Debounce the save
    const timeout = setTimeout(saveLayerPrefs, 500)
    return () => clearTimeout(timeout)
  }, [apiUrl, mapId, baseMapStyle, layerVisibility, layerOpacity, labelDetail, layerPrefsLoaded, headless])

  // Persistent audit: layer/basemap preference changes (same debounce
  // shape as the save above; skipped for headless renders, which never
  // represent an analyst action).
  useEffect(() => {
    if (!layerPrefsLoaded || headless) return
    const timeout = setTimeout(() => {
      logAnalystEvent({
        event_type: 'map.layer_prefs_changed',
        user_id: userId ?? null,
        map_id: mapId ? String(mapId) : null,
        surface: 'layer_switcher',
        detail: {
          base_map_style: baseMapStyle,
          layer_visibility: layerVisibility,
          label_detail: labelDetail,
        },
      })
    }, 500)
    return () => clearTimeout(timeout)
  }, [mapId, userId, baseMapStyle, layerVisibility, labelDetail, layerPrefsLoaded, headless])

  // Persistent audit: weather overlay + echelon roll-up changes. The
  // forecast HOUR scrub is deliberately not audited (per-tick noise);
  // layer/visibility flips and roll-up tier changes are the actions.
  useEffect(() => {
    if (!layerPrefsLoaded || headless) return
    logAnalystEvent({
      event_type: 'map.weather_changed',
      user_id: userId ?? null,
      map_id: mapId ? String(mapId) : null,
      surface: 'layer_switcher',
      detail: { visible: weatherVisible, layer: weatherLayer },
    })
  }, [weatherVisible, weatherLayer])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!layerPrefsLoaded || headless) return
    logAnalystEvent({
      event_type: 'map.rollup_changed',
      user_id: userId ?? null,
      map_id: mapId ? String(mapId) : null,
      surface: 'sidebar',
      detail: {
        tiers: Object.keys(rollupEchelonByFaction).length
          ? rollupEchelonByFaction
          : 'off',
      },
    })
  }, [rollupEchelonByFaction])  // eslint-disable-line react-hooks/exhaustive-deps
  
  // Pending chat operation editing - for editing operations before confirming
  const [pendingChatOp, setPendingChatOp] = useState(null) // { index, op, onSave }
  
  // Map refresh trigger - increment to trigger a map data reload
  const [mapRefreshTrigger, setMapRefreshTrigger] = useState(0)
  const triggerMapRefresh = useCallback(() => {
    setMapRefreshTrigger(prev => prev + 1)
  }, [])

  // Visibility model (defined in utils/featureVisibility.js — the ONE
  // home for token grammar + matching; the Tactical Overlays panel and
  // the loadMapState filter both import from it):
  //
  //   enabledLayers — WHICH product claim-sets paint. Entries are
  //   source tokens of product pushes (SITEMP:<coa_id>, "Threat
  //   Overlay", …) plus the polled report-pin feeds (live_klieglight /
  //   live_osir, read by GeoAgentMap's signal-report effect). Base-map
  //   content (live_oob feed, analyst-authored `manual`, scenario /
  //   OPORD baseline) is NOT a layer — it always passes the gate;
  //   provenance is audit metadata, never a view axis.
  //
  //   hiddenTypes — the LEGEND. Global, source-agnostic type tokens
  //   (kind:phase_line, affiliation:Hostile, Hostile:category:…):
  //   hiding a type hides it no matter which pipe produced the
  //   feature. Per-product-layer SAVED copies of this legend live on
  //   the map record (attrs.visibility_collections, managed by the
  //   Tactical Overlays panel) — activating a layer restores its
  //   collection; edits autosave to the active collection.
  //
  // Each entry in enabledLayers is a source token matching
  // `attrs.source` on overlays + entities returned
  // by /maps/state. **Only the OperationsMap page** (master-map sidebar
  // toggle UI) populates this set. Every other consumer of GeoAgent —
  // per-product render maps (SITEMP/MCOO/Threat Overlay/…), the
  // headless screenshot route, DocEditor map embeds — runs against
  // their OWN dedicated map_uuid which contains ONLY that product's
  // overlays. There is no aggregation on a per-product map → there is
  // nothing to filter → the filter must be off.
  //
  // Default = null = no filter; useMapInstance._filterBySource is a
  // no-op when enabledLayers is null. OperationsMap.tsx explicitly
  // seeds the Set on mount (via setEnabledLayers) once it knows which
  // toggles are present in its sidebar.
  //
  // Past regression: defaulting this to new Set(['live_oob']) here
  // (commit 74b5ef0) silently filtered every per-product render — the
  // SITEMP / Threat Overlay headless renders saw only mil_units pass
  // through, dropped scenario_terrain (range fans, EAs, AAs, key
  // terrain) + writer overlays (axes, NAIs, threat objectives), and
  // shipped JPGs with units floating on a blank basemap. The filter
  // belongs on the master map's sidebar UI, not in the shared hook.
  const [enabledLayers, setEnabledLayers] = useState(null)

  // Per-layer sub-toggles. Token shape: "<source>:<dimension>:<value>"
  // where dimension is one of kind | echelon | category | range_fan_class.
  // A token in this set means the matching sub-feature is HIDDEN even
  // when its parent source is in enabledLayers. Default = empty set
  // (no sub-features hidden). Same null-default convention as
  // enabledLayers: only the OperationsMap sidebar mounts with toggles
  // populated; per-product render maps leave the filter off entirely.
  //
  // The matching predicate lives in useMapInstance._filterBySource. Each
  // feature carries enough metadata on properties (kind, echelon,
  // category, subkind) to evaluate the relevant tokens.
  const [hiddenTypes, setHiddenTypes] = useState(() => new Set())

  // Unit designation labels are per-faction legend state now:
  // "unit_names:<aff>" tokens in hiddenTypes (utils/featureVisibility)
  // hide a faction's labels without hiding its symbols. No separate
  // boolean — the tokens persist in visibility collections like every
  // other legend entry.

  // Realtime WebSocket to /api/v1/ws — opens once on mount per mapId. Any
  // sync_complete / ingest_complete / op-kind frame bumps mapRefreshTrigger
  // so GeoAgentMap's existing refresh effect (which calls loadMapState)
  // pulls the latest overlay/entity snapshot. Skipped in headless mode —
  // the screenshot renderer is read-only and has no business holding a
  // socket open.
  const onRealtimeSyncComplete = useCallback(() => {
    setMapRefreshTrigger(prev => prev + 1)
  }, [])
  useGeoAgentRealtime({
    mapId,
    enabled: !headless,
    onSyncComplete: onRealtimeSyncComplete,
  })

  // Add activity log entry
  const addActivity = useCallback((message, type = 'info') => {
    setActivities(prev => [{
      message,
      type,
      time: new Date().toLocaleTimeString()
    }, ...prev.slice(0, 9)])
  }, [])

  // Keep refs in sync with state
  React.useEffect(() => {
    overlayDrawModeRef.current = overlayDrawMode
  }, [overlayDrawMode])

  React.useEffect(() => {
    placementModeRef.current = placementMode
  }, [placementMode])

  React.useEffect(() => {
    measureModeRef.current = measureMode
  }, [measureMode])

  React.useEffect(() => {
    geometryEditModeRef.current = geometryEditMode
  }, [geometryEditMode])

  React.useEffect(() => {
    routePlanModeRef.current = routePlanMode
  }, [routePlanMode])

  React.useEffect(() => {
    routeEditModeRef.current = routeEditMode
  }, [routeEditMode])

  const value = {
    // Configuration
    apiUrl,
    mapId,
    userId,
    defaultCenter,
    defaultZoom,
    headless,
    productType: productType || mapAttrsProductType,

    // Schema-derived overlay-kind allowlist (set from map record attrs)
    allowedKinds,

    // App config from backend
    appConfig,
    configLoaded,
    configError,

    // Saved viewport from backend (for restoring on refresh)
    savedViewport,
    viewportLoaded,

    // Offline region bounds (tile coverage area)
    regionBounds,

    // Symbols from backend
    symbols,
    symbolsLoaded,
    symbolsLoading,
    loadSymbols,
    searchSymbols,
    findBestSymbolMatch,

    // Map refs
    mapRef,
    mapContainerRef,
    drawRef,
    milMarkersRef,
    tacticalGraphicMarkersRef,

    // Map state
    mapLoaded,
    setMapLoaded,
    milSymRendererReady,
    setMilSymRendererReady,
    coordinates,
    setCoordinates,

    // Stats
    stats,
    setStats,

    // Activities
    activities,
    addActivity,

    // Mode state
    placementMode,
    setPlacementMode,
    placementModeRef,
    overlayDrawMode,
    setOverlayDrawMode,
    overlayDrawModeRef,
    
    // Measure mode
    measureMode,
    setMeasureMode,
    measureModeRef,
    measurePoints,
    setMeasurePoints,

    // Entity editing
    selectedEntity,
    setSelectedEntity,
    showEditPanel,
    setShowEditPanel,
    editForm,
    setEditForm,

    // Live ops-map unit-metadata panel (left-click inspector)
    selectedUnitMeta,
    setSelectedUnitMeta,

    // Live ops-map signal-report panel (KLIEGLIGHT / OSIR markers)
    selectedSignalReport,
    setSelectedSignalReport,

    // Control-measure placard (read-only inspector)
    selectedOverlayMeta,
    setSelectedOverlayMeta,

    // View / Edit interaction mode (live map)
    interactionMode,
    setInteractionMode,

    // Create mode
    pendingLocation,
    setPendingLocation,
    showCreatePanel,
    setShowCreatePanel,
    createForm,
    setCreateForm,

    // Overlay state
    selectedOverlayType,
    setSelectedOverlayType,
    pendingOverlay,
    setPendingOverlay,
    showOverlayPanel,
    setShowOverlayPanel,
    showOverlayToolbar,
    setShowOverlayToolbar,
    overlayForm,
    setOverlayForm,
    selectedOverlay,
    setSelectedOverlay,
    showOverlayEditPanel,
    setShowOverlayEditPanel,
    originalOverlayGeometry,
    setOriginalOverlayGeometry,
    
    // Geometry editing
    geometryEditMode,
    setGeometryEditMode,
    geometryEditModeRef,

    // Symbol picker
    showSymbolPicker,
    setShowSymbolPicker,
    symbolPickerSearch,
    setSymbolPickerSearch,
    symbolPickerCategory,
    setSymbolPickerCategory,
    symbolPickerTarget,
    setSymbolPickerTarget,
    symbolPickerCallback,
    setSymbolPickerCallback,

    // Loading/error
    loading,
    setLoading,
    error,
    setError,
    response,
    setResponse,
    query,
    setQuery,

    // Chat panel
    showChatPanel,
    setShowChatPanel,
    confirmRequest,
    requestConfirm,
    resolveConfirm,
    
    // History panel
    showHistoryPanel,
    setShowHistoryPanel,
    
    // Layer switcher
    showLayerSwitcher,
    setShowLayerSwitcher,
    baseMapStyle,
    setBaseMapStyle,
    layerVisibility,
    setLayerVisibility,
    labelDetail,
    setLabelDetail,
    layerOpacity,
    setLayerOpacity,

    // Weather overlay (OpenWeatherMap forecast tiles via /tiles/weather)
    weatherVisible,
    setWeatherVisible,
    weatherLayer,
    setWeatherLayer,
    weatherHour,
    setWeatherHour,

    // Per-faction echelon roll-up (live view only)
    rollupEchelonByFaction,
    setRollupEchelonByFaction,

    // Timeline scrub (live view only; null = live)
    timelineAsOf,
    setTimelineAsOf,
    trackExtent,
    setTrackExtent,
    timelineDragMs,
    setTimelineDragMs,

    // Pending chat operation editing
    pendingChatOp,
    setPendingChatOp,
    
    // Map refresh trigger
    mapRefreshTrigger,
    triggerMapRefresh,

    // Operations-map overlay-source visibility (sidebar toggles) and
    // edit-mode gate (only the DocEditor edit-map deep link enables it).
    enabledLayers,
    setEnabledLayers,
    hiddenTypes,
    setHiddenTypes,
    // Operations-map "Unit Names" visibility sub-toggle (gates mil-unit
    // designation labels; read + stashed on the map by MapDoctrinalPaint).
    editEnabled,
    shellGraphViewerUrl,

    // Route planning
    routePlanMode,
    setRoutePlanMode,
    routePlanModeRef,
    routeMode,
    setRouteMode,
    routeStart,
    setRouteStart,
    routeEnd,
    setRouteEnd,
    routeResult,
    setRouteResult,
    routeLoading,
    setRouteLoading,
    showRoutePanel,
    setShowRoutePanel,
    routePreferences,
    setRoutePreferences,

    // Route planner modal
    showRouteModeModal,
    setShowRouteModeModal,

    // Route failure diagnostic
    routeDiagnostic,
    setRouteDiagnostic,

    // Route editing
    routeEditMode,
    setRouteEditMode,
    routeEditModeRef,
    routeEditAnalysis,
    setRouteEditAnalysis,
    routeEditLoading,
    setRouteEditLoading,
    routeEditDirty,
    setRouteEditDirty,
    routeIsNew,
    setRouteIsNew,

    // Custom symbols (user-uploaded PNG/SVG)
    customSymbols,
    customSymbolsLoaded,
    loadCustomSymbols,
    setCustomSymbols,
    customSymbolMarkersRef,
    selectedCustomSymbolEntityId,
    setSelectedCustomSymbolEntityId,
    showCustomSymbolLibrary,
    setShowCustomSymbolLibrary,
  }

  return (
    <GeoAgentContext.Provider value={value}>
      {children}
    </GeoAgentContext.Provider>
  )
}

/**
 * Hook to access the GeoAgent context
 * @returns {Object} The GeoAgent context value
 */
export function useGeoAgent() {
  const context = useContext(GeoAgentContext)
  if (!context) {
    throw new Error('useGeoAgent must be used within a GeoAgentProvider')
  }
  return context
}

export { GeoAgentContext }
