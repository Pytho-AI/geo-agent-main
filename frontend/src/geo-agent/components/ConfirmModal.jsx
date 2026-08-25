/**
 * ConfirmModal — THE confirmation dialog for the map UI.
 *
 * Browser popups (window.confirm / alert / prompt) are banned in every
 * Pytho surface; anything that needs a yes/no goes through
 * GeoAgentProvider.requestConfirm(), which this single mounted modal
 * renders. Styling matches the reset-map modal in MapControls.
 */

import React, { useEffect } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'

export function ConfirmModal() {
  const { confirmRequest, resolveConfirm } = useGeoAgent()

  // Escape cancels — listener lives only while a request is open.
  useEffect(() => {
    if (!confirmRequest) return undefined
    const onKey = (e) => { if (e.key === 'Escape') resolveConfirm(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [confirmRequest, resolveConfirm])

  if (!confirmRequest) return null

  return (
    <div
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 2000,
      }}
      onClick={() => resolveConfirm(false)}
    >
      <div
        style={{
          background: '#1e1e1e', borderRadius: '8px', padding: '20px',
          minWidth: '320px', maxWidth: '440px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)', border: '1px solid #333',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 12px 0', color: '#fff', fontSize: '16px', fontWeight: '500' }}>
          {confirmRequest.title}
        </h3>
        <p style={{ margin: '0 0 20px 0', color: '#aaa', fontSize: '14px', lineHeight: '1.5' }}>
          {confirmRequest.message}
        </p>
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button
            onClick={() => resolveConfirm(false)}
            style={{
              padding: '8px 16px', fontSize: '14px', border: 'none',
              borderRadius: '6px', background: '#666', color: 'white',
              cursor: 'pointer', fontWeight: '500',
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => resolveConfirm(true)}
            style={{
              padding: '8px 16px', fontSize: '14px', border: 'none',
              borderRadius: '6px', background: '#c0392b', color: 'white',
              cursor: 'pointer', fontWeight: '500',
            }}
          >
            {confirmRequest.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
