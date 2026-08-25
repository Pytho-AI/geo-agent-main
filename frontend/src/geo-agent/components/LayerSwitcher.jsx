/**
 * LayerSwitcher
 *
 * Drives the analyst's base-map / overlay choices on the unified style.
 *
 * Sections (collapsible accordion):
 *   - Base Map       visibility-toggles the style's basemap raster layers
 *                    (default / terrain / satellite)
 *   - Map Features   MGRS grid + the two client-side place-label tiers
 *   - Weather        forecast raster overlay + scrub slider
 *
 * Every toggle here MUST map to layers that exist in the unified style —
 * a control wired to a retired layer id renders a checkbox that does
 * nothing, which reads as a broken map to the analyst.
 */

import React, { useEffect, useCallback, useState } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { BASE_MAP_SOURCES, placeLabelFilters, LABEL_DETAIL_MAX } from '../utils/mapStyles'

// Map Features toggle -> MapLibre layer-id mapping. Client-side layers
// only: the basemap raster is opaque server-rendered imagery, so
// anything baked into it (water, roads, terrain shading) cannot be
// toggled from here.
//
// Place labels: ONE master toggle ("Labels" — both layers' visibility)
// plus the label DETAIL SLIDER, which caps Protomaps' min_zoom
// prominence rank via setFilter (placeLabelFilters in mapStyles —
// countries/capitals rank ~0-4, towns ~8-11, villages 11+, so the
// slider sweeps from "Major" to "All").
//
// Contours are DELIBERATELY absent from this mapping: their layers are
// added at runtime by the owners of each treatment (GeoAgentMap for
// the topo-basemap brown set, MapDoctrinalPaint for the black
// doctrinal set), and both read layerVisibility.contours directly —
// the checkbox here only drives that state. Listing runtime layer ids
// here would race the owners' idempotent ensure/repaint passes.
const FEATURE_LAYER_MAPPINGS = {
  mgrsGrid: ['mgrs-zone-lines', 'mgrs-grid-lines', 'mgrs-grid-labels'],
  labels: ['places-region-labels', 'places-locality-labels'],
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
// Section wrapper. MODULE-scoped deliberately: defining this inside the
// LayerSwitcher render made it a brand-new component type every render,
// so React REMOUNTED each section's subtree on any state change — a
// slider inside died mid-drag (the input was replaced after the first
// step and lost its native pointer capture). Never define components
// inside a render body.
function Section({ id, title, children, count, open, onToggle }) {
  return (
    <div className={`layer-section ${open ? 'open' : 'collapsed'}`}>
      <button className="layer-section-header" onClick={() => onToggle(id)} type="button">
        <span className="layer-section-caret">{open ? '▼' : '▶'}</span>
        <span className="layer-section-title">{title}</span>
        {count != null && <span className="layer-section-count">{count}</span>}
      </button>
      {open && <div className="layer-section-body">{children}</div>}
    </div>
  )
}

function setLayerVisibilityOnMap(map, layerId, visible) {
  try {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none')
    }
  } catch {
    // layer not yet present — ignore
  }
}

function setLayerOpacityOnMap(map, layerId, opacity) {
  try {
    if (map.getLayer(layerId)) {
      const type = map.getLayer(layerId).type
      if (type === 'raster') {
        map.setPaintProperty(layerId, 'raster-opacity', opacity)
      }
    }
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function LayerSwitcher() {
  const {
    showLayerSwitcher,
    setShowLayerSwitcher,
    baseMapStyle,
    setBaseMapStyle,
    layerVisibility,
    setLayerVisibility,
    labelDetail,
    setLabelDetail,
    layerOpacity,
    mapRef,
    mapLoaded,
    viewportLoaded,
    // Weather overlay (forecast tiles via this service's /tiles/weather
    // proxy — ported from the pytho-vite copy)
    weatherVisible,
    setWeatherVisible,
    weatherLayer,
    setWeatherLayer,
    weatherHour,
    setWeatherHour,
  } = useGeoAgent()

  // Section collapse state (uncontrolled — local only).
  const [openSections, setOpenSections] = useState({
    base:     true,
    features: true,
    weather:  true,
  })

  const toggleSection = (key) => setOpenSections((p) => ({ ...p, [key]: !p[key] }))

  // ---- Apply Map Features visibility -------------------------------------
  const applyFeatureVisibility = useCallback((logicalId, visible) => {
    const map = mapRef.current
    if (!map) return
    const ids = FEATURE_LAYER_MAPPINGS[logicalId] || []
    ids.forEach((layerName) => setLayerVisibilityOnMap(map, layerName, visible))
  }, [mapRef])

  useEffect(() => {
    if (!mapLoaded || !viewportLoaded) return
    applyFeatureVisibility('mgrsGrid', !!layerVisibility.mgrsGrid)
    // "Labels" master kills/restores BOTH place-label layers.
    applyFeatureVisibility('labels', !!layerVisibility.labels)
  }, [mapLoaded, viewportLoaded, layerVisibility, applyFeatureVisibility])

  // ---- Apply label detail (prominence cap) via setFilter -----------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || !viewportLoaded) return
    const filters = placeLabelFilters(labelDetail)
    for (const [layerId, filter] of Object.entries(filters)) {
      try {
        if (map.getLayer(layerId)) map.setFilter(layerId, filter)
      } catch { /* layer not ready yet — initial style filter applies */ }
    }
  }, [mapRef, mapLoaded, viewportLoaded, labelDetail])

  // ---- Apply per-layer opacity (persisted map attrs) ----------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || !viewportLoaded) return
    for (const [layerId, op] of Object.entries(layerOpacity)) {
      setLayerOpacityOnMap(map, layerId, op)
    }
  }, [mapRef, mapLoaded, viewportLoaded, layerOpacity])

  if (!showLayerSwitcher) return null

  // ---- Handlers ----------------------------------------------------------
  const handleBaseMapChange = (mapId) => setBaseMapStyle(mapId)

  const handleFeatureToggle = (logicalId) => {
    setLayerVisibility((p) => ({ ...p, [logicalId]: !p[logicalId] }))
  }

  const baseMaps = Object.values(BASE_MAP_SOURCES)

  // Map Features rows — every entry MUST have a live backing layer in
  // the unified style. The old 'water' row targeted the retired
  // offline-vector era's client water layers, which do not exist on the
  // unified raster basemap (water is baked into the server-rendered
  // raster) — a toggle wired to nothing is a lie to the analyst.
  const featureLayers = [
    { id: 'mgrsGrid', name: 'MGRS Grid', icon: '⊞' },  // ⊞
    { id: 'labels',   name: 'Labels',    icon: 'Aa' },
    // Contour linework (elevation rings + labeled index contours) and
    // spot heights (named-peak elevation points). State-only here —
    // see FEATURE_LAYER_MAPPINGS.
    { id: 'contours',    name: 'Contours',     icon: '〰' },
    { id: 'spotHeights', name: 'Spot Heights', icon: '△' },
  ]

  return (
    <div className="layer-switcher">
      <div className="layer-switcher-header">
        <h3>Map Layers</h3>
        <button onClick={() => setShowLayerSwitcher(false)} type="button">×</button>
      </div>

      <div className="layer-switcher-content">
        {/* Base Map ------------------------------------------------------ */}
        <Section id="base" title="Base Map" open={openSections.base} onToggle={toggleSection}>
          <div className="base-map-grid">
            {baseMaps.map((source) => (
              <button
                key={source.id}
                className={`base-map-btn ${baseMapStyle === source.id ? 'active' : ''}`}
                onClick={() => handleBaseMapChange(source.id)}
                title={source.name}
                type="button"
              >
                <div className="base-map-preview" data-type={source.id}>
                  {source.id === 'default'   && '🪖'}
                  {source.id === 'terrain'   && '⛰️'}
                  {source.id === 'topo'      && '🗺️'}
                  {source.id === 'satellite' && '🛰️'}
                </div>
                <span className="base-map-name">{source.name}</span>
              </button>
            ))}
          </div>
        </Section>

        {/* Map Features -------------------------------------------------- */}
        <Section id="features" title="Map Features" open={openSections.features} onToggle={toggleSection}>
          <div className="overlay-toggles">
            {featureLayers.map((layer) => (
              <React.Fragment key={layer.id}>
                <label className="overlay-toggle">
                  <input
                    type="checkbox"
                    checked={!!layerVisibility[layer.id]}
                    onChange={() => handleFeatureToggle(layer.id)}
                  />
                  <span className="overlay-toggle-icon">{layer.icon}</span>
                  <span className="overlay-toggle-name">{layer.name}</span>
                </label>
                {/* Label detail — prominence cap over Protomaps' min_zoom
                    rank. Left = only the most prominent places (countries,
                    Osaka-class cities); right = every village. Rendered
                    directly under its owning Labels row and ONLY while
                    Labels is checked — same conditional-render pattern as
                    the weather forecast slider. */}
                {layer.id === 'labels' && layerVisibility.labels && (
                  <div
                    className="label-detail-row"
                    title={`Label detail: places of prominence rank ${labelDetail} and above`}
                  >
                    <span className="label-detail-title">Detail</span>
                    <input
                      type="range"
                      className="label-detail-slider"
                      min={3}
                      max={LABEL_DETAIL_MAX}
                      step={1}
                      value={labelDetail}
                      onChange={(e) => setLabelDetail(Number(e.target.value))}
                    />
                    <span className="label-detail-value">
                      {labelDetail >= LABEL_DETAIL_MAX ? 'All' : labelDetail <= 3 ? 'Major' : labelDetail}
                    </span>
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
        </Section>

        {/* Weather overlay (forecast raster tiles; layer codes are the
            upstream service's own identifiers) ---------------------- */}
        <Section id="weather" title="Weather" open={openSections.weather} onToggle={toggleSection}>
          <div className="weather-layer-grid">
            {[
              { id: 'TA2',  label: 'Temp',     icon: '🌡' },
              { id: 'PR0',  label: 'Rain',     icon: '🌧' },
              { id: 'PAS0', label: 'Snow',     icon: '❄' },
              { id: 'WND',  label: 'Wind',     icon: '💨' },
              { id: 'CL',   label: 'Clouds',   icon: '☁' },
              { id: 'APM',  label: 'Pressure', icon: '◎' },
            ].map(layer => {
              const isActive = weatherVisible && weatherLayer === layer.id
              return (
                <button
                  key={layer.id}
                  className={`weather-layer-btn ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    if (isActive) {
                      setWeatherVisible(false)
                    } else {
                      setWeatherLayer(layer.id)
                      setWeatherVisible(true)
                    }
                  }}
                  title={layer.label}
                >
                  <span className="weather-layer-icon">{layer.icon}</span>
                  <span className="weather-layer-label">{layer.label}</span>
                </button>
              )
            })}
          </div>
          {weatherVisible && (
            <div className="weather-forecast-row">
              <div className="weather-forecast-header">
                <span className="weather-forecast-label">Forecast</span>
                <span className="weather-forecast-value">
                  {weatherHour === 0 ? 'Now' : `+${weatherHour}h`}
                </span>
              </div>
              <input
                type="range"
                className="weather-forecast-slider"
                min={0}
                max={72}
                step={3}
                value={weatherHour}
                onChange={(e) => setWeatherHour(Number(e.target.value))}
              />
              <div className="weather-forecast-ticks">
                <span>Now</span>
                <span>24h</span>
                <span>48h</span>
                <span>72h</span>
              </div>
            </div>
          )}
        </Section>

      </div>
    </div>
  )
}
