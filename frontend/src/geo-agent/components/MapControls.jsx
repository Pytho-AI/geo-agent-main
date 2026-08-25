/**
 * Map control buttons (zoom, edit mode, placement, overlay tools)
 */

import React, { useState, useEffect } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { cleanupRouteLayers } from '../utils/routeConstants'
import { createApiClient } from '../utils/api'
import { logAnalystEvent } from '../../lib/analystEvent'
import { RoutePlannerModal } from './RoutePlannerModal'
import { MapSearchControl } from './MapSearchControl'

/**
 * Check if Clipboard API with image support is available
 * (requires secure context: HTTPS or localhost)
 */
function isClipboardImageSupported() {
  return !!(
    navigator.clipboard &&
    typeof navigator.clipboard.write === 'function' &&
    typeof ClipboardItem !== 'undefined'
  )
}

/**
 * Download a blob as a file (fallback when clipboard is unavailable)
 */
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Capture the map as a PNG and copy to clipboard (or download as fallback)
 * @param {Object} mapRef - Reference to the MapLibre map instance
 * @param {Function} addActivity - Activity logger function
 * @returns {Promise<{success: boolean, message: string}>}
 */
async function captureMapToClipboard(mapRef, addActivity) {
  if (!mapRef?.current) {
    addActivity?.('Map not ready', 'error')
    return { success: false, message: 'Map not ready' }
  }

  try {
    const canvas = mapRef.current.getCanvas()
    
    // Create a blob from the canvas
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob)
        } else {
          reject(new Error('Failed to create image blob'))
        }
      }, 'image/png')
    })

    // Check if Clipboard API is available (requires HTTPS or localhost)
    if (isClipboardImageSupported()) {
      // Copy to clipboard using the Clipboard API
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': blob })
      ])
      addActivity?.('Map screenshot copied to clipboard', 'success')
      return { success: true, message: 'Screenshot copied to clipboard' }
    } else {
      // Fallback: download the image instead
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      downloadBlob(blob, `map-screenshot-${timestamp}.png`)
      addActivity?.('Map screenshot downloaded (clipboard not available over HTTP)', 'success')
      return { success: true, message: 'Screenshot downloaded (use HTTPS for clipboard)' }
    }
  } catch (err) {
    console.error('Failed to capture map:', err)
    addActivity?.(`Failed to capture map: ${err.message}`, 'error')
    return { success: false, message: `Failed: ${err.message}` }
  }
}

/**
 * MapControls component
 * @param {Object} props
 * @param {Function} props.onZoomIn - Zoom in handler
 * @param {Function} props.onZoomOut - Zoom out handler
 * @param {Function} props.onExitOverlayDrawMode - Exit overlay draw mode handler
 */
export function MapControls({
  onZoomIn,
  onZoomOut,
  onExitOverlayDrawMode,
  replanRoute,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  showUndoRedo = false,
}) {
  const {
    mapRef,
    apiUrl,
    mapId,
    placementMode,
    setPlacementMode,
    overlayDrawMode,
    showOverlayToolbar,
    setShowOverlayToolbar,
    setOverlayDrawMode,
    measureMode,
    setMeasureMode,
    setMeasurePoints,
    routePlanMode,
    setRoutePlanMode,
    setRouteMode,
    routeStart,
    setRouteStart,
    routeEnd,
    setRouteEnd,
    setRouteResult,
    setShowRoutePanel,
    routeMode,
    showHistoryPanel,
    setShowHistoryPanel,
    showChatPanel,
    setShowChatPanel,
    showLayerSwitcher,
    setShowLayerSwitcher,
    showCustomSymbolLibrary,
    setShowCustomSymbolLibrary,
    addActivity,
    triggerMapRefresh,
    setRoutePreferences,
    showRouteModeModal,
    setShowRouteModeModal,
    routeResult,
    editEnabled,
    userId,
    interactionMode,
    setInteractionMode,
  } = useGeoAgent()

  const [isCapturing, setIsCapturing] = useState(false)
  const [isSnapshotting, setIsSnapshotting] = useState(false)
  const [isResetting, setIsResetting] = useState(false)
  const [isRegeneratingOpord, setIsRegeneratingOpord] = useState(false)
  const [toast, setToast] = useState(null)
  const [showSnapshotModal, setShowSnapshotModal] = useState(false)
  const [showResetModal, setShowResetModal] = useState(false)
  const [showToolsModal, setShowToolsModal] = useState(false)
  const [snapshotName, setSnapshotName] = useState('')

  // Auto-hide toast after 2.5 seconds
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 2500)
      return () => clearTimeout(timer)
    }
  }, [toast])

  const handleOpenSnapshotModal = () => {
    setSnapshotName('')
    setShowSnapshotModal(true)
  }

  const handleCancelSnapshot = () => {
    setShowSnapshotModal(false)
    setSnapshotName('')
  }

  const handleCaptureMap = async () => {
    setIsCapturing(true)
    try {
      if (!mapRef?.current) {
        setToast({ success: false, message: 'Map not ready' })
        addActivity?.('Map not ready', 'error')
        return
      }

      const canvas = mapRef.current.getCanvas()
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
          if (blob) resolve(blob)
          else reject(new Error('Failed to create image blob'))
        }, 'image/png')
      })

      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      downloadBlob(blob, `map-screenshot-${timestamp}.png`)
      setToast({ success: true, message: 'Map screenshot downloaded' })
      addActivity?.('Map screenshot downloaded', 'success')
    } catch (err) {
      console.error('Failed to capture map:', err)
      setToast({ success: false, message: `Failed: ${err.message}` })
      addActivity?.(`Failed to capture map: ${err.message}`, 'error')
    } finally {
      setIsCapturing(false)
    }
  }

  const handleReset = async () => {
    setShowResetModal(false)
    setIsResetting(true)
    
    try {
      const response = await fetch(`${apiUrl}/maps/${mapId}/clear`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Failed to clear map: ${response.status}`)
      }
      
      const result = await response.json()
      const message = `Cleared ${result.entities_deleted} entities and ${result.overlays_deleted} overlays`
      setToast({ success: true, message })
      addActivity?.(message, 'success')
      
      // Clear route state and layers
      setRoutePlanMode(false)
      setRouteStart(null)
      setRouteEnd(null)
      setRouteResult(null)
      setShowRoutePanel(false)
      cleanupRouteLayers(mapRef?.current)
      
      // Refresh the map to show empty state
      triggerMapRefresh?.()
    } catch (err) {
      console.error('Failed to reset map:', err)
      setToast({ success: false, message: `Failed: ${err.message}` })
      addActivity?.(`Failed to reset map: ${err.message}`, 'error')
    } finally {
      setIsResetting(false)
    }
  }

  // Regenerate scenario from OPORD/FRAGOs. Hits the pytho-app backend
  // (relative /api/scenario/... — nginx-proxied to pytho-app, not
  // geo-agent). Blocks 30-90s while Gemma4 parses the docs and writes the
  // operations overlay back to the geo-agent master map. Triggers a map
  // refresh on success so the new overlay renders without page reload.
  const handleRegenerateFromOpord = async () => {
    setIsRegeneratingOpord(true)
    try {
      addActivity?.('Parsing OPORD/FRAGOs…', 'info')
      const resp = await fetch('/api/scenario/regenerate-from-opord', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (!resp.ok) {
        let detail = ''
        try {
          const body = await resp.json()
          detail = body?.detail?.error || body?.detail || JSON.stringify(body).slice(0, 200)
        } catch (_) {
          detail = await resp.text().catch(() => '')
        }
        throw new Error(`HTTP ${resp.status}: ${detail || 'parse failed'}`)
      }
      const result = await resp.json()
      const cmCount = result?.overlay_summary?.total ?? 0
      const civilCount = result?.civil_count ?? 0
      const phasesCount = (result?.phases || []).length
      const docs = (result?.source_docs || []).join(', ')
      const message = `OPORD parsed: ${cmCount} control measures, ${civilCount} civil entities, ${phasesCount} phases (from ${docs})`
      setToast({ success: true, message })
      addActivity?.(message, 'success')
      // Pull the new overlay onto the visible map.
      triggerMapRefresh?.()
    } catch (err) {
      console.error('Regenerate-from-OPORD failed:', err)
      setToast({ success: false, message: `Regenerate failed: ${err.message}` })
      addActivity?.(`Regenerate from OPORD failed: ${err.message}`, 'error')
    } finally {
      setIsRegeneratingOpord(false)
    }
  }

  const handleSnapshotAndCapture = async () => {
    setShowSnapshotModal(false)
    setIsSnapshotting(true)
    
    const name = snapshotName.trim()
    const sanitizedName = name 
      ? name.replace(/[^a-zA-Z0-9-_\s]/g, '').replace(/\s+/g, '-').toLowerCase()
      : new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    
    try {
      // 1. Create API snapshot
      const snapshotPromise = fetch(`${apiUrl}/maps/${mapId}/snapshots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: name || `Snapshot ${new Date().toLocaleString()}`,
          // Snapshots are PERSONAL save points of the shared map —
          // created_by is the ownership key the history list filters
          // on (the old literal 'user' made ownership untrackable).
          created_by: userId || 'unknown'
        })
      })

      // 2. Capture screenshot. The WebGL canvas alone is NOT the map
      // the analyst sees — unit glyphs, doctrinal graphic styling, and
      // labels are painted by the SVG paint pass (MapDoctrinalPaint)
      // as DOM overlays. Composite the canvas plus every overlay SVG
      // inside the map container into one image, or the download ships
      // without a single unit symbol on it.
      let screenshotSuccess = false
      if (mapRef?.current) {
        try {
          const map = mapRef.current
          // Fresh frame right before reading pixels — a stale WebGL
          // buffer reads back blank on some drivers.
          map.triggerRepaint()
          await new Promise((resolve) => map.once('render', resolve))
          const canvas = map.getCanvas()
          const out = document.createElement('canvas')
          out.width = canvas.width
          out.height = canvas.height
          const ctx = out.getContext('2d')
          ctx.drawImage(canvas, 0, 0)

          const canvasRect = canvas.getBoundingClientRect()
          const scaleX = canvas.width / canvasRect.width
          const scaleY = canvas.height / canvasRect.height
          const svgs = map.getContainer().querySelectorAll('svg')
          for (const svg of svgs) {
            const rect = svg.getBoundingClientRect()
            if (!rect.width || !rect.height) continue
            const clone = svg.cloneNode(true)
            clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
            clone.setAttribute('width', String(rect.width))
            clone.setAttribute('height', String(rect.height))
            const url = URL.createObjectURL(
              new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' })
            )
            try {
              const img = await new Promise((resolve, reject) => {
                const i = new Image()
                i.onload = () => resolve(i)
                i.onerror = reject
                i.src = url
              })
              ctx.drawImage(
                img,
                (rect.left - canvasRect.left) * scaleX,
                (rect.top - canvasRect.top) * scaleY,
                rect.width * scaleX,
                rect.height * scaleY
              )
            } catch (svgErr) {
              // One unrasterizable overlay must not sink the capture.
              console.warn('screenshot: svg overlay skipped', svgErr)
            } finally {
              URL.revokeObjectURL(url)
            }
          }

          const blob = await new Promise((resolve, reject) => {
            out.toBlob((blob) => {
              if (blob) resolve(blob)
              else reject(new Error('Failed to create image blob'))
            }, 'image/png')
          })
          downloadBlob(blob, `map-${sanitizedName}.png`)
          screenshotSuccess = true
        } catch (err) {
          console.error('Failed to capture screenshot:', err)
        }
      }

      // 3. Wait for snapshot API response
      const response = await snapshotPromise
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Failed to create snapshot: ${response.status}`)
      }

      const snapshot = await response.json()
      logAnalystEvent({
        event_type: 'map.snapshot_saved',
        map_id: mapId ? String(mapId) : null,
        surface: 'map_controls',
        detail: { version: snapshot.version, label: name || null },
      })
      const message = screenshotSuccess
        ? `Snapshot "${name || `v${snapshot.version}`}" saved & screenshot downloaded`
        : `Snapshot "${name || `v${snapshot.version}`}" created`
      setToast({ success: true, message })
      addActivity?.(message, 'success')
    } catch (err) {
      console.error('Failed to create snapshot:', err)
      setToast({ success: false, message: `Failed: ${err.message}` })
      addActivity?.(`Failed to create snapshot: ${err.message}`, 'error')
    } finally {
      setIsSnapshotting(false)
      setSnapshotName('')
    }
  }

  return (
    <>
      {toast && (
        <div 
          className={`map-toast ${toast.success ? 'success' : 'error'}`}
          style={{
            position: 'absolute',
            top: '60px',
            left: '50%',
            transform: 'translateX(-50%)',
            background: toast.success ? 'rgba(39, 174, 96, 0.95)' : 'rgba(231, 76, 60, 0.95)',
            color: 'white',
            padding: '10px 20px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '500',
            zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            animation: 'fadeInOut 2.5s ease-in-out'
          }}
        >
          {toast.success ? '✓ ' : '✗ '}{toast.message}
        </div>
      )}
      
      {/* Snapshot Name Modal */}
      {showSnapshotModal && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 2000
          }}
          onClick={handleCancelSnapshot}
        >
          <div 
            style={{
              background: '#1e1e1e',
              borderRadius: '8px',
              padding: '20px',
              minWidth: '320px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              border: '1px solid #333'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ 
              margin: '0 0 16px 0', 
              color: '#fff', 
              fontSize: '16px',
              fontWeight: '500'
            }}>
              Save Map Snapshot
            </h3>
            <input
              type="text"
              value={snapshotName}
              onChange={(e) => setSnapshotName(e.target.value)}
              placeholder="Enter snapshot name..."
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && snapshotName.trim()) {
                  handleSnapshotAndCapture()
                } else if (e.key === 'Escape') {
                  handleCancelSnapshot()
                }
              }}
              style={{
                width: '100%',
                padding: '10px 12px',
                fontSize: '14px',
                border: '1px solid #444',
                borderRadius: '6px',
                background: '#2a2a2a',
                color: '#fff',
                outline: 'none',
                boxSizing: 'border-box'
              }}
            />
            <div style={{ 
              display: 'flex', 
              gap: '10px', 
              marginTop: '16px',
              justifyContent: 'flex-end'
            }}>
              <button
                onClick={handleCancelSnapshot}
                style={{
                  padding: '8px 16px',
                  fontSize: '14px',
                  border: 'none',
                  borderRadius: '6px',
                  background: '#666',
                  color: 'white',
                  cursor: 'pointer',
                  fontWeight: '500'
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSnapshotAndCapture}
                disabled={!snapshotName.trim()}
                style={{
                  padding: '8px 16px',
                  fontSize: '14px',
                  border: 'none',
                  borderRadius: '6px',
                  background: snapshotName.trim() ? '#3B82F6' : '#555',
                  color: snapshotName.trim() ? '#fff' : '#888',
                  cursor: snapshotName.trim() ? 'pointer' : 'not-allowed',
                  fontWeight: '500',
                  opacity: snapshotName.trim() ? 1 : 0.6
                }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reset Confirmation Modal */}
      {showResetModal && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 2000
          }}
          onClick={() => setShowResetModal(false)}
        >
          <div 
            style={{
              background: '#1e1e1e',
              borderRadius: '8px',
              padding: '20px',
              minWidth: '320px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              border: '1px solid #333'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ 
              margin: '0 0 12px 0', 
              color: '#fff', 
              fontSize: '16px',
              fontWeight: '500'
            }}>
              Reset Map
            </h3>
            <p style={{
              margin: '0 0 20px 0',
              color: '#aaa',
              fontSize: '14px',
              lineHeight: '1.5'
            }}>
              This will permanently delete all entities and overlays from the map. This action cannot be undone.
            </p>
            <div style={{ 
              display: 'flex', 
              gap: '10px', 
              justifyContent: 'flex-end'
            }}>
              <button
                onClick={() => setShowResetModal(false)}
                style={{
                  padding: '8px 16px',
                  fontSize: '14px',
                  border: 'none',
                  borderRadius: '6px',
                  background: '#666',
                  color: 'white',
                  cursor: 'pointer',
                  fontWeight: '500'
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleReset}
                style={{
                  padding: '8px 16px',
                  fontSize: '14px',
                  border: 'none',
                  borderRadius: '6px',
                  background: '#3B82F6',
                  color: 'white',
                  cursor: 'pointer',
                  fontWeight: '500'
                }}
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Tools Modal */}
      {showToolsModal && (
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
          onClick={() => setShowToolsModal(false)}
        >
          <div 
            style={{
              background: '#1e1e1e',
              borderRadius: '12px',
              padding: '24px',
              minWidth: '340px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              border: '1px solid #333',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: '0 0 4px 0', color: '#fff', fontSize: '16px', fontWeight: '600' }}>
              Tools
            </h3>
            <p style={{ margin: '0 0 16px 0', color: '#888', fontSize: '13px' }}>
              Select a tool to use on the map.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[
                // Place Unit + Draw Overlay are available on EVERY
                // surface — the live map edits analyst-authored content
                // (pipeline rows stay inspect-only via the provenance
                // boundary in useMapEvents.isPipelineOwned).
                {
                  label: 'Place Unit',
                  desc: 'Click map to place a military unit symbol',
                  icon: '◇',
                  onClick: () => {
                    setShowToolsModal(false)
                    setPlacementMode(true)
                    setShowOverlayToolbar(false)
                    setOverlayDrawMode(false)
                    setMeasureMode(false)
                    setMeasurePoints([])
                  },
                },
                {
                  label: 'Draw Overlay',
                  desc: 'Draw tactical graphics and control measures',
                  icon: (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M2 15 A10 10 0 0 1 22 15"/>
                      <path d="M4 8 L7 12"/>
                      <path d="M12 4 L12 10"/>
                      <path d="M20 8 L17 12"/>
                    </svg>
                  ),
                  onClick: () => {
                    setShowToolsModal(false)
                    setShowOverlayToolbar(true)
                    setPlacementMode(false)
                    setMeasureMode(false)
                    setMeasurePoints([])
                  },
                },
                {
                  label: 'Measure Distance',
                  desc: 'Click two points to measure distance between them',
                  icon: (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="2" y="8" width="20" height="8" rx="1"/>
                      <path d="M6 8v3"/><path d="M10 8v5"/><path d="M14 8v3"/><path d="M18 8v5"/>
                    </svg>
                  ),
                  onClick: () => {
                    setShowToolsModal(false)
                    setMeasureMode(true)
                    setMeasurePoints([])
                    setPlacementMode(false)
                    setShowOverlayToolbar(false)
                    setOverlayDrawMode(false)
                  },
                },
                {
                  label: 'Plan Route',
                  desc: 'Select route type, then click two points on the map',
                  icon: (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="5" cy="6" r="3"/><circle cx="19" cy="18" r="3"/>
                      <path d="M5 9v3a4 4 0 0 0 4 4h6a4 4 0 0 0 4-4V9"/>
                    </svg>
                  ),
                  onClick: () => {
                    setShowToolsModal(false)
                    setShowRouteModeModal(true)
                  },
                },
              ].map(({ label, desc, icon, onClick }) => (
                <button
                  key={label}
                  onClick={onClick}
                  style={{
                    padding: '12px 16px',
                    fontSize: '14px',
                    border: '1px solid #444',
                    borderRadius: '8px',
                    background: '#2a2a3e',
                    color: '#fff',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all 0.15s',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = '#3a3a5e'
                    e.currentTarget.style.borderColor = '#3B82F6'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = '#2a2a3e'
                    e.currentTarget.style.borderColor = '#444'
                  }}
                >
                  <span style={{ fontSize: '18px', width: '24px', textAlign: 'center', flexShrink: 0, display: 'flex', justifyContent: 'center' }}>
                    {icon}
                  </span>
                  <div>
                    <div style={{ fontWeight: '600', marginBottom: '2px' }}>{label}</div>
                    <div style={{ fontSize: '11px', color: '#888', fontWeight: '400' }}>{desc}</div>
                  </div>
                </button>
              ))}
            </div>
            <button
              onClick={() => setShowToolsModal(false)}
              style={{
                marginTop: '16px', width: '100%', padding: '8px',
                fontSize: '13px', border: 'none', borderRadius: '6px',
                background: '#333', color: '#aaa', cursor: 'pointer',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Route Mode Selection Modal */}
      <RoutePlannerModal
        open={showRouteModeModal}
        onClose={() => setShowRouteModeModal(false)}
        onConfirm={async (mode, preferences) => {
          // Delete the old route before replanning with a new mode
          const oldRouteId = routeResult?.id
          if (oldRouteId) {
            const api = createApiClient(apiUrl)
            try { await api.deleteRoute(oldRouteId) } catch (_) {}
          }

          setRouteMode(mode)
          setRoutePreferences(preferences)
          setShowRouteModeModal(false)
          setPlacementMode(false)
          setShowOverlayToolbar(false)
          setOverlayDrawMode(false)
          setMeasureMode(false)
          setMeasurePoints([])
          setRouteResult(null)
          setShowRoutePanel(false)

          // If start/end exist (retry from failure modal), replan immediately
          // Pass mode + preferences directly to avoid stale closure
          if (routeStart && routeEnd && replanRoute) {
            replanRoute(routeStart, routeEnd, mode, preferences)
          } else {
            // Fresh planning — clear points and enter click-to-select mode
            setRouteStart(null)
            setRouteEnd(null)
            setRoutePlanMode(true)
          }
        }}
      />

      {/* Undo/Redo — bottom right. Shown on every surface: the live map
          fills the undo stack through analyst-authored drag/edit (the
          provenance boundary in useMapEvents.isPipelineOwned). */}
      {showUndoRedo && (
        <div className="undo-redo-controls">
          <button
            onClick={onUndo}
            disabled={!canUndo}
            title="Undo (Ctrl+Z)"
            className={`icon-btn ${!canUndo ? 'disabled' : ''}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="1 4 1 10 7 10"/>
              <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
            </svg>
          </button>
          <button
            onClick={onRedo}
            disabled={!canRedo}
            title="Redo (Ctrl+Y)"
            className={`icon-btn ${!canRedo ? 'disabled' : ''}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10"/>
              <path d="M20.49 15a9 9 0 1 1-2.13-9.36L23 10"/>
            </svg>
          </button>
        </div>
      )}

      {/* The echelon roll-up sliders live in the Tactical Overlays
          sidebar (OperationsMap.tsx), one per faction under the Units
          row's Faction group — no floating pill here. */}
      <div className="map-controls">
      <button onClick={onZoomIn} title="Zoom in">+</button>
      <button onClick={onZoomOut} title="Zoom out">−</button>
      {/* VIEW / EDIT interaction mode. View (default): every click is a
          placard, nothing drags — reading the map can never move a
          symbol. Edit: click-to-edit + drag-to-move. Edit-map deep-link
          sessions (editEnabled) are always edit mode; the toggle hides
          there. */}
      {!editEnabled && (
        <button
          onClick={() => {
            const next = interactionMode === 'edit' ? 'view' : 'edit'
            setInteractionMode(next)
            logAnalystEvent({
              event_type: 'map.interaction_mode',
              surface: 'map',
              user_id: userId ?? null,
              detail: { mode: next },
            })
            addActivity(next === 'edit'
              ? 'Edit mode — drag to move, click to edit'
              : 'View mode — click to inspect', 'info')
          }}
          title={interactionMode === 'edit'
            ? 'Edit mode ON — symbols drag and edit. Click for view mode.'
            : 'View mode — click to inspect. Click to enable editing.'}
          className={`icon-btn ${interactionMode === 'edit' ? 'active' : ''}`}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            {interactionMode === 'edit'
              ? <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
              : <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></>}
          </svg>
        </button>
      )}
      {/* Find-unit-by-name search pill — sits in the right control column,
          directly under the zoom buttons. */}
      <MapSearchControl />
      {/* Entity graph — the network/hierarchy view of units, facilities,
          and their relationships. Lives in the control stack (square
          style, clear of the bottom-left MGRS readout); opens the
          GraphLinkView via the window event OperationsMap listens for. */}
      {mapId && (
        <button
          onClick={() => window.dispatchEvent(new CustomEvent('geoagent:openLinkView'))}
          title="Entity graph — units, facilities, and their relationships"
          className="icon-btn"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="5.5" cy="6" r="2.3"/><circle cx="18.5" cy="6" r="2.3"/><circle cx="12" cy="18.5" r="2.3"/>
            <path d="M7.2 7.4 L10.6 16.4"/><path d="M16.8 7.4 L13.4 16.4"/><path d="M7.8 6 h8.4"/>
          </svg>
        </button>
      )}
      {/* Tools button — opens modal with Place Unit, Draw Overlay, Measure, Route */}
      <button 
        onClick={() => {
          // If any tool is active, cancel it
          if (placementMode || showOverlayToolbar || overlayDrawMode || measureMode || routePlanMode) {
            setPlacementMode(false)
            if (showOverlayToolbar || overlayDrawMode) {
              setShowOverlayToolbar(false)
              setOverlayDrawMode(false)
              if (onExitOverlayDrawMode) onExitOverlayDrawMode()
            }
            setMeasureMode(false)
            setMeasurePoints([])
            if (routePlanMode) {
              setRoutePlanMode(false)
              setRouteStart(null)
              setRouteEnd(null)
              setRouteResult(null)
              setShowRoutePanel(false)
            }
          } else {
            setShowToolsModal(true)
          }
        }} 
        title={placementMode || showOverlayToolbar || overlayDrawMode || measureMode || routePlanMode ? "Cancel active tool" : "Tools"}
        className={`icon-btn ${placementMode || showOverlayToolbar || overlayDrawMode || measureMode || routePlanMode ? 'active' : ''}`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
        </svg>
      </button>
      <button
        onClick={() => setShowLayerSwitcher(!showLayerSwitcher)}
        title={showLayerSwitcher ? "Close layers" : "Map layers"}
        className={`icon-btn ${showLayerSwitcher ? 'active' : ''}`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="12 2 2 7 12 12 22 7 12 2"/>
          <polyline points="2 17 12 22 22 17"/>
          <polyline points="2 12 12 17 22 12"/>
        </svg>
      </button>
      <button
        onClick={() => setShowCustomSymbolLibrary(!showCustomSymbolLibrary)}
        title={showCustomSymbolLibrary ? "Close custom symbols" : "Custom symbols"}
        className={`icon-btn ${showCustomSymbolLibrary ? 'active' : ''}`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1"/>
          <rect x="14" y="3" width="7" height="7" rx="1"/>
          <rect x="3" y="14" width="7" height="7" rx="1"/>
          <path d="M17.5 14v7"/>
          <path d="M14 17.5h7"/>
        </svg>
      </button>
      <button
        onClick={handleOpenSnapshotModal}
        disabled={isSnapshotting}
        title="Save snapshot & download screenshot"
        className="icon-btn"
      >
        {isSnapshotting ? '…' : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
            <circle cx="12" cy="13" r="4"/>
          </svg>
        )}
      </button>
      <button
        onClick={() => setShowHistoryPanel(!showHistoryPanel)}
        title={showHistoryPanel ? "Close history" : "View snapshot history"}
        className={`icon-btn ${showHistoryPanel ? 'active' : ''}`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
      </button>
      {/* Map agent toggle — the panel opens as a right column ONLY while
          in use; no reserved gutter when closed (a collapsed rail wasted
          40px of map). */}
      <button
        data-testid="map-agent-toggle"
        onClick={() => setShowChatPanel(!showChatPanel)}
        title={showChatPanel ? "Close agent" : "Open agent"}
        className={`icon-btn ${showChatPanel ? 'active' : ''}`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
      {/* Regenerate scenario from authoritative OPORD/FRAGOs. Distinct green
          color so analysts know this is a "rebuild from source" action, not a
          routine view change. Blocks 30-90s while the model parses. The tool
          tip used to mention "(Gemma4)" — removed per the no-system-internals-
          in-analyst-UI rule. */}
      {editEnabled && (
      <button
        onClick={handleRegenerateFromOpord}
        disabled={isRegeneratingOpord}
        title="Regenerate operations overlay from OPORD/FRAGOs"
        className="icon-btn"
        style={{
          background: isRegeneratingOpord ? '#1e5a2e' : '#27ae60',
          borderColor: '#1e8449',
          color: '#fff',
        }}
      >
        {isRegeneratingOpord ? '…' : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="23 4 23 10 17 10"/>
            <polyline points="1 20 1 14 7 14"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
        )}
      </button>
      )}
      {/* Chat toggle removed: the operations-map chat is now the shared
          #operationalmap IRC room, presented as a self-collapsing side
          panel (OperationsMap.tsx) that mirrors the doc-editor ChatAgent
          UI and owns its own open/close affordance. No toolbar button. */}
      {editEnabled && (
      <button
        onClick={() => setShowResetModal(true)}
        disabled={isResetting}
        title="Reset map (clear all entities and overlays)"
        className="icon-btn reset-btn"
      >
        {isResetting ? '…' : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            <line x1="10" y1="11" x2="10" y2="17"/>
            <line x1="14" y1="11" x2="14" y2="17"/>
          </svg>
        )}
      </button>
      )}
    </div>
    </>
  )
}
