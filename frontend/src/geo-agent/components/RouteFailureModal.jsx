/**
 * RouteFailureModal — shows diagnostic info when the route planner
 * cannot find a path.  Styled to match RoutePlannerModal.
 */

import React from 'react'
import { useGeoAgent } from '../GeoAgentProvider'

export function RouteFailureModal() {
  const {
    routeDiagnostic,
    setRouteDiagnostic,
    setRoutePlanMode,
    setRouteStart,
    setRouteEnd,
    setShowRouteModeModal,
  } = useGeoAgent()

  if (!routeDiagnostic) return null

  const { message, diagnostic } = routeDiagnostic

  const handleDismiss = () => {
    setRouteDiagnostic(null)
    setRouteStart(null)
    setRouteEnd(null)
    setRoutePlanMode(false)
  }

  const handleRetry = () => {
    // Close diagnostic and reopen the planner modal so the user
    // can adjust preferences — start/end points are preserved.
    setRouteDiagnostic(null)
    setRoutePlanMode(false)
    setShowRouteModeModal(true)
  }

  const reachPct = diagnostic
    ? Math.round((diagnostic.reachable_from_start / Math.max(diagnostic.total_tiles, 1)) * 100)
    : 0

  return (
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
      onClick={handleDismiss}
    >
      <div
        style={{
          background: '#1e1e1e',
          borderRadius: '12px',
          padding: '24px',
          width: '400px',
          maxHeight: '85vh',
          overflowY: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          border: '1px solid #333',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
          <span style={{
            width: '28px', height: '28px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            borderRadius: '6px',
            background: '#EF444422',
            color: '#EF4444',
            flexShrink: 0,
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </span>
          <h3 style={{ margin: 0, color: '#fff', fontSize: '16px', fontWeight: '600' }}>
            Route Not Found
          </h3>
        </div>
        <p style={{ margin: '0 0 16px 0', color: '#888', fontSize: '13px' }}>
          {message || 'No route could be found between these points.'}
        </p>

        {diagnostic && (
          <div style={{
            padding: '14px',
            background: '#161622',
            borderRadius: '8px',
            border: '1px solid #2a2a3e',
          }}>
            {/* Reachability gauge */}
            <div style={{ marginBottom: '14px' }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                marginBottom: '6px',
              }}>
                <span style={{ fontSize: '12px', color: '#aaa', fontWeight: '600' }}>
                  Search Coverage
                </span>
                <span style={{ fontSize: '12px', color: '#3B82F6', fontWeight: '600' }}>
                  {reachPct}%
                </span>
              </div>
              <div style={{
                height: '8px', borderRadius: '4px',
                background: '#333', overflow: 'hidden',
              }}>
                <div style={{
                  width: `${reachPct}%`, height: '100%',
                  background: reachPct < 20 ? '#EF4444' : reachPct < 60 ? '#F59E0B' : '#10B981',
                  borderRadius: '4px',
                  transition: 'width 0.3s',
                }} />
              </div>
              <div style={{ fontSize: '10px', color: '#666', marginTop: '4px' }}>
                {reachPct < 20
                  ? 'Start point is nearly surrounded by obstacles'
                  : reachPct < 60
                    ? 'Search reached some area but was blocked before the destination'
                    : 'Searched most of the area but the destination remains unreachable'}
              </div>
            </div>

            {/* Suggestions */}
            {diagnostic.suggestions?.length > 0 && (
              <div>
                <div style={{ fontSize: '11px', color: '#888', marginBottom: '6px', fontWeight: '500' }}>
                  Suggestions
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {diagnostic.suggestions.map((s, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex', alignItems: 'flex-start', gap: '8px',
                        padding: '8px 10px',
                        background: '#1a1a2e',
                        borderRadius: '6px',
                        border: '1px solid #333',
                        fontSize: '12px', color: '#ccc',
                        lineHeight: '1.4',
                      }}
                    >
                      <span style={{ color: '#3B82F6', flexShrink: 0, marginTop: '1px' }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="12" cy="12" r="10" />
                          <path d="M12 16v-4" />
                          <path d="M12 8h.01" />
                        </svg>
                      </span>
                      <span>{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
          <button
            onClick={handleDismiss}
            style={{
              flex: 1,
              padding: '10px',
              fontSize: '13px',
              border: 'none',
              borderRadius: '6px',
              background: '#333',
              color: '#aaa',
              cursor: 'pointer',
              fontWeight: '500',
            }}
          >
            Dismiss
          </button>
          <button
            onClick={handleRetry}
            style={{
              flex: 1,
              padding: '10px',
              fontSize: '13px',
              border: 'none',
              borderRadius: '6px',
              background: '#3B82F6',
              color: '#fff',
              cursor: 'pointer',
              fontWeight: '600',
              transition: 'all 0.15s',
            }}
          >
            Try Again
          </button>
        </div>
      </div>
    </div>
  )
}
