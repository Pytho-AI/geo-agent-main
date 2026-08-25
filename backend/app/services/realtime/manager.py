from fastapi import WebSocket
from typing import Dict, Set
import json


class ConnectionManager:
    """Simple WebSocket connection manager for real-time updates"""
    
    def __init__(self):
        # session_id -> set of websocket connections
        self.connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept and register a new connection"""
        await websocket.accept()
        if session_id not in self.connections:
            self.connections[session_id] = set()
        self.connections[session_id].add(websocket)
    
    def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a connection"""
        if session_id in self.connections:
            self.connections[session_id].discard(websocket)
            if not self.connections[session_id]:
                del self.connections[session_id]
    
    async def broadcast(self, session_id: str, message: dict):
        """Broadcast message to all connections in a session"""
        if session_id not in self.connections:
            return
        
        dead_connections = set()
        for websocket in self.connections[session_id]:
            try:
                await websocket.send_json(message)
            except Exception:
                dead_connections.add(websocket)
        
        # Clean up dead connections
        for ws in dead_connections:
            self.connections[session_id].discard(ws)
    
    async def notify_change(self, session_id: str, change_type: str, data: dict):
        """Notify all clients about a change"""
        await self.broadcast(session_id, {
            "type": change_type,
            "data": data,
        })


# Global instance
manager = ConnectionManager()
