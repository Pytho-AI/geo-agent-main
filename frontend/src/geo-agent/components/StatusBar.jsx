/**
 * Status bar — bottom-left HUD showing MGRS + lat/lon under the cursor and
 * the active base map's acquisition date. Acquisition dates are hard-coded
 * on each base-map entry in mapStyles.js (S2 picks have YYYYMMDD in their
 * STAC IDs; Maa-amet is the 2024 mosaic; the OMT-derived bases are vendor-
 * sourced and carry vendor strings instead of dates).
 */

import React, { useMemo } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { latLngToMGRS } from '../utils/mgrsGrid'
import { BASE_MAP_SOURCES } from '../utils/mapStyles'

/**
 * StatusBar component
 */
export function StatusBar() {
  const { coordinates, loading, mapLoaded, baseMapStyle } = useGeoAgent()

  const mgrs = useMemo(() => {
    const lat = parseFloat(coordinates.lat)
    const lng = parseFloat(coordinates.lng)
    if (isNaN(lat) || isNaN(lng)) return ''
    return latLngToMGRS(lat, lng, 4)
  }, [coordinates.lat, coordinates.lng])

  const baseMeta = baseMapStyle ? BASE_MAP_SOURCES[baseMapStyle] : null
  const acquired = baseMeta?.acquired || ''
  const baseLabel = baseMeta?.name || baseMapStyle || ''

  return (
    <div className="status-bar">
      {loading && <span className="loading" />}
      {mgrs} | {coordinates.lng}, {coordinates.lat}
      {baseLabel && acquired && (
        <> | {baseLabel} · {acquired}</>
      )}
      {!mapLoaded && ' | Loading map...'}
    </div>
  )
}
