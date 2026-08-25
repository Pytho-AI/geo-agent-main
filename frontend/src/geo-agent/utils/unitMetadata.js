/**
 * Unit metadata index — fetches the latest resolved RED OOB from the main
 * backend and indexes the per-unit records so the operations-map
 * left-click panel can resolve a clicked mil_unit to its MGRS / linked
 * equipment / last known activity.
 *
 * Source: GET /api/oob/resolved_latest → { units: named_units[],
 * snapshot_ts_ms } (served from scenario.KG["unit_red"], the canonical
 * scenario OOB). These are the SAME records that drive the units painted
 * on the master map (build_geo_agent_sync_payload tags each mil_unit
 * with source_kbid = the unit's kg_id), so every clickable unit has a
 * record here. We join on kg_id first, then fall back to the unit name
 * (names are unique within the RED OOB).
 *
 * Hierarchy: the snapshot has no children lists — each unit carries a
 * `parent_kg_id`. We invert that relation here into childrenByParent
 * keyed on the parent's kg_id, so the panel can render a full
 * subordinate tree client-side via an exact uuid join (no name/alias
 * string-matching).
 *
 * Note: this hits the MAIN pytho-app backend (same origin, /api/...), not
 * the geo-agent service (/api/v1). Hence the bare relative URL rather than
 * the GeoAgent apiUrl.
 */

// Module-level cache: the fetch+index runs once per page load. Holds the
// in-flight promise so concurrent first-clicks share a single round-trip.
let _indexPromise = null

// Echelon sort rank for sibling ordering (higher formations first). Mirrors
// the backend's ECHELON_ORDINAL (equipment_doctrine.py) — the OOB carries
// short codes ("BN", "CO"), so sidc.js's full-name/keyword maps don't fit.
// Unknown echelons rank 0 → sort last (display concern only).
const ECHELON_RANK = {
  CORPS: 7,
  DIV: 6, DIVISION: 6,
  BDE: 5, BRIGADE: 5, REGT: 5, REGIMENT: 5,
  BN: 4, BATTALION: 4, SQUADRON: 4,
  CO: 3, COY: 3, COMPANY: 3, TROOP: 3, BTRY: 3, BATTERY: 3,
  PLT: 2, PLATOON: 2,
  SEC: 1, SECTION: 1, SQUAD: 1,
}

function _echRank(echelon) {
  return ECHELON_RANK[String(echelon || '').trim().toUpperCase()] ?? 0
}

function _normName(name) {
  return String(name || '').trim().toUpperCase()
}

/** All normalized keys a unit can be referenced by (in parent_unit strings). */
function _aliasesOf(unit) {
  const out = []
  for (const v of [unit?.name, unit?.honorific_name, unit?.unit_designator]) {
    const k = _normName(v)
    if (k && !out.includes(k)) out.push(k)
  }
  return out
}

async function _buildIndex() {
  const byKgId = new Map()
  const byName = new Map()
  const byAlias = new Map()
  const childrenByParent = new Map()
  let snapshotTsMs = null
  try {
    const res = await fetch('/api/oob/resolved_latest')
    if (res.ok) {
      const data = await res.json()
      snapshotTsMs = data?.snapshot_ts_ms ?? null
      const units = data?.units || []
      for (const u of units) {
        if (!u) continue
        if (u.kg_id) byKgId.set(String(u.kg_id), u)
        if (u.name) {
          const k = _normName(u.name)
          byName.set(k, u)
          byAlias.set(k, u)
        }
      }
      // Second pass: secondary aliases (so a designator collision never
      // shadows a real unit name) for lookupUnitByAlias, and the subordinate
      // index keyed on the parent's kg_id (the structured tree join key).
      for (const u of units) {
        if (!u) continue
        for (const k of _aliasesOf(u)) {
          if (!byAlias.has(k)) byAlias.set(k, u)
        }
        const pk = u.parent_kg_id ? String(u.parent_kg_id) : null
        if (pk) {
          if (!childrenByParent.has(pk)) childrenByParent.set(pk, [])
          childrenByParent.get(pk).push(u)
        }
      }
    } else {
      console.warn(`[unitMetadata] /api/oob/resolved_latest → HTTP ${res.status}`)
    }
  } catch (e) {
    console.warn('[unitMetadata] fetch failed:', e)
  }
  return { byKgId, byName, byAlias, childrenByParent, snapshotTsMs }
}

/**
 * Lazily fetch + cache the resolved-OOB index (one round-trip per page load).
 * @returns {Promise<{byKgId: Map, byName: Map, byAlias: Map, childrenByParent: Map, snapshotTsMs: number|null}>}
 */
export function getUnitMetadataIndex() {
  if (!_indexPromise) _indexPromise = _buildIndex()
  return _indexPromise
}

/** Force a re-fetch (e.g. after a known fresh resolve / map refresh). */
export function refreshUnitMetadataIndex() {
  _indexPromise = _buildIndex()
  return _indexPromise
}

/**
 * Resolve a clicked unit's fused record by kg_id (preferred) then name.
 * @param {{kgId?: string, name?: string}} keys
 * @returns {Promise<object|null>} the named_unit record, or null if unknown
 */
export async function lookupUnitMetadata({ kgId, name } = {}) {
  const { byKgId, byName } = await getUnitMetadataIndex()
  if (kgId && byKgId.has(String(kgId))) return byKgId.get(String(kgId))
  if (name) {
    const k = _normName(name)
    if (byName.has(k)) return byName.get(k)
  }
  return null
}

/**
 * Resolve a unit record from any of its reference aliases (name, honorific
 * name, unit designator) — i.e. the strings parent_unit fields carry.
 * @returns {Promise<object|null>}
 */
export async function lookupUnitByAlias(name) {
  const { byAlias } = await getUnitMetadataIndex()
  return byAlias.get(_normName(name)) || null
}

// Direct children of the unit with this kg_id, sorted echelon-rank desc then
// name asc. Each unit has exactly one parent_kg_id, so the per-parent list is
// already duplicate-free.
function _childrenOf(index, kgId) {
  if (!kgId) return []
  const kids = index.childrenByParent.get(String(kgId)) || []
  return [...kids].sort(
    (a, b) =>
      _echRank(b.echelon) - _echRank(a.echelon) ||
      _normName(a.name).localeCompare(_normName(b.name))
  )
}

/**
 * Direct subordinates of a unit (children whose parent_kg_id == unit.kg_id).
 * @param {object|null} unit fused record (null / props-only pins have no kg_id
 *   and therefore no subordinates)
 * @returns {Promise<object[]>}
 */
export async function getSubordinateUnits(unit) {
  const index = await getUnitMetadataIndex()
  return _childrenOf(index, unit?.kg_id)
}

// Belt-and-braces recursion cap — the cycle guard below is the real
// protection; real OOBs are ≤6 echelons deep.
const _TREE_MAX_DEPTH = 8

/**
 * Full nested subordinate tree of a unit, joined on kg_id, with cycle
 * protection.
 * @param {object|null} unit fused record (null / props-only pins have no
 *   kg_id and therefore no subtree)
 * @returns {Promise<Array<{unit: object, key: string, children: Array}>>}
 *   top level = direct children of the given unit
 */
export async function getSubordinateTree(unit) {
  const index = await getUnitMetadataIndex()
  const rootKg = unit?.kg_id ? String(unit.kg_id) : null
  if (!rootKg) return []

  // One shared visited set (kg_ids) across the whole tree: each unit appears
  // at most once, which kills cycles (A→B→A) and diamond joins.
  const visited = new Set([rootKg])

  const build = (kgId, depth) => {
    if (depth > _TREE_MAX_DEPTH) return []
    const nodes = []
    for (const child of _childrenOf(index, kgId)) {
      const key = child.kg_id ? String(child.kg_id) : null
      if (!key || visited.has(key)) continue
      visited.add(key)
      nodes.push({ unit: child, key, children: build(key, depth + 1) })
    }
    return nodes
  }
  return build(rootKg, 0)
}
