/**
 * RoutePlannerPanel - Panel showing route analysis with edit support
 */

import React, { useState, useCallback } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'

// Tiny CSS spinner for pending analysis fields
const Spinner = () => (
  <span style={{
    display: 'inline-block',
    width: '12px',
    height: '12px',
    border: '2px solid #333',
    borderTop: '2px solid #888',
    borderRadius: '50%',
    animation: 'route-spin 0.8s linear infinite',
    verticalAlign: 'middle',
  }} />
)

/** Format hours into DoD-style duration: e.g. "2h 15m" or "45m" */
function formatTimeDod(hours) {
  if (hours == null || isNaN(hours)) return '—'
  const h = Math.floor(hours)
  const m = Math.round((hours - h) * 60)
  if (h === 0) return `${m}m`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

function AnalysisView({ analysis, pendingFields, rateOfAdvance }) {
  const accentColor = '#3B82F6'
  if (!analysis) return <div style={{ color: '#666', padding: '16px' }}>No analysis available</div>

  const pending = pendingFields || new Set()

  // Compute time of march from distance (mi) and rate of advance (mph)
  const rate = rateOfAdvance ? parseFloat(rateOfAdvance) : null
  const distanceMi = analysis.distance_mi != null ? parseFloat(analysis.distance_mi) : null
  const timeHours = (rate && rate > 0 && distanceMi != null) ? distanceMi / rate : null

  // Build stats array — include rate & time only when rate was provided
  const stats = [
    { label: 'Distance', key: 'distance_mi', value: `${analysis.distance_mi ?? '—'} mi` },
    { label: 'Max Slope', key: 'max_slope_pct', value: `${analysis.max_slope_pct ?? '—'}%` },
    { label: 'Concealment', key: 'concealment_pct', value: `${analysis.concealment_pct ?? '—'}%` },
    { label: 'Threat Exposure', key: 'threat_exposure_mi', value: `${analysis.threat_exposure_mi ?? '—'} mi` },
    { label: 'Elev Gain', key: 'elevation_gain_ft', value: `${analysis.elevation_gain_ft ?? '—'} ft` },
    { label: 'Elev Loss', key: 'elevation_loss_ft', value: `${analysis.elevation_loss_ft ?? '—'} ft` },
  ]

  if (rate && rate > 0) {
    stats.push({ label: 'Rate of Advance', key: '_roa', value: `${rate} mph` })
    stats.push({ label: 'Est. Time of March', key: '_tom', value: formatTimeDod(timeHours) })
  }

  return (
    <div style={{ padding: '12px 0' }}>
      {/* Summary stats */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '16px' }}>
        {stats.map(({ label, key, value }) => (
          <div key={label} style={{
            background: '#1a1a2e',
            borderRadius: '6px',
            padding: '8px 10px',
            border: '1px solid #333',
          }}>
            <div style={{ fontSize: '10px', color: '#888', marginBottom: '2px' }}>{label}</div>
            <div style={{ fontSize: '14px', color: '#fff', fontWeight: '500' }}>
              {pending.has(key) ? <Spinner /> : value}
            </div>
          </div>
        ))}
      </div>

      {/* Terrain breakdown */}
      {analysis.terrain_breakdown && Object.keys(analysis.terrain_breakdown).length > 0 && (
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '12px', color: '#aaa', marginBottom: '6px', fontWeight: '500' }}>
            Terrain Breakdown
          </div>
          {pending.size > 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 0', color: '#888', fontSize: '12px' }}>
              <Spinner /> Updating terrain data...
            </div>
          ) : (
            Object.entries(analysis.terrain_breakdown).map(([name, pct]) => (
              <div key={name} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <div style={{
                  flex: 1, height: '6px', background: '#333', borderRadius: '3px', overflow: 'hidden',
                }}>
                  <div style={{
                    width: `${Math.round(pct * 100)}%`, height: '100%',
                    background: accentColor, borderRadius: '3px',
                  }} />
                </div>
                <span style={{ fontSize: '11px', color: '#ccc', minWidth: '120px' }}>
                  {Math.round(pct * 100)}% {name}
                </span>
              </div>
            ))
          )}
        </div>
      )}

      {/* Weather along route (backend routing analysis attaches
          analysis.weather when the forecast service is configured;
          ported from the pytho-vite copy) */}
      {analysis.weather && (() => {
        const segments = analysis.weather.segments || []
        const hazards = analysis.weather.hazards || []
        const w = analysis.weather.summary || {}
        const conditionIcons = {
          Thunderstorm: '⛈', Rain: '🌧', Drizzle: '🌦',
          Snow: '❄', Clouds: '☁', Clear: '☀',
          Mist: '🌫', Fog: '🌫', Haze: '🌫',
          Smoke: '🌫', Dust: '🌫', Sand: '🌫',
          Squall: '💨', Tornado: '🌪',
        }
        if (segments.length === 0 && hazards.length === 0) return null

        return (
          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '12px', color: '#aaa', marginBottom: '6px', fontWeight: '500' }}>
              Weather Along Route
            </div>
            {pending.size > 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 0', color: '#888', fontSize: '12px' }}>
                <Spinner /> Updating weather data...
              </div>
            ) : (
              <>
                {/* Weather condition bar */}
                {segments.length > 0 && (() => {
                  const totalMi = analysis.distance_mi || (segments[segments.length - 1].end_mi) || 1
                  return (
                    <div style={{ marginBottom: '8px' }}>
                      <div style={{ display: 'flex', height: '14px', borderRadius: '4px', overflow: 'hidden', gap: '1px' }}>
                        {segments.map((seg, i) => {
                          const width = Math.max(((seg.end_mi - seg.start_mi) / totalMi) * 100, 2)
                          return (
                            <div
                              key={i}
                              title={`Mi ${seg.start_mi}–${seg.end_mi}: ${seg.condition}${seg.temp_c != null ? `, ${seg.temp_c}°C` : ''}${seg.wind_speed_ms != null ? `, ${seg.wind_speed_ms} m/s` : ''}`}
                              style={{
                                width: `${width}%`,
                                background: seg.color || '#94a3b8',
                                minWidth: '4px',
                                cursor: 'default',
                              }}
                            />
                          )
                        })}
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#666', marginTop: '2px' }}>
                        <span>0 mi</span>
                        <span>{totalMi} mi</span>
                      </div>
                    </div>
                  )
                })()}

                {/* Enriched segment breakdown */}
                {segments.length > 0 && (
                  <div style={{ marginBottom: '8px' }}>
                    {segments.map((seg, i) => {
                      const visKm = w.visibility_m != null ? (w.visibility_m / 1000).toFixed(1) : null
                      return (
                        <div key={i} style={{
                          padding: '6px 8px', marginBottom: '4px',
                          background: '#1a1a2e', borderRadius: '6px',
                          borderLeft: `3px solid ${seg.color || '#94a3b8'}`,
                        }}>
                          <div style={{ fontSize: '12px', color: '#fff', fontWeight: '500', marginBottom: '2px' }}>
                            {conditionIcons[seg.condition] || ''} {seg.condition}
                            <span style={{ color: '#666', fontWeight: '400', marginLeft: '6px' }}>
                              Mi {seg.start_mi}–{seg.end_mi}
                            </span>
                          </div>
                          <div style={{ fontSize: '11px', color: '#999', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                            {seg.temp_c != null && <span>{seg.temp_c}°C</span>}
                            {seg.wind_speed_ms != null && <span>{seg.wind_speed_ms} m/s wind</span>}
                            {visKm != null && parseFloat(visKm) < 10 && <span>vis {visKm} km</span>}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
                {/* Hazard callouts */}
                {hazards.length > 0 && (
                  <div style={{ marginBottom: '4px' }}>
                    {hazards.map((h, i) => (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'flex-start', gap: '6px',
                        padding: '5px 8px', marginBottom: '4px',
                        background: h.severity === 'danger' ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
                        border: `1px solid ${h.severity === 'danger' ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.4)'}`,
                        borderRadius: '5px', fontSize: '11px',
                      }}>
                        <span style={{ flexShrink: 0 }}>
                          {h.severity === 'danger' ? '⚠️' : '⚠'}
                        </span>
                        <span style={{ color: h.severity === 'danger' ? '#fca5a5' : '#fcd34d' }}>
                          {h.message}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )
      })()}

      {/* Elevation profile */}
      {analysis.elevation_profile && analysis.elevation_profile.length > 0 && (
        <div>
          <div style={{ fontSize: '12px', color: '#aaa', marginBottom: '6px', fontWeight: '500' }}>
            Elevation Profile
          </div>
          {pending.size > 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 0', color: '#888', fontSize: '12px' }}>
              <Spinner /> Updating elevation data...
            </div>
          ) : (
            <>
              <div style={{
                display: 'flex', alignItems: 'flex-end', gap: '2px', height: '60px', padding: '0 4px',
              }}>
                {analysis.elevation_profile.map((pt, i) => {
                  const maxE = Math.max(...analysis.elevation_profile.map(p => p.elevation_ft || 0))
                  const minE = Math.min(...analysis.elevation_profile.filter(p => p.elevation_ft).map(p => p.elevation_ft))
                  const range = maxE - minE || 1
                  const h = pt.elevation_ft ? ((pt.elevation_ft - minE) / range * 50 + 10) : 10
                  return (
                    <div
                      key={i}
                      title={`${pt.mi} mi — ${pt.elevation_ft ?? '?'} ft`}
                      style={{
                        flex: 1, height: `${h}px`, background: accentColor,
                        borderRadius: '2px 2px 0 0', opacity: 0.7, minWidth: '3px',
                      }}
                    />
                  )
                })}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#666', marginTop: '2px' }}>
                <span>0 mi</span>
                <span>{analysis.distance_mi} mi</span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function RoutePlannerPanel({ getRouteEditCoordsRef }) {
  const {
    routeResult,
    showRoutePanel,
    setShowRoutePanel,
    setRoutePlanMode,
    setRouteStart,
    setRouteEnd,
    setRouteResult,
    apiUrl,
    mapId,
    addActivity,
    triggerMapRefresh,
    // Route editing
    setRouteEditMode,
    routeEditAnalysis,
    setRouteEditAnalysis,
    routeEditLoading,
    routeEditDirty,
    setRouteEditDirty,
    setShowRouteModeModal,
    routePreferences,
    routeIsNew,
    setRouteIsNew,
  } = useGeoAgent()

  const [deleting, setDeleting] = useState(false)
  const [saving, setSaving] = useState(false)
  const api = createApiClient(apiUrl)

  if (!showRoutePanel || !routeResult) return null

  const path = routeResult.paths?.[0]

  // --- Shared: exit edit mode and close panel ---
  const exitAndClose = () => {
    setRouteEditMode(false)   // removes amber preview + handles (hook cleanup)
    setRouteEditAnalysis(null)
    setRouteEditDirty(false)
    setShowRoutePanel(false)
    setRouteStart(null)
    setRouteEnd(null)
    setRoutePlanMode(false)
    setRouteIsNew(false)
  }

  // --- Cancel / Close: just remove the amber preview, original green stays ---
  const handleClose = () => exitAndClose()

  // --- Save: persist to backend, then refresh map to show updated green route ---
  const handleSave = async () => {
    const coords = getRouteEditCoordsRef?.current?.()
    if (!coords || !routeEditDirty) {
      handleClose()
      return
    }

    setSaving(true)
    try {
      let analysis = routeEditAnalysis
      if (!analysis && routeEditDirty) {
        try { analysis = await api.analyzeRouteEdit(mapId, coords) } catch (_) {}
      }
      if (!analysis) analysis = path?.analysis

      if (!routeResult?.id || !path?.id) {
        console.warn('Cannot save route edit: missing routeId or pathId', { routeId: routeResult?.id, pathId: path?.id })
        addActivity('Failed to save route: missing route or path ID', 'error')
        return
      }

      await api.updatePath(routeResult.id, path.id, {
        geom: { type: 'LineString', coordinates: coords },
        analysis,
      })

      exitAndClose()
      // Refresh map — routes are re-fetched from API so the green line updates
      triggerMapRefresh()
      addActivity('Route saved', 'success')
    } catch (err) {
      addActivity(`Failed to save route: ${err.message}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  // --- Edit: open planner modal with existing start/end ---
  const handleEdit = () => {
    const startCoords = routeResult.start_geom?.coordinates
    const endCoords = routeResult.end_geom?.coordinates
    if (startCoords && endCoords) {
      setRouteStart({ lng: startCoords[0], lat: startCoords[1] })
      setRouteEnd({ lng: endCoords[0], lat: endCoords[1] })
    }
    setRouteEditMode(false)
    setRouteEditAnalysis(null)
    setRouteEditDirty(false)
    setShowRoutePanel(false)
    setShowRouteModeModal(true)
  }

  // --- Delete: remove from backend, then refresh map ---
  const handleDelete = async () => {
    if (!routeResult?.id) return
    setDeleting(true)
    try {
      try { await api.deleteRoute(routeResult.id) } catch (_) {}
      exitAndClose()
      setRouteResult(null)
      triggerMapRefresh()
      addActivity('Route deleted', 'success')
    } catch (err) {
      addActivity(`Failed to delete route: ${err.message}`, 'error')
    } finally {
      setDeleting(false)
    }
  }

  // Merge live edit analysis into the original — only override fields that have real values
  const displayAnalysis = (() => {
    const base = path?.analysis
    if (!routeEditDirty || !routeEditAnalysis || !base) return base
    const merged = { ...base }
    for (const [key, val] of Object.entries(routeEditAnalysis)) {
      if (val !== '—' && val != null) merged[key] = val
    }
    return merged
  })()

  return (
    <div style={{
      position: 'absolute',
      top: '10px',
      right: '10px',
      width: '340px',
      maxHeight: 'calc(100vh - 80px)',
      background: '#141422',
      borderRadius: '10px',
      border: '1px solid #333',
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      zIndex: 1000,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #333',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ fontSize: '14px', color: '#fff', fontWeight: '600' }}>Route</div>
        <button
          onClick={handleClose}
          style={{
            background: 'none', border: 'none', color: '#888',
            fontSize: '18px', cursor: 'pointer', padding: '4px',
          }}
        >
          ×
        </button>
      </div>

      {/* Content */}
      <div style={{ overflowY: 'auto', padding: '0 16px', flex: 1 }}>
        {displayAnalysis
          ? <AnalysisView
              analysis={displayAnalysis}
              rateOfAdvance={routePreferences?.rate_of_advance}
              pendingFields={(routeEditDirty && (!routeEditAnalysis || routeEditLoading)) ? new Set([
                'max_slope_pct', 'concealment_pct', 'threat_exposure_mi',
                'elevation_gain_ft', 'elevation_loss_ft',
              ]) : null}
            />
          : <div style={{ color: '#666', padding: '16px' }}>No route data</div>
        }
      </div>

      {/* Footer */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid #333', display: 'flex', gap: '8px' }}>
        {routeIsNew ? (
          /* New route: Save (accept) + Re-route, no Delete */
          <>
            <button
              onClick={routeEditDirty ? handleSave : () => { exitAndClose(); triggerMapRefresh() }}
              disabled={saving}
              style={{
                flex: 1, padding: '8px', fontSize: '13px', border: 'none',
                borderRadius: '6px', background: '#3B82F6', color: '#fff',
                cursor: saving ? 'not-allowed' : 'pointer',
                fontWeight: '600',
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={handleEdit}
              style={{
                flex: 1, padding: '8px', fontSize: '13px', border: 'none',
                borderRadius: '6px', background: '#3B82F6', color: '#fff',
                cursor: 'pointer',
                fontWeight: '600',
              }}
            >
              Re-route
            </button>
          </>
        ) : (
          /* Existing saved route: Delete + Save/Re-route */
          <>
            <button
              onClick={handleDelete}
              disabled={deleting}
              style={{
                flex: 1, padding: '8px', fontSize: '13px', border: 'none',
                borderRadius: '6px', background: '#3B82F6', color: '#fff',
                cursor: deleting ? 'not-allowed' : 'pointer',
                fontWeight: '600',
                opacity: deleting ? 0.6 : 1,
              }}
            >
              {deleting ? 'Deleting...' : 'Delete'}
            </button>
            {routeEditDirty ? (
              <button
                onClick={handleSave}
                disabled={saving}
                style={{
                  flex: 1, padding: '8px', fontSize: '13px', border: 'none',
                  borderRadius: '6px', background: '#3B82F6', color: '#fff',
                  cursor: saving ? 'not-allowed' : 'pointer',
                  fontWeight: '600',
                  opacity: saving ? 0.6 : 1,
                }}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            ) : (
              <button
                onClick={handleEdit}
                style={{
                  flex: 1, padding: '8px', fontSize: '13px', border: 'none',
                  borderRadius: '6px', background: '#3B82F6', color: '#fff',
                  cursor: 'pointer',
                  fontWeight: '600',
                }}
              >
                Re-route
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
