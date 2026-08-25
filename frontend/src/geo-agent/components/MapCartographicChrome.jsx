/**
 * MapCartographicChrome — In-frame cartographic chrome for IBL map
 * products.
 *
 * Hosts the elements that belong INSIDE the map frame per ATP 2-01.3
 * doctrinal cartographic products:
 *   - Legend strip (ATP 2-01.3 fig 4-9: legend prints with the map)
 *   - North arrow (true / grid / magnetic)
 *   - Dual scale bar (km + mi)
 *
 * Elements that previously lived here but belong to the document layer
 * have moved out and are produced by the exporter's _render_header_block
 * (top + bottom classification banners, title block, prepared-by / DTG /
 * sheet / series / datum, AOI locator inset). Those appear in the doc
 * surrounding the <figure class="ibl-map-embed"> embed, not inside the
 * map figure itself.
 *
 * Mounted by BOTH OperationsMap (analyst editor) and OperationsMapHeadless
 * (export render). The chrome scales with the map container so the editor
 * preview matches the export PNG.
 *
 * Renders only for product_type in {MCOO, SITEMP, THREAT_OVERLAY}.
 * Inserted into `map.getCanvasContainer()` so the chrome lives inside
 * MapLibre's DOM stack, exactly like MapDoctrinalPaint.
 */

import React, { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useGeoAgent } from '../GeoAgentProvider'

// Match the whitespace→underscore-normalized uppercase product_type
// (pytho-app sends "Threat Overlay" → "THREAT_OVERLAY"; same
// normalization MapDoctrinalPaint uses).
const PRODUCT_TYPES_WITH_CHROME = new Set(['MCOO', 'SITEMP', 'THREAT_OVERLAY'])

// --- Legend SVG helpers --------------------------------------------------

function legendChevronSvg(w, h) {
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} xmlns="http://www.w3.org/2000/svg">
      <path
        d={`M 2 ${h / 2 - 4} L ${w - 8} ${h / 2 - 4} L ${w - 2} ${h / 2} L ${w - 8} ${h / 2 + 4} L 2 ${h / 2 + 4} Z`}
        fill="none"
        stroke="#000"
        strokeWidth="1.6"
      />
    </svg>
  )
}

function legendMobilityCorridorSvg(size) {
  if (size === 'bn') {
    return (
      <svg width="32" height="14" viewBox="0 0 32 14">
        <line x1="0" y1="4" x2="26" y2="4" stroke="#000" strokeWidth="1.4" />
        <line x1="0" y1="10" x2="26" y2="10" stroke="#000" strokeWidth="1.4" />
        <path d="M 26 1 L 31 7 L 26 13 z" fill="#000" />
      </svg>
    )
  }
  return (
    <svg width="32" height="14" viewBox="0 0 32 14">
      <line x1="0" y1="7" x2="26" y2="7" stroke="#000" strokeWidth="1.2" />
      <path d="M 26 3 L 31 7 L 26 11 z" fill="#000" />
    </svg>
  )
}

// Hatch-pattern swatch matching the on-map graphics-pat-* fill patterns.
function makePatternSwatchDataUrl(patId) {
  if (typeof document === 'undefined') return ''
  const canvas = document.createElement('canvas')
  canvas.width = 24
  canvas.height = 16
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  if (patId === 'graphics-pat-restricted') {
    ctx.strokeStyle = '#1f7a3a'
    ctx.lineWidth = 2
    for (let i = -16; i < 32; i += 6) {
      ctx.beginPath()
      ctx.moveTo(i, 0)
      ctx.lineTo(i + 16, 16)
      ctx.stroke()
    }
  } else if (patId === 'graphics-pat-severe') {
    ctx.strokeStyle = '#1f7a3a'
    ctx.lineWidth = 2
    for (let i = -16; i < 32; i += 6) {
      ctx.beginPath()
      ctx.moveTo(i, 0)
      ctx.lineTo(i + 16, 16)
      ctx.stroke()
    }
    for (let i = -16; i < 32; i += 6) {
      ctx.beginPath()
      ctx.moveTo(i, 16)
      ctx.lineTo(i + 16, 0)
      ctx.stroke()
    }
  } else if (patId === 'graphics-pat-urban') {
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, 24, 16)
    ctx.strokeStyle = '#000'
    ctx.lineWidth = 1.5
    ctx.strokeRect(1, 1, 22, 14)
    ctx.beginPath()
    ctx.moveTo(1, 1)
    ctx.lineTo(23, 15)
    ctx.moveTo(23, 1)
    ctx.lineTo(1, 15)
    ctx.stroke()
  }
  return canvas.toDataURL()
}

function LegendPatternSwatch({ patId }) {
  const dataUrl = useMemo(() => makePatternSwatchDataUrl(patId), [patId])
  if (!dataUrl) return null
  return <img src={dataUrl} width="24" height="16" style={{ border: '1px solid #999' }} />
}

function legendKeyTerrainSvg() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="8" fill="#fff" stroke="#7c3aed" strokeWidth="2" />
      <text x="10" y="14" textAnchor="middle" fontFamily="Helvetica" fontWeight="800" fontSize="11" fill="#7c3aed">
        K
      </text>
    </svg>
  )
}

function legendObstacleXSvg() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path d="M 2 2 L 16 16 M 16 2 L 2 16" stroke="#000" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  )
}

function legendRiverSvg() {
  return (
    <svg width="32" height="6" viewBox="0 0 32 6">
      <line x1="0" y1="3" x2="32" y2="3" stroke="#1d4ed8" strokeWidth="3" />
    </svg>
  )
}

function legendUnitFrameSvg(kind) {
  if (kind === 'friend') {
    return (
      <svg width="22" height="18" viewBox="0 0 22 18">
        <rect x="2" y="3" width="18" height="12" fill="#bfdbfe" stroke="#0369a1" strokeWidth="1.6" />
      </svg>
    )
  }
  if (kind === 'hostile-strike') {
    return (
      <svg width="22" height="18" viewBox="0 0 22 18">
        <polygon points="11,2 20,9 11,16 2,9" fill="#fecaca" stroke="#7f1d1d" strokeWidth="1.6" />
        <line x1="3" y1="3" x2="19" y2="15" stroke="#7f1d1d" strokeWidth="1.8" />
      </svg>
    )
  }
  return (
    <svg width="22" height="18" viewBox="0 0 22 18">
      <polygon points="11,2 20,9 11,16 2,9" fill="#fecaca" stroke="#7f1d1d" strokeWidth="1.6" />
    </svg>
  )
}

// Engagement area per ATP 2-01.3 Fig 6-3 = red-outlined rectangle (no
// fill, solid border) with "EAn" inside in red. Matches drawPointEaHex's
// rectangle geometry.
function legendEngagementAreaSvg() {
  return (
    <svg width="34" height="16" viewBox="0 0 34 16">
      <rect
        x="1"
        y="2"
        width="32"
        height="12"
        fill="none"
        stroke="#b91c1c"
        strokeWidth="1.6"
      />
      <text x="17" y="11" textAnchor="middle" fontFamily="Helvetica" fontWeight="800" fontSize="9" fill="#b91c1c">
        EA
      </text>
    </svg>
  )
}

// NAI = solid border, TAI = dashed border (FM 1-02.2 distinction). The
// `dashed` flag MUST be set by callers for TAI — previously TAI used the
// same swatch as NAI and the legend gave the analyst no way to tell them
// apart at a glance. Dash pattern matches drawPointNaiBox(isTai=true).
function legendNaiBoxSvg(label = 'NAI', dashed = false) {
  return (
    <svg width="34" height="16" viewBox="0 0 34 16">
      <rect
        x="1"
        y="2"
        width="32"
        height="12"
        fill="none"
        stroke="#000"
        strokeWidth="1.4"
        strokeDasharray={dashed ? '4,2' : undefined}
      />
      <text x="17" y="11" textAnchor="middle" fontFamily="Helvetica" fontWeight="800" fontSize="9" fill="#000">
        {label}
      </text>
    </svg>
  )
}

function legendPhaseLineSvg() {
  return (
    <svg width="34" height="14" viewBox="0 0 34 14">
      <line x1="1" y1="7" x2="33" y2="7" stroke="#000" strokeWidth="2.2" />
      <text x="17" y="5" textAnchor="middle" fontFamily="Helvetica" fontWeight="800" fontSize="9" fill="#000">
        PL
      </text>
    </svg>
  )
}

// Friendly / hostile axis of advance — clean outlined corridor + hollow
// triangular tip. Matches the new drawAxisOfAdvance geometry (straight
// segments via buildArrowOutline, single 2 px stroke, no fill, no solid
// arrowhead, no white halo). `side` flips the color: friend=#1e3a8a,
// hostile=#7f1d1d.
function legendAxisOfAdvanceSvg(side) {
  const color = side === 'hostile' ? '#7f1d1d' : '#1e3a8a'
  return (
    <svg width="40" height="16" viewBox="0 0 40 16">
      <path
        d="M 2 4 L 28 4 L 28 1 L 38 8 L 28 15 L 28 12 L 2 12 Z"
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// Boundary — solid black line with white halo (matches graphics-bnd-halo +
// graphics-bnd-line + the BNDRY/BDRY label that drawBoundaryLabel paints at
// both line endpoints).
function legendBoundarySvg() {
  return (
    <svg width="34" height="14" viewBox="0 0 34 14">
      <line x1="1" y1="7" x2="33" y2="7" stroke="#fff" strokeWidth="6" />
      <line x1="1" y1="7" x2="33" y2="7" stroke="#000" strokeWidth="3" />
      <text x="17" y="5" textAnchor="middle" fontFamily="Helvetica" fontWeight="800" fontSize="9" fill="#000">
        BDRY
      </text>
    </svg>
  )
}

// Objective per ATP 2-01.3 Fig 6-3 = red-outlined circle with "OBJ"
// label adjacent. Matches drawPointObjKidney's annular circle geometry.
function legendObjectiveSvg() {
  return (
    <svg width="34" height="16" viewBox="0 0 34 16">
      <circle cx="8" cy="8" r="6" fill="none" stroke="#b91c1c" strokeWidth="1.6" />
      <text x="17" y="11" textAnchor="start" fontFamily="Helvetica" fontWeight="800" fontSize="9" fill="#b91c1c">
        OBJ
      </text>
    </svg>
  )
}

// Decision point per ATP 2-01.3 Fig 6-3 = red 5-point star. Matches
// drawDecisionPoint's star geometry (scaled down for the chip).
function legendDecisionPointSvg() {
  const cx = 9, cy = 8, rOuter = 6.5, rInner = 2.6
  const pts = []
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5
    const r = i % 2 === 0 ? rOuter : rInner
    pts.push(`${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`)
  }
  return (
    <svg width="34" height="16" viewBox="0 0 34 16">
      <polygon points={pts.join(' ')} fill="none" stroke="#b91c1c" strokeWidth="1.4" strokeLinejoin="round" />
      <text x="18" y="11" textAnchor="start" fontFamily="Helvetica" fontWeight="800" fontSize="9" fill="#7f1d1d">
        DP
      </text>
    </svg>
  )
}

// Avenue of approach per ATP 2-01.3 Fig 6-3 = neutral (black) hollow
// chevron — terrain-derived, applies to any force. Matches drawAvenueChevron
// geometry (open black outline, light neutral fill).
function legendAvenueOfApproachSvg() {
  return (
    <svg width="40" height="16" viewBox="0 0 40 16">
      <path
        d="M 2 4 L 28 4 L 28 1 L 38 8 L 28 15 L 28 12 L 2 12 Z"
        fill="rgba(0,0,0,0.06)"
        stroke="#000"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// Range fan per ATP 2-01.3 Fig 6-3 = concentric red rings showing
// weapons effects radius (e.g. "3,500 meters"). Single ring + label
// scaled down for the chip.
function legendRangeFanSvg() {
  return (
    <svg width="34" height="16" viewBox="0 0 34 16">
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="#b91c1c" strokeWidth="1.2" opacity="0.7" />
      <circle cx="8" cy="8" r="1.4" fill="#b91c1c" />
      <text x="17" y="11" textAnchor="start" fontFamily="Helvetica" fontWeight="600" fontSize="9" fill="#7f1d1d">
        Range
      </text>
    </svg>
  )
}

// Threat objective per FM 1-02.2 = filled red circle (vs friendly OBJ
// which is the OPEN red ring above). Distinguishes enemy intent from
// friendly seizure.
function legendThreatObjectiveSvg() {
  return (
    <svg width="34" height="16" viewBox="0 0 34 16">
      <circle cx="8" cy="8" r="6" fill="rgba(220,38,38,0.55)" stroke="#7f1d1d" strokeWidth="1.4" />
      <text x="17" y="11" textAnchor="start" fontFamily="Helvetica" fontWeight="800" fontSize="9" fill="#7f1d1d">
        THR
      </text>
    </svg>
  )
}

// Phase line H+N timing label per ATP 2-01.3 Fig 6-3 = small black
// banner with white "H+N" text. Distinct from the generic "PL Name"
// label — the banner treatment marks PLs that are timed objectives.
function legendPhaseLineBannerSvg() {
  return (
    <svg width="34" height="14" viewBox="0 0 34 14">
      <line x1="1" y1="7" x2="33" y2="7" stroke="#000" strokeWidth="2.2" />
      <rect x="1" y="1" width="14" height="10" fill="#000" />
      <text x="8" y="9" textAnchor="middle" fontFamily="Helvetica" fontWeight="700" fontSize="8" fill="#fff">
        H+N
      </text>
    </svg>
  )
}


function legendTargetDotSvg(kind) {
  if (kind === 'p1') {
    return (
      <svg width="20" height="20" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="8" fill="#dc2626" stroke="#7f1d1d" strokeWidth="2" />
      </svg>
    )
  }
  if (kind === 'p2') {
    return (
      <svg width="20" height="20" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="6" fill="#ef4444" stroke="#7f1d1d" strokeWidth="1.5" />
      </svg>
    )
  }
  if (kind === 'defeated') {
    return (
      <svg width="20" height="20" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="6" fill="#fca5a5" stroke="#7f1d1d" strokeWidth="1.4" />
        <line x1="3" y1="3" x2="17" y2="17" stroke="#7f1d1d" strokeWidth="2" />
      </svg>
    )
  }
  return (
    <svg width="20" height="20" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="4.5" fill="#fca5a5" stroke="#7f1d1d" strokeWidth="1.2" />
    </svg>
  )
}

// Legend item registry --- one entry per (legendItemId → React fragment).
// The active product schema declares `map_overlay_kinds` (the kinds the
// product paints); the legend below iterates the kinds list and emits
// each kind's canonical legend chip. Anything not in the kinds set is
// silently skipped, so legend content is doctrinally consistent with
// what the map actually paints. No product-type switch.
//
// A handful of overlay kinds have multiple visual variants on the legend
// (mobility corridors come in PLT and BN widths; targets in P1/P2/P3/
// Defeated dots) — those are emitted as one chip per variant when the
// underlying kind is allowed. Friendly-vs-threat affiliation for the
// mil_unit kind is gated by the schema's `map_legend_show_friendly_unit`
// + `map_legend_show_threat_unit` primitives so doctrinal CONOP-style
// products that need both can opt in.
function legendItemsForKind(kind, renderConfig) {
  switch (kind) {
    case 'mil_unit': {
      const items = []
      const cfg = renderConfig || {}
      // Default: show threat label only (matches every IPB product in
      // the current catalog — SITEMP/Threat Overlay/Threat COA Statement/THREAT_MODEL all show
      // hostile units). Schema can override via the explicit
      // map_legend_* primitives when a product (CONOP, etc.) needs
      // both affiliations on the legend.
      const showThreat = cfg.legendShowThreatUnit !== false
      const showFriendly = cfg.legendShowFriendlyUnit === true
      if (showThreat) items.push(
        <div className="mcc-item" key="unit-hostile">{legendUnitFrameSvg('hostile')}<span>Threat unit</span></div>
      )
      if (showFriendly) items.push(
        <div className="mcc-item" key="unit-friend">{legendUnitFrameSvg('friend')}<span>Friendly unit</span></div>
      )
      return items
    }
    case 'avenue_of_approach':
      return [<div className="mcc-item" key="aa">{legendAvenueOfApproachSvg()}<span>Avenue of approach</span></div>]
    case 'mobility_corridor':
      return [
        <div className="mcc-item" key="mc-plt">{legendMobilityCorridorSvg('plt')}<span>PLT mobility corridor</span></div>,
        <div className="mcc-item" key="mc-bn">{legendMobilityCorridorSvg('bn')}<span>BN mobility corridor</span></div>,
      ]
    case 'engagement_area':
      return [<div className="mcc-item" key="ea">{legendEngagementAreaSvg()}<span>Engagement area</span></div>]
    case 'objective':
      return [<div className="mcc-item" key="obj">{legendObjectiveSvg()}<span>Objective</span></div>]
    case 'threat_objective':
      return [<div className="mcc-item" key="thr-obj">{legendThreatObjectiveSvg()}<span>Threat objective</span></div>]
    case 'decision_point':
      return [<div className="mcc-item" key="dp">{legendDecisionPointSvg()}<span>Decision point</span></div>]
    case 'range_fan':
      return [<div className="mcc-item" key="rf">{legendRangeFanSvg()}<span>Range fan</span></div>]
    case 'named_area_of_interest':
      return [<div className="mcc-item" key="nai">{legendNaiBoxSvg()}<span>NAI</span></div>]
    case 'targeted_area_of_interest':
      return [<div className="mcc-item" key="tai">{legendNaiBoxSvg('TAI', true)}<span>TAI</span></div>]
    case 'phase_line':
      return [
        <div className="mcc-item" key="pl">{legendPhaseLineSvg()}<span>Phase line</span></div>,
        <div className="mcc-item" key="pl-banner">{legendPhaseLineBannerSvg()}<span>PL (H-hour timing)</span></div>,
      ]
    case 'boundary':
      return [<div className="mcc-item" key="bnd">{legendBoundarySvg()}<span>Boundary</span></div>]
    case 'target':
      return [
        <div className="mcc-item" key="t-p1">{legendTargetDotSvg('p1')}<span>P1 target</span></div>,
        <div className="mcc-item" key="t-p2">{legendTargetDotSvg('p2')}<span>P2 target</span></div>,
        <div className="mcc-item" key="t-p3">{legendTargetDotSvg('p3')}<span>P3-5 target</span></div>,
        <div className="mcc-item" key="t-def">{legendTargetDotSvg('defeated')}<span>Defeated</span></div>,
      ]
    case 'axis_of_advance':
      return [<div className="mcc-item" key="ax">{legendAxisOfAdvanceSvg('friend')}<span>Friendly axis</span></div>]
    case 'restricted_terrain':
      return [<div className="mcc-item" key="pat-rest"><LegendPatternSwatch patId="graphics-pat-restricted" /><span>Restricted terrain</span></div>]
    case 'severely_restricted_terrain':
      return [<div className="mcc-item" key="pat-sev"><LegendPatternSwatch patId="graphics-pat-severe" /><span>Severely restricted</span></div>]
    case 'urban_area':
      return [<div className="mcc-item" key="pat-urb"><LegendPatternSwatch patId="graphics-pat-urban" /><span>Urban terrain</span></div>]
    case 'key_terrain':
      return [<div className="mcc-item" key="kt">{legendKeyTerrainSvg()}<span>Key terrain</span></div>]
    case 'choke_point':
      return [<div className="mcc-item" key="cp">{legendObstacleXSvg()}<span>CP &mdash; Choke point</span></div>]
    case 'hydrology_obstacle':
      return [<div className="mcc-item" key="hyd">{legendRiverSvg()}<span>Hydrology obstacle</span></div>]
    default:
      // Kind has no canonical legend chip (e.g. battle_position,
      // intervisibility_line, mobility_go, obstacle_point) — those
      // render on the map but don't carry a legend entry in the
      // current chip vocabulary. Silently omit.
      return []
  }
}

// Iterate the schema-allowed kinds (stashed on the map instance by
// HeadlessRenderConfigStash from the `layers` URL primitive forwarded
// by intel_agent.tool_render_map) and emit the matching legend chips.
// Editor mode (no render config) falls back to the MCOO baseline so
// the analyst always sees a legend while editing.
const _MCOO_FALLBACK_KINDS = [
  'avenue_of_approach', 'mobility_corridor',
  'restricted_terrain', 'severely_restricted_terrain', 'urban_area',
  'key_terrain', 'choke_point', 'hydrology_obstacle', 'boundary',
]
function LegendItems({ renderConfig }) {
  const allowedKinds = renderConfig?.allowedKinds
  const kinds = allowedKinds
    ? Array.from(allowedKinds)
    : _MCOO_FALLBACK_KINDS
  const items = []
  for (const k of kinds) {
    for (const it of legendItemsForKind(k, renderConfig)) items.push(it)
  }
  return <>{items}</>
}

// Compute scale-bar distance in km from canvas-relative screen points.
function computeScaleKm(map) {
  try {
    const container = map.getContainer()
    const cw = container ? container.clientWidth : 1600
    const cy = container ? container.clientHeight / 2 : 600
    const ll1 = map.unproject([cw / 2 - 45, cy])
    const ll2 = map.unproject([cw / 2 + 45, cy])
    const dLat = ((ll2.lat - ll1.lat) * Math.PI) / 180
    const dLng = ((ll2.lng - ll1.lng) * Math.PI) / 180
    const meanLat = (((ll1.lat + ll2.lat) / 2) * Math.PI) / 180
    const a =
      Math.sin(dLat / 2) ** 2 + Math.cos(meanLat) ** 2 * Math.sin(dLng / 2) ** 2
    const distM = 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
    return Math.max(1, Math.round(distM / 1000))
  } catch (err) {
    return 0
  }
}

// Compute the fractional/representative scale (1 : RF) of the map at the
// current viewport. Required by ATP 2-01.3 marginalia: medium-scale
// tactical maps (1:25K-1:100K) must publish the RF alongside the linear
// bar so analysts can read distance directly off the printed sheet.
//
// Method: project two screen-space points exactly 1 cm apart on a typical
// embed (we use the same 90-px screen baseline as the linear bar to keep
// the two values consistent), measure the ground distance between them in
// metres, then divide ground / map to get the dimensionless RF. The map-
// side distance assumes a 178-DPI print target (the same DPI the headless
// renderer outputs and the same that DOCX / PPTX embed at default zoom).
function computeFractionalScaleDenominator(map) {
  try {
    const container = map.getContainer()
    if (!container) return 0
    const cw = container.clientWidth
    const cy = container.clientHeight / 2
    // Same 90-px baseline as the km bar so the two readings stay paired.
    const screenPx = 90
    const ll1 = map.unproject([cw / 2 - screenPx / 2, cy])
    const ll2 = map.unproject([cw / 2 + screenPx / 2, cy])
    const dLat = ((ll2.lat - ll1.lat) * Math.PI) / 180
    const dLng = ((ll2.lng - ll1.lng) * Math.PI) / 180
    const meanLat = (((ll1.lat + ll2.lat) / 2) * Math.PI) / 180
    const a =
      Math.sin(dLat / 2) ** 2 + Math.cos(meanLat) ** 2 * Math.sin(dLng / 2) ** 2
    const groundMetres =
      6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
    // Convert screen-pixels to print-metres at 178 DPI:
    //   inches = px / 178; metres = inches * 0.0254
    const mapMetres = (screenPx / 178) * 0.0254
    if (mapMetres <= 0) return 0
    return Math.round(groundMetres / mapMetres)
  } catch (err) {
    return 0
  }
}

// Round an RF denominator to the nearest doctrinal map scale so the analyst
// reads a clean "1:50,000" rather than "1:47,213". Steps follow standard
// topo scale ladder (ATP 2-01.3 + JP 2-03 figure 5-1): 5k / 10k / 25k /
// 50k / 100k / 250k / 500k / 1M ...
function roundToDoctrinalScale(rf) {
  if (!rf || rf <= 0) return rf
  const ladder = [
    5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000,
    1_000_000, 2_500_000, 5_000_000, 10_000_000,
  ]
  let best = ladder[0]
  let bestDelta = Math.abs(Math.log(rf / ladder[0]))
  for (const s of ladder) {
    const d = Math.abs(Math.log(rf / s))
    if (d < bestDelta) {
      best = s
      bestDelta = d
    }
  }
  return best
}

function formatFractionalScale(rf) {
  if (!rf || rf <= 0) return ''
  const rounded = roundToDoctrinalScale(rf)
  return '1:' + rounded.toLocaleString('en-US')
}

/**
 * MapCartographicChrome — main export.
 *
 * @param {Object} props
 * @param {Object} props.mapMeta - { attrs: { product_type } }
 */
export function MapCartographicChrome({ mapMeta }) {
  const { mapRef, mapLoaded, productType: ctxProductType, headless } = useGeoAgent()
  const [scaleKm, setScaleKm] = useState(0)
  const [scaleRf, setScaleRf] = useState(0)
  const [host, setHost] = useState(null)

  // Three sources for productType, in priority order:
  //  1. context.productType — embedded mounts (DocEditor EditMap overlay)
  //     pass it as a prop to GeoAgentProvider since the DocEditor URL
  //     doesn't carry product_type.
  //  2. mapMeta.attrs.product_type — route-mounted callers that fetch the
  //     map record themselves and pass mapMeta in.
  // Normalize whitespace→underscore so 'Threat Model' → 'THREAT_MODEL'
  // matches the same identifier MapDoctrinalPaint uses.
  const productType = (
    (ctxProductType || '').toUpperCase()
    || (mapMeta?.attrs?.product_type || '').toUpperCase()
  ).replace(/\s+/g, '_')
  const enabled = PRODUCT_TYPES_WITH_CHROME.has(productType)

  // Mount a host div inside MapLibre's canvas container so the chrome
  // lives in the same DOM stack as the WebGL canvas (and the doctrinal
  // paint SVG). pointer-events: none lets the analyst still click /
  // drag through the chrome to underlying map features.
  useEffect(() => {
    if (!enabled) return
    const map = mapRef?.current
    if (!map || !mapLoaded) return
    const container = map.getCanvasContainer()
    if (!container) return
    const div = document.createElement('div')
    div.className = 'map-cartographic-chrome'
    div.style.position = 'absolute'
    div.style.left = '0'
    div.style.top = '0'
    div.style.width = '100%'
    div.style.height = '100%'
    div.style.pointerEvents = 'none'
    div.style.zIndex = '3'
    container.appendChild(div)
    setHost(div)
    return () => {
      if (div.parentNode) div.parentNode.removeChild(div)
      setHost(null)
    }
  }, [enabled, mapRef, mapLoaded])

  // Recompute scale-bar distance once the map is loaded and on every
  // move-end (the editor pans/zooms; the headless render fits once).
  useEffect(() => {
    if (!enabled) return
    const map = mapRef?.current
    if (!map || !mapLoaded) return
    const recompute = () => {
      setScaleKm(computeScaleKm(map))
      setScaleRf(computeFractionalScaleDenominator(map))
    }
    const id = setTimeout(recompute, 50)
    map.on('moveend', recompute)
    return () => {
      clearTimeout(id)
      try {
        map.off('moveend', recompute)
      } catch {
        /* ignore */
      }
    }
  }, [enabled, mapRef, mapLoaded])

  if (!enabled || !host) return null

  const scaleMi = Math.max(1, Math.round(scaleKm * 0.621371))

  const body = (
    <>
      {/* Legend strip — ATP 2-01.3 figs 4-9 show the legend INSIDE the
          map frame so it prints with the map. Editor mounts (non-headless)
          skip the legend entirely: it's sized for the headless 2560x1440
          render, dwarfs the embedded editor viewport, and doesn't carry
          actionable info for analyst interaction. The exported PNG still
          gets the legend baked in via the headless render path. */}
      {headless && (
        <div className="mcc-legend">
          <div className="mcc-legend-row">
            <LegendItems renderConfig={mapRef?.current?.__renderConfig || null} />
          </div>
        </div>
      )}

      {/* North arrow (grid + magnetic declination diagram) — doctrinal
          marginalia baked into the PRODUCT render only. In the interactive
          editor it's useless: it's a static SVG that doesn't track the
          map bearing, and MapLibre's own NavigationControl compass
          (bottom-right, added in GeoAgentMap) already shows live bearing
          and resets north on click. So render it only when headless. */}
      {headless && (
        <div className="mcc-north-arrow">
          <svg viewBox="0 0 64 56" xmlns="http://www.w3.org/2000/svg">
            <polygon points="14,4 22,42 14,34 6,42" fill="#000" />
            <polygon points="14,4 14,34 6,42" fill="#fff" stroke="#000" strokeWidth="1" />
            <line x1="14" y1="4" x2="42" y2="4" stroke="#000" strokeWidth="1.0" />
            <line x1="42" y1="4" x2="48" y2="42" stroke="#000" strokeWidth="1.6" />
            <text x="48" y="52" fontSize="11" fontWeight="800" fontFamily="Helvetica" fill="#000">
              GN
            </text>
            <line x1="14" y1="4" x2="32" y2="4" stroke="#000" strokeWidth="0.8" strokeDasharray="1.5,1.5" />
            <line x1="32" y1="4" x2="54" y2="42" stroke="#000" strokeWidth="1.2" strokeDasharray="3,1.5" />
          </svg>
          <div className="mcc-na-lbl">N &nbsp;GN &nbsp;MN</div>
        </div>
      )}

      {/* Fractional + linear scale bar (ATP 2-01.3 marginalia requirement:
          medium-scale tactical maps must publish BOTH the representative
          fraction 1:RF and the linear km/mi bars). PRODUCT render only —
          the interactive editor uses MapLibre's native ScaleControl
          (bottom-right, added in GeoAgentMap) instead of this custom box. */}
      {headless && (
        <div className="mcc-scale-bar">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 4 }}>
            <div className="mcc-rf">{formatFractionalScale(scaleRf)}</div>
            <div>
              <span className="mcc-bar" />
              <span>{scaleKm} km</span>
            </div>
            <div>
              <span
                className="mcc-bar"
                style={{ background: 'linear-gradient(to right,#000 0 33%,#fff 33% 66%,#000 66%)' }}
              />
              <span>{scaleMi} mi</span>
            </div>
          </div>
        </div>
      )}

      <style>{`
        .map-cartographic-chrome { font-family: "Helvetica Neue", Arial, sans-serif;
          color: #000; -webkit-font-smoothing: antialiased; }
        .mcc-legend { position: absolute; left: 12px; right: 12px; bottom: 12px;
          background: rgba(255,255,255,0.96); border: 1.5px solid #000;
          padding: 12px 18px; font-size: 16px;
          line-height: 1.4; font-weight: 600; color: #000;
          pointer-events: none; }
        .mcc-legend-row { display: flex; flex-wrap: wrap; align-items: center;
          gap: 8px 28px; }
        .mcc-item { display: flex; align-items: center; gap: 9px;
          white-space: nowrap; }
        .mcc-scale-bar { position: absolute; right: 28px;
          bottom: ${headless ? '110px' : '60px'};
          background: rgba(255,255,255,0.94); border: 1.2px solid #000;
          padding: 8px 12px; font-size: 14px; line-height: 1.4;
          font-weight: 700; color: #000; pointer-events: none; }
        .mcc-scale-bar .mcc-bar { display: inline-block; height: 10px; width: 110px;
          border: 1px solid #000;
          background: linear-gradient(to right, #000 0 50%, #fff 50% 100%);
          vertical-align: middle; margin-right: 7px; }
        .mcc-rf { font-size: 16px; font-weight: 900; letter-spacing: 0.02em;
          color: #000; padding-bottom: 2px;
          border-bottom: 1px solid rgba(0,0,0,0.25); width: 100%; }
        .mcc-north-arrow { position: absolute; right: 28px; top: 12px;
          background: rgba(255,255,255,0.94); border: 1.5px solid #000;
          padding: 8px 10px 6px; text-align: center;
          pointer-events: none; }
        .mcc-north-arrow svg { display: block; width: 64px; height: 56px; margin: 0 auto; }
        .mcc-na-lbl { font-size: 14px; font-weight: 800; margin-top: 4px;
          color: #000; letter-spacing: 0.05em; }
      `}</style>
    </>
  )

  return createPortal(body, host)
}

export default MapCartographicChrome
