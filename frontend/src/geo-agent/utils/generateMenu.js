/**
 * Per-target generation menu — shared by the map right-click gesture
 * (useMapEvents) and the unit-metadata panel's subordinate-tree rows
 * (UnitCompositionTree / UnitMetadataPanel). Extracted verbatim from
 * useMapEvents.js so both surfaces fire the exact same generate flow.
 *
 * Direct DOM rather than a React portal: the original caller is a pure
 * event-binding hook with no render state, and the panel reuses the same
 * floating menu so the two gestures stay pixel-identical. The DOM nodes
 * are self-cleaning.
 */

export const GENERATE_MENU_ID = 'geoagent-generate-menu'

// Tear down any previously-rendered ephemeral menu / toast nodes. Keeping
// only one alive at a time matches the analyst's mental model — second
// right-click on a different unit replaces the first menu.
export function dismissEphemeral(id) {
  if (typeof document === 'undefined') return
  const existing = document.getElementById(id)
  if (existing && existing.parentNode) existing.parentNode.removeChild(existing)
}

// Per-target Deliver-phase products the analyst can generate from a single
// right-clicked red mil_unit. Each entry: { productType, label, format }.
// Order = canonical D3A targeting sequence MATCHING THE DAG dependency
// flow (so the analyst's left-to-right gesture mirrors the sidebar's
// top-to-bottom order from the doctrine-reorder PR):
//   TMP first — mints the JDPI and parent_etf_eid for this target.
//   TIDAT next — consumes lookup:TMP.jdpi_id + lookup:TMP.parent_etf_eid,
//     so firing TIDAT before TMP leaves those fields empty.
//   CDE — consumes TMP + NSL + RTL; sits after TMP exists.
//   BDA / CA — post-engagement assessment (FM 3-60 ¶2-70).
// Every format (docx + pptx + xlsx) opens in LiveEditor; the Collabora
// WOPI handler picks Writer / Impress / Calc by MIME server-side.
// `format` here is only used to label the artifact and bake the right
// extension into the export URL — it does NOT select a different React
// component. (SheetEditor.tsx is a back-compat alias for LiveEditor.)
export const PER_TARGET_PRODUCTS = [
  { productType: 'TMP',   label: 'Generate TMP (Target Material Production)',         format: 'docx' },
  { productType: 'TIDAT', label: 'Generate TIDAT (Target Intelligence Data Report)', format: 'docx' },
  { productType: 'CDE',   label: 'Generate CDE (Collateral Damage Estimate)',         format: 'docx' },
  { productType: 'BDA',   label: 'Generate BDA (Battle Damage Assessment)',           format: 'pptx' },
  { productType: 'CA',    label: 'Generate Combat Assessment',                        format: 'pptx' },
]

/**
 * Render an inline floating per-target generation menu at (screenX, screenY).
 * Each item dispatches to `fireGenerateAndOpen` which fires the generate
 * endpoint, polls the unified product-records chain for completion, then
 * navigates the browser to `/missioncommand/docs/{autodraft_session_id}` so
 * the analyst lands inside the rendered artifact. The whole point of the
 * gesture is opening the artifact for review — fire-and-forget would leave
 * the analyst staring at the map wondering whether anything happened.
 */
export function showGenerateTidatMenu({ screenX, screenY, entityId, callsign, userId, addActivity, navigate }) {
  if (typeof document === 'undefined') return

  const MENU_ID = GENERATE_MENU_ID
  dismissEphemeral(MENU_ID)

  const menu = document.createElement('div')
  menu.id = MENU_ID
  menu.style.position = 'fixed'
  menu.style.left = `${screenX}px`
  menu.style.top = `${screenY}px`
  menu.style.zIndex = '2000'
  menu.style.background = '#1a1a2e'
  menu.style.color = '#e6e6f0'
  menu.style.border = '1px solid #3a3a52'
  menu.style.borderRadius = '4px'
  menu.style.padding = '4px 0'
  menu.style.minWidth = '320px'
  menu.style.boxShadow = '0 4px 12px rgba(0,0,0,0.4)'
  menu.style.fontSize = '13px'
  menu.style.userSelect = 'none'

  // Header — names the bound target so the analyst knows what every menu
  // item will be authored against. OOB/scenario names can collide at
  // the same MGRS, so the topmost hit (which the contextmenu handler
  // picked) is the binding even if multiple units overlap at this point.
  const header = document.createElement('div')
  header.textContent = callsign || entityId
  header.style.padding = '6px 14px'
  header.style.fontSize = '11px'
  header.style.color = '#a0a0b8'
  header.style.textTransform = 'uppercase'
  header.style.letterSpacing = '0.4px'
  header.style.borderBottom = '1px solid #2a2a44'
  menu.appendChild(header)

  for (const spec of PER_TARGET_PRODUCTS) {
    const item = document.createElement('div')
    item.textContent = spec.label
    item.style.padding = '6px 14px'
    item.style.cursor = 'pointer'
    item.addEventListener('mouseenter', () => { item.style.background = '#2a2a44' })
    item.addEventListener('mouseleave', () => { item.style.background = 'transparent' })
    item.addEventListener('click', () => {
      dismissEphemeral(MENU_ID)
      fireGenerateAndOpen({
        productType: spec.productType,
        format: spec.format,
        entityId, callsign, userId, addActivity, navigate,
      })
    })
    menu.appendChild(item)
  }
  document.body.appendChild(menu)

  // Auto-dismiss: outside-click, Escape, second right-click, or
  // page navigation. All listeners self-clean.
  const dismiss = () => {
    dismissEphemeral(MENU_ID)
    document.removeEventListener('mousedown', onDown, true)
    document.removeEventListener('keydown', onKey, true)
    document.removeEventListener('contextmenu', onDown, true)
  }
  const onDown = (ev) => {
    if (menu.contains(ev.target)) return
    dismiss()
  }
  const onKey = (ev) => {
    if (ev.key === 'Escape') dismiss()
  }
  document.addEventListener('mousedown', onDown, true)
  document.addEventListener('keydown', onKey, true)
  document.addEventListener('contextmenu', onDown, true)
}

/**
 * Fire the generate POST, poll the unified product-records chain for
 * completion, then navigate the browser to the rendered artifact in the
 * DocEditor. The toast updates through three states: "Generating <PT>
 * for <callsign>" while waiting, then "Opening <PT>" on completion, and
 * the page transitions away. On timeout (>120s) or error the toast flips
 * to a failure variant and the analyst stays on the map.
 *
 * Polling rather than WebSocket-listening: the unified product_records
 * broadcast IS already on the WS the sidebar mounts, but plumbing a
 * per-call listener through the React context would entangle this hook
 * with realtime state. The chain endpoint resolves cheaply (cached
 * JSON, <50 ms) and 5 polls × 5 s covers the typical 30-90 s author
 * latency comfortably.
 */
export function fireGenerateAndOpen({ productType, format, entityId, callsign, userId, addActivity, navigate }) {
  const by = userId || ''
  const startMs = Date.now()
  const postUrl = `/api/products/generate?product_type=${encodeURIComponent(productType)}`
    + `&target_entity_id=${encodeURIComponent(entityId)}`
    + (by ? `&by=${encodeURIComponent(by)}` : '')

  showTransientToast(`Generating ${productType} for ${callsign}`)
  if (typeof addActivity === 'function') {
    try { addActivity(`Generating ${productType} for ${callsign}`, 'info') } catch { /* ignore */ }
  }

  fetch(postUrl, { method: 'POST' })
    .then((res) => {
      if (!res.ok) {
        showTransientToast(`${productType} request failed (HTTP ${res.status})`, true)
        return
      }
      pollAndOpen({ productType, format, entityId, callsign, startMs, navigate, addActivity })
    })
    .catch((err) => {
      console.warn(`[Generate ${productType}] POST failed:`, err)
      showTransientToast(`${productType} request failed`, true)
    })
}

/**
 * Poll /api/products/records every 4 seconds for up to 150 s looking for a
 * `rest_generate_async` chain with our target_entity_id that's reached
 * state='complete'. When found, redirect to its DocEditor session URL.
 */
function pollAndOpen({ productType, format, entityId, callsign, startMs, navigate, addActivity }) {
  const POLL_MS = 4000
  const TIMEOUT_MS = 150_000

  let cancelled = false
  const tick = async () => {
    if (cancelled) return
    if (Date.now() - startMs > TIMEOUT_MS) {
      showTransientToast(`${productType} timed out (>${Math.round(TIMEOUT_MS/1000)} s); check Drafts`, true)
      return
    }
    try {
      const r = await fetch(`/api/products/records?product_type=${encodeURIComponent(productType)}`)
      if (!r.ok) {
        setTimeout(tick, POLL_MS)
        return
      }
      const body = await r.json()
      const chains = (body && body.chains) || []
      // Match: this product, this target_entity_id, started after our POST,
      // state complete with an artifact_id. The records endpoint returns
      // chains globally; client-side filter is the contract.
      const match = chains
        .filter(c => c && c.product_type === productType)
        .filter(c => c.source === 'rest_generate_async')
        .filter(c => c.source_metadata && c.source_metadata.target_entity_id === entityId)
        .filter(c => (c.started_at_ms || 0) >= startMs - 5000)
        .sort((a, b) => (b.started_at_ms || 0) - (a.started_at_ms || 0))[0]
      if (match && match.state === 'complete' && match.autodraft_session_id && match.artifact_id) {
        showTransientToast(`Opening ${productType} ${match.artifact_id}`)
        if (typeof addActivity === 'function') {
          try { addActivity(`Opened ${productType} ${match.artifact_id} for ${callsign}`, 'success') } catch { /* ignore */ }
        }
        const params = new URLSearchParams({
          pending_product_type: productType,
          pending_format: format || '',
          opening: '1',
        })
        const url = `/missioncommand/docs/${encodeURIComponent(match.autodraft_session_id)}?${params.toString()}`
        // Iframe-aware navigation: react-router lives in the parent
        // (pytho-app), not inside the geo-agent iframe. postMessage the
        // parent so it can navigate its own router to
        // /missioncommand/docs/<session_id>. Fall back to react-router
        // navigate() when the map is mounted OUTSIDE an iframe (e.g. the
        // future geo-agent standalone dev harness).
        if (typeof window !== 'undefined' && window.parent !== window) {
          try {
            window.parent.postMessage(
              { type: 'geoagent.navigate', url }, '*',
            )
          } catch (_e) {
            window.top && window.top.location.assign(url)
          }
        } else if (typeof navigate === 'function') {
          navigate(url)
        } else if (typeof window !== 'undefined') {
          window.location.assign(url)
        }
        return
      }
      if (match && match.state === 'failed') {
        showTransientToast(`${productType} chain failed: ${(match.error || '').slice(0, 100)}`, true)
        return
      }
      setTimeout(tick, POLL_MS)
    } catch (err) {
      console.warn(`[Generate ${productType}] poll failed:`, err)
      setTimeout(tick, POLL_MS)
    }
  }
  setTimeout(tick, POLL_MS)
}

export function showTransientToast(message, isError = false) {
  if (typeof document === 'undefined') return
  const TOAST_ID = 'geoagent-generate-toast'
  dismissEphemeral(TOAST_ID)

  const node = document.createElement('div')
  node.id = TOAST_ID
  node.textContent = message
  node.style.position = 'fixed'
  node.style.top = '20px'
  node.style.left = '50%'
  node.style.transform = 'translateX(-50%)'
  node.style.zIndex = '2100'
  node.style.background = isError ? '#7c1d1d' : '#1a3a5f'
  node.style.color = '#fff'
  node.style.padding = '8px 16px'
  node.style.borderRadius = '4px'
  node.style.fontSize = '13px'
  node.style.boxShadow = '0 4px 12px rgba(0,0,0,0.4)'
  node.style.pointerEvents = 'none'
  document.body.appendChild(node)

  setTimeout(() => dismissEphemeral(TOAST_ID), 3000)
}
