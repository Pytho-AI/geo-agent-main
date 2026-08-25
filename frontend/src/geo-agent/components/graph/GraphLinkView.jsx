// Forces & Connections — the entity-graph UI (repurposed cougaar
// GraphViewer, react-force-graph-2d). Redesigned for a first-time,
// touch-native reader (uiux-review skill): every dot has a NAME and a
// SIDE color, a persistent legend explains the colors, a real empty
// state tells you what to do first, connections are made with a visible
// Connect flow (no shift-click) and broken from the inspector (no
// clicking 1px lines), Import shows a reassuring staged progress, and
// the labels are plain English. Two layouts over one graph: Web view
// (force-directed) and Chain of command (top-down tree).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { useGeoAgent } from '../../GeoAgentProvider'
import { graphApi, typeColor, GRAPH_AFFILIATION_COLORS } from '../../utils/graphApi'
import { GraphEntityEditor } from './GraphEntityEditor'
import { UnitMetadataPanel } from '../UnitMetadataPanel'
import { createMilSymbol } from '../../utils/symbols'

// Doctrinal-glyph cache for the canvas renderer: SIDC → decoded image
// + geometry (milsymbol SVGs are larger than the icon; `anchor` marks
// the doctrinal center — draw by anchor, never bbox center). Module
// scope: survives re-mounts, one decode per SIDC per session.
const _ICON_CACHE = new Map()
function _iconFor(sidc) {
  let icon = _ICON_CACHE.get(sidc)
  if (icon) return icon
  let made = null
  try { made = createMilSymbol(sidc, { size: 22 }) } catch { /* fall back */ }
  if (!made || !made.svg) {
    icon = { ready: false, failed: true }
    _ICON_CACHE.set(sidc, icon)
    return icon
  }
  const img = new Image()
  // Frame CENTER (octagon anchor) is the node position — same centering
  // rule as the map (HQ-staff symbols would otherwise hang off-node).
  const a = made.octagonAnchor || made.anchor
  icon = {
    img, ready: false,
    w: made.size.width, h: made.size.height,
    ax: a.x, ay: a.y,
  }
  img.onload = () => { icon.ready = true }
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(made.svg)}`
  _ICON_CACHE.set(sidc, icon)
  return icon
}

// ── plain-English vocabulary (staff jargon → words a first-timer reads)
const SIDE_OPTIONS = [
  ['Hostile', 'Enemy'], ['Friend', 'Us'], ['Neutral', 'Civilian'], ['Unknown', 'Not sure'],
]
const SIDE_LABEL = Object.fromEntries(SIDE_OPTIONS.map(([k, v]) => [k, v]))
const FAMILY_COLOR = { command: '#94a3b8', support: '#f59e0b', supply: '#fb923c' }

function edgeFamily(type, rt) {
  if (type === '__organic' || rt?.is_hierarchical) return 'command'
  if (/suppl|depend/i.test(type)) return 'supply'
  return 'support'
}

// ── design tokens (the shell's scale — no more 11px debug text)
const ACCENT = '#3b82f6'
const S = {
  wrap: { position: 'fixed', inset: 0, background: '#0b0e14', zIndex: 1200,
    display: 'flex', color: '#e6e9f2', fontSize: 13,
    fontFamily: 'system-ui, -apple-system, sans-serif' },
  side: { width: 340, minWidth: 340, borderRight: '1px solid #232838',
    display: 'flex', flexDirection: 'column', background: '#12141c' },
  head: { padding: '14px 16px', borderBottom: '1px solid #232838',
    display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: 15, fontWeight: 700, letterSpacing: 0.2 },
  sub: { fontSize: 12, color: '#8b93a7', marginTop: 2 },
  toolbar: { display: 'flex', flexWrap: 'wrap', gap: 6, padding: '10px 12px',
    borderBottom: '1px solid #232838' },
  body: { flex: 1, overflowY: 'auto', padding: 14 },
  btn: { background: '#1c2130', color: '#e6e9f2', border: '1px solid #2e3446',
    borderRadius: 8, padding: '9px 13px', cursor: 'pointer', fontSize: 13,
    fontWeight: 500, whiteSpace: 'nowrap', minHeight: 40 },
  btnActive: { background: ACCENT, borderColor: ACCENT, color: '#fff' },
  btnPrimary: { background: ACCENT, borderColor: ACCENT, color: '#fff', fontWeight: 600 },
  iconBtn: { background: 'transparent', color: '#9aa0b4', border: 0,
    cursor: 'pointer', padding: 6, fontSize: 18, borderRadius: 8, minWidth: 36, minHeight: 36 },
  label: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5,
    color: '#8b93a7', marginBottom: 6, display: 'block' },
  in: { width: '100%', background: '#0f1119', color: '#e6e9f2',
    border: '1px solid #2e3446', borderRadius: 8, padding: '10px 12px',
    fontSize: 13, boxSizing: 'border-box', minHeight: 42 },
  card: { border: '1px solid #232838', borderRadius: 10, padding: 12,
    marginBottom: 12, background: '#161922' },
}

export function GraphLinkView({ mapId, userId, focusId, onClose, onOpenCatalog }) {
  const { requestConfirm, setSelectedUnitMeta } = useGeoAgent()
  const fgRef = useRef()
  const canvasWrapRef = useRef(null)
  const selectedRef = useRef(null)
  const [dims, setDims] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const measure = () => {
      const el = canvasWrapRef.current
      if (el) setDims({ w: el.clientWidth, h: el.clientHeight })
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  const [bulk, setBulk] = useState(null)
  const [layout, setLayout] = useState('network')
  const [selected, setSelected] = useState(null)
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { selectedRef.current = selected }, [selected])

  const reload = useCallback(() => {
    graphApi.bulk(mapId).then(b => {
      setBulk(b)
    }).catch(e => setError(String(e.message || e)))
  }, [mapId])
  useEffect(() => { reload() }, [reload])


  const etypes = useMemo(() => Object.fromEntries(
    (bulk?.entity_types || []).map(t => [t.type_key, t])), [bulk])
  const rtypes = useMemo(() => Object.fromEntries(
    (bulk?.relationship_types || []).map(t => [t.type_key, t])), [bulk])
  const hierRels = useMemo(() => new Set(
    (bulk?.relationship_types || []).filter(t => t.is_hierarchical).map(t => t.type_key)), [bulk])

  const data = useMemo(() => {
    if (!bulk) return { nodes: [], links: [] }
    const nodes = bulk.entities.map(e => ({
      id: e.id, name: e.name, entity_type: e.entity_type,
      affiliation: e.affiliation, echelon: e.echelon,
      // The composed SIDC from the bulk read — WITHOUT this the canvas
      // icon branch never fired and every node fell back to a colored
      // dot. lon/lat feed the placard's click-to-locate.
      sidc: e.sidc, lon: e.lon, lat: e.lat,
      fixed: !!etypes[e.entity_type]?.is_fixed,
    }))
    // Pre-warm the doctrinal glyph cache so icons decode while the
    // layout settles instead of on their first draw frame.
    for (const n of nodes) {
      if (n.sidc && !n.fixed) _iconFor(n.sidc)
    }
    const ids = new Set(nodes.map(n => n.id))
    const links = []
    for (const e of bulk.entities) {
      if (e.organic_parent_id && ids.has(e.organic_parent_id)) {
        links.push({ source: e.organic_parent_id, target: e.id, type: '__organic', open: true, edgeId: null })
      }
    }
    for (const ed of bulk.edges || []) {
      if (!ids.has(ed.from_id) || !ids.has(ed.to_id)) continue
      const isHier = hierRels.has(ed.relationship_type)
      if (layout === 'hierarchy' && !(isHier && !ed.effective_to)) continue
      links.push(layout === 'hierarchy'
        ? { source: ed.to_id, target: ed.from_id, type: ed.relationship_type, open: !ed.effective_to, edgeId: ed.id }
        : { source: ed.from_id, target: ed.to_id, type: ed.relationship_type, open: !ed.effective_to, edgeId: ed.id })
    }
    return { nodes, links }
  }, [bulk, layout, hierRels, etypes])

  useEffect(() => {
    const fg = fgRef.current
    if (!fg || !data.nodes.length) return
    try {
      fg.d3Force('charge').strength(-340).distanceMax(700)
      const lf = fg.d3Force('link'); if (lf) lf.distance(115)
      fg.d3ReheatSimulation()
      const t = setTimeout(() => { try { fg.zoomToFit(500, 60) } catch { /* best effort */ } }, 800)
      return () => clearTimeout(t)
    } catch { /* not ready */ }
  }, [data])

  useEffect(() => {
    if (!focusId || !fgRef.current || !data.nodes.length) return
    const t = setTimeout(() => {
      const node = data.nodes.find(n => n.id === focusId)
      if (node && node.x != null) {
        fgRef.current.centerAt(node.x, node.y, 600)
        fgRef.current.zoom(3, 600); setSelected(node.id)
      }
    }, 800)
    return () => clearTimeout(t)
  }, [focusId, data])

  // Side color for EVERY node (units and facilities alike). Type is
  // carried by SHAPE (round unit vs square site), so the color can
  // always mean "which side" — a friendly and an enemy fuel dump are no
  // longer the same color.
  const nodeColor = useCallback((n) => GRAPH_AFFILIATION_COLORS[n.affiliation] || '#eab308', [])

  const linkColor = useCallback((l) => FAMILY_COLOR[edgeFamily(l.type, rtypes[l.type])], [rtypes])
  const linkLabel = useCallback((l) => {
    if (l.type === '__organic') return 'reports to'
    const rt = rtypes[l.type]
    return `${rt?.label || l.type}${l.open ? '' : ' (ended)'}`
  }, [rtypes])

  const onNodeClick = useCallback((node) => {
    setSelected(node.id)
    // Same placard as the map (user ruling 2026-07-17): clicking a
    // node opens UnitMetadataPanel with the graph-card flow — the
    // panel mounts INSIDE this overlay so it stacks above it.
    if (setSelectedUnitMeta) {
      setSelectedUnitMeta({
        unit: null,
        props: {
          id: String(node.id), source: 'entity_graph',
          name: node.name, echelon: node.echelon,
          affiliation: node.affiliation, sidc: node.sidc,
          kind: node.fixed ? node.entity_type : 'mil_unit',
        },
        coords: (node.lon != null && node.lat != null)
          ? [node.lon, node.lat] : null,
      })
    }
  }, [setSelectedUnitMeta])

  // Connection/unit WRITE affordances removed (S17 cutover, 2026-07-28):
  // relationships and identities are record data — corrections go
  // through the world surface's general verbs, chained to their
  // stating source. This view browses the record; templates and
  // document import remain the authored-build entries.

  const sel = selected && bulk ? bulk.entities.find(e => e.id === selected) : null
  const connections = useMemo(() => {
    if (!sel || !bulk) return []
    const name = (id) => (bulk.entities.find(e => e.id === id) || {}).name || id
    const out = []
    if (sel.organic_parent_id) out.push({ id: null, text: `Reports to ${name(sel.organic_parent_id)}`, open: true })
    for (const ed of bulk.edges || []) {
      const rt = rtypes[ed.relationship_type] || {}
      if (ed.from_id === sel.id) out.push({ id: ed.id, text: `${rt.label || ed.relationship_type} ${name(ed.to_id)}`, open: !ed.effective_to })
      else if (ed.to_id === sel.id) out.push({ id: ed.id, text: `${rt.inverse_label || ed.relationship_type} ${name(ed.from_id)}`, open: !ed.effective_to })
    }
    return out
  }, [sel, bulk, rtypes])
  const selHoldings = useMemo(() => (
    !sel || !bulk ? [] : (bulk.holdings || []).filter(h => h.node_id === sel.id)), [sel, bulk])

  const facTypes = (bulk?.entity_types || []).filter(t => t.is_fixed)
  const isEmpty = bulk && data.nodes.length === 0


  return (
    <div style={S.wrap}>
      <div style={S.side}>
        <div style={S.head}>
          <div>
            <div style={S.title}>Forces &amp; Connections</div>
            <div style={S.sub}>Every unit, site, and who works with whom.</div>
          </div>
          <div style={{ display: 'flex', gap: 2 }}>
            <button style={S.iconBtn} title="Refresh" onClick={reload}>↻</button>
            <button style={S.iconBtn} title="Close" onClick={onClose}>✕</button>
          </div>
        </div>

        <div style={S.toolbar}>
          <button style={{ ...S.btn, ...(layout === 'network' ? S.btnActive : {}) }}
                  onClick={() => setLayout('network')}>Web view</button>
          <button style={{ ...S.btn, ...(layout === 'hierarchy' ? S.btnActive : {}) }}
                  title="Lay it out as a top-down chain of command"
                  onClick={() => setLayout('hierarchy')}>Chain of command</button>
          {onOpenCatalog && <button style={S.btn} onClick={onOpenCatalog}>Equipment</button>}
          <button style={S.btn} onClick={() => fgRef.current && fgRef.current.zoomToFit(500, 60)}>Zoom to fit</button>
        </div>

        <div style={S.body}>
          {error && (
            <div style={{ ...S.card, borderColor: '#7f1d1d', background: '#1f1416', color: '#fca5a5' }}>
              {error}
            </div>)}

          {sel && (
            <div style={S.card}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                <span style={{ width: 14, height: 14, borderRadius: sel.fixed ? 3 : 7,
                  background: nodeColor({ affiliation: sel.affiliation }), flexShrink: 0 }} />
                <strong style={{ flex: 1, fontSize: 14 }}>{sel.name}</strong>
                <button style={{ ...S.btn, padding: '7px 12px', minHeight: 34 }} onClick={() => setEditing(sel.id)}>Edit details</button>
              </div>
              <div style={{ color: '#8b93a7', marginBottom: 8 }}>
                {SIDE_LABEL[sel.affiliation] || sel.affiliation}
                {' · '}{etypes[sel.entity_type]?.label || sel.entity_type}
                {sel.echelon ? ` · ${sel.echelon}` : ''}
              </div>
              {connections.length > 0 && <span style={S.label}>Connections</span>}
              {connections.map((c, i) => (
                <div key={c.id || `o${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0',
                  color: c.open ? '#e6e9f2' : '#6b7280' }}>
                  <span style={{ flex: 1 }}>{c.text}{c.open ? '' : ' (ended)'}</span>
                </div>))}
              {connections.length === 0 && (
                <div style={{ color: '#8b93a7' }}>Not connected to anything yet.</div>)}
              {selHoldings.length > 0 && (
                <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid #232838' }}>
                  <span style={S.label}>Equipment</span>
                  {selHoldings.map(h => (
                    <div key={h.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '2px 0' }}>
                      <span>{h.catalog?.name || h.nomenclature_raw || h.weg_id}</span>
                      <span style={{ color: '#8b93a7', flexShrink: 0 }}>{h.count_current ?? h.count_authorized ?? ''}</span>
                    </div>))}
                </div>)}
            </div>)}
        </div>
      </div>

      <div ref={canvasWrapRef} style={{ flex: 1, position: 'relative', minWidth: 0, overflow: 'hidden' }}>
        {/* Empty state — a real "start here", not a black void. */}
        {isEmpty && (
          <div style={overlayStyle}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>No forces on this map yet</div>
            <div style={{ color: '#8b93a7', marginTop: 8, maxWidth: 380, textAlign: 'center', lineHeight: 1.5 }}>
              Every unit, site, and connection shows up here once the event's documents are ingested.
            </div>
          </div>)}

        {/* Legend — always visible; colors and shapes explained in words. */}
        {!isEmpty && bulk && (
          <div style={legendStyle}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Key</div>
            {SIDE_OPTIONS.map(([k, v]) => (
              <div key={k} style={legendRow}>
                <span style={{ width: 11, height: 11, borderRadius: 6, background: GRAPH_AFFILIATION_COLORS[k] }} />{v}
              </div>))}
            <div style={{ ...legendRow, marginTop: 6, color: '#8b93a7' }}>
              <span style={{ width: 11, height: 11, borderRadius: 6, border: '2px solid #8b93a7' }} />round = unit
            </div>
            <div style={{ ...legendRow, color: '#8b93a7' }}>
              <span style={{ width: 11, height: 11, borderRadius: 2, border: '2px solid #8b93a7' }} />square = site
            </div>
            <div style={{ marginTop: 6, borderTop: '1px solid #232838', paddingTop: 6 }}>
              <div style={legendRow}><span style={{ width: 16, height: 3, background: FAMILY_COLOR.command }} />chain of command</div>
              <div style={legendRow}><span style={{ width: 16, height: 3, background: FAMILY_COLOR.support }} />supports</div>
              <div style={legendRow}><span style={{ width: 16, height: 3, background: FAMILY_COLOR.supply }} />supplies</div>
            </div>
          </div>)}

        {bulk && dims.w > 0 && !isEmpty && (
          <ForceGraph2D
            ref={fgRef}
            width={dims.w}
            height={dims.h}
            graphData={data}
            backgroundColor="rgba(0,0,0,0)"
            dagMode={layout === 'hierarchy' ? 'td' : undefined}
            dagLevelDistance={120}
            nodeRelSize={7}
            nodeColor={nodeColor}
            autoPauseRedraw={false}
            nodePointerAreaPaint={(n, color, ctx) => {
              // Hit target covers the DRAWN glyph box, not a nominal
              // dot — clicking what you see selects what you see.
              ctx.fillStyle = color
              const icon = (n.sidc && !n.fixed) ? _iconFor(n.sidc) : null
              if (icon && icon.ready) {
                const h = 26
                const w = h * icon.w / icon.h
                const ax = w * icon.ax / icon.w
                const ay = h * icon.ay / icon.h
                ctx.fillRect(n.x - ax, n.y - ay, w, h)
              } else {
                ctx.beginPath(); ctx.arc(n.x, n.y, 12, 0, 2 * Math.PI); ctx.fill()
              }
            }}
            nodeCanvasObjectMode={() => 'replace'}
            nodeCanvasObject={(n, ctx, scale) => {
              const r = 7
              const sel = n.id === selectedRef.current
              // Units draw their real doctrinal symbol (same milsymbol
              // pipeline as the map) — plain colored dots made the
              // chain of command unreadable. SVGs cache per SIDC as
              // decoded images; until a glyph decodes (first frames)
              // the color dot stands in. Sites keep the square chip.
              let drewIcon = false
              let halfH = r
              if (n.sidc && !n.fixed) {
                const icon = _iconFor(n.sidc)
                if (icon && icon.ready) {
                  const h = 26
                  const w = h * icon.w / icon.h
                  // anchor = doctrinal icon center within the SVG
                  const ax = w * icon.ax / icon.w
                  const ay = h * icon.ay / icon.h
                  ctx.drawImage(icon.img, n.x - ax, n.y - ay, w, h)
                  drewIcon = true
                  halfH = h - ay        // below-icon extent for the label
                  if (sel) {
                    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5 / scale
                    ctx.strokeRect(n.x - ax - 2, n.y - ay - 2, w + 4, h + 4)
                  }
                }
              }
              if (!drewIcon) {
                ctx.beginPath()
                if (n.fixed) ctx.rect(n.x - r, n.y - r, 2 * r, 2 * r)
                else ctx.arc(n.x, n.y, r, 0, 2 * Math.PI)
                ctx.fillStyle = nodeColor(n); ctx.fill()
                if (sel) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.5; ctx.stroke() }
              }
              // Label CENTERED BELOW the node — EVERY node, ALWAYS
              // (user ruling 2026-07-17: all of them or none at all;
              // no collision-hiding, no labels appearing "willy
              // nilly" as the camera moves). Dense clusters overlap;
              // zooming in separates them.
              const fs = Math.max(11, 13 / scale)
              ctx.font = `600 ${fs}px system-ui, sans-serif`
              const label = n.name || ''
              const pad = 3, tw = ctx.measureText(label).width
              const lx = n.x, ly = n.y + halfH + fs / 2 + 4
              const box = { x: lx - tw / 2 - pad, y: ly - fs / 2 - pad, w: tw + pad * 2, h: fs + pad * 2 }
              ctx.fillStyle = 'rgba(11,14,20,0.8)'
              ctx.fillRect(box.x, box.y, box.w, box.h)
              ctx.fillStyle = '#e6e9f2'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
              ctx.fillText(label, lx, ly)
            }}
            linkColor={linkColor}
            linkWidth={2}
            linkLabel={linkLabel}
            linkDirectionalArrowLength={5}
            linkDirectionalArrowRelPos={0.9}
            linkLineDash={l => (l.open ? null : [4, 4])}
            onNodeClick={onNodeClick}
            onNodeRightClick={(n) => setEditing(n.id)}
            onBackgroundClick={() => setSelected(null)}
          />)}
      </div>

      {editing && bulk && (
        <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 380,
          background: '#0f1117', borderLeft: '1px solid #232838', zIndex: 1, overflowY: 'auto' }}>
          <GraphEntityEditor
            mapId={mapId} userId={userId} bulk={bulk}
            entity={bulk.entities.find(e => e.id === editing) || {}}
            onChanged={reload} onClose={() => setEditing(null)} />
        </div>)}

      {/* The SAME unit placard the map opens — node clicks feed
          selectedUnitMeta; mounted inside this overlay so it stacks
          above the link-view canvas. */}
      <UnitMetadataPanel />
    </div>
  )
}

const overlayStyle = {
  position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: 24,
  color: '#e6e9f2', zIndex: 2, pointerEvents: 'auto',
}
const legendStyle = {
  position: 'absolute', right: 14, bottom: 14, zIndex: 3,
  background: 'rgba(18,20,28,0.92)', border: '1px solid #232838', borderRadius: 10,
  padding: '10px 12px', fontSize: 12, color: '#e6e9f2', lineHeight: 1.4,
  backdropFilter: 'blur(4px)',
}
const legendRow = { display: 'flex', alignItems: 'center', gap: 7, padding: '1px 0' }
