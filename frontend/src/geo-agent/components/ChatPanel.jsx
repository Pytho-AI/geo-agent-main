/**
 * Chat Panel component for natural language map operations
 * 
 * Provides a sidebar chat interface where users can:
 * - Send natural language commands to modify the map
 * - Review proposed operations before approval
 * - Approve or reject pending changes
 */

import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { useChat, MessageType } from '../hooks/useChat'
import { useGeoAgent } from '../GeoAgentProvider'
import { generateMilUnitSidc } from '../utils/sidc'
import { createMilSymbol, createMilsymbolPreview } from '../utils/symbols'
import { latLngToMGRS } from '../utils/mgrsGrid'
import ms from 'milsymbol'

/**
 * Generate a symbol preview SVG for an entity
 */
function getEntitySymbolSvg(attrs, size = 50) {
  try {
    const affiliation = attrs?.affiliation || 'Friend'
    const echelon = attrs?.echelon || 'Battalion'
    const status = attrs?.status || 'Present'
    const unitType = attrs?.unitType || 'unit'
    
    const sidc = generateMilUnitSidc(affiliation, echelon, status, unitType)
    const symbol = new ms.Symbol(sidc, { size })
    return symbol.asSVG()
  } catch (err) {
    console.error('Error generating symbol preview:', err)
    return null
  }
}

/**
 * Range arc SVG icon component for overlay indicators
 */
function RangeArcIcon({ size = 24, className = '' }) {
  return (
    <svg 
      width={size} 
      height={size} 
      viewBox="0 0 24 24" 
      fill="none" 
      stroke="currentColor" 
      strokeWidth="1.5" 
      strokeLinecap="round" 
      strokeLinejoin="round"
      className={className}
      style={{ display: 'inline-block', verticalAlign: 'middle' }}
    >
      <path d="M2 15 A10 10 0 0 1 22 15"/>
      <path d="M4 8 L7 12"/>
      <path d="M12 4 L12 10"/>
      <path d="M20 8 L17 12"/>
    </svg>
  )
}

/**
 * Get overlay icon based on type
 */
function getOverlayIcon(kind) {
  const icons = {
    phase_line: '━━━',
    boundary: '┄┄┄',
    route: '→→→',
    assembly_area: '◻',
    engagement_area: <RangeArcIcon size={20} />,
    objective: '⬭',
    axis_of_advance: '⟹',
    direction_of_attack: '➤'
  }
  return icons[kind] || <RangeArcIcon size={20} />
}

/**
 * Format coordinates for display
 */
function formatCoordinates(geom) {
  if (!geom || !geom.coordinates) return null
  
  if (geom.type === 'Point') {
    const [lon, lat] = geom.coordinates
    const mgrs = latLngToMGRS(lat, lon, 4)
    return { latLng: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`, mgrs }
  } else if (geom.type === 'LineString') {
    const count = geom.coordinates.length
    return { simple: `${count} points` }
  } else if (geom.type === 'Polygon') {
    const count = geom.coordinates[0]?.length || 0
    return { simple: `${count} vertices` }
  }
  return null
}

/**
 * Operation Preview Card - shows detailed info about a single operation
 * @param {Object} op - The operation object
 * @param {boolean} isPending - Whether the operation is pending approval
 * @param {Function} onClick - Click handler for editing (only when pending)
 */
function OperationPreviewCard({ op, isPending, onClick }) {
  // Get symbol for entity operations (create or delete)
  const symbolSvg = useMemo(() => {
    if ((op.kind === 'unit' || op.kind === 'mil_unit') && op.attrs) {
      return getEntitySymbolSvg(op.attrs)
    }
    return null
  }, [op])
  
  // Determine if this operation type is editable
  const isEditable = isPending && (op.op === 'create_entity' || op.op === 'create_overlay')
  
  const handleClick = () => {
    if (isEditable && onClick) {
      onClick()
    }
  }
  
  if (op.op === 'create_entity') {
    const attrs = op.attrs || {}
    const coords = formatCoordinates(op.geom)
    
    return (
      <div 
        className={`op-preview-card ${isEditable ? 'clickable' : ''}`}
        onClick={handleClick}
        title={isEditable ? 'Click to edit' : undefined}
      >
        <div className="op-preview-header">
          {symbolSvg ? (
            <div 
              className="op-symbol-preview"
              dangerouslySetInnerHTML={{ __html: symbolSvg }}
            />
          ) : (
            <div className="op-icon-placeholder">⊕</div>
          )}
          <div className="op-preview-title">
            <span className="op-type-label">New Unit</span>
            <span className="op-name">{attrs.name || 'Unnamed Unit'}</span>
          </div>
          {isEditable && <span className="edit-hint">✎</span>}
        </div>
        <div className="op-preview-details">
          <div className="op-detail-row">
            <span className="op-detail-label">Affiliation</span>
            <span className={`op-detail-value affiliation-${(attrs.affiliation || 'Friend').toLowerCase()}`}>
              {attrs.affiliation || 'Friend'}
            </span>
          </div>
          <div className="op-detail-row">
            <span className="op-detail-label">Echelon</span>
            <span className="op-detail-value">{attrs.echelon || 'Battalion'}</span>
          </div>
          <div className="op-detail-row">
            <span className="op-detail-label">Type</span>
            <span className="op-detail-value">{attrs.symbolName || attrs.unitType || 'unit'}</span>
          </div>
          {coords && (
            <div className="op-detail-row">
              <span className="op-detail-label">Location</span>
              <span className="op-detail-value op-coords">
                {coords.simple || <>{coords.latLng}<br/>{coords.mgrs}</>}
              </span>
            </div>
          )}
        </div>
      </div>
    )
  }
  
  if (op.op === 'create_overlay') {
    const coords = formatCoordinates(op.geom)
    const kindLabel = (op.kind || 'overlay').replace(/_/g, ' ')
    
    return (
      <div 
        className={`op-preview-card overlay ${isEditable ? 'clickable' : ''}`}
        onClick={handleClick}
        title={isEditable ? 'Click to edit' : undefined}
      >
        <div className="op-preview-header">
          <div className="op-overlay-icon">{getOverlayIcon(op.kind)}</div>
          <div className="op-preview-title">
            <span className="op-type-label">New {kindLabel}</span>
            <span className="op-name">{op.name || 'Unnamed'}</span>
          </div>
          {isEditable && <span className="edit-hint">✎</span>}
        </div>
        <div className="op-preview-details">
          <div className="op-detail-row">
            <span className="op-detail-label">Type</span>
            <span className="op-detail-value">{kindLabel}</span>
          </div>
          {coords && (
            <div className="op-detail-row">
              <span className="op-detail-label">Geometry</span>
              <span className="op-detail-value op-coords">
                {coords.simple || <>{coords.latLng}<br/>{coords.mgrs}</>}
              </span>
            </div>
          )}
          {op.attrs?.affiliation && (
            <div className="op-detail-row">
              <span className="op-detail-label">Affiliation</span>
              <span className={`op-detail-value affiliation-${op.attrs.affiliation.toLowerCase()}`}>
                {op.attrs.affiliation}
              </span>
            </div>
          )}
        </div>
      </div>
    )
  }
  
  // Delete entity
  if (op.op === 'delete_entity') {
    const attrs = op.attrs || {}
    const name = attrs.name || `Entity ${op.id?.substring(0, 8) || 'Unknown'}`
    
    return (
      <div className="op-preview-card delete">
        <div className="op-preview-header">
          {symbolSvg ? (
            <div 
              className="op-symbol-preview"
              dangerouslySetInnerHTML={{ __html: symbolSvg }}
            />
          ) : (
            <div className="op-icon-placeholder delete-icon">✕</div>
          )}
          <div className="op-preview-title">
            <span className="op-type-label">Delete Entity</span>
            <span className="op-name">{name}</span>
          </div>
        </div>
        <div className="op-preview-details">
          {attrs.affiliation && (
            <div className="op-detail-row">
              <span className="op-detail-label">Affiliation</span>
              <span className={`op-detail-value affiliation-${attrs.affiliation.toLowerCase()}`}>
                {attrs.affiliation}
              </span>
            </div>
          )}
          {attrs.echelon && (
            <div className="op-detail-row">
              <span className="op-detail-label">Echelon</span>
              <span className="op-detail-value">{attrs.echelon}</span>
            </div>
          )}
          {(attrs.symbolName || attrs.unitType) && (
            <div className="op-detail-row">
              <span className="op-detail-label">Type</span>
              <span className="op-detail-value">{attrs.symbolName || attrs.unitType}</span>
            </div>
          )}
        </div>
      </div>
    )
  }
  
  // Delete overlay
  if (op.op === 'delete_overlay') {
    const shortId = op.id ? op.id.substring(0, 8) : 'Unknown'
    
    return (
      <div className="op-preview-card delete">
        <div className="op-preview-header">
          <div className="op-icon-placeholder delete-icon">✕</div>
          <div className="op-preview-title">
            <span className="op-type-label">Delete Overlay</span>
            <span className="op-name">Overlay {shortId}</span>
          </div>
        </div>
        <div className="op-preview-details">
          <div className="op-detail-row">
            <span className="op-detail-label">Action</span>
            <span className="op-detail-value">Remove from map</span>
          </div>
          <div className="op-detail-row">
            <span className="op-detail-label">ID</span>
            <span className="op-detail-value op-id">{op.id || 'Unknown'}</span>
          </div>
        </div>
      </div>
    )
  }
  
  // Move entity
  if (op.op === 'move_entity') {
    const shortId = op.id ? op.id.substring(0, 8) + '...' : 'Unknown'
    const coords = formatCoordinates(op.geom)
    
    return (
      <div className="op-preview-card move">
        <div className="op-preview-header">
          <div className="op-icon-move">↗</div>
          <div className="op-preview-title">
            <span className="op-type-label">Move Entity</span>
            <span className="op-name op-id">{shortId}</span>
          </div>
        </div>
        {coords && (
          <div className="op-preview-details">
            <div className="op-detail-row">
              <span className="op-detail-label">New Location</span>
              <span className="op-detail-value op-coords">
                {coords.simple || <>{coords.latLng}<br/>{coords.mgrs}</>}
              </span>
            </div>
          </div>
        )}
      </div>
    )
  }
  
  // Update entity
  if (op.op === 'update_entity') {
    const shortId = op.id ? op.id.substring(0, 8) + '...' : 'Unknown'
    const attrs = op.attrs || {}
    const attrKeys = Object.keys(attrs)
    
    return (
      <div className="op-preview-card update">
        <div className="op-preview-header">
          <div className="op-icon-update">✎</div>
          <div className="op-preview-title">
            <span className="op-type-label">Update Entity</span>
            <span className="op-name op-id">{shortId}</span>
          </div>
        </div>
        {attrKeys.length > 0 && (
          <div className="op-preview-details">
            {attrKeys.slice(0, 3).map(key => (
              <div className="op-detail-row" key={key}>
                <span className="op-detail-label">{key}</span>
                <span className="op-detail-value">{String(attrs[key])}</span>
              </div>
            ))}
            {attrKeys.length > 3 && (
              <div className="op-detail-row">
                <span className="op-detail-label">+ {attrKeys.length - 3} more</span>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }
  
  // Fallback for any other operation types
  return (
    <div className="op-preview-card simple">
      <div className="op-preview-header">
        <div className="op-icon-generic">●</div>
        <div className="op-preview-title">
          <span className="op-type-label">{op.op.replace(/_/g, ' ')}</span>
        </div>
      </div>
    </div>
  )
}

/**
 * Inline Entity Editor - embedded editor for pending entity operations
 */
function InlineEntityEditor({ op, onSave, onCancel }) {
  const { appConfig, setShowSymbolPicker, setSymbolPickerCallback, searchSymbols } = useGeoAgent()
  
  const [form, setForm] = useState({
    name: op.attrs?.name || '',
    affiliation: op.attrs?.affiliation || 'Friend',
    echelon: op.attrs?.echelon || 'Battalion',
    status: op.attrs?.status || 'Present',
    unitType: op.attrs?.unitType || '',
    symbolSet: op.attrs?.symbolSet || '10',
    symbolName: op.attrs?.symbolName || ''
  })
  
  // Symbol suggestions state
  const [symbolSuggestions, setSymbolSuggestions] = useState([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const nameInputRef = useRef(null)

  // Search symbols for suggestions when name changes
  useEffect(() => {
    if (!form.name || form.name.length < 2) {
      setSymbolSuggestions([])
      return
    }

    const searchForSuggestions = async () => {
      setIsSearching(true)
      const { results } = await searchSymbols(form.name, null, 5)
      setSymbolSuggestions(results)
      setIsSearching(false)
      if (results.length > 0) {
        setShowSuggestions(true)
      }
    }

    const timer = setTimeout(searchForSuggestions, 200)
    return () => clearTimeout(timer)
  }, [form.name, searchSymbols])

  // Handle selecting a suggestion
  const handleSelectSuggestion = useCallback((symbol) => {
    const displayName = symbol.entitySubtype || symbol.entityType || symbol.entity || symbol.name
    setForm(prev => ({
      ...prev,
      unitType: symbol.code,
      symbolSet: symbol.symbolSet || '10',
      symbolName: displayName
    }))
    setShowSuggestions(false)
  }, [])

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (nameInputRef.current && !nameInputRef.current.contains(e.target)) {
        const suggestionsEl = e.target.closest('.symbol-suggestions')
        if (!suggestionsEl) {
          setShowSuggestions(false)
        }
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Generate symbol preview
  const symbolPreview = useMemo(() => {
    if (!form.unitType) return null
    const sidc = generateMilUnitSidc(
      form.affiliation,
      form.echelon,
      form.status,
      form.unitType,
      appConfig?.sidc,
      form.symbolSet || '10'
    )
    const result = createMilSymbol(sidc, { size: 50 })
    return { sidc, svgHtml: result?.svg || null }
  }, [form.affiliation, form.echelon, form.status, form.unitType, form.symbolSet, appConfig])

  // Coordinates from operation geometry
  const coords = useMemo(() => {
    if (!op.geom || op.geom.type !== 'Point') return null
    const [lon, lat] = op.geom.coordinates
    const mgrs = latLngToMGRS(lat, lon, 4)
    return { latLng: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`, mgrs }
  }, [op.geom])

  const handleSave = () => {
    const newSidc = generateMilUnitSidc(
      form.affiliation,
      form.echelon,
      form.status,
      form.unitType,
      appConfig?.sidc,
      form.symbolSet || '10'
    )
    onSave({
      attrs: {
        ...op.attrs,
        ...form,
        sidc: newSidc
      }
    })
  }

  return (
    <div className="inline-entity-editor">
      {/* Symbol Preview */}
      <div className="inline-editor-symbol">
        {symbolPreview?.svgHtml ? (
          <div 
            className="inline-symbol-preview"
            dangerouslySetInnerHTML={{ __html: symbolPreview.svgHtml }}
          />
        ) : (
          <div className="inline-symbol-placeholder">+</div>
        )}
        <button 
          className="inline-change-symbol-btn"
          onClick={() => {
            setSymbolPickerCallback(() => (symbol) => {
              setForm(prev => ({ 
                ...prev, 
                unitType: symbol.unitType,
                symbolSet: symbol.symbolSet,
                symbolName: symbol.symbolName
              }))
            })
            setShowSymbolPicker(true)
          }}
        >
          {form.unitType ? 'Change' : 'Select Symbol'}
        </button>
      </div>

      {/* Name Field */}
      <div className="inline-editor-field">
        <label>Name</label>
        <div className="inline-name-input-wrapper" ref={nameInputRef}>
          <input 
            type="text"
            value={form.name}
            onChange={(e) => setForm(prev => ({ ...prev, name: e.target.value }))}
            onFocus={() => symbolSuggestions.length > 0 && setShowSuggestions(true)}
            placeholder="e.g., 1st Armor Battalion"
          />
          {isSearching && <span className="inline-input-spinner"></span>}
          {showSuggestions && symbolSuggestions.length > 0 && (
            <div className="inline-symbol-suggestions">
              {symbolSuggestions.map((symbol, idx) => {
                const svgHtml = createMilsymbolPreview(symbol.code, { 
                  size: 28, 
                  symbolSet: symbol.symbolSet 
                })
                const primaryName = symbol.entitySubtype || symbol.entityType || symbol.entity || symbol.name
                
                return (
                  <div
                    key={`${symbol.code}-${idx}`}
                    className="inline-suggestion-item"
                    onClick={() => handleSelectSuggestion(symbol)}
                  >
                    <div 
                      className="inline-suggestion-icon"
                      dangerouslySetInnerHTML={{ __html: svgHtml || '' }}
                    />
                    <span className="inline-suggestion-name">{primaryName}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Affiliation */}
      <div className="inline-editor-field">
        <label>Affiliation</label>
        <select 
          value={form.affiliation}
          onChange={(e) => setForm(prev => ({ ...prev, affiliation: e.target.value }))}
        >
          <option value="Friend">Friend</option>
          <option value="Hostile">Hostile</option>
          <option value="Neutral">Neutral</option>
          <option value="Unknown">Unknown</option>
        </select>
      </div>

      {/* Echelon */}
      <div className="inline-editor-field">
        <label>Echelon</label>
        <select 
          value={form.echelon}
          onChange={(e) => setForm(prev => ({ ...prev, echelon: e.target.value }))}
        >
          <option value="Team">Team</option>
          <option value="Squad">Squad</option>
          <option value="Section">Section</option>
          <option value="Platoon">Platoon</option>
          <option value="Company">Company</option>
          <option value="Battalion">Battalion</option>
          <option value="Regiment">Regiment</option>
          <option value="Brigade">Brigade</option>
          <option value="Division">Division</option>
          <option value="Corps">Corps</option>
          <option value="Army">Army</option>
        </select>
      </div>

      {/* Status */}
      <div className="inline-editor-field">
        <label>Status</label>
        <select 
          value={form.status}
          onChange={(e) => setForm(prev => ({ ...prev, status: e.target.value }))}
        >
          <option value="Present">Present</option>
          <option value="Planned">Planned</option>
          <option value="Anticipated">Anticipated</option>
          <option value="Known">Known</option>
        </select>
      </div>

      {/* Location (read-only) */}
      {coords && (
        <div className="inline-editor-field inline-coords">
          <label>Location</label>
          <div className="inline-coords-value">
            <span>{coords.latLng}</span>
            <span className="inline-mgrs">{coords.mgrs}</span>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="inline-editor-actions">
        <button className="inline-save-btn" onClick={handleSave}>Save</button>
        <button className="inline-cancel-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}

/**
 * Inline Overlay Editor - embedded editor for pending overlay operations
 */
function InlineOverlayEditor({ op, onSave, onCancel }) {
  const [form, setForm] = useState({
    name: op.name || op.attrs?.name || '',
    designation: op.name || op.attrs?.designation || '',
    affiliation: op.attrs?.affiliation || 'Friend',
    echelon: op.attrs?.echelon || '',
    obstacleEffect: op.attrs?.obstacleEffect || '',
    remarks: op.attrs?.remarks || ''
  })

  const overlayKind = op.kind || ''
  const kindLabel = overlayKind.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  // Check if echelon field should be shown
  const showEchelon = ['battle_position', 'strong_point', 'assembly_area'].includes(overlayKind)
  
  // Check if obstacle effect field should be shown
  const showObstacleEffect = ['minefield', 'wire', 'roadblock', 'abatis', 'antitank_ditch'].includes(overlayKind)

  // Get placeholder text for name field
  const getNamePlaceholder = () => {
    if (overlayKind === 'phase_line') return 'e.g., PL ALPHA'
    if (overlayKind === 'engagement_area') return 'e.g., EA DOG'
    if (overlayKind === 'battle_position') return 'e.g., BP 22'
    if (overlayKind === 'objective') return 'e.g., OBJ TIGER'
    return `e.g., ${kindLabel.toUpperCase()}`
  }

  // Coordinates from operation geometry
  const coords = useMemo(() => {
    if (!op.geom) return null
    
    let coordPoint
    if (op.geom.type === 'Point') {
      coordPoint = op.geom.coordinates
    } else if (op.geom.type === 'LineString') {
      // Use midpoint
      const midIdx = Math.floor(op.geom.coordinates.length / 2)
      coordPoint = op.geom.coordinates[midIdx]
    } else if (op.geom.type === 'Polygon') {
      // Use first point
      coordPoint = op.geom.coordinates[0]?.[0]
    }
    
    if (coordPoint && coordPoint.length >= 2) {
      const [lon, lat] = coordPoint
      const mgrs = latLngToMGRS(lat, lon, 4)
      return { 
        latLng: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`, 
        mgrs,
        geomType: op.geom.type,
        pointCount: op.geom.type === 'LineString' 
          ? op.geom.coordinates.length 
          : op.geom.type === 'Polygon' 
            ? op.geom.coordinates[0]?.length 
            : 1
      }
    }
    return null
  }, [op.geom])

  const handleSave = () => {
    onSave({
      name: form.name || form.designation,
      attrs: {
        ...op.attrs,
        name: form.name,
        designation: form.designation,
        affiliation: form.affiliation,
        echelon: form.echelon,
        obstacleEffect: form.obstacleEffect,
        remarks: form.remarks
      }
    })
  }

  return (
    <div className="inline-entity-editor inline-overlay-editor">
      {/* Type indicator */}
      <div className="inline-overlay-type">
        <span className="inline-overlay-icon">{getOverlayIcon(overlayKind)}</span>
        <span className="inline-overlay-label">{kindLabel}</span>
        {coords && (
          <span className="inline-overlay-geom">
            {coords.geomType === 'LineString' && `${coords.pointCount} pts`}
            {coords.geomType === 'Polygon' && `${coords.pointCount} vertices`}
          </span>
        )}
      </div>

      {/* Name / Designation */}
      <div className="inline-editor-field">
        <label>Name / Designation</label>
        <input 
          type="text"
          value={form.designation || form.name}
          onChange={(e) => setForm(prev => ({ 
            ...prev, 
            name: e.target.value,
            designation: e.target.value 
          }))}
          placeholder={getNamePlaceholder()}
        />
      </div>

      {/* Affiliation */}
      <div className="inline-editor-field">
        <label>Affiliation</label>
        <select 
          value={form.affiliation}
          onChange={(e) => setForm(prev => ({ ...prev, affiliation: e.target.value }))}
        >
          <option value="Friend">Friend</option>
          <option value="Hostile">Hostile</option>
          <option value="Neutral">Neutral</option>
          <option value="Unknown">Unknown</option>
        </select>
      </div>

      {/* Echelon (conditional) */}
      {showEchelon && (
        <div className="inline-editor-field">
          <label>Echelon</label>
          <select 
            value={form.echelon}
            onChange={(e) => setForm(prev => ({ ...prev, echelon: e.target.value }))}
          >
            <option value="">--</option>
            <option value="Team">Team</option>
            <option value="Squad">Squad</option>
            <option value="Platoon">Platoon</option>
            <option value="Company">Company</option>
            <option value="Battalion">Battalion</option>
            <option value="Brigade">Brigade</option>
          </select>
        </div>
      )}

      {/* Obstacle Effect (conditional) */}
      {showObstacleEffect && (
        <div className="inline-editor-field">
          <label>Obstacle Effect</label>
          <select 
            value={form.obstacleEffect}
            onChange={(e) => setForm(prev => ({ ...prev, obstacleEffect: e.target.value }))}
          >
            <option value="">--</option>
            <option value="block">Block</option>
            <option value="turn">Turn</option>
            <option value="fix">Fix</option>
            <option value="disrupt">Disrupt</option>
          </select>
        </div>
      )}

      {/* Location (read-only) */}
      {coords && (
        <div className="inline-editor-field inline-coords">
          <label>Location</label>
          <div className="inline-coords-value">
            <span>{coords.latLng}</span>
            <span className="inline-mgrs">{coords.mgrs}</span>
          </div>
        </div>
      )}

      {/* Remarks */}
      <div className="inline-editor-field">
        <label>Remarks</label>
        <textarea 
          value={form.remarks}
          onChange={(e) => setForm(prev => ({ ...prev, remarks: e.target.value }))}
          placeholder="Additional notes..."
          rows={2}
        />
      </div>

      {/* Actions */}
      <div className="inline-editor-actions">
        <button className="inline-save-btn" onClick={handleSave}>Save</button>
        <button className="inline-cancel-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}

/**
 * Message component
 */
function ChatMessage({ message, onApprove, onReject, onEditOp, onSaveOp, isLoading }) {
  const { type, content, proposedOps, approved, rejected } = message
  
  // Track which operation is being edited inline
  const [editingOpIndex, setEditingOpIndex] = useState(null)
  
  const isUser = type === MessageType.USER
  const isPending = type === MessageType.PENDING && !approved && !rejected
  const isSuccess = type === MessageType.SUCCESS || approved
  const isError = type === MessageType.ERROR

  // Handle clicking on an operation card to edit inline
  const handleOpClick = (idx, op) => {
    if (isPending && (op.op === 'create_entity' || op.op === 'create_overlay')) {
      setEditingOpIndex(idx)
    }
  }

  // Handle saving inline edits
  const handleInlineSave = (idx, updates) => {
    if (onSaveOp) {
      onSaveOp(idx, updates)
    }
    setEditingOpIndex(null)
  }

  // Handle canceling inline edit
  const handleInlineCancel = () => {
    setEditingOpIndex(null)
  }
  
  return (
    <div className={`chat-message ${isUser ? 'user' : 'assistant'} ${isSuccess ? 'success' : ''} ${isError ? 'error' : ''} ${isPending ? 'pending' : ''}`}>
      <div className="message-content">
        {content}
      </div>
      
      {/* Show detailed operation previews for pending and approved messages */}
      {proposedOps && proposedOps.length > 0 && (
        <div className="proposed-ops">
          <div className="ops-preview-list">
            {proposedOps.map((op, idx) => (
              <React.Fragment key={idx}>
                {editingOpIndex === idx ? (
                  // Show inline editor for this operation
                  op.op === 'create_entity' ? (
                    <InlineEntityEditor
                      op={op}
                      onSave={(updates) => handleInlineSave(idx, updates)}
                      onCancel={handleInlineCancel}
                    />
                  ) : op.op === 'create_overlay' ? (
                    <InlineOverlayEditor
                      op={op}
                      onSave={(updates) => handleInlineSave(idx, updates)}
                      onCancel={handleInlineCancel}
                    />
                  ) : (
                    <OperationPreviewCard 
                      op={op} 
                      isPending={isPending}
                      onClick={() => handleOpClick(idx, op)}
                    />
                  )
                ) : (
                  // Show preview card
                  <OperationPreviewCard 
                    op={op} 
                    isPending={isPending && editingOpIndex === null}
                    onClick={() => handleOpClick(idx, op)}
                  />
                )}
              </React.Fragment>
            ))}
          </div>
          
          {/* Show approval buttons only when pending and not editing */}
          {isPending && editingOpIndex === null && (
            <div className="approval-buttons">
              <button 
                className="approve-btn"
                onClick={onApprove}
                disabled={isLoading}
              >
                {isLoading ? 'Processing...' : 'Confirm'}
              </button>
              <button 
                className="reject-btn"
                onClick={onReject}
                disabled={isLoading}
              >
                Cancel
              </button>
            </div>
          )}
          
          {/* Show done badge after approval */}
          {approved && (
            <div className="done-badge">Done</div>
          )}
        </div>
      )}
      
    </div>
  )
}

/**
 * Main Chat Panel component
 */
export function ChatPanel() {
  const { setShowChatPanel, triggerMapRefresh } = useGeoAgent()
  const {
    messages,
    isLoading,
    hasPendingApproval,
    sendMessage,
    approveOps,
    rejectOps,
    updatePendingOp,
    clearChat
  } = useChat()
  
  const [inputValue, setInputValue] = useState('')
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  
  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])
  
  // Handle send message
  const handleSend = async () => {
    if (!inputValue.trim() || isLoading) return
    
    const text = inputValue.trim()
    setInputValue('')
    await sendMessage(text)
  }
  
  // Handle key press
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }
  
  // Auto-resize textarea based on content
  const handleInputChange = (e) => {
    setInputValue(e.target.value)
    
    // Reset height to auto to get the correct scrollHeight
    const textarea = e.target
    textarea.style.height = 'auto'
    // Set height to scrollHeight, capped at max-height by CSS
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
  }
  
  // Reset textarea height when cleared
  useEffect(() => {
    if (inputRef.current && inputValue === '') {
      inputRef.current.style.height = 'auto'
    }
  }, [inputValue])
  
  // Handle approve
  const handleApprove = async () => {
    const success = await approveOps()
    if (success) {
      triggerMapRefresh()
    }
  }
  
  // Handle reject
  const handleReject = () => {
    rejectOps()
  }
  
  // Handle edit operation - now handled inline in ChatMessage
  const handleEditOp = (index, op) => {
    // Inline editing is now the default behavior
    // This handler is kept for compatibility but may be removed
  }
  
  // Handle saving inline edits to pending operations
  const handleSaveOp = (index, updates) => {
    updatePendingOp(index, updates)
  }
  
  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h3>Map Agent</h3>
        <div className="chat-header-actions">
          <button 
            className="close-btn" 
            onClick={() => setShowChatPanel(false)}
            title="Close chat"
          >
            ×
          </button>
        </div>
      </div>
      
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-welcome">
            <div className="chat-welcome-tip">
              Pan the map to your area of interest first
            </div>
            <p>Then ask me to modify the map. Try:</p>
            <ul>
              <li>"Add a friendly infantry battalion"</li>
              <li>"Create an enemy armor company"</li>
              <li>"Draw an antitank ditch"</li>
              <li>"Describe this terrain"</li>
            </ul>
          </div>
        ) : (
          messages.map(message => (
            <ChatMessage
              key={message.id}
              message={message}
              onApprove={handleApprove}
              onReject={handleReject}
              onEditOp={handleEditOp}
              onSaveOp={handleSaveOp}
              isLoading={isLoading}
            />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      
      <div className="chat-input-container">
        <div className="chat-input-wrapper">
          <textarea
            ref={inputRef}
            className="chat-input"
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={hasPendingApproval ? "Approve or reject pending changes..." : "Type a command or paste a scenario..."}
            disabled={isLoading || hasPendingApproval}
            rows={1}
          />
          <button
            className="send-btn"
            onClick={handleSend}
            disabled={!inputValue.trim() || isLoading || hasPendingApproval}
            title="Send"
          >
            {isLoading ? (
              <svg className="send-spinner" width="18" height="18" viewBox="0 0 18 18">
                <circle className="send-spinner-track" cx="9" cy="9" r="7" />
                <circle className="send-spinner-arc" cx="9" cy="9" r="7" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8 3L8 13M8 3L4 7M8 3L12 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            )}
          </button>
        </div>
      </div>
      
    </div>
  )
}
