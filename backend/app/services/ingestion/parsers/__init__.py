from app.services.ingestion.parsers.geojson import parse_geojson
from app.services.ingestion.parsers.shapefile import parse_shapefile
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID


async def parse_file(
    db: AsyncSession,
    file_path: str,
    file_type: str,
    map_id: UUID,
    user_id: str,
) -> dict:
    """Route to appropriate parser based on file type"""
    
    if file_type == "geojson":
        return await parse_geojson(db, file_path, map_id, user_id)
    elif file_type == "shapefile":
        return await parse_shapefile(db, file_path, map_id, user_id)
    elif file_type == "geotiff":
        # TODO: Implement raster ingestion
        return {"entities": 0, "overlays": 0}
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
