/**
 * featureVisibility — THE visibility model for map features.
 *
 * Two orthogonal axes, and only two:
 *
 * 1. LAYERS (`enabledLayers`: Set of source tokens). A layer is a
 *    product push — a claim-set of geometry from one product run
 *    (SITEMP:<coa_id>, "Threat Overlay", "Event Template", …). The
 *    source token names WHICH HYPOTHESIS a feature belongs to, and
 *    toggling a layer swaps hypotheses. Base-map content (the live
 *    order-of-battle feed, analyst-placed/drawn features, the
 *    scenario/OPORD baseline) is NOT a layer: it always passes the
 *    layer gate. Provenance (`attrs.source` = 'manual' etc.) on base
 *    content is audit metadata, never a view axis — an analyst-drawn
 *    phase line behaves exactly like a pushed one everywhere.
 *
 * 2. TYPES (`hiddenTypes`: Set of type tokens). Source-agnostic ON
 *    PURPOSE: unchecking "Phase lines" hides phase lines no matter
 *    which pipe produced them (2026-07-13 direction). Token grammar —
 *    build tokens ONLY through the helpers below so emitters (the
 *    Tactical Overlays panel) and the matcher (featureVisible) can
 *    never drift:
 *      kind:<kind>                 hide a kind everywhere
 *      subkind:<subkind>           hide a range-fan class everywhere
 *      affiliation:<aff>           hide a whole faction
 *      <aff>:<dim>:<value>         faction-scoped dimension, e.g.
 *                                  Hostile:category:fire_support
 *    Matching is case-insensitive (feature props carry mixed case:
 *    Brigade / Battalion from the SIDC→echelon map).
 *
 * Consumers with no toggle UI (per-product render maps, headless
 * screenshots, DocEditor embeds) run with enabledLayers = null and an
 * empty hiddenTypes — every feature passes, same contract as before.
 */

// Base-map sources — always visible at the layer level. Everything
// else in `attrs.source` is a product-layer token. entity_graph is
// the record (graph_nodes) — the unit source post-cutover.
// reference_walk is the record's DOCTRINE projection (templated
// subordinates derived at paint) — base content with its own Units
// toggle, never a product layer: classing it as a product hid every
// derived subordinate behind an unchecked raw-token chip.
export const BASE_SOURCES = ['live_oob', 'manual', 'scenario_terrain', 'opord', 'entity_graph', 'reference_walk']
const BASE_SOURCE_SET = new Set(BASE_SOURCES)

// Units the analyst placed by hand may carry no category property.
// They still must be reachable by exactly one category chip — a
// feature no token can match is a feature no checkbox can hide.
export const UNCATEGORIZED = 'uncategorized'

export function kindToken(kind) {
  return `kind:${kind}`
}

export function typeToken(dim, value) {
  return `${dim}:${value}`
}

export function factionToken(affiliation) {
  return `affiliation:${affiliation}`
}

export function factionDimToken(affiliation, dim, value) {
  return `${affiliation}:${dim}:${value}`
}

// ── Category from the symbol itself. The SIDC codes the branch, so a
// unit placed without a category property is still classifiable.
//
// 2525E numeric (version 13; 2525D-compatible): Land Unit entity
// groups by the first two digits of the entity code (chars 10-15 of
// the SIDC): 11 Command and Control, 12 Movement and Maneuver,
// 13 Fires, 14 Protection, 15 Intelligence, 16 Sustainment — with
// overrides where the FM 3-60 category is finer than the group.
// Verified against backend/app/data/milstd/2525E 10 land-unit.json.
const SIDC_ENTITY_OVERRIDES = {
  1206: 'lift',                                 // Army Aviation / rotary
  1207: 'lift',                                 // Aviation Composite
  1208: 'lift',                                 // Aviation Fixed Wing
  1213: 'reconnaissance_and_surveillance',      // Recon / Cavalry / Scout
  1301: 'air_defense_artillery',
  1401: 'chemical_biological_radiological_nuclear',
  1407: 'engineer',
  1505: 'cyberspace_electromagnetic_activities', // Electronic Warfare
}
const SIDC_GROUP_CATEGORY = {
  11: 'command_and_control',
  12: 'maneuver',
  13: 'fire_support',
  15: 'reconnaissance_and_surveillance',        // Intelligence group
  16: 'sustainment',
  // 14 Protection deliberately unmapped beyond its overrides — MP and
  // the rest have no single FM 3-60 bucket.
}
// ONE symbol format: 2525E numeric. The backend normalizes every
// ingest path (sync/create/update) and the DB was migrated
// (backend/scripts/migrate_sidcs_to_2525e.py) — letter SIDCs cannot
// reach this code.
export function categoryFromSidc(sidc) {
  if (!sidc) return null
  const s = String(sidc).trim()
  if (!/^\d{20}/.test(s)) return null
  if (s.slice(4, 6) !== '10') return null       // land units only
  const entity = s.slice(10, 16)
  return SIDC_ENTITY_OVERRIDES[entity.slice(0, 4)]
    || SIDC_GROUP_CATEGORY[entity.slice(0, 2)]
    || null
}

/** Effective category of a feature for filtering and census alike. */
export function categoryOf(props) {
  if (props.category) return props.category
  if (props.kind !== 'mil_unit') return null
  return categoryFromSidc(props.sidc) || UNCATEGORIZED
}

// ── Unit designation labels, per faction. These tokens ride
// hiddenTypes (so they persist in visibility collections) but hide
// only the LABEL, never the feature — featureVisible does not read
// the unit_names dimension.
export function unitNamesToken(affiliation) {
  return `unit_names:${affiliation}`
}

/** Lowercased faction set whose designation labels are hidden. */
export function hiddenUnitNameFactions(hiddenTypes) {
  const out = new Set()
  if (!hiddenTypes) return out
  for (const token of hiddenTypes) {
    const t = String(token).toLowerCase()
    if (t.startsWith('unit_names:')) out.add(t.slice('unit_names:'.length))
  }
  return out
}

/**
 * Range fans carry no affiliation of their own — resolve a feature's
 * effective faction through its bearer unit. Build the index once per
 * load from the UNFILTERED entity stream.
 */
export function buildBearerAffiliationIndex(entityFeatures) {
  const index = new Map()
  for (const f of (entityFeatures || [])) {
    const p = (f && f.properties) || {}
    if (p.kind !== 'mil_unit' || !p.affiliation) continue
    for (const id of [p.source_kbid, p.kg_id, p.id]) {
      if (id) index.set(String(id), p.affiliation)
    }
  }
  return index
}

export function effectiveAffiliation(props, affiliationByUnitId) {
  return props.affiliation
    || (props.bearer_unit_kg_id && affiliationByUnitId
        ? affiliationByUnitId.get(String(props.bearer_unit_kg_id))
        : null)
    || null
}

// Lowercased mirror of a token Set, cached on the Set instance so the
// per-feature check stays O(1) across a load pass.
function lowerSet(tokens) {
  if (!tokens.__lowerCache) {
    tokens.__lowerCache = new Set(
      Array.from(tokens).map((t) => String(t).toLowerCase()))
  }
  return tokens.__lowerCache
}

/**
 * The ONE visibility predicate. Layer gate, then the selected-unit
 * range-fan override, then type tokens.
 *
 * @param {Object} props   feature.properties
 * @param {Object} opts
 * @param {Set|null} opts.enabledLayers        null = no layer gate
 * @param {Set}      opts.hiddenTypes          global type tokens
 * @param {Map}      opts.affiliationByUnitId  bearer faction index
 * @param {string}   opts.selectedBearerKgId   COP unit selection
 */
export function featureVisible(props, opts) {
  const {
    enabledLayers = null,
    hiddenTypes = null,
    affiliationByUnitId = null,
    selectedBearerKgId = null,
  } = opts || {}
  const p = props || {}
  // Untagged features are analyst-authored: every pipeline producer
  // tags its rows (the sync endpoint enforces attrs.source), so
  // anything untagged predates the source stamps and is base content.
  const src = p.source || 'manual'

  // ── Layer gate — product layers only; base content always passes.
  if (enabledLayers && !BASE_SOURCE_SET.has(src)) {
    let layerOn = enabledLayers.has(src)
    const coa = (p.coa_id || p.threat_branch || '').toString()
    if (!layerOn && coa && enabledLayers.has(`${src}:${coa}`)) layerOn = true
    if (!layerOn) return false
  }

  // ── Click-to-show-range-fans override: with a unit selected on the
  // COP, that unit's fans/detection rings always show and every other
  // unit's hide (all-fans-on would bury the selected unit's envelope
  // in noise). Graph-emitted rings carry bearer_unit_kg_id = the node
  // uuid; bearer_id is the legacy fallback key.
  if (p.kind === 'range_fan' || p.kind === 'detection_ring') {
    // Rings are SELECTION chrome, never ambient paint: with no unit
    // selected NO rings show; with one selected only ITS envelopes
    // show (all-fans-on buries the map in circles — user ruling
    // 2026-07-20).
    if (!selectedBearerKgId) return false
    return ((p.bearer_unit_kg_id || p.bearer_id || '').toString()
            === selectedBearerKgId)
  }

  // ── Type tokens — source-agnostic, case-insensitive.
  if (hiddenTypes && hiddenTypes.size > 0) {
    const aff = effectiveAffiliation(p, affiliationByUnitId)
    const lower = lowerSet(hiddenTypes)
    const dims = [
      ['kind', p.kind],
      ['subkind', p.subkind],
      ['echelon', p.echelon],
      ['category', categoryOf(p)],
      ['affiliation', aff],
      // source as a TYPE dimension: the Units-group "Doctrinal
      // subordinates" chip hides the reference walk's derived units via
      // source:reference_walk without demoting them to a product layer.
      ['source', p.source],
    ]
    for (const [dim, val] of dims) {
      if (val == null || val === '') continue
      if (lower.has(`${dim}:${val}`.toLowerCase())) return false
      if (aff && lower.has(`${aff}:${dim}:${val}`.toLowerCase())) return false
    }
  }
  return true
}

/**
 * One pass over the raw (unfiltered) map state → everything the
 * Tactical Overlays panel needs to render ONLY what exists. A chip
 * with nothing behind it is a lie to the analyst.
 *
 * Returns:
 *   layers:        Map<sourceToken, count>   (incl. <src>:<coa> compounds)
 *   kinds:         Map<kind, count>          (global)
 *   kindsBySource: Map<source, Map<kind, count>>
 *   factions:      Map<aff, { units, categories: Map<value,count>,
 *                             subkinds: Map<value,count> }>
 */
export function buildOverlayCensus(features, affiliationByUnitId) {
  const layers = new Map()
  const kinds = new Map()
  const kindsBySource = new Map()
  const factions = new Map()
  const bump = (map, key) => map.set(key, (map.get(key) || 0) + 1)
  const faction = (aff) => {
    if (!factions.has(aff)) {
      factions.set(aff, { units: 0, categories: new Map(), subkinds: new Map() })
    }
    return factions.get(aff)
  }
  for (const f of (features || [])) {
    const p = (f && f.properties) || {}
    const src = p.source || 'manual'
    bump(layers, src)
    const coa = (p.coa_id || p.threat_branch || '').toString()
    if (coa) bump(layers, `${src}:${coa}`)
    if (p.kind) {
      bump(kinds, p.kind)
      if (!kindsBySource.has(src)) kindsBySource.set(src, new Map())
      bump(kindsBySource.get(src), p.kind)
    }
    const aff = effectiveAffiliation(p, affiliationByUnitId)
    if (p.kind === 'mil_unit' && p.affiliation) {
      const bucket = faction(p.affiliation)
      bucket.units += 1
      bump(bucket.categories, categoryOf(p))
    }
    if (p.kind === 'range_fan' && aff && p.subkind) {
      bump(faction(aff).subkinds, p.subkind)
    }
  }
  return { layers, kinds, kindsBySource, factions }
}
