import React from 'react'

export function IconButton({ icon = '', size = 'medium', onClick, ...rest }) {
  const dim = size === 'small' ? 24 : size === 'large' ? 40 : 32
  return (
    <button
      type="button"
      style={{ width: dim, height: dim, background: 'transparent',
               border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer',
               display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClick}
      aria-label={icon}
      {...rest}
    >
      {icon === 'FeatherX' ? '×' : '•'}
    </button>
  )
}
