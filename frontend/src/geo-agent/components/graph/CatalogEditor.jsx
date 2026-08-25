// STANDALONE equipment catalog reference (her ruling 2026-07-28): the
// searchable illustrated WEG catalog with the CURATED per-map
// engagement-range pick. The type/relationship/field registries are
// internal specifications — no UI; reference curation (aliases,
// registry rows) happens through the API/agent path.
import { Fragment, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { graphApi, typeColor } from '../../utils/graphApi'
import { GeoAgentContext } from '../../GeoAgentProvider'

// Subframe dark-theme tokens (pytho-vite index.css). This surface is
// embedded in the shell, so it uses the SHELL's background, borders and
// input treatment — a different dark reads as a foreign frame.
const SF = {
  bg: 'var(--color-default-background)',
  border: 'var(--color-neutral-border)',
  font: 'var(--color-default-font)',
  subtext: 'var(--color-subtext-color)',
  brand: 'var(--color-brand-600)',
  brandText: 'var(--color-brand-700)',
  neutral50: 'var(--color-neutral-50)',
  neutral100: 'var(--color-neutral-100)',
  // Row selection / hover: brand tints, so both themes stay legible
  // (a fixed navy is invisible in light mode).
  selected: 'var(--color-brand-100)',
  hover: 'var(--color-neutral-100)',
}

const S = {
  // Fixed to the viewport (matches the link-view Finding-3 fix) so the
  // full-screen editor can't collapse to a mount ancestor or sit under
  // the map controls.
  // Opens FROM the graph viewer (zIndex 1200), so it must sit ABOVE it —
  // solid so nothing bleeds through.
  wrap: { position: 'fixed', inset: 0, background: SF.bg,
    zIndex: 1400, color: SF.font, fontSize: 13,
    display: 'flex', flexDirection: 'column', padding: 16,
    fontFamily: '"Source Sans 3", system-ui, -apple-system, sans-serif' },
  btn: { background: SF.neutral50, color: SF.font,
    border: `1px solid ${SF.border}`, borderRadius: 4,
    padding: '3px 8px', cursor: 'pointer', fontSize: 12 },
  in: { background: SF.neutral50, color: SF.font,
    border: `1px solid ${SF.border}`, borderRadius: 4,
    padding: '4px 8px' },
  row: { display: 'flex', gap: 6, alignItems: 'center', padding: '3px 0',
    borderBottom: `1px solid ${SF.border}` },
}

// Design tokens mirrored from the shell's Subframe dark theme
// (pytho-vite index.css) so the catalog's chat surface is visually the
// SAME chat as the doctrine chat — the shell is where this page lives.
const PAGE_SIZE = 50
const EMPTY_FILTERS = { domain: '', class: '', category: '',
  category_group: '', country: '', operator: '', year_min: '',
  year_max: '' }

// Display-only casing: slugs read as words with military acronyms
// upper-cased; the filter VALUES stay the slugs the API filters on.
const ACRONYMS = new Set(['uav', 'ucav', 'ugv', 'usv', 'uuv', 'apc', 'ifv',
  'atgm', 'sph', 'spm', 'spg', 'mlrs', 'hmg', 'gpmg', 'lmg', 'mmg', 'abm',
  'cbrn', 'c2', 'ew', 'sam', 'aaa', 'mbt', 'rov', 'asv', 'auv', 'alcm',
  'ascm', 'eod', 'vhf', 'uhf', 'ecm', 'gps', 'ied', 'avlb', 'lav', 'spw',
  'smg', 'weg', 'asw', 'icbm'])
const displayCase = (v) => {
  if (v == null) return v
  return String(v).split('_').filter(Boolean).map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase()
      : w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

// Wikipedia-style figure text from the stored image entry: alt from the
// image name (underscores/percent-escapes unwound), caption from name +
// origin + licence/author where the source states them.
const figureAlt = (img, systemName) => {
  const n = String(img?.name || '')
    .replace(/\.(jpg|jpeg|png|avif|gif|webp)$/i, '')
    .replace(/%2[08]/gi, ' ').replace(/[_]+/g, ' ').trim()
  return n || systemName || 'equipment photograph'
}
const ORIGIN_LABELS = {
  live_original: 'ODIN live original',
  backfill_original: 'ODIN live original (backfill)',
  legacy_pdf_extraction: 'WEG PDF extraction',
  export_avif: 'ODIN export',
}
const figureCaption = (img, systemName) => {
  const parts = [figureAlt(img, systemName)]
  if (img?.origin && ORIGIN_LABELS[img.origin]) parts.push(ORIGIN_LABELS[img.origin])
  if (img?.license) parts.push(String(img.license))
  if (img?.author) parts.push(`by ${img.author}`)
  return parts.join(' · ')
}
const imgSrc = (img, size) =>
  `/geo-api/v1/equipment/images/${encodeURIComponent(img.path).replaceAll('%2F', '/')}`
  + (size === 'thumb' ? '?size=thumb' : '')

export function CatalogEditor({ mapId, onClose, onChanged, focusWegId }) {
  const [q, setQ] = useState('')
  // Debounced mirror of the typed query: the list and facets fetch on
  // THIS, so typing costs one request per pause instead of one per
  // keystroke — each keystroke's fetch re-rendered a shrinking list
  // and the catalog visibly skipped/refreshed as it narrowed.
  const [debouncedQ, setDebouncedQ] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300)
    return () => clearTimeout(t)
  }, [q])
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [rows, setRows] = useState([])
  const [facets, setFacets] = useState(null)
  const [tokens, setTokens] = useState([])
  // Per-map engagement-range overrides (PROJECT config layered on the
  // seed default) — read once, updated in place as the analyst picks.
  const [rangeOverrides, setRangeOverrides] = useState({})
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(focusWegId || null)
  const [selectedRow, setSelectedRow] = useState(null)
  // Null-safe: the standalone /equipment-catalog iframe mounts with no
  // provider and no map — pure reference, nothing to refresh.
  const { triggerMapRefresh } = useContext(GeoAgentContext) || {}

  const reloadEquip = useCallback(() => {
    graphApi.equipment(debouncedQ || undefined,
                       { offset, limit: PAGE_SIZE, filters })
      .then((res) => { setRows(res.rows || []); setTotal(res.total || 0) })
      .catch(e => setError(String(e.message || e)))
  }, [debouncedQ, offset, filters])
  useEffect(() => { reloadEquip() }, [reloadEquip])
  // Search/filter changes restart at page one.
  useEffect(() => { setOffset(0) }, [debouncedQ, filters])

  // SCOPED facets: refetched with the live search + filters so every
  // picker narrows to what the other filters leave (hierarchical
  // behavior — domain narrows class narrows category). The token feed
  // for the sheet cross-link matcher stays a single full fetch.
  useEffect(() => {
    graphApi.equipmentFacets(debouncedQ || undefined, filters)
      .then(setFacets).catch(() => {})
  }, [debouncedQ, filters])
  useEffect(() => {
    graphApi.equipmentTokens().then(setTokens).catch(() => {})
  }, [])

  // Load this map's engagement-range overrides once.
  useEffect(() => {
    if (!mapId) return
    graphApi.getEquipmentRangeOverrides(mapId)
      .then(setRangeOverrides).catch(() => {})
  }, [mapId])

  // Deep-link from a placard equipment row: select the system's sheet
  // as soon as the list carries it.
  useEffect(() => {
    if (focusWegId) setSelectedId(focusWegId)
  }, [focusWegId])

  // The selected sheet is fetched INDEPENDENTLY of the page — a deep-
  // linked or previously-selected system stays open while the analyst
  // pages/filters elsewhere.
  useEffect(() => {
    let cancelled = false
    if (!selectedId) { setSelectedRow(null); return undefined }
    const inPage = rows.find(r => r.weg_id === selectedId)
    if (inPage) { setSelectedRow(inPage); return undefined }
    graphApi.equipment(selectedId, { limit: 10 })
      .then((res) => {
        if (cancelled) return
        setSelectedRow((res.rows || [])
          .find(r => r.weg_id === selectedId) || null)
      })
      .catch(() => { if (!cancelled) setSelectedRow(null) })
    return () => { cancelled = true }
  }, [selectedId, rows])

  // Host protocol inbound: a citation clicked in the sibling chat frame
  // opens that system's sheet here; the chat frame's own close control
  // clears the button's active state.
  useEffect(() => {
    const onMessage = (event) => {
      const data = event.data || {}
      if (data.type === 'geoagent.catalog.openSystem' && data.weg_id) {
        setSelectedId(String(data.weg_id))
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  const selected = selectedRow

  return (
    <div style={S.wrap}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <strong style={{ flex: 1 }}>Equipment catalog</strong>

        {onClose && <button style={S.btn} onClick={onClose}>✕</button>}
      </div>
      {error && <div style={{ color: 'var(--color-error-700)' }}>{error}</div>}
      {(
        <div style={{ flex: 1, display: 'flex', gap: 14, minHeight: 0 }}>
          {/* Left: search + filters + paged system list */}
          <div style={{ width: 340, minWidth: 340, display: 'flex',
                        flexDirection: 'column', minHeight: 0 }}>
            <input style={{ ...S.in, marginBottom: 6 }}
                   placeholder="Search"
                   value={q} autoFocus
                   onChange={e => setQ(e.target.value)} />
            <FilterBar facets={facets} filters={filters}
                       onChange={setFilters} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8,
                          color: SF.subtext, fontSize: 11, margin: '4px 0' }}>
              <span style={{ flex: 1 }}>
                {total === 0 ? 'no systems'
                  : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
              </span>
              <button style={{ ...S.btn, padding: '1px 7px',
                               opacity: offset > 0 ? 1 : 0.4 }}
                      disabled={offset <= 0}
                      onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                ‹ prev
              </button>
              <button style={{ ...S.btn, padding: '1px 7px',
                               opacity: offset + PAGE_SIZE < total ? 1 : 0.4 }}
                      disabled={offset + PAGE_SIZE >= total}
                      onClick={() => setOffset(offset + PAGE_SIZE)}>
                next ›
              </button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto',
                          border: `1px solid ${SF.border}`, borderRadius: 6 }}>
              {rows.map(r => (
                <div key={r.weg_id}
                     onClick={() => setSelectedId(r.weg_id)}
                     style={{ display: 'flex', alignItems: 'center', gap: 8,
                              padding: '6px 8px', cursor: 'pointer',
                              borderBottom: `1px solid ${SF.border}`,
                              background: r.weg_id === (selected && selected.weg_id)
                                ? SF.selected : 'transparent' }}>
                  <span style={{ width: 48, height: 34, flexShrink: 0,
                                 display: 'flex', alignItems: 'center',
                                 justifyContent: 'center' }}>
                    {r.image_url && (
                      <img src={`/geo-api/v1${r.image_url}?size=thumb`}
                           alt={figureAlt((r.images || [])[0], r.name)}
                           loading="lazy"
                           style={{ maxWidth: 48, maxHeight: 34,
                                    width: 'auto', height: 'auto',
                                    objectFit: 'contain', borderRadius: 2 }} />
                    )}
                  </span>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
                    <span style={{ display: 'block', overflow: 'hidden',
                                   textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          title={r.name}>{r.name}</span>
                    <span style={{ color: SF.subtext, fontSize: 10,
                                   display: 'block', overflow: 'hidden',
                                   textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {[r.country_of_origin, r.category || displayCase(r.class)]
                        .filter(Boolean).join(' · ')}
                    </span>
                  </span>
                </div>
              ))}
              {rows.length === 0 && (
                <div style={{ color: SF.subtext, padding: 16, fontSize: 12 }}>
                  No systems match.
                </div>
              )}
            </div>
          </div>

          {/* Right: the WEG sheet for the selected system */}
          <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
            {selected ? (
              <WegSheet key={selected.weg_id} row={selected}
                        tokens={tokens} onOpen={setSelectedId}
                        onError={setError} mapId={mapId}
                        rangeOverride={rangeOverrides[selected.weg_id]}
                        onRangeOverride={async (rangeM) => {
                          if (!mapId) return
                          try {
                            const next = await graphApi.setEquipmentRangeOverride(
                              mapId, selected.weg_id, rangeM)
                            setRangeOverrides(next)
                            // Repaint the map from the updated map state
                            // so the range fan re-resolves immediately.
                            triggerMapRefresh && triggerMapRefresh()
                          } catch (e) { setError(String(e.message || e)) }
                        }}
                        onSaved={() => { reloadEquip(); onChanged && onChanged() }} />
            ) : (
              <div style={{ color: SF.subtext, padding: 24 }}>
                Select a system to open its sheet.
              </div>
            )}
          </div>

          
        </div>
      )}

    </div>
  )
}

// Styled searchable selector (the Active-Event-selector pattern: value
// button + popover with a filter input) — NEVER a native browser
// <select>. Searchability matters here: 208 operators and 379 classes
// are unfindable in a native dropdown.
function SelectBox({ value, placeholder, options, onChange }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  const opts = options || []
  const optLabel = (o) => o.label != null ? o.label : displayCase(String(o.value))
  const shown = opts.filter(o => !filter
    || optLabel(o).toLowerCase().includes(filter.toLowerCase()))
  const current = opts.find(o => String(o.value) === String(value))
  return (
    <div ref={ref} style={{ position: 'relative', flex: '1 1 46%', minWidth: 0 }}>
      <button style={{ ...S.in, width: '100%', display: 'flex',
                       alignItems: 'center', justifyContent: 'space-between',
                       gap: 6, cursor: 'pointer', fontSize: 11,
                       color: value ? SF.font : SF.subtext }}
              onClick={() => { setOpen(v => !v); setFilter('') }}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis',
                       whiteSpace: 'nowrap' }}>
          {current ? `${optLabel(current)}${current.count != null ? ` (${current.count})` : ''}`
            : (value ? displayCase(String(value)) : placeholder)}
        </span>
        <span style={{ color: SF.subtext, flexShrink: 0 }}>▾</span>
      </button>
      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0,
                      minWidth: '100%', width: 'max-content', maxWidth: 300,
                      zIndex: 1550, background: SF.neutral50,
                      border: `1px solid ${SF.border}`, borderRadius: 6,
                      boxShadow: '0 8px 24px rgba(0,0,0,0.55)',
                      maxHeight: 300, display: 'flex',
                      flexDirection: 'column' }}>
          <input autoFocus style={{ ...S.in, margin: 6, fontSize: 12 }}
                 placeholder={`Filter ${placeholder}…`} value={filter}
                 onChange={e => setFilter(e.target.value)} />
          <div style={{ overflowY: 'auto' }}>
            <div style={{ padding: '5px 10px', cursor: 'pointer',
                          color: SF.subtext, fontSize: 12 }}
                 onClick={() => { onChange(''); setOpen(false) }}>
              any {placeholder}
            </div>
            {shown.map((o, i) => {
              // Options carrying a group render as a TREE: a header row
              // per group (the source's taxonomy level above the leaf),
              // leaves indented beneath it. Group-less leaves sit
              // directly under their domain root and list first.
              const header = o.group && o.group !== shown[i - 1]?.group
                ? (
                  <div key={`hdr-${o.group}`}
                       style={{ padding: '6px 10px 2px', fontSize: 10,
                                color: SF.subtext,
                                textTransform: 'uppercase',
                                letterSpacing: 0.4 }}>
                    {o.group}
                  </div>
                ) : null
              return (
                <Fragment key={String(o.value)}>
                  {header}
                  <div style={{ padding: '5px 10px', cursor: 'pointer',
                                fontSize: 12,
                                paddingLeft: o.group ? 18 : 10,
                                background: String(o.value) === String(value)
                                  ? SF.selected : 'transparent' }}
                       onMouseEnter={e => { e.currentTarget.style.background = SF.hover }}
                       onMouseLeave={e => {
                         e.currentTarget.style.background =
                           String(o.value) === String(value) ? SF.selected : 'transparent'
                       }}
                       onClick={() => { onChange(o.value); setOpen(false) }}>
                    {optLabel(o)}
                    {o.count != null && (
                      <span style={{ color: SF.subtext }}> ({o.count})</span>
                    )}
                  </div>
                </Fragment>
              )
            })}
            {shown.length === 0 && (
              <div style={{ padding: '6px 10px', color: SF.subtext,
                            fontSize: 12 }}>no matches</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// Simple filters inline; the full set lives in the Advanced modal.
// Every select is populated from the SCOPED facets (counts reflect the
// other active filters — hierarchical pickers), alphabetical, cased for
// reading. Origin = who built it; Operator = who fields it.
function FilterBar({ facets, filters, onChange }) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const set = (k, v) => onChange({ ...filters, [k]: v })
  const any = Object.values(filters).some(v => v !== '' && v != null)
  const advancedActive = ['operator', 'class', 'year_min', 'year_max']
    .filter(k => filters[k] !== '' && filters[k] != null).length
  const sel = (key, label) => (
    <SelectBox key={key} value={filters[key] ?? ''} placeholder={label}
               options={(facets && facets[key]) || []}
               onChange={v => set(key, v)} />
  )
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4,
                  marginBottom: 4 }}>
      {sel('country', 'origin')}
      {sel('domain', 'domain')}
      {/* The source's taxonomy, two linked levels: pick a group and the
          category picker narrows to its leaves (scoped facets); the
          category picker alone shows the whole tree with group
          headers. */}
      {sel('category_group', 'group')}
      {sel('category', 'category')}
      <button style={{ ...S.btn, fontSize: 11, flex: '1 1 46%' }}
              onClick={() => setShowAdvanced(true)}>
        advanced{advancedActive ? ` (${advancedActive})` : ''}
      </button>
      {any && (
        <button style={{ ...S.btn, fontSize: 11, flex: '1 1 100%' }}
                onClick={() => onChange({ ...EMPTY_FILTERS })}>
          clear filters
        </button>
      )}
      {showAdvanced && (
        <AdvancedFilters facets={facets} filters={filters}
                         onChange={onChange}
                         onClose={() => setShowAdvanced(false)} />
      )}
    </div>
  )
}

// Advanced filter modal (styled in-app — browser popups are banned):
// operator (proliferation), equipment class, and the introduction-year
// range the data supports on 4,039 of 4,297 records.
function AdvancedFilters({ facets, filters, onChange, onClose }) {
  const yr = (facets && facets.year_range) || {}
  const set = (k, v) => onChange({ ...filters, [k]: v })
  const row = (label, child) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10,
                  padding: '6px 0' }}>
      <span style={{ width: 150, color: SF.subtext, fontSize: 11,
                     textTransform: 'uppercase', letterSpacing: 0.4 }}>
        {label}
      </span>
      {child}
    </div>
  )
  const sel = (key, label) => (
    <SelectBox value={filters[key] ?? ''} placeholder={label}
               options={(facets && facets[key]) || []}
               onChange={v => set(key, v)} />
  )
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1500,
                  background: 'rgba(4,6,10,0.72)', display: 'flex',
                  alignItems: 'center', justifyContent: 'center' }}
         onClick={onClose}>
      <div style={{ background: SF.neutral50, border: `1px solid ${SF.border}`,
                    borderRadius: 8, padding: 18, width: 440,
                    maxWidth: '92vw' }}
           onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center',
                      marginBottom: 8 }}>
          <strong style={{ flex: 1 }}>Advanced filters</strong>
          <button style={S.btn} onClick={onClose}>✕</button>
        </div>
        {row('Operator', sel('operator', 'any operator (proliferation)'))}
        {row('Class', sel('class', 'any class'))}
        {row('Introduced', (
          <span style={{ display: 'flex', gap: 8, flex: 1,
                         alignItems: 'center' }}>
            <input style={{ ...S.in, width: 90 }} type="number"
                   placeholder={yr.min != null ? String(yr.min) : 'from'}
                   value={filters.year_min ?? ''}
                   onChange={e => set('year_min', e.target.value)} />
            <span style={{ color: SF.subtext }}>to</span>
            <input style={{ ...S.in, width: 90 }} type="number"
                   placeholder={yr.max != null ? String(yr.max) : 'to'}
                   value={filters.year_max ?? ''}
                   onChange={e => set('year_max', e.target.value)} />
          </span>
        ))}
        <div style={{ display: 'flex', gap: 8, marginTop: 12,
                      justifyContent: 'flex-end' }}>
          <button style={S.btn}
                  onClick={() => onChange({ ...filters, operator: '',
                    class: '', year_min: '', year_max: '' })}>
            clear advanced
          </button>
          <button style={{ ...S.btn, background: SF.brand }}
                  onClick={onClose}>
            done
          </button>
        </div>
      </div>
    </div>
  )
}

// Full-size figure lightbox: uncropped image, Wikipedia-style caption
// (name, origin, licence/author), prev/next across the system's
// gallery. In-app modal, never a browser popup.
function Lightbox({ images, index, systemName, onClose, onStep }) {
  const img = images[index]
  if (!img) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1600,
                  background: 'rgba(2,3,6,0.88)', display: 'flex',
                  flexDirection: 'column', alignItems: 'center',
                  justifyContent: 'center', gap: 10 }}
         onClick={onClose}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}
           onClick={e => e.stopPropagation()}>
        <button style={{ ...S.btn, fontSize: 18,
                         visibility: index > 0 ? 'visible' : 'hidden' }}
                onClick={() => onStep(index - 1)}>‹</button>
        <img src={imgSrc(img)} alt={figureAlt(img, systemName)}
             style={{ maxWidth: '78vw', maxHeight: '78vh',
                      objectFit: 'contain', borderRadius: 4,
                      border: `1px solid ${SF.border}` }} />
        <button style={{ ...S.btn, fontSize: 18,
                         visibility: index < images.length - 1
                           ? 'visible' : 'hidden' }}
                onClick={() => onStep(index + 1)}>›</button>
      </div>
      <div style={{ color: SF.font, fontSize: 12, maxWidth: '70vw',
                    textAlign: 'center' }}
           onClick={e => e.stopPropagation()}>
        {figureCaption(img, systemName)}
        <span style={{ color: SF.subtext }}>
          {`  ·  ${index + 1}/${images.length}`}
        </span>
      </div>
      <button style={{ ...S.btn, position: 'absolute', top: 18, right: 18 }}
              onClick={onClose}>✕</button>
    </div>
  )
}


// Cross-link plain text against the catalog: every mention of another
// system (by NAME or taught ALIAS, e.g. the NATO reporting name "DOG
// EAR" -> Sborka) renders as a link that opens that system's sheet.
function Linkified({ text, matcher, onOpen }) {
  const nodes = []
  let rest = text
  let guard = 0
  while (rest && guard++ < 200) {
    let best = null
    const lower = rest.toLowerCase()
    for (const [token, wegId] of matcher) {
      const idx = lower.indexOf(token)
      if (idx === -1) continue
      // Word-ish boundaries so "Grad" doesn't light inside "degraded".
      const before = idx === 0 ? ' ' : lower[idx - 1]
      const after = idx + token.length >= lower.length
        ? ' ' : lower[idx + token.length]
      if (/[a-z0-9]/.test(before) || /[a-z0-9]/.test(after)) continue
      if (!best || idx < best.idx
          || (idx === best.idx && token.length > best.token.length)) {
        best = { idx, token, wegId }
      }
    }
    if (!best) { nodes.push(rest); break }
    if (best.idx > 0) nodes.push(rest.slice(0, best.idx))
    const shown = rest.slice(best.idx, best.idx + best.token.length)
    const wegId = best.wegId
    nodes.push(
      <a key={nodes.length} href="#weg"
         style={{ color: SF.brand, textDecoration: 'underline',
                  cursor: 'pointer' }}
         onClick={(e) => { e.preventDefault(); onOpen(wegId) }}>
        {shown}
      </a>,
    )
    rest = rest.slice(best.idx + best.token.length)
  }
  return <>{nodes}</>
}

// WEG-sheet layout for one system: identification header, photo,
// characteristics, the RANGES block (the curated engagement-range
// scenario toggle + detection range — the same mutually-exclusive
// picker the old row carried) and emitters; taught aliases list read-only.
function WegSheet({ row, tokens, onOpen, onSaved, onError,
                   mapId, rangeOverride, onRangeOverride }) {
  // Catalog match tokens (other systems only), built from the FULL
  // catalog token feed (never the paged list — a late-alphabet system
  // must still link). Name-derived tokens require a digit or hyphen so
  // generic words ("command vehicle", "radar") don't light up as
  // links; taught ALIASES are always allowed (a reporting name like
  // "DOG EAR" carries no digit but IS the link the analyst wants).
  // Longest first so "Sborka-M1-2" wins over "Sborka".
  const matcher = (() => {
    const out = []
    const hasDigitOrHyphen = (t) => /[0-9-]/.test(t)
    const addName = (t, wegId) => {
      const s = String(t || '').trim()
      if (s.length >= 4 && hasDigitOrHyphen(s)) out.push([s.toLowerCase(), wegId])
    }
    const addAlias = (t, wegId) => {
      const s = String(t || '').trim()
      if (s.length >= 3) out.push([s.toLowerCase(), wegId])
    }
    for (const r of tokens || []) {
      if (r.weg_id === row.weg_id) continue
      const nm = String(r.name || '').trim()
      addName(nm, r.weg_id)
      const lead = nm.split('(')[0].trim()
      addName(lead, r.weg_id)
      for (const part of lead.split(/\s+and\s+/i)) addName(part, r.weg_id)
      for (const a of r.aliases || []) addAlias(a, r.weg_id)
    }
    // Deduplicate identical (token -> weg) pairs, keep longest first.
    const seen = new Set()
    const uniq = out.filter(([t, w]) => {
      const k = `${t}|${w}`
      if (seen.has(k)) return false
      seen.add(k); return true
    })
    uniq.sort((a, b) => b[0].length - a[0].length)
    return uniq
  })()
  const candidates = row.range_candidates || []
  // Display-side cleanup of the range candidates: the stored label and
  // condition carry extraction/adjudication bookkeeping verbatim
  // ("meters as printed, shared munitions block -- this sub-line may be
  // more specifically attributable to..."). The verbatim stays in the
  // data; the SHEET shows the doctrine-shaped part only, deduped.
  const trimCond = (c) => {
    if (!c) return ''
    let s = String(c).split(' -- ')[0].trim().replace(/^\(|\)$/g, '')
    s = s.replace(/meters as printed[,;]?\s*/gi, '')
      .replace(/shared [^,;]*munitions? block[^,;]*/gi, '')
      .replace(/^[,;\s]+|[,;\s]+$/g, '').trim()
    return s.length > 60 ? '' : s
  }
  // One entry per DISTINCT range value (the sheet prints the same figure
  // from several shared munition blocks); a range keeps the most
  // informative condition seen and the default flag if any copy had it.
  const dedupedCandidates = (() => {
    const byRange = new Map()
    for (const c of candidates) {
      const shownCond = trimCond(c.condition)
      const baseLabel = String(c.label || 'Stated range')
        .split(' -- ')[0].split('(')[0].trim()
      const prev = byRange.get(c.range_m)
      if (!prev) {
        byRange.set(c.range_m, { ...c, shownCond, shownLabel: baseLabel })
      } else {
        if (!prev.shownCond && shownCond) prev.shownCond = shownCond
        if (c.is_default) prev.is_default = true
      }
    }
    return [...byRange.values()].sort((a, b) => a.range_m - b.range_m)
  })()
  // Grouped one-row-per-label view for the reference sheet: the ranges
  // read like the printed sheet ("7,100 m (standard) · 12,800 m
  // (extended) — default"), never a wall of numbered repeats.
  const rangeRows = (() => {
    const byLabel = new Map()
    for (const c of dedupedCandidates) {
      if (!byLabel.has(c.shownLabel)) byLabel.set(c.shownLabel, [])
      byLabel.get(c.shownLabel).push(
        `${c.range_m.toLocaleString()} m`
        + (c.shownCond ? ` (${c.shownCond})` : '')
        + (c.is_default ? ' — default' : ''))
    }
    return [...byLabel.entries()]
  })()
  // Effective range = this map's analyst override (project config), else
  // the seed default. The seed default (row.engagement_range_m) is
  // immutable reference; the override lives on the map, never here.
  const seedDefault = row.engagement_range_m
  const effRange = rangeOverride != null ? rangeOverride : seedDefault
  const active = candidates.find(c => c.range_m === effRange)
  const sheetRow = (label, value) => (value == null || value === '' ? null : (
    <div key={label} style={{ display: 'flex', gap: 10, padding: '4px 0',
                              borderBottom: `1px solid ${SF.border}` }}>
      <span style={{ width: 190, color: SF.subtext, flexShrink: 0,
                     textTransform: 'uppercase', fontSize: 11,
                     letterSpacing: 0.4, paddingTop: 1 }}>{label}</span>
      <span style={{ flex: 1 }}>{String(value)}</span>
    </div>
  ))
  const sectionHead = (t) => (
    <div style={{ margin: '16px 0 4px', fontWeight: 700, fontSize: 12,
                  letterSpacing: 0.6, textTransform: 'uppercase',
                  color: SF.subtext, borderBottom: `1px solid ${SF.border}`,
                  paddingBottom: 3 }}>{t}</div>
  )
  const gallery = (row.images || []).filter(im => im && im.path)
  const [lightbox, setLightbox] = useState(null)
  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{row.name}</div>
          {/* Analyst-facing classification only — the weg_id and the
              internal bin name are system identifiers, not sheet
              content. The breadcrumb is the source's own taxonomy walk;
              class appends when the walk doesn't already end there. */}
          <div style={{ color: SF.subtext, fontSize: 12, marginTop: 2 }}>
            {(row.category_path && row.category_path.length
              ? row.category_path.join(' › ')
                + (row.class && displayCase(row.class) !== row.category_path[row.category_path.length - 1]
                  ? ` · ${displayCase(row.class)}` : '')
              : [displayCase(row.class), displayCase(row.domain)]
                  .filter(Boolean).join(' · '))}
          </div>
        </div>
        {gallery.length > 0 && (
          <figure style={{ margin: 0, maxWidth: 280 }}>
            <img src={imgSrc(gallery[0])}
                 alt={figureAlt(gallery[0], row.name)}
                 onClick={() => setLightbox(0)}
                 style={{ maxWidth: 280, maxHeight: 190, width: 'auto',
                          height: 'auto', objectFit: 'contain',
                          borderRadius: 4, border: `1px solid ${SF.border}`,
                          cursor: 'zoom-in', display: 'block' }} />
            <figcaption style={{ color: SF.subtext, fontSize: 10,
                                 marginTop: 3, lineHeight: 1.4 }}>
              {figureCaption(gallery[0], row.name)} · click for full size
            </figcaption>
          </figure>
        )}
      </div>
      {gallery.length > 1 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap',
                      marginTop: 10 }}>
          {gallery.map((im, i) => (
            <figure key={i} style={{ margin: 0, width: 92 }}>
              <img src={imgSrc(im, 'thumb')}
                   alt={figureAlt(im, row.name)} loading="lazy"
                   onClick={() => setLightbox(i)}
                   style={{ maxWidth: 92, maxHeight: 64, width: 'auto',
                            height: 'auto', objectFit: 'contain',
                            borderRadius: 3, border: `1px solid ${SF.border}`,
                            cursor: 'zoom-in', display: 'block' }} />
              <figcaption style={{ color: SF.subtext, fontSize: 9,
                                   overflow: 'hidden', whiteSpace: 'nowrap',
                                   textOverflow: 'ellipsis' }}
                          title={figureCaption(im, row.name)}>
                {figureAlt(im, row.name)}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {lightbox != null && (
        <Lightbox images={gallery} index={lightbox} systemName={row.name}
                  onClose={() => setLightbox(null)} onStep={setLightbox} />
      )}

      {sectionHead('Characteristics')}
      {sheetRow('Country of origin', row.country_of_origin)}
      {sheetRow('Alternative designations', row.alternative_designations)}
      {sheetRow('Crew', row.crew)}
      {sheetRow('Caliber', row.caliber)}
      {sheetRow('Combat weight', row.combat_weight)}
      {sheetRow('Road speed', row.road_speed_kph != null
        ? `${row.road_speed_kph} km/h` : null)}
      {sheetRow('Date of introduction', row.date_of_introduction)}
      {sheetRow('Proliferation', row.proliferation_note)}

      {row.description && (
        <>
          {sectionHead('Description')}
          <div style={{ fontSize: 12, lineHeight: 1.55, color: SF.font }}>
            {String(row.description).split(/;\s+/).map((seg, i) => (
              <div key={i} style={{ padding: '2px 0' }}>
                <Linkified text={seg} matcher={matcher} onOpen={onOpen} />
              </div>
            ))}
          </div>
        </>
      )}
      {!row.description && row.characteristics && (
        <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.55,
                      color: SF.font }}>
          {String(row.characteristics).split(/;\s+/).map((seg, i) => (
            <div key={i} style={{ padding: '2px 0',
                                  borderBottom: `1px solid ${SF.border}` }}>
              <Linkified text={seg} matcher={matcher} onOpen={onOpen} />
            </div>
          ))}
        </div>
      )}

      {row.sheet_data && row.sheet_data.specs
        && Object.keys(row.sheet_data.specs).length > 0 && (
        <>
          {sectionHead('Specifications')}
          {/* specs = {section: {label: value}} — the source's own
              subsections (weapon stations, ammunition options) render
              under their names; the '' section is the general block. */}
          {Object.entries(row.sheet_data.specs).map(([section, rows]) => (
            <Fragment key={section || 'general'}>
              {section && (
                <div style={{ padding: '8px 0 2px', fontSize: 11,
                              letterSpacing: 0.4,
                              textTransform: 'uppercase',
                              color: SF.subtext, fontWeight: 600 }}>
                  {section}
                </div>
              )}
              {typeof rows === 'object' && rows !== null
                ? Object.entries(rows).map(([l, v]) => sheetRow(l, v))
                : sheetRow(section, rows)}
            </Fragment>
          ))}
        </>
      )}

      {/* The RANGES section renders only when the system HAS range
          content — a header over nothing reads as a data hole even when
          the source genuinely states no engagement range (mines,
          satellites, recon vehicles). */}
      {(candidates.length > 0 || seedDefault != null
        || row.detection_range_m != null || rangeOverride != null) && (
      <>
      {sectionHead('Ranges')}
      {mapId && (
        <>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center',
                        padding: '6px 0' }}>
            <span style={{ width: 190, color: SF.subtext, fontSize: 11,
                           textTransform: 'uppercase', letterSpacing: 0.4 }}>
              Effective range (this map)
            </span>
            <div style={{ flex: 1, minWidth: 0, display: 'flex' }}
                 title={rangeOverride != null
                   ? 'Overridden for this map — layered over the seed default'
                   : 'The seed default; pick another range to override it on THIS map only (the catalog stays unchanged)'}>
              <SelectBox value={effRange != null ? String(effRange) : '__default'}
                         placeholder="effective range"
                         options={[
                           { value: '__default',
                             label: `Seed default${seedDefault != null ? ` — ${seedDefault} m` : ' — no fan'}` },
                           ...dedupedCandidates.map(c => ({
                             value: String(c.range_m),
                             label: `${c.range_m} m${c.shownCond ? ` — ${c.shownCond}` : ''}${c.is_default ? ' (default)' : ''}`,
                           })),
                           ...(rangeOverride != null
                             && !candidates.some(c => c.range_m === rangeOverride)
                             ? [{ value: String(rangeOverride),
                                  label: `${rangeOverride} m — custom override` }]
                             : []),
                         ]}
                         onChange={(val) => {
                           onRangeOverride(val === '__default' || val === ''
                             ? null : Number(val))
                         }} />
            </div>
          </div>
          {rangeOverride != null && (
            <div style={{ color: SF.subtext, fontSize: 11, paddingLeft: 200,
                          marginTop: -2 }}>
              Overridden on this map (seed default {seedDefault != null
                ? `${seedDefault} m` : 'no fan'}) ·{' '}
              <a href="#reset" style={{ color: SF.brand, cursor: 'pointer' }}
                 onClick={(e) => { e.preventDefault(); onRangeOverride(null) }}>
                reset to default
              </a>
            </div>
          )}
        </>
      )}
      {!mapId && sheetRow('Effective range',
        seedDefault != null ? `${seedDefault.toLocaleString()} m` : null)}
      {sheetRow('Detection range', row.detection_range_m != null
        ? `${row.detection_range_m.toLocaleString()} m` : null)}
      {rangeRows.map(([label, vals]) => sheetRow(label, vals.join(' · ')))}
      </>
      )}

      {(row.emitters || []).length > 0 && (
        <>
          {sectionHead('Emitters')}
          {(row.emitters || []).map((em, i) => (
            <div key={i} style={{ padding: '4px 0', fontSize: 12,
                                  borderBottom: `1px solid ${SF.border}` }}>
              <div>{em.emitter_type || 'Emitter'}</div>
              <div style={{ color: SF.subtext }}>
                {[em.frequency_band ? `band ${em.frequency_band}` : null,
                  em.frequency_ghz != null ? `${em.frequency_ghz} GHz` : null,
                  em.effective_range_km != null ? `effective ${em.effective_range_km} km` : null,
                  em.tracking_range_km != null ? `tracking ${em.tracking_range_km} km` : null]
                  .filter(Boolean).join(' · ')}
              </div>
            </div>
          ))}
        </>
      )}

      {/* Teach-an-alias UI removed (2026-07-28 ruling: reference
          curation needs no human UI intervention) — aliases are taught
          through the API/agent path; taught aliases still LIST above. */}
    </div>
  )
}

// The verbatim sheet capture stores whole tables as STRINGIFIED JSON
// (radars, ammunition natures, armament blocks). Raw JSON on the pane
// is not UI: parse it back and lay each entry out as label/value rows.
function renderSpecBlock(label, v, sheetRow) {
  let parsed = v
  if (typeof v === 'string') {
    const t = v.trim()
    if ((t.startsWith('[') && t.endsWith(']')) || (t.startsWith('{') && t.endsWith('}'))) {
      try { parsed = JSON.parse(t) } catch { parsed = v }
    }
  }
  const kv = (obj, i) => (
    <div key={i} style={{ padding: '4px 0 4px 12px', fontSize: 12,
                          borderBottom: `1px solid ${SF.border}`,
                          overflowWrap: 'anywhere' }}>
      {Object.entries(obj)
        .filter(([, val]) => val != null && String(val).trim() !== '')
        .map(([kk, val]) => (
          <div key={kk} style={{ display: 'flex', gap: 8, padding: '1px 0' }}>
            <span style={{ color: SF.subtext, minWidth: 170, flexShrink: 0 }}>
              {String(kk).replace(/_/g, ' ')}
            </span>
            <span style={{ color: SF.font }}>{String(val)}</span>
          </div>
        ))}
    </div>
  )
  if (Array.isArray(parsed) && parsed.every(x => x && typeof x === 'object')) {
    return (
      <div key={label} style={{ marginTop: 6 }}>
        <div style={{ color: SF.subtext, fontSize: 11, textTransform: 'uppercase',
                      letterSpacing: 0.4, padding: '4px 0' }}>{label}</div>
        {parsed.map((item, i) => kv(item, i))}
      </div>
    )
  }
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    return (
      <div key={label} style={{ marginTop: 6 }}>
        <div style={{ color: SF.subtext, fontSize: 11, textTransform: 'uppercase',
                      letterSpacing: 0.4, padding: '4px 0' }}>{label}</div>
        {kv(parsed, 0)}
      </div>
    )
  }
  return sheetRow(label, Array.isArray(parsed) ? parsed.join(', ') : parsed)
}

