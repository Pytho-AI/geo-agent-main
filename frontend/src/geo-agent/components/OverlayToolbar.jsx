/**
 * Overlay drawing toolbar component
 */

import React, { useMemo } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'

/**
 * Group line types by category
 * @param {Array} lineTypes - Array of line type objects with category field
 * @param {Array} categoryOrder - Ordered list of category names
 * @returns {Array} Array of { category, types } objects in order
 */
function groupLinesByCategory(lineTypes, categoryOrder) {
  // Group by category
  const grouped = {}
  for (const type of lineTypes) {
    const cat = type.category || 'Other'
    if (!grouped[cat]) grouped[cat] = []
    grouped[cat].push(type)
  }
  
  // Return in specified order
  const result = []
  for (const cat of categoryOrder) {
    if (grouped[cat] && grouped[cat].length > 0) {
      result.push({ category: cat, types: grouped[cat] })
      delete grouped[cat]
    }
  }
  
  // Add any remaining categories not in order
  for (const cat of Object.keys(grouped)) {
    if (grouped[cat].length > 0) {
      result.push({ category: cat, types: grouped[cat] })
    }
  }
  
  return result
}

/**
 * OverlayToolbar - Toolbar for selecting tactical overlay types to draw
 * @param {Object} props
 * @param {Function} props.onStartDraw - Handler to start drawing (overlayType) => void
 */
export function OverlayToolbar({ onStartDraw }) {
  const {
    overlayDrawMode,
    showOverlayToolbar,
    setShowOverlayToolbar,
    appConfig,
    configLoaded
  } = useGeoAgent()

  // Group lines AND points by category. Point graphics (decision
  // points, key terrain, choke points, range fans, supply/medical
  // points) belong in the same doctrinal sections as their line
  // siblings — the catalog's point list was never rendered at all
  // before, leaving every point kind the pipelines emit with no
  // manual-add UI. The draw flow picks draw_point / draw_line_string /
  // draw_polygon from the catalog geometry, not from the section.
  const groupedLines = useMemo(() => {
    if (!appConfig?.overlayTypes) return []
    const categoryOrder = appConfig.overlayTypes.lineCategoryOrder || []
    const linesAndPoints = [
      ...(appConfig.overlayTypes.line || []),
      ...(appConfig.overlayTypes.point || []),
    ]
    return groupLinesByCategory(linesAndPoints, categoryOrder)
  }, [appConfig?.overlayTypes])

  if (!showOverlayToolbar || overlayDrawMode) return null

  // Wait for config to load from backend
  if (!configLoaded || !appConfig?.overlayTypes) {
    return (
      <div className="overlay-toolbar">
        <div className="overlay-toolbar-header">
          <h3>Tactical Overlays</h3>
          <button onClick={() => setShowOverlayToolbar(false)}>×</button>
        </div>
        <div className="overlay-toolbar-content">
          <p style={{ padding: '16px', color: '#888' }}>Loading overlay types...</p>
        </div>
      </div>
    )
  }

  const overlayTypes = appConfig.overlayTypes
  const overlayStyles = appConfig.overlayStyles || {}

  return (
    <div className="overlay-toolbar">
      <div className="overlay-toolbar-header">
        <h3>Tactical Overlays</h3>
        <button onClick={() => setShowOverlayToolbar(false)}>×</button>
      </div>
      <div className="overlay-toolbar-content">
        {/* Areas section */}
        <div className="overlay-category">
          <div className="overlay-category-title">Areas</div>
          {(overlayTypes.polygon || []).map(type => (
            <button 
              key={type.value}
              className="overlay-type-btn"
              onClick={() => onStartDraw && onStartDraw(type.value)}
              title={type.desc}
            >
              {type.label}
            </button>
          ))}
        </div>

        {/* Lines grouped by category */}
        {groupedLines.map(group => (
          <div key={group.category} className="overlay-category">
            <div className="overlay-category-title">{group.category}</div>
            {group.types.map(type => (
              <button 
                key={type.value}
                className="overlay-type-btn"
                onClick={() => onStartDraw && onStartDraw(type.value)}
                title={type.desc}
              >
                {type.label}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
