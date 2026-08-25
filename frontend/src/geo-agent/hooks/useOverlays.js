/**
 * Hook for overlay CRUD operations
 */

import { useCallback } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'
import { updateSidcAffiliation } from '../utils/sidc'

// Helper to get overlay type info from appConfig
const getOverlayTypeInfo = (kind, overlayTypes) => {
  if (!overlayTypes) return null
  const allTypes = [...(overlayTypes.line || []), ...(overlayTypes.polygon || []), ...(overlayTypes.point || [])]
  return allTypes.find(t => t.value === kind)
}

// Helper to get point count from geometry
const getPointCount = (geometry) => {
  if (!geometry) return 0
  if (geometry.type === 'Point') return 1
  if (geometry.type === 'LineString') return geometry.coordinates?.length || 0
  if (geometry.type === 'Polygon') return geometry.coordinates?.[0]?.length - 1 || 0 // -1 for closing point
  return 0
}

// Helper to validate minimum points for overlay type
const validateMinPoints = (geometry, overlayType, overlayTypes) => {
  const typeInfo = getOverlayTypeInfo(overlayType, overlayTypes)
  // Geometry-aware default: point kinds need 1, polygons 3, lines 2.
  // The old flat default of 2 made every point kind unsaveable — a
  // drawn Point always counts 1, so the save silently failed
  // validation with only an activity toast.
  const isPointKind = (overlayTypes?.point || []).some(t => t.value === overlayType)
  const isPolygonKind = (overlayTypes?.polygon || []).some(t => t.value === overlayType)
  const minPoints = typeInfo?.minPoints || (isPointKind ? 1 : isPolygonKind ? 3 : 2)
  const pointCount = getPointCount(geometry)
  
  if (pointCount < minPoints) {
    return {
      valid: false,
      message: `${typeInfo?.label || overlayType} requires at least ${minPoints} points. You drew ${pointCount}.`
    }
  }
  return { valid: true }
}

/**
 * Hook providing overlay CRUD operations
 * @returns {Object} Overlay operation methods
 */
export function useOverlays() {
  const {
    apiUrl,
    mapId,
    addActivity,
    drawRef,
    mapRef,
    setShowOverlayEditPanel,
    setSelectedOverlay,
    setPendingOverlay,
    setShowOverlayPanel,
    overlayForm,
    setOverlayForm,
    setOverlayDrawMode,
    setShowOverlayToolbar,
    overlayDrawModeRef,
    setOriginalOverlayGeometry,
    appConfig,
    userId,
    // Geometry editing state
    setGeometryEditMode,
    geometryEditModeRef,
    requestConfirm
  } = useGeoAgent()

  // userId is appended to POST /overlays so the geo-agent backend records
  // the row's `created_by` (multi-user attribution).
  const api = createApiClient(apiUrl, userId)

  /**
   * Get SIDC for an overlay type with affiliation
   */
  const getSidcForOverlayType = useCallback((kind, affiliation = 'Friend') => {
    // Use overlay types from backend config, fallback to hardcoded
    const typeInfo = getOverlayTypeInfo(kind, appConfig?.overlayTypes)
    if (!typeInfo?.sidc) return null
    // Update affiliation in SIDC (position 3, 0-indexed, using backend sidc config)
    return updateSidcAffiliation(typeInfo.sidc, affiliation, appConfig?.sidc)
  }, [appConfig])

  /**
   * Create a new overlay
   */
  const createOverlay = useCallback(async (geom, kind, attrs) => {
    try {
      // Get SIDC code for this overlay type
      const sidc = getSidcForOverlayType(kind, attrs.affiliation)
      
      const overlayAttrs = {
        ...attrs,
        sidc: sidc,  // Include SIDC for MIL-STD-2525 rendering
        // Analyst-drawn tag — same convention as placed units
        // (useEntities): NEVER a pipeline source token, so the sync
        // endpoint's transactional replace can't delete hand-drawn
        // graphics, and _filterBySource / isPipelineOwned classify
        // them as analyst-authored.
        source: 'manual'
      }
      
      const overlay = await api.createOverlay(mapId, {
        kind: kind,
        name: attrs.name || attrs.designation || kind,
        geom: geom,
        attrs: overlayAttrs
      })
      
      addActivity(`Created ${kind}: ${attrs.name || attrs.designation || 'Unnamed'}`, 'success')
      return overlay
    } catch (err) {
      addActivity(`Failed to create overlay: ${err.message}`, 'error')
      return null
    }
  }, [api, mapId, addActivity, getSidcForOverlayType])

  /**
   * Update an existing overlay
   */
  const updateOverlay = useCallback(async (overlayId, data) => {
    try {
      await api.updateOverlay(overlayId, data)
      addActivity(`Updated overlay ${overlayId.slice(0, 8)}...`, 'success')
      setShowOverlayEditPanel(false)
      setSelectedOverlay(null)
      return true
    } catch (err) {
      addActivity(`Failed to update overlay: ${err.message}`, 'error')
      return false
    }
  }, [api, addActivity, setShowOverlayEditPanel, setSelectedOverlay])

  /**
   * Delete an overlay
   */
  const deleteOverlay = useCallback(async (overlayId) => {
    if (!(await requestConfirm({ title: 'Delete Overlay', message: 'Delete this overlay from the map? This cannot be undone.', confirmLabel: 'Delete' }))) return false
    try {
      await api.deleteOverlay(overlayId)
      addActivity(`Deleted overlay ${overlayId.slice(0, 8)}...`, 'success')
      setShowOverlayEditPanel(false)
      setSelectedOverlay(null)
      return true
    } catch (err) {
      addActivity(`Failed to delete overlay: ${err.message}`, 'error')
      return false
    }
  }, [api, addActivity, setShowOverlayEditPanel, setSelectedOverlay, requestConfirm])

  /**
   * Handle completed drawing from MapboxDraw
   */
  const handleDrawCreate = useCallback((e) => {
    if (!overlayDrawModeRef.current || !e.features || e.features.length === 0) return
    
    const feature = e.features[0]
    setPendingOverlay({
      geometry: feature.geometry,
      drawId: feature.id
    })
    setShowOverlayPanel(true)
  }, [overlayDrawModeRef, setPendingOverlay, setShowOverlayPanel])

  /**
   * Save pending overlay to backend
   */
  const savePendingOverlay = useCallback(async (pendingOverlay, overlayForm, selectedOverlayType, loadMapState) => {
    if (!pendingOverlay) return null

    // Validate minimum points for this overlay type
    const validation = validateMinPoints(pendingOverlay.geometry, selectedOverlayType, appConfig?.overlayTypes)
    if (!validation.valid) {
      addActivity(validation.message, 'error')
      return null
    }

    const attrs = {
      ...overlayForm,
      affiliation: overlayForm.affiliation
    }

    const overlay = await createOverlay(pendingOverlay.geometry, selectedOverlayType, attrs)
    
    if (overlay) {
      // Remove from draw control
      if (drawRef.current && pendingOverlay.drawId) {
        drawRef.current.delete(pendingOverlay.drawId)
      }
      
      // Clear the drawing preview layer
      if (mapRef.current) {
        const previewSource = mapRef.current.getSource('drawing-preview')
        if (previewSource) {
          previewSource.setData({ type: 'FeatureCollection', features: [] })
        }
      }
      
      // Reset state
      setPendingOverlay(null)
      setShowOverlayPanel(false)
      setOverlayForm({
        name: '',
        designation: '',
        affiliation: 'Friend',
        echelon: '',
        obstacleEffect: '',
        remarks: ''
      })
      setOverlayDrawMode(false)
      setShowOverlayToolbar(false)
      
      // Reload map data if callback provided
      if (loadMapState) {
        loadMapState()
      }
      
      return overlay
    }
    return null
  }, [createOverlay, drawRef, mapRef, setPendingOverlay, setShowOverlayPanel, setOverlayForm, setOverlayDrawMode, setShowOverlayToolbar, appConfig, addActivity])

  /**
   * Cancel overlay creation completely (exits draw mode)
   * Used when clicking the Cancel button
   */
  const cancelOverlayCreation = useCallback((pendingOverlay) => {
    if (drawRef.current && pendingOverlay?.drawId) {
      drawRef.current.delete(pendingOverlay.drawId)
    }
    
    // Clear the drawing preview layer
    if (mapRef.current) {
      const previewSource = mapRef.current.getSource('drawing-preview')
      if (previewSource) {
        previewSource.setData({ type: 'FeatureCollection', features: [] })
      }
    }
    
    setPendingOverlay(null)
    setShowOverlayPanel(false)
    setOverlayForm({
      name: '',
      designation: '',
      affiliation: 'Friend',
      echelon: '',
      obstacleEffect: '',
      remarks: ''
    })
    // Fully exit draw mode
    setOverlayDrawMode(false)
    setShowOverlayToolbar(false)
    if (drawRef.current) {
      drawRef.current.changeMode('simple_select')
    }
  }, [drawRef, mapRef, setPendingOverlay, setShowOverlayPanel, setOverlayForm, setOverlayDrawMode, setShowOverlayToolbar])

  /**
   * Restart overlay drawing (clears current drawing but stays in draw mode)
   * Used when pressing ESC
   */
  const restartOverlayDraw = useCallback((pendingOverlay, selectedOverlayType) => {
    if (drawRef.current && pendingOverlay?.drawId) {
      drawRef.current.delete(pendingOverlay.drawId)
    }
    
    // Clear the drawing preview layer
    if (mapRef.current) {
      const previewSource = mapRef.current.getSource('drawing-preview')
      if (previewSource) {
        previewSource.setData({ type: 'FeatureCollection', features: [] })
      }
    }
    
    setPendingOverlay(null)
    setShowOverlayPanel(false)
    setOverlayForm({
      name: '',
      designation: '',
      affiliation: 'Friend',
      echelon: '',
      obstacleEffect: '',
      remarks: ''
    })
    
    // Restart draw mode with the same overlay type
    if (selectedOverlayType && drawRef.current && appConfig?.overlayTypes) {
      const overlayTypes = appConfig.overlayTypes
      const isLine = (overlayTypes.line || []).some(t => t.value === selectedOverlayType)
      const isPoint = (overlayTypes.point || []).some(t => t.value === selectedOverlayType)
      
      if (isPoint) {
        drawRef.current.changeMode('draw_point')
      } else if (isLine) {
        drawRef.current.changeMode('draw_line_string')
      } else {
        drawRef.current.changeMode('draw_polygon')
      }
    }
  }, [drawRef, mapRef, setPendingOverlay, setShowOverlayPanel, setOverlayForm, appConfig])

  // Affiliation colors for tactical graphics (MIL-STD-2525)
  const AFFILIATION_COLORS = {
    Friend: '#0000FF',   // Blue
    Hostile: '#FF0000',  // Red
    Neutral: '#00FF00',  // Green
    Unknown: '#FFFF00'   // Yellow
  }

  /**
   * Start overlay drawing mode
   */
  const startOverlayDraw = useCallback((overlayType, setSelectedOverlayType) => {
    setSelectedOverlayType(overlayType)
    setOverlayDrawMode(true)
    
    // Use overlay types from backend config
    const overlayTypes = appConfig?.overlayTypes
    if (!overlayTypes) {
      addActivity('Config not loaded yet', 'error')
      return
    }
    
    // Get color based on current affiliation (default to Friend/Blue)
    const currentAffiliation = overlayForm?.affiliation || 'Friend'
    const strokeColor = AFFILIATION_COLORS[currentAffiliation] || '#0000FF'
    const fillColor = strokeColor
    
    // Update draw layer styles on the map to match the affiliation
    if (mapRef.current) {
      try {
        // Update line style
        if (mapRef.current.getLayer('gl-draw-line')) {
          mapRef.current.setPaintProperty('gl-draw-line', 'line-color', strokeColor)
        }
        // Update polygon styles
        if (mapRef.current.getLayer('gl-draw-polygon-fill')) {
          mapRef.current.setPaintProperty('gl-draw-polygon-fill', 'fill-color', fillColor)
        }
        if (mapRef.current.getLayer('gl-draw-polygon-stroke')) {
          mapRef.current.setPaintProperty('gl-draw-polygon-stroke', 'line-color', strokeColor)
        }
        // Update vertex styles
        if (mapRef.current.getLayer('gl-draw-polygon-and-line-vertex-active')) {
          mapRef.current.setPaintProperty('gl-draw-polygon-and-line-vertex-active', 'circle-stroke-color', strokeColor)
        }
        // Update point style
        if (mapRef.current.getLayer('gl-draw-point')) {
          mapRef.current.setPaintProperty('gl-draw-point', 'circle-color', strokeColor)
        }
      } catch (err) {
        // Layer styling failed, continue with defaults
      }
    }
    
    if (drawRef.current) {
      // Determine geometry type from overlay type
      const isLine = (overlayTypes.line || []).some(t => t.value === overlayType)
      const isPoint = (overlayTypes.point || []).some(t => t.value === overlayType)
      
      if (isPoint) {
        drawRef.current.changeMode('draw_point')
      } else if (isLine) {
        drawRef.current.changeMode('draw_line_string')
      } else {
        drawRef.current.changeMode('draw_polygon')
      }
    }
  }, [drawRef, mapRef, setOverlayDrawMode, appConfig, overlayForm])

  /**
   * Exit overlay draw mode
   */
  const exitOverlayDrawMode = useCallback(() => {
    setOverlayDrawMode(false)
    setShowOverlayToolbar(false)
    if (drawRef.current) {
      drawRef.current.changeMode('simple_select')
      drawRef.current.deleteAll()
    }
  }, [drawRef, setOverlayDrawMode, setShowOverlayToolbar])

  /**
   * Select overlay for editing (opens edit panel)
   */
  const selectOverlayForEdit = useCallback((feature, originalGeometry = null) => {
    setSelectedOverlay(feature)
    const props = feature.properties || {}
    setOverlayForm({
      name: props.name || '',
      designation: props.designation || '',
      affiliation: props.affiliation || 'Friend',
      echelon: props.echelon || '',
      obstacleEffect: props.obstacleEffect || props.obstacle_effect || '',
      remarks: props.remarks || ''
    })
    // Store original geometry for move operations
    if (originalGeometry) {
      setOriginalOverlayGeometry(originalGeometry)
    }
    setShowOverlayEditPanel(true)
  }, [setSelectedOverlay, setOverlayForm, setShowOverlayEditPanel, setOriginalOverlayGeometry])

  /**
   * Move an overlay by translating its geometry
   * Used for drag-and-drop moving of overlays
   * 
   * @param {string} overlayId - The overlay ID
   * @param {number} deltaLngOrNewLng - Delta longitude (if useDelta=true) or new center longitude
   * @param {number} deltaLatOrNewLat - Delta latitude (if useDelta=true) or new center latitude
   * @param {Object} props - Feature properties containing originalGeometry
   * @param {boolean} useDelta - If true, first two params are delta values; if false, they're new center position
   */
  const moveOverlay = useCallback(async (overlayId, deltaLngOrNewLng, deltaLatOrNewLat, props, useDelta = false) => {
    try {
      // Get original geometry from props
      let originalGeometry = null
      if (props?.originalGeometry) {
        try {
          originalGeometry = JSON.parse(props.originalGeometry)
        } catch (e) {
          addActivity('Could not parse overlay geometry for move', 'error')
          return false
        }
      }
      
      if (!originalGeometry) {
        addActivity('No geometry available for move', 'error')
        return false
      }

      let deltaLng, deltaLat

      if (useDelta) {
        // Delta values passed directly
        deltaLng = deltaLngOrNewLng
        deltaLat = deltaLatOrNewLat
      } else {
        // Calculate delta from new center position
        let centroid
        if (originalGeometry.type === 'Point') {
          centroid = originalGeometry.coordinates
        } else if (originalGeometry.type === 'LineString') {
          const coords = originalGeometry.coordinates
          const sumLng = coords.reduce((acc, c) => acc + c[0], 0)
          const sumLat = coords.reduce((acc, c) => acc + c[1], 0)
          centroid = [sumLng / coords.length, sumLat / coords.length]
        } else if (originalGeometry.type === 'Polygon') {
          const coords = originalGeometry.coordinates[0]
          const sumLng = coords.reduce((acc, c) => acc + c[0], 0)
          const sumLat = coords.reduce((acc, c) => acc + c[1], 0)
          centroid = [sumLng / coords.length, sumLat / coords.length]
        } else {
          addActivity('Unsupported geometry type for move', 'error')
          return false
        }
        
        deltaLng = deltaLngOrNewLng - centroid[0]
        deltaLat = deltaLatOrNewLat - centroid[1]
      }

      // Translate the geometry
      let newGeometry
      if (originalGeometry.type === 'Point') {
        newGeometry = {
          type: 'Point',
          coordinates: [originalGeometry.coordinates[0] + deltaLng, originalGeometry.coordinates[1] + deltaLat]
        }
      } else if (originalGeometry.type === 'LineString') {
        newGeometry = {
          type: 'LineString',
          coordinates: originalGeometry.coordinates.map(c => [c[0] + deltaLng, c[1] + deltaLat])
        }
      } else if (originalGeometry.type === 'Polygon') {
        newGeometry = {
          type: 'Polygon',
          coordinates: originalGeometry.coordinates.map(ring =>
            ring.map(c => [c[0] + deltaLng, c[1] + deltaLat])
          )
        }
      }

      // Update via API
      await api.updateOverlay(overlayId, { geom: newGeometry })
      addActivity(`Moved overlay`, 'success')
      return true
    } catch (err) {
      addActivity(`Failed to move overlay: ${err.message}`, 'error')
      return false
    }
  }, [api, addActivity])

  /**
   * Start geometry editing mode for an overlay
   * Loads the overlay geometry into MapboxDraw for vertex editing
   */
  const startGeometryEdit = useCallback((overlay) => {
    if (!drawRef.current || !overlay?.geometry) {
      addActivity('Cannot start geometry edit - missing draw control or geometry', 'error')
      return
    }

    setGeometryEditMode(true)

    // Set draw layer colors to black for editing
    // MapboxDraw creates layers with .hot and .cold suffixes
    if (mapRef.current) {
      try {
        const layers = mapRef.current.getStyle().layers || []
        layers.forEach(layer => {
          if (layer.id.startsWith('gl-draw')) {
            try {
              if (layer.type === 'line') {
                mapRef.current.setPaintProperty(layer.id, 'line-color', '#000000')
              } else if (layer.type === 'fill') {
                mapRef.current.setPaintProperty(layer.id, 'fill-color', '#000000')
              } else if (layer.type === 'circle') {
                mapRef.current.setPaintProperty(layer.id, 'circle-color', '#000000')
                mapRef.current.setPaintProperty(layer.id, 'circle-stroke-color', '#000000')
              }
            } catch (e) {
              // Some properties may not exist on all layers
            }
          }
        })
      } catch (err) {
        // Layer styling failed, continue with defaults
      }
    }

    // Clear any existing features in draw control
    drawRef.current.deleteAll()

    // Add the overlay geometry to draw control
    const featureIds = drawRef.current.add({
      type: 'Feature',
      geometry: overlay.geometry,
      properties: { overlayId: overlay.id }
    })

    // Enter direct_select mode for vertex editing
    // Use setTimeout to ensure draw control has processed the add() call
    const featureId = Array.isArray(featureIds) ? featureIds[0] : featureIds
    if (featureId) {
      // Use requestAnimationFrame for better timing with browser render cycle
      requestAnimationFrame(() => {
        if (drawRef.current) {
          drawRef.current.changeMode('direct_select', { featureId })
        }
      })
    }

  }, [drawRef, mapRef, setGeometryEditMode])

  /**
   * Save the edited geometry to the backend
   */
  const saveGeometryEdit = useCallback(async (loadMapState) => {
    if (!drawRef.current || !geometryEditModeRef.current) return false

    try {
      // Get the updated geometry from draw control
      const features = drawRef.current.getAll()
      if (!features || features.features.length === 0) {
        addActivity('No geometry to save', 'error')
        return false
      }

      const editedFeature = features.features[0]
      const overlayId = editedFeature.properties?.overlayId

      if (!overlayId) {
        addActivity('Cannot save - overlay ID not found', 'error')
        return false
      }

      // Save to backend
      await api.updateOverlay(overlayId, { geom: editedFeature.geometry })
      addActivity('Geometry updated successfully', 'success')

      // Clean up
      drawRef.current.deleteAll()
      drawRef.current.changeMode('simple_select')
      setGeometryEditMode(false)

      // Refresh map to show updated tactical graphic
      if (loadMapState) {
        loadMapState()
      }

      return true
    } catch (err) {
      addActivity(`Failed to save geometry: ${err.message}`, 'error')
      return false
    }
  }, [api, drawRef, geometryEditModeRef, addActivity, setGeometryEditMode])

  /**
   * Cancel geometry editing and restore original state
   */
  const cancelGeometryEdit = useCallback((loadMapState) => {
    if (!drawRef.current) return

    // Clear draw control
    drawRef.current.deleteAll()
    drawRef.current.changeMode('simple_select')

    // Reset state
    setGeometryEditMode(false)

    addActivity('Geometry edit cancelled', 'info')

    // Refresh map to restore original tactical graphic
    if (loadMapState) {
      loadMapState()
    }
  }, [drawRef, addActivity, setGeometryEditMode])

  return {
    getSidcForOverlayType,
    createOverlay,
    updateOverlay,
    deleteOverlay,
    handleDrawCreate,
    savePendingOverlay,
    cancelOverlayCreation,
    restartOverlayDraw,
    startOverlayDraw,
    exitOverlayDrawMode,
    selectOverlayForEdit,
    moveOverlay,
    // Geometry editing
    startGeometryEdit,
    saveGeometryEdit,
    cancelGeometryEdit
  }
}
