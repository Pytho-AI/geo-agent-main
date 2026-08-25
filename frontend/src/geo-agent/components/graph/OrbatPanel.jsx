// ORBAT panel — full-height left rail over the entity graph
// (design §7). Organic vs task-org view toggle; collapsed to Brigade
// echelon by default with echelon-null (fixed) nodes exempt from the
// fold; fixed entities render as leaf rows (type chip, status badge,
// no strength). The panel shows the FULL command tree over both
// kinds; the OOB read is an API projection, not a panel.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useGeoAgent } from '../../GeoAgentProvider'
import { graphApi, buildTree, typeColor, GRAPH_AFFILIATION_COLORS, ECHELON_ORDER } from '../../utils/graphApi'
import { GraphEntityEditor } from './GraphEntityEditor'

const COLLAPSE_AT = ECHELON_ORDER.indexOf('Brigade')

const S = {
  // Matches the map's panel design system (TacticalOverlaysPanel):
  // floating, blurred, bordered, rounded — not an edge-to-edge rail.
  rail: { position: 'absolute', top: 12, left: 12, bottom: 12, width: 320,
    background: 'rgba(17,19,26,0.88)',
    backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
    color: '#e6e6f0', border: '1px solid rgba(58,58,82,0.6)',
    borderRadius: 6, boxShadow: '0 4px 16px rgba(0,0,0,0.4)', zIndex: 1100,
    display: 'flex', flexDirection: 'column', fontSize: 12 },
  head: { padding: '8px 12px', borderBottom: '1px solid rgba(42,42,58,0.6)',
    fontWeight: 600, letterSpacing: 0.3, fontSize: 11,
    textTransform: 'uppercase', color: '#a0a0b8',
    display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  toolbar: { display: 'flex', flexWrap: 'wrap', gap: 5, padding: '8px 10px',
    borderBottom: '1px solid rgba(42,42,58,0.6)' },
  btn: { background: '#1f2230', color: '#e6e6f0', border: '1px solid #3a3a52',
    borderRadius: 3, padding: '3px 8px', cursor: 'pointer', fontSize: 11,
    lineHeight: 1.4, whiteSpace: 'nowrap' },
  btnActive: { background: '#2b3b6b', borderColor: '#3b5bbb' },
  btnDanger: { borderColor: '#6b2a32', color: '#f0a0a8' },
  iconBtn: { background: 'transparent', color: '#a0a0b8', border: 0,
    cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center',
    fontSize: 14 },
  input: { width: '100%', background: '#16181f', color: '#e6e6f0',
    border: '1px solid #2a2c38', borderRadius: 3, padding: '4px 8px',
    fontSize: 12, boxSizing: 'border-box' },
  row: { display: 'flex', alignItems: 'center', gap: 6, padding: '2px 6px',
    cursor: 'pointer', borderRadius: 3 },
  chip: (c) => ({ width: 11, height: 11, borderRadius: 3, background: c,
    flexShrink: 0 }),
  badge: { fontSize: 10, padding: '1px 5px', borderRadius: 3,
    background: '#262838', color: '#a0a0b8' },
}

function NodeRow({ id, depth, tree, bulk, onSelect, onToggle, expanded, keepSet }) {
  const e = tree.byId[id]
  // When searching, render only children on the keep path.
  const kids = (tree.children[id] || []).filter(k => !keepSet || keepSet.has(k))
  const fixedTypes = useMemo(() => new Set(
    (bulk.entity_types || []).filter(t => t.is_fixed).map(t => t.type_key)), [bulk])
  const isFixed = fixedTypes.has(e.entity_type)
  const typeRow = (bulk.entity_types || []).find(t => t.type_key === e.entity_type)
  const strength = (e.personnel_current != null && e.personnel_authorized)
    ? `${e.personnel_current}/${e.personnel_authorized}` : null
  const echIdx = ECHELON_ORDER.indexOf(e.echelon)
  // Echelon-null nodes are exempt from the brigade fold — revealed
  // whenever their parent is expanded. An active search force-opens
  // the keep path so matches below the fold are visible.
  const isOpen = !!keepSet || expanded.has(id) ||
    (!expanded.has(`closed:${id}`) && (e.echelon == null || echIdx >= COLLAPSE_AT))
  return (
    <div>
      <div style={{ ...S.row, paddingLeft: 6 + depth * 14 }}
           onClick={() => onSelect(e)}>
        {kids.length > 0 && (
          <span style={{ cursor: 'pointer', width: 12 }}
                onClick={(ev) => { ev.stopPropagation(); onToggle(id, isOpen) }}>
            {isOpen ? '▾' : '▸'}
          </span>
        )}
        {kids.length === 0 && <span style={{ width: 12 }} />}
        <span style={S.chip(GRAPH_AFFILIATION_COLORS[e.affiliation] || typeColor(typeRow))} />
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
          whiteSpace: 'nowrap' }}>{e.name}</span>
        {isFixed
          ? <span style={S.badge}>{typeRow?.label || e.entity_type}</span>
          : e.echelon && <span style={S.badge}>{e.echelon}</span>}
        {!isFixed && strength && <span style={S.badge}>{strength}</span>}
        {e.combat_effectiveness && e.combat_effectiveness !== 'effective' &&
          <span style={{ ...S.badge, background: '#6b2a32', color: '#f0a0a8' }}>{e.combat_effectiveness}</span>}
      </div>
      {isOpen && kids.map(k => (
        <NodeRow key={k} id={k} depth={depth + 1} tree={tree} bulk={bulk}
                 onSelect={onSelect} onToggle={onToggle} expanded={expanded}
                 keepSet={keepSet} />
      ))}
    </div>
  )
}

const RANGE_CONDITIONS = [
  { value: '', label: 'Ranges: default' },
  { value: 'night', label: 'Ranges: night' },
  { value: 'day', label: 'Ranges: day' },
  { value: 'extended', label: 'Ranges: extended' },
]

export function OrbatPanel({ mapId, userId, onClose, onOpenLink, onOpenCatalog }) {
  const { mapRef, weatherVisible, weatherLayer } = useGeoAgent()
  const [rangeCondition, setRangeCondition] = useState('')
  // The weather hook: an active precipitation/cloud overlay suggests
  // degraded-visibility employment — surfaced, never auto-switched.
  const weatherSuggestsNight = weatherVisible && ['PR', 'PA0', 'CL'].includes(weatherLayer)
  const [bulk, setBulk] = useState(null)
  const [view, setView] = useState('organic')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const [expanded, setExpanded] = useState(new Set())
  const [error, setError] = useState(null)

  const reload = useCallback(() => {
    graphApi.bulk(mapId).then(b => {
      setBulk(b)
      // Registry stash for the catalog editor's registry tabs — the
      // registries ride every bulk read (design §6).
      window.__graphRegistries = {
        entity_types: b.entity_types,
        relationship_types: b.relationship_types,
        field_defs: b.field_defs,
      }
    }).catch(e => setError(String(e.message || e)))
  }, [mapId])
  useEffect(() => { reload() }, [reload])
  // Hydrate the range-condition toggle from the map record (Finding 5).
  useEffect(() => {
    graphApi.getRangeCondition(mapId).then(setRangeCondition).catch(() => {})
  }, [mapId])

  const tree = useMemo(() => bulk ? buildTree(bulk, view) : null, [bulk, view])

  // keepSet: null = no search, render everything; otherwise the set of
  // node ids to render — matches plus the ancestors AND descendants
  // needed to reach them. Walked over the DISPLAY tree (children map)
  // so it is correct under both organic and task-org views. NodeRow
  // consults it at every level (Finding 6: it must filter children,
  // not just roots).
  const keepSet = useMemo(() => {
    if (!tree || !search.trim()) return null
    const q = search.toLowerCase()
    const matches = bulk.entities
      .filter(e => (e.name || '').toLowerCase().includes(q)).map(e => e.id)
    const keep = new Set()
    // parent lookup over the display tree
    const parentOf = {}
    for (const [pid, kids] of Object.entries(tree.children)) {
      for (const k of kids) parentOf[k] = pid
    }
    const addSubtree = (id) => {
      keep.add(id)
      for (const k of (tree.children[id] || [])) addSubtree(k)
    }
    for (const id of matches) {
      addSubtree(id)                       // the match and everything under it
      let p = parentOf[id]
      while (p && !keep.has(p)) { keep.add(p); p = parentOf[p] }  // ancestors
    }
    return keep
  }, [tree, search, bulk])

  const filteredRoots = useMemo(() => {
    if (!tree) return []
    if (!keepSet) return tree.roots
    return tree.roots.filter(r => keepSet.has(r))
  }, [tree, keepSet])

  const onToggle = (id, isOpen) => {
    const next = new Set(expanded)
    if (isOpen) { next.delete(id); next.add(`closed:${id}`) }
    else { next.add(id); next.delete(`closed:${id}`) }
    setExpanded(next)
  }

  const onSelect = (e) => {
    setSelected(e)
    if (e.lon != null && e.lat != null && mapRef?.current) {
      try { mapRef.current.flyTo({ center: [e.lon, e.lat], zoom: 11 }) } catch { /* focus best-effort */ }
    }
  }

  // "+ Unit" removed (S17 cutover, 2026-07-28): a unit is record data —
  // it enters through ingestion or the world surface's create (basis
  // clause required), never a blank node minted from the toolbar.

  // Import / Wipe / template-instantiate removed (S17 cutover + her
  // 2026-07-28 rulings): bulk material enters through the world-model
  // ingestion pipeline; deleting the PROJECT is the wipe; templates
  // paint as doctrine through the reference walk, never instantiated.

  return (
    <div style={S.rail}>
      <div style={S.head}>
        <span>Order of Battle</span>
        <button style={S.iconBtn} title="Close" aria-label="Close ORBAT"
                onClick={onClose}>✕</button>
      </div>
      {/* One tidy toolbar (wraps within the panel) instead of a row of
          buttons overflowing the map. View toggle, then surfaces, then
          create/import, then destructive. */}
      <div style={S.toolbar}>
        <button style={{ ...S.btn, ...(view === 'task_org' ? S.btnActive : {}) }}
                title="Organic vs task-org view"
                onClick={() => setView(v => v === 'organic' ? 'task_org' : 'organic')}>
          {view === 'organic' ? 'Organic' : 'Task org'}
        </button>
        <button style={S.btn} onClick={onOpenLink}>Graph</button>
        <button style={S.btn} onClick={onOpenCatalog}>Catalog</button>
      </div>
      <div style={{ padding: '8px 10px 4px' }}>
        <input value={search} onChange={e => setSearch(e.target.value)}
               placeholder="Search the tree" style={S.input} />
      </div>
      <div style={{ padding: '0 10px 8px', display: 'flex', gap: 8,
        alignItems: 'center' }}>
        {/* Mutually exclusive employment condition — persisted on the
            map record; fans re-resolve to the matching scenario range
            at paint time (decision 24). */}
        <select value={rangeCondition}
                style={{ ...S.input, width: 'auto', cursor: 'pointer' }}
                onChange={async (e) => {
                  const v = e.target.value
                  setRangeCondition(v)
                  try { await graphApi.setRangeCondition(mapId, v || null) }
                  catch (err) { setError(String(err.message || err)) }
                }}>
          {RANGE_CONDITIONS.map(c => (
            <option key={c.value} value={c.value}>{c.label}</option>))}
        </select>
        {weatherSuggestsNight && !rangeCondition && (
          <span style={{ ...S.badge, background: '#78350f' }}
                title="The active weather overlay suggests degraded visibility — consider night ranges">
            weather: consider night
          </span>
        )}
      </div>
      {error && <div style={{ color: '#f0a0a8', padding: '4px 12px', fontSize: 12 }}>{error}</div>}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 6px' }}>
        {!bulk && !error && <em style={{ padding: 12 }}>Loading…</em>}
        {tree && filteredRoots.map(r => (
          <NodeRow key={r} id={r} depth={0} tree={tree} bulk={bulk}
                   onSelect={onSelect} onToggle={onToggle} expanded={expanded}
                   keepSet={keepSet} />
        ))}
        {tree && tree.roots.length === 0 && (
          <em style={{ display: 'block', padding: 12 }}>
            Empty graph — material enters through ingestion.
          </em>
        )}
      </div>
      {selected && bulk && (
        <GraphEntityEditor
          mapId={mapId} userId={userId} bulk={bulk}
          entity={tree.byId[selected.id] || selected}
          onChanged={reload} onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
