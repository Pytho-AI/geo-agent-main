/**
 * Hook for map initialization and lifecycle management
 */

import { useEffect, useCallback, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import MapboxDraw from '@mapbox/mapbox-gl-draw'
import { useGeoAgent } from '../GeoAgentProvider'
import { MAP_STYLE, DRAW_STYLES } from '../utils/mapStyles'
import { createApiClient } from '../utils/api'
import { applyDoctrinalControlMeasures, applyProductLayerPreset, applyOmtBasemapPreset } from '../utils/tacticalLayers.maplibre'
import { clientWarn } from '../../lib/clientLog'
import { updateSavedRouteLayers } from '../utils/routeConstants'
import { rollupByEchelon, smoothGeometryCoords } from '../utils/tacticalGraphics.svg'
import { updateEnvelopeVolumes } from '../utils/envelopeVolumes'
import { featureVisible, buildBearerAffiliationIndex } from '../utils/featureVisibility'

/**
 * Hook for initializing and managing the MapLibre map instance
 * @param {Object} options - Configuration options
 * @param {Function} options.onDrawCreate - Callback for draw create events
 * @param {Function} options.onEntityClick - Callback for entity click
 * @param {Function} options.onOverlayClick - Callback for overlay click
 * @returns {Object} Map utilities
 */
export function useMapInstance(options = {}) {
  const {
    mapRef,
    mapContainerRef,
    drawRef,
    milMarkersRef,
    tacticalGraphicMarkersRef,
    defaultCenter,
    defaultZoom,
    apiUrl,
    mapId,
    mapLoaded,
    setMapLoaded,
    milSymRendererReady,
    setMilSymRendererReady,
    setCoordinates,
    setStats,
    addActivity,
    overlayDrawMode,
    setRouteResult,
    setShowRoutePanel,
    setRouteEditMode,
    headless,
    userId,
    rollupEchelonByFaction,
    timelineAsOf,
    timelineDragMs,
    setTrackExtent,
    appConfig,
    allowedKinds: ctxAllowedKinds,
    enabledLayers,
    hiddenTypes,
    // Click-to-show-range-fans on the COP: when the analyst left-clicks a
    // mil_unit, useMapEvents sets selectedUnitMeta; featureVisible uses
    // .props.source_kbid (= scenario.KG unit id, e.g. "U-OCC-721-MRB")
    // to bypass the default range_fan kind-hide for that one unit's fans
    // only. Closing the UnitMetadataPanel clears selectedUnitMeta and the
    // fans go back to hidden. This is independent of the kind:range_fan
    // hiddenTypes toggle — that toggle still controls the "show all
    // fans" path; click-to-select is a per-unit override.
    selectedUnitMeta,
  } = useGeoAgent()

  // Bearer-unit-id of the currently selected unit, normalised — used by
  // featureVisible to allow that unit's range fans through even when
  // the kind:range_fan type toggle is disabled.
  const selectedBearerKgId = (selectedUnitMeta?.props?.source_kbid
    || selectedUnitMeta?.props?.id
    || selectedUnitMeta?.props?.entity_id
    || selectedUnitMeta?.unit?.id
    || '').toString()

  // userId rides every mutating call as ?user_id so created_by
  // attribution survives (ported from the pytho-vite copy).
  const api = createApiClient(apiUrl, userId)

  // Stale-response guard: a slow bbox fetch must never overwrite the
  // result of a newer one (ported from the pytho-vite copy).
  const loadMapStateVersionRef = useRef(0)

  // Mil-units paint path: backend syncs unit features into the geo-agent
  // map (source=live_oob), the frontend pulls them via /map/state, and
  // MapDoctrinalPaint paints them via the SVG PRIMITIVE_DRAWERS dispatch
  // (mil_unit primitive, painted last so icons sit on top of every other
  // graphic per ATP 2-01.3 / FM 6-99 focal-point rule). All clustering +
  // SITEMP hostile-only filtering happens inside _getMilUnitStream in
  // tacticalGraphics.svg.js — this hook only delivers raw GeoJSON to the
  // mil-units source. createMilSymbol is invoked once per (sidc, heading)
  // at paint time and the SVG is cached on the paint registry; no
  // addImage / blob URL / image-manager state to keep in sync.
  // Raw (pre-roll-up) mil-unit cache so moving a faction's echelon
  // slider re-derives the view instantly without a /map/state refetch.
  const rawMilUnitsRef = useRef([])
  // The legend/type visibility predicate for mil units, stashed by the
  // fetch pass so renderMilUnits can re-apply it per-feature (with
  // hover/selected/lock exemptions) without a refetch.
  const milVisPredicateRef = useRef(null)
  const rollupEchelonByFactionRef = useRef(rollupEchelonByFaction)
  useEffect(() => { rollupEchelonByFactionRef.current = rollupEchelonByFaction }, [rollupEchelonByFaction])
  // Self-referencing re-derivation handle (stashed on the map for the
  // placard's hover-exemption path).
  const renderMilUnitsRef = useRef(null)

  // Track frames for CLIENT-SIDE timeline scrubbing: one fetch per
  // map, then every drag tick re-resolves unit positions locally
  // (latest dated frame at or before the thumb time; units with a
  // dated history and no qualifying frame hide; everything else is
  // timeless and stays put). The release commits timelineAsOf and the
  // authoritative server re-resolution reconciles.
  const trackFramesRef = useRef(null)
  const timelineDragMsRef = useRef(null)
  useEffect(() => { timelineDragMsRef.current = timelineDragMs }, [timelineDragMs])

  const _applyDragTime = useCallback((features) => {
    const t = timelineDragMsRef.current
    const frames = trackFramesRef.current
    if (t == null || !frames) return features
    const out = []
    for (const f of features) {
      const track = frames[String(f.id || f.properties?.id)]
      if (!track || !track.length) { out.push(f); continue }   // timeless
      let last = null
      for (const [iso, lon, lat] of track) {
        if (Date.parse(iso) <= t) last = [lon, lat]
        else break
      }
      if (last === null) continue                 // not observed yet
      out.push({ ...f, geometry: { type: 'Point', coordinates: last } })
    }
    return out
  }, [])

  const renderMilUnits = useCallback((features, selectEntity, updateEntityPosition) => {
    if (!mapRef.current) return

    rawMilUnitsRef.current = features

    milMarkersRef.current.forEach(({ marker, cleanup }) => {
      cleanup?.()
      marker?.remove()
    })
    milMarkersRef.current = []
    milMarkersRef.current.selectEntity = selectEntity
    milMarkersRef.current.updateEntityPosition = updateEntityPosition

    // Visibility exemptions: the hovered unit, the SELECTED unit (open
    // placard), and every visibility-LOCKED unit stay on the map
    // through legend toggles and roll-up — the analyst must never lose
    // the unit they are looking at to a filter.
    const exemptIds = new Set()
    const hlIdRaw = mapRef.current.__unitHighlight?.id
    if (hlIdRaw != null) exemptIds.add(String(hlIdRaw))
    if (mapRef.current.__unitSelected?.id != null) {
      exemptIds.add(String(mapRef.current.__unitSelected.id))
    }
    for (const v of mapRef.current.__unitVisibilityLocks || []) {
      exemptIds.add(String(v))
    }

    let stream = []
    for (const feature of features) {
      const props = feature.properties || {}
      const entityId = feature.id || props.id
      if (!props.sidc) continue
      // The legend/type filter runs HERE (per-feature predicate stashed
      // by the fetch pass) so exempt units bypass it without a refetch.
      if (exemptIds.size === 0 || !exemptIds.has(String(entityId))) {
        const pred = milVisPredicateRef.current
        if (pred && !pred(feature)) continue
      }
      stream.push({
        type: 'Feature',
        id: entityId,
        geometry: feature.geometry,
        properties: {
          ...props,
          id: entityId,
        },
      })
    }

    // Per-faction echelon roll-up — live analyst view only.
    // Headless/product renders never see a tier (the slider state exists
    // only in the live UI), so the render path stays schema-driven.
    // Transitions are a single setData — the SVG paint pass repaints
    // discretely on sourcedata, so per-frame coordinate tweening cannot
    // animate it.
    // Live scrub-drag re-times the stream BEFORE the roll-up, so
    // clustered parents follow their subordinates through time.
    stream = _applyDragTime(stream)

    const tiers = rollupEchelonByFactionRef.current
    if (!headless && tiers && Object.keys(tiers).length) {
      // Exemption: hovered / selected / locked units paint AS
      // THEMSELVES even when the tier would roll them up
      // (UnitMetadataPanel re-derives via __rerenderMilUnits).
      stream = rollupByEchelon(
        stream, tiers, exemptIds.size ? exemptIds : null)
    }

    // Exempt units paint LAST — the SVG pass appends in stream order,
    // so the selected/locked unit and its selection ring sit at the
    // top of the symbol stack instead of under its neighbors.
    if (exemptIds.size) {
      const onTop = (f) => exemptIds.has(String(f.id))
        || (Array.isArray(f.properties?.rollupMemberIds)
            && f.properties.rollupMemberIds.some(
              (m) => exemptIds.has(String(m))))
      stream = [...stream.filter((f) => !onTop(f)),
                ...stream.filter(onTop)]
    }

    const source = mapRef.current.getSource('mil-units')
    if (source) {
      source.setData({ type: 'FeatureCollection', features: stream })
    }
    // Hover re-derivation handle for the placard (no listener
    // lifecycle: the freshest closure wins).
    mapRef.current.__rerenderMilUnits = () => renderMilUnitsRef.current?.()
    setStats(prev => ({ ...prev, milUnits: features.length }))
  }, [mapRef, milMarkersRef, setStats, headless, _applyDragTime])

  // Scrub-drag tick: re-derive the stream from cache — no refetch, no
  // debounce; the thumb IS the time. Frames load once per map on the
  // first tick (a quick fetch; subsequent ticks are pure local math).
  useEffect(() => {
    if (timelineDragMs == null || !mapRef.current) return
    if (!trackFramesRef.current) {
      let cancelled = false
      api.getTrackFrames(mapId)
        .then((frames) => {
          if (cancelled) return
          trackFramesRef.current = frames
          renderMilUnits(
            rawMilUnitsRef.current,
            milMarkersRef.current.selectEntity,
            milMarkersRef.current.updateEntityPosition,
          )
        })
        .catch(() => { trackFramesRef.current = {} })
      return () => { cancelled = true }
    }
    renderMilUnits(
      rawMilUnitsRef.current,
      milMarkersRef.current.selectEntity,
      milMarkersRef.current.updateEntityPosition,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timelineDragMs])

  // Keep the hover re-derivation handle pointing at the freshest
  // renderMilUnits closure with the cached raw stream.
  useEffect(() => {
    renderMilUnitsRef.current = () => renderMilUnits(
      rawMilUnitsRef.current,
      milMarkersRef.current.selectEntity,
      milMarkersRef.current.updateEntityPosition,
    )
  }, [renderMilUnits, milMarkersRef])

  // A faction slider moved → re-derive the roll-up from the cached raw
  // features. No refetch; setData fires MapDoctrinalPaint's sourcedata
  // repaint.
  useEffect(() => {
    if (!mapRef.current || !rawMilUnitsRef.current.length) return
    renderMilUnits(
      rawMilUnitsRef.current,
      milMarkersRef.current.selectEntity,
      milMarkersRef.current.updateEntityPosition,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rollupEchelonByFaction])

  // Per MOVEMENT_ARROW_REDESIGN.md §2.2 — ingestion is pure passthrough.
  // SVG paintTacticalGraphics owns all visible paint via PRIMITIVE_DRAWERS.
  const renderTacticalGraphics = useCallback((overlayFeatures) => {
    if (!mapRef.current) return

    tacticalGraphicMarkersRef.current.forEach(({ marker }) => marker?.remove())
    tacticalGraphicMarkersRef.current = []

    const features = overlayFeatures.map(feature => ({
      ...feature,
      properties: {
        ...(feature.properties || {}),
        overlayId: feature.id || feature.properties?.id,
        // The RAW stated geometry — for smoothed features the painted
        // geometry is a derived densification; edits and drags must
        // operate on the analyst's actual vertices.
        originalGeometry: feature.properties?.__rawGeometry
          || JSON.stringify(feature.geometry),
      },
    }))

    const source = mapRef.current.getSource('tactical-graphics')
    if (source) {
      source.setData({ type: 'FeatureCollection', features })
    }
  }, [mapRef, tacticalGraphicMarkersRef])

  // Load map state from API
  const loadMapState = useCallback(async (selectEntity, updateEntityPosition) => {
    const mapInstance = mapRef.current
    if (!mapInstance || typeof mapInstance.getBounds !== 'function') return

    const version = ++loadMapStateVersionRef.current

    try {
      // WHOLE-MAP fetch, not viewport-scoped. Event maps carry a few
      // hundred entities + a couple thousand overlay features — the
      // same payload the Tactical Overlays census already pulls on
      // every refresh — and MapLibre culls client-side for free.
      // Viewport-bbox fetching made units outside the initially loaded
      // box pop in only after zoom/pan ended (moveend debounce + round
      // trip); with the full set loaded, camera moves never need a
      // refetch. The bbox parameter stays supported server-side for
      // headless product renders and API consumers.
      const bbox = '-180,-85,180,85'

      // Schema-driven SERVER-SIDE kind filter. Two sources, in priority
      // order:
      //  1. context.allowedKinds — set by GeoAgentProvider from the map
      //     record's attrs.allowed_kinds (stashed by tool_render_map at
      //     render time). Editor-mode mounts (e.g. EditMap overlay inside
      //     DocEditor) have no URL params and rely on this.
      //  2. URL ?layers= — set by the headless /render route via
      //     intel_agent.tool_render_map for the PNG render path.
      // Either path = the schema's map_overlay_kinds. Both empty =
      // analyst view, no filter, every kind comes back.
      let _allowedKinds = (ctxAllowedKinds && ctxAllowedKinds.size > 0)
        ? ctxAllowedKinds
        : null
      if (!_allowedKinds) {
        try {
          const _layersParam = new URLSearchParams(window.location.search).get('layers')
          if (_layersParam) {
            _allowedKinds = new Set(_layersParam.split(',').filter(Boolean))
          }
        } catch { /* not in a window (SSR / test) → no filter */ }
      }
      const data = await api.getMapState(mapId, bbox, _allowedKinds, timelineAsOf)
      if (!mapRef.current) return
      // Bail if a newer loadMapState started while we were fetching —
      // the stale response must not clobber the newer one's paint.
      if (version !== loadMapStateVersionRef.current) return

      // Publish the project's track time-extent so the timeline
      // scrubber knows whether a time dimension exists and its domain.
      const _extent = data.meta?.track_extent || null
      if (setTrackExtent) setTrackExtent(_extent)
      // PREFETCH the track frames the moment a time dimension exists —
      // fetching them lazily on the FIRST drag tick made the scrubber
      // dead for the whole fetch (the analyst's first scrub sat frozen
      // for seconds). One background fetch per map load.
      if (_extent && (_extent.dated_observations || 0) >= 2
          && !trackFramesRef.current && !trackFramesRef.inflight) {
        trackFramesRef.inflight = true
        api.getTrackFrames(mapId)
          .then((frames) => { trackFramesRef.current = frames })
          .catch(() => { /* the drag path retries */ })
          .finally(() => { trackFramesRef.inflight = false })
      }

      // --- Visibility filter. Operates on the raw feature stream so it
      // applies uniformly to BOTH the MapLibre hit-target layers AND
      // the SVG paint pass (paintTacticalGraphics, MapDoctrinalPaint),
      // which consume the same source data we push below.
      //
      // The model lives in utils/featureVisibility.js and ONLY there:
      // enabledLayers gates product claim-sets (SITEMP:<coa> compounds
      // included; base-map content always passes — provenance is not a
      // view axis), hiddenTypes carries the legend's global type
      // tokens (kind / faction / faction-scoped category + subkind,
      // case-insensitive). enabledLayers = null → no gate (per-product
      // render maps, headless screenshots, DocEditor embeds).
      //
      // Strict layer gating (no implicit companions) is deliberate:
      // with companions, every per-COA toggle showed the same 40+
      // baseline overlays and analysts saw "all COAs look the same" —
      // toggling COA-X must visibly change the threat picture.
      const affiliationByUnitId = buildBearerAffiliationIndex(
        data.entities?.features)
      const visibilityOpts = {
        enabledLayers,
        hiddenTypes,
        affiliationByUnitId,
        selectedBearerKgId,
      }
      const _filterBySource = (f) =>
        featureVisible(f && f.properties, visibilityOpts)

      // Separate military units from regular entities. mil_unit is its
      // own kind (handled by renderMilUnits / cluster path). Mil units
      // pass UNFILTERED: renderMilUnits applies this same predicate
      // per-feature so hovered/selected/locked units can bypass it
      // without a refetch.
      milVisPredicateRef.current = _filterBySource
      const allFeaturesRaw = (data.entities?.features || []).filter(_filterBySource)
      const milUnitFeatures = (data.entities?.features || []).filter(
        f => f.properties?.kind === 'mil_unit'
      )
      const milUnitFeaturesVisible = milUnitFeatures.filter(_filterBySource)
      const regularEntities = allFeaturesRaw
        .filter(f => f.properties?.kind !== 'mil_unit')
        .map(f => ({
          ...f,
          properties: { ...f.properties, id: f.id }
        }))

      // Update map data
      mapRef.current.getSource('entities')?.setData({
        type: 'FeatureCollection',
        features: regularEntities
      })

      // Render overlays as tactical graphics (always call to clear old
      // overlays even if empty). Server already filtered by schema kinds;
      // we additionally apply the enabledLayers/hiddenTypes filter so the
      // operations-map sidebar's per-source toggles take effect.
      // Selection stash for the SVG unit painter (selection halo).
      mapRef.current.__selectedUnitKgId = selectedBearerKgId || null

      // 3D envelope volumes for the selected unit — the pitched-view
      // form of its rings (terrain-aware deck slice, slant dome above).
      updateEnvelopeVolumes(
        mapRef.current, data.overlays?.features, selectedBearerKgId)

      const overlayFeatures = (data.overlays?.features || [])
        .filter(_filterBySource)
        .map(f => {
          // Analyst smoothing choice (edit panel): densify the
          // geometry through the shared Catmull-Rom sampler HERE, so
          // the MapLibre line/fill layers and the SVG drawers all
          // paint the same smoothed shape. The raw stated geometry is
          // preserved for editing (originalGeometry below).
          const smoothed = (f.properties?.smoothing === 'bezier'
            || f.properties?.attrs?.smoothing === 'bezier')
          return {
            ...f,
            geometry: smoothed
              ? smoothGeometryCoords(f.geometry)
              : f.geometry,
            properties: {
              ...f.properties, id: f.id,
              ...(smoothed
                ? { __rawGeometry: JSON.stringify(f.geometry) } : {}),
            },
          }
        })

      renderTacticalGraphics(overlayFeatures)

      // Apply MCOO doctrinal kind-segregated MapLibre paint
      // (terrain hatches, road network, hydrology casing, urban X-fill, NAI/TAI/
      // EA/OBJ polygon outlines, battle positions, boundaries, FSCM lines,
      // assembly areas, ROZ outlines). Also stashes feature lists for the
      // MapDoctrinalPaint SVG paint pass (AA chevrons, key terrain, choke
      // points, obstacle points, FSCM labels, BP labels, etc.).
      //
      // Runs in BOTH the analyst editor view and the headless render so
      // both surfaces show the same doctrinal MCOO/SITEMP/Threat Overlay paint.
      // The unified `tactical-graphics` source above keeps driving editor
      // click + edit handlers; the doctrinal MCOO sources here paint
      // doctrinal styling on top without interfering with hit-test.
      if (mapRef.current) {
        try {
          applyDoctrinalControlMeasures(mapRef.current, overlayFeatures)
        } catch (e) {
          clientWarn('geoAgent.applyDoctrinalControlMeasures', e)
        }
        // Schema-driven layer-visibility presets. The active render
        // config (stashed on the map instance by HeadlessRenderConfigStash
        // from URL primitives forwarded by intel_agent.tool_render_map)
        // carries the allowed layer id sets for both the OMT vector
        // basemap and the doctrinal-MCOO layer family. Null sets =
        // analyst-edit mode (every layer visible). NO product-type
        // switches in this function or in the preset appliers --- the
        // doctrinal decision lives in each product's schema.
        try {
          const _renderConfig = mapRef.current.__renderConfig || null
          applyProductLayerPreset(mapRef.current, _renderConfig?.doctrinalLayers || null)
          applyOmtBasemapPreset(mapRef.current, _renderConfig?.basemapLayers || null)
        } catch (e) {
          clientWarn('geoAgent.applyProductLayerPreset', e)
        }
        // Partition targets out of the regular entity stream for the
        // Threat-overlay-style target dot paint. Backend already filtered
        // by the schema's map_overlay_kinds, so if `target` isn't allowed
        // for this product, no target features made it through.
        const targetFeatures = allFeaturesRaw
          .filter(f => f.properties?.kind === 'target')
        mapRef.current.__milUnitFeatures = milUnitFeaturesVisible
        mapRef.current.__threatOverlayTargets = targetFeatures
      }

      // Render military units as symbol markers
      renderMilUnits(milUnitFeatures, selectEntity, updateEntityPosition)

      // Saved-route painter (REINTRODUCED 2026-07-06 under the
      // provenance rule that replaced the 2026-05-26 rip-out). The old
      // "blue river down the avenue of approach" bug was PIPELINE
      // routes auto-painting: intel_agent planned a scratch route per
      // avenue and the rows persisted. That emission is now stopped at
      // the source (intel_agent deletes its planning routes after
      // extracting geometry), so every route in data.routes is
      // ANALYST-authored and paints on every surface — live map and
      // headless/product renders alike. No renderer-side filtering.
      // Persistent sources only get setData here (layers were created
      // once by initSavedRouteLayers at map init).
      try {
        if (mapRef.current) {
          updateSavedRouteLayers(mapRef.current, data.routes || [], {
            setRouteResult, setShowRoutePanel, setRouteEditMode,
          })
        }
      } catch (err) {
        clientWarn('geoAgent.updateSavedRouteLayers', err)
      }

      setStats({
        entities: data.meta?.entity_count || 0,
        overlays: data.meta?.overlay_count || 0,
        milUnits: data.meta?.mil_unit_count || 0
      })

      addActivity(`Loaded ${regularEntities.length} entities, ${overlayFeatures.length} tactical overlays, ${milUnitFeatures.length} mil units`, 'success')

      // Deterministic data-loaded signal for MapDoctrinalPaint's SVG
      // paint pass. MapDoctrinalPaint repaints on idle/move/moveend/
      // sourcedata. When mil-sym-ts's isReady() poll runs long
      // (initMilSymRenderer loops up to 15s), the useEffect's listeners
      // attach AFTER loadMapState's setData calls have already fired
      // their sourcedata events. Events don't replay; the SVG paint
      // sees an empty `getSource('mil-units')._data` on its initial
      // repaint and never repaints again until the analyst pans the
      // camera — that's the "symbols only appear after you drag the
      // map" headless-render bug (no drag in a static screenshot →
      // no unit icons in the PNG).
      //
      // Custom map event => any listener attached later still receives
      // it once they're set up if loadMapState is re-invoked (editor
      // viewport refresh, after-save reload, etc.); MapDoctrinalPaint
      // also runs its initial repaint() at useEffect mount which reads
      // the now-populated source synchronously, so first-load is
      // covered for both timing orders.
      try {
        mapRef.current?.fire('pytho:data-loaded', {
          milUnits: milUnitFeatures.length,
          entities: regularEntities.length,
          overlays: overlayFeatures.length,
        })
      } catch (_e) {
        /* map torn down between setData and fire — non-fatal */
      }
    } catch (err) {
      console.error('Error loading map state:', err)
      addActivity(`Failed to load data: ${err.message}`, 'error')
    }
  }, [mapRef, api, mapId, renderMilUnits, renderTacticalGraphics, setStats, addActivity, enabledLayers, hiddenTypes, selectedBearerKgId, timelineAsOf, setTrackExtent])

  // Disable some map interactions during overlay draw mode only
  // (placement mode and entity dragging are handled in useMapEvents)
  useEffect(() => {
    if (!mapRef.current) return
    
    if (overlayDrawMode) {
      // During overlay drawing, disable double-click zoom to prevent accidental zooms
      mapRef.current.doubleClickZoom.disable()
    } else {
      mapRef.current.doubleClickZoom.enable()
    }
  }, [mapRef, overlayDrawMode])

  // Map controls
  const zoomIn = useCallback(() => mapRef.current?.zoomIn(), [mapRef])
  const zoomOut = useCallback(() => mapRef.current?.zoomOut(), [mapRef])
  const resetView = useCallback(() => {
    // Same camera-resolution chain as map init: the deployment's
    // /config defaultView (per-box DEFAULT_VIEW env) wins over the
    // neutral frontend fallback.
    const dv = appConfig?.defaultView
    mapRef.current?.flyTo({
      center: dv?.center || defaultCenter,
      zoom: dv?.zoom ?? defaultZoom,
    })
  }, [mapRef, appConfig, defaultCenter, defaultZoom])

  return {
    mapRef,
    mapContainerRef,
    drawRef,
    mapLoaded,
    milSymRendererReady,
    loadMapState,
    renderMilUnits,
    renderTacticalGraphics,
    zoomIn,
    zoomOut,
    resetView,
    MAP_STYLE,
    DRAW_STYLES
  }
}
