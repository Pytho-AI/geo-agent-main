/**
 * useGeoAgentRealtime — singleton-ish WebSocket consumer for the geo-agent
 * /api/v1/ws backend channel scoped to a single mapId.
 *
 * The geo-agent backend's ConnectionManager (backend/app/services/realtime/
 * manager.py) emits broadcast frames keyed by session_id (= the map UUID).
 * On any incoming frame whose `type` is `sync_complete`, an operation-kind
 * tag (geoops per-op frames), or `ingest_complete` (gateway), the hook
 * invokes the supplied `onSyncComplete(data)` callback so the caller can
 * bump its map-refresh trigger and re-pull /maps/state.
 *
 * Mount contract:
 *   - One socket per `mapId` per consumer mount. The OperationsMap page
 *     mounts this from GeoAgentProvider (analyst path only); the headless
 *     screenshot route skips the hook by gating on `enabled=false`.
 *   - Exponential reconnect backoff 1s → 2s → 4s → 8s cap. No infinite
 *     reconnect storm; a `wasClean === true` close (component unmount)
 *     halts reconnection.
 *   - Ping every 25s, matching the backend ws.py keepalive cadence.
 *   - Cleans up on unmount: clears timers, sets a "stopped" flag, closes
 *     the socket cleanly.
 *
 * The hook is intentionally tiny: it does NOT decide which frames are
 * relevant — that's the caller's job in onSyncComplete. The map_id query
 * param is REQUIRED by the backend (ws.py:12); the hook composes the URL
 * accordingly.
 */

import { useEffect, useRef } from 'react'

const RECONNECT_BACKOFF_MS = [1000, 2000, 4000, 8000]
const PING_INTERVAL_MS = 25000

// Frame types that should fire a refresh on the consumer side. `sync_complete`
// is the new emit from maps.py sync_map_layer. The live_oob/writer push path
// also goes through /sync, so it lands on sync_complete too. `ingest_complete`
// is the gateway-driven ingest-finished broadcast from ws.py:99-107. Op-kind
// frames (geoops, ws.py:71-76) cover per-op overlay updates. Anything else is
// dropped on the floor — the caller decides what to do with relevant frames.
const REFRESH_FRAME_TYPES = new Set([
  'sync_complete',
  'ingest_complete',
  // entity-graph post-commit nudge (graph.py _nudge) — a record CRUD /
  // template / wipe write coalesces to one graph_updated frame.
  'graph_updated',
  // op-kind frames from geoops (overlay create/update/delete, entity
  // create/update/delete) — wholesale refresh on any of these.
  'overlay_created',
  'overlay_updated',
  'overlay_deleted',
  'entity_created',
  'entity_updated',
  'entity_deleted',
])

/**
 * Open a WebSocket against the geo-agent backend and invoke onSyncComplete
 * whenever a relevant frame arrives.
 *
 * @param {Object} opts
 * @param {string} opts.mapId  Map UUID (REQUIRED by the backend ws.py:12)
 * @param {boolean} opts.enabled  When false, no socket is opened. Used to
 *   suppress the hook in headless render mode.
 * @param {(data: any) => void} opts.onSyncComplete  Invoked with the frame's
 *   `data` payload for every relevant frame type.
 */
export function useGeoAgentRealtime({ mapId, enabled, onSyncComplete }) {
  // Ref instead of state — the callback can change between renders without
  // tearing down the socket. We always invoke the latest version.
  const onSyncCompleteRef = useRef(onSyncComplete)
  useEffect(() => { onSyncCompleteRef.current = onSyncComplete }, [onSyncComplete])

  useEffect(() => {
    if (!enabled || !mapId) return

    let stopped = false
    let socket = null
    let reconnectTimer = null
    let pingTimer = null
    let attempt = 0

    // Build the WebSocket URL from window.location so the same code path
    // works behind the analyst's nginx proxy (which routes /api/v1/* to the
    // geo-agent backend). Mirrors the relative-path default in
    // GeoAgentProvider's DEFAULT_CONFIG.apiUrl. No localhost fallback —
    // analysts sit on a different host than the server.
    const buildUrl = () => {
      if (typeof window === 'undefined' || !window.location) return null
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${proto}//${window.location.host}/geo-api/v1/ws?map_id=${encodeURIComponent(mapId)}`
    }

    const scheduleReconnect = () => {
      if (stopped) return
      const delay = RECONNECT_BACKOFF_MS[
        Math.min(attempt, RECONNECT_BACKOFF_MS.length - 1)
      ]
      attempt += 1
      reconnectTimer = setTimeout(connect, delay)
    }

    const clearPing = () => {
      if (pingTimer) {
        clearInterval(pingTimer)
        pingTimer = null
      }
    }

    const connect = () => {
      if (stopped) return
      const url = buildUrl()
      if (!url) return

      try {
        socket = new WebSocket(url)
      } catch (err) {
        // Construction failure (malformed URL, etc.). Treat like a closed
        // socket and back off.
        console.warn('[useGeoAgentRealtime] socket construct failed:', err)
        scheduleReconnect()
        return
      }

      socket.onopen = () => {
        attempt = 0
        clearPing()
        // Match the backend ws.py keepalive cadence (25s). The backend only
        // echoes "pong" when it receives the literal text "ping" — a JSON
        // envelope is silently ignored. Send the raw token, not a JSON
        // frame. Wrap in try so a mid-flight close doesn't throw an
        // unhandled error.
        pingTimer = setInterval(() => {
          try {
            if (socket && socket.readyState === WebSocket.OPEN) {
              socket.send('ping')
            }
          } catch {
            /* swallow — onclose will fire and reconnect */
          }
        }, PING_INTERVAL_MS)
      }

      socket.onmessage = (event) => {
        if (stopped) return
        let frame
        try {
          frame = typeof event.data === 'string'
            ? JSON.parse(event.data)
            : null
        } catch {
          // Non-JSON frames (pong text, etc.) — ignore.
          return
        }
        if (!frame || typeof frame !== 'object') return
        const type = frame.type
        if (!type) return
        if (REFRESH_FRAME_TYPES.has(type)) {
          try {
            onSyncCompleteRef.current?.(frame.data || frame)
          } catch (err) {
            console.warn('[useGeoAgentRealtime] onSyncComplete threw:', err)
          }
        }
      }

      socket.onerror = () => {
        // Errors are immediately followed by onclose; defer all
        // reconnect bookkeeping to onclose so we don't double-schedule.
      }

      socket.onclose = () => {
        clearPing()
        socket = null
        if (stopped) return
        scheduleReconnect()
      }
    }

    connect()

    return () => {
      stopped = true
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      clearPing()
      if (socket) {
        try {
          socket.onopen = null
          socket.onmessage = null
          socket.onerror = null
          socket.onclose = null
          if (socket.readyState === WebSocket.OPEN ||
              socket.readyState === WebSocket.CONNECTING) {
            socket.close(1000, 'unmount')
          }
        } catch {
          /* ignore */
        }
        socket = null
      }
    }
  }, [mapId, enabled])
}

export default useGeoAgentRealtime
