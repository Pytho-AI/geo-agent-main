/**
 * Hook for route planning — handles the two-click workflow
 * (set start, set end, call planner, draw result).
 */

import { useCallback, useRef, useEffect } from 'react'
import maplibregl from 'maplibre-gl'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'
import {
  ROUTE_LINE_ID,
  ROUTE_COLOR,
  ROUTE_LINE_PAINT,
  ROUTE_LINE_LAYOUT,
  ROUTE_START_MARKER_COLOR,
  ROUTE_END_MARKER_COLOR,
} from '../utils/routeConstants'

/**
 * @returns {{ drawRoute: (path: Object) => void, replanRoute: (start, end) => Promise<void> }}
 */
export function useRoutePlanning() {
  const {
    mapRef,
    mapLoaded,
    apiUrl,
    mapId,
    userId,
    addActivity,
    routePlanMode,
    routePlanModeRef,
    routeMode,
    routeStart,
    setRouteStart,
    routeEnd,
    setRouteEnd,
    setRoutePlanMode,
    setRouteResult,
    setRouteLoading,
    setShowRoutePanel,
    setRouteEditMode,
    routePreferences,
    setRouteDiagnostic,
    setRouteIsNew,
    triggerMapRefresh,
  } = useGeoAgent()

  // userId rides mutating calls for created_by attribution.
  const api = createApiClient(apiUrl, userId)
  const markersRef = useRef([])

  // Max weather segment layers for the transient active-route draw
  const MAX_WEATHER_SEGS = 20
  const WEATHER_SEG_PREFIX = 'route-weather-seg-'

  // Remove weather segment layers from the map
  const cleanupWeatherSegLayers = useCallback((map) => {
    for (let i = 0; i < MAX_WEATHER_SEGS; i++) {
      const id = `${WEATHER_SEG_PREFIX}${i}`
      if (map.getLayer(id)) map.removeLayer(id)
      if (map.getSource(id)) map.removeSource(id)
    }
  }, [])

  // --- Draw a route line on the map, colored by weather segments when
  // available (ported from the pytho-vite copy) ---
  const drawRoute = useCallback((path) => {
    const map = mapRef.current
    if (!map || !path?.geom?.coordinates?.length) return

    if (map.getLayer(ROUTE_LINE_ID)) map.removeLayer(ROUTE_LINE_ID)
    if (map.getSource(ROUTE_LINE_ID)) map.removeSource(ROUTE_LINE_ID)
    cleanupWeatherSegLayers(map)

    const coords = path.geom.coordinates
    const segments = path.analysis?.weather?.segments

    if (segments && segments.length > 0) {
      // Build cumulative distance (miles) to map segment ranges to coordinate indices
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

      segments.forEach((seg, si) => {
        if (si >= MAX_WEATHER_SEGS) return
        let startIdx = 0
        let endIdx = coords.length - 1
        for (let i = 0; i < cumDist.length; i++) {
          if (cumDist[i] >= seg.start_mi) { startIdx = Math.max(0, i - 1); break }
        }
        for (let i = cumDist.length - 1; i >= 0; i--) {
          if (cumDist[i] <= seg.end_mi) { endIdx = Math.min(coords.length - 1, i + 1); break }
        }
        if (endIdx <= startIdx) endIdx = Math.min(startIdx + 1, coords.length - 1)
        const segCoords = coords.slice(startIdx, endIdx + 1)
        if (segCoords.length < 2) return

        const id = `${WEATHER_SEG_PREFIX}${si}`
        map.addSource(id, {
          type: 'geojson',
          data: { type: 'Feature', geometry: { type: 'LineString', coordinates: segCoords } },
        })
        map.addLayer({
          id, type: 'line', source: id,
          paint: { 'line-color': seg.color || ROUTE_COLOR, 'line-width': 5, 'line-opacity': 0.85 },
          layout: { 'line-cap': 'round', 'line-join': 'round' },
        })
      })
    } else {
      // No weather data — solid blue line
      map.addSource(ROUTE_LINE_ID, {
        type: 'geojson',
        data: { type: 'Feature', geometry: path.geom },
      })
      map.addLayer({
        id: ROUTE_LINE_ID,
        type: 'line',
        source: ROUTE_LINE_ID,
        paint: { ...ROUTE_LINE_PAINT },
        layout: { ...ROUTE_LINE_LAYOUT },
      })
    }
  }, [mapRef, cleanupWeatherSegLayers])

  // --- Core planning logic (shared by click flow and retry) ---
  // Optional overrides let callers pass fresh mode/prefs that haven't
  // hit React state yet (avoids stale-closure on retry).
  const planWithPoints = useCallback(async (start, end, { mode, prefs } = {}) => {
    const useMode = mode || routeMode
    const usePrefs = prefs !== undefined ? prefs : routePreferences

    setRouteLoading(true)
    addActivity(`Planning ${useMode.replace('_', ' ')} route...`, 'info')

    try {
      const result = await api.planRoute(mapId, {
        name: 'Route Plan',
        start_geom: { type: 'Point', coordinates: [start.lng, start.lat] },
        end_geom: { type: 'Point', coordinates: [end.lng, end.lat] },
        route_mode: useMode,
        attrs: usePrefs || {},
      })
      setRouteResult(result)
      setShowRoutePanel(true)
      setRouteEditMode(true)
      setRouteIsNew(true)
      addActivity('Route planned', 'success')
      drawRoute(result.paths?.[0])
      // Saved-route painter picks the new route up on the next
      // loadMapState pass.
      triggerMapRefresh()
    } catch (err) {
      addActivity(`Route planning failed: ${err.message}`, 'error')
      if (err.diagnostic) {
        setRouteDiagnostic({ message: err.message, diagnostic: err.diagnostic })
      } else {
        setRouteDiagnostic({ message: err.message || 'Route planning failed. Try different points or switch route mode.', diagnostic: null })
      }
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
    } finally {
      setRouteLoading(false)
    }
  }, [routeMode, routePreferences, mapId, api, addActivity,
      drawRoute, setRouteLoading, setRouteResult, setShowRoutePanel,
      setRouteEditMode, setRouteDiagnostic])

  // --- Retry with same start/end (called after user adjusts preferences) ---
  // mode + prefs are passed directly from onConfirm so they're always fresh.
  const replanRoute = useCallback(async (start, end, mode, prefs) => {
    setRouteStart(start)
    setRouteEnd(end)
    setRoutePlanMode(true)
    // Place markers for the preserved points
    if (mapRef.current) {
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
      markersRef.current.push(
        new maplibregl.Marker({ color: ROUTE_START_MARKER_COLOR })
          .setLngLat([start.lng, start.lat])
          .addTo(mapRef.current)
      )
      markersRef.current.push(
        new maplibregl.Marker({ color: ROUTE_END_MARKER_COLOR })
          .setLngLat([end.lng, end.lat])
          .addTo(mapRef.current)
      )
    }
    await planWithPoints(start, end, { mode, prefs })
  }, [planWithPoints, setRouteStart, setRouteEnd, setRoutePlanMode, mapRef])

  // --- Handle map click to set start / end ---
  const handleRouteClick = useCallback(async (e) => {
    if (!routePlanModeRef.current) return
    const { lng, lat } = e.lngLat

    if (!routeStart) {
      setRouteStart({ lng, lat })
      addActivity(`Route start set at ${lat.toFixed(4)}, ${lng.toFixed(4)}`, 'info')
      if (mapRef.current) {
        markersRef.current.push(
          new maplibregl.Marker({ color: ROUTE_START_MARKER_COLOR })
            .setLngLat([lng, lat])
            .addTo(mapRef.current)
        )
      }
      return
    }

    if (!routeEnd) {
      setRouteEnd({ lng, lat })
      addActivity(`Route end set at ${lat.toFixed(4)}, ${lng.toFixed(4)}`, 'info')
      if (mapRef.current) {
        markersRef.current.push(
          new maplibregl.Marker({ color: ROUTE_END_MARKER_COLOR })
            .setLngLat([lng, lat])
            .addTo(mapRef.current)
        )
      }
      await planWithPoints(routeStart, { lng, lat })
    }
  }, [routeStart, routeEnd, routePlanModeRef, mapRef, addActivity,
      setRouteStart, setRouteEnd, planWithPoints])

  // Register / unregister click handler
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    map.on('click', handleRouteClick)
    return () => map.off('click', handleRouteClick)
  }, [mapLoaded, handleRouteClick, mapRef])

  // Cleanup markers when route plan mode is exited
  useEffect(() => {
    if (!routePlanMode) {
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
    }
  }, [routePlanMode])

  return { drawRoute, replanRoute }
}
