/**
 * MGRS Grid Generation Utility
 * Generates Military Grid Reference System grid lines and labels for MapLibre
 */

// UTM zone boundaries
const UTM_ZONE_WIDTH = 6

// Latitude band boundaries
const LATITUDE_BAND_HEIGHT = 8

// Latitude band letters (C-X, excluding I and O)
const LATITUDE_BANDS = 'CDEFGHJKLMNPQRSTUVWX'

// 100km grid square column letters (A-Z excluding I and O)
const GRID_COLS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'

// 100km grid square row letters
const GRID_ROWS = 'ABCDEFGHJKLMNPQRSTUV'

/**
 * Convert degrees to radians
 */
function toRadians(deg) {
  return deg * Math.PI / 180
}

/**
 * Get UTM zone number for a longitude
 */
function getUTMZone(lng) {
  return Math.floor((lng + 180) / 6) + 1
}

/**
 * Get latitude band letter for a latitude
 */
function getLatitudeBand(lat) {
  if (lat < -80 || lat > 84) return 'Z'
  const bandIndex = Math.floor((lat + 80) / 8)
  return LATITUDE_BANDS[Math.min(bandIndex, LATITUDE_BANDS.length - 1)]
}

/**
 * Convert lat/lng to UTM coordinates
 */
function latLngToUTM(lat, lng) {
  const zone = getUTMZone(lng)
  
  // WGS84 ellipsoid constants
  const a = 6378137 // semi-major axis
  const f = 1 / 298.257223563 // flattening
  const k0 = 0.9996 // scale factor
  
  const e = Math.sqrt(2 * f - f * f)
  const e2 = e * e
  const ep2 = e2 / (1 - e2)
  
  const latRad = toRadians(lat)
  const lngRad = toRadians(lng)
  
  const lngOrigin = (zone - 1) * 6 - 180 + 3
  const lngOriginRad = toRadians(lngOrigin)
  
  const N = a / Math.sqrt(1 - e2 * Math.sin(latRad) * Math.sin(latRad))
  const T = Math.tan(latRad) * Math.tan(latRad)
  const C = ep2 * Math.cos(latRad) * Math.cos(latRad)
  const A = Math.cos(latRad) * (lngRad - lngOriginRad)
  
  const M = a * (
    (1 - e2/4 - 3*e2*e2/64 - 5*e2*e2*e2/256) * latRad -
    (3*e2/8 + 3*e2*e2/32 + 45*e2*e2*e2/1024) * Math.sin(2*latRad) +
    (15*e2*e2/256 + 45*e2*e2*e2/1024) * Math.sin(4*latRad) -
    (35*e2*e2*e2/3072) * Math.sin(6*latRad)
  )
  
  const easting = k0 * N * (
    A + (1-T+C) * A*A*A/6 +
    (5-18*T+T*T+72*C-58*ep2) * A*A*A*A*A/120
  ) + 500000
  
  let northing = k0 * (
    M + N * Math.tan(latRad) * (
      A*A/2 + (5-T+9*C+4*C*C) * A*A*A*A/24 +
      (61-58*T+T*T+600*C-330*ep2) * A*A*A*A*A*A/720
    )
  )
  
  // Adjust for southern hemisphere
  if (lat < 0) {
    northing += 10000000
  }
  
  return { zone, easting, northing, band: getLatitudeBand(lat) }
}

/**
 * Get the 100km square identifier letters
 */
function get100kId(zone, easting, northing) {
  // Column letter set depends on zone number (cycles every 3 zones)
  const setNumber = ((zone - 1) % 3)
  const colOffset = setNumber * 8
  
  // Get column letter (based on easting)
  const col100k = Math.floor(easting / 100000)
  const colIndex = (colOffset + col100k - 1) % 24
  const colLetter = GRID_COLS[colIndex]
  
  // Row letter set depends on odd/even zone
  const rowOffset = (zone % 2 === 0) ? 5 : 0
  
  // Get row letter (based on northing)
  const row100k = Math.floor(northing / 100000) % 20
  const rowIndex = (rowOffset + row100k) % 20
  const rowLetter = GRID_ROWS[rowIndex]
  
  return colLetter + rowLetter
}

/**
 * Convert latitude/longitude to MGRS string
 * @param {number} lat - Latitude in degrees
 * @param {number} lng - Longitude in degrees
 * @param {number} precision - Precision level (1-5, default 5 for 1m)
 * @returns {string} MGRS coordinate string
 */
export function latLngToMGRS(lat, lng, precision = 5) {
  // Handle polar regions (UPS)
  if (lat < -80 || lat > 84) {
    return 'Outside MGRS coverage'
  }
  
  const utm = latLngToUTM(lat, lng)
  const gzd = `${utm.zone}${utm.band}`
  const sqId = get100kId(utm.zone, utm.easting, utm.northing)
  
  // Get the numeric portion within the 100km square
  const easting100k = utm.easting % 100000
  const northing100k = utm.northing % 100000
  
  // Format based on precision
  const divisor = Math.pow(10, 5 - precision)
  const eastStr = Math.floor(easting100k / divisor).toString().padStart(precision, '0')
  const northStr = Math.floor(northing100k / divisor).toString().padStart(precision, '0')
  
  return `${gzd} ${sqId} ${eastStr} ${northStr}`
}

/**
 * Convert UTM coordinates back to lat/lng (WGS84). Standard series
 * inverse of latLngToUTM above — needed to draw TRUE MGRS grid lines
 * (constant easting / constant northing), which are curves in lat/lng
 * space, not degree-aligned graticule lines.
 */
function utmToLatLng(zone, easting, northing, southernHemisphere = false) {
  const a = 6378137
  const f = 1 / 298.257223563
  const k0 = 0.9996

  const e = Math.sqrt(2 * f - f * f)
  const e2 = e * e
  const ep2 = e2 / (1 - e2)
  const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2))

  const x = easting - 500000
  const y = southernHemisphere ? northing - 10000000 : northing

  const M = y / k0
  const mu = M / (a * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 * e2 * e2 / 256))

  const phi1 = mu +
    (3 * e1 / 2 - 27 * e1 * e1 * e1 / 32) * Math.sin(2 * mu) +
    (21 * e1 * e1 / 16 - 55 * e1 * e1 * e1 * e1 / 32) * Math.sin(4 * mu) +
    (151 * e1 * e1 * e1 / 96) * Math.sin(6 * mu) +
    (1097 * e1 * e1 * e1 * e1 / 512) * Math.sin(8 * mu)

  const sinPhi1 = Math.sin(phi1)
  const cosPhi1 = Math.cos(phi1)
  const tanPhi1 = Math.tan(phi1)

  const N1 = a / Math.sqrt(1 - e2 * sinPhi1 * sinPhi1)
  const T1 = tanPhi1 * tanPhi1
  const C1 = ep2 * cosPhi1 * cosPhi1
  const R1 = a * (1 - e2) / Math.pow(1 - e2 * sinPhi1 * sinPhi1, 1.5)
  const D = x / (N1 * k0)

  const lat = phi1 - (N1 * tanPhi1 / R1) * (
    D * D / 2 -
    (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * D * D * D * D / 24 +
    (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * D * D * D * D * D * D / 720
  )

  const lng = (
    D -
    (1 + 2 * T1 + C1) * D * D * D / 6 +
    (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * D * D * D * D * D / 120
  ) / cosPhi1

  const lngOrigin = (zone - 1) * 6 - 180 + 3
  return {
    lat: lat * 180 / Math.PI,
    lng: lngOrigin + lng * 180 / Math.PI,
  }
}

// Grid spacing (meters) by zoom — the real MGRS tiers. Zoom < 6 shows
// only the GZD frame (zone/band boundaries).
function gridSpacingForZoom(zoom) {
  if (zoom >= 15) return 1000     // 1 km squares, close-in work
  if (zoom >= 12) return 1000     // 1 km
  if (zoom >= 9) return 10000     // 10 km
  if (zoom >= 6) return 100000    // 100 km
  return null
}

// Hard cap on lines per axis per zone — if the viewport is too wide for
// the tier (transition zooms), coarsen one tier instead of flooding.
const MAX_LINES_PER_AXIS = 80
const LINE_SAMPLE_POINTS = 12

/**
 * Generate MGRS grid GeoJSON for the current map bounds.
 *
 * TRUE MGRS lines: within each UTM zone intersecting the viewport,
 * lines of constant easting and constant northing at the zoom tier's
 * spacing (100 km / 10 km / 1 km), sampled into polylines (they curve
 * in lat/lng space), clipped to the zone's longitude band so lines
 * break at zone boundaries exactly as MGRS does. Intersection labels
 * carry the principal easting/northing digits.
 *
 * @param {Object} bounds - Map bounds {north, south, east, west}
 * @param {number} zoom - Current zoom level
 * @returns {Object} GeoJSON FeatureCollection with grid lines and labels
 */
export function generateMGRSGrid(bounds, zoom) {
  const features = []
  const { north, south, east, west } = bounds

  // --- GZD frame: UTM zone boundaries (every 6° lng) + latitude bands (8°) ---
  const startZoneLng = Math.floor(west / UTM_ZONE_WIDTH) * UTM_ZONE_WIDTH
  const endZoneLng = Math.ceil(east / UTM_ZONE_WIDTH) * UTM_ZONE_WIDTH
  for (let lng = startZoneLng; lng <= endZoneLng; lng += UTM_ZONE_WIDTH) {
    if (lng >= -180 && lng <= 180) {
      features.push({
        type: 'Feature',
        properties: { type: 'zone-boundary', longitude: lng },
        geometry: {
          type: 'LineString',
          coordinates: [[lng, Math.max(south, -80)], [lng, Math.min(north, 84)]],
        },
      })
    }
  }
  const startBandLat = Math.floor((south + 80) / LATITUDE_BAND_HEIGHT) * LATITUDE_BAND_HEIGHT - 80
  const endBandLat = Math.ceil((north + 80) / LATITUDE_BAND_HEIGHT) * LATITUDE_BAND_HEIGHT - 80
  for (let lat = startBandLat; lat <= endBandLat; lat += LATITUDE_BAND_HEIGHT) {
    if (lat >= -80 && lat <= 84) {
      features.push({
        type: 'Feature',
        properties: { type: 'band-boundary', latitude: lat },
        geometry: {
          type: 'LineString',
          coordinates: [[Math.max(west, -180), lat], [Math.min(east, 180), lat]],
        },
      })
    }
  }

  let spacing = gridSpacingForZoom(zoom)
  if (!spacing) return { type: 'FeatureCollection', features }

  const southernHemisphere = (south + north) / 2 < 0

  // --- Per UTM zone intersecting the viewport ---
  const firstZone = getUTMZone(Math.max(west, -179.999))
  const lastZone = getUTMZone(Math.min(east, 179.999))
  for (let zone = firstZone; zone <= lastZone; zone++) {
    const zoneWest = (zone - 1) * 6 - 180
    const zoneEast = zoneWest + 6
    const clipWest = Math.max(west, zoneWest)
    const clipEast = Math.min(east, zoneEast)
    if (clipEast <= clipWest) continue

    // UTM range of the clipped viewport corners (sample all four plus
    // edge midpoints — easting extremes sit at top or bottom depending
    // on hemisphere and meridian side).
    const cornerPts = [
      [south, clipWest], [south, clipEast], [north, clipWest], [north, clipEast],
      [south, (clipWest + clipEast) / 2], [north, (clipWest + clipEast) / 2],
    ]
    let minE = Infinity, maxE = -Infinity, minN = Infinity, maxN = -Infinity
    for (const [lat, lng] of cornerPts) {
      const u = latLngToUTM(lat, Math.min(Math.max(lng, zoneWest + 1e-9), zoneEast - 1e-9))
      minE = Math.min(minE, u.easting); maxE = Math.max(maxE, u.easting)
      minN = Math.min(minN, u.northing); maxN = Math.max(maxN, u.northing)
    }

    // Coarsen if the viewport spans too many lines for this tier
    // (transition zooms), rather than flooding the style.
    let effSpacing = spacing
    while ((maxE - minE) / effSpacing > MAX_LINES_PER_AXIS ||
           (maxN - minN) / effSpacing > MAX_LINES_PER_AXIS) {
      effSpacing *= 10
    }

    const eStart = Math.floor(minE / effSpacing) * effSpacing
    const nStart = Math.floor(minN / effSpacing) * effSpacing

    // Constant-easting lines (run south-north), sampled along northing.
    for (let eVal = eStart; eVal <= maxE + effSpacing; eVal += effSpacing) {
      const coords = []
      for (let i = 0; i <= LINE_SAMPLE_POINTS; i++) {
        const nVal = minN + ((maxN - minN) * i) / LINE_SAMPLE_POINTS
        const p = utmToLatLng(zone, eVal, nVal, southernHemisphere)
        if (p.lng >= zoneWest - 0.001 && p.lng <= zoneEast + 0.001) {
          coords.push([p.lng, p.lat])
        }
      }
      if (coords.length >= 2) {
        features.push({
          type: 'Feature',
          properties: { type: 'grid-line', subtype: 'easting', value: eVal },
          geometry: { type: 'LineString', coordinates: coords },
        })
      }
    }

    // Constant-northing lines (run west-east), sampled along easting.
    for (let nVal = nStart; nVal <= maxN + effSpacing; nVal += effSpacing) {
      const coords = []
      for (let i = 0; i <= LINE_SAMPLE_POINTS; i++) {
        const eVal = minE + ((maxE - minE) * i) / LINE_SAMPLE_POINTS
        const p = utmToLatLng(zone, eVal, nVal, southernHemisphere)
        if (p.lng >= zoneWest - 0.001 && p.lng <= zoneEast + 0.001) {
          coords.push([p.lng, p.lat])
        }
      }
      if (coords.length >= 2) {
        features.push({
          type: 'Feature',
          properties: { type: 'grid-line', subtype: 'northing', value: nVal },
          geometry: { type: 'LineString', coordinates: coords },
        })
      }
    }

    // Intersection labels: principal digits per MGRS convention (the
    // 10 km / 1 km digits of the easting+northing pair), thinned so at
    // most every other intersection labels at the densest tier.
    const labelEvery = effSpacing >= 100000 ? 1 : 2
    let ei = 0
    for (let eVal = eStart; eVal <= maxE + effSpacing; eVal += effSpacing, ei++) {
      if (ei % labelEvery) continue
      let ni = 0
      for (let nVal = nStart; nVal <= maxN + effSpacing; nVal += effSpacing, ni++) {
        if (ni % labelEvery) continue
        const p = utmToLatLng(zone, eVal, nVal, southernHemisphere)
        if (p.lng < clipWest || p.lng > clipEast || p.lat < south || p.lat > north) continue
        const digits = effSpacing >= 100000
          ? get100kId(zone, eVal + 1, nVal + 1)
          : `${String(Math.floor((eVal % 100000) / effSpacing)).padStart(2, '0')} ${String(Math.floor((nVal % 100000) / effSpacing)).padStart(2, '0')}`
        features.push({
          type: 'Feature',
          properties: { type: 'grid-label', label: digits },
          geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
        })
      }
    }
  }

  return { type: 'FeatureCollection', features }
}

/**
 * MGRS grid layer styles for MapLibre
 * Line widths scale with zoom to maintain visual weight
 */
export const MGRS_GRID_LAYERS = [
  // Zone/band boundary lines (thicker)
  {
    id: 'mgrs-zone-lines',
    type: 'line',
    source: 'mgrs-grid',
    filter: ['in', 'type', 'zone-boundary', 'band-boundary'],
    paint: {
      'line-color': '#3d566b',
      'line-width': [
        'interpolate', ['linear'], ['zoom'],
        3, 1,
        6, 1.5,
        10, 2.5,
        14, 4
      ],
      'line-opacity': 0.9
    }
  },
  // Grid lines (constant easting/northing at the zoom tier's spacing)
  {
    id: 'mgrs-grid-lines',
    type: 'line',
    source: 'mgrs-grid',
    filter: ['==', 'type', 'grid-line'],
    paint: {
      'line-color': '#3d566b',
      'line-width': [
        'interpolate', ['linear'], ['zoom'],
        5, 0.6,
        8, 1,
        12, 1.6,
        16, 2.5
      ],
      'line-opacity': 0.65
    }
  },
  // Intersection labels (principal easting/northing digits, or the
  // 100 km square id at the 100 km tier)
  {
    id: 'mgrs-grid-labels',
    type: 'symbol',
    source: 'mgrs-grid',
    filter: ['==', 'type', 'grid-label'],
    layout: {
      'text-field': ['get', 'label'],
      'text-font': ['Noto Sans Regular'],
      'text-size': 11,
      'text-anchor': 'bottom-left',
      'text-offset': [0.3, -0.3],
      'text-allow-overlap': false,
    },
    paint: {
      'text-color': '#3d566b',
      'text-halo-color': 'rgba(255,255,255,0.9)',
      'text-halo-width': 1.4,
    }
  }
]
