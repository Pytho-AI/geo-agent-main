/**
 * Forward frontend errors/warnings to the backend logger.
 *
 * Why this exists:
 *   `console.warn` only shows up in DevTools. Analysts in the field do not
 *   keep DevTools open, so a failed WS reconnect or a swallowed render
 *   exception dies in their browser without ever reaching us. This helper
 *   POSTs the same payload to `/api/client_log`, which routes it through the
 *   normal `pytho.client` logger — same pipeline as the backend errors.
 *
 * Transport priority:
 *   1. navigator.sendBeacon — zero-overhead, survives page unload.
 *   2. fetch keepalive — same survives-unload guarantee, used when the
 *      payload exceeds sendBeacon's 64 KB limit or when sendBeacon is
 *      missing.
 *
 * Failure mode:
 *   ALL errors from this helper are swallowed. If we couldn't tell the
 *   backend, there is nothing else productive we can do client-side, and we
 *   absolutely must not loop (helper throws → we'd try to log THAT error →
 *   we'd loop forever burning the analyst's battery).
 */

type Level = "debug" | "info" | "warn" | "error";

interface ClientLogPayload {
  level: Level;
  label: string;
  message: string;
  url?: string;
  user_agent?: string;
  stack?: string;
  context?: Record<string, unknown>;
}

function describe(err: unknown): { message: string; stack?: string } {
  if (err instanceof Error) {
    return { message: err.message || err.name || "Error", stack: err.stack };
  }
  if (typeof err === "string") return { message: err };
  try {
    return { message: JSON.stringify(err) };
  } catch {
    return { message: String(err) };
  }
}

function send(level: Level, label: string, message: string,
              opts?: { err?: unknown; context?: Record<string, unknown> }) {
  try {
    const errInfo = opts?.err !== undefined ? describe(opts.err) : null;
    const payload: ClientLogPayload = {
      level,
      label: label.slice(0, 200),
      message: (errInfo ? `${message}: ${errInfo.message}` : message).slice(0, 4000),
      url: typeof window !== "undefined" ? window.location.href : undefined,
      user_agent: typeof navigator !== "undefined" ? navigator.userAgent : undefined,
      stack: errInfo?.stack?.slice(0, 8000),
      context: opts?.context,
    };
    const body = JSON.stringify(payload);
    // geo-agent's OWN sink: routed through the server logger (which
    // persists to the data-volume log file) and stored as a queryable
    // analyst_events row. The earlier consumer-relative /api/client_log
    // path only existed behind one consumer's proxy.
    const url = "/geo-api/v1/events/client-log";
    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function" && body.length < 60_000) {
      const blob = new Blob([body], { type: "application/json" });
      const ok = navigator.sendBeacon(url, blob);
      if (ok) return;
    }
    if (typeof fetch !== "undefined") {
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => { /* swallow */ });
    }
  } catch {
    /* swallow — see header */
  }
}

export function clientWarn(label: string, err: unknown, context?: Record<string, unknown>): void {
  send("warn", label, "", { err, context });
}

export function clientError(label: string, err: unknown, context?: Record<string, unknown>): void {
  send("error", label, "", { err, context });
}

export function clientInfo(label: string, message: string, context?: Record<string, unknown>): void {
  send("info", label, message, { context });
}

export function clientDebug(label: string, message: string, context?: Record<string, unknown>): void {
  send("debug", label, message, { context });
}
