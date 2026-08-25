"""Product engine records — the graph-to-text half's persistence.

ONE entity: the product record (a reified generation event). Flat rows,
no chains, no retry lineage, no parent pointers. The draft-layer model
rides the WORLD-MODEL tables (layer + origin_record_id columns there,
models/graph.py, models/reference.py); this module holds the record,
the engine-owned product-type registry, and the staleness touch table.
Lifecycle: draft -> final (LOCKED FOREVER) -> approved (= MERGE; one
approved edition per (project, product_type); approving another
supersedes the prior). Rows are never deleted — soft flags only.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Index, Integer, String,
    Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base


def _now():
    return datetime.now(timezone.utc)


RECORD_STATUSES = ("queued", "running", "complete", "failed", "cancelled")
ERROR_KINDS = ("llm_failure", "writer_invalid", "render_failed",
               "upstream_failed", "task_lost", "engine_restart")
LIFECYCLES = ("draft", "final", "approved", "superseded")


class ProductType(Base):
    """The engine-owned catalog registry (DB-seeded, versioned like
    every registry). The rail, the modals, and the staleness comparator
    all derive from these rows; writer-spec bodies live in code keyed
    by writer_spec_key. declared_fact_classes uses the coverage-audit
    key space: entity-type keys and clause:<register>:<kind> pairs."""
    __tablename__ = "product_types"

    type_key = Column(String(64), primary_key=True)
    label = Column(String(255), nullable=False)
    category = Column(String(64))
    ipoe_step = Column(Integer)
    output_formats = Column(JSONB, nullable=False, server_default="[]")
    depends_on = Column(JSONB, nullable=False, server_default="[]")
    fanout_dimension = Column(String(32))
    declared_fact_classes = Column(JSONB, nullable=False,
                                   server_default="[]")
    writer_spec_key = Column(String(64))
    # Dev-only rows never reach the analyst-facing rail (the 1a stub).
    dev_only = Column(Boolean, nullable=False, server_default=text("false"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    # Row-creation provenance (the registry convention; the seeder
    # stamps 'bundled').
    source = Column(String(32))


class ProductRecord(Base):
    __tablename__ = "product_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','complete','failed',"
            "'cancelled')", name="ck_product_records_status"),
        CheckConstraint(
            "lifecycle IN ('draft','final','approved','superseded')",
            name="ck_product_records_lifecycle"),
        # ONE running record per (project, product_type) — enforced by
        # a partial unique index (never an in-process dict); the losing
        # insert of a race returns the winner's record.
        Index("ux_product_records_one_running", "project_id",
              "product_type",
              unique=True,
              postgresql_where=text(
                  "status IN ('queued','running')")),
        # ONE approved edition per (project, product_type).
        Index("ux_product_records_one_approved", "project_id",
              "product_type",
              unique=True,
              postgresql_where=text("lifecycle = 'approved'")),
        Index("ix_product_records_project_type", "project_id",
              "product_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    product_type = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, server_default="queued")
    status_detail = Column(Text)
    error_kind = Column(String(32))
    log = Column(Text, nullable=False, server_default="")
    # The merged validated field payload — the substrate for ref: reads,
    # fanout keying, agentic read-back, and the approve-time merge.
    structured_content = Column(JSONB)
    # [{artifact_id, filename, content_type, coa_id?, object_key?}] —
    # bytes live in MinIO from 1b; 1a stub records carry none.
    artifacts = Column(JSONB, nullable=False, server_default="[]")
    lifecycle = Column(String(16), nullable=False, server_default="draft")
    finalized_at = Column(DateTime(timezone=True))
    finalized_by = Column(String(128))
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(String(128))
    # APPROVE LOCKS FOREVER (2026-07-23 lifecycle ruling): once an
    # edition has been approved its content is immutable history even
    # after an approval revoke — this flag survives the revoke's
    # approved_at reset and refuses revoke-to-draft.
    ever_approved = Column(Boolean, nullable=False,
                           server_default="false")
    superseded_by_record = Column(UUID(as_uuid=True))
    # Analyst-selected generation knobs (2026-07-27 ruling: the IBL
    # HVTL config_fields pattern, knobs declared in the template). The
    # EFFECTIVE config (declared defaults + analyst choices) captured
    # at mint — the edition's provenance of how it was generated.
    generation_config = Column(JSONB)
    # {type_key: approved_record_id} consumed at start — provenance and
    # the stale-vs-upstream comparator's input, never control flow.
    consumed_upstreams = Column(JSONB, nullable=False, server_default="{}")
    # {fact_class: iso_ts} captured at record start (the mid-run change
    # detector's baseline) and, post-approve, the merge marks used for
    # comparator self-exclusion.
    touch_baseline = Column(JSONB, nullable=False, server_default="{}")
    merge_touch_marks = Column(JSONB, nullable=False, server_default="{}")
    deleted = Column(Boolean, nullable=False, server_default=text("false"))
    created_by = Column(String(128), nullable=False,
                        server_default="_autodraft")
    created_at = Column(DateTime(timezone=True), default=_now,
                        nullable=False)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))


class ProductFactTouch(Base):
    """One row per (project, fact_class): the staleness high-water mark,
    bumped by DATABASE TRIGGERS on the underlying world-model tables
    (project-layer rows only; deletes included) — triggers because the
    write surfaces are many and the bulk paths (restore, wipe) would
    forget an application-level bump forever."""
    __tablename__ = "product_fact_touch"

    project_id = Column(UUID(as_uuid=True), primary_key=True)
    fact_class = Column(String(96), primary_key=True)
    touched_at = Column(DateTime(timezone=True), nullable=False,
                        default=_now)
