from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from geoalchemy2.functions import ST_MakeEnvelope, ST_Intersects, ST_AsGeoJSON
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from types import SimpleNamespace
from typing import List, Optional
from uuid import UUID
import json

from app.models.entity import Entity
from app.models.overlay import Overlay
from app.schemas.entity import EntityCreate
from app.schemas.overlay import OverlayCreate, OverlayUpdate


# ---------------------------------------------------------------------------
# Reads — single query, return lightweight objects (no ORM mutation)
# ---------------------------------------------------------------------------

async def get_entities(
    db: AsyncSession,
    map_id: UUID,
    kind: str = None,
    bbox: List[float] = None,
) -> list:
    """Get entities filtered by map_id and optional spatial/kind filters."""
    query = select(Entity, ST_AsGeoJSON(Entity.geom).label("geojson")).where(
        Entity.map_id == map_id
    )

    if kind:
        query = query.where(Entity.kind == kind)

    if bbox:
        envelope = ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326)
        query = query.where(ST_Intersects(Entity.geom, envelope))

    result = await db.execute(query)
    return [
        SimpleNamespace(
            id=e.id, kind=e.kind, geom=json.loads(gj),
            attrs=e.attrs or {}, confidence=e.confidence,
            map_id=e.map_id, created_by=e.created_by,
            created_at=e.created_at, updated_at=e.updated_at,
        )
        for e, gj in result.all()
    ]


async def get_entity_by_id(db: AsyncSession, entity_id: UUID):
    """Get single entity by ID."""
    result = await db.execute(
        select(Entity, ST_AsGeoJSON(Entity.geom).label("geojson")).where(
            Entity.id == entity_id
        )
    )
    row = result.one_or_none()
    if not row:
        return None
    e, gj = row
    return SimpleNamespace(
        id=e.id, kind=e.kind, geom=json.loads(gj),
        attrs=e.attrs or {}, confidence=e.confidence,
        map_id=e.map_id, created_by=e.created_by,
        created_at=e.created_at, updated_at=e.updated_at,
    )


# ---------------------------------------------------------------------------
# Writes — build ORM, commit once, return dict from known data
# ---------------------------------------------------------------------------

async def create_entity(
    db: AsyncSession,
    entity_data: EntityCreate,
    map_id: UUID,
    user_id: str,
):
    """Create a new entity."""
    attrs = dict(entity_data.attrs or {})
    # Symbol coding is geo-agent's responsibility: a mil_unit created
    # without a SIDC (NL agent ops, semantic API callers) gets a 2525E
    # one built from affiliation/echelon/category. Picker-placed units
    # arrive with their SIDC and keep it.
    if entity_data.kind == "mil_unit":
        from app.utils.sidc import ensure_mil_unit_sidc
        ensure_mil_unit_sidc(attrs)
    entity = Entity(
        kind=entity_data.kind,
        geom=from_shape(shape(entity_data.geom.model_dump()), srid=4326),
        attrs=attrs,
        confidence=entity_data.confidence,
        map_id=map_id,
        created_by=user_id,
    )
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    # Return from known data — geom comes from input, rest from refreshed ORM
    return SimpleNamespace(
        id=entity.id, kind=entity.kind,
        geom=entity_data.geom.model_dump(),
        attrs=entity.attrs or {}, confidence=entity.confidence,
        map_id=entity.map_id, created_by=entity.created_by,
        created_at=entity.created_at, updated_at=entity.updated_at,
    )


async def update_entity(
    db: AsyncSession,
    entity_id: UUID,
    geom: dict = None,
    attrs: dict = None,
    confidence: float = None,
):
    """Update an existing entity."""
    result = await db.execute(select(Entity).where(Entity.id == entity_id))
    entity = result.scalar_one_or_none()
    if not entity:
        return None

    if geom is not None:
        entity.geom = from_shape(shape(geom), srid=4326)
    if attrs is not None:
        # ONE symbol format in the system: any SIDC written through the
        # API is normalized to 2525E numeric at this boundary.
        if entity.kind == "mil_unit" and attrs.get("sidc"):
            from app.utils.sidc import to_2525e_sidc
            attrs = {**attrs, "sidc": to_2525e_sidc(attrs["sidc"])}
        entity.attrs = attrs
    if confidence is not None:
        entity.confidence = confidence

    await db.commit()
    await db.refresh(entity)

    # If geom was updated we have it as dict; otherwise read once from DB
    if geom is not None:
        geom_json = geom
    else:
        geom_json = json.loads(await db.scalar(ST_AsGeoJSON(entity.geom)))

    return SimpleNamespace(
        id=entity.id, kind=entity.kind, geom=geom_json,
        attrs=entity.attrs or {}, confidence=entity.confidence,
        map_id=entity.map_id, created_by=entity.created_by,
        created_at=entity.created_at, updated_at=entity.updated_at,
    )


async def delete_entity(db: AsyncSession, entity_id: UUID) -> bool:
    """Delete an entity by ID."""
    result = await db.execute(select(Entity).where(Entity.id == entity_id))
    entity = result.scalar_one_or_none()
    if not entity:
        return False
    await db.delete(entity)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------

async def get_overlays(
    db: AsyncSession,
    map_id: UUID,
    kind: str = None,
    bbox: List[float] = None,
) -> list:
    """Get overlays filtered by map_id and optional spatial/kind filters."""
    query = select(Overlay, ST_AsGeoJSON(Overlay.geom).label("geojson")).where(
        Overlay.map_id == map_id
    )

    if kind:
        query = query.where(Overlay.kind == kind)

    if bbox:
        envelope = ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326)
        query = query.where(ST_Intersects(Overlay.geom, envelope))

    result = await db.execute(query)
    return [
        SimpleNamespace(
            id=o.id, kind=o.kind, name=o.name, geom=json.loads(gj),
            attrs=o.attrs or {}, map_id=o.map_id, created_by=o.created_by,
            created_at=o.created_at, updated_at=o.updated_at,
        )
        for o, gj in result.all()
    ]


async def get_overlay_by_id(db: AsyncSession, overlay_id: UUID):
    """Get single overlay by ID."""
    result = await db.execute(
        select(Overlay, ST_AsGeoJSON(Overlay.geom).label("geojson")).where(
            Overlay.id == overlay_id
        )
    )
    row = result.one_or_none()
    if not row:
        return None
    o, gj = row
    return SimpleNamespace(
        id=o.id, kind=o.kind, name=o.name, geom=json.loads(gj),
        attrs=o.attrs or {}, map_id=o.map_id, created_by=o.created_by,
        created_at=o.created_at, updated_at=o.updated_at,
    )


async def create_overlay(
    db: AsyncSession,
    overlay_data: OverlayCreate,
    map_id: UUID,
    user_id: str,
):
    """Create a new overlay."""
    overlay = Overlay(
        kind=overlay_data.kind,
        name=overlay_data.name,
        geom=from_shape(shape(overlay_data.geom.model_dump()), srid=4326),
        attrs=overlay_data.attrs,
        map_id=map_id,
        created_by=user_id,
    )
    db.add(overlay)
    await db.commit()
    await db.refresh(overlay)
    return SimpleNamespace(
        id=overlay.id, kind=overlay.kind, name=overlay.name,
        geom=overlay_data.geom.model_dump(),
        attrs=overlay.attrs or {}, map_id=overlay.map_id,
        created_by=overlay.created_by,
        created_at=overlay.created_at, updated_at=overlay.updated_at,
    )


async def update_overlay(
    db: AsyncSession,
    overlay_id: UUID,
    overlay_data: OverlayUpdate,
):
    """Update an existing overlay."""
    result = await db.execute(select(Overlay).where(Overlay.id == overlay_id))
    overlay = result.scalar_one_or_none()
    if not overlay:
        return None

    if overlay_data.kind is not None:
        overlay.kind = overlay_data.kind
    if overlay_data.name is not None:
        overlay.name = overlay_data.name
    if overlay_data.geom is not None:
        overlay.geom = from_shape(shape(overlay_data.geom.model_dump()), srid=4326)
    if overlay_data.attrs is not None:
        overlay.attrs = overlay_data.attrs

    await db.commit()
    await db.refresh(overlay)

    if overlay_data.geom is not None:
        geom_json = overlay_data.geom.model_dump()
    else:
        geom_json = json.loads(await db.scalar(ST_AsGeoJSON(overlay.geom)))

    return SimpleNamespace(
        id=overlay.id, kind=overlay.kind, name=overlay.name,
        geom=geom_json, attrs=overlay.attrs or {},
        map_id=overlay.map_id, created_by=overlay.created_by,
        created_at=overlay.created_at, updated_at=overlay.updated_at,
    )


async def delete_overlay(db: AsyncSession, overlay_id: UUID) -> bool:
    """Delete an overlay by ID."""
    result = await db.execute(select(Overlay).where(Overlay.id == overlay_id))
    overlay = result.scalar_one_or_none()
    if not overlay:
        return False
    await db.delete(overlay)
    await db.commit()
    return True
