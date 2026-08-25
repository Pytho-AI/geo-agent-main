/**
 * useProductChains — unified jobs registry data source for the
 * dashboard.
 *
 * Backed by GET /api/products/records on first mount, then maintained
 * via the session-less WS frames product_record_upsert /
 * product_record_delete / product_records_snapshot broadcast by
 * handlers/product_records.py on every state transition.
 *
 * One row per logical job (chain_head_id). The row's appearance is
 * driven by chain.state: `running` / `complete` / `failed`. Retry
 * mutates the displayed state in place (same chain_head_id, new
 * latest_record_id) — no new row appears.
 *
 * Replaces useProductCatalog + the local generating[] / inflight[]
 * shadow arrays + the 4s polling loop. The unified registry is the
 * single source of truth.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useIntelAgentWs } from "./IntelAgentWs";

export type ChainState = "running" | "complete" | "failed";

export interface ChainView {
  chain_head_id: string;
  latest_record_id: string;
  parent_record_id?: string | null;
  product_parent_record_id?: string | null;
  product_type: string;
  coa_id: string | null;
  coa_label: string | null;
  source: string;
  source_metadata: Record<string, unknown>;
  state: ChainState;
  phase: string;
  attempts: number;
  started_at_ms: number;
  latest_started_at_ms: number;
  ended_at_ms: number | null;
  duration_ms: number | null;
  artifact_id: string | null;
  autodraft_session_id: string | null;
  error: string | null;
  error_kind: string | null;
  gate_position: number | null;
  // Wave progress (0-99) + wave label ("3/5") emitted by the DAG
  // executor at each wave end via record_transition. Dashboard reads
  // these on the running row to render "Generating… XX%".
  progress_pct: number;
  progress_wave: string;
  // Dashboard render metadata enriched by product_records.
  long_name: string;
  format: string;
  is_xlsx: boolean;
  category: string | null;
  category_order: number;
  step_label: string | null;
  approval_status: "draft" | "published" | string | null;
  approved_by: string;
  approved_at: number;
}

export interface GateStats {
  in_use?: number;
  waiters?: number;
  budget?: number;
  headroom?: number;
  queue_head?: Array<{
    chain_head_id: string;
    product_type: string;
    gate_position: number;
  }>;
}

interface ProductRecordWire {
  record_id: string;
  chain_head_id: string;
  parent_record_id: string | null;
  product_parent_record_id: string | null;
  product_type: string;
  coa_id: string | null;
  coa_label: string | null;
  source: string;
  source_metadata: Record<string, unknown>;
  state: ChainState;
  phase: string;
  attempt_index: number;
  started_at_ms: number;
  gate_acquired_at_ms: number | null;
  writer_started_at_ms: number | null;
  ended_at_ms: number | null;
  duration_ms: number | null;
  artifact_id: string | null;
  autodraft_session_id: string | null;
  error: string | null;
  error_kind: string | null;
  gate_position: number | null;
  progress_pct: number;
  progress_wave: string;
  long_name: string;
  format: string;
  is_xlsx: boolean;
  category: string | null;
  category_order: number;
  step_label: string | null;
  approval_status: string | null;
  approved_by: string;
  approved_at: number;
}

/**
 * Merge a single ProductRecord upsert into the chain map. Each
 * record represents one attempt; chains group attempts by
 * chain_head_id. The displayed row carries the LATEST attempt's
 * state (highest attempt_index).
 */
function applyRecordUpsert(
  chainsByHead: Map<string, { records: ProductRecordWire[] }>,
  record: ProductRecordWire,
): void {
  const head = record.chain_head_id;
  const entry = chainsByHead.get(head) ?? { records: [] };
  // Replace the same record_id if present (transitions), otherwise append.
  const existingIdx = entry.records.findIndex(
    (r) => r.record_id === record.record_id,
  );
  if (existingIdx >= 0) {
    entry.records[existingIdx] = record;
  } else {
    entry.records.push(record);
  }
  chainsByHead.set(head, entry);
}

/** Collapse one chain's attempts into the wire-shape ChainView. */
function projectChain(records: ProductRecordWire[]): ChainView | null {
  if (!records.length) return null;
  const sorted = [...records].sort(
    (a, b) => a.attempt_index - b.attempt_index,
  );
  const latest = sorted[sorted.length - 1];
  const earliest = sorted[0];
  return {
    chain_head_id: latest.chain_head_id,
    latest_record_id: latest.record_id,
    parent_record_id: latest.parent_record_id,
    product_parent_record_id: latest.product_parent_record_id,
    product_type: latest.product_type,
    coa_id: latest.coa_id,
    coa_label: latest.coa_label,
    source: latest.source,
    source_metadata: latest.source_metadata,
    state: latest.state,
    phase: latest.phase,
    attempts: records.length,
    started_at_ms: earliest.started_at_ms,
    latest_started_at_ms: latest.started_at_ms,
    ended_at_ms: latest.ended_at_ms,
    duration_ms: latest.duration_ms,
    artifact_id: latest.artifact_id,
    autodraft_session_id: latest.autodraft_session_id,
    error: latest.error,
    error_kind: latest.error_kind,
    gate_position: latest.gate_position,
    progress_pct: latest.progress_pct ?? 0,
    progress_wave: latest.progress_wave ?? "",
    long_name: latest.long_name,
    format: latest.format,
    is_xlsx: latest.is_xlsx,
    category: latest.category,
    category_order: latest.category_order,
    step_label: latest.step_label,
    approval_status: latest.approval_status,
    approved_by: latest.approved_by,
    approved_at: latest.approved_at,
  };
}

export function useProductChains() {
  const ws = useIntelAgentWs();

  const [chains, setChains] = useState<ChainView[]>([]);
  const [gate, setGate] = useState<GateStats>({});
  // Initialize true: the load() effect runs on mount and sets this to
  // true again at the top + false in finally. Starting true means the
  // spinner shows on first render before the first fetch completes,
  // rather than flashing "empty" for a single paint.
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Internal record-level state — keyed by chain_head_id. Projection
  // recomputes whenever a record upsert lands.
  const chainsByHeadRef = useRef<
    Map<string, { records: ProductRecordWire[] }>
  >(new Map());

  // Monotonic seq seen so the reducer drops out-of-order frames.
  const lastSeenSeqRef = useRef<number>(0);

  const rebuildChains = useCallback(() => {
    const built: ChainView[] = [];
    chainsByHeadRef.current.forEach((entry) => {
      const cv = projectChain(entry.records);
      if (cv) built.push(cv);
    });
    built.sort((a, b) => b.started_at_ms - a.started_at_ms);
    setChains(built);
  }, []);

  /** Initial fetch — chains AND derive record-level state from the
   *  ChainView shape so subsequent upserts can compare against
   *  attempt_index. The backend returns ChainView (collapsed), but
   *  for the reducer to work correctly on subsequent upserts we
   *  need to track per-record state. Two-fetch approach: pull the
   *  full snapshot via WS resume protocol; the REST endpoint just
   *  primes the displayed list. */
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/products/records");
      if (!r.ok) {
        setChains([]);
        setError(`Records request failed (HTTP ${r.status}).`);
        return;
      }
      const body = await r.json();
      const cs: ChainView[] = Array.isArray(body?.chains) ? body.chains : [];
      // Bootstrap idempotently: the WS subscribe effect may already be
      // active and may have received product_record_upsert frames
      // DURING this fetch. Clearing the map unconditionally would wipe
      // in-flight state. Instead, only seed chains the WS reducer has
      // NOT already populated. WS-driven entries win.
      //
      // Per-chain shape: REST returns the projected ChainView (one row
      // per chain with attempts=N), but the internal map keeps the
      // per-attempt records that projectChain re-collapses. Synthesize
      // N records — one per attempt — so attempts count is correct
      // immediately, before any WS records for older attempts arrive.
      // Prior attempts (attempt_index < N) are synthesized as 'failed'
      // (they weren't the latest, so by definition the chain retried);
      // only the last attempt carries the latest state.
      for (const c of cs) {
        if (chainsByHeadRef.current.has(c.chain_head_id)) {
          // WS reducer already owns this chain — leave it alone.
          continue;
        }
        const totalAttempts = Math.max(1, c.attempts || 1);
        const synthRecords: ProductRecordWire[] = [];
        for (let i = 1; i <= totalAttempts; i++) {
          const isLatest = i === totalAttempts;
          synthRecords.push({
            // Only the latest attempt has a known record_id from the
            // REST projection. Earlier attempts get a synthetic id
            // namespaced under the chain head; the WS reducer will
            // replace these by record_id when real records arrive.
            record_id: isLatest
              ? c.latest_record_id
              : `__synth__:${c.chain_head_id}:${i}`,
            chain_head_id: c.chain_head_id,
            parent_record_id: isLatest ? c.parent_record_id ?? null : null,
            product_parent_record_id: isLatest
              ? c.product_parent_record_id ?? null
              : null,
            product_type: c.product_type,
            coa_id: c.coa_id,
            coa_label: c.coa_label,
            source: c.source,
            source_metadata: c.source_metadata ?? {},
            state: isLatest ? c.state : "failed",
            phase: isLatest ? c.phase : "retired",
            attempt_index: i,
            started_at_ms: isLatest
              ? c.latest_started_at_ms || c.started_at_ms
              : c.started_at_ms,
            gate_acquired_at_ms: null,
            writer_started_at_ms: null,
            ended_at_ms: isLatest ? c.ended_at_ms : c.started_at_ms,
            duration_ms: isLatest ? c.duration_ms : null,
            artifact_id: isLatest ? c.artifact_id : null,
            autodraft_session_id: isLatest ? c.autodraft_session_id : null,
            error: isLatest ? c.error : null,
            error_kind: isLatest ? c.error_kind : null,
            gate_position: isLatest ? c.gate_position : null,
            long_name: c.long_name,
            format: c.format,
            is_xlsx: c.is_xlsx,
            category: c.category,
            category_order: c.category_order,
            step_label: c.step_label,
            approval_status: c.approval_status,
            approved_by: c.approved_by,
            approved_at: c.approved_at,
          });
        }
        chainsByHeadRef.current.set(c.chain_head_id, {
          records: synthRecords,
        });
      }
      setGate(body?.gate || {});
      // Monotonic: WS frames may have arrived during the fetch and
      // advanced lastSeenSeq past body.as_of_seq. Never roll backward.
      lastSeenSeqRef.current = Math.max(
        lastSeenSeqRef.current,
        Number(body?.as_of_seq) || 0,
      );
      rebuildChains();
    } catch (e: any) {
      setError(e?.message || "Failed to load the unified product records.");
    } finally {
      setLoading(false);
    }
  }, [rebuildChains]);

  // Subscribe to broadcast WS frames. The unified registry emits
  // session-less frames (no sessionId in payload) so the WS layer
  // hands every subscription every frame — we filter by `type`.
  useEffect(() => {
    const onMessage = (payload: any) => {
      const t = payload?.type;
      const seq = Number(payload?.seq) || 0;
      if (t === "product_record_upsert" && payload.record) {
        if (seq && seq <= lastSeenSeqRef.current) return;
        lastSeenSeqRef.current = Math.max(lastSeenSeqRef.current, seq);
        applyRecordUpsert(chainsByHeadRef.current, payload.record);
        rebuildChains();
      } else if (t === "product_record_delete" && payload.chain_head_id) {
        chainsByHeadRef.current.delete(payload.chain_head_id);
        rebuildChains();
      } else if (t === "product_records_snapshot") {
        // Full reset — wipe + replay.
        chainsByHeadRef.current.clear();
        const records: ProductRecordWire[] = Array.isArray(payload?.records)
          ? payload.records
          : [];
        for (const rec of records) {
          applyRecordUpsert(chainsByHeadRef.current, rec);
        }
        lastSeenSeqRef.current = Math.max(
          lastSeenSeqRef.current,
          Number(payload?.seq) || 0,
        );
        rebuildChains();
      } else if (t === "gate_stats") {
        const { in_use, waiters, budget, headroom, queue_head } = payload;
        setGate({ in_use, waiters, budget, headroom, queue_head });
      }
    };
    // Subscribe under a dummy sessionId — session-less frames go
    // to every subscription, so we just need ONE subscription
    // registered to receive broadcasts.
    const unsub = ws.subscribe("__product_records__", { onMessage });
    return () => {
      // Clean up subscription AND reset local seq + chain map so a
      // remount starts from a clean slate. Without this, lastSeenSeqRef
      // persists across mount cycles and would drop early frames that
      // happen to share a seq with the prior session. (The chain map is
      // a ref — its identity persists across React strict-mode double
      // mounts and HMR reloads; clearing it here prevents stale entries
      // from leaking into the next mount before load() repopulates.)
      try {
        unsub();
      } finally {
        chainsByHeadRef.current.clear();
        lastSeenSeqRef.current = 0;
      }
    };
  }, [ws, rebuildChains]);

  // Initial fetch on mount.
  useEffect(() => {
    load();
  }, [load]);

  // Action helpers — REST calls that mutate the registry server-side.
  // The WS broadcast follows; the reducer picks it up automatically.

  const cancel = useCallback(async (recordId: string) => {
    const r = await fetch(
      `/api/products/records/${encodeURIComponent(recordId)}/cancel`,
      { method: "POST" },
    );
    if (!r.ok) {
      throw new Error(`Cancel failed (HTTP ${r.status}).`);
    }
  }, []);

  const retry = useCallback(async (chainHeadId: string, by?: string) => {
    // Attribute the regeneration to whoever clicked Retry so the
    // "generating by" reflects the current user, not the original creator.
    const qs = by ? `?by=${encodeURIComponent(by)}` : "";
    const r = await fetch(
      `/api/products/chains/${encodeURIComponent(chainHeadId)}/retry${qs}`,
      { method: "POST" },
    );
    if (!r.ok) {
      throw new Error(`Retry failed (HTTP ${r.status}).`);
    }
  }, []);

  const remove = useCallback(async (recordId: string) => {
    const r = await fetch(
      `/api/products/records/${encodeURIComponent(recordId)}`,
      { method: "DELETE" },
    );
    if (!r.ok) {
      throw new Error(`Delete failed (HTTP ${r.status}).`);
    }
  }, []);

  return {
    chains,
    gate,
    loading,
    error,
    refresh: load,
    cancel,
    retry,
    delete: remove,
  };
}

export default useProductChains;
