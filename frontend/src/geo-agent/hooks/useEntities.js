/**
 * Hook for entity CRUD operations
 */

import { useCallback } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'
import { generateMilUnitSidc } from '../utils/sidc'

/**
 * Hook providing entity CRUD operations
 * @returns {Object} Entity operation methods
 */
export function useEntities() {
  const {
    apiUrl,
    mapId,
    userId,
    addActivity,
    setShowEditPanel,
    setSelectedEntity,
    setShowCreatePanel,
    setPendingLocation,
    setPlacementMode,
    setCreateForm,
    setEditForm,
    appConfig,
    triggerMapRefresh,
    requestConfirm
  } = useGeoAgent()

  // userId is appended to POST /entities so the geo-agent backend records
  // the row's `created_by` (multi-user attribution).
  const api = createApiClient(apiUrl, userId)

  /**
   * Update entity position
   */
  const updateEntityPosition = useCallback(async (entityId, newCoords) => {
    try {
      await api.updateEntity(entityId, {
        geom: {
          type: 'Point',
          coordinates: newCoords
        }
      })
      addActivity(`Moved entity ${entityId.slice(0, 8)}...`, 'success')
      return true
    } catch (err) {
      addActivity(`Failed to move entity: ${err.message}`, 'error')
      return false
    }
  }, [api, addActivity])

  /**
   * Update entity attributes
   */
  const updateEntityAttrs = useCallback(async (entityId, attrs) => {
    try {
      await api.updateEntity(entityId, { attrs })
      addActivity(`Updated entity ${entityId.slice(0, 8)}...`, 'success')
      setShowEditPanel(false)
      setSelectedEntity(null)
      return true
    } catch (err) {
      addActivity(`Failed to update entity: ${err.message}`, 'error')
      return false
    }
  }, [api, addActivity, setShowEditPanel, setSelectedEntity])

  /**
   * Delete an entity
   */
  const deleteEntity = useCallback(async (entityId) => {
    if (!(await requestConfirm({ title: 'Delete Entity', message: 'Delete this entity from the map? This cannot be undone.', confirmLabel: 'Delete' }))) return false
    try {
      await api.deleteEntity(entityId)
      addActivity(`Deleted entity ${entityId.slice(0, 8)}...`, 'success')
      setShowEditPanel(false)
      setSelectedEntity(null)
      return true
    } catch (err) {
      addActivity(`Failed to delete entity: ${err.message}`, 'error')
      return false
    }
  }, [api, addActivity, setShowEditPanel, setSelectedEntity, requestConfirm])

  /**
   * Create a new military unit entity
   */
  const createNewEntity = useCallback(async (coords, formData) => {
    try {
      // Generate SIDC from form selections including unit type and symbol set
      const sidc = generateMilUnitSidc(
        formData.affiliation, 
        formData.echelon, 
        formData.status, 
        formData.unitType,
        appConfig?.sidc,
        formData.symbolSet || '10'  // Include symbol set, default to Land Unit
      )
      
      const attrs = {
        name: formData.name,
        affiliation: formData.affiliation,
        echelon: formData.echelon,
        status: formData.status,
        unitType: formData.unitType,
        symbolSet: formData.symbolSet || '10',
        symbolName: formData.symbolName || '',
        sidc: sidc,
        // Source token for the tactical-overlay sidebar's Units row
        // (which governs live_oob + manual together) and for
        // _filterBySource. NEVER 'live_oob' — that bucket is the sync
        // endpoint's transactional-REPLACE key, and a manually placed
        // unit tagged live_oob would be deleted by the next OOB push.
        source: 'manual'
      }
      
      const entity = await api.createEntity(mapId, {
        kind: 'mil_unit',
        geom: { type: 'Point', coordinates: coords },
        attrs: attrs
      })
      
      addActivity(`Created military unit: ${attrs.name || 'Unnamed'}`, 'success')
      setShowCreatePanel(false)
      setPendingLocation(null)
      setPlacementMode(false)

      // Reset create form to defaults (no symbol selected)
      setCreateForm({
        name: '',
        affiliation: 'Friend',
        echelon: 'Battalion',
        status: 'Present',
        unitType: '',
        symbolSet: '10'
      })

      // Pull the new mil_unit into the source NOW. Without this the unit
      // only appears on the next moveend-driven loadMapState (analyst
      // sees nothing for ~seconds after hitting Create, thinks it failed,
      // and tries again). Same pattern useCustomSymbols.handleMapDrop
      // uses for custom-symbol drops.
      triggerMapRefresh?.()

      return entity
    } catch (err) {
      addActivity(`Failed to create entity: ${err.message}`, 'error')
      return null
    }
  }, [api, mapId, addActivity, setShowCreatePanel, setPendingLocation, setPlacementMode, setCreateForm, appConfig, triggerMapRefresh])

  /**
   * Select an entity for editing
   */
  const selectEntity = useCallback((feature) => {
    setSelectedEntity(feature)
    const props = feature.properties || {}
    
    setEditForm({
      name: props.name || '',
      kind: props.kind || '',
      // For mil units, extract key editable fields with sensible defaults
      affiliation: props.affiliation || 'Friend',
      echelon: props.echelon || 'Battalion',
      status: props.status || 'Present',
      unitType: props.unitType || '',  // Use stored entity code, empty if not set
      symbolSet: props.symbolSet || '10',  // Symbol set for correct SIDC generation
      symbolName: props.symbolName || '',  // Symbol display name
      // Full attrs for advanced editing
      attrs: { ...props }
    })
    
    setShowEditPanel(true)
  }, [setSelectedEntity, setShowEditPanel, setEditForm])

  return {
    updateEntityPosition,
    updateEntityAttrs,
    deleteEntity,
    createNewEntity,
    selectEntity
  }
}
