from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from pydantic import BaseModel

from app.db.session import get_db
from app.services.ingestion.gateway import upload_artifact, get_artifact_status, trigger_ingest

router = APIRouter()


class ArtifactResponse(BaseModel):
    id: UUID
    filename: str
    file_type: str
    status: str


class IngestResponse(BaseModel):
    artifact_id: UUID
    status: str
    entities_created: int = 0
    overlays_created: int = 0


@router.post("", response_model=ArtifactResponse)
async def upload_file(
    file: UploadFile = File(...),
    map_id: UUID = Query(...),
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a geo file (shapefile, geojson, geotiff)"""
    return await upload_artifact(db, file, map_id, user_id)


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get artifact status"""
    return await get_artifact_status(db, artifact_id)


@router.post("/{artifact_id}/ingest", response_model=IngestResponse)
async def ingest_artifact(
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger ingestion of an uploaded artifact"""
    return await trigger_ingest(db, artifact_id)
