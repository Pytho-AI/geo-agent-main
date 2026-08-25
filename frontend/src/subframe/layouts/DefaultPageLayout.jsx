import React from 'react'

// Iframe passthrough — the analyst-facing chrome (top nav, side rail)
// lives in the parent frame (pytho-app). Inside the iframe we just
// render children fullscreen so the map fills the viewport.
export function DefaultPageLayout({ children }) {
  return (
    <div style={{ width: '100%', height: '100vh', overflow: 'hidden',
                  display: 'flex', flexDirection: 'column',
                  background: '#0b1120', color: '#e6e6f0' }}>
      {children}
    </div>
  )
}
