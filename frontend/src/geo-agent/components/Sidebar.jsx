/**
 * Sidebar component with stats, file upload, NL query, and activity log
 */

import React from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'

/**
 * Sidebar component
 * @param {Object} props
 * @param {string} props.title - Title to display (default: "Geo-Agent Demo")
 * @param {string} props.subtitle - Subtitle to display
 * @param {Function} props.onDataLoaded - Callback when data is loaded
 */
export function Sidebar({ 
  title = 'Geo-Agent Demo', 
  subtitle = 'AI-powered geo-spatial intelligence',
  onDataLoaded
}) {
  const {
    apiUrl,
    mapId,
    stats,
    activities,
    addActivity,
    loading,
    setLoading,
    error,
    setError,
    response,
    setResponse,
    query,
    setQuery,
    mapRef
  } = useGeoAgent()

  const api = createApiClient(apiUrl)

  // Handle file upload
  const handleFileUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return

    setLoading(true)
    addActivity(`Uploading ${file.name}...`)

    try {
      const { id } = await api.uploadArtifact(mapId, file)
      addActivity('Processing file...')

      const result = await api.ingestArtifact(id)
      addActivity(`Created ${result.entities_created} entities, ${result.overlays_created} overlays`, 'success')

      if (onDataLoaded) {
        onDataLoaded()
      }
    } catch (err) {
      addActivity(`Error: ${err.message}`, 'error')
      setError(err.message)
    } finally {
      setLoading(false)
      e.target.value = ''
    }
  }

  // Handle natural language query
  const handleQuery = async () => {
    if (!query.trim() || !mapRef.current) return

    setLoading(true)
    setResponse(null)
    setError(null)
    addActivity(`Query: "${query}"`)

    try {
      const bounds = mapRef.current.getBounds()
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]

      const data = await api.nlQuery(mapId, query, bbox)

      setResponse(data)
      addActivity(`Found ${data.entities?.length || 0} entities`, 'success')
    } catch (err) {
      setError(err.message)
      addActivity(`Error: ${err.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>

      <div className="sidebar-content">
        {/* Stats */}
        <div className="section">
          <div className="section-title">Current View</div>
          <div className="stats stats-three">
            <div className="stat-card">
              <div className="stat-value">{stats.entities}</div>
              <div className="stat-label">Entities</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.overlays}</div>
              <div className="stat-label">Overlays</div>
            </div>
            <div className="stat-card mil-unit-stat">
              <div className="stat-value">{stats.milUnits}</div>
              <div className="stat-label">Mil Units</div>
            </div>
          </div>
        </div>

        {/* File Upload */}
        <div className="section">
          <div className="section-title">Upload Data</div>
          <label className="upload-area">
            <input
              type="file"
              accept=".geojson,.json,.shp,.zip"
              onChange={handleFileUpload}
              disabled={loading}
            />
            <div className="upload-icon">📁</div>
            <div className="upload-text">
              {loading ? 'Processing...' : 'Click to upload'}
            </div>
            <div className="upload-formats">GeoJSON, Shapefile (.zip)</div>
          </label>
        </div>

        {/* NL Query */}
        <div className="section">
          <div className="section-title">Ask a Question</div>
          <div className="query-input">
            <input
              type="text"
              placeholder="What's in this area?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
              disabled={loading}
            />
            <button onClick={handleQuery} disabled={loading}>
              {loading ? '...' : 'Ask'}
            </button>
          </div>

          {response && (
            <div className="response-box">{response.answer}</div>
          )}

          {error && (
            <div className="response-box error">{error}</div>
          )}
        </div>

        {/* Activity Log */}
        <div className="section">
          <div className="section-title">Activity</div>
          <div className="activity-log">
            {activities.map((activity, i) => (
              <div key={i} className={`activity-item ${activity.type}`}>
                <span className="time">{activity.time}</span>
                <div>{activity.message}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
