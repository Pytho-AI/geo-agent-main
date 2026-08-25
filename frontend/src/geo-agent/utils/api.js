/**
 * API client utilities for Geo-Agent backend
 */

import { logAnalystEvent } from '../../lib/analystEvent'

/**
 * Safely parse JSON response, returning null for empty responses
 * @param {Response} res - Fetch response
 * @returns {Promise<any>} Parsed JSON or null
 */
const safeJson = async (res) => {
  const text = await res.text()
  if (!text || text.trim() === '') {
    return null
  }
  try {
    return JSON.parse(text)
  } catch (e) {
    console.error('Failed to parse JSON:', text.substring(0, 200))
    throw new Error('Invalid JSON response from server')
  }
}

/**
 * Create an API client with a base URL
 * @param {string} baseUrl - Base URL for the API
 * @returns {Object} API client methods
 */
export const createApiClient = (baseUrl, userId) => {
  // userId is appended to multi-user mutating endpoints (/entities,
  // /overlays, /custom-symbols, /artifacts) as a `user_id` query param.
  // The geo-agent backend records it as the row's `created_by` so the
  // dashboard / audit view can show who made which change. Required
  // server-side; supplying a real analyst id (Cognito sub / email) here
  // is non-negotiable for multi-user maps.
  const uidQs = (extra = "") => {
    const q = new URLSearchParams(extra)
    if (userId) q.set("user_id", String(userId))
    const s = q.toString()
    return s ? `?${s}` : ""
  }
  const client = {
    /**
     * Get map state (entities, overlays) for a bounding box
     */
    getMapState: async (mapId, bbox, kinds, asOf) => {
      const bboxStr = Array.isArray(bbox) ? bbox.join(',') : bbox
      // Schema-driven server-side kind filter. The caller passes the
      // active product's allowed kinds (from schema.map_overlay_kinds,
      // forwarded by intel_agent.tool_render_map → URL param → render
      // config → here). The geo-agent filters server-side; the client
      // has no product-aware logic.
      const kindsQs = kinds && kinds.size > 0
        ? `&kinds=${Array.from(kinds).join(',')}`
        : ''
      // Timeline scrub: an ISO timestamp re-resolves graph features
      // from their append-only tracks as of that time (observed_at —
      // the record's one temporal dimension); absent = live.
      const asOfQs = asOf ? `&as_of=${encodeURIComponent(asOf)}` : ''
      // A product record's own figure paints the project layer PLUS
      // that record's draft rows. Only the headless render URL ever
      // carries include_draft_of (built by the render pipeline); the
      // live analyst map never sets it, so this passthrough is inert
      // outside record-figure renders.
      const draftOf = new URLSearchParams(window.location.search)
        .get('include_draft_of')
      const draftQs = draftOf
        ? `&include_draft_of=${encodeURIComponent(draftOf)}`
        : ''
      const res = await fetch(
        `${baseUrl}/map/state?map_id=${mapId}&bbox=${bboxStr}${kindsQs}${asOfQs}${draftQs}`
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await safeJson(res)
      // Return default empty state if no data
      return data || {
        entities: { type: 'FeatureCollection', features: [] },
        overlays: { type: 'FeatureCollection', features: [] },
        meta: { entity_count: 0, overlay_count: 0, mil_unit_count: 0 }
      }
    },

    /**
     * Dated point observations per movable unit (oldest-first) — the
     * client-side data behind the timeline scrubber. One fetch per
     * map; dragging resolves positions locally per tick.
     */
    getTrackFrames: async (mapId) => {
      const res = await fetch(`${baseUrl}/map/state/track-frames?map_id=${mapId}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await safeJson(res)
      return (data && data.frames) || {}
    },

    /**
     * Create a new entity
     */
    createEntity: async (mapId, data) => {
      const res = await fetch(
        `${baseUrl}/entities${uidQs(`map_id=${mapId}`)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        }
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Update an entity
     */
    updateEntity: async (entityId, data) => {
      const res = await fetch(`${baseUrl}/entities/${entityId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Delete an entity
     */
    deleteEntity: async (entityId) => {
      const res = await fetch(`${baseUrl}/entities/${entityId}`, {
        method: 'DELETE'
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.ok
    },

    /**
     * Create a new overlay
     */
    createOverlay: async (mapId, data) => {
      const res = await fetch(
        `${baseUrl}/overlays${uidQs(`map_id=${mapId}`)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        }
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Update an overlay
     */
    updateOverlay: async (overlayId, data) => {
      const res = await fetch(`${baseUrl}/overlays/${overlayId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Delete an overlay
     */
    deleteOverlay: async (overlayId) => {
      const res = await fetch(`${baseUrl}/overlays/${overlayId}`, {
        method: 'DELETE'
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.ok
    },

    /**
     * Upload an artifact (file)
     */
    uploadArtifact: async (mapId, file) => {
      const formData = new FormData()
      formData.append('file', file)
      
      const res = await fetch(
        `${baseUrl}/artifacts${uidQs(`map_id=${mapId}`)}`,
        {
          method: 'POST',
          body: formData
        }
      )
      if (!res.ok) throw new Error('Upload failed')
      return safeJson(res)
    },

    /**
     * Ingest an artifact
     */
    ingestArtifact: async (artifactId) => {
      const res = await fetch(`${baseUrl}/artifacts/${artifactId}/ingest`, {
        method: 'POST'
      })
      if (!res.ok) throw new Error('Ingestion failed')
      return safeJson(res)
    },

    /**
     * Natural language query
     */
    nlQuery: async (mapId, text, bbox) => {
      const res = await fetch(`${baseUrl}/nl/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          map_id: mapId,
          // Required by NLQueryRequest (see nlChat note).
          user_id: userId || 'unknown',
          bbox
        })
      })
      if (!res.ok) throw new Error('Query failed')
      return safeJson(res)
    },

    /**
     * Natural language chat for map operations
     * Returns proposed operations for approval before execution
     * @param {string} mapId - Map ID
     * @param {string} text - User's message
     * @param {Array<number>} bbox - Current viewport bounding box
     * @param {Array<{role: string, content: string}>} history - Conversation history
     * @returns {Promise<{message: string, proposed_ops: Array, requires_approval: boolean, clarification_needed: string|null}>}
     */
    nlChat: async (mapId, text, bbox, history = null) => {
      const res = await fetch(`${baseUrl}/nl/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          map_id: mapId,
          // Required by NLChatRequest — the omission 422'd every
          // UI-originated chat call. Same identity every other write
          // path sends (attribution + telemetry).
          user_id: userId || 'unknown',
          bbox,
          conversation_history: history
        })
      })
      if (!res.ok) throw new Error('Chat request failed')
      return safeJson(res)
    },

    /**
     * Execute geo operations (create, move, update, delete entities/overlays)
     * @param {string} mapId - Map ID
     * @param {Array<Object>} ops - Array of operations to execute
     * @returns {Promise<{results: Array<{op: string, success: boolean, id?: string, error?: string}>}>}
     */
    executeGeoOps: async (mapId, ops) => {
      const res = await fetch(`${baseUrl}/geoops`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          map_id: mapId,
          // Required by GeoOpsRequest (MapRequest base) — and it IS
          // the created_by attribution on every op the batch executes.
          user_id: userId || 'unknown',
          ops
        })
      })
      if (!res.ok) throw new Error('GeoOps execution failed')
      return safeJson(res)
    },

    /**
     * Update map viewport state (bbox, center, zoom)
     * Called asynchronously when user pans/zooms
     * @param {string} mapId - Map ID
     * @param {Object} viewport - Viewport state
     */
    updateMapViewport: async (mapId, viewport) => {
      const res = await fetch(`${baseUrl}/maps/${mapId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(viewport)
      })
      // Silently fail - this is a background save
      if (!res.ok) {
        console.warn('Failed to save map viewport')
      }
      return res.ok
    },

    /**
     * Get map details
     * @param {string} mapId - Map ID
     */
    getMap: async (mapId) => {
      const res = await fetch(`${baseUrl}/maps/${mapId}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Generate a Common Operational Picture from a world state narrative.
     * Creates a new map with extracted entities, overlays, and routes.
     * @param {string} worldState - Narrative text describing the tactical situation
     * @returns {Promise<{map_id: string, bbox: number[], entities: Object, overlays: Object, routes: Array, terrain: Object|null, meta: Object, generation_summary: string}>}
     */
    generateCOP: async (worldState) => {
      const res = await fetch(`${baseUrl}/cop/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          world_state: worldState
        })
      })
      if (!res.ok) {
        const errData = await safeJson(res).catch(() => null)
        throw new Error(errData?.detail || `COP generation failed (HTTP ${res.status})`)
      }
      return safeJson(res)
    },

    /**
     * Plan a route: computes up to 3 alternative paths
     * @param {string} mapId - Map ID
     * @param {Object} params - Route parameters
     * @param {Object} params.start_geom - GeoJSON Point for start
     * @param {Object} params.end_geom - GeoJSON Point for end
     * @param {string} params.route_mode - "on_road", "off_road", or "mixed"
     * @param {string} [params.name] - Optional route name
     * @returns {Promise<Object>} Route with paths and analysis
     */
    planRoute: async (mapId, params) => {
      const res = await fetch(
        `${baseUrl}/routes/plan?map_id=${mapId}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params)
        }
      )
      if (!res.ok) {
        const err = await safeJson(res)
        const detail = err?.detail
        // 422 with diagnostic payload — attach structured detail to the error
        if (res.status === 422 && detail && typeof detail === 'object') {
          const e = new Error(detail.message || 'Route planning failed')
          e.diagnostic = detail.diagnostic || null
          throw e
        }
        throw new Error(typeof detail === 'string' ? detail : `HTTP ${res.status}`)
      }
      return safeJson(res)
    },

    /**
     * Get routes for a map
     */
    getRoutes: async (mapId) => {
      const res = await fetch(`${baseUrl}/routes?map_id=${mapId}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Select a path on a route
     */
    selectPath: async (routeId, pathId) => {
      const res = await fetch(`${baseUrl}/routes/${routeId}/paths/${pathId}/select`, {
        method: 'POST'
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Delete a route
     */
    deleteRoute: async (routeId) => {
      const res = await fetch(`${baseUrl}/routes/${routeId}`, {
        method: 'DELETE'
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.ok
    },

    /**
     * Analyze user-drawn/edited route coordinates (off-road analysis)
     * @param {string} mapId - Map ID
     * @param {Array<[number, number]>} coordinates - [[lon, lat], ...]
     * @returns {Promise<Object>} Analysis results
     */
    analyzeRouteEdit: async (mapId, coordinates) => {
      const res = await fetch(
        `${baseUrl}/routes/analyze-edit?map_id=${mapId}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ coordinates })
        }
      )
      if (!res.ok) {
        const err = await safeJson(res)
        throw new Error(err?.detail || `HTTP ${res.status}`)
      }
      return safeJson(res)
    },

    /**
     * Update a route path (geometry and/or analysis)
     * @param {string} routeId - Route ID
     * @param {string} pathId - Path ID
     * @param {Object} data - { geom?, analysis?, label? }
     */
    updatePath: async (routeId, pathId, data) => {
      const res = await fetch(`${baseUrl}/routes/${routeId}/paths/${pathId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return safeJson(res)
    },

    /**
     * Custom symbol library (PNG/SVG icons uploaded by users, global scope).
     */
    listCustomSymbols: async () => {
      const res = await fetch(`${baseUrl}/custom-symbols`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return (await safeJson(res)) || []
    },
    uploadCustomSymbol: async (file) => {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(
        `${baseUrl}/custom-symbols${uidQs()}`,
        { method: 'POST', body: formData }
      )
      if (!res.ok) {
        const err = await safeJson(res).catch(() => null)
        throw new Error(err?.detail || `Upload failed (HTTP ${res.status})`)
      }
      return safeJson(res)
    },
    deleteCustomSymbol: async (symbolId) => {
      const res = await fetch(`${baseUrl}/custom-symbols/${symbolId}`, {
        method: 'DELETE'
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.ok
    },
    customSymbolUrl: (symbolId) => `${baseUrl}/custom-symbols/${symbolId}/file`
  }

  // ---- Analyst-action audit (persistent) ---------------------------------
  // Every MUTATING client method reports one analyst_events row to the
  // backend's persistent audit sink after it resolves — success AND
  // failure (`<event>.failed` with the error message), because "what
  // did the analyst do right before it broke" is the whole point of a
  // debugging audit trail. One chokepoint here instead of call-site
  // sprinkling: every map surface (panels, hooks, toolbars) funnels
  // its writes through these methods. Reads and viewport saves are
  // deliberately NOT audited — the viewport persists on every moveend
  // and would drown the signal. Fire-and-forget: logAnalystEvent never
  // throws and never blocks the mutation result.
  const AUDITED_METHODS = {
    createEntity: 'map.entity_created',
    updateEntity: 'map.entity_updated',
    deleteEntity: 'map.entity_deleted',
    createOverlay: 'map.overlay_created',
    updateOverlay: 'map.overlay_updated',
    deleteOverlay: 'map.overlay_deleted',
    uploadArtifact: 'map.artifact_uploaded',
    ingestArtifact: 'map.artifact_ingested',
    nlQuery: 'nl.query_submitted',
    nlChat: 'nl.chat_submitted',
    executeGeoOps: 'map.geoops_executed',
    planRoute: 'route.planned',
    selectPath: 'route.path_selected',
    deleteRoute: 'route.deleted',
    updatePath: 'route.path_updated',
    uploadCustomSymbol: 'symbol.uploaded',
    deleteCustomSymbol: 'symbol.deleted',
  }
  // Methods whose FIRST positional arg is the map id.
  const MAP_SCOPED = new Set([
    'createEntity', 'createOverlay', 'nlQuery', 'nlChat',
    'executeGeoOps', 'planRoute',
  ])
  const auditDetail = (method, args) => {
    try {
      switch (method) {
        case 'createEntity':
        case 'createOverlay':
          return { kind: args[1]?.kind, name: args[1]?.name || args[1]?.attrs?.name }
        case 'updateEntity':
        case 'updateOverlay':
        case 'updatePath':
          return { id: String(args[0]), fields: Object.keys(args[1] || {}) }
        case 'deleteEntity':
        case 'deleteOverlay':
        case 'deleteRoute':
        case 'deleteCustomSymbol':
        case 'ingestArtifact':
          return { id: String(args[0]) }
        case 'nlQuery':
        case 'nlChat':
          return { text: String(args[1] ?? '').slice(0, 500) }
        case 'executeGeoOps':
          return {
            op_count: (args[1] || []).length,
            ops: (args[1] || []).map((o) => o?.op).slice(0, 50),
          }
        case 'planRoute':
          return { mode: args[1]?.mode, force_type: args[1]?.force_type }
        case 'selectPath':
          return { route_id: String(args[0]), path_id: String(args[1]) }
        case 'uploadArtifact':
          return { file: args[1]?.name, bytes: args[1]?.size }
        case 'uploadCustomSymbol':
          return { file: args[0]?.name, bytes: args[0]?.size }
        default:
          return null
      }
    } catch {
      return null
    }
  }
  for (const [method, eventType] of Object.entries(AUDITED_METHODS)) {
    const inner = client[method]
    if (typeof inner !== 'function') continue
    client[method] = async (...args) => {
      const base = {
        user_id: userId ?? null,
        map_id: MAP_SCOPED.has(method) ? String(args[0]) : null,
        surface: 'map',
        detail: auditDetail(method, args),
      }
      try {
        const result = await inner(...args)
        logAnalystEvent({ ...base, event_type: eventType })
        return result
      } catch (err) {
        logAnalystEvent({
          ...base,
          event_type: `${eventType}.failed`,
          detail: { ...(base.detail || {}), error: String(err).slice(0, 500) },
        })
        throw err
      }
    }
  }

  return client
}

/**
 * Default API client (uses relative URL)
 */
export const defaultApiClient = createApiClient('/geo-api/v1')
