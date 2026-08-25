from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from uuid import UUID

from app.db.session import get_db
from app.services.nl.agent import process_nl_query, process_nl_update, process_nl_chat

router = APIRouter()


class NLQueryRequest(BaseModel):
    text: str
    map_id: UUID
    user_id: str
    bbox: Optional[List[float]] = None  # [min_lon, min_lat, max_lon, max_lat]


class NLQueryResponse(BaseModel):
    answer: str
    entities: Optional[List[Dict[str, Any]]] = None
    overlays: Optional[List[Dict[str, Any]]] = None
    suggested_filters: Optional[Dict[str, Any]] = None


class NLUpdateRequest(BaseModel):
    text: str
    map_id: UUID
    user_id: str


class NLUpdateResponse(BaseModel):
    success: bool
    message: str
    ops_executed: Optional[List[Dict[str, Any]]] = None


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class NLChatRequest(BaseModel):
    text: str
    map_id: UUID
    user_id: str
    bbox: Optional[List[float]] = None  # [min_lon, min_lat, max_lon, max_lat]
    conversation_history: Optional[List[ChatMessage]] = None
    supply_context: Optional[Dict[str, Any]] = None  # depots + lanes from frontend


class NLChatResponse(BaseModel):
    message: str
    proposed_ops: List[Dict[str, Any]]
    requires_approval: bool
    clarification_needed: Optional[str] = None
    supply_depot_focus: Optional[str] = None  # depot code to navigate to in UI


@router.post("/query", response_model=NLQueryResponse)
async def nl_query(
    request: NLQueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """Natural language query over geo data"""
    return await process_nl_query(db, request)


@router.post("/update", response_model=NLUpdateResponse)
async def nl_update(
    request: NLUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Natural language update (create, move, modify entities/overlays)"""
    return await process_nl_update(db, request)


@router.post("/chat", response_model=NLChatResponse)
async def nl_chat(
    request: NLChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Natural language chat for map operations.
    
    This endpoint parses user intent and returns proposed operations
    for approval before execution. The actual execution happens via
    the /geoops endpoint after user confirmation.
    
    Returns:
        - message: Human-readable description of proposed action
        - proposed_ops: List of GeoOps to execute if approved
        - requires_approval: True if operations need user confirmation
        - clarification_needed: If set, indicates more info is needed
    """
    # Convert conversation history to dict format
    history = None
    if request.conversation_history:
        history = [{"role": msg.role, "content": msg.content} for msg in request.conversation_history]
    
    return await process_nl_chat(
        db=db,
        text=request.text,
        user_id=request.user_id,
        map_id=request.map_id,
        bbox=request.bbox,
        conversation_history=history,
        supply_context=request.supply_context,
    )
