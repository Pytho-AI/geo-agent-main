import React from 'react'

export function IconWithBackground({ variant = 'neutral', size = 'medium', icon = '' }) {
  const dim = size === 'small' ? 24 : size === 'large' ? 48 : 32
  const bg = variant === 'warning' ? '#fef3c7' : variant === 'error' ? '#fee2e2' : '#e5e7eb'
  const fg = variant === 'warning' ? '#b45309' : variant === 'error' ? '#b91c1c' : '#374151'
  return (
    <div style={{ width: dim, height: dim, background: bg, color: fg,
                  borderRadius: 6, display: 'inline-flex',
                  alignItems: 'center', justifyContent: 'center', fontSize: dim * 0.55 }}
         aria-label={icon}>
      {icon === 'FeatherAlertTriangle' ? '⚠' : '•'}
    </div>
  )
}
