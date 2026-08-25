import React from 'react'

// Minimal SubframeCore.Icon stub — feather-style glyphs rendered as
// UTF chars. Enough for OperationsMap chrome (layers, chevrons,
// message-square, etc.) inside the iframe.
const GLYPHS = {
  FeatherLayers: '⧉',
  FeatherChevronLeft: '‹',
  FeatherChevronRight: '›',
  FeatherChevronDown: '⌄',
  FeatherChevronUp: '˄',
  FeatherMessageSquare: '💬',
  FeatherX: '×',
  FeatherAlertTriangle: '⚠',
  FeatherCheck: '✓',
  FeatherPlus: '＋',
  FeatherMinus: '−',
  FeatherEye: '👁',
  FeatherEyeOff: '🚫',
  FeatherSettings: '⚙',
  FeatherRefreshCw: '↻',
  FeatherEdit: '✎',
  FeatherTrash: '🗑',
  FeatherSearch: '🔍',
  FeatherMap: '🗺',
  FeatherMapPin: '📍',
  FeatherClock: '🕒',
  FeatherFile: '📄',
  FeatherUser: '👤',
}

export function Icon({ name = '', className = '', style = {}, ...rest }) {
  const glyph = GLYPHS[name] || '•'
  return (
    <span
      className={className}
      style={{ display: 'inline-block', minWidth: '1em', textAlign: 'center', ...style }}
      aria-label={name}
      {...rest}
    >
      {glyph}
    </span>
  )
}

export default { Icon }
