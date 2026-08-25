/**
 * TimelineScrubber — scrub the map through the project's position
 * history. Every position write is an append-only observation
 * (graph_node_positions); dragging the scrubber re-resolves the whole
 * graph stream at that instant (map/state?as_of=), so units appear
 * where they were observed at that time, formations without a fix yet
 * are absent, and control-measure redraws roll back. LIVE returns to
 * newest-wins.
 *
 * Renders only when the project has a real time dimension (2+ dated
 * observations) and never in headless/product renders — the scrub is
 * an analyst view, not a render primitive.
 */
import React, { useMemo, useState } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'

function formatDtg(ms) {
  const d = new Date(ms)
  const p = (n) => String(n).padStart(2, '0')
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  return `${p(d.getUTCDate())} ${p(d.getUTCHours())}${p(d.getUTCMinutes())}Z ` +
         `${months[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`
}

export default function TimelineScrubber() {
  const {
    trackExtent, timelineAsOf, setTimelineAsOf,
    setTimelineDragMs, headless,
  } = useGeoAgent()

  const domain = useMemo(() => {
    if (!trackExtent?.min || !trackExtent?.max) return null
    const min = Date.parse(trackExtent.min)
    const max = Date.parse(trackExtent.max)
    if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) return null
    if ((trackExtent.dated_observations || 0) < 2) return null
    return { min, max }
  }, [trackExtent])

  // Every drag tick re-times the map CLIENT-SIDE (timelineDragMs →
  // prefetched track frames in useMapInstance) — the thumb IS the
  // time, no debounce, no round trip. Release commits the
  // authoritative as_of.
  const [dragMs, setDragMs] = useState(null)

  if (headless || !domain) return null

  const live = timelineAsOf == null && dragMs == null
  const valueMs = dragMs != null
    ? dragMs
    : (timelineAsOf != null ? Date.parse(timelineAsOf) : domain.max)

  const onDrag = (e) => {
    const ms = Number(e.target.value)
    setDragMs(ms)
    setTimelineDragMs(ms)
  }

  const commit = () => {
    if (dragMs == null) return
    const ms = dragMs
    setDragMs(null)
    setTimelineDragMs(null)
    // Scrubbed all the way right = live view, drop the as_of entirely.
    setTimelineAsOf(ms >= domain.max ? null : new Date(ms).toISOString())
  }

  return (
    <div className="timeline-scrubber" data-live={live ? '1' : '0'}>
      <button
        className={`timeline-live-btn ${live ? 'active' : ''}`}
        title="Return to the live (newest observation) picture"
        onClick={() => { setDragMs(null); setTimelineDragMs(null); setTimelineAsOf(null) }}
      >
        LIVE
      </button>
      <span className="timeline-dtg">{live ? formatDtg(domain.max) : formatDtg(valueMs)}</span>
      <input
        type="range"
        min={domain.min}
        max={domain.max}
        step={Math.max(60000, Math.floor((domain.max - domain.min) / 500))}
        value={valueMs}
        onChange={onDrag}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        aria-label="Timeline scrub — map as of"
      />
      <span className="timeline-extent">
        {formatDtg(domain.min)} — {formatDtg(domain.max)}
      </span>
    </div>
  )
}
