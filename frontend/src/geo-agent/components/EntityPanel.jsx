/**
 * Unified Entity Panel component for creating and editing military units
 */

import React, { useEffect, useRef, useCallback, useState, useMemo } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { 
  generateMilUnitSidc, 
  detectAffiliationFromName,
  detectEchelonFromName
} from '../utils/sidc'
import { createMilSymbol, createMilsymbolPreview } from '../utils/symbols'
import { latLngToMGRS } from '../utils/mgrsGrid'

/**
 * EntityPanel - Unified panel for creating and editing military units
 * @param {Object} props
 * @param {Function} props.onCreate - Create handler (coords, formData) => entity
 * @param {Function} props.onSave - Save handler (id, attrs) => void
 * @param {Function} props.onDelete - Delete handler (id) => void
 */
export function EntityPanel({ onCreate, onSave, onDelete }) {
  const {
    // Create mode state
    pendingLocation,
    setPendingLocation,
    showCreatePanel,
    setShowCreatePanel,
    createForm,
    setCreateForm,
    // Edit mode state
    selectedEntity,
    setSelectedEntity,
    showEditPanel,
    setShowEditPanel,
    editForm,
    setEditForm,
    // Shared state
    setShowSymbolPicker,
    setSymbolPickerCallback,
    appConfig,
    findBestSymbolMatch,
    searchSymbols,
    // Pending chat operation editing
    pendingChatOp,
    setPendingChatOp
  } = useGeoAgent()

  // Determine mode
  const isCreateMode = showCreatePanel && pendingLocation
  const isEditMode = showEditPanel && selectedEntity
  const isChatOpMode = pendingChatOp !== null && pendingChatOp.op?.op === 'create_entity'
  const isMilUnitSelected = isEditMode && selectedEntity?.properties?.kind === 'mil_unit'

  // Chat op form state (local state for editing pending chat operations)
  const [chatOpForm, setChatOpForm] = useState({
    name: '',
    affiliation: 'Friend',
    echelon: 'Battalion',
    status: 'Present',
    unitType: '',
    symbolSet: '10',
    symbolName: ''
  })

  // Initialize chat op form when pendingChatOp changes
  useEffect(() => {
    if (isChatOpMode && pendingChatOp?.op?.attrs) {
      const attrs = pendingChatOp.op.attrs
      setChatOpForm({
        name: attrs.name || '',
        affiliation: attrs.affiliation || 'Friend',
        echelon: attrs.echelon || 'Battalion',
        status: attrs.status || 'Present',
        unitType: attrs.unitType || '',
        symbolSet: attrs.symbolSet || '10',
        symbolName: attrs.symbolName || ''
      })
    }
  }, [isChatOpMode, pendingChatOp])

  // Use appropriate form based on mode
  const form = isChatOpMode ? chatOpForm : (isCreateMode ? createForm : editForm)
  const setForm = isChatOpMode ? setChatOpForm : (isCreateMode ? setCreateForm : setEditForm)

  // Symbol suggestions state (only used in create mode)
  const [symbolSuggestions, setSymbolSuggestions] = useState([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const nameInputRef = useRef(null)

  // Track if user manually changed fields (to not override with auto-detection)
  const manualSymbol = useRef(false)
  const manualAffiliation = useRef(false)
  const manualEchelon = useRef(false)

  // Compute MGRS for coordinates
  const coordsMGRS = useMemo(() => {
    if (isCreateMode && pendingLocation) {
      const [lng, lat] = pendingLocation
      return latLngToMGRS(lat, lng, 4)
    }
    if (isEditMode && selectedEntity?.geometry?.coordinates) {
      const coords = selectedEntity.geometry.coordinates
      if (coords.length >= 2) {
        const [lng, lat] = coords
        return latLngToMGRS(lat, lng, 4)
      }
    }
    return ''
  }, [isCreateMode, isEditMode, pendingLocation, selectedEntity?.geometry?.coordinates])

  // Get coordinates for display (lat/long only)
  const displayLatLng = useMemo(() => {
    if (isCreateMode && pendingLocation) {
      return `${pendingLocation[1].toFixed(4)}°, ${pendingLocation[0].toFixed(4)}°`
    }
    if (isEditMode && selectedEntity?.geometry?.coordinates) {
      const coords = selectedEntity.geometry.coordinates
      if (coords.length >= 2) {
        return `${coords[1]?.toFixed(4)}°, ${coords[0]?.toFixed(4)}°`
      }
    }
    return ''
  }, [isCreateMode, isEditMode, pendingLocation, selectedEntity?.geometry?.coordinates])

  // Auto-detect unit type, affiliation, and echelon from name as user types (create mode only)
  useEffect(() => {
    if (!isCreateMode || !createForm.name) return
    
    const updates = {}
    
    // Detect affiliation (using keywords from backend config)
    if (!manualAffiliation.current) {
      const detectedAffiliation = detectAffiliationFromName(createForm.name, appConfig?.keywords)
      if (detectedAffiliation && createForm.affiliation !== detectedAffiliation) {
        updates.affiliation = detectedAffiliation
      }
    }
    
    // Detect echelon (using keywords from backend config)
    if (!manualEchelon.current) {
      const detectedEchelon = detectEchelonFromName(createForm.name, appConfig?.keywords)
      if (detectedEchelon && createForm.echelon !== detectedEchelon) {
        updates.echelon = detectedEchelon
      }
    }
    
    // Apply affiliation/echelon updates immediately
    if (Object.keys(updates).length > 0) {
      setCreateForm(prev => ({ ...prev, ...updates }))
    }
  }, [isCreateMode, createForm.name, createForm.affiliation, createForm.echelon, setCreateForm, appConfig])

  // Detect unit type via backend API (debounced, create mode only)
  useEffect(() => {
    if (!isCreateMode || !createForm.name || manualSymbol.current) return
    
    const detectUnitType = async () => {
      const bestMatch = await findBestSymbolMatch(createForm.name)
      if (bestMatch && bestMatch.code) {
        const updates = {}
        if (createForm.unitType !== bestMatch.code) {
          updates.unitType = bestMatch.code
        }
        if (bestMatch.symbolSet && createForm.symbolSet !== bestMatch.symbolSet) {
          updates.symbolSet = bestMatch.symbolSet
        }
        const displayName = bestMatch.entitySubtype || bestMatch.entityType || bestMatch.entity || bestMatch.name
        if (displayName && createForm.symbolName !== displayName) {
          updates.symbolName = displayName
        }
        if (Object.keys(updates).length > 0) {
          setCreateForm(prev => ({ ...prev, ...updates }))
        }
      }
    }
    
    const timer = setTimeout(detectUnitType, 300)
    return () => clearTimeout(timer)
  }, [isCreateMode, createForm.name, createForm.unitType, createForm.symbolSet, createForm.symbolName, setCreateForm, findBestSymbolMatch])
  
  // Reset manual flags when panel closes/opens
  useEffect(() => {
    if (showCreatePanel) {
      manualSymbol.current = false
      manualAffiliation.current = false
      manualEchelon.current = false
    }
  }, [showCreatePanel])

  // Detect when user manually selects a symbol from the picker
  useEffect(() => {
    if (createForm._manualSymbol) {
      manualSymbol.current = true
      setCreateForm(prev => {
        const { _manualSymbol, ...rest } = prev
        return rest
      })
    }
  }, [createForm._manualSymbol, setCreateForm])

  // Search symbols for suggestions when name changes (create mode only)
  useEffect(() => {
    if (!isCreateMode || !createForm.name || createForm.name.length < 2) {
      setSymbolSuggestions([])
      return
    }

    const searchForSuggestions = async () => {
      setIsSearching(true)
      const { results } = await searchSymbols(createForm.name, null, 5)
      setSymbolSuggestions(results)
      setIsSearching(false)
      if (results.length > 0) {
        setShowSuggestions(true)
      }
    }

    const timer = setTimeout(searchForSuggestions, 200)
    return () => clearTimeout(timer)
  }, [isCreateMode, createForm.name, searchSymbols])

  // Handle selecting a suggestion
  const handleSelectSuggestion = useCallback((symbol) => {
    manualSymbol.current = true
    const displayName = symbol.entitySubtype || symbol.entityType || symbol.entity || symbol.name
    setCreateForm(prev => ({
      ...prev,
      unitType: symbol.code,
      symbolSet: symbol.symbolSet || '10',
      symbolName: displayName
    }))
    setShowSuggestions(false)
  }, [setCreateForm])

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (nameInputRef.current && !nameInputRef.current.contains(e.target)) {
        const suggestionsEl = document.querySelector('.symbol-suggestions')
        if (!suggestionsEl || !suggestionsEl.contains(e.target)) {
          setShowSuggestions(false)
        }
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Don't render if no mode is active
  if (!isCreateMode && !isEditMode && !isChatOpMode) return null

  // For edit mode, only show mil unit form if it's a mil unit
  const showMilUnitForm = isCreateMode || isMilUnitSelected || isChatOpMode

  const handleClose = () => {
    if (isChatOpMode) {
      setPendingChatOp(null)
    } else if (isCreateMode) {
      setShowCreatePanel(false)
      setPendingLocation(null)
      manualSymbol.current = false
      manualAffiliation.current = false
      manualEchelon.current = false
      setSymbolSuggestions([])
      setShowSuggestions(false)
      setCreateForm({
        name: '',
        affiliation: 'Friend',
        echelon: 'Battalion',
        status: 'Present',
        unitType: '',
        symbolSet: '10',
        symbolName: ''
      })
    } else {
      setShowEditPanel(false)
      setSelectedEntity(null)
    }
  }

  const handleSubmit = async () => {
    if (isChatOpMode) {
      // Save pending chat operation
      if (pendingChatOp?.onSave) {
        const newSidc = generateMilUnitSidc(
          chatOpForm.affiliation,
          chatOpForm.echelon,
          chatOpForm.status,
          chatOpForm.unitType,
          appConfig?.sidc,
          chatOpForm.symbolSet || '10'
        )
        pendingChatOp.onSave(pendingChatOp.index, {
          attrs: {
            ...pendingChatOp.op.attrs,
            ...chatOpForm,
            sidc: newSidc
          }
        })
      }
      setPendingChatOp(null)
    } else if (isCreateMode) {
      if (onCreate) {
        await onCreate(pendingLocation, createForm)
      }
    } else if (isEditMode) {
      if (isMilUnitSelected) {
        const newSidc = generateMilUnitSidc(
          editForm.affiliation, 
          editForm.echelon, 
          editForm.status, 
          editForm.unitType,
          appConfig?.sidc,
          editForm.symbolSet || editForm.attrs?.symbolSet || '10'
        )
        const updatedAttrs = { 
          ...editForm.attrs, 
          sidc: newSidc, 
          unitType: editForm.unitType,
          symbolSet: editForm.symbolSet || editForm.attrs?.symbolSet || '10',
          symbolName: editForm.symbolName || editForm.attrs?.symbolName || ''
        }
        if (onSave) onSave(selectedEntity.id, updatedAttrs)
      } else {
        if (onSave) onSave(selectedEntity.id, editForm.attrs)
      }
    }
  }

  const handleDelete = () => {
    if (isEditMode && onDelete) {
      onDelete(selectedEntity.id)
    }
  }

  // Generate SIDC and symbol for preview
  const getSymbolPreview = () => {
    const unitType = form.unitType
    if (!unitType && isCreateMode) return null

    // Edit mode with no fresh symbol pick: render the stored SIDC as-is.
    // The backend stamps OOB-fed mil_units with a complete SIDC in attrs
    // (positions 1=affiliation, 4-9=function, etc.), but those codes
    // don't translate 1:1 into the form's 2525D unitType + symbolSet
    // pair — re-generating via generateMilUnitSidc with an empty
    // unitType produced an "unknown function" icon. Fall through to
    // generateMilUnitSidc only when the user has actively picked a new
    // symbol (unitType set) or this is a Create flow.
    if (!unitType && form.attrs?.sidc) {
      const result = createMilSymbol(form.attrs.sidc, { size: 60 })
      return { sidc: form.attrs.sidc, svgHtml: result?.svg || null }
    }

    const sidc = generateMilUnitSidc(
      form.affiliation,
      form.echelon,
      form.status,
      unitType,
      appConfig?.sidc,
      form.symbolSet || form.attrs?.symbolSet || '10'
    )
    const result = createMilSymbol(sidc, { size: 60 })
    return { sidc, svgHtml: result?.svg || null }
  }

  const symbolPreview = showMilUnitForm ? getSymbolPreview() : null
  const symbolName = form.symbolName || form.attrs?.symbolName

  // Panel title
  const panelTitle = isChatOpMode
    ? 'Edit Pending Unit'
    : isCreateMode 
      ? 'Create Military Unit' 
      : (isMilUnitSelected ? 'Edit Military Unit' : 'Edit Entity')

  return (
    <div className="edit-panel">
      <div className="edit-panel-header">
        <h3>{panelTitle}</h3>
        <button onClick={handleClose}>×</button>
      </div>
      <div className="edit-panel-content">
        {/* Symbol Preview for military units */}
        {showMilUnitForm && (
          <div className="symbol-preview">
            {symbolPreview?.svgHtml ? (
              <>
                <div 
                  className="symbol-preview-icon"
                  dangerouslySetInnerHTML={{ 
                    __html: symbolPreview.svgHtml || '<div class="symbol-placeholder">?</div>' 
                  }}
                />
                {symbolName && (
                  <div className="symbol-name">{symbolName}</div>
                )}
              </>
            ) : (
              <div className="symbol-select-prompt">
                <div className="symbol-placeholder-large">+</div>
                <div className="symbol-prompt-text">Select a symbol</div>
              </div>
            )}
            <button 
              className="browse-symbols-btn"
              onClick={() => {
                // Always use callback pattern - updates the correct form based on mode
                // Wrap in arrow function to prevent React from treating it as functional update
                setSymbolPickerCallback(() => (symbol) => {
                  if (isEditMode) {
                    setEditForm(prev => ({
                      ...prev,
                      unitType: symbol.unitType,
                      symbolSet: symbol.symbolSet,
                      symbolName: symbol.symbolName,
                      attrs: { ...prev.attrs, ...symbol }
                    }))
                  } else {
                    // _manualSymbol flips the manualSymbol ref (effect
                    // above) so the name-based auto-detect effect stops
                    // rewriting unitType/symbolSet. Without it, picking
                    // "Armor/Mechanized" and naming the unit "TEST
                    // ARMOR BN" silently replaced the picked symbol
                    // with the best free-text match for the NAME 300ms
                    // later — the picker choice never survived.
                    setForm(prev => ({ ...prev, ...symbol, _manualSymbol: true }))
                  }
                })
                setShowSymbolPicker(true)
              }}
            >
              {form.unitType ? 'Change Symbol' : 'Select Symbol'}
            </button>
          </div>
        )}
        
        {/* Name field */}
        <div className="edit-field">
          <label>Name</label>
          {isCreateMode ? (
            <div className="name-input-wrapper" ref={nameInputRef}>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm(prev => ({ ...prev, name: e.target.value }))}
                onFocus={() => symbolSuggestions.length > 0 && setShowSuggestions(true)}
                // Escape dismisses the suggestion dropdown — it
                // overlaps the Create button, and without this the
                // analyst's first click only closes the dropdown.
                onKeyDown={(e) => { if (e.key === 'Escape') setShowSuggestions(false) }}
                placeholder="e.g., 1st Armor Battalion"
                autoFocus
              />
              {isSearching && <span className="name-input-spinner"></span>}
              {showSuggestions && symbolSuggestions.length > 0 && (
                <div className="symbol-suggestions">
                  <div className="suggestions-header">
                    <span>Matching Symbols</span>
                    <button onClick={() => setShowSuggestions(false)}>×</button>
                  </div>
                  {symbolSuggestions.map((symbol, idx) => {
                    const svgHtml = createMilsymbolPreview(symbol.code, { 
                      size: 32, 
                      symbolSet: symbol.symbolSet 
                    })
                    const primaryName = symbol.entitySubtype || symbol.entityType || symbol.entity || symbol.name
                    const pathParts = [symbol.entity, symbol.entityType].filter(p => p && p !== primaryName)
                    const categoryPath = pathParts.join(' › ')
                    
                    return (
                      <div
                        key={`${symbol.code}-${idx}`}
                        className="suggestion-item"
                        onClick={() => handleSelectSuggestion(symbol)}
                      >
                        <div 
                          className="suggestion-icon"
                          dangerouslySetInnerHTML={{ 
                            __html: svgHtml || '<div class="symbol-placeholder-sm">?</div>' 
                          }}
                        />
                        <div className="suggestion-info">
                          <div className="suggestion-name">{primaryName}</div>
                          {categoryPath && (
                            <div className="suggestion-path">{categoryPath}</div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          ) : (
            <input 
              type="text" 
              value={form.name}
              onChange={(e) => {
                const val = e.target.value
                if (isEditMode) {
                  setEditForm(prev => ({ ...prev, name: val, attrs: { ...prev.attrs, name: val } }))
                } else {
                  setForm(prev => ({ ...prev, name: val }))
                }
              }}
            />
          )}
        </div>
        
        {/* Mil Unit specific fields - compact grid layout */}
        {showMilUnitForm && (
          <div className="edit-fields-grid">
            <div className="edit-field">
              <label>Affiliation</label>
              <select 
                value={form.affiliation}
                onChange={(e) => {
                  const val = e.target.value
                  if (isEditMode) {
                    setEditForm(prev => ({ ...prev, affiliation: val, attrs: { ...prev.attrs, affiliation: val } }))
                  } else {
                    if (isCreateMode) manualAffiliation.current = true
                    setForm(prev => ({ ...prev, affiliation: val }))
                  }
                }}
              >
                <option value="Friend">Friend</option>
                <option value="Hostile">Hostile</option>
                <option value="Neutral">Neutral</option>
                <option value="Unknown">Unknown</option>
              </select>
            </div>
            <div className="edit-field">
              <label>Echelon</label>
              <select 
                value={form.echelon}
                onChange={(e) => {
                  const val = e.target.value
                  if (isEditMode) {
                    setEditForm(prev => ({ ...prev, echelon: val, attrs: { ...prev.attrs, echelon: val } }))
                  } else {
                    if (isCreateMode) manualEchelon.current = true
                    setForm(prev => ({ ...prev, echelon: val }))
                  }
                }}
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
            <div className="edit-field">
              <label>Status</label>
              <select 
                value={form.status}
                onChange={(e) => {
                  const val = e.target.value
                  if (isEditMode) {
                    setEditForm(prev => ({ ...prev, status: val, attrs: { ...prev.attrs, status: val } }))
                  } else {
                    setForm(prev => ({ ...prev, status: val }))
                  }
                }}
              >
                <option value="Present">Present</option>
                <option value="Planned">Planned</option>
                <option value="Anticipated">Anticipated</option>
                <option value="Known">Known</option>
              </select>
            </div>
          </div>
        )}
        
        {/* Non-mil-unit fields (edit mode only) */}
        {isEditMode && !isMilUnitSelected && (
          <div className="edit-field">
            <label>Kind</label>
            <input type="text" value={editForm.kind} disabled />
          </div>
        )}

        {/* Coordinates - compact single line for create mode, full for edit */}
        {isCreateMode && coordsMGRS && (
          <div className="coordinates-compact">
            <span className="coords-label">Location:</span>
            <span className="coords-value">{coordsMGRS}</span>
          </div>
        )}
        {isEditMode && !isMilUnitSelected && (
          <div className="coordinates-section">
            <label className="coordinates-header">Coordinates</label>
            <div className="edit-field">
              <label>Lat/Long</label>
              <input 
                type="text" 
                value={displayLatLng} 
                disabled 
              />
            </div>
            <div className="edit-field">
              <label>MGRS</label>
              <input 
                type="text" 
                value={coordsMGRS} 
                disabled 
              />
            </div>
          </div>
        )}
        
        {/* Action buttons */}
        <div className="edit-actions">
          {isChatOpMode ? (
            <>
              <button className="cancel-btn" onClick={handleClose}>
                Cancel
              </button>
              <button className="save-btn" onClick={handleSubmit}>
                Save
              </button>
            </>
          ) : isCreateMode ? (
            <>
              <button className="cancel-btn" onClick={handleClose}>
                Cancel
              </button>
              <button 
                className="save-btn"
                onClick={handleSubmit}
                disabled={!form.unitType}
                title={!form.unitType ? 'Please select a symbol first' : ''}
              >
                Create
              </button>
            </>
          ) : (
            <>
              <button className="delete-btn" onClick={handleDelete}>
                Delete
              </button>
              <button className="save-btn" onClick={handleSubmit}>
                Save
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// Re-export for backwards compatibility
export { EntityPanel as CreatePanel }
export { EntityPanel as EditPanel }
