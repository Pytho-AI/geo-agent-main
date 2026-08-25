"""Document → entity-graph ingestion — the analyst IMPORT pipeline.

SELF-CONTAINED IN GEO-AGENT: geo-agent does the whole job by itself
today — the engine behind the analyst import UI (upload an OPORD / OOB
annex / road-to-war → VLM extraction → graph entities/edges/holdings +
a resolution report the analyst reviews), running on geo-agent's OWN
gemma-4 client (app.services.llm). It revises decision 19 (which cut
the hand-built column-mapping wizard): import returns, VLM-driven.

The TOOL SURFACE IS EXPOSED for later integration — the two layers
below plus the ingest-oob / ingest-doc HTTP endpoints are a stable,
callable contract a future consumer can drive (e.g. the coa-pipeline
extracting a threat OOB to draw out COAs, or the IBL DAG-runner port).
What is DEFERRED is any cross-service WIRING: nothing here reaches
outward today; the surface is shaped so integration lands without a
rewrite when that architecture is confirmed.

STAGED PIPELINE (ingest_document) — the document is NOT a one-shot
input→output; defining WHERE the operation happens comes first and
frames everything after it:
  1. render_document_to_images  — doc → Gemma-sized JPEG page images.
  2. define_ao                  — read the pages, geocode the theater/
     anchors → the AREA OF OPERATIONS bbox (extract.py + resolve.py).
  3. extract_oob               — read the pages → units / infrastructure
     / holdings / typed edges (extract.py), never inventing coordinates.
  4. resolve_placements         — MGRS → coords; place names → geocode
     SCOPED TO THE AO; out-of-AO is impossible, no-match stays unplaced.
  5. ingest_oob                — the DETERMINISTIC core: ExtractedOOB →
     graph rows (type/alias/parent resolution, report). Extractor-
     agnostic — any producer (this VLM, a COA generator, a fixture) feeds
     it, so it stays the stable contract a future consumer drives.
  6. confirm_visually          — render the AO with the laydown, let the
     VLM adjudicate the genuinely ambiguous placements, apply corrections.
"""
import logging
from typing import List, Optional, Tuple

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.graph_ingest.schema import (
    AreaOfOperations, ExtractedOOB, ExtractedEntity, ExtractedEdge,
    ExtractedHolding, IngestReport,
)
from app.services.graph_ingest.ingest import ingest_oob

log = logging.getLogger("app.graph_ingest")

__all__ = [
    "AreaOfOperations", "ExtractedOOB", "ExtractedEntity", "ExtractedEdge",
    "ExtractedHolding", "IngestReport", "ingest_oob", "ingest_document",
    "ingest_documents",
]


async def _apply_coord_corrections(db: AsyncSession, project_id, corrections):
    from app.models.graph import GraphNode
    applied = 0
    for corr in corrections:
        node = (await db.execute(select(GraphNode).where(
            GraphNode.project_id == project_id,
            func.lower(GraphNode.name) == (corr["name"] or "").strip().lower()
        ).limit(1))).scalars().first()
        if node is not None:
            node.geom = WKTElement(f"POINT({corr['lon']} {corr['lat']})", srid=4326)
            applied += 1
    if applied:
        await db.commit()
    return applied


# Doctrinal disposition moved to graph_ingest/disposition.py — the
# engine reads frontage/depth norms from the force-template rows and
# per-echelon doctrine defaults, arrays subordinates threat-facing in
# two echelons, land-checks every synthesized point (ESA WorldCover),
# and writes through record_position so the track stays the record and
# the placard shows the doctrinal basis. Re-exports keep old imports
# working.
from app.services.graph_ingest.disposition import (  # noqa: E402,F401
    array_subordinates, role_class as _role_class,
)


async def _place_by_frontage(db: AsyncSession, project_id, ao) -> int:
    """Compatibility wrapper — the doctrinal disposition engine
    (disposition.array_subordinates) does the arraying now."""
    report = await array_subordinates(db, project_id)
    return report["synthesized_positions"]


async def ingest_documents(
    db: AsyncSession, project_id, docs: List[Tuple[bytes, str]], *,
    created_by: str = "_ingest", document_kind: Optional[str] = None,
) -> dict:
    """Ingest ONE OR MANY scenario documents in a SINGLE extraction. All
    the pages go to the model together, so it reads the whole scenario at
    once and emits ONE consolidated order of battle — a unit named across
    several documents is resolved in-context, with no sequential per-doc
    pass to merge (and dedup) afterward. Staged: pages → AO → OOB →
    placement → graph → visual confirmation."""
    from app.services.graph_ingest.extract import read_document, define_ao, extract_oob
    from app.services.graph_ingest.resolve import (
        resolve_placements, confirm_visually,
    )
    from app.models.graph import GraphNode

    all_pages: List[bytes] = []
    doc_texts: List[str] = []
    labels: List[str] = []
    for data, filename in docs:
        labels.append(filename)
        # ONE conversion per document → both lossless text and page images.
        # Text is authoritative for names/grids (the vision encoder blurs
        # small grid text); images ride along for visual context. A scanned
        # doc yields no text and falls back to vision.
        text, pages = await read_document(data, filename)
        if text and text.strip():
            doc_texts.append(f"===== DOCUMENT: {filename} =====\n{text}")
            # L0: persist the verbatim document text — the provenance
            # root the register's clauses cite by filename, so Sources
            # can quote the actual document.
            from app.models.graph import SourceDocument
            db.add(SourceDocument(project_id=project_id, filename=filename,
                                  doc_text=text, created_by=created_by))
        if pages:
            all_pages.extend(pages)
    plain_text: Optional[str] = "\n\n".join(doc_texts) if doc_texts else None
    source = ", ".join(labels)

    # 1. area of operations — from the whole scenario, first, so placement
    #    is a lookup inside it. Prefers the lossless text.
    ao = await define_ao(all_pages, plain_text=plain_text, source_label=source)
    # A FRAGO / update reuses the names already in the project (match by
    # name to apply deltas); a fresh multi-doc build starts clean.
    known_names = [n for (n,) in (await db.execute(
        select(GraphNode.name).where(GraphNode.project_id == project_id))).all() if n]
    # The doctrinal force-template catalog (RU/CN + US, seeded) so the
    # model can tag each unit with the standard template that supplies its
    # equipment and subordinate structure — the narrative rarely lists
    # them, so this is where a unit's equipment comes from (ingest_oob then
    # instantiates the tagged template's subtree under the unit).
    from app.models.graph import ForceTemplate
    tpls = (await db.execute(
        select(ForceTemplate).order_by(ForceTemplate.key))).scalars().all()
    catalog = "\n".join(
        f"{t.key} | {t.name} | {t.echelon or '?'} | "
        f"{'US/NATO' if t.key.startswith('us_') else 'China' if t.key.startswith('chn_') else 'Russia/OPFOR'}"
        for t in tpls) or None
    # 2. one consolidated order of battle over the whole scenario. With
    #    text present this is a SINGLE call (dedup + grids work); images
    #    ride along only if they fit that one call.
    oob = await extract_oob(all_pages, ao, plain_text=plain_text,
                            filename=source, known_names=known_names,
                            templates_catalog=catalog)
    if document_kind:
        oob.document_kind = document_kind
    # 3. deterministic placement (mutates entity coords).
    placement = await resolve_placements(oob, ao)
    # 4. persist.
    report = await ingest_oob(db, project_id, oob, created_by=created_by)
    # 4b. episodic register — the world model's clause layer: atomic
    #     statements ABOUT the just-created entities (assessments,
    #     strengths, activities, intents, obligations) with slots and
    #     bitemporal supersession. Non-fatal: a register failure never
    #     sinks the ingest.
    from app.services.graph_ingest.clauses import run_register_stage
    register = await run_register_stage(db, project_id, plain_text, source)
    # 5. visual confirmation of the ambiguous placements only.
    corrections = await confirm_visually(project_id, ao, placement.ambiguous)
    corrected = await _apply_coord_corrections(db, project_id, corrections) if corrections else 0
    # 6. array the instantiated subordinate structure across each placed
    #    unit's doctrinal frontage, so the whole force lands on the map.
    frontage_placed = await _place_by_frontage(db, project_id, ao)

    return {
        "documents": labels,
        "extracted_entities": len(oob.entities),
        "extracted_edges": len(oob.edges),
        "episodic_register": register,
        "report": report.model_dump(),
        "area_of_operations": {
            "theater": ao.theater, "countries": ao.countries,
            "bbox": list(ao.bbox), "resolved": ao.resolved,
            "anchors": ao.anchors, "note": ao.note,
        },
        "placement": {
            "placed": placement.placed, "from_grid": placement.from_grid,
            "from_name": placement.from_name,
            "track_points": placement.track_points,
            "unresolved": placement.unresolved,
            "ambiguous": [a["name"] for a in placement.ambiguous],
            "visually_corrected": corrected,
            "frontage_placed": frontage_placed,
        },
    }


async def ingest_document(
    db: AsyncSession, project_id, data: bytes, filename: str, *,
    created_by: str = "_ingest", document_kind: Optional[str] = None,
) -> dict:
    """Single-document convenience wrapper over ingest_documents (e.g. a
    FRAGO update dropped on its own)."""
    return await ingest_documents(
        db, project_id, [(data, filename)],
        created_by=created_by, document_kind=document_kind)
