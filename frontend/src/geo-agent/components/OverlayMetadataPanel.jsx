import React, { useEffect, useRef } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { latLngToMGRS } from '../utils/mgrsGrid'
import { AFFILIATION_POPUP_COLORS } from '../utils/mapStyles'

/**
 * OverlayMetadataPanel — control-measure placard (view-mode click
 * inspector for tactical graphics: boundaries, MSRs, phase lines,
 * decision points, objectives, NAIs...).
 *
 * Parallel to UnitMetadataPanel: self-gates on selectedOverlayMeta
 * ({ props, coords } set by useMapEvents' view-mode overlay click) and
 * reuses the unit-meta-panel styling so the two inspectors read as one
 * family. Shows what the graphic IS (label + kind), where the click
 * landed (MGRS), what it means (significance / notes), and the
 * position provenance — which document put this graphic HERE.
 */
export function OverlayMetadataPanel() {
  const { selectedOverlayMeta, setSelectedOverlayMeta } = useGeoAgent()
  const panelRef = useRef(null)

  const close = () => setSelectedOverlayMeta(null)

  useEffect(() => {
    if (!selectedOverlayMeta) return undefined
    const onKey = (e) => { if (e.key === 'Escape') close() }
    const onDown = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) close()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown, true)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown, true)
    }
  }, [selectedOverlayMeta]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!selectedOverlayMeta) return null
  const { props = {}, coords } = selectedOverlayMeta

  const name = props.name || props.label || props.designation || 'Control measure'
  const kind = String(props.kind || props.entity_type || '')
  const kindLabel = kind.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  const affiliation = (props.affiliation || props.side || '').toString()
  const color =
    AFFILIATION_POPUP_COLORS[affiliation]
    || AFFILIATION_POPUP_COLORS[
      affiliation.charAt(0).toUpperCase() + affiliation.slice(1).toLowerCase()]
    || '#cbd5e1'

  const hasLoc = Array.isArray(coords) && coords.length >= 2
  const mgrs = hasLoc ? latLngToMGRS(coords[1], coords[0], 4) : '—'

  const positionSource = (props.position_source || '').toString()
  const positionDtg = (props.position_dtg || '').toString()
  const positionObservedAt = (props.position_observed_at || '').toString()

  const rows = [
    ['Type', kindLabel],
    ['Affiliation', affiliation],
    ['MGRS (at click)', mgrs],
    ['Significance', props.significance || ''],
  ].filter(([, v]) => v)

  return (
    <div className="unit-meta-panel" ref={panelRef}>
      <div className="unit-meta-header" style={{ borderLeft: `4px solid ${color}` }}>
        <div className="unit-meta-title">
          <div className="unit-meta-name">{name}</div>
          <div className="unit-meta-sub">{kindLabel || 'Tactical graphic'}</div>
        </div>
        <button className="unit-meta-close" onClick={close} aria-label="Close">×</button>
      </div>

      <div className="unit-meta-content">
        <div className="unit-meta-section">
          {rows.map(([k, v]) => (
            <div className="unit-meta-row" key={k}>
              <span className="unit-meta-key">{k}</span>
              <span className="unit-meta-val">{String(v)}</span>
            </div>
          ))}
        </div>

        {(positionSource || positionDtg || positionObservedAt) && (
          <div className="unit-meta-section">
            <div className="unit-meta-section-label">Placement provenance</div>
            {positionSource && (
              <div className="unit-meta-row">
                <span className="unit-meta-key">Source</span>
                <span className="unit-meta-val">{positionSource}</span>
              </div>
            )}
            {(positionDtg || positionObservedAt) && (
              <div className="unit-meta-row">
                <span className="unit-meta-key">As of</span>
                <span className="unit-meta-val unit-meta-mono">
                  {positionDtg || positionObservedAt}
                </span>
              </div>
            )}
          </div>
        )}

        {props.notes && (
          <div className="unit-meta-section">
            <div className="unit-meta-section-label">Notes</div>
            <div className="unit-meta-activity">{props.notes}</div>
          </div>
        )}

        {props.source === 'entity_graph' && props.id && (
          <a
            className="unit-meta-source"
            href="#link-view"
            onClick={(e) => {
              e.preventDefault()
              window.dispatchEvent(new CustomEvent('geoagent:openLinkView', {
                detail: { id: String(props.id) },
              }))
            }}
          >
            View relationships →
          </a>
        )}
      </div>
    </div>
  )
}
