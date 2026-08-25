import json
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import shape
from geoalchemy2.shape import from_shape
from uuid import UUID

from app.models.entity import Entity
from app.models.overlay import Overlay


async def parse_geojson(
    db: AsyncSession,
    file_path: str,
    map_id: UUID,
    user_id: str,
) -> dict:
    """Parse GeoJSON file and create entities/overlays"""
    
    with open(file_path, "r") as f:
        data = json.load(f)
    
    features = data.get("features", [])
    entities_created = 0
    overlays_created = 0
    
    for feature in features:
        geom = shape(feature["geometry"])
        props = feature.get("properties", {})
        
        # Determine if entity or overlay based on geometry type or properties
        kind = props.pop("kind", None)
        name = props.pop("name", None)
        
        geom_type = geom.geom_type
        is_overlay = kind in ["phase_line", "boundary", "route", "area"] or geom_type in ["LineString", "MultiLineString", "Polygon", "MultiPolygon"]
        
        if is_overlay and name:
            overlay = Overlay(
                kind=kind or geom_type.lower(),
                name=name,
                geom=from_shape(geom, srid=4326),
                attrs=props,
                map_id=map_id,
                created_by=user_id,
            )
            db.add(overlay)
            overlays_created += 1
        else:
            entity = Entity(
                kind=kind or "feature",
                geom=from_shape(geom, srid=4326),
                attrs=props,
                map_id=map_id,
                created_by=user_id,
            )
            db.add(entity)
            entities_created += 1
    
    await db.commit()
    
    return {"entities": entities_created, "overlays": overlays_created}
