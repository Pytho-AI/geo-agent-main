/**
 * Hook for managing map event handlers (click, hover, drag, contextmenu)
 *
 * Edit model:
 * - Single click on entity/overlay → opens edit panel
 * - Click and drag on entity/overlay → moves it (no vertex editing)
 *
 * Live ops-map (editEnabled === false) applies the provenance boundary
 * (isPipelineOwned): analyst-authored features (no properties.source)
 * get the full edit model above; pipeline rows are inspect-only —
 * mil-unit click → UnitMetadataPanel, signal-report markers → their
 * panel. Edit sessions (editEnabled) may manipulate everything for
 * product framing.
 *
 * Live ops-map extras:
 * - Right-click on a red `mil_unit` icon → contextmenu with a single
 *   "Generate TIDAT" item. The clicked unit is the observed threat
 *   entity; the menu is suppressed on friendly / neutral / unknown
 *   affiliations and on empty terrain. Doctrinal reference for the
 *   target-observation chain-of-custody (originating cell, detection
 *   source, prepared by) is in code-comments only — never user-visible.
 *   See FM 34-25-3 Ch 5.
 */

import { useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useGeoAgent } from '../GeoAgentProvider'
import { useEntities } from './useEntities'
import { useOverlays } from './useOverlays'
import { logAnalystEvent } from '../../lib/analystEvent'
import { lookupUnitMetadata } from '../utils/unitMetadata'
import { showGenerateTidatMenu } from '../utils/generateMenu'

// Overlay layers for querying. Includes the unified MCOO point hit-target
// layer added by applyDoctrinalControlMeasures so that doctrinal point glyphs whose
// visual is painted by MapDoctrinalPaint's SVG (NAI/TAI/OBJ/EA point
// variants, key terrain, choke points, obstacle points, strong points,
// decision points) remain clickable in the editor. The SVG layer itself
// has pointer-events: none.
const OVERLAY_LAYERS = [
  'tactical-graphics-fill',
  'tactical-graphics-lines',
  'tactical-graphics-hit-target',
  'graphics-points-hit-target'
]

/**
 * Parse feature properties (handles JSON string case)
 */
function parseFeatureProperties(feature) {
  return typeof feature.properties === 'string'
    ? JSON.parse(feature.properties)
    : feature.properties
}

// Provenance boundary for LIVE-map editing: analyst-authored features
// carry no properties.source (drawn overlays) or source === 'manual'
// (placed units — tagged so the live_oob transactional replace never
// deletes them; see useEntities). Every pipeline row is source-tagged
// by the sync endpoint (live_oob, scenario_terrain, opord,
// product-mirror keys, osm seeds). On the live operations map,
// analyst-authored content is fully editable — place, drag, edit,
// delete — while pipeline rows stay inspect-only (the next source sync
// would silently clobber a hand move anyway). Edit sessions
// (editEnabled) may still manipulate everything for product framing.
function isPipelineOwned(feature) {
  const props = parseFeatureProperties(feature) || {}
  return !!props.source && props.source !== 'manual'
}

/**
 * Hook that sets up all map event handlers
 * @param {Object} options
 * @param {Function} options.onEntityClick - External entity click callback
 * @param {Function} options.loadMapStateWithCallbacks - Function to reload map state
 * @param {Function} options.pushUndo - Record a move op (type, id, oldGeom, newGeom) on the undo stack
 */
export function useMapEvents({ onEntityClick, loadMapStateWithCallbacks, pushUndo }) {
  const {
    mapRef,
    placementModeRef,
    overlayDrawModeRef,
    geometryEditModeRef,
    measureModeRef,
    routePlanModeRef,
    measurePoints,
    setMeasurePoints,
    setPlacementMode,
    setOverlayDrawMode,
    setShowOverlayToolbar,
    setShowEditPanel,
    setSelectedEntity,
    setShowOverlayEditPanel,
    setSelectedOverlay,
    setCoordinates,
    setPendingLocation,
    setShowCreatePanel,
    editEnabled,
    userId,
    addActivity,
    setSelectedUnitMeta,
    setSelectedOverlayMeta,
    interactionMode,
  } = useGeoAgent()

  // Ref so the right-click handler always reads the current edit-mode
  // gate and analyst identity without forcing setupEventHandlers to
  // re-register (which would tear down + re-attach every MapLibre
  // listener on each render).
  const editEnabledRef = useRef(editEnabled)
  useEffect(() => { editEnabledRef.current = editEnabled }, [editEnabled])

  // VIEW / EDIT interaction mode. Edit-map deep-link sessions
  // (editEnabled) are edit mode by definition; on the live map the
  // MapControls toggle flips it. In view mode NOTHING drags and every
  // click is an inspect (placard) — an analyst reading the map can
  // never accidentally move a symbol.
  const interactionModeRef = useRef(interactionMode)
  useEffect(() => { interactionModeRef.current = interactionMode }, [interactionMode])
  const inEditMode = () => editEnabledRef.current || interactionModeRef.current === 'edit'

  const userIdRef = useRef(userId)
  useEffect(() => { userIdRef.current = userId }, [userId])

  const addActivityRef = useRef(addActivity)
  useEffect(() => { addActivityRef.current = addActivity }, [addActivity])

  // Ref-mirrored so the live-mode unit-click handler can open the metadata
  // panel without re-registering MapLibre listeners on every render.
  const setSelectedUnitMetaRef = useRef(setSelectedUnitMeta)
  useEffect(() => { setSelectedUnitMetaRef.current = setSelectedUnitMeta }, [setSelectedUnitMeta])

  const setSelectedOverlayMetaRef = useRef(setSelectedOverlayMeta)
  useEffect(() => { setSelectedOverlayMetaRef.current = setSelectedOverlayMeta }, [setSelectedOverlayMeta])

  // react-router navigate handle threaded into the right-click generate
  // flow so it can hop the analyst into the DocEditor session URL once
  // the chain completes. Falls back to window.location.assign in
  // fireGenerateAndOpen if navigate is somehow null at call time.
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  useEffect(() => { navigateRef.current = navigate }, [navigate])

  const { selectEntity, updateEntityPosition } = useEntities()
  const { selectOverlayForEdit, moveOverlay, startGeometryEdit } = useOverlays()

  // Refs to hold current versions of selection functions
  const selectEntityRef = useRef(selectEntity)
  const selectOverlayForEditRef = useRef(selectOverlayForEdit)
  const updateEntityPositionRef = useRef(updateEntityPosition)
  const moveOverlayRef = useRef(moveOverlay)
  const startGeometryEditRef = useRef(startGeometryEdit)
  const loadMapStateRef = useRef(loadMapStateWithCallbacks)
  const pushUndoRef = useRef(pushUndo)

  // Keep refs in sync
  useEffect(() => {
    selectEntityRef.current = selectEntity
  }, [selectEntity])

  useEffect(() => {
    selectOverlayForEditRef.current = selectOverlayForEdit
  }, [selectOverlayForEdit])

  useEffect(() => {
    updateEntityPositionRef.current = updateEntityPosition
  }, [updateEntityPosition])

  useEffect(() => {
    moveOverlayRef.current = moveOverlay
  }, [moveOverlay])

  useEffect(() => {
    startGeometryEditRef.current = startGeometryEdit
  }, [startGeometryEdit])

  useEffect(() => {
    loadMapStateRef.current = loadMapStateWithCallbacks
  }, [loadMapStateWithCallbacks])

  useEffect(() => {
    pushUndoRef.current = pushUndo
  }, [pushUndo])

  /**
   * Handle entity selection (single click opens edit panel)
   */
  const handleEntitySelect = useCallback((feature, onClickCallback) => {
    const props = parseFeatureProperties(feature)
    
    // Clear other modes
    setPlacementMode(false)
    setShowOverlayToolbar(false)
    setOverlayDrawMode(false)
    
    // Close overlay panel if open
    setShowOverlayEditPanel(false)
    setSelectedOverlay(null)
    
    // Select the entity (opens edit panel)
    selectEntityRef.current({
      id: props.id || feature.id,
      geometry: feature.geometry,
      properties: props
    })
    
    if (onClickCallback) {
      onClickCallback(feature)
    }
  }, [setPlacementMode, setShowOverlayToolbar, setOverlayDrawMode, 
      setShowOverlayEditPanel, setSelectedOverlay])

  /**
   * Handle overlay selection (single click opens edit panel and geometry edit mode)
   */
  const handleOverlaySelect = useCallback((feature) => {
    const props = parseFeatureProperties(feature)
    const overlayId = props.overlayId || props.id || feature.id
    
    // Clear other modes
    setPlacementMode(false)
    setShowOverlayToolbar(false)
    setOverlayDrawMode(false)
    
    // Close entity panel if open
    setShowEditPanel(false)
    setSelectedEntity(null)
    
    // Get original geometry for potential move operations
    let originalGeometry = feature.geometry
    if (props.originalGeometry) {
      try {
        originalGeometry = JSON.parse(props.originalGeometry)
      } catch (e) {
        // Use rendered geometry if parsing fails
      }
    }
    
    const overlayData = {
      id: overlayId,
      geometry: originalGeometry,
      properties: props
    }
    
    // Select the overlay (opens edit panel)
    selectOverlayForEditRef.current(overlayData, originalGeometry)
    
    // Start geometry editing with a small delay to ensure refs are populated
    // and the edit panel has opened
    setTimeout(() => {
      if (startGeometryEditRef.current) {
        startGeometryEditRef.current(overlayData)
      }
    }, 50)
  }, [setPlacementMode, setShowOverlayToolbar, setOverlayDrawMode,
      setShowEditPanel, setSelectedEntity])

  /**
   * Set up all map event handlers
   */
  const setupEventHandlers = useCallback((map) => {
    if (!map) return

    // Track drag state
    let isDragging = false
    let dragStartPoint = null
    let dragStartLngLat = null
    let dragFeature = null
    let dragType = null // 'entity' or 'overlay'
    let dragSourceName = null
    let hasMoved = false
    let originalTacticalGraphicsData = null // Store original data for overlay dragging
    let dragOriginalGeom = null // For undo: geometry before drag started
    let inspectStartPoint = null // view-mode click origin (pan-vs-click test)
    const DRAG_THRESHOLD = 5 // pixels before considering it a drag

    // Coordinate tracking
    map.on('mousemove', (e) => {
      setCoordinates({
        lng: e.lngLat.lng.toFixed(4),
        lat: e.lngLat.lat.toFixed(4)
      })
    })

    // Placement mode click (for creating new entities)
    map.on('click', (e) => {
      if (placementModeRef.current) {
        setPendingLocation([e.lngLat.lng, e.lngLat.lat])
        setShowCreatePanel(true)
        setPlacementMode(false)
        return
      }
      
      // Route planning mode — let GeoAgentMap handle it
      if (routePlanModeRef.current) {
        return
      }

      // Measure mode click (for measuring distance)
      if (measureModeRef.current) {
        const newPoint = { lng: e.lngLat.lng, lat: e.lngLat.lat }
        setMeasurePoints(prev => {
          if (prev.length >= 2) {
            // Reset and start new measurement
            return [newPoint]
          }
          return [...prev, newPoint]
        })
        return
      }
    })

    // --- Entity/Mil-unit mouse handlers ---
    // Gated on editEnabled — the live ops-map (read-only) suppresses every
    // edit affordance. Edit mode is only entered via the DocEditor edit-map
    // deep link (?from_artifact=<id>).
    const handleEntityMouseDown = (e, sourceName) => {
      // Dragging exists ONLY in edit mode. View mode is read-only —
      // clicks inspect, nothing moves.
      if (!inEditMode()) return
      if (overlayDrawModeRef.current || placementModeRef.current || measureModeRef.current || geometryEditModeRef.current) return
      // A rolled-up formation stands for N subordinate units — dragging it
      // would silently move only the parent row. Not a drag target.
      if (parseFeatureProperties(e.features[0])?.isRollup) return
      e.preventDefault()

      dragStartPoint = e.point
      dragStartLngLat = e.lngLat
      dragFeature = e.features[0]
      dragType = 'entity'
      dragSourceName = sourceName
      hasMoved = false

      // Capture original geometry for undo
      dragOriginalGeom = dragFeature.geometry ? JSON.parse(JSON.stringify(dragFeature.geometry)) : null
    }

    map.on('mousedown', 'entities-points', (e) => handleEntityMouseDown(e, 'entities'))
    map.on('mousedown', 'mil-units-symbols', (e) => {
      // The invisible anchor circle can belong to a NEIGHBOR in dense
      // clusters — the drawn frame under the cursor wins (unitAtPoint,
      // topmost-first, nearest-center).
      const hit = unitAtPoint(e.point)
      const ev = hit
        ? { ...e, features: [hit.feature], preventDefault: () => e.preventDefault() }
        : e
      handleEntityMouseDown(ev, 'mil-units')
    })

    // --- Overlay mouse handlers ---
    const handleOverlayMouseDown = (e) => {
      if (overlayDrawModeRef.current || placementModeRef.current || measureModeRef.current || geometryEditModeRef.current) return

      const existingLayers = OVERLAY_LAYERS.filter(layer => map.getLayer(layer))
      const features = map.queryRenderedFeatures(e.point, { layers: existingLayers })

      // Dragging exists ONLY in edit mode — view-mode clicks fall
      // through to the mouseup inspect branch (control-measure
      // placard). No dragStartPoint: the mousemove drag machinery
      // never engages, so map panning stays untouched.
      if (features.length > 0 && !inEditMode()) {
        dragFeature = features[0]
        dragType = 'overlay-inspect'
        inspectStartPoint = e.point
        hasMoved = false
        return
      }

      if (features.length > 0) {
        e.preventDefault()
        dragStartPoint = e.point
        dragStartLngLat = e.lngLat
        dragFeature = features[0]
        dragType = 'overlay'
        hasMoved = false

        // Capture original overlay geometry for undo. Prefer the
        // originalGeometry prop stamped on each feature by the tactical
        // layer builder (the rendered geometry may be a simplified/derived
        // hit-target), falling back to the feature's own geometry.
        const overlayProps = parseFeatureProperties(features[0])
        if (overlayProps?.originalGeometry) {
          try {
            dragOriginalGeom = JSON.parse(overlayProps.originalGeometry)
          } catch (_) {
            dragOriginalGeom = features[0].geometry ? JSON.parse(JSON.stringify(features[0].geometry)) : null
          }
        } else {
          dragOriginalGeom = features[0].geometry ? JSON.parse(JSON.stringify(features[0].geometry)) : null
        }

        // Store original tactical graphics data for restoration/modification
        const source = map.getSource('tactical-graphics')
        if (source && source._data) {
          originalTacticalGraphicsData = JSON.parse(JSON.stringify(source._data))
        }
      }
    }

    map.on('mousedown', (e) => {
      // Only handle if not on entity layers (those have their own handlers)
      const entityLayers = ['entities-points', 'mil-units-symbols']
      const existingEntityLayers = entityLayers.filter(layer => map.getLayer(layer))
      const entityFeatures = map.queryRenderedFeatures(e.point, { layers: existingEntityLayers })

      if (entityFeatures.length > 0) return

      // Drawn-frame hit test (edit mode): HQ-staff symbols hang their
      // frame a staff-length above the ground anchor — the analyst
      // drags the frame they SEE, not the invisible anchor circle.
      if (inEditMode()) {
        for (const b of (map.__milUnitHitBoxes || [])) {
          if (e.point.x >= b.x && e.point.x <= b.x + b.w
              && e.point.y >= b.y && e.point.y <= b.y + b.h) {
            handleEntityMouseDown(
              { ...e, features: [b.feature], preventDefault: () => e.preventDefault() },
              'mil-units',
            )
            return
          }
        }
      }

      handleOverlayMouseDown(e)
    })

    // --- Right-click → Generate TIDAT for the clicked red mil_unit. ---
    // Phase-1: single menu item only ("Generate TIDAT"). The clicked entity
    // is the observed-threat target subject — server-side TIDAT writer
    // pulls target_id / target_name / target_location_mgrs / DOI /
    // detection_source from THIS entity's kg record. Affiliation gate
    // blocks the menu on friendly / neutral / unknown markers; the HPTL
    // schema rejects non-red entries anyway and this gates the dead path
    // out at the UI. Empty terrain right-click returns silently.
    // See FM 34-25-3 Ch 5 — TIDAT comes from the ACE workstation, not a
    // forward observer; chain-of-custody is originating_cell +
    // detection_source + prepared_by on the artifact.
    map.on('contextmenu', (e) => {
      // Right-click is unconditional with respect to editEnabled — it's
      // the only generation gesture in live mode, and it remains usable
      // in edit mode too (handler is harmless when overlapping with
      // edit panels).
      e.preventDefault()

      const layers = map.getLayer('mil-units-symbols') ? ['mil-units-symbols'] : []
      if (layers.length === 0) return
      const feats = map.queryRenderedFeatures(e.point, { layers })
      if (!feats || feats.length === 0) return

      const unit = feats[0]
      const props = parseFeatureProperties(unit) || {}
      const affiliationRaw = (props.affiliation || props.side || '').toString().toLowerCase()
      // Phase-1: only red / hostile units carry TIDATs. The HPTL schema
      // also enforces this server-side; gating in the UI keeps the menu
      // from appearing on entries that would never produce an artifact.
      if (affiliationRaw !== 'red' && affiliationRaw !== 'hostile') return

      // target_entity_id MUST be the KNOWLEDGE-GRAPH id (`source_kbid`
      // on live_oob features), NOT geo-agent's own entity row uuid
      // (`props.id`): the per-target writer binds the KG record by this
      // value and the HPTL dispatch gate validates it against HPTL row
      // ids (KG ids) — a geo-agent uuid fails both, so every right-click
      // TIDAT since the map takeover was refused or gap-noticed, and the
      // pushed-badge join (same key) never matched. NO row-uuid
      // fallback: a feature without KG lineage (analyst-placed hostile
      // unit) gets no menu instead of a menu whose generation the
      // server refuses.
      const entityId = props.source_kbid
      if (!entityId) return

      const callsign = props.name || props.callsign || props.unique_designation || props.short_name || entityId
      // Telemetry: right-click → Generate TIDAT engagement on the map.
      // Fire-and-forget; never affects the gesture.
      logAnalystEvent({
        event_type: 'map.tidat_right_click',
        surface: 'map',
        user_id: userIdRef.current ?? null,
        detail: { entity_id: entityId, callsign: String(callsign) },
      })
      showGenerateTidatMenu({
        screenX: e.originalEvent.clientX,
        screenY: e.originalEvent.clientY,
        entityId,
        callsign,
        userId: userIdRef.current,
        addActivity: addActivityRef.current,
        navigate: navigateRef.current,
      })
    })

    // --- Live ops-map LEFT-CLICK on a unit → metadata panel. ---
    // The read-only operations map suppresses the edit-mode select/drag
    // machinery (handleEntityMouseDown bails when !editEnabled, so
    // dragFeature is never set and the mouseup click branch is inert). This
    // layer-scoped click is the live-mode inspect gesture: look the clicked
    // unit up in the resolved-OOB index (kg_id == source_kbid, name
    // fallback) and open UnitMetadataPanel. Gated to NON-edit mode so edit
    // mode keeps EntityPanel; suppressed while placing / measuring / route-
    // planning so it never hijacks those click flows.
    // Opens UnitMetadataPanel for a unit — the ONE unit-inspect path.
    // Rolled-up member clicks reuse it so subordinate rows open the same
    // panel a direct icon click would.
    const inspectUnit = (kgId, name, props, coords) => {
      setSelectedUnitMetaRef.current?.({ unit: null, props, coords })
      lookupUnitMetadata({ kgId, name })
        .then((unit) => {
          if (unit) setSelectedUnitMetaRef.current?.({ unit, props, coords })
        })
        .catch(() => { /* keep the feature-only view */ })
    }

    // Rolled-up formations are ordinary click targets: the click opens
    // the SAME rich UnitMetadataPanel a direct icon click would, and its
    // subordinate tree is the member navigation — no parallel list UI,
    // no extra map chrome.
    const openUnitPlacard = (feature) => {
      const props = parseFeatureProperties(feature) || {}
      const kgId = props.source_kbid || props.id || props.entity_id || feature.id
      const name = props.name || props.unique_designation || props.short_name
      const coords = feature.geometry?.coordinates
      // Show the feature's own data immediately; enrich with the fused OOB
      // record (equipment / activity / fused MGRS) once the lookup resolves.
      inspectUnit(kgId, name, props, coords)
    }

    // Frame-box hit test — the AUTHORITATIVE unit click target. The
    // SVG paint pass registers the frame extent of every drawn symbol
    // (map.__milUnitHitBoxes, paint order = bottom-to-top). Walk them
    // TOP-FIRST and break ties by nearest frame center, so in a dense
    // cluster the click selects exactly the symbol under the cursor —
    // the old path let the invisible 30 px anchor circle of a NEIGHBOR
    // claim the click before the frame test ever ran.
    const unitAtPoint = (pt) => {
      const boxes = map.__milUnitHitBoxes || []
      let best = null
      let bestD = Infinity
      for (let i = boxes.length - 1; i >= 0; i--) {
        const b = boxes[i]
        if (pt.x >= b.x && pt.x <= b.x + b.w
            && pt.y >= b.y && pt.y <= b.y + b.h) {
          const d = Math.hypot(pt.x - b.cx, pt.y - b.cy)
          if (d < bestD) { best = b; bestD = d }
        }
      }
      return best
    }

    map.on('click', (e) => {
      if (inEditMode()) return
      if (placementModeRef.current || measureModeRef.current || routePlanModeRef.current) return
      const hit = unitAtPoint(e.point)
      if (hit) {
        openUnitPlacard(hit.feature)
        return
      }
      // Range-ring hit: clicking a painted band opens ITS BEARER's
      // placard (rings only paint for the selected unit, but the
      // click must also work while they're up — and near-boundary
      // clicks belong to the ring, not to empty terrain).
      for (const ring of (map.__rangeRingHits || [])) {
        // Rings are GROUND circles: compare ground distance from the
        // click to the ring radius, with an 8-px tolerance converted
        // to meters at this latitude/zoom (screen-space center+radius
        // math breaks under pitch/rotation).
        const dLatM = (e.lngLat.lat - ring.lat) * 111320
        const dLngM = (e.lngLat.lng - ring.lng) * 111320
          * Math.cos((ring.lat * Math.PI) / 180)
        const dM = Math.hypot(dLatM, dLngM)
        const mPerPx = (156543.03392
          * Math.cos((e.lngLat.lat * Math.PI) / 180))
          / Math.pow(2, map.getZoom())
        if (Math.abs(dM - ring.radius_m) <= 8 * mPerPx && ring.bearerId) {
          const src = map.getSource && map.getSource('mil-units')
          const feats = (src && src._data && src._data.features) || []
          const bearer = feats.find(f =>
            String((f.properties || {}).id || '') === ring.bearerId)
          if (bearer) {
            openUnitPlacard(bearer)
            return
          }
        }
      }
      // Fallback: the anchor circle layer (covers the first frames
      // before the SVG pass has painted).
      const circleHits = map.getLayer('mil-units-symbols')
        ? map.queryRenderedFeatures(e.point, { layers: ['mil-units-symbols'] })
        : []
      if (circleHits.length > 0) openUnitPlacard(circleHits[0])
    })

    // Helper to translate geometry by delta
    const translateGeometry = (geometry, deltaLng, deltaLat) => {
      if (!geometry) return geometry
      
      if (geometry.type === 'Point') {
        return {
          type: 'Point',
          coordinates: [geometry.coordinates[0] + deltaLng, geometry.coordinates[1] + deltaLat]
        }
      } else if (geometry.type === 'LineString') {
        return {
          type: 'LineString',
          coordinates: geometry.coordinates.map(c => [c[0] + deltaLng, c[1] + deltaLat])
        }
      } else if (geometry.type === 'Polygon') {
        return {
          type: 'Polygon',
          coordinates: geometry.coordinates.map(ring =>
            ring.map(c => [c[0] + deltaLng, c[1] + deltaLat])
          )
        }
      } else if (geometry.type === 'MultiLineString') {
        return {
          type: 'MultiLineString',
          coordinates: geometry.coordinates.map(line =>
            line.map(c => [c[0] + deltaLng, c[1] + deltaLat])
          )
        }
      } else if (geometry.type === 'MultiPolygon') {
        return {
          type: 'MultiPolygon',
          coordinates: geometry.coordinates.map(polygon =>
            polygon.map(ring => ring.map(c => [c[0] + deltaLng, c[1] + deltaLat]))
          )
        }
      }
      return geometry
    }

    // --- Mouse move for dragging ---
    map.on('mousemove', (e) => {
      if (!dragFeature || !dragStartPoint) return
      
      // Check if we've moved enough to start dragging
      const dx = e.point.x - dragStartPoint.x
      const dy = e.point.y - dragStartPoint.y
      const distance = Math.sqrt(dx * dx + dy * dy)
      
      if (distance < DRAG_THRESHOLD) return
      
      if (!isDragging) {
        isDragging = true
        hasMoved = true
        map.getCanvas().style.cursor = 'grabbing'
        // Disable map panning while dragging
        map.dragPan.disable()
      }
      
      // Update visual position for entities (points)
      if (dragType === 'entity' && dragSourceName) {
        const coords = [e.lngLat.lng, e.lngLat.lat]
        const source = map.getSource(dragSourceName)
        
        if (source && source._data?.features) {
          const featureId = dragFeature.properties?.id || dragFeature.id
          const updated = source._data.features.map(f =>
            (f.properties?.id || f.id) === featureId
              ? { ...f, geometry: { type: 'Point', coordinates: coords } }
              : f
          )
          source.setData({ type: 'FeatureCollection', features: updated })
        }
      }
      
      // Update visual position for overlays
      if (dragType === 'overlay' && originalTacticalGraphicsData && dragStartLngLat) {
        const deltaLng = e.lngLat.lng - dragStartLngLat.lng
        const deltaLat = e.lngLat.lat - dragStartLngLat.lat
        const overlayId = dragFeature.properties?.overlayId || dragFeature.properties?.id || dragFeature.id
        
        const source = map.getSource('tactical-graphics')
        if (source && overlayId) {
          // Translate all features belonging to this overlay
          const updatedFeatures = originalTacticalGraphicsData.features.map(f => {
            const fOverlayId = f.properties?.overlayId || f.properties?.id || f.id
            if (fOverlayId === overlayId) {
              return {
                ...f,
                geometry: translateGeometry(f.geometry, deltaLng, deltaLat)
              }
            }
            return f
          })
          source.setData({ type: 'FeatureCollection', features: updatedFeatures })
        }
      }
    })

    // --- Mouse up - finish drag or handle click ---
    map.on('mouseup', async (e) => {
      const wasDragging = isDragging
      const hadMoved = hasMoved
      const feature = dragFeature
      const type = dragType
      const sourceName = dragSourceName
      const startLngLat = dragStartLngLat
      const savedOriginalGeom = dragOriginalGeom

      // Reset state
      isDragging = false
      dragStartPoint = null
      dragStartLngLat = null
      dragFeature = null
      dragType = null
      dragSourceName = null
      hasMoved = false
      originalTacticalGraphicsData = null
      dragOriginalGeom = null
      map.getCanvas().style.cursor = ''
      map.dragPan.enable()
      
      if (!feature) return
      
      const props = parseFeatureProperties(feature)
      
      if (hadMoved && wasDragging) {
        // This was a drag - save new position
        if (type === 'entity') {
          const entityId = props.id || feature.id
          const coords = [e.lngLat.lng, e.lngLat.lat]
          if (entityId) {
            const newGeom = { type: 'Point', coordinates: coords }
            if (props.source === 'entity_graph') {
              // RECORD units do not drag (S17 cutover, 2026-07-28):
              // a position is a sourced observation, and an analyst
              // drag cites no source — the actor is never a source.
              // The refetch below snaps the symbol back to the record.
              loadMapStateRef.current()
              return
            } else {
              await updateEntityPositionRef.current(entityId, coords)
            }
            // Push undo entry
            if (pushUndoRef.current && savedOriginalGeom) {
              pushUndoRef.current('entity', entityId, savedOriginalGeom, newGeom)
            }
            loadMapStateRef.current()
          }
        } else if (type === 'overlay') {
          // Move the entire overlay geometry using delta
          const overlayId = props.overlayId || props.id || feature.id
          if (overlayId && moveOverlayRef.current && startLngLat) {
            const deltaLng = e.lngLat.lng - startLngLat.lng
            const deltaLat = e.lngLat.lat - startLngLat.lat
            await moveOverlayRef.current(overlayId, deltaLng, deltaLat, props, true) // true = use delta mode
            // Push undo entry — compute new geometry from original + delta
            if (pushUndoRef.current && savedOriginalGeom) {
              const translateCoords = (coords) => [coords[0] + deltaLng, coords[1] + deltaLat]
              let newGeom
              if (savedOriginalGeom.type === 'Point') {
                newGeom = { type: 'Point', coordinates: translateCoords(savedOriginalGeom.coordinates) }
              } else if (savedOriginalGeom.type === 'LineString') {
                newGeom = { type: 'LineString', coordinates: savedOriginalGeom.coordinates.map(translateCoords) }
              } else if (savedOriginalGeom.type === 'Polygon') {
                newGeom = { type: 'Polygon', coordinates: savedOriginalGeom.coordinates.map(ring => ring.map(translateCoords)) }
              }
              if (newGeom) {
                pushUndoRef.current('overlay', overlayId, savedOriginalGeom, newGeom)
              }
            }
            loadMapStateRef.current()
          }
        }
      } else {
        // This was a click.
        if (type === 'overlay-inspect') {
          // View mode: every control measure opens its placard. A
          // mousedown that turned into a map pan is not a click.
          const moved = inspectStartPoint
            && Math.hypot(e.point.x - inspectStartPoint.x,
                          e.point.y - inspectStartPoint.y) > DRAG_THRESHOLD
          inspectStartPoint = null
          if (moved) return
          const p = parseFeatureProperties(feature) || {}
          setSelectedOverlayMetaRef.current?.({
            props: p,
            coords: [e.lngLat.lng, e.lngLat.lat],
          })
          return
        }
        // Edit mode: open the edit panels.
        if (!inEditMode()) return
        if (type === 'entity') {
          handleEntitySelect(feature, onEntityClick)
        } else if (type === 'overlay') {
          handleOverlaySelect(feature)
        }
      }
    })

    // Unified cursor change for all clickable layers
    map.on('mousemove', (e) => {
      if (isDragging || overlayDrawModeRef.current) return
      
      const clickableLayers = [
        'entities-points',
        'mil-units-symbols',
        ...OVERLAY_LAYERS,
      ]

      const existingLayers = clickableLayers.filter(layer => map.getLayer(layer))
      const features = map.queryRenderedFeatures(e.point, { layers: existingLayers })
      
      map.getCanvas().style.cursor = features.length > 0 ? 'pointer' : ''
    })

  }, [handleEntitySelect, handleOverlaySelect, onEntityClick,
      setCoordinates, setPendingLocation, setShowCreatePanel, setPlacementMode,
      placementModeRef, overlayDrawModeRef, measureModeRef, setMeasurePoints])

  return { setupEventHandlers }
}
