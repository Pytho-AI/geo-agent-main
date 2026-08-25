/**
 * Symbol picker modal for selecting military unit symbols
 * Uses backend API for all symbol data and search
 */

import React, { useEffect, useState, useMemo } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createMilsymbolPreview } from '../utils/symbols'

/**
 * SymbolPicker - Modal for browsing and selecting military symbols
 */
export function SymbolPicker() {
  const {
    showSymbolPicker,
    setShowSymbolPicker,
    symbolPickerSearch,
    setSymbolPickerSearch,
    symbolPickerCategory,
    setSymbolPickerCategory,
    symbolPickerCallback,
    setSymbolPickerCallback,
    appConfig,
    loadSymbols,
    searchSymbols: searchSymbolsApi,
    symbols: backendSymbols,
    symbolsLoaded,
    symbolsLoading
  } = useGeoAgent()

  // Local search results state
  const [searchResults, setSearchResults] = useState([])
  const [isSearching, setIsSearching] = useState(false)

  // Load symbols when picker opens
  useEffect(() => {
    if (showSymbolPicker && !symbolsLoaded && !symbolsLoading) {
      loadSymbols()
    }
  }, [showSymbolPicker, symbolsLoaded, symbolsLoading, loadSymbols])

  // Search symbols when search text changes
  useEffect(() => {
    if (!showSymbolPicker) return
    
    const search = async () => {
      if (symbolPickerSearch.length >= 2) {
        setIsSearching(true)
        const { results } = await searchSymbolsApi(symbolPickerSearch, null, 100)
        setSearchResults(results)
        setIsSearching(false)
      } else {
        setSearchResults([])
      }
    }
    
    // Debounce search
    const timer = setTimeout(search, 200)
    return () => clearTimeout(timer)
  }, [symbolPickerSearch, showSymbolPicker, searchSymbolsApi])

  // Get available symbol sets from config
  const symbolSets = useMemo(() => {
    return appConfig?.symbolSets || []
  }, [appConfig])

  // Process backend symbols into categories (grouped by symbol set)
  const categories = useMemo(() => {
    if (backendSymbols.length === 0) return []
    
    const cats = {}
    backendSymbols.forEach(symbol => {
      const setName = symbol.symbolSetName || 'Other'
      const setCode = symbol.symbolSet || 'other'
      if (!cats[setCode]) {
        cats[setCode] = {
          id: setCode,
          name: setName,
          entities: []
        }
      }
      cats[setCode].entities.push({
        name: symbol.name,
        code: symbol.code,
        sidc: symbol.sidc,
        entity: symbol.entity,
        entityType: symbol.entityType,
        entitySubtype: symbol.entitySubtype,
        keywords: symbol.keywords || [],
        symbolSet: symbol.symbolSet,
        symbolSetName: symbol.symbolSetName
      })
    })
    return Object.values(cats)
  }, [backendSymbols])

  if (!showSymbolPicker) return null

  const handleClose = () => {
    setShowSymbolPicker(false)
    setSymbolPickerSearch('')
    setSymbolPickerCategory('all')
    setSearchResults([])
    setSymbolPickerCallback(null)
  }

  const handleSelect = (entity) => {
    // Get the most specific display name for the symbol
    const displayName = entity.entitySubtype || entity.entityType || entity.entity || entity.name
    
    // Call the callback with selected symbol data
    if (symbolPickerCallback) {
      symbolPickerCallback({
        unitType: entity.code,
        symbolSet: entity.symbolSet || '10',
        symbolName: displayName
      })
    }
    handleClose()
  }

  // Use search results if searching, otherwise show by category
  let displayEntities = []
  
  if (symbolPickerSearch.length >= 2) {
    // Use backend search results
    displayEntities = searchResults.map(s => ({
      name: s.name,
      code: s.code,
      sidc: s.sidc,
      entity: s.entity,
      entityType: s.entityType,
      entitySubtype: s.entitySubtype,
      categoryName: s.symbolSetName,
      symbolSet: s.symbolSet
    }))
  } else {
    // Show all in selected category
    const filteredCategories = symbolPickerCategory === 'all' 
      ? categories 
      : categories.filter(c => c.id === symbolPickerCategory)
    
    displayEntities = filteredCategories.flatMap(cat => 
      cat.entities.map(entity => ({ ...entity, categoryName: cat.name }))
    )
  }

  return (
    <div className="symbol-picker-overlay" onClick={handleClose}>
      <div className="symbol-picker-modal" onClick={(e) => e.stopPropagation()}>
        <div className="symbol-picker-header">
          <h3>Select Symbol {symbolsLoading && '(loading...)'}</h3>
          <button onClick={handleClose}>×</button>
        </div>
        
        <div className="symbol-picker-search">
          <input
            type="text"
            placeholder="Search all symbols..."
            value={symbolPickerSearch}
            onChange={(e) => setSymbolPickerSearch(e.target.value)}
            autoFocus
          />
          {isSearching && <span className="search-indicator">Searching...</span>}
        </div>
        
        <div className="symbol-picker-body">
          <div className="symbol-picker-categories">
            <button
              className={symbolPickerCategory === 'all' ? 'active' : ''}
              onClick={() => setSymbolPickerCategory('all')}
            >
              All ({backendSymbols.length || 'local'})
            </button>
            {categories.map(cat => (
              <button
                key={cat.id}
                className={symbolPickerCategory === cat.id ? 'active' : ''}
                onClick={() => setSymbolPickerCategory(cat.id)}
                title={`${cat.entities.length} symbols`}
              >
                {cat.name}
              </button>
            ))}
          </div>
          
          <div className="symbol-picker-grid">
            {displayEntities.length === 0 ? (
              <div className="no-results">
                {isSearching ? 'Searching...' : symbolsLoading ? 'Loading symbols...' : 'No symbols found'}
              </div>
            ) : (
              displayEntities.slice(0, 200).map((entity, idx) => {
                const svgHtml = createMilsymbolPreview(entity.code, { size: 35, symbolSet: entity.symbolSet })
                
                return (
                  <div
                    key={`${entity.code}-${idx}`}
                    className="symbol-picker-item"
                    onClick={() => handleSelect(entity)}
                    title={`${entity.entity}${entity.entityType ? ' > ' + entity.entityType : ''}${entity.entitySubtype ? ' > ' + entity.entitySubtype : ''}\nCode: ${entity.code}${entity.categoryName ? '\nSet: ' + entity.categoryName : ''}`}
                  >
                    <div 
                      className="symbol-picker-icon"
                      dangerouslySetInnerHTML={{ 
                        __html: svgHtml || '<div class="symbol-placeholder">?</div>' 
                      }}
                    />
                    <div className="symbol-picker-name">{entity.name}</div>
                  </div>
                )
              })
            )}
            {displayEntities.length > 200 && (
              <div className="more-results">
                Showing 200 of {displayEntities.length} results. Refine your search.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
