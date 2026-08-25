import React, { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useGeoAgent } from '../GeoAgentProvider'
import { latLngToMGRS } from '../utils/mgrsGrid'

/**
 * SignalReportPanel — live operations-map left-click inspector for autofired
 * signal-report markers (KLIEGLIGHT / OSIR).
 *
 * Parallel to UnitMetadataPanel: it self-gates on selectedSignalReport (set
 * only by the KLIEGLIGHT/OSIR layer click handler in GeoAgentMap), shows the
 * report's summary + location + fire time, and offers "Open in editor".
 *
 * "Open in editor" opens the exact same session the product dashboard opens:
 * it mirrors WhiteCellHome's openRow, navigating to
 * /missioncommand/docs/<autodraft_session_id> with the same
 * pending_product_type / pending_format / opening params. The
 * autodraft_session_id + format are joined from the product-records registry
 * server-side (recent_signal_reports) — the dashboard's own source — so the
 * map and the dashboard land on the identical editor session. Replaces the
 * old behavior of opening the read-only headless render in a new tab.
 *
 * Dismissible via the × button, Escape, or an outside click.
 */
function firedAgo(ms) {
  const t = Number(ms)
  if (!t) return ''
  const mins = Math.max(1, Math.ceil((Date.now() - t) / 60000))
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.ceil(mins / 60)
  if (hrs < 24) return `${hrs} hr${hrs !== 1 ? 's' : ''} ago`
  const days = Math.ceil(mins / (24 * 60))
  return `${days} day${days !== 1 ? 's' : ''} ago`
}

export function SignalReportPanel() {
  const { selectedSignalReport, setSelectedSignalReport } = useGeoAgent()
  const navigate = useNavigate()
  const panelRef = useRef(null)

  const close = () => setSelectedSignalReport(null)

  // Esc + outside-click dismissal — listeners live only while the panel is
  // open. Capture phase on mousedown so it resolves before MapLibre's canvas
  // handlers (and before a fresh marker click re-opens the panel).
  useEffect(() => {
    if (!selectedSignalReport) return undefined
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
  }, [selectedSignalReport]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!selectedSignalReport) return null

  const {
    kind,
    summary,
    mgrs: rawMgrs,
    fired_at_ms,
    autodraft_session_id,
    format,
    coords,
  } = selectedSignalReport
  const label = kind || 'Signal report'

  // Location → MGRS. Prefer the backend-resolved mgrs; fall back to the
  // marker's own coordinates (GeoJSON [lng, lat]).
  const hasCoords = Array.isArray(coords) && coords.length === 2
  const mgrs =
    rawMgrs || (hasCoords ? latLngToMGRS(coords[1], coords[0], 4) : '—')
  const latLonStr = hasCoords
    ? `${Number(coords[1]).toFixed(4)}°, ${Number(coords[0]).toFixed(4)}°`
    : '—'
  const ago = firedAgo(fired_at_ms)

  // Open the same editor session the dashboard opens (WhiteCellHome openRow).
  // Disabled until the artifact has a registry chain carrying its
  // autodraft_session_id.
  const canOpen = !!autodraft_session_id
  function openInEditor() {
    if (!autodraft_session_id) return
    setSelectedSignalReport(null)
    const params = new URLSearchParams({
      pending_product_type: kind || '',
      pending_format: format || 'docx',
      opening: '1',
    })
    navigate(
      `/missioncommand/docs/${encodeURIComponent(autodraft_session_id)}?${params.toString()}`,
    )
  }

  return (
    <div className="unit-meta-panel" ref={panelRef}>
      <div
        className="unit-meta-header"
        style={{ borderLeft: '4px solid #facc15' }}
      >
        <div className="unit-meta-title">
          <div className="unit-meta-name">{label}</div>
          <div className="unit-meta-sub">
            {['Signal report', ago].filter(Boolean).join(' · ')}
          </div>
        </div>
        <button className="unit-meta-close" onClick={close} aria-label="Close">×</button>
      </div>

      <div className="unit-meta-content">
        <div className="unit-meta-section">
          <div className="unit-meta-section-label">Location</div>
          <div className="unit-meta-row">
            <span className="unit-meta-key">MGRS</span>
            <span className="unit-meta-val unit-meta-mono">{mgrs}</span>
          </div>
          <div className="unit-meta-row">
            <span className="unit-meta-key">Lat / Lon</span>
            <span className="unit-meta-val unit-meta-mono">{latLonStr}</span>
          </div>
        </div>

        <div className="unit-meta-section">
          <div className="unit-meta-section-label">Summary</div>
          <div className="unit-meta-activity">
            {summary || 'No summary available'}
          </div>
        </div>

        <div className="unit-meta-section">
          <button
            className="unit-meta-open-editor"
            onClick={openInEditor}
            disabled={!canOpen}
            title={canOpen ? undefined : 'Draft is still registering — try again shortly'}
          >
            Open in editor
          </button>
          {!canOpen && (
            <div className="unit-meta-open-error">Draft not ready yet</div>
          )}
        </div>
      </div>
    </div>
  )
}
