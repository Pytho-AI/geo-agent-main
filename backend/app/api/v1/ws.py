from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from uuid import UUID

from app.services.realtime.manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    map_id: UUID = Query(...),
):
    """
    WebSocket endpoint for real-time updates.
    
    Connect with: ws://localhost:8000/api/v1/ws?map_id=xxx
    
    Messages received:
    - {"type": "entity_created", "data": {...}}
    - {"type": "entity_updated", "data": {...}}
    - {"type": "entity_deleted", "data": {"id": "..."}}
    - {"type": "overlay_created", "data": {...}}
    - {"type": "ingest_complete", "data": {"artifact_id": "...", "entities": N}}
    """
    map_id_str = str(map_id)
    await manager.connect(websocket, map_id_str)
    
    try:
        while True:
            # Keep connection alive, handle pings
            data = await websocket.receive_text()
            
            # Echo ping/pong for keepalive
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, map_id_str)
