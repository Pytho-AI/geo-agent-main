/**
 * Mode indicator banners (placement mode, draw mode)
 */

import React from 'react'
import { useGeoAgent } from '../GeoAgentProvider'

// Helper to get all overlay types from appConfig
const getAllOverlayTypes = (overlayTypes) => {
  if (!overlayTypes) return []
  return [...(overlayTypes.line || []), ...(overlayTypes.polygon || []), ...(overlayTypes.point || [])]
}

/**
 * PlacementModeBanner - Shows when in placement mode
 */
export function PlacementModeBanner() {
  const { placementMode, setPlacementMode } = useGeoAgent()

  if (!placementMode) return null

  return (
    <div className="edit-mode-banner placement">
      PLACEMENT MODE: Click on map to place new military unit
      <button onClick={() => setPlacementMode(false)} className="banner-cancel">Cancel</button>
    </div>
  )
}

/**
 * OverlayDrawModeBanner - Shows when drawing an overlay
 * @param {Object} props
 * @param {Function} props.onExit - Handler to exit draw mode
 */
export function OverlayDrawModeBanner({ onExit }) {
  const { overlayDrawMode, selectedOverlayType, appConfig } = useGeoAgent()

  if (!overlayDrawMode) return null

  const allTypes = getAllOverlayTypes(appConfig?.overlayTypes)
  const typeInfo = allTypes.find(t => t.value === selectedOverlayType)
  const minPoints = typeInfo?.minPoints || 2

  return (
    <div className="edit-mode-banner overlay-draw">
      <strong>DRAW {typeInfo?.label?.toUpperCase() || selectedOverlayType}:</strong>
      {minPoints > 2 
        ? ` Click to add points (minimum ${minPoints}) • Double-click or Enter to finish • Esc to cancel`
        : ' Click to add points • Double-click or Enter to finish • Esc to cancel'
      }
      <button onClick={onExit} className="banner-cancel">Cancel</button>
    </div>
  )
}

/**
 * MeasureBanner - Shows when in measure mode
 */
export function MeasureBanner() {
  const { measureMode, measurePoints, setMeasureMode, setMeasurePoints } = useGeoAgent()

  if (!measureMode) return null

  const getInstructions = () => {
    if (measurePoints.length === 0) {
      return 'Click first point on the map'
    } else if (measurePoints.length === 1) {
      return 'Click second point to measure distance'
    } else {
      return 'Click to start new measurement'
    }
  }

  return (
    <div className="edit-mode-banner measure">
      <strong>MEASURE MODE:</strong> {getInstructions()}
      <button 
        onClick={() => {
          setMeasureMode(false)
          setMeasurePoints([])
        }} 
        className="banner-cancel"
      >
        Exit
      </button>
    </div>
  )
}

/**
 * GeometryEditModeBanner - Shows when editing overlay geometry
 */
export function GeometryEditModeBanner() {
  const { geometryEditMode } = useGeoAgent()

  if (!geometryEditMode) return null

  return (
    <div className="edit-mode-banner geometry-edit">
      <strong>EDITING GEOMETRY:</strong> Drag vertices to reshape • Click Save when finished
    </div>
  )
}

/**
 * AllBanners - Convenience component that renders all banners
 * @param {Object} props
 * @param {Function} props.onExitOverlayDrawMode - Handler to exit overlay draw mode
 */
export function AllBanners({ onExitOverlayDrawMode }) {
  return (
    <>
      <PlacementModeBanner />
      <OverlayDrawModeBanner onExit={onExitOverlayDrawMode} />
      <GeometryEditModeBanner />
    </>
  )
}
