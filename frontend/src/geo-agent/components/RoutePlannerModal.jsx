/**
 * RoutePlannerModal — route mode selection with preference controls.
 * User picks a mode, adjusts optional preferences, then confirms.
 */

import React, { useState } from 'react'

const ROUTE_MODES = [
  {
    mode: 'on_road',
    label: 'On Road',
    desc: 'Follow existing roads and highways',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19L8 5" /><path d="M16 5l4 14" /><path d="M12 5v14" />
      </svg>
    ),
  },
  {
    mode: 'off_road',
    label: 'Off Road',
    desc: 'Cross-country through open terrain',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 20L8 8l4 6 4-10 6 16" />
      </svg>
    ),
  },
  {
    mode: 'mixed',
    label: 'Mixed',
    desc: 'Roads when available, terrain when needed',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19L8 5" /><path d="M16 5l4 14" />
        <path d="M9 12c1-2 3-2 4 0s3 2 4 0" />
      </svg>
    ),
  },
]

const TERRAIN_OPTIONS = [
  { value: 'tree_cover', label: 'Forest' },
  //{ value: 'shrubland', label: 'Shrubland' },
  { value: 'grassland', label: 'Grassland' },
  { value: 'cropland', label: 'Cropland' },
  { value: 'built_up', label: 'Built-up' },
  //{ value: 'bare_sparse', label: 'Bare/Sparse' },
  //{ value: 'snow_ice', label: 'Snow/Ice' },
  //{ value: 'water', label: 'Water' },
  //{ value: 'wetland', label: 'Wetland' },
]

const DEFAULT_PREFS = {
  slope_weight: 1.0,
  threat_weight: 1.0,
  concealment_weight: 0.0,
  // Backend routing/weather.py honors this (RoutePreferences
  // weather_weight); the knob was missing from this UI until the
  // cloud-map unification port.
  weather_weight: 0.0,
  max_slope_pct: 58,
  preferred_terrain: [],
  avoid_terrain: [],
  rate_of_advance: '',
}

/** Reusable range slider with label + value */
function PrefSlider({ label, value, min, max, step, onChange, hint }) {
  return (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
        <span style={{ fontSize: '12px', color: '#ccc' }}>{label}</span>
        <span style={{ fontSize: '12px', color: '#3B82F6', fontWeight: '600', minWidth: '32px', textAlign: 'right' }}>
          {value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: '100%', accentColor: '#3B82F6' }}
      />
      {hint && (
        <div style={{ fontSize: '10px', color: '#666', marginTop: '2px' }}>{hint}</div>
      )}
    </div>
  )
}

/** Pill toggle for terrain type preferences */
function TerrainPills({ label, selected, onToggle, color }) {
  return (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ fontSize: '12px', color: '#ccc', marginBottom: '6px' }}>{label}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
        {TERRAIN_OPTIONS.map(({ value, label: tLabel }) => {
          const active = selected.includes(value)
          return (
            <button
              key={value}
              onClick={() => onToggle(value)}
              style={{
                padding: '3px 8px',
                fontSize: '11px',
                border: `1px solid ${active ? color : '#444'}`,
                borderRadius: '12px',
                background: active ? `${color}22` : 'transparent',
                color: active ? color : '#888',
                cursor: 'pointer',
                transition: 'all 0.15s',
                fontWeight: active ? '600' : '400',
              }}
            >
              {tLabel}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * @param {Object} props
 * @param {boolean} props.open
 * @param {Function} props.onClose
 * @param {Function} props.onConfirm - (mode, preferences) => void
 */
export function RoutePlannerModal({ open, onClose, onConfirm }) {
  const [selectedMode, setSelectedMode] = useState(null)
  const [prefs, setPrefs] = useState({ ...DEFAULT_PREFS })

  if (!open) return null

  const updatePref = (key, val) => setPrefs(prev => ({ ...prev, [key]: val }))

  const toggleTerrain = (list, value) => {
    setPrefs(prev => {
      const current = prev[list]
      const other = list === 'preferred_terrain' ? 'avoid_terrain' : 'preferred_terrain'
      // Remove from opposite list if present
      const otherList = prev[other].filter(v => v !== value)
      const updated = current.includes(value)
        ? current.filter(v => v !== value)
        : [...current, value]
      return { ...prev, [list]: updated, [other]: otherList }
    })
  }

  const handleConfirm = () => {
    if (!selectedMode) return
    onConfirm(selectedMode, { ...prefs })
  }

  const handleClose = () => {
    onClose()
  }

  // Which prefs matter for this mode
  const showTerrainPrefs = selectedMode === 'off_road' || selectedMode === 'mixed'
  const showSlopePrefs = selectedMode === 'off_road' || selectedMode === 'mixed'
  const showConcealPrefs = selectedMode === 'off_road' || selectedMode === 'mixed'
  const showThreatPrefs = !!selectedMode

  return (
    <div
      style={{
        position: 'fixed',
        top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(0, 0, 0, 0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2000,
      }}
      onClick={handleClose}
    >
      <div
        style={{
          background: '#1e1e1e',
          borderRadius: '12px',
          padding: '24px',
          width: '380px',
          maxHeight: '85vh',
          overflowY: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          border: '1px solid #333',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <h3 style={{ margin: '0 0 4px 0', color: '#fff', fontSize: '16px', fontWeight: '600' }}>
          Plan Route
        </h3>
        <p style={{ margin: '0 0 16px 0', color: '#888', fontSize: '13px' }}>
          {selectedMode
            ? 'Adjust preferences, then click Plan to start.'
            : 'Select a route type to configure preferences.'}
        </p>

        {/* Mode cards */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {ROUTE_MODES.map(({ mode, label, desc, icon }) => {
            const active = selectedMode === mode
            return (
              <button
                key={mode}
                onClick={() => setSelectedMode(active ? null : mode)}
                style={{
                  padding: '12px 14px',
                  fontSize: '14px',
                  border: `1px solid ${active ? '#3B82F6' : '#444'}`,
                  borderRadius: '8px',
                  background: active ? '#1a2240' : '#2a2a3e',
                  color: '#fff',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'all 0.15s',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                }}
                onMouseEnter={(e) => {
                  if (!active) {
                    e.currentTarget.style.background = '#3a3a5e'
                    e.currentTarget.style.borderColor = '#666'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    e.currentTarget.style.background = '#2a2a3e'
                    e.currentTarget.style.borderColor = '#444'
                  }
                }}
              >
                <span style={{
                  width: '28px', height: '28px',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  borderRadius: '6px',
                  background: active ? '#3B82F633' : '#333',
                  color: active ? '#3B82F6' : '#aaa',
                  flexShrink: 0,
                }}>
                  {icon}
                </span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: '600', marginBottom: '1px' }}>{label}</div>
                  <div style={{ fontSize: '11px', color: '#888', fontWeight: '400' }}>{desc}</div>
                </div>
                {active && (
                  <span style={{ color: '#3B82F6', fontSize: '16px', flexShrink: 0 }}>&#10003;</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Preferences panel — slides open when a mode is selected */}
        {selectedMode && (
          <div style={{
            marginTop: '16px',
            padding: '14px',
            background: '#161622',
            borderRadius: '8px',
            border: '1px solid #2a2a3e',
          }}>
            <div style={{
              fontSize: '12px', color: '#aaa', fontWeight: '600',
              textTransform: 'uppercase', letterSpacing: '0.5px',
              marginBottom: '12px',
            }}>
              Preferences
            </div>

            {showThreatPrefs && (
              <PrefSlider
                label="Threat Avoidance"
                value={prefs.threat_weight}
                min={0} max={3} step={0.1}
                onChange={(v) => updatePref('threat_weight', v)}
                hint="0 = ignore threats, 1 = default, 3 = strongly avoid"
              />
            )}

            {showSlopePrefs && (
              <>
                <PrefSlider
                  label="Slope Penalty"
                  value={prefs.slope_weight}
                  min={0} max={3} step={0.1}
                  onChange={(v) => updatePref('slope_weight', v)}
                  hint="0 = ignore slope, 1 = default, 3 = strongly avoid steep"
                />
                <PrefSlider
                  label="Max Slope %"
                  value={prefs.max_slope_pct}
                  min={10} max={84} step={1}
                  onChange={(v) => updatePref('max_slope_pct', v)}
                  hint="Tiles steeper than this are blocked"
                />
              </>
            )}

            {showConcealPrefs && (
              <PrefSlider
                label="Concealment Preference"
                value={prefs.concealment_weight}
                min={0} max={2} step={0.1}
                onChange={(v) => updatePref('concealment_weight', v)}
                hint="0 = don't care, 1 = prefer cover, 2 = strongly prefer"
              />
            )}

            <PrefSlider
              label="Weather Routing"
              value={prefs.weather_weight}
              min={0} max={3} step={0.1}
              onChange={(v) => updatePref('weather_weight', v)}
              hint="0 = off, 1 = factor weather into route, 2+ = heavy penalty for bad weather"
            />


            {showTerrainPrefs && (
              <>
                <TerrainPills
                  label="Prefer Terrain"
                  selected={prefs.preferred_terrain}
                  onToggle={(v) => toggleTerrain('preferred_terrain', v)}
                  color="#3B82F6"
                />
                <TerrainPills
                  label="Avoid Terrain"
                  selected={prefs.avoid_terrain}
                  onToggle={(v) => toggleTerrain('avoid_terrain', v)}
                  color="#60A5FA"
                />
              </>
            )}

            {/* Rate of Advance */}
            <div style={{ marginBottom: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', color: '#ccc' }}>Rate of Advance (mph)</span>
              </div>
              <input
                type="number"
                min="0"
                step="0.1"
                placeholder="e.g. 5"
                value={prefs.rate_of_advance}
                onChange={(e) => updatePref('rate_of_advance', e.target.value)}
                style={{
                  width: '100%',
                  padding: '6px 10px',
                  fontSize: '13px',
                  background: '#1a1a2e',
                  border: '1px solid #444',
                  borderRadius: '6px',
                  color: '#fff',
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
              <div style={{ fontSize: '10px', color: '#666', marginTop: '2px' }}>
                Speed of movement — used to estimate time of march
              </div>
            </div>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
          <button
            onClick={handleClose}
            style={{
              flex: 1,
              padding: '10px',
              fontSize: '13px',
              border: 'none',
              borderRadius: '6px',
              background: '#333',
              color: '#aaa',
              cursor: 'pointer',
              fontWeight: '500',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!selectedMode}
            style={{
              flex: 1,
              padding: '10px',
              fontSize: '13px',
              border: 'none',
              borderRadius: '6px',
              background: selectedMode ? '#3B82F6' : '#333',
              color: selectedMode ? '#fff' : '#666',
              cursor: selectedMode ? 'pointer' : 'not-allowed',
              fontWeight: '600',
              transition: 'all 0.15s',
            }}
          >
            Plan Route
          </button>
        </div>
      </div>
    </div>
  )
}
