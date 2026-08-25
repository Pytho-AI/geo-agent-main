from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import os
from pathlib import Path

from app.config import get_settings
from app.models.artifact import Artifact
from app.services.ingestion.parsers import parse_file
from app.services.realtime.manager import manager

# Uploads live under the deployment's data root (data_dir — the
# compose GEO_DATA_DIR mount), never a hardcoded container path: the
# hardcoded /app/data broke every out-of-container import (doc
# generation, tooling) on a read-only root.
UPLOAD_DIR = Path(get_settings().data_dir) / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def upload_artifact(
    db: AsyncSession,
    file: UploadFile,
    map_id: UUID,
    user_id: str,
) -> Artifact:
    """Upload and register an artifact"""
    
    # Determine file type
    filename = file.filename
    ext = filename.lower().split(".")[-1]
    
    file_type_map = {
        "geojson": "geojson",
        "json": "geojson",
        "shp": "shapefile",
        "zip": "shapefile",  # Assume zipped shapefile
        "tif": "geotiff",
        "tiff": "geotiff",
    }
    
    file_type = file_type_map.get(ext)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    
    # Save file locally (or to S3)
    file_path = UPLOAD_DIR / filename
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Create artifact record
    artifact = Artifact(
        filename=filename,
        file_type=file_type,
        storage_uri=str(file_path),
        status="pending",
        map_id=map_id,
        created_by=user_id,
    )
    
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    
    return artifact


async def get_artifact_status(db: AsyncSession, artifact_id: UUID) -> Artifact:
    """Get artifact by ID"""
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


async def trigger_ingest(db: AsyncSession, artifact_id: UUID) -> dict:
    """Parse and ingest artifact into entities/overlays"""
    artifact = await get_artifact_status(db, artifact_id)
    
    if artifact.status == "completed":
        raise HTTPException(status_code=400, detail="Artifact already ingested")
    
    artifact.status = "processing"
    await db.commit()
    
    try:
        result = await parse_file(
            db,
            artifact.storage_uri,
            artifact.file_type,
            artifact.map_id,
            artifact.created_by,
        )
        
        artifact.status = "completed"
        artifact.file_meta = {"entities": result["entities"], "overlays": result["overlays"]}
        await db.commit()
        
        # Notify via WebSocket
        if artifact.map_id:
            await manager.notify_change(
                str(artifact.map_id),
                "ingest_complete",
                {
                    "artifact_id": str(artifact_id),
                    "entities_created": result["entities"],
                    "overlays_created": result["overlays"],
                }
            )
        
        return {
            "artifact_id": artifact_id,
            "status": "completed",
            "entities_created": result["entities"],
            "overlays_created": result["overlays"],
        }
    except Exception as e:
        artifact.status = "failed"
        artifact.file_meta = {"error": str(e)}
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))
