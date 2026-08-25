/**
 * Chat hook for natural language map operations
 * 
 * Manages chat state, message history, and the approval flow
 * for map modifications via natural language.
 */

import { useState, useCallback, useRef } from 'react'
import { useGeoAgent } from '../GeoAgentProvider'
import { createApiClient } from '../utils/api'

/**
 * Message types in the chat
 */
export const MessageType = {
  USER: 'user',
  ASSISTANT: 'assistant',
  PENDING: 'pending',  // Waiting for approval
  SUCCESS: 'success',  // Operation completed
  ERROR: 'error'
}

/**
 * Hook for managing chat functionality with the geo agent
 * 
 * @returns {Object} Chat state and methods
 */
export function useChat() {
  const {
    apiUrl,
    mapId,
    mapRef,
    addActivity,
    setRouteDiagnostic,
    userId,
  } = useGeoAgent()

  // userId threads into every chat + geoops call — it is the
  // created_by attribution on agent-created content (a client built
  // without it stamped 'unknown' on everything the agent placed).
  const api = createApiClient(apiUrl, userId)
  
  // Chat state
  const [messages, setMessages] = useState([])
  const [pendingOps, setPendingOps] = useState(null)
  const [pendingMessageId, setPendingMessageId] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  
  // Message ID counter
  const messageIdRef = useRef(0)
  
  /**
   * Generate a unique message ID
   */
  const generateMessageId = useCallback(() => {
    messageIdRef.current += 1
    return `msg-${Date.now()}-${messageIdRef.current}`
  }, [])
  
  /**
   * Get the current viewport bounding box
   */
  const getBbox = useCallback(() => {
    if (!mapRef.current) return null
    const bounds = mapRef.current.getBounds()
    return [
      bounds.getWest(),
      bounds.getSouth(),
      bounds.getEast(),
      bounds.getNorth()
    ]
  }, [mapRef])
  
  /**
   * Get conversation history in the format expected by the API
   */
  const getConversationHistory = useCallback(() => {
    return messages
      .filter(m => m.type === MessageType.USER || m.type === MessageType.ASSISTANT)
      .map(m => ({
        role: m.type === MessageType.USER ? 'user' : 'assistant',
        content: m.content
      }))
  }, [messages])
  
  /**
   * Add a message to the chat
   */
  const addMessage = useCallback((type, content, extra = {}) => {
    const id = generateMessageId()
    const message = {
      id,
      type,
      content,
      timestamp: new Date().toISOString(),
      ...extra
    }
    setMessages(prev => [...prev, message])
    return id
  }, [generateMessageId])
  
  /**
   * Update an existing message
   */
  const updateMessage = useCallback((messageId, updates) => {
    setMessages(prev => prev.map(m => 
      m.id === messageId ? { ...m, ...updates } : m
    ))
  }, [])
  
  /**
   * Send a message to the agent
   */
  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || isLoading) return
    
    setError(null)
    setIsLoading(true)
    
    // Add user message
    addMessage(MessageType.USER, text)
    
    try {
      const bbox = getBbox()
      const history = getConversationHistory()
      
      // Call the chat API
      const response = await api.nlChat(mapId, text, bbox, history)
      
      if (response.clarification_needed) {
        // Agent needs more info
        addMessage(MessageType.ASSISTANT, response.message)
      } else if (response.requires_approval && response.proposed_ops?.length > 0) {
        // Agent has proposed operations - wait for approval
        const msgId = addMessage(MessageType.PENDING, response.message, {
          proposedOps: response.proposed_ops
        })
        setPendingOps(response.proposed_ops)
        setPendingMessageId(msgId)
      } else {
        // Simple response, no operations
        addMessage(MessageType.ASSISTANT, response.message)
      }
      
      addActivity(`Chat: "${text.substring(0, 30)}${text.length > 30 ? '...' : ''}"`)
      
    } catch (err) {
      console.error('Chat error:', err)
      setError(err.message)
      addMessage(MessageType.ERROR, `Error: ${err.message}`)
      addActivity(`Chat error: ${err.message}`, 'error')
    } finally {
      setIsLoading(false)
    }
  }, [api, mapId, isLoading, addMessage, getBbox, getConversationHistory, addActivity])
  
  /**
   * Approve pending operations
   */
  const approveOps = useCallback(async () => {
    if (!pendingOps || pendingOps.length === 0) return
    
    setIsLoading(true)
    setError(null)
    
    try {
      // Execute the operations
      const response = await api.executeGeoOps(mapId, pendingOps)
      
      // Check results
      const allSuccess = response.results?.every(r => r.success) ?? false
      const successCount = response.results?.filter(r => r.success).length ?? 0
      const failCount = response.results?.filter(r => !r.success).length ?? 0
      
      // Update the pending message to show success
      if (pendingMessageId) {
        if (allSuccess) {
          updateMessage(pendingMessageId, {
            type: MessageType.SUCCESS,
            approved: true
          })
        } else {
          const errors = response.results
            ?.filter(r => !r.success)
            .map(r => r.error)
            .join(', ')
          updateMessage(pendingMessageId, {
            type: MessageType.ERROR,
            content: `Partial failure: ${successCount} succeeded, ${failCount} failed. Errors: ${errors}`
          })
        }
      }
      
      // Check for route planning failures — show RouteFailureModal
      if (response.results) {
        const routeFailure = response.results.find(r => r.op === 'create_route' && !r.success)
        if (routeFailure && setRouteDiagnostic) {
          setRouteDiagnostic({
            message: routeFailure.error || 'Route planning failed',
            diagnostic: routeFailure.detail || null,
          })
        }
      }

      // Log to activity feed (no chat message needed)
      if (allSuccess) {
        addActivity(`Approved: ${successCount} operation(s)`, 'success')
        
        // Fly to the created entities/routes if they have coordinates
        if (pendingOps.length > 0 && mapRef?.current) {
          const coords = pendingOps
            .flatMap(op => {
              // Route ops have start_geom/end_geom instead of geom
              if (op.op === 'create_route') {
                const pts = []
                if (op.start_geom?.coordinates) pts.push(op.start_geom.coordinates)
                if (op.end_geom?.coordinates) pts.push(op.end_geom.coordinates)
                return pts
              }
              if (!op.geom?.coordinates) return []
              const geom = op.geom
              if (geom.type === 'Point') return [geom.coordinates]
              if (geom.type === 'LineString') return [geom.coordinates[0]]
              if (geom.type === 'Polygon') return [geom.coordinates[0][0]]
              return []
            })
            .filter(Boolean)
          
          if (coords.length > 0) {
            // Calculate bounding box
            const lons = coords.map(c => c[0])
            const lats = coords.map(c => c[1])
            const bounds = [
              [Math.min(...lons), Math.min(...lats)],
              [Math.max(...lons), Math.max(...lats)]
            ]
            
            // Fly to fit all entities
            mapRef.current.fitBounds(bounds, {
              padding: 100,
              maxZoom: 12,
              duration: 1500
            })
          }
        }
      }
      
      // Clear pending state
      setPendingOps(null)
      setPendingMessageId(null)
      
      // Return success status for parent to refresh map
      return allSuccess
      
    } catch (err) {
      console.error('Execute error:', err)
      setError(err.message)
      addMessage(MessageType.ERROR, `Failed to execute: ${err.message}`)
      addActivity(`Execution failed: ${err.message}`, 'error')
      return false
    } finally {
      setIsLoading(false)
    }
  }, [api, mapId, pendingOps, pendingMessageId, updateMessage, addMessage, addActivity])
  
  /**
   * Reject pending operations
   */
  const rejectOps = useCallback(() => {
    if (pendingMessageId) {
      updateMessage(pendingMessageId, {
        type: MessageType.ASSISTANT,
        rejected: true
      })
    }
    
    addActivity('Operation rejected')
    
    setPendingOps(null)
    setPendingMessageId(null)
  }, [pendingMessageId, updateMessage, addMessage, addActivity])

  /**
   * Update a specific pending operation by index
   * @param {number} opIndex - Index of the operation to update
   * @param {Object} updates - Updated operation data
   */
  const updatePendingOp = useCallback((opIndex, updates) => {
    if (!pendingOps || opIndex < 0 || opIndex >= pendingOps.length) return
    
    const newOps = [...pendingOps]
    newOps[opIndex] = { ...newOps[opIndex], ...updates }
    setPendingOps(newOps)
    
    // Also update the message's proposedOps for display
    if (pendingMessageId) {
      updateMessage(pendingMessageId, {
        proposedOps: newOps
      })
    }
    
    addActivity('Updated pending operation')
  }, [pendingOps, pendingMessageId, updateMessage, addActivity])
  
  /**
   * Clear chat history
   */
  const clearChat = useCallback(() => {
    setMessages([])
    setPendingOps(null)
    setPendingMessageId(null)
    setError(null)
  }, [])
  
  return {
    // State
    messages,
    pendingOps,
    isLoading,
    error,
    hasPendingApproval: pendingOps !== null && pendingOps.length > 0,
    
    // Actions
    sendMessage,
    approveOps,
    rejectOps,
    updatePendingOp,
    clearChat
  }
}
