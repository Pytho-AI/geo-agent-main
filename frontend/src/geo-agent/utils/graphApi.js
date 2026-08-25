// Entity-graph API client. Same relative-base convention as api.js —
// everything rides /geo-api/v1 through the embedding stack's proxy.
// No SIDC in any of these contracts (symbols come from /map/state,
// composed server-side at paint time).

const BASE = '/geo-api/v1'

async function req(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { detail = (await res.json()).detail || detail } catch { /* keep */ }
    throw new Error(detail)
  }
  try { return await res.json() } catch { return null }
}

export const graphApi = {
  // Reads
  bulk: (projectId) => req('GET', `/graph/${projectId}`),
  oob: (projectId) => req('GET', `/oob/${projectId}`),
  // Placard-shaped read: unit + parent + children (SIDCs, positions)
  // + subtree equipment rollup + governing position observation.
  card: (nodeId) => req('GET', `/graph/nodes/${nodeId}/card`),
  // As-of resolver read: attribute History chains + reporting
  // statements with Sources + Doctrine + position, resolved at the
  // scrub time (observed_at — the record's one temporal dimension).
  brief: (nodeId, asOf) => {
    const q = new URLSearchParams()
    if (asOf) q.set('as_of', asOf)
    const qs = q.toString()
    return req('GET', `/graph/nodes/${nodeId}/brief${qs ? `?${qs}` : ''}`)
  },

  // Legacy node/edge/holdings CRUD + rearray REMOVED (S17 cutover,
  // 2026-07-28): every record write goes through the world surface's
  // general verbs; an analyst action citing no source is not a record
  // write. The posture list read stays (the placard's working-layer
  // override selector reads it).
  postures: () => req('GET', '/graph/postures'),

  // Extensible fields
  putNodeField: (nodeId, fieldKey, value, updatedBy) =>
    req('PUT', `/graph/nodes/${nodeId}/fields/${encodeURIComponent(fieldKey)}`,
        { value, updated_by: updatedBy }),
  deleteNodeField: (nodeId, fieldKey) =>
    req('DELETE', `/graph/nodes/${nodeId}/fields/${encodeURIComponent(fieldKey)}`),

  // Registry curation UI removed (2026-07-28 ruling): the type/
  // relationship/field registries are internal specifications — rows
  // ride the bulk read; curation happens through the API/agent path.

  // Catalog
  // Paginated catalog read -> {total, offset, rows}. filters:
  // {domain, class, category, country (origin), operator, year_min,
  // year_max}
  equipment: (q, { offset = 0, limit = 50, filters = {} } = {}) => {
    const p = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (q) p.set('q', q)
    for (const [k, v] of Object.entries(filters)) {
      if (v !== '' && v != null) p.set(k, String(v))
    }
    return req('GET', `/equipment?${p}`)
  },
  // Facets are SCOPED: pass the active search + filters and each picker
  // narrows to what the other filters leave (hierarchical pickers).
  equipmentFacets: (q, filters = {}) => {
    const p = new URLSearchParams()
    if (q) p.set('q', q)
    for (const [k, v] of Object.entries(filters)) {
      if (v !== '' && v != null) p.set(k, String(v))
    }
    const qs = p.toString()
    return req('GET', `/equipment/facets${qs ? `?${qs}` : ''}`)
  },
  equipmentTokens: () => req('GET', '/equipment/tokens'),
  // The unified agent chat (catalog + doctrine libraries) — blocking
  // JSON mode; streaming consumers POST /chat with stream:true and read
  // the SSE themselves.
  chat: (message, history = [], extra = {}) =>
    req('POST', '/chat', { message, history, ...extra }),
  // Equipment curation writes (upsert, teach-an-alias) have no UI —
  // reference curation is the API/agent path; the catalog panel is a
  // standalone READ reference.

  // Template instantiate/save, wipe, and document import removed (S17
  // cutover + 2026-07-28 rulings): bulk material enters through the
  // world-model ingestion pipeline; deleting the project is the wipe;
  // doctrine broods paint from the reference walk.


  // Map-level range condition (decision 24, the weather hook): a
  // mutually exclusive employment toggle persisted on the map record
  // (PUT /maps merges attrs); /map/state resolves each system's fan
  // to the condition-matched candidate at paint time.
  setRangeCondition: (projectId, condition) =>
    req('PUT', `/maps/${projectId}`, { attrs: { range_condition: condition } }),
  // Read it back on panel load so the toggle reflects the stored
  // state (Finding 5: it was write-only).
  getRangeCondition: async (projectId) => {
    const m = await req('GET', `/maps/${projectId}`)
    return (m && m.attrs && m.attrs.range_condition) || ''
  },

  // Per-map engagement-range override: PROJECT config that layers on top
  // of the immutable seed default at paint time. Lives in the map
  // record's attrs (like range_condition / basemap / layer_visibility),
  // NEVER written into the reference catalog. Read-modify-write the map
  // (PUT /maps shallow-merges attrs, so the whole overrides object is
  // sent).
  getEquipmentRangeOverrides: async (mapId) => {
    const m = await req('GET', `/maps/${mapId}`)
    return (m && m.attrs && m.attrs.equipment_range_overrides) || {}
  },
  setEquipmentRangeOverride: async (mapId, wegId, rangeM) => {
    const m = await req('GET', `/maps/${mapId}`)
    const cur = (m && m.attrs && m.attrs.equipment_range_overrides) || {}
    const next = { ...cur }
    if (rangeM == null) delete next[wegId]
    else next[wegId] = rangeM
    await req('PUT', `/maps/${mapId}`, { attrs: { equipment_range_overrides: next } })
    return next
  },
}

// Affiliation display colors — mirror of AFFILIATION_COLORS used by
// the map surfaces and the link view.
export const GRAPH_AFFILIATION_COLORS = {
  Hostile: '#ef4444',
  Friend: '#3b82f6',
  Neutral: '#22c55e',
  Unknown: '#eab308',
}

// Deterministic fallback palette for registry rows with no color set.
const FALLBACK = ['#a855f7', '#f59e0b', '#10b981', '#64748b', '#ec4899',
                  '#06b6d4', '#84cc16', '#f97316']
export function typeColor(typeRow) {
  if (typeRow?.color) return typeRow.color
  const key = typeRow?.type_key || ''
  let h = 0
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0
  return FALLBACK[h % FALLBACK.length]
}

// ORBAT helpers ------------------------------------------------------

export const ECHELON_ORDER = ['Team', 'Squad', 'Section', 'Platoon',
  'Company', 'Battalion', 'Regiment', 'Brigade', 'Division', 'Corps', 'Army']

// Build the display tree: organic parents, optionally overlaid by the
// OPEN hierarchical edges (task-org view). Fixed entities render as
// leaf rows under their command parent (design §7).
export function buildTree(bulk, view /* 'organic' | 'task_org' */) {
  const hier = new Set((bulk.relationship_types || [])
    .filter(t => t.is_hierarchical).map(t => t.type_key))
  const parentOf = {}
  for (const e of bulk.entities) parentOf[e.id] = e.organic_parent_id
  if (view === 'task_org') {
    for (const ed of bulk.edges || []) {
      if (hier.has(ed.relationship_type) && !ed.effective_to) {
        parentOf[ed.from_id] = ed.to_id
      }
    }
  }
  const byId = Object.fromEntries(bulk.entities.map(e => [e.id, e]))
  const children = {}
  const roots = []
  for (const e of bulk.entities) {
    const p = parentOf[e.id]
    if (p && byId[p]) (children[p] = children[p] || []).push(e.id)
    else roots.push(e.id)
  }
  const echIdx = (id) => ECHELON_ORDER.indexOf(byId[id]?.echelon)
  const sortIds = ids => ids.sort((a, b) => (echIdx(b) - echIdx(a)) ||
    (byId[a]?.name || '').localeCompare(byId[b]?.name || ''))
  sortIds(roots)
  Object.values(children).forEach(sortIds)
  return { roots, children, byId }
}
