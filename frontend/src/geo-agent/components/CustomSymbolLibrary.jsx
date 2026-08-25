/**
 * CustomSymbolLibrary - sidebar panel for user-uploaded PNG/SVG icons.
 * Users upload here, then drag any tile onto the map to place an instance.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'

export const CUSTOM_SYMBOL_DRAG_MIME = 'application/x-custom-symbol-id'

export function CustomSymbolLibrary() {
  const {
    apiUrl,
    userId,
    customSymbols,
    customSymbolsLoaded,
    loadCustomSymbols,
    setCustomSymbols,
    addActivity,
    showCustomSymbolLibrary,
    setShowCustomSymbolLibrary,
    requestConfirm,
  } = useGeoAgent()

  // userId is stamped onto every uploaded symbol's `created_by` row so the
  // library can show who contributed which icon.
  const api = useMemo(() => createApiClient(apiUrl, userId), [apiUrl, userId])
  const fileInputRef = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (showCustomSymbolLibrary && !customSymbolsLoaded) loadCustomSymbols()
  }, [showCustomSymbolLibrary, customSymbolsLoaded, loadCustomSymbols])

  if (!showCustomSymbolLibrary) return null

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return
    setUploading(true)
    setError(null)
    try {
      for (const file of files) {
        const record = await api.uploadCustomSymbol(file)
        setCustomSymbols(prev => [record, ...prev])
        addActivity(`Uploaded symbol: ${file.name}`, 'success')
      }
    } catch (err) {
      setError(err.message)
      addActivity(`Symbol upload failed: ${err.message}`, 'error')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleDelete = async (id, name) => {
    if (!(await requestConfirm({ title: 'Delete Symbol', message: `Delete "${name}"? Existing placements on maps will lose their icon.`, confirmLabel: 'Delete' }))) return
    try {
      await api.deleteCustomSymbol(id)
      setCustomSymbols(prev => prev.filter(s => s.id !== id))
      addActivity(`Deleted symbol: ${name}`, 'success')
    } catch (err) {
      addActivity(`Failed to delete symbol: ${err.message}`, 'error')
    }
  }

  const handleDragStart = (e, symbol) => {
    e.dataTransfer.setData(CUSTOM_SYMBOL_DRAG_MIME, symbol.id)
    e.dataTransfer.setData('text/plain', symbol.id) // fallback
    e.dataTransfer.effectAllowed = 'copy'
    // Use the actual icon as the drag image so the user sees what's being placed.
    const img = new Image()
    img.src = api.customSymbolUrl(symbol.id)
    try {
      e.dataTransfer.setDragImage(img, 24, 24)
    } catch {
      // Some browsers/SVGs can't be used as drag images — silently fall back.
    }
  }

  return (
    <div className="custom-symbol-library-panel">
      <div className="custom-symbol-library-header">
        <h3>Custom Symbols</h3>
        <button onClick={() => setShowCustomSymbolLibrary(false)} title="Close">×</button>
      </div>

      <label className={`upload-area ${uploading ? 'disabled' : ''}`}>
        <input
          ref={fileInputRef}
          type="file"
          accept=".png,.svg,image/png,image/svg+xml"
          multiple
          onChange={handleUpload}
          disabled={uploading}
        />
        <div className="upload-icon">+</div>
        <div className="upload-text">
          {uploading ? 'Uploading...' : 'Upload PNG or SVG'}
        </div>
        <div className="upload-formats">Drag from grid below onto the map</div>
      </label>

      {error && <div className="response-box error">{error}</div>}

      <div className="custom-symbol-grid">
        {!customSymbolsLoaded && (
          <div className="custom-symbol-empty">Loading...</div>
        )}
        {customSymbolsLoaded && customSymbols.length === 0 && (
          <div className="custom-symbol-empty">No symbols yet. Upload one to get started.</div>
        )}
        {customSymbols.map(symbol => (
          <div
            key={symbol.id}
            className="custom-symbol-tile"
            draggable
            onDragStart={(e) => handleDragStart(e, symbol)}
            title={`${symbol.name} — drag onto the map`}
          >
            <img
              className="custom-symbol-thumb"
              src={api.customSymbolUrl(symbol.id)}
              alt={symbol.name}
              draggable={false}
            />
            <div className="custom-symbol-name">{symbol.name}</div>
            <button
              className="custom-symbol-delete"
              onClick={(e) => { e.stopPropagation(); handleDelete(symbol.id, symbol.name) }}
              title="Delete symbol"
            >×</button>
          </div>
        ))}
      </div>
    </div>
  )
}
