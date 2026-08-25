/**
 * Map unit search — a collapsible control-style button (top-left) that opens
 * into a search pill. Type a unit name and fly the camera to it.
 *
 * Collapsed it's a 40x40 icon button matching the map's other controls; click
 * it and the pill expands with a search field + live results. Matches against
 * the mil_unit features currently painted on the map (the `mil-units` GeoJSON
 * source), so it always finds exactly what's visible — enemy OOB units and any
 * friendly units alike — without a separate fetch. Selecting a match flies the
 * camera there and opens the same UnitMetadataPanel a left-click would
 * (setSelectedUnitMeta + the resolved-OOB lookup, mirroring useMapEvents).
 */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { lookupUnitMetadata } from '../utils/unitMetadata'

const MAX_RESULTS = 8

// Property keys a unit's name can live under, in display-preference order.
const NAME_KEYS = [
  'name',
  'unit_short_name',
  'unit_long_name',
  'honorific_name',
  'unique_designation',
  'short_name',
]

function displayName(props) {
  for (const k of NAME_KEYS) {
    const v = props?.[k]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return 'Unnamed unit'
}

// Read the mil_unit point features straight off the live source. renderMilUnits
// always setData()s an inline FeatureCollection, so `_data` holds the current
// set (the codebase already relies on this private field elsewhere).
function readUnitFeatures(map) {
  try {
    const feats = map?.getSource('mil-units')?._data?.features || []
    return feats.filter(
      (f) => f?.geometry?.type === 'Point' && Array.isArray(f.geometry.coordinates),
    )
  } catch {
    return []
  }
}

export function MapSearchControl() {
  const { mapRef, setSelectedUnitMeta, addActivity, editEnabled } = useGeoAgent()

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  // Bumped when the pill opens so the feature list is re-read fresh.
  const [refreshTick, setRefreshTick] = useState(0)
  const wrapRef = useRef(null)
  const inputRef = useRef(null)

  // Focus the field once the pill opens; re-read the painted features.
  useEffect(() => {
    if (!open) return
    setRefreshTick((t) => t + 1)
    const id = requestAnimationFrame(() => inputRef.current?.focus())
    return () => cancelAnimationFrame(id)
  }, [open])

  // Collapse the pill on an outside click.
  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q || !open) return []
    void refreshTick // re-read features when the tick changes
    const feats = readUnitFeatures(mapRef?.current)
    const scored = []
    const seen = new Set()
    for (const f of feats) {
      const props = f.properties || {}
      const name = displayName(props)
      const key = props.source_kbid || props.id || f.id || name
      if (seen.has(key)) continue
      const hay = NAME_KEYS.map((k) => props[k])
        .filter((v) => typeof v === 'string')
        .join(' ')
        .toLowerCase()
      const idx = hay.indexOf(q)
      if (idx === -1) continue
      seen.add(key)
      // Rank exact-prefix matches on the display name above mid-string hits.
      const rank = name.toLowerCase().startsWith(q) ? 0 : 1
      scored.push({ feature: f, name, rank, idx })
    }
    scored.sort((a, b) => a.rank - b.rank || a.idx - b.idx || a.name.localeCompare(b.name))
    return scored.slice(0, MAX_RESULTS)
  }, [query, open, mapRef, refreshTick])

  function goToUnit(feature) {
    const map = mapRef?.current
    if (!map || !feature) return
    const coords = feature.geometry.coordinates // [lng, lat]
    const props = feature.properties || {}
    map.flyTo({ center: coords, zoom: Math.max(map.getZoom(), 14), duration: 1200 })

    // Open the unit inspector, mirroring the live-map left-click handler:
    // show feature props immediately, then enrich with the fused OOB record.
    const kgId = props.source_kbid || props.id || props.entity_id || feature.id
    const name = props.name || props.unique_designation || props.short_name
    setSelectedUnitMeta?.({ unit: null, props, coords })
    lookupUnitMetadata({ kgId, name })
      .then((unit) => {
        if (unit) setSelectedUnitMeta?.({ unit, props, coords })
      })
      .catch(() => { /* keep the feature-only view */ })

    addActivity?.(`Located unit: ${displayName(props)}`, 'info')
    setQuery(displayName(props))
    setOpen(false)
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && matches.length > 0) {
      goToUnit(matches[0].feature)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const showResults = open && query.trim().length > 0

  return (
    <div ref={wrapRef} className={`map-search-wrap ${editEnabled ? 'edit-offset' : ''}`}>
      <div className={`map-search ${open ? 'open' : ''}`}>
        <button
          type="button"
          className="map-search-toggle"
          title={open ? 'Close unit search' : 'Find unit by name'}
          aria-label="Find unit by name"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
        <div className="map-search-field">
          <input
            ref={inputRef}
            type="text"
            value={query}
            placeholder="Find unit by name…"
            tabIndex={open ? 0 : -1}
            onChange={(e) => { setQuery(e.target.value); if (!open) setOpen(true) }}
            onKeyDown={onKeyDown}
          />
          {query && (
            <button
              type="button"
              className="map-search-clear"
              title="Clear"
              onClick={() => { setQuery(''); inputRef.current?.focus() }}
            >
              ×
            </button>
          )}
        </div>
      </div>
      {showResults && (
        <div className="map-search-results">
          {matches.length === 0 ? (
            <div className="map-search-empty">No matching units</div>
          ) : (
            matches.map(({ feature, name }, i) => {
              const props = feature.properties || {}
              const sub = props.echelon || props.affiliation || props.force_type
              return (
                <button
                  key={props.source_kbid || props.id || feature.id || i}
                  type="button"
                  className="map-search-result"
                  onClick={() => goToUnit(feature)}
                >
                  <span className="map-search-name">{name}</span>
                  {sub && <span className="map-search-sub">{sub}</span>}
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
