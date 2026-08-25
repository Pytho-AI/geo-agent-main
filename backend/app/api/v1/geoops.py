from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.geoops import GeoOpsRequest, GeoOpsResponse
from app.services.knowledge.geoops_executor import execute_geoops

router = APIRouter()


@router.post("", response_model=GeoOpsResponse)
async def execute_operations(
    request: GeoOpsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Execute a batch of geo operations (create, move, update, delete)"""
    return await execute_geoops(db, request)
