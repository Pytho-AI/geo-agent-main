import geopandas as gpd
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.shape import from_shape
import zipfile
import tempfile
import os
from uuid import UUID

from app.models.entity import Entity


async def parse_shapefile(
    db: AsyncSession,
    file_path: str,
    map_id: UUID,
    user_id: str,
) -> dict:
    """Parse Shapefile (or zipped shapefile) and create entities"""
    
    # Handle zipped shapefiles
    if file_path.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(file_path, "r") as z:
                z.extractall(tmpdir)
            
            # Find .shp file
            shp_files = [f for f in os.listdir(tmpdir) if f.endswith(".shp")]
            if not shp_files:
                raise ValueError("No .shp file found in zip")
            
            shp_path = os.path.join(tmpdir, shp_files[0])
            return await _parse_shp(db, shp_path, map_id, user_id)
    else:
        return await _parse_shp(db, file_path, map_id, user_id)


async def _parse_shp(
    db: AsyncSession,
    shp_path: str,
    map_id: UUID,
    user_id: str,
) -> dict:
    """Parse a .shp file"""
    
    gdf = gpd.read_file(shp_path)
    
    # Convert to WGS84 if needed
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    
    entities_created = 0
    
    for _, row in gdf.iterrows():
        geom = row.geometry
        attrs = row.drop("geometry").to_dict()
        
        # Clean attrs (convert non-serializable types)
        clean_attrs = {}
        for k, v in attrs.items():
            if v is not None and str(v) != "nan":
                clean_attrs[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v
        
        entity = Entity(
            kind=clean_attrs.pop("kind", "feature"),
            geom=from_shape(geom, srid=4326),
            attrs=clean_attrs,
            map_id=map_id,
            created_by=user_id,
        )
        db.add(entity)
        entities_created += 1
    
    await db.commit()
    
    return {"entities": entities_created, "overlays": 0}
