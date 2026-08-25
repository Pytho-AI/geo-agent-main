import React from 'react'

export function Button({ children, className = '', variant = 'brand-primary',
                         loading = false, disabled = false, onClick, ...rest }) {
  const style = variant === 'brand-primary'
    ? { background: '#1e40af', color: '#fff', border: '1px solid #1e3a8a' }
    : { background: '#ffffff', color: '#111', border: '1px solid #ccc' }
  return (
    <button
      type="button"
      className={className}
      style={{ padding: '6px 12px', borderRadius: 4, cursor: 'pointer',
               opacity: disabled || loading ? 0.6 : 1, ...style }}
      disabled={disabled || loading}
      onClick={onClick}
      {...rest}
    >
      {loading ? 'Working…' : children}
    </button>
  )
}
