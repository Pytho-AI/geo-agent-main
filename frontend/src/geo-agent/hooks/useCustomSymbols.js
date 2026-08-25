/**
 * Custom-symbol map integration.
 *
 * Each `kind: 'custom_symbol'` feature in the entities source becomes one
 * maplibregl.Marker rendered as an HTML <img>. The marker DOM is the
 * live visual; the entities source is the persistent store. syncMarkers
 * reconciles them: create missing markers, remove stale ones, sync attrs
 * for markers that aren't mid-gesture.
 *
 * Two-level DOM is essential: `outer` is the element MapLibre owns (it
 * writes its positioning transform there). `inner` is ours — rotation
 * and drag-translate live on its transform. Without the split, our
 * writes clobber MapLibre's positioning.
 *
 * During a gesture, `inner.dataset.gesture = 'true'`. syncMarkers and
 * renderAttrs both honor the flag and leave the in-flight visual alone
 * until the gesture's commit clears it.
 */

import { useCallback, useEffect, useMemo, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'
import { CUSTOM_SYMBOL_DRAG_MIME } from '../components/CustomSymbolLibrary'

const DEFAULT_SIZE = 64
const MIN_SIZE = 16
const MAX_SIZE = 512
const DRAG_THRESHOLD = 4   // px before mousedown becomes a drag (else click)

const DELETE_ICON_SVG =
  '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" ' +
  'stroke="currentColor" stroke-width="3" stroke-linecap="round">' +
  '<line x1="6" y1="6" x2="18" y2="18"/>' +
  '<line x1="18" y1="6" x2="6" y2="18"/></svg>'

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

// ─── Pure DOM helpers (no hook state) ──────────────────────────────────

function renderAttrs(inner, img, attrs) {
  const size = clamp(Number(attrs.size) || DEFAULT_SIZE, MIN_SIZE, MAX_SIZE)
  const rotation = Number(attrs.rotation) || 0
  img.style.width = `${size}px`
  img.style.height = 'auto'
  inner.dataset.size = String(size)
  inner.dataset.rotation = String(rotation)
  if (inner.dataset.gesture !== 'true') {
    inner.style.transform = `rotate(${rotation}deg)`
  }
}

function makeHandle(cls, cursor, html) {
  const h = document.createElement('div')
  h.className = `custom-symbol-handle ${cls}`
  h.style.cursor = cursor
  if (html) h.innerHTML = html
  return h
}

function ensureHandles(inner) {
  if (inner.querySelector('.custom-symbol-handle')) return
  inner.classList.add('selected')
  inner.appendChild(makeHandle('handle-resize-se', 'nwse-resize'))
  inner.appendChild(makeHandle('handle-rotate', 'crosshair'))
  inner.appendChild(makeHandle('handle-delete', 'pointer', DELETE_ICON_SVG))
}

function removeHandles(inner) {
  inner.querySelectorAll('.custom-symbol-handle').forEach(h => h.remove())
  inner.classList.remove('selected')
}

// Optimistic source patch: rewrite the entities source so that any
// sourcedata event before the server-confirmed refresh reads consistent
// data and doesn't snap the marker back to old values.
function patchEntityInSource(map, entityId, mutate) {
  const src = map.getSource('entities')
  const data = src && src._data
  if (!data?.features) return
  src.setData({
    ...data,
    features: data.features.map(f =>
      (f.id || f.properties?.id) === entityId ? mutate(f) : f
    ),
  })
}


export function useCustomSymbols() {
  const {
    mapRef, apiUrl, mapId, userId, mapLoaded,
    customSymbols, customSymbolMarkersRef,
    selectedCustomSymbolEntityId, setSelectedCustomSymbolEntityId,
    addActivity, triggerMapRefresh, requestConfirm,
  } = useGeoAgent()

  // One API client per (apiUrl, userId), not one per render — otherwise every
  // downstream useCallback that lists `api` as a dep churns each render.
  // userId is appended to every /entities POST so the backend records who
  // placed each custom-symbol entity.
  const api = useMemo(() => createApiClient(apiUrl, userId), [apiUrl, userId])

  // Latest library list, accessible from synchronous DOM handlers
  // without rebinding them on each customSymbols change.
  const customSymbolsRef = useRef(customSymbols)
  customSymbolsRef.current = customSymbols

  // ─── Drop from library → create entity at the cursor position ────────
  const handleMapDrop = useCallback(async (e) => {
    const map = mapRef.current
    if (!map) return
    const symbolId =
      e.dataTransfer.getData(CUSTOM_SYMBOL_DRAG_MIME) ||
      e.dataTransfer.getData('text/plain')
    if (!symbolId) return
    e.preventDefault()

    const canvasRect = map.getCanvas().getBoundingClientRect()
    const cx = e.clientX - canvasRect.left
    const cy = e.clientY - canvasRect.top

    const lib = customSymbolsRef.current.find(s => s.id === symbolId)
    const initialSize = lib?.width
      ? clamp(lib.width, MIN_SIZE, MAX_SIZE)
      : DEFAULT_SIZE

    try {
      const { lng, lat } = map.unproject([cx, cy])
      await api.createEntity(mapId, {
        kind: 'custom_symbol',
        geom: { type: 'Point', coordinates: [lng, lat] },
        attrs: {
          custom_symbol_id: symbolId,
          name: lib?.name || 'Custom symbol',
          size: initialSize,
          rotation: 0,
        },
      })
      addActivity(`Placed ${lib?.name || 'symbol'}`, 'success')
      // Pull the new entity into the source now — without this, the
      // marker only appears on the next moveend-driven loadMapState.
      triggerMapRefresh?.()
    } catch (err) {
      addActivity(`Failed to place symbol: ${err.message}`, 'error')
    }
  }, [mapRef, mapId, api, addActivity, triggerMapRefresh])

  // ─── Marker DOM ──────────────────────────────────────────────────────
  const buildMarker = useCallback((id, attrs, [lng, lat]) => {
    const outer = document.createElement('div')
    outer.className = 'custom-symbol-marker'
    outer.dataset.entityId = id

    const inner = document.createElement('div')
    inner.className = 'custom-symbol-marker-inner'
    outer.appendChild(inner)

    const img = document.createElement('img')
    img.className = 'custom-symbol-marker-img'
    img.draggable = false
    img.src = `${apiUrl}/custom-symbols/${attrs.custom_symbol_id}/file`
    img.alt = attrs.name || 'Custom symbol'
    inner.appendChild(img)

    const marker = new maplibregl.Marker({ element: outer, anchor: 'center', draggable: false })
      .setLngLat([lng, lat])
      .addTo(mapRef.current)

    return { marker, outer, inner, img }
  }, [apiUrl, mapRef])

  // ─── Delete (handle click + keyboard) ────────────────────────────────
  const deleteSymbol = useCallback(async (id) => {
    if (!(await requestConfirm({ title: 'Delete Symbol', message: 'Delete this placed symbol from the map?', confirmLabel: 'Delete' }))) return
    try {
      await api.deleteEntity(id)
      const entry = customSymbolMarkersRef.current.get(id)
      if (entry) {
        entry.marker.remove()
        customSymbolMarkersRef.current.delete(id)
      }
      setSelectedCustomSymbolEntityId(null)
      addActivity('Deleted custom symbol', 'success')
    } catch (err) {
      addActivity(`Delete failed: ${err.message}`, 'error')
    }
  }, [api, customSymbolMarkersRef, setSelectedCustomSymbolEntityId, addActivity, requestConfirm])

  // ─── Gesture factory: shared by drag / resize / rotate ───────────────
  // The caller supplies onMove (live DOM update) and onCommit (server write).
  // We hold `inner.dataset.gesture` set until the commit resolves, so
  // syncMarkers skips this marker for the full in-flight window.
  const startGesture = useCallback((inner, downEvt, onMove, onCommit) => {
    inner.dataset.gesture = 'true'
    const onMouseMove = (e) => onMove(e)
    const onMouseUp = async (e) => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
      try {
        await onCommit(e)
      } catch (err) {
        addActivity(err.message || 'Gesture failed', 'error')
      } finally {
        delete inner.dataset.gesture
      }
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    downEvt.preventDefault()
    downEvt.stopPropagation()
  }, [addActivity])

  // Send full merged attrs on every update — backend's PUT replaces the
  // attrs JSONB column entirely, so partial payloads wipe sibling keys
  // (custom_symbol_id, name, rotation, …).
  const mergeAttrs = (entry, patch) => ({ ...(entry.attrs || {}), ...patch })

  // ─── Drag ────────────────────────────────────────────────────────────
  const beginDrag = useCallback((entry, id, downEvt) => {
    const { marker, inner } = entry
    const map = mapRef.current
    const startX = downEvt.clientX
    const startY = downEvt.clientY
    const startRect = inner.getBoundingClientRect()
    const baseTransform = `rotate(${inner.dataset.rotation || 0}deg)`
    let moved = false

    const onMove = (e) => {
      const dx = e.clientX - startX
      const dy = e.clientY - startY
      if (!moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return
      moved = true
      inner.style.transform = `translate(${dx}px, ${dy}px) ${baseTransform}`
    }

    const onCommit = async (e) => {
      if (!moved) {
        inner.style.transform = baseTransform
        setSelectedCustomSymbolEntityId(id)
        return
      }
      const vx = startRect.left + startRect.width / 2 + (e.clientX - startX)
      const vy = startRect.top + startRect.height / 2 + (e.clientY - startY)
      const canvasRect = map.getCanvas().getBoundingClientRect()
      const pos = map.unproject([vx - canvasRect.left, vy - canvasRect.top])
      if (!Number.isFinite(pos?.lng) || !Number.isFinite(pos?.lat)) {
        inner.style.transform = baseTransform
        throw new Error('Invalid drop position')
      }

      // setLngLat updates MapLibre's transform on `outer`; clearing the
      // inner translate doesn't touch that — so the visual lands at the
      // new position in the same frame, no flash through the origin.
      marker.setLngLat([pos.lng, pos.lat])
      inner.style.transform = baseTransform

      patchEntityInSource(map, id, f => ({
        ...f,
        geometry: { ...f.geometry, coordinates: [pos.lng, pos.lat] },
      }))
      await api.updateEntity(id, {
        geom: { type: 'Point', coordinates: [pos.lng, pos.lat] },
      })
    }

    startGesture(inner, downEvt, onMove, onCommit)
  }, [api, mapRef, setSelectedCustomSymbolEntityId, startGesture])

  // ─── Resize (SE corner) ──────────────────────────────────────────────
  const beginResize = useCallback((entry, id, downEvt) => {
    const { inner, img } = entry
    const startW = img.getBoundingClientRect().width
    const startX = downEvt.clientX
    const startY = downEvt.clientY
    let size = startW

    const onMove = (e) => {
      const delta = ((e.clientX - startX) + (e.clientY - startY)) / 2
      size = clamp(startW + delta, MIN_SIZE, MAX_SIZE)
      img.style.width = `${size}px`
      inner.dataset.size = String(Math.round(size))
    }
    const onCommit = async () => {
      const finalSize = Math.round(size)
      const attrs = mergeAttrs(entry, { size: finalSize })
      entry.attrs = attrs
      patchEntityInSource(mapRef.current, id, f => ({
        ...f, properties: { ...(f.properties || {}), size: finalSize },
      }))
      await api.updateEntity(id, { attrs })
    }

    startGesture(inner, downEvt, onMove, onCommit)
  }, [api, mapRef, startGesture])

  // ─── Rotate (top handle) ─────────────────────────────────────────────
  const beginRotate = useCallback((entry, id, downEvt) => {
    const { inner, img } = entry
    const r = img.getBoundingClientRect()
    const cx = r.left + r.width / 2
    const cy = r.top + r.height / 2
    const startAngle = Math.atan2(downEvt.clientY - cy, downEvt.clientX - cx)
    const startRotation = Number(inner.dataset.rotation || 0)
    let rotation = startRotation

    const onMove = (e) => {
      const a = Math.atan2(e.clientY - cy, e.clientX - cx)
      rotation = (startRotation + (a - startAngle) * (180 / Math.PI)) % 360
      inner.style.transform = `rotate(${rotation}deg)`
      inner.dataset.rotation = String(rotation)
    }
    const onCommit = async () => {
      const finalRotation = Math.round(rotation * 10) / 10
      const attrs = mergeAttrs(entry, { rotation: finalRotation })
      entry.attrs = attrs
      patchEntityInSource(mapRef.current, id, f => ({
        ...f, properties: { ...(f.properties || {}), rotation: finalRotation },
      }))
      await api.updateEntity(id, { attrs })
    }

    startGesture(inner, downEvt, onMove, onCommit)
  }, [api, mapRef, startGesture])

  // ─── One mousedown handler per marker, dispatching by target. ────────
  const bindGestures = useCallback((entry, id) => {
    const { outer } = entry

    outer.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return
      const handle = e.target.closest('.custom-symbol-handle')
      if (handle?.classList.contains('handle-delete')) return  // click-only
      if (handle?.classList.contains('handle-resize-se')) beginResize(entry, id, e)
      else if (handle?.classList.contains('handle-rotate')) beginRotate(entry, id, e)
      else beginDrag(entry, id, e)
    })

    outer.addEventListener('click', (e) => {
      const handle = e.target.closest('.custom-symbol-handle')
      if (handle?.classList.contains('handle-delete')) {
        e.stopPropagation()
        deleteSymbol(id)
      }
    })
  }, [beginDrag, beginResize, beginRotate, deleteSymbol])

  // ─── Reconcile markers against the entities source ───────────────────
  const syncMarkers = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    const src = map.getSource('entities')
    if (!src?._data?.features) return

    const markers = customSymbolMarkersRef.current
    const seen = new Set()

    for (const feat of src._data.features) {
      if (feat.properties?.kind !== 'custom_symbol') continue
      if (feat.geometry?.type !== 'Point') continue
      const id = feat.id || feat.properties.id
      if (!id) continue
      // Stale entities from before the attrs-merge fix may have lost
      // their custom_symbol_id; skip them rather than render a broken img.
      if (!feat.properties.custom_symbol_id) continue
      seen.add(id)

      const attrs = feat.properties
      const coords = feat.geometry.coordinates

      let entry = markers.get(id)
      if (!entry) {
        entry = buildMarker(id, attrs, coords)
        entry.attrs = attrs
        renderAttrs(entry.inner, entry.img, attrs)
        bindGestures(entry, id)
        markers.set(id, entry)
      } else if (entry.inner.dataset.gesture !== 'true') {
        entry.marker.setLngLat(coords)
        entry.attrs = attrs
        renderAttrs(entry.inner, entry.img, attrs)
      }
    }

    for (const [id, entry] of markers.entries()) {
      if (!seen.has(id)) {
        entry.marker.remove()
        markers.delete(id)
      }
    }
  }, [mapRef, customSymbolMarkersRef, buildMarker, bindGestures])

  // ─── Effects ─────────────────────────────────────────────────────────

  // Sync on entities source updates + deselect on map click.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    const onSource = (e) => {
      if (e.sourceId === 'entities' && e.isSourceLoaded) syncMarkers()
    }
    const onMapClick = () => setSelectedCustomSymbolEntityId(null)
    map.on('sourcedata', onSource)
    map.on('click', onMapClick)
    syncMarkers()
    return () => {
      map.off('sourcedata', onSource)
      map.off('click', onMapClick)
    }
  }, [mapRef, mapLoaded, syncMarkers, setSelectedCustomSymbolEntityId])

  // Toggle handles when selection changes.
  useEffect(() => {
    for (const [id, entry] of customSymbolMarkersRef.current.entries()) {
      if (id === selectedCustomSymbolEntityId) ensureHandles(entry.inner)
      else removeHandles(entry.inner)
    }
  }, [selectedCustomSymbolEntityId, customSymbolMarkersRef])

  // Delete / Backspace removes the selected symbol.
  useEffect(() => {
    if (!selectedCustomSymbolEntityId) return
    const onKey = (e) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      const t = e.target
      const tag = (t?.tagName || '').toLowerCase()
      if (tag === 'input' || tag === 'textarea' || t?.isContentEditable) return
      e.preventDefault()
      deleteSymbol(selectedCustomSymbolEntityId)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedCustomSymbolEntityId, deleteSymbol])

  // Cleanup on unmount.
  useEffect(() => {
    const markersRef = customSymbolMarkersRef
    return () => {
      for (const entry of markersRef.current.values()) entry.marker.remove()
      markersRef.current.clear()
    }
  }, [customSymbolMarkersRef])

  return { handleMapDrop }
}
