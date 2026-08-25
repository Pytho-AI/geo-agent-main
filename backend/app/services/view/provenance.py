"""Chain-derived position provenance — THE analyst-visible Source line.

Provenance is the record chain (2026-07-28 ruling): projection row ->
backing assertion -> basis clause -> section -> source view -> source
revision. This module is the ONE place that chain is rendered into
English, at read time. Nothing here is ever stored, and no write surface
composes provenance text — a stored `source` string on a position row is
either legacy code-composed labeling (analyst drag, doctrinal
disposition, bare ingestion tag) used only as the FALLBACK for rows with
no backing assertion, or dead residue.
"""
from typing import Dict, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.world import (Assertion, AssertionBasis, Clause, Section,
                              SectionSourceView, SourceRevision, SourceView)


def _compose(title, filename, headings) -> str:
    doc = title or filename or "source document"
    path = " > ".join(headings or [])
    return f"stated: {doc}" + (f" - {path}" if path else "")


async def provenance_for_rows(
    db: AsyncSession, row_ids: Iterable[UUID],
) -> Dict[str, str]:
    """{position_row_id_str: rendered provenance} for every row backed by
    a committed assertion with a clause basis. First basis wins the line
    (a multi-basis assertion cites its primary statement); rows without
    backing are absent from the result — callers fall back to the row's
    stored code-composed label."""
    ids = [r for r in row_ids if r is not None]
    if not ids:
        return {}
    rows = (await db.execute(
        select(Assertion.materialized_position_id,
               Section.headings, SourceRevision.title,
               SourceRevision.filename,
               AssertionBasis.id)
        .join(AssertionBasis, AssertionBasis.assertion_id == Assertion.id)
        .join(Clause, Clause.id == AssertionBasis.clause_id)
        .join(Section, Section.id == Clause.section_id)
        .join(SectionSourceView,
              SectionSourceView.section_id == Section.id)
        .join(SourceView,
              SourceView.id == SectionSourceView.source_view_id)
        .join(SourceRevision,
              SourceRevision.id == SourceView.source_revision_id)
        .where(Assertion.materialized_position_id.in_(ids),
               Assertion.record_state == "committed",
               Assertion.retracted_by.is_(None)))).all()
    out: Dict[str, str] = {}
    for rid, headings, title, filename, _bid in rows:
        key = str(rid)
        if key not in out:
            out[key] = _compose(title, filename, headings)
    return out
