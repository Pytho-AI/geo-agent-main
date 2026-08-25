/**
 * History Panel component for viewing map snapshots
 * 
 * Displays a list of all snapshots for the current map in chronological order
 */

import React, { useState, useEffect } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { logAnalystEvent } from '../../lib/analystEvent'
import { DialogLayout } from '../../subframe/layouts/DialogLayout'
import { Button } from '../../subframe/components/Button'
import { IconButton } from '../../subframe/components/IconButton'
import { IconWithBackground } from '../../subframe/components/IconWithBackground'

/**
 * Format date for display
 */
function formatDate(dateString) {
  if (!dateString) return ''
  const date = new Date(dateString)
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

/**
 * Snapshot card component
 */
function SnapshotCard({ snapshot, isExpanded, onToggle, onRestore, isRestoring }) {
  const [showConfirm, setShowConfirm] = useState(false)
  const entitiesCount = snapshot.entities_snapshot?.length || 0
  const overlaysCount = snapshot.overlays_snapshot?.length || 0
  const routesCount = snapshot.routes_snapshot?.length || 0

  const handleRestore = (e) => {
    e.stopPropagation()
    setShowConfirm(true)
  }

  return (
    <>
    <DialogLayout open={showConfirm} onOpenChange={setShowConfirm}>
      <div className="flex h-full w-full items-start gap-2">
        <div className="flex grow shrink-0 basis-0 items-start gap-4">
          <div className="flex grow shrink-0 basis-0 flex-col items-start self-stretch overflow-hidden rounded-md border border-solid border-neutral-border bg-default-background shadow-sm">
            <div className="flex w-full items-center justify-between bg-neutral-100 pl-6 pr-2 py-2">
              <span className="text-caption-bold font-caption-bold text-default-font">
                Restore Snapshot
              </span>
              <IconButton
                size="small"
                icon="FeatherX"
                onClick={() => setShowConfirm(false)}
              />
            </div>
            <div className="flex w-full grow shrink-0 basis-0 flex-col items-start gap-6 px-6 py-6">
              <div className="flex w-full items-center gap-3">
                <IconWithBackground
                  variant="warning"
                  size="medium"
                  icon="FeatherAlertTriangle"
                />
                <div className="flex grow shrink-0 basis-0 flex-col items-start gap-1">
                  <span className="text-heading-3 font-heading-3 text-default-font">
                    Restore to v{snapshot.version}?
                  </span>
                  <span className="text-body font-body text-default-font">
                    This will replace all current entities, overlays, and routes with the snapshot state.
                  </span>
                </div>
              </div>
              <div className="flex w-full items-center justify-end gap-2">
                <Button
                  className="h-8 grow shrink-0 basis-0"
                  variant="neutral-secondary"
                  onClick={() => setShowConfirm(false)}
                  disabled={isRestoring}
                >
                  Cancel
                </Button>
                <Button
                  className="h-8 grow shrink-0 basis-0"
                  variant="brand-primary"
                  onClick={() => {
                    setShowConfirm(false)
                    onRestore(snapshot)
                  }}
                  loading={isRestoring}
                >
                  Restore
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </DialogLayout>
    <div className={`snapshot-card ${isExpanded ? 'expanded' : ''}`}>
      <div className="snapshot-header" onClick={onToggle}>
        <div className="snapshot-version">v{snapshot.version}</div>
        <div className="snapshot-info">
          <div className="snapshot-label">{snapshot.label || `Snapshot ${snapshot.version}`}</div>
          <div className="snapshot-date">{formatDate(snapshot.created_at)}</div>
        </div>
        <div className="snapshot-toggle">{isExpanded ? '−' : '+'}</div>
      </div>
      
      {isExpanded && (
        <div className="snapshot-details">
          <div className="snapshot-stats">
            <div className="snapshot-stat">
              <span className="stat-icon">◇</span>
              <span className="stat-value">{entitiesCount}</span>
              <span className="stat-label">entities</span>
            </div>
            <div className="snapshot-stat">
              <span className="stat-icon">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
                  <path d="M2 15 A10 10 0 0 1 22 15"/>
                  <path d="M4 8 L7 12"/>
                  <path d="M12 4 L12 10"/>
                  <path d="M20 8 L17 12"/>
                </svg>
              </span>
              <span className="stat-value">{overlaysCount}</span>
              <span className="stat-label">overlays</span>
            </div>
            <div className="snapshot-stat">
              <span className="stat-icon">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
                  <circle cx="5" cy="6" r="3"/>
                  <circle cx="19" cy="18" r="3"/>
                  <path d="M5 9v3a4 4 0 0 0 4 4h6a4 4 0 0 0 4-4V9"/>
                </svg>
              </span>
              <span className="stat-value">{routesCount}</span>
              <span className="stat-label">routes</span>
            </div>
          </div>
          
          <div className="snapshot-actions">
            <button 
              className="restore-btn"
              onClick={handleRestore}
              disabled={isRestoring}
              title="Restore map to this snapshot"
            >
              {isRestoring ? 'Restoring...' : 'Restore'}
            </button>
          </div>
        </div>
      )}
    </div>
    </>
  )
}

/**
 * Main History Panel component
 */
export function HistoryPanel() {
  const { apiUrl, mapId, mapRef, setShowHistoryPanel, addActivity, triggerMapRefresh, setBaseMapStyle, setLayerVisibility, userId } = useGeoAgent()
  
  const [snapshots, setSnapshots] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [isRestoring, setIsRestoring] = useState(false)
  
  // Fetch snapshots on mount
  useEffect(() => {
    const fetchSnapshots = async () => {
      setIsLoading(true)
      setError(null)
      
      try {
        // Personal history: each analyst sees THEIR OWN save points of
        // the shared event map (restore still applies to the shared map).
        const response = await fetch(
          `${apiUrl}/maps/${mapId}/snapshots${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`
        )
        
        if (!response.ok) {
          throw new Error(`Failed to fetch snapshots: ${response.status}`)
        }
        
        const data = await response.json()
        setSnapshots(data.snapshots || [])
      } catch (err) {
        console.error('Failed to fetch snapshots:', err)
        setError(err.message)
        addActivity?.(`Failed to load history: ${err.message}`, 'error')
      } finally {
        setIsLoading(false)
      }
    }
    
    fetchSnapshots()
  }, [apiUrl, mapId, userId, addActivity])
  
  // Fetch full snapshot details when expanded
  const handleToggleExpand = async (snapshot) => {
    if (expandedId === snapshot.id) {
      setExpandedId(null)
      return
    }
    
    // If we already have the full data, just expand
    if (snapshot.map_snapshot) {
      setExpandedId(snapshot.id)
      return
    }
    
    // Fetch full snapshot details
    try {
      const response = await fetch(`${apiUrl}/maps/${mapId}/snapshots/${snapshot.id}`)
      
      if (!response.ok) {
        throw new Error(`Failed to fetch snapshot details: ${response.status}`)
      }
      
      const fullSnapshot = await response.json()
      
      // Update the snapshot in the list with full data
      setSnapshots(prev => prev.map(s => 
        s.id === snapshot.id ? fullSnapshot : s
      ))
      
      setExpandedId(snapshot.id)
    } catch (err) {
      console.error('Failed to fetch snapshot details:', err)
      addActivity?.(`Failed to load snapshot details: ${err.message}`, 'error')
    }
  }
  
  // Restore map to a snapshot
  const handleRestore = async (snapshot) => {
    setIsRestoring(true)
    
    try {
      // First, fetch full snapshot details if we don't have map_snapshot
      let fullSnapshot = snapshot
      if (!snapshot.map_snapshot) {
        const detailsResponse = await fetch(`${apiUrl}/maps/${mapId}/snapshots/${snapshot.id}`)
        if (detailsResponse.ok) {
          fullSnapshot = await detailsResponse.json()
        }
      }
      
      // Call restore API
      const response = await fetch(`${apiUrl}/maps/${mapId}/snapshots/${snapshot.id}/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Failed to restore: ${response.status}`)
      }

      await response.json()

      logAnalystEvent({
        event_type: 'map.snapshot_restored',
        map_id: mapId ? String(mapId) : null,
        surface: 'history_panel',
        detail: { snapshot_id: String(snapshot.id), version: snapshot.version },
      })

      // Fly to the restored map viewport and apply restored layer preferences
      if (fullSnapshot.map_snapshot && mapRef?.current) {
        const { center_lng, center_lat, zoom, attrs } = fullSnapshot.map_snapshot
        if (center_lng != null && center_lat != null) {
          mapRef.current.flyTo({
            center: [center_lng, center_lat],
            zoom: zoom || mapRef.current.getZoom(),
            duration: 1500
          })
        }
        
        // Restore layer preferences from snapshot attrs
        if (attrs?.base_map_style) {
          setBaseMapStyle(attrs.base_map_style)
        }
        if (attrs?.layer_visibility) {
          setLayerVisibility(prev => ({ ...prev, ...attrs.layer_visibility }))
        }
      }
      
      // Trigger map data refresh to show restored entities/overlays
      triggerMapRefresh?.()
      
      addActivity?.(`Restored to snapshot v${snapshot.version}`, 'success')
      setShowHistoryPanel(false)
    } catch (err) {
      console.error('Failed to restore snapshot:', err)
      addActivity?.(`Failed to restore: ${err.message}`, 'error')
    } finally {
      setIsRestoring(false)
    }
  }
  
  return (
    <div className="history-panel">
      <div className="history-header">
        <h3>Map History</h3>
        <button 
          className="close-btn" 
          onClick={() => setShowHistoryPanel(false)}
          title="Close history"
        >
          ×
        </button>
      </div>
      
      <div className="history-content">
        {isLoading ? (
          <div className="history-loading">
            <div className="loading-spinner"></div>
            <span>Loading history...</span>
          </div>
        ) : error ? (
          <div className="history-error">
            <span className="error-icon">⚠</span>
            <span>{error}</span>
          </div>
        ) : snapshots.length === 0 ? (
          <div className="history-empty">
            <div className="empty-icon">📷</div>
            <p>No snapshots yet</p>
            <p className="empty-hint">Click the camera button to create your first snapshot</p>
          </div>
        ) : (
          <div className="snapshot-list">
            {snapshots.map(snapshot => (
              <SnapshotCard
                key={snapshot.id}
                snapshot={snapshot}
                isExpanded={expandedId === snapshot.id}
                onToggle={() => handleToggleExpand(snapshot)}
                onRestore={handleRestore}
                isRestoring={isRestoring}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
