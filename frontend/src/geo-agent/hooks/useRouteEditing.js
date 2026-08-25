/**
 * Hook for route editing via draggable control-point markers.
 *
 * UX: The original route stays green. An amber preview line shows the
 * edited shape on top. Save replaces the green line; Cancel removes the amber.
 * No other routes are touched at any point.
 */

import { useCallback, useRef, useEffect } from 'react'
import maplibregl from 'maplibre-gl'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'
import {
  ROUTE_EDIT_PREVIEW_ID,
  ROUTE_EDIT_PREVIEW_COLOR,
  CP_MIN,
  CP_MAX,
  CP_DIVISOR,
  EDIT_DEBOUNCE_MS,
} from '../utils/routeConstants'

export function useRouteEditing() {
  const {
    mapRef,
    mapLoaded,
    apiUrl,
    mapId,
    routeResult,
    routeEditMode,
    routeEditModeRef,
    setRouteEditAnalysis,
    setRouteEditLoading,
    setRouteEditDirty,
  } = useGeoAgent()

  const api = createApiClient(apiUrl)

  const markersRef = useRef([])
  const origCoordsRef = useRef([])
  const controlPtsRef = useRef([])
  const timerRef = useRef(null)

  // --- Debounced backend analysis ---
  const requestAnalysis = useCallback((coordinates) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      if (!routeEditModeRef.current || !coordinates || coordinates.length < 2) return
      setRouteEditLoading(true)
      try {
        const result = await api.analyzeRouteEdit(mapId, coordinates)
        if (routeEditModeRef.current) setRouteEditAnalysis(result)
      } catch (err) {
        console.warn('Route edit analysis failed:', err)
      } finally {
        setRouteEditLoading(false)
      }
    }, EDIT_DEBOUNCE_MS)
  }, [api, mapId, routeEditModeRef, setRouteEditAnalysis, setRouteEditLoading])

  // --- Rebuild coords from control-point deltas ---
  const rebuildRouteCoords = useCallback(() => {
    const original = origCoordsRef.current
    const cps = controlPtsRef.current
    if (!original.length || cps.length < 2) return original

    const newCoords = original.map(c => [...c])
    for (let k = 0; k < cps.length - 1; k++) {
      const cpA = cps[k]
      const cpB = cps[k + 1]
      const idxA = cpA.origIdx
      const idxB = cpB.origIdx
      const deltaA = [cpA.coord[0] - original[idxA][0], cpA.coord[1] - original[idxA][1]]
      const deltaB = [cpB.coord[0] - original[idxB][0], cpB.coord[1] - original[idxB][1]]

      for (let j = idxA; j <= idxB; j++) {
        const t = idxB > idxA ? (j - idxA) / (idxB - idxA) : 1
        newCoords[j] = [
          original[j][0] + deltaA[0] * (1 - t) + deltaB[0] * t,
          original[j][1] + deltaA[1] * (1 - t) + deltaB[1] * t,
        ]
      }
    }
    // Always apply the last control point directly (endpoint never missed)
    const lastCp = cps[cps.length - 1]
    newCoords[lastCp.origIdx] = [...lastCp.coord]
    // Always apply the first control point directly
    newCoords[cps[0].origIdx] = [...cps[0].coord]
    return newCoords
  }, [])

  // --- Update amber preview line ---
  const updatePreviewLine = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    const newCoords = rebuildRouteCoords()
    if (newCoords.length < 2) return
    const src = map.getSource(ROUTE_EDIT_PREVIEW_ID)
    if (src) {
      src.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: newCoords } })
    }
  }, [rebuildRouteCoords, mapRef])

  // --- Create a draggable handle marker ---
  const createHandle = useCallback((map, cp, isStart, isEnd) => {
    const el = document.createElement('div')
    el.className = 'route-edit-handle' + (isStart ? ' start' : '') + (isEnd ? ' end' : '')

    const marker = new maplibregl.Marker({ element: el, draggable: true })
      .setLngLat(cp.coord)
      .addTo(map)

    marker.on('drag', () => {
      const { lng, lat } = marker.getLngLat()
      cp.coord = [lng, lat]
      updatePreviewLine()
      setRouteEditDirty(true)
      setRouteEditAnalysis(null)
    })

    marker.on('dragend', () => {
      requestAnalysis(rebuildRouteCoords())
    })

    return marker
  }, [updatePreviewLine, rebuildRouteCoords, requestAnalysis, setRouteEditDirty, setRouteEditAnalysis])

  // --- Enter / exit edit mode ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return

    if (routeEditMode) {
      const path = routeResult?.paths?.[0]
      const coords = path?.geom?.coordinates
      if (!coords || coords.length < 2) return

      // Snapshot original coords
      origCoordsRef.current = coords.map(c => [...c])

      // Build cumulative distance for geographic sampling
      const toRad = (d) => d * Math.PI / 180
      const cumDist = [0]
      for (let i = 1; i < coords.length; i++) {
        const [lon1, lat1] = coords[i - 1]
        const [lon2, lat2] = coords[i]
        const dLat = toRad(lat2 - lat1)
        const dLon = toRad(lon2 - lon1)
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
        cumDist.push(cumDist[i - 1] + 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)))
      }
      const totalDist = cumDist[cumDist.length - 1]

      // Sample control points at equal geographic distance, always including start + end
      const numCp = Math.min(Math.max(CP_MIN, Math.ceil(coords.length / CP_DIVISOR)), CP_MAX)
      const controlPoints = [{ origIdx: 0, coord: [...coords[0]] }]
      let cursor = 1
      for (let i = 1; i < numCp - 1; i++) {
        const target = (i / (numCp - 1)) * totalDist
        while (cursor < coords.length - 1 && cumDist[cursor] < target) cursor++
        controlPoints.push({ origIdx: cursor, coord: [...coords[cursor]] })
      }
      controlPoints.push({ origIdx: coords.length - 1, coord: [...coords[coords.length - 1]] })
      controlPtsRef.current = controlPoints

      // DO NOT touch the original green route layer — just add the amber preview on top
      if (map.getLayer(ROUTE_EDIT_PREVIEW_ID)) map.removeLayer(ROUTE_EDIT_PREVIEW_ID)
      if (map.getSource(ROUTE_EDIT_PREVIEW_ID)) map.removeSource(ROUTE_EDIT_PREVIEW_ID)

      map.addSource(ROUTE_EDIT_PREVIEW_ID, {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'LineString', coordinates: coords } },
      })
      map.addLayer({
        id: ROUTE_EDIT_PREVIEW_ID, type: 'line', source: ROUTE_EDIT_PREVIEW_ID,
        paint: { 'line-color': ROUTE_EDIT_PREVIEW_COLOR, 'line-width': 5, 'line-opacity': 0.9 },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      })

      // Create draggable handle markers
      markersRef.current = controlPoints.map((cp, i) =>
        createHandle(map, cp, i === 0, i === controlPoints.length - 1)
      )

      // Click on preview line to insert a new control point
      const handlePreviewClick = (e) => {
        if (!routeEditModeRef.current) return
        e.preventDefault?.()
        const clickLng = e.lngLat.lng
        const clickLat = e.lngLat.lat
        const original = origCoordsRef.current
        const cps = controlPtsRef.current

        let bestIdx = 0, bestDist = Infinity
        for (let i = 0; i < original.length; i++) {
          const d = (original[i][0] - clickLng) ** 2 + (original[i][1] - clickLat) ** 2
          if (d < bestDist) { bestDist = d; bestIdx = i }
        }
        let insertAt = cps.length
        for (let k = 0; k < cps.length; k++) {
          if (cps[k].origIdx > bestIdx) { insertAt = k; break }
        }
        if (cps.some(cp => cp.origIdx === bestIdx)) return

        const newCp = { origIdx: bestIdx, coord: [clickLng, clickLat] }
        cps.splice(insertAt, 0, newCp)
        markersRef.current.splice(insertAt, 0, createHandle(map, newCp, false, false))
      }

      map.on('click', ROUTE_EDIT_PREVIEW_ID, handlePreviewClick)

      return () => {
        if (map.getLayer(ROUTE_EDIT_PREVIEW_ID)) {
          map.off('click', ROUTE_EDIT_PREVIEW_ID, handlePreviewClick)
        }
      }
    } else {
      // --- Exit edit mode: just remove preview + handles ---
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
      origCoordsRef.current = []
      controlPtsRef.current = []

      if (map.getLayer(ROUTE_EDIT_PREVIEW_ID)) map.removeLayer(ROUTE_EDIT_PREVIEW_ID)
      if (map.getSource(ROUTE_EDIT_PREVIEW_ID)) map.removeSource(ROUTE_EDIT_PREVIEW_ID)

      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [routeEditMode, mapLoaded]) // eslint-disable-line react-hooks/exhaustive-deps

  const getRouteEditCoords = useCallback(() => rebuildRouteCoords(), [rebuildRouteCoords])

  return { getRouteEditCoords }
}
