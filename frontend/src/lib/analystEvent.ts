// Analyst-action telemetry → POST /geo-api/v1/events (geo-agent's OWN
// persistent audit sink — the analyst_events table in the stack's
// PostGIS, so the record survives container recreates).
//
// The earlier consumer-relative /api/analyst_event path only existed
// behind one consumer's proxy and 404'd on standalone deployments; a
// standalone service logs to itself. STRICTLY fire-and-forget — this
// must NEVER throw, block, or otherwise affect the analyst's UX. A
// telemetry failure is silent.
//
// Relative URL keeps it protocol-agnostic (works under the air-gapped
// HTTPS deployment and plain-HTTP dev alike; the backend serves
// /geo-api/* natively, so it also works with no proxy at all).

export interface AnalystEventInput {
  event_type: string;
  user_id?: string | null;
  map_id?: string | null;
  surface?: string | null;
  product_type?: string | null;
  session_id?: string | null;
  artifact_id?: string | null;
  value_num?: number | null;
  detail?: Record<string, unknown> | null;
}

const EVENTS_URL = "/geo-api/v1/events";

export function logAnalystEvent(evt: AnalystEventInput): void {
  try {
    // Fold the legacy top-level extras into detail so the audit row
    // keeps them without per-field backend columns.
    const { product_type, session_id, artifact_id, value_num, ...rest } = evt;
    const detail: Record<string, unknown> = { ...(evt.detail ?? {}) };
    if (product_type != null) detail.product_type = product_type;
    if (session_id != null) detail.session_id = session_id;
    if (artifact_id != null) detail.artifact_id = artifact_id;
    if (value_num != null) detail.value_num = value_num;
    const body = JSON.stringify({
      ...rest,
      detail,
      occurred_at_ms: Date.now(),
    });
    // sendBeacon survives page unload — important for abandonment / navigation
    // events. Falls back to a keepalive fetch when unavailable.
    if (
      typeof navigator !== "undefined" &&
      typeof navigator.sendBeacon === "function"
    ) {
      const ok = navigator.sendBeacon(
        EVENTS_URL,
        new Blob([body], { type: "application/json" }),
      );
      if (ok) return;
    }
    void fetch(EVENTS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {
      /* swallow — telemetry never affects UX */
    });
  } catch {
    /* swallow — telemetry never affects UX */
  }
}
