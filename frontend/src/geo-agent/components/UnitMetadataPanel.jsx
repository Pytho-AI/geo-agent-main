import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useGeoAgent } from '../GeoAgentProvider'
import { latLngToMGRS } from '../utils/mgrsGrid'
import { AFFILIATION_POPUP_COLORS } from '../utils/mapStyles'
import { lookupUnitByAlias, lookupUnitMetadata } from '../utils/unitMetadata'
import { showGenerateTidatMenu, GENERATE_MENU_ID } from '../utils/generateMenu'
import { UnitCompositionTree } from './UnitCompositionTree'
import { graphApi } from '../utils/graphApi'
import { createMilSymbol } from '../utils/symbols'
import { echelonRank } from '../utils/tacticalGraphics.svg'

// Echelon → the slider stop that keeps a unit of that echelon painted
// (TacticalOverlaysPanel ROLLUP_STOPS values). Click-to-locate lowers
// the faction's roll-up tier to the target's stop so the camera lands
// on a symbol that is actually visible.
const _ECHELON_STOP = (echelon) => {
  const r = echelonRank(echelon)
  if (r < 0) return null
  if (r <= 3) return 'PLT'
  if (r === 4) return 'CO'
  if (r === 5) return 'BN'
  if (r <= 7) return 'BDE'
  return 'DIV'
}

// Staleness of an observation against the SCENARIO clock (the latest
// dated observation / scrub time — not wall clock; an exercise set in
// APR 26 is not "3 months old"). Returns e.g. "4 days ago".
const _MONTHS = { JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5,
                  JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11 }
function stalenessLabel(observedIso, dtgLabel, refMs) {
  let t = observedIso ? Date.parse(observedIso) : NaN
  if (!isFinite(t) && dtgLabel) {
    const m = /^(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{2,4})$/
      .exec(String(dtgLabel).trim())
    if (m && _MONTHS[m[2].toUpperCase()] != null) {
      const y = Number(m[3]) < 100 ? 2000 + Number(m[3]) : Number(m[3])
      t = Date.UTC(y, _MONTHS[m[2].toUpperCase()], Number(m[1]))
    }
  }
  if (!isFinite(t) || !isFinite(refMs)) return null
  const d = refMs - t
  if (d < 0) return null
  const hours = Math.round(d / 3600000)
  if (hours < 1) return 'current'
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

// Small inline SIDC glyph for placard ORBAT rows.
function SidcGlyph({ sidc }) {
  const html = React.useMemo(() => {
    if (!sidc) return null
    try {
      const sym = createMilSymbol(sidc, { size: 16 })
      return sym && sym.svg ? sym.svg : null
    } catch {
      return null
    }
  }, [sidc])
  if (!html) return null
  return (
    <span
      className="unit-meta-sidc-glyph"
      style={{ display: 'inline-flex', width: 26, justifyContent: 'center',
               alignItems: 'center', flexShrink: 0 }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

/**
 * UnitMetadataPanel — live operations-map left-click inspector.
 *
 * Shows the fused metadata for a clicked mil_unit: location (MGRS), linked
 * equipment (composition_rollup), unit composition (subordinate-unit tree),
 * and last known activity (current_activity / disposition + DOI). The data
 * comes from the resolved RED OOB snapshot via lookupUnitMetadata
 * (utils/unitMetadata.js); the clicked map feature's own props/coords are
 * used as fallbacks so the panel still shows name + MGRS + affiliation even
 * when a unit has no fused record (e.g. sub-position or
 * unidentified-formation pins).
 *
 * Clicking a unit in the composition tree (or the Parent unit row) drills
 * the panel into that unit. The ⌖ buttons open the same per-target
 * generation menu as the map right-click gesture (utils/generateMenu.js) —
 * gated to units that exist as map entities, because the generate backend
 * resolves target_entity_id against the geo-agent entity store.
 *
 * Mounted only on the live (read-only) ops map — edit mode keeps EntityPanel.
 * Dismissible via the × button, Escape, or an outside click.
 */
export function UnitMetadataPanel() {
  const {
    selectedUnitMeta, setSelectedUnitMeta, userId, addActivity, mapRef,
    shellGraphViewerUrl, setRollupEchelonByFaction,
    timelineAsOf, trackExtent,
  } = useGeoAgent()
  const navigate = useNavigate()
  const panelRef = useRef(null)
  const [parentRec, setParentRec] = useState(null)
  const [copiedKey, setCopiedKey] = useState(null)

  // Map-highlight helpers (repaint via the ring-highlight event).
  const _fireHl = () => {
    const map = mapRef?.current
    if (!map) return
    try { map.fire('pytho:ring-highlight') } catch { /* torn down */ }
  }
  const hoverRing = (payload) => {
    const map = mapRef?.current
    if (!map) return
    map.__ringHighlight = payload
    _fireHl()
  }
  const hoverUnit = (payload) => {
    const map = mapRef?.current
    if (!map) return
    map.__unitHighlight = payload
    // Re-derive the roll-up with the hover exemption so a rolled-up
    // subordinate APPEARS at its own position while pointed at.
    map.__rerenderMilUnits?.()
    _fireHl()
  }
  const copyValue = (key, value) => {
    try { navigator.clipboard.writeText(String(value)) } catch { /* insecure ctx */ }
    setCopiedKey(key)
    setTimeout(() => setCopiedKey(null), 900)
  }
  // Graph card: unit + organic parent + children (SIDCs, positions) +
  // subtree equipment rollup, one fetch per placard open. Only for
  // entity_graph features — legacy rows keep the fused-OOB path.
  const [graphCard, setGraphCard] = useState(null)
  // Posture override selector (parent formations only): the list comes
  // from the disposition engine (GET /graph/postures); the selection is
  // a WORKING-LAYER visual override (posture_override display field) —
  // the painted brood reshapes, the record never changes.
  const [postureList, setPostureList] = useState([])
  const [postureSel, setPostureSel] = useState('')
  const [postureBusy, setPostureBusy] = useState(false)
  // As-of brief (world-model read): attribute History chains, reporting
  // statements with Sources, Doctrine for the unit's template, resolved
  // at the scrub time on the selected temporal axis.
  const [unitBrief, setUnitBrief] = useState(null)
  const { timelineAsOf: briefAsOf } = useGeoAgent()

  const close = () => {
    // Never leave a hover highlight behind after the panel goes away.
    hoverRing(null)
    hoverUnit(null)
    setSelectedUnitMeta(null)
  }

  // The SELECTED unit is exempt from every visibility gate while its
  // placard is open — roll-up tiers and legend toggles never hide the
  // unit the analyst is looking at — and it paints at the TOP of the
  // symbol stack with the selection ring. Stash on the map instance
  // (same channel as the hover exemption); cleared when the placard
  // changes or closes.
  const selectedEntityId = selectedUnitMeta?.props?.id
    ?? selectedUnitMeta?.feature?.id ?? null
  useEffect(() => {
    const map = mapRef?.current
    if (!map || selectedEntityId == null) return undefined
    map.__unitSelected = { id: selectedEntityId }
    map.__rerenderMilUnits?.()
    _fireHl()
    return () => {
      if (map.__unitSelected?.id === selectedEntityId) {
        map.__unitSelected = null
        map.__rerenderMilUnits?.()
        _fireHl()
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEntityId])

  // Visibility LOCK — the placard's pin: a locked unit stays on the
  // map through visibility toggles and roll-up even after the placard
  // closes (unlock by toggling again). Lives on the map instance so it
  // survives placard unmounts for the session.
  const [visLocked, setVisLocked] = useState(false)
  useEffect(() => {
    const locks = mapRef?.current?.__unitVisibilityLocks
    setVisLocked(Boolean(
      selectedEntityId != null && locks?.has(String(selectedEntityId))))
  }, [selectedEntityId, mapRef])
  const toggleVisLock = () => {
    const map = mapRef?.current
    if (!map || selectedEntityId == null) return
    if (!map.__unitVisibilityLocks) map.__unitVisibilityLocks = new Set()
    const key = String(selectedEntityId)
    const locks = map.__unitVisibilityLocks
    if (locks.has(key)) locks.delete(key)
    else locks.add(key)
    setVisLocked(locks.has(key))
    map.__rerenderMilUnits?.()
    _fireHl()
  }

  useEffect(() => {
    let cancelled = false
    setGraphCard(null)
    const p = selectedUnitMeta?.props || {}
    const nodeId = p.source === 'entity_graph' ? (p.id || null) : null
    if (!nodeId) return undefined
    graphApi.card(nodeId)
      .then((card) => { if (!cancelled) setGraphCard(card) })
      .catch(() => { /* placard keeps the feature-only view */ })
    return () => { cancelled = true }
  }, [selectedUnitMeta])

  // Engine posture list, fetched once per session; selector reflects
  // the card's stored posture whenever the card (re)loads.
  useEffect(() => {
    let cancelled = false
    graphApi.postures()
      .then((r) => { if (!cancelled) setPostureList(r?.postures || []) })
      .catch(() => { /* selector simply doesn't render */ })
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    setPostureSel(graphCard?.unit?.posture_override || '')
  }, [graphCard])

  // WORKING-LAYER VISUAL OVERRIDE (2026-07-28 ruling): the selector
  // writes the posture_override display field — never the record and
  // never the node's posture column. An unsourced analyst flip is not
  // a record write; the record posture stays what the record states,
  // and clearing the override returns the paint to the record view.
  const applyPosture = async (value) => {
    const p = selectedUnitMeta?.props || {}
    const nodeId = p.source === 'entity_graph' ? (p.id || null) : null
    if (!nodeId || postureBusy) return
    setPostureSel(value)
    setPostureBusy(true)
    try {
      if (value) {
        await graphApi.putNodeField(nodeId, 'posture_override', value, userId)
        addActivity?.(`Posture visual override set to ${value} `
          + '(working layer - the record is unchanged)')
      } else {
        await graphApi.deleteNodeField(nodeId, 'posture_override')
        addActivity?.('Posture visual override cleared - record view')
      }
      // Fresh card so the placard reflects the override state; the map
      // itself repaints off the backend's graph_updated broadcast.
      graphApi.card(nodeId)
        .then((card) => setGraphCard(card))
        .catch(() => { /* keep the current card */ })
    } catch (err) {
      addActivity?.(`Posture override failed: ${err?.message || err}`)
      setPostureSel(graphCard?.unit?.posture_override || '')
    } finally {
      setPostureBusy(false)
    }
  }

  // Brief re-resolves whenever the placard opens, the scrub moves, or
  // the temporal axis flips — the placard always shows the state AT the
  // time the analyst is looking at.
  useEffect(() => {
    let cancelled = false
    setUnitBrief(null)
    const p = selectedUnitMeta?.props || {}
    const nodeId = p.source === 'entity_graph' ? (p.id || null) : null
    if (!nodeId) return undefined
    graphApi.brief(nodeId, briefAsOf || null)
      .then((b) => { if (!cancelled) setUnitBrief(b) })
      .catch(() => { /* sections simply don't render */ })
    return () => { cancelled = true }
  }, [selectedUnitMeta, briefAsOf])

  // Fly the camera to an ORBAT row's unit, first lowering the faction's
  // echelon roll-up tier so the target is actually painted when the
  // camera lands (a battalion under a rolled-up brigade is invisible
  // until the tier drops to BN or finer).
  const locateUnit = (rec, affiliationForTier) => {
    if (rec.lon == null || rec.lat == null) {
      // Unplaced (or position unknown to this card): still drill the
      // placard into the unit — its own card carries what IS known.
      setSelectedUnitMeta({
        unit: null,
        props: {
          id: rec.id, source: 'entity_graph', name: rec.name,
          echelon: rec.echelon, affiliation: rec.affiliation,
          sidc: rec.sidc,
        },
        coords: null,
      })
      return
    }
    const stop = _ECHELON_STOP(rec.echelon)
    if (stop && affiliationForTier && setRollupEchelonByFaction) {
      setRollupEchelonByFaction((prev) => {
        const cur = prev?.[affiliationForTier]
        if (cur && echelonRank(cur) <= echelonRank(stop)) return prev
        return { ...prev, [affiliationForTier]: stop }
      })
    }
    const map = mapRef?.current
    if (map) {
      map.flyTo({
        center: [rec.lon, rec.lat],
        zoom: Math.max(map.getZoom(), 9),
      })
    }
    // Drill the placard into the located unit.
    setSelectedUnitMeta({
      unit: null,
      props: {
        id: rec.id, source: 'entity_graph', name: rec.name,
        echelon: rec.echelon, affiliation: rec.affiliation,
        sidc: rec.sidc,
      },
      coords: [rec.lon, rec.lat],
    })
  }

  // Esc + outside-CLICK dismissal — listeners live only while the panel
  // is open. A camera gesture must NEVER dismiss: closing on mousedown
  // killed the panel the instant the analyst pressed to pan or
  // right-drag rotate. So the mousedown (capture, ahead of MapLibre's
  // canvas handlers) only ARMS the dismissal with the press position
  // and button; the matching mouseup dismisses only when the pointer
  // stayed put (a true click, not a drag) and it was the left button.
  // Clicks in the floating generation menu (mounted on document.body,
  // outside the panel) must not dismiss — picking a product would
  // otherwise close the panel out from under the analyst.
  useEffect(() => {
    if (!selectedUnitMeta) return
    const onKey = (e) => { if (e.key === 'Escape') close() }
    let armed = null
    const onDown = (e) => {
      armed = null
      if (e.button !== 0) return
      const genMenu = document.getElementById(GENERATE_MENU_ID)
      if (genMenu && genMenu.contains(e.target)) return
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        armed = { x: e.clientX, y: e.clientY }
      }
    }
    const onUp = (e) => {
      if (!armed) return
      const moved = Math.hypot(e.clientX - armed.x, e.clientY - armed.y)
      armed = null
      if (moved < 5) close()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown, true)
    document.addEventListener('mouseup', onUp, true)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown, true)
      document.removeEventListener('mouseup', onUp, true)
    }
  }, [selectedUnitMeta]) // eslint-disable-line react-hooks/exhaustive-deps

  // Resolve the unit's parent to its fused record so the Parent unit row can
  // navigate up. Live IDX-26 carries the link as parent_kg_id (resolved from
  // the OOB feed — the same join the subordinate tree uses);
  // the parent_unit string is null there, so join by kg_id first and only
  // fall back to the name/alias string for scenario data. Plain text /
  // hidden when nothing resolves.
  useEffect(() => {
    let cancelled = false
    setParentRec(null)
    if (!selectedUnitMeta) return undefined
    const { unit: u0, props: p0 = {} } = selectedUnitMeta
    const pkg = u0 && u0.parent_kg_id
    const pn = (u0 && u0.parent_unit) || p0.parent || ''
    const lookup = pkg
      ? lookupUnitMetadata({ kgId: pkg })
      : (pn ? lookupUnitByAlias(pn) : null)
    if (lookup) {
      lookup.then((r) => { if (!cancelled) setParentRec(r) })
    }
    return () => { cancelled = true }
  }, [selectedUnitMeta])

  if (!selectedUnitMeta) return null

  const { unit, props = {}, coords } = selectedUnitMeta
  const u = unit || {}

  const name = u.name || props.name || props.unique_designation || 'Unknown unit'
  const echelon = u.echelon || props.echelon || ''
  const affiliation = (props.affiliation || props.side || '').toString()
  const color =
    AFFILIATION_POPUP_COLORS[affiliation] ||
    AFFILIATION_POPUP_COLORS[affiliation.charAt(0).toUpperCase() + affiliation.slice(1).toLowerCase()] ||
    '#cbd5e1'

  // Location → MGRS. Prefer the fused primary_position; fall back to the
  // clicked symbol's own coordinates (GeoJSON [lng, lat], always present).
  const pos = u.primary_position || null
  let lat = pos?.lat
  let lon = pos?.lon
  if ((lat == null || lon == null) && Array.isArray(coords)) {
    lon = coords[0]
    lat = coords[1]
  }
  const hasLoc = lat != null && lon != null
  const mgrs = hasLoc ? latLngToMGRS(lat, lon, 4) : '—'
  const latLonStr = hasLoc ? `${Number(lat).toFixed(4)}°, ${Number(lon).toFixed(4)}°` : '—'

  // Position provenance — surfaces an INFERRED banner in the Location
  // section when the OOB feed didn't report this unit's coords directly. The
  // OOB resolver stamps position_source on every named_unit and threads
  // it down to entity attrs in pytho-app utils/oob.build_geo_agent_sync_payload.
  //   'raw'                       → the feed reported the position directly
  //   'attributed'                → HIGH-confidence cluster member position
  //   'children_avg'              → BDE centroid of its known subordinate BNs
  //   'frontage:<role>@<deg>'     → doctrinal-frontage offset along the
  //                                  threat avenue-of-approach tangent
  //                                  from the parent BDE's position
  // Anything other than 'raw' (or an unset / unknown value that the
  // backend hasn't stamped yet) renders as the INFERRED banner.
  const positionSource = (u.position_source || props.position_source || '').toString()
  // Graph-era provenance: every position observation carries its
  // source verbatim — the parsed document, the doctrinal-disposition
  // basis, an analyst drag. Derived (never-observed) positions carry
  // position_derived + position_basis instead. The legacy OOB-feed
  // tokens (raw / attributed / children_avg / frontage:<role>@<deg>)
  // keep their historical rendering.
  const isDerived = props.position_derived === true || props.position_derived === 'true'
  const derivedBasis = (props.position_basis || '').toString()
  const positionDtg = (props.position_dtg || u.position_dtg || '').toString()
  const positionObservedAt = (props.position_observed_at || '').toString()
  const legacyTokens = ['raw', 'attributed', 'children_avg']
  const isLegacyToken = legacyTokens.includes(positionSource)
    || positionSource.startsWith('frontage:')
  const isDoctrinal = /doctrinal/i.test(positionSource)
  const isInferred = isDerived || isDoctrinal
    || (isLegacyToken && positionSource !== 'raw')
  const inferredLabel = (() => {
    if (isDerived) return `Derived — ${derivedBasis || 'no stated position'}`
    if (positionSource.startsWith('frontage:')) {
      // 'frontage:maneuver@273deg' → 'Doctrinal frontage (maneuver, axis 273°)'
      const rest = positionSource.slice('frontage:'.length)
      const [role, axisRaw] = rest.split('@')
      const axis = (axisRaw || '').replace('deg', '°')
      return `Doctrinal frontage — ${role}${axis ? `, axis ${axis}` : ''} from parent`
    }
    if (positionSource === 'attributed') return 'Attributed from sensor-cluster fusion'
    if (positionSource === 'children_avg') return 'Inferred from subordinate-unit centroid'
    if (isDoctrinal) return positionSource
    return ''
  })()
  // A real provenance string (not a legacy token, not a derivation):
  // the document / input the position was parsed from. Shown as a
  // plain Source row — a stated position is a fact, not an inference.
  const parsedSource = (!isLegacyToken && !isDoctrinal && positionSource)
    ? positionSource : ''

  // Linked equipment from composition_rollup {name: count}, count-desc.
  // Three sources, in trust order: the graph card (fresh subtree
  // rollup), the fused OOB record (legacy feed), the feature's own
  // properties. MapLibre STRINGIFIES nested feature properties on
  // query — a clicked feature delivers composition_rollup as a JSON
  // string, which the old typeof-object gate silently rejected (the
  // "equipment missing from every placard" bug).
  let featureComp = props.composition_rollup
  if (typeof featureComp === 'string') {
    try { featureComp = JSON.parse(featureComp) } catch { featureComp = null }
  }
  const comp =
    (graphCard?.composition_rollup
      && typeof graphCard.composition_rollup === 'object'
      && graphCard.composition_rollup)
    || (u.composition_rollup && typeof u.composition_rollup === 'object' && u.composition_rollup)
    || (featureComp && typeof featureComp === 'object' && featureComp)
    || {}
  // Zero/unstated counts still LIST — the source names the system
  // without a strength ("R-330Zh present, count not stated"); dropping
  // it told the analyst the unit had no equipment at all.
  const equipment = Object.entries(comp)
    .sort((a, b) => (b[1] || 0) - (a[1] || 0) || a[0].localeCompare(b[0]))

  // Last known activity.
  const activity = u.current_activity || u.disposition || props.posture || ''
  const lastSeen = pos?.last_seen || u.last_seen || props.doi || ''

  // Extras — only rows that have a value. Parent unit renders as its own
  // (possibly clickable) row above these. Name comes from the resolved parent
  // record (live data: parent_unit string is null, so the name arrives via the
  // parent_kg_id lookup); falls back to the raw string for scenario data.
  // Graph features carry `parent` as the organic parent UUID (the
  // roll-up walk key) — never show a raw uuid; the graph card's Higher
  // headquarters section carries the real parent row.
  const _rawParent = parentRec?.name || u.parent_unit || props.parent || ''
  const parentName = (graphCard
      || /^[0-9a-f]{8}-[0-9a-f]{4}/i.test(String(_rawParent)))
    ? (parentRec?.name || u.parent_unit || '')
    : _rawParent
  const extras = [
    ['Strength', u.strength_pct || u.strength_pct_manned || props.personnel_status || ''],
    ['Rate of march', u.rate_of_march_kmh ? `${u.rate_of_march_kmh} km/h` : ''],
    ['HVT-worthy items', u.hvt_worthy_count ? String(u.hvt_worthy_count) : ''],
    [
      'Firing positions',
      Array.isArray(u.attributed_positions) && u.attributed_positions.length
        ? `${u.attributed_positions.length + 1} (1 primary + ${u.attributed_positions.length} attributed)`
        : '',
    ],
  ].filter(([, v]) => v !== '' && v != null)

  const isSub = props.is_sub_position === true || props.is_sub_position === 'true'
  const isUnidentified =
    props.is_unidentified_formation === true || props.is_unidentified_formation === 'true'

  // Real kbID to deep-link into the Graph Viewer ("View data source").
  // Named unit → its kg_id; sub-position pin → its bearer's kg_id. Synthetic
  // ids (sub-pin "<kbid>#subN", unidentified-formation "UFP-…") have no
  // standalone graph vertex, so the link hides for those.
  const rawKbid = u.kg_id || props.bearer_unit_kg_id || props.source_kbid || ''
  const dataSourceKbid =
    rawKbid && !String(rawKbid).includes('#') && !String(rawKbid).startsWith('UFP-')
      ? String(rawKbid)
      : ''

  // Drill the panel down into another fused record (composition tree /
  // Parent unit row). Fresh minimal props — spreading the current props
  // would leak the previous unit's name/parent/sub-position fallbacks into
  // the new view. Affiliation carries over (the resolved OOB is RED-only).
  const handleSelectUnit = (rec) => {
    const p = rec.primary_position
    setSelectedUnitMeta({
      unit: rec,
      props: { affiliation: affiliation || 'Hostile' },
      coords: p && p.lat != null && p.lon != null ? [p.lon, p.lat] : null,
    })
  }

  // kg_id → geo-agent entity id, via the full synced mil-unit feature list
  // (stashed by useMapInstance on every sync; NOT viewport-limited). The
  // generate backend resolves target_entity_id against the geo-agent entity
  // store, so subordinates that aren't painted on the map can't be targeted
  // — the affordance hides for those. Red/hostile gate mirrors the map
  // right-click handler.
  const resolveTargetEntityId = (rec) => {
    const kgId = rec?.kg_id
    if (!kgId) return null
    const map = mapRef?.current
    const feats = map?.__milUnitFeatures || []
    const f = feats.find((ft) => ft?.properties?.source_kbid === kgId)
    if (!f) return null
    const aff = String(f.properties?.affiliation || f.properties?.side || '').toLowerCase()
    if (aff !== 'red' && aff !== 'hostile') return null
    // The KG id itself IS the target binding: the per-target writer
    // resolves target_entity_id against the KG and the HPTL dispatch
    // gate validates it against HPTL row ids (KG ids). The painted
    // feature lookup above is only the "on the map + red" gate —
    // returning the feature's geo-agent row uuid here (the old
    // behavior) bound nothing server-side.
    return kgId
  }

  const openGenerateMenu = (rec, entityId, e) => {
    showGenerateTidatMenu({
      screenX: e.clientX,
      screenY: e.clientY,
      entityId,
      callsign: rec.name || String(entityId),
      userId,
      addActivity,
      navigate,
    })
  }

  // Generate affordance for the selected unit itself. The target id is
  // the KNOWLEDGE-GRAPH id (`source_kbid` on live_oob features) — the
  // per-target writer + HPTL dispatch gate resolve against KG ids, not
  // geo-agent entity row uuids. NO row-uuid fallback: a geo-agent uuid
  // fails both server-side bindings, so the affordance on a feature
  // without KG lineage (e.g. an analyst-placed hostile unit) was a
  // dead button. Drill-down units resolve through the synced feature
  // list like tree rows do.
  const selfIsRed = ['red', 'hostile'].includes(affiliation.toLowerCase())
  const selfTargetId =
    (selfIsRed && !isSub && !isUnidentified && props.source_kbid) ||
    (unit ? resolveTargetEntityId(unit) : null)

  return (
    <div className="unit-meta-panel" ref={panelRef}>
      <div className="unit-meta-header" style={{ borderLeft: `4px solid ${color}` }}>
        <div className="unit-meta-title">
          <div className="unit-meta-name">{name}</div>
          <div className="unit-meta-sub">
            {[echelon, affiliation].filter(Boolean).join(' · ') || 'Mil unit'}
          </div>
        </div>
        <button
          className="unit-meta-gen"
          title={visLocked
            ? 'Visibility locked - this unit stays on the map through '
              + 'every visibility toggle and roll-up. Click to unlock.'
            : 'Lock visibility - keep this unit on the map through '
              + 'visibility toggles and roll-up'}
          aria-label={visLocked ? 'Unlock visibility' : 'Lock visibility'}
          aria-pressed={visLocked}
          onClick={toggleVisLock}
          style={visLocked ? { color: '#f59e0b' } : undefined}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2.4"
               strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="11" width="16" height="10" rx="2"
                  fill={visLocked ? 'currentColor' : 'none'} />
            {visLocked
              ? <path d="M8 11 V7 a4 4 0 0 1 8 0 v4" />
              : <path d="M8 11 V7 a4 4 0 0 1 8 0" />}
          </svg>
        </button>
        {Array.isArray(selectedUnitMeta?.coords) && (
          <button
            className="unit-meta-gen"
            title="Center map on unit"
            aria-label="Center map on unit"
            onClick={() => {
              const m = mapRef?.current
              const c = selectedUnitMeta.coords
              if (!m || !Number.isFinite(c[0]) || !Number.isFinite(c[1])) return
              m.easeTo({ center: [c[0], c[1]],
                         zoom: Math.max(m.getZoom(), 10), duration: 700 })
            }}
          >
            ◎
          </button>
        )}
        {selfTargetId && (
          <button
            className="unit-meta-gen"
            title={`Generate targeting products for ${name}`}
            onClick={(e) => openGenerateMenu(u.name ? u : { name }, selfTargetId, e)}
          >
            ⌖
          </button>
        )}
        <button className="unit-meta-close" onClick={close} aria-label="Close">×</button>
      </div>

      <div className="unit-meta-content">
        {(isSub || isUnidentified) && (
          <div className="unit-meta-flag">
            {isUnidentified ? 'Unidentified formation (PIR candidate)' : 'Attributed sub-position'}
          </div>
        )}

        <div className="unit-meta-section">
          <div className="unit-meta-section-label">
            Location
            {isInferred && (
              <span className="unit-meta-inferred-badge"> · INFERRED</span>
            )}
          </div>
          {isInferred && (
            <div className="unit-meta-inferred-note">{inferredLabel}</div>
          )}
          {/* MGRS | Lat/Lon side by side, click to copy. */}
          <div style={{ display: 'flex', gap: 6, margin: '4px 0' }}>
            {[['MGRS', mgrs], ['Lat / Lon', latLonStr]].map(([k, v]) => (
              <button
                key={k}
                className="unit-meta-coord"
                title={`Copy ${k}`}
                onClick={() => copyValue(k, v)}
                style={{ flex: 1, minWidth: 0, textAlign: 'left',
                         background: '#0f1b33', border: '1px solid #0f3460',
                         borderRadius: 6, padding: '4px 7px',
                         cursor: 'pointer', color: 'inherit' }}
              >
                <div style={{ fontSize: 9, textTransform: 'uppercase',
                              letterSpacing: 0.5, color: '#8b93a7' }}>
                  {copiedKey === k ? 'Copied' : k}
                </div>
                <div className="unit-meta-mono"
                     style={{ fontSize: 11, whiteSpace: 'nowrap',
                              overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {v}
                </div>
              </button>
            ))}
          </div>
          {parsedSource && (
            <div className="unit-meta-row">
              <span className="unit-meta-key">Source</span>
              <span className="unit-meta-val">{parsedSource}</span>
            </div>
          )}
          {(positionDtg || positionObservedAt) && (() => {
            // Staleness against the SCENARIO clock: the scrub time when
            // scrubbing, else the project's latest dated observation.
            const refMs = Date.parse(
              timelineAsOf || trackExtent?.max || '') || Date.now()
            const stale = stalenessLabel(
              positionObservedAt, positionDtg, refMs)
            return (
              <div className="unit-meta-row">
                <span className="unit-meta-key">As of</span>
                <span className="unit-meta-val"
                      title={positionDtg || positionObservedAt}>
                  {stale || positionDtg || positionObservedAt}
                </span>
              </div>
            )
          })()}
        </div>

        {/* Formation posture — the RECORD value plus the analyst's
            working-layer VISUAL override selector (2026-07-28 ruling):
            the override reshapes the painted brood but never writes
            the record; clearing it returns to the record view. */}
        {props.source === 'entity_graph'
          && graphCard?.children?.length > 0 && postureList.length > 0 && (
          <div className="unit-meta-section">
            <div className="unit-meta-section-label">
              Posture
              {graphCard?.unit?.posture
                ? ` — record: ${graphCard.unit.posture}`
                : ' — record: none stated'}
            </div>
            <select
              className="unit-meta-posture"
              title={postureBusy
                ? 'Applying the visual override'
                : 'Visual override (working layer) - reshapes the '
                  + 'painted formation; the record is unchanged'}
              aria-label="Posture visual override"
              value={postureSel}
              disabled={postureBusy}
              onChange={(e) => applyPosture(e.target.value)}
              style={{ background: '#0f1b33', color: '#cbd5e1',
                       border: '1px solid #0f3460', borderRadius: 6,
                       fontSize: 12, padding: '4px 7px', width: '100%',
                       cursor: postureBusy ? 'wait' : 'pointer' }}
            >
              <option value="">record view (no override)</option>
              {postureSel && !postureList.includes(postureSel) && (
                <option value={postureSel}>{postureSel}</option>
              )}
              {postureList.map((po) => (
                <option key={po} value={po}>
                  {po.charAt(0).toUpperCase() + po.slice(1)} (override)
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Equipment renders whenever ANY source carries holdings —
            the graph card, the fused OOB record (legacy feed), or the
            feature's own composition_rollup property. Only omitted
            entirely when no source exists ("None recorded" about a
            unit whose holdings simply weren't fetched would be a
            false claim). */}
        {(unit || graphCard || equipment.length > 0) && (
          <div className="unit-meta-section">
            <div className="unit-meta-section-label">
              {graphCard
                ? `Composition${graphCard.children?.length
                    ? ` (${graphCard.children.length} units)` : ''}`
                : `Linked equipment${equipment.length
                    ? ` (${equipment.length})` : ''}`}
            </div>
            {(() => {
              const equipRow = (item, bearerId) => (
                <li
                  key={`${bearerId || 'x'}-${item.name}`}
                  style={{ cursor: item.weg_id ? 'pointer' : 'default' }}
                  title={item.weg_id
                    ? `Open ${item.name} in the equipment catalog`
                    : item.name}
                  onMouseEnter={() => hoverRing(
                    { name: item.name, bearerId })}
                  onMouseLeave={() => hoverRing(null)}
                  onClick={() => {
                    if (!item.weg_id) return
                    window.dispatchEvent(new CustomEvent(
                      'geoagent:openCatalog',
                      { detail: { weg_id: item.weg_id } }))
                  }}
                >
                  <span className="unit-meta-equip-name">{item.name}</span>
                  <span className="unit-meta-equip-count">
                    {item.count ? `×${item.count}` : 'count not stated'}
                  </span>
                </li>
              )
              // ONE merged composition tree (user ruling: no separate
              // equipment + subordinate sections). Own equipment
              // first, then EVERY subordinate with its equipment
              // nested beneath it; deeper-descendant holders follow.
              // Hovering a unit row shows THAT unit on the map (roll-
              // up exemption); hovering an item lights THAT unit's
              // ring; clicking a unit locates it, an item opens its
              // catalog sheet.
              if (graphCard) {
                const byUnit = new Map(
                  (graphCard.composition_by_unit || [])
                    .map((g) => [g.unit_id, g]))
                const selfItems = [...byUnit.values()]
                  .find((g) => g.is_self)?.items || []
                const children = graphCard.children || []
                const childIds = new Set(children.map((c) => c.id))
                const deeper = [...byUnit.values()].filter(
                  (g) => !g.is_self && !childIds.has(g.unit_id))
                const unitRow = (rec, items) => (
                  <div key={rec.id} style={{ marginBottom: 4 }}>
                    <button
                      className="unit-meta-tree-name"
                      style={{ display: 'flex', alignItems: 'center',
                               gap: 5, width: '100%', textAlign: 'left' }}
                      title={rec.lon != null
                        ? `Locate ${rec.name}` : `${rec.name} (unplaced)`}
                      onMouseEnter={() => hoverUnit({ id: rec.id })}
                      onMouseLeave={() => hoverUnit(null)}
                      onClick={() => locateUnit(rec, rec.affiliation)}
                    >
                      <SidcGlyph sidc={rec.sidc} />
                      <span style={{ flex: 1, minWidth: 0 }}>{rec.name}</span>
                      {rec.echelon && (
                        <span style={{ opacity: 0.65, flexShrink: 0 }}>
                          {rec.echelon}
                        </span>
                      )}
                    </button>
                    {items.length > 0 && (
                      <ul className="unit-meta-equip"
                          style={{ marginLeft: 14 }}>
                        {items.map((it) => equipRow(it, rec.id))}
                      </ul>
                    )}
                  </div>
                )
                const any = selfItems.length || children.length
                  || deeper.length
                if (!any) {
                  return <div className="unit-meta-empty">None recorded</div>
                }
                return (
                  <>
                    {selfItems.length > 0 && (
                      <ul className="unit-meta-equip">
                        {selfItems.map((it) =>
                          equipRow(it, graphCard.unit?.id))}
                      </ul>
                    )}
                    {children.map((c) => unitRow(
                      c, byUnit.get(c.id)?.items || []))}
                    {deeper.map((g) => unitRow(
                      { id: g.unit_id, name: g.unit_name,
                        echelon: g.echelon, sidc: g.sidc,
                        affiliation, lon: null, lat: null },
                      g.items))}
                  </>
                )
              }
              if (equipment.length) {
                return (
                  <ul className="unit-meta-equip">
                    {equipment.map(([nm, count]) =>
                      equipRow({ weg_id: null, name: nm, count }, null))}
                  </ul>
                )
              }
              return <div className="unit-meta-empty">None recorded</div>
            })()}
          </div>
        )}

        {/* Graph ORBAT: organic parent + subordinates, each with its
            composed SIDC glyph; clicking a row lowers the faction's
            roll-up tier so the target paints, flies the camera to it,
            and drills the placard into it. */}
        {graphCard?.parent && (
          <div className="unit-meta-section">
            <div className="unit-meta-section-label">Higher headquarters</div>
            <button
              className="unit-meta-tree-name unit-meta-parent-link"
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              onClick={() => locateUnit(graphCard.parent, graphCard.parent.affiliation)}
              title={graphCard.parent.lon != null
                ? `Locate ${graphCard.parent.name}` : graphCard.parent.name}
            >
              <SidcGlyph sidc={graphCard.parent.sidc} />
              <span>{graphCard.parent.name}</span>
              {graphCard.parent.echelon && (
                <span style={{ opacity: 0.65 }}>· {graphCard.parent.echelon}</span>
              )}
            </button>
          </div>
        )}
        <UnitCompositionTree
          key={u.kg_id || name}
          unit={unit}
          onSelectUnit={handleSelectUnit}
          resolveTargetEntityId={resolveTargetEntityId}
          onGenerate={openGenerateMenu}
        />

        {unit && (
          <div className="unit-meta-section">
            <div className="unit-meta-section-label">Last known activity</div>
            <div className="unit-meta-activity">{activity || 'None recorded'}</div>
            {lastSeen && (
              <div className="unit-meta-row">
                <span className="unit-meta-key">Last seen (DOI)</span>
                <span className="unit-meta-val">{lastSeen}</span>
              </div>
            )}
          </div>
        )}

        {(parentName || extras.length > 0) && (
          <div className="unit-meta-section">
            {parentName && (
              <div className="unit-meta-row">
                <span className="unit-meta-key">Parent unit</span>
                {parentRec ? (
                  <button
                    className="unit-meta-tree-name unit-meta-parent-link"
                    onClick={() => handleSelectUnit(parentRec)}
                    title={`View ${parentName}`}
                  >
                    {parentName}
                  </button>
                ) : (
                  <span className="unit-meta-val">{parentName}</span>
                )}
              </div>
            )}
            {extras.map(([k, v]) => (
              <div className="unit-meta-row" key={k}>
                <span className="unit-meta-key">{k}</span>
                <span className="unit-meta-val">{v}</span>
              </div>
            ))}
          </div>
        )}

        {unitBrief?.as_of && (
          <div className="unit-meta-section" style={{ opacity: 0.85 }}>
            <div className="unit-meta-row">
              <span className="unit-meta-key">As of</span>
              <span className="unit-meta-val">
                {new Date(unitBrief.as_of).toUTCString().replace('GMT', 'Z')}
              </span>
            </div>
          </div>
        )}

        {unitBrief?.attributes?.length > 0 && (
          <div className="unit-meta-section">
            <div className="unit-meta-row">
              <span className="unit-meta-key">History</span>
            </div>
            {unitBrief.attributes.map((a) => (
              <div key={a.attribute} style={{ margin: '2px 0 6px' }}>
                <div className="unit-meta-row">
                  <span className="unit-meta-key" style={{ textTransform: 'capitalize' }}>{a.attribute}</span>
                  <span className="unit-meta-val">{a.current?.text}</span>
                </div>
                {a.history?.length > 1 && (
                  <details style={{ marginLeft: 8, fontSize: '0.85em' }}>
                    <summary style={{ cursor: 'pointer', opacity: 0.8 }}>
                      history ({a.history.length})
                    </summary>
                    {[...a.history].reverse().map((h) => (
                      <div key={h.id} style={{ margin: '3px 0', opacity: h.superseded ? 0.65 : 1 }}>
                        <span style={{
                          display: 'inline-block', padding: '0 4px', marginRight: 4,
                          borderRadius: 3, fontSize: '0.8em',
                          background: h.superseded ? '#57534e' : '#166534', color: '#fff',
                        }}>
                          {h.superseded ? 'SUPERSEDED' : 'CURRENT'}
                        </span>
                        {h.text}
                        <div style={{ opacity: 0.7, marginLeft: 8 }}>
                          {h.observed_at ? h.observed_at.slice(0, 16).replace('T', ' ') + 'Z' : ''}
                          {h.speaker ? ` — ${h.speaker}` : ''}
                          {h.source ? ` — ${h.source}` : ''}
                        </div>
                      </div>
                    ))}
                  </details>
                )}
              </div>
            ))}
          </div>
        )}

        {unitBrief?.statements?.length > 0 && (
          <div className="unit-meta-section">
            <details>
              <summary className="unit-meta-key" style={{ cursor: 'pointer' }}>
                Reporting ({unitBrief.statements.length})
              </summary>
              {[...unitBrief.statements].reverse().map((sRow) => (
                <div key={sRow.id} style={{ margin: '4px 0', fontSize: '0.88em' }}>
                  {sRow.text}
                  <div style={{ opacity: 0.7, marginLeft: 8 }}>
                    {sRow.observed_at ? sRow.observed_at.slice(0, 16).replace('T', ' ') + 'Z' : ''}
                    {sRow.speaker ? ` — ${sRow.speaker}` : ''}
                    {sRow.source ? ` — ${sRow.source}` : ''}
                  </div>
                </div>
              ))}
            </details>
          </div>
        )}

        {unitBrief?.doctrine?.length > 0 && (
          <div className="unit-meta-section">
            <details>
              <summary className="unit-meta-key" style={{ cursor: 'pointer' }}>
                Doctrine ({unitBrief.doctrine.length})
              </summary>
              {unitBrief.doctrine.map((d, i) => (
                <div key={i} style={{ margin: '4px 0', fontSize: '0.88em' }}>
                  {d.text}
                  {d.source && (
                    <div style={{ opacity: 0.7, marginLeft: 8 }}>{d.source}</div>
                  )}
                </div>
              ))}
            </details>
          </div>
        )}

        {/* Entity-graph units open the IN-APP link view (the ported
            GraphViewer, design decision 17), focused on the record
            uuid — the kbid/name fallback chain retired with the
            cougaar data path. */}
        {props.source === 'entity_graph' && (
          <a
            className="unit-meta-source"
            href="#link-view"
            onClick={(e) => {
              e.preventDefault()
              window.dispatchEvent(new CustomEvent('geoagent:openLinkView', {
                detail: { id: String(u.id || props.id || '') },
              }))
            }}
          >
            View relationships →
          </a>
        )}
        {/* Legacy deep link into the embedding shell's graph viewer
            (cougaar-era rows only). The shell DECLARES the surface by
            passing ?graph_viewer_url= on the iframe URL — geo-agent is
            standalone and never hardcodes a consumer's routes. No
            param → no link, instead of a dead tab. */}
        {props.source !== 'entity_graph' && dataSourceKbid && shellGraphViewerUrl && (
          <a
            className="unit-meta-source"
            href={`${shellGraphViewerUrl}${shellGraphViewerUrl.includes('?') ? '&' : '?'}focus_kbid=${encodeURIComponent(dataSourceKbid)}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            View data source →
          </a>
        )}
      </div>
    </div>
  )
}
