/**
 * Undo/redo stack for map operations (entity moves, overlay moves).
 *
 * Each entry records the object type, ID, old geometry, and new geometry
 * so operations can be reversed by calling the same update API.
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'

const MAX_STACK = 50

/**
 * @typedef {Object} UndoEntry
 * @property {'entity'|'overlay'} type
 * @property {string} id
 * @property {Object} oldGeom - GeoJSON geometry before the change
 * @property {Object} newGeom - GeoJSON geometry after the change
 */

export function useUndoStack() {
  const { apiUrl, userId, addActivity, triggerMapRefresh } = useGeoAgent()
  const api = createApiClient(apiUrl, userId)

  const [undoStack, setUndoStack] = useState([])
  const [redoStack, setRedoStack] = useState([])
  const [isApplying, setIsApplying] = useState(false)

  // Refs so keyboard handler always sees latest state
  const undoRef = useRef(undoStack)
  const redoRef = useRef(redoStack)
  const isApplyingRef = useRef(false)
  useEffect(() => { undoRef.current = undoStack }, [undoStack])
  useEffect(() => { redoRef.current = redoStack }, [redoStack])
  useEffect(() => { isApplyingRef.current = isApplying }, [isApplying])

  /**
   * Record a move operation so it can be undone later.
   */
  const pushUndo = useCallback((type, id, oldGeom, newGeom) => {
    setUndoStack(prev => [...prev.slice(-(MAX_STACK - 1)), { type, id, oldGeom, newGeom }])
    // Any new action clears the redo stack
    setRedoStack([])
  }, [])

  /**
   * Apply a geometry change via the API.
   */
  const applyGeom = useCallback(async (entry, geom) => {
    if (entry.type === 'entity') {
      if (geom.type === 'Point') {
        await api.updateEntity(entry.id, { geom })
      }
    } else if (entry.type === 'overlay') {
      await api.updateOverlay(entry.id, { geom })
    }
  }, [api])

  /**
   * Undo the most recent operation.
   */
  const undo = useCallback(async () => {
    if (isApplyingRef.current || undoRef.current.length === 0) return
    setIsApplying(true)
    try {
      const entry = undoRef.current[undoRef.current.length - 1]
      await applyGeom(entry, entry.oldGeom)
      setUndoStack(prev => prev.slice(0, -1))
      setRedoStack(prev => [...prev, entry])
      addActivity('Undo: moved back', 'info')
      triggerMapRefresh()
    } catch (err) {
      addActivity(`Undo failed: ${err.message}`, 'error')
    } finally {
      setIsApplying(false)
    }
  }, [applyGeom, addActivity, triggerMapRefresh])

  /**
   * Redo the most recently undone operation.
   */
  const redo = useCallback(async () => {
    if (isApplyingRef.current || redoRef.current.length === 0) return
    setIsApplying(true)
    try {
      const entry = redoRef.current[redoRef.current.length - 1]
      await applyGeom(entry, entry.newGeom)
      setRedoStack(prev => prev.slice(0, -1))
      setUndoStack(prev => [...prev, entry])
      addActivity('Redo: moved forward', 'info')
      triggerMapRefresh()
    } catch (err) {
      addActivity(`Redo failed: ${err.message}`, 'error')
    } finally {
      setIsApplying(false)
    }
  }, [applyGeom, addActivity, triggerMapRefresh])

  /**
   * Keyboard shortcut listener (Ctrl/Cmd+Z, Ctrl/Cmd+Y, Ctrl/Cmd+Shift+Z).
   */
  useEffect(() => {
    const handler = (e) => {
      const isMod = e.metaKey || e.ctrlKey
      if (!isMod) return

      // Don't intercept when focus is inside an input/textarea/select
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if (e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        undo()
      } else if (e.key === 'z' && e.shiftKey) {
        e.preventDefault()
        redo()
      } else if (e.key === 'y') {
        e.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undo, redo])

  return {
    pushUndo,
    undo,
    redo,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    isApplying,
  }
}
