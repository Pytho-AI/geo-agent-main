from app.models.map import Map
from app.models.entity import Entity
from app.models.overlay import Overlay
from app.models.artifact import Artifact
from app.models.event import Event
from app.models.history import MapHistory
from app.models.route import Route, RoutePath
from app.models.custom_symbol import CustomSymbol
from app.models.analyst_event import AnalystEvent
from app.models.graph import (
    ForceTemplate, GraphNode, GraphNodePosition, GraphEdge, GraphHolding, NodeField, EdgeField,
)
from app.models.reference import (
    EntityType, RelationshipType, FieldDef, WegEquipment, WegEquipmentAlias,
    WegEquipmentEmitter, WegEquipmentVariant, ReferenceSeedMeta,
)
# World-model provenance + ingestion records — the L0/L1/L2 rewrite
# (scratch/docs/oob/tool-surface-consolidation.md). Importing the module here
# registers its tables on Base.metadata for create_all.
from app.models.world import (
    Source, SourceRevision, SourceView, HeadingOccurrence, Section,
    SectionSourceView, Clause, EntityOccurrence, ClauseAbout, Assertion,
    AssertionBasis, Derivation, Supersession, Retraction, ProductBranch,
    IngestionRun,
)

__all__ = [
    "Map", "Entity", "Overlay", "Artifact", "Event", "MapHistory", "Route",
    "RoutePath", "CustomSymbol", "AnalystEvent",
    "ForceTemplate", "GraphNode", "GraphNodePosition", "GraphEdge", "GraphHolding", "NodeField",
    "EdgeField", "EntityType", "RelationshipType", "FieldDef", "WegEquipment",
    "WegEquipmentAlias", "WegEquipmentEmitter", "WegEquipmentVariant",
    "ReferenceSeedMeta",
    "Source", "SourceRevision", "SourceView", "HeadingOccurrence", "Section",
    "SectionSourceView", "Clause", "EntityOccurrence", "ClauseAbout",
    "Assertion", "AssertionBasis", "Derivation", "Supersession", "Retraction",
    "ProductBranch", "IngestionRun",
]
