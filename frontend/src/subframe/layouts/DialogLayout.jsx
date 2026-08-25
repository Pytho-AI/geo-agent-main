import React from 'react'

export function DialogLayout({ open, onOpenChange, children }) {
  if (!open) return null
  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{ position: 'fixed', inset: 0, zIndex: 1000,
               background: 'rgba(0,0,0,0.4)',
               display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onOpenChange?.(false)
      }}
    >
      <div style={{ maxWidth: 640, width: 'calc(100% - 32px)', maxHeight: '80vh',
                    overflow: 'auto', background: '#fff', borderRadius: 8,
                    padding: 24, boxShadow: '0 10px 30px rgba(0,0,0,0.2)' }}>
        {children}
      </div>
    </div>
  )
}
