/**
 * Unified Overlay Panel component for creating and editing overlays
 */

import React, { useMemo, useState, useEffect } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { latLngToMGRS } from '../utils/mgrsGrid'
import { createApiClient } from '../utils/api'

// Helper to get all overlay types from appConfig
const getAllOverlayTypes = (overlayTypes) => {
  if (!overlayTypes) return []
  return [...(overlayTypes.line || []), ...(overlayTypes.polygon || []), ...(overlayTypes.point || [])]
}

/**
 * OverlayPanel - Unified panel for creating and editing overlays
 * @param {Object} props
 * @param {Function} props.onSave - Save handler for create mode
 * @param {Function} props.onCancel - Cancel handler for create mode
 * @param {Function} props.onEditSave - Save handler for edit mode
 * @param {Function} props.onDelete - Delete handler for edit mode
 */
export function OverlayPanel({ onSave, onCancel, onEditSave, onDelete, onCancelGeometryEdit }) {
  const {
    // Create mode state
    pendingOverlay,
    showOverlayPanel,
    selectedOverlayType,
    // Edit mode state
    selectedOverlay,
    setSelectedOverlay,
    showOverlayEditPanel,
    setShowOverlayEditPanel,
    // Shared state
    overlayForm,
    setOverlayForm,
    appConfig,
    // Pending chat operation editing
    pendingChatOp,
    setPendingChatOp,
    // Geometry editing
    geometryEditMode,
    // Smoothing toggle persistence + refresh
    apiUrl,
    userId,
    triggerMapRefresh,
    addActivity
  } = useGeoAgent()

  const api = useMemo(() => createApiClient(apiUrl, userId), [apiUrl, userId])

  // Determine mode
  const isCreateMode = showOverlayPanel && pendingOverlay
  const isEditMode = showOverlayEditPanel && selectedOverlay
  const isChatOpMode = pendingChatOp !== null && pendingChatOp.op?.op === 'create_overlay'

  // Chat op form state (local state for editing pending chat operations)
  const [chatOpForm, setChatOpForm] = useState({
    name: '',
    designation: '',
    affiliation: 'Friend',
    echelon: '',
    obstacleEffect: '',
    remarks: ''
  })

  // Initialize chat op form when pendingChatOp changes
  useEffect(() => {
    if (isChatOpMode && pendingChatOp?.op) {
      const op = pendingChatOp.op
      const attrs = op.attrs || {}
      setChatOpForm({
        name: op.name || attrs.name || '',
        designation: op.name || attrs.designation || '',
        affiliation: attrs.affiliation || 'Friend',
        echelon: attrs.echelon || '',
        obstacleEffect: attrs.obstacleEffect || '',
        remarks: attrs.remarks || ''
      })
    }
  }, [isChatOpMode, pendingChatOp])

  // Get overlay kind for current mode
  const overlayKind = isChatOpMode
    ? (pendingChatOp?.op?.kind || '')
    : isCreateMode 
      ? selectedOverlayType 
      : (selectedOverlay?.properties?.kind || '')

  // Get all overlay types from config
  const allTypes = getAllOverlayTypes(appConfig?.overlayTypes)
  const typeInfo = allTypes.find(t => t.value === overlayKind)
  const typeLabel = typeInfo?.label || overlayKind.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  // Compute MGRS for overlay centroid (for display)
  const overlayMGRS = useMemo(() => {
    const geometry = isCreateMode 
      ? pendingOverlay?.geometry 
      : selectedOverlay?.geometry
    
    if (!geometry?.coordinates) return ''
    
    let coords
    if (geometry.type === 'Point') {
      coords = geometry.coordinates
    } else if (geometry.type === 'LineString') {
      // Use midpoint
      const midIdx = Math.floor(geometry.coordinates.length / 2)
      coords = geometry.coordinates[midIdx]
    } else if (geometry.type === 'Polygon') {
      // Use first point of ring
      coords = geometry.coordinates[0]?.[0]
    }
    
    if (coords && coords.length >= 2) {
      const [lng, lat] = coords
      return latLngToMGRS(lat, lng, 4)
    }
    return ''
  }, [isCreateMode, pendingOverlay?.geometry, selectedOverlay?.geometry])

  // Don't render if no mode is active
  if (!isCreateMode && !isEditMode && !isChatOpMode) return null
  
  // Use appropriate form based on mode
  const activeForm = isChatOpMode ? chatOpForm : overlayForm
  const setActiveForm = isChatOpMode ? setChatOpForm : setOverlayForm

  // Check if echelon field should be shown
  const showEchelon = ['battle_position', 'strong_point', 'assembly_area'].includes(overlayKind)
  
  // Check if obstacle effect field should be shown
  const showObstacleEffect = ['minefield', 'wire', 'roadblock', 'abatis', 'antitank_ditch'].includes(overlayKind)

  const handleClose = () => {
    if (isChatOpMode) {
      setPendingChatOp(null)
    } else if (isCreateMode) {
      onCancel && onCancel()
    } else {
      // Cancel geometry edit if active
      if (geometryEditMode && onCancelGeometryEdit) {
        onCancelGeometryEdit()
      }
      setShowOverlayEditPanel(false)
      setSelectedOverlay(null)
    }
  }

  const handleSubmit = () => {
    if (isChatOpMode) {
      // Save pending chat operation
      if (pendingChatOp?.onSave) {
        pendingChatOp.onSave(pendingChatOp.index, {
          name: chatOpForm.name || chatOpForm.designation,
          attrs: {
            ...pendingChatOp.op.attrs,
            name: chatOpForm.name,
            designation: chatOpForm.designation,
            affiliation: chatOpForm.affiliation,
            echelon: chatOpForm.echelon,
            obstacleEffect: chatOpForm.obstacleEffect,
            remarks: chatOpForm.remarks
          }
        })
      }
      setPendingChatOp(null)
    } else if (isCreateMode) {
      onSave && onSave()
    } else {
      onEditSave && onEditSave(selectedOverlay)
    }
  }

  const handleDelete = () => {
    if (isEditMode && onDelete) {
      onDelete(selectedOverlay.id)
    }
  }

  // Get placeholder text for name field
  const getNamePlaceholder = () => {
    if (overlayKind === 'phase_line') return 'e.g., PL ALPHA'
    if (overlayKind === 'engagement_area') return 'e.g., EA DOG'
    if (overlayKind === 'battle_position') return 'e.g., BP 22'
    return 'Name'
  }

  // Panel title
  const panelTitle = isChatOpMode
    ? `Edit Pending ${typeLabel}`
    : isCreateMode 
      ? `New ${typeLabel}` 
      : 'Edit Overlay'

  return (
    <div className="edit-panel overlay-panel">
      <div className="edit-panel-header">
        <h3>{panelTitle}</h3>
        <button onClick={handleClose}>×</button>
      </div>
      <div className="edit-panel-content">
        {/* Type field (edit mode only, disabled) */}
        {isEditMode && (
          <div className="edit-field">
            <label>Type</label>
            <input type="text" value={typeLabel} disabled />
          </div>
        )}

        {/* Name / Designation */}
        <div className="edit-field">
          <label>Name / Designation</label>
          <input 
            type="text" 
            value={activeForm.designation || activeForm.name}
            onChange={(e) => setActiveForm({ 
              ...activeForm, 
              designation: e.target.value,
              name: e.target.value 
            })}
            placeholder={(isCreateMode || isChatOpMode) ? getNamePlaceholder() : ''}
          />
        </div>

        {/* Affiliation */}
        <div className="edit-field">
          <label>Affiliation</label>
          <select 
            value={activeForm.affiliation}
            onChange={(e) => setActiveForm({ ...activeForm, affiliation: e.target.value })}
          >
            <option value="Friend">Friend</option>
            <option value="Hostile">Hostile</option>
            <option value="Neutral">Neutral</option>
            <option value="Unknown">Unknown</option>
          </select>
        </div>

        {/* Echelon (conditional) */}
        {showEchelon && (
          <div className="edit-field">
            <label>Echelon</label>
            <select 
              value={activeForm.echelon}
              onChange={(e) => setActiveForm({ ...activeForm, echelon: e.target.value })}
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
          <div className="edit-field">
            <label>Obstacle Effect</label>
            <select 
              value={activeForm.obstacleEffect}
              onChange={(e) => setActiveForm({ ...activeForm, obstacleEffect: e.target.value })}
            >
              <option value="">--</option>
              <option value="block">Block</option>
              <option value="turn">Turn</option>
              <option value="fix">Fix</option>
              <option value="disrupt">Disrupt</option>
            </select>
          </div>
        )}

        {/* Location (MGRS) - not for chat op mode since geometry is already set */}
        {overlayMGRS && !isChatOpMode && (
          <div className="edit-field">
            <label>Location</label>
            <input type="text" value={overlayMGRS} disabled />
          </div>
        )}

        {/* Line/area smoothing — edit-mode display choice: paint the
            stated vertices as straight segments (default) or densified
            through the shared Catmull-Rom spline (the same smoothing
            the axis-of-advance arrows use). Persists immediately:
            entity-graph features carry it as the `smoothing` node
            field; legacy overlay rows carry attrs.smoothing. The
            stated geometry itself is never modified. */}
        {isEditMode && selectedOverlay?.geometry
          && selectedOverlay.geometry.type !== 'Point' && (
          <div className="edit-field">
            <label>Line smoothing</label>
            <select
              value={selectedOverlay?.properties?.smoothing
                || selectedOverlay?.properties?.attrs?.smoothing || ''}
              onChange={async (e) => {
                const v = e.target.value || null
                try {
                  const props = selectedOverlay?.properties || {}
                  if (props.source === 'entity_graph') {
                    const { graphApi } = await import('../utils/graphApi')
                    if (v) await graphApi.putNodeField(props.id, 'smoothing', v, userId)
                    else await graphApi.deleteNodeField(props.id, 'smoothing')
                  } else {
                    await api.updateOverlay(props.overlayId || props.id, {
                      attrs: { ...(props.attrs || {}), smoothing: v },
                    })
                  }
                  setSelectedOverlay({
                    ...selectedOverlay,
                    properties: { ...props, smoothing: v },
                  })
                  triggerMapRefresh && triggerMapRefresh()
                } catch (err) {
                  addActivity && addActivity(
                    `Smoothing change failed: ${err.message}`, 'error')
                }
              }}
            >
              <option value="">Segments (as stated)</option>
              <option value="bezier">Smoothed (spline)</option>
            </select>
          </div>
        )}

        {/* Remarks */}
        <div className="edit-field">
          <label>Remarks</label>
          <textarea
            value={activeForm.remarks}
            onChange={(e) => setActiveForm({ ...activeForm, remarks: e.target.value })}
            placeholder={(isCreateMode || isChatOpMode) ? 'Additional notes...' : ''}
            rows={2}
          />
        </div>

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
              <button className="save-btn" onClick={handleSubmit}>
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
export { OverlayPanel as OverlayCreatePanel }
export { OverlayPanel as OverlayEditPanel }
