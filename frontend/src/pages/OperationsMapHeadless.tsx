"use client";

/**
 * OperationsMapHeadless - Screenshot-mode mount of the analyst's Operations Map.
 *
 * Loaded by the geo-agent render driver (backend/app/services/render/
 * headless.py) at /geo-app/headless?map_id=... behind POST /api/v1/render.
 * Renders the same <GeoAgentMap> the analyst edits with,
 * with all UI chrome (panels, banners, controls) hidden via the provider's
 * `headless` flag. Sets `window.__renderReady = true` once the map has
 * fully painted, which is the contract Playwright waits on before screenshotting.
 *
 * URL contract (all optional except map_id):
 *   map_id       UUID of the map to render
 *   bbox         "west,south,east,north" — fit-bounds override
 *   w, h         viewport dimensions (informational; Playwright sets the actual
 *                viewport size)
 *   pixel_ratio  device scale factor (informational; Playwright sets DPR)
 *   layers       comma-separated layer-name filter (passed through to the
 *                provider; honored by mapLayers source filters)
 *
 * Intentionally NOT wrapped in DefaultPageLayout / AuthenticatedRoute — this
 * route is for the internal headless renderer only. The geo-agent reaches it
 * over the cluster network; analysts should never navigate here.
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  GeoAgentProvider,
  useGeoAgent,
} from "../geo-agent/GeoAgentProvider";
import { GeoAgentMap } from "../geo-agent/components/GeoAgentMap";
import { MapDoctrinalPaint } from "../geo-agent/components/MapDoctrinalPaint";
import { MapCartographicChrome } from "../geo-agent/components/MapCartographicChrome";

// Same env var the interactive Operations Map page uses, so DEV/PROD parity is
// automatic — the React bundle still points at the geo-agent's /api/v1 surface
// (in the headless render context, that's a service-internal hop, not a
// browser-to-cluster one).
import "../geo-agent/index.css";

// Relative path. proxy-app nginx (ui/nginx/nginx.conf) routes `/api/v1/*`
// to http://geo-agent-backend:8000 via the `^~ /api/v1/` location. Same URL
// works from the analyst's networked browser and from the headless Chromium
// running inside docker-api — both hit nginx on whatever origin served the
// SPA. Previous fallback was `http://localhost:9845/api/v1`, which broke
// every non-dev deployment (analyst's localhost ≠ the server, headless
// Chromium's localhost ≠ a service).
const GEO_AGENT_API_URL =
  (import.meta as any).env?.VITE_GEO_AGENT_API_URL ||
  "/geo-api/v1";

// ----------------------------------------------------------------------
// Schema-driven map render primitives forwarded from intel_agent
// tool_render_map → render/headless.py URL builder → this component.
// Every per-product behavior the frontend used to switch on productType
// is now a value in this RenderConfig, populated from the active product
// schema's map_* fields (templates/products/*.py). The frontend reads
// these as primitives only --- there is no per-product switch in any
// client code; every layer reads its config off map.__renderConfig.
//
// Keys mirror the URL param names emitted by render/headless.py
// _build_url so the frontend never re-derives or maps schema → URL → JS.
// ----------------------------------------------------------------------
export type RenderConfig = {
  // Tileserver style id for the basemap raster. One of "default" /
  // "terrain" / "topo" / "satellite".
  basemap: string | null;
  // Allowed overlay/entity kinds — features whose properties.kind is NOT
  // in this set are filtered out before paint. From schema
  // `map_overlay_kinds`. null = no filter applied (analyst-edit default).
  allowedKinds: Set<string> | null;
  // OMT vector basemap MapLibre layer ids that should be visible.
  // Anything else gets visibility='none'. From schema
  // `map_basemap_layer_visibility`. null = no preset (all visible).
  basemapLayers: Set<string> | null;
  // Doctrinal-MCOO MapLibre layer ids that should be visible. From schema
  // `map_doctrinal_layer_visibility`. null = no preset.
  doctrinalLayers: Set<string> | null;
  // SITEMP-style zoom-tiered topographic contour overlay (Z>=11 100m,
  // Z>=12 50m, Z>=13 20m, Z>=14 10m). From schema
  // `map_show_topographic_contours`. null = analyst-edit default (off).
  showContours: boolean | null;
  // Cluster individual mil_unit features into echelon icons (bn/bde).
  // From schema `map_cluster_mil_units`. null = analyst-edit default.
  clusterUnits: boolean | null;
  // Compact AA labels along the chevron. From schema
  // `map_compact_aa_labels`. null = analyst-edit default.
  compactAaLabels: boolean | null;
  // Compact legend packing. From schema `map_compact_legend_labels`.
  // null = analyst-edit default.
  compactLegendLabels: boolean | null;
};

function parseBoolParam(v: string | null): boolean | null {
  if (v === null) return null;
  if (v === "1" || v.toLowerCase() === "true") return true;
  if (v === "0" || v.toLowerCase() === "false") return false;
  return null;
}

function parseSetParam(v: string | null): Set<string> | null {
  if (!v) return null;
  return new Set(v.split(",").map((s) => s.trim()).filter(Boolean));
}

/**
 * Inner — runs inside the provider so it can observe mapLoaded /
 * milSymRendererReady from context. When both are true AND we've held an
 * idle for a few repaint cycles (matches render.html's waitForFullPaint),
 * flip window.__renderReady.
 *
 * The 3-cycle idle dance is required because MapLibre raises 'idle' as
 * soon as the current frame is queued, BEFORE any deferred raster/symbol
 * layers (mil-sym-ts SVG sprites, hatch-pattern addImage) re-trigger a
 * repaint. Three back-to-back idles guarantee the deferred work has had
 * time to land on the canvas.
 */
function HeadlessReadySignal({
  bbox,
  renderConfig,
}: {
  bbox: number[] | null;
  renderConfig: RenderConfig;
}) {
  const { mapRef, mapLoaded, milSymRendererReady, savedViewport } =
    useGeoAgent();
  const firedRef = useRef(false);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (firedRef.current) return;
    const map = mapRef.current;
    if (!map) return;
    if (!mapLoaded) return;
    // mil-sym-ts may still be loading its symbol catalog. Wait. If it
    // never reports ready within the Playwright timeout, the outer
    // wait_for_function will trip — we don't want to ship a half-painted
    // PNG.
    if (!milSymRendererReady) return;

    let cancelled = false;

    // Earlier this awaited 3 `idle` events from MapLibre via
    // `map.once("idle", tick)`. Two failure modes made it hang forever:
    //   1) If the map had already reached idle by the time the listener
    //      registered (common in headless: style.load fires, mil-sym
    //      ready fires synchronously, useEffect runs in the same task,
    //      idle has already passed), `once` waited for the NEXT idle
    //      that never came.
    //   2) `triggerRepaint()` between cycles doesn't guarantee a fresh
    //      idle event — if nothing actually re-rendered, the loop stalls.
    // Then we tried a rAF-paced poll with a 600 ms floor; that worked
    // but burned ~600 ms on every render even when the map was already
    // painted. Replace with: check current load state, if already painted
    // skip straight to 2 rAFs; otherwise wait for the next `idle` event
    // (which IS reliable now because we proved the map isn't idle yet)
    // with a 4 s ceiling. 2 rAFs at the end covers MapLibre GL composite
    // + SVG overlay reflow + scale-bar / legend DOM commit.
    const waitForFullPaint = (): Promise<void> =>
      new Promise<void>((resolve) => {
        if (cancelled) return resolve();
        let alreadyPainted = false;
        try {
          alreadyPainted =
            !!map.loaded?.() &&
            (typeof map.areTilesLoaded === "function"
              ? map.areTilesLoaded()
              : true);
        } catch {
          return resolve();
        }
        const flushTwoFrames = () => {
          requestAnimationFrame(() => {
            requestAnimationFrame(() => resolve());
          });
        };
        if (alreadyPainted) {
          flushTwoFrames();
          return;
        }
        let settled = false;
        const settle = () => {
          if (settled) return;
          settled = true;
          try { map.off("idle", onIdle); } catch { /* ignore */ }
          clearTimeout(ceiling);
          if (cancelled) return resolve();
          flushTwoFrames();
        };
        const onIdle = () => settle();
        const ceiling = setTimeout(settle, 4000);
        map.on("idle", onIdle);
      });

    (async () => {
      try {
        // If a bbox was supplied via URL, ensure we're framed there before
        // we declare ready. The map constructor was given the same bounds,
        // but on slow loads MapLibre may not have hit the fitBounds before
        // 'load' fires.
        if (bbox && bbox.length === 4) {
          try {
            // padding=0 for headless so the AOR fits edge-to-edge in the
            // viewport — any padding here yields a basemap halo around the
            // doctrinal paint that the analyst-edit view doesn't have to
            // care about (it's a 16:9 wrapper with paddings elsewhere).
            map.fitBounds(
              [
                [bbox[0], bbox[1]],
                [bbox[2], bbox[3]],
              ],
              { padding: 0, duration: 0, animate: false },
            );
          } catch {
            /* non-fatal — initial map options already passed bounds */
          }
        }

        await waitForFullPaint();
        if (cancelled) return;
        // ALSO wait for the doctrinal SVG paint pass to have produced
        // visible output. `idle` fires before applyDoctrinalControlMeasures
        // populates the per-product feature stashes, so MapDoctrinalPaint's
        // first repaint runs with empty data; the catch-up repaint on
        // `sourcedata` arrives AFTER waitForFullPaint resolves and the
        // screenshot would otherwise capture a basemap-only frame.
        // MapDoctrinalPaint flips window.__doctrinalPainted = true the
        // first time it actually draws children. 4 s ceiling so a SITEMP
        // with no entities still resolves.
        await new Promise<void>((resolve) => {
          if ((window as any).__doctrinalPainted === true) return resolve();
          const start = performance.now();
          const ceilingMs = 4000;
          const tick = () => {
            if (cancelled) return resolve();
            if ((window as any).__doctrinalPainted === true) return resolve();
            if (performance.now() - start >= ceilingMs) return resolve();
            requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        });
        if (cancelled) return;
        // Spot heights resolve ASYNCHRONOUSLY (MapDoctrinalPaint's
        // _refreshSpotHeights fetches /terrain/peaks for the viewport
        // and setDatas the label source). When the render wants the
        // contour/spot-height treatment, wait for that first fetch to
        // publish — otherwise the screenshot races the response and
        // exports without the peak labels. Settled = a viewport
        // signature has been published and no fetch is in flight.
        // 6 s ceiling so a peaks-endpoint outage degrades to a render
        // without spot heights instead of a hang.
        if (renderConfig.showContours === true) {
          await new Promise<void>((resolve) => {
            const start = performance.now();
            const ceilingMs = 6000;
            const settled = () =>
              (map as any).__spotHeightsSig != null &&
              !(map as any).__spotHeightsInflight;
            const tick = () => {
              if (cancelled) return resolve();
              if (settled()) return resolve();
              if (performance.now() - start >= ceilingMs) return resolve();
              setTimeout(tick, 100);
            };
            tick();
          });
        }
        if (cancelled) return;
        // Mil-unit icons are painted by the synchronous SVG dispatch in
        // paintTacticalGraphics (PRIMITIVE_DRAWERS mil_unit). They appear
        // inside the __doctrinalPainted gate above — no separate readiness
        // wait needed.
        // Give React one more rAF + a microtask so any state updates
        // queued by the marginalia component (scale-bar km/mi values
        // computed off map.unproject after mapLoaded) have committed
        // their DOM before the screenshot. Without this the scale bar
        // can flash "0 km / 0 mi" on a slow first-render.
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        });
        if (cancelled) return;
        // Surface the map instance for headless probes (e.g. smoke tests
        // that need to call map.project / map.queryRenderedFeatures to
        // verify that doctrinal layers exist and are pickable). Harmless
        // in production headless render — Playwright tears the page down.
        (window as any).__map = map;
        // Surface the signal Playwright is waiting on.
        (window as any).__renderReady = true;
      } catch (err) {
        // Even on failure, flip the flag so Playwright doesn't hang —
        // the screenshot will simply capture whatever made it to the canvas.
        // The error is surfaced via console for the headless runner's
        // pageerror/console listener.
        // eslint-disable-next-line no-console
        console.error("headless: ready-signal wait failed", err);
        (window as any).__renderReady = true;
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapLoaded, milSymRendererReady, savedViewport, bbox]);

  // Re-render once when the map first reports ready. Otherwise we'd never
  // observe the latch transition.
  useEffect(() => {
    setTick((n) => n + 1);
  }, [mapLoaded, milSymRendererReady]);

  return null;
}

function HeadlessRenderConfigStash({
  mapMeta,
  renderConfig,
}: {
  mapMeta: any;
  renderConfig: RenderConfig;
}) {
  // Stash the SCHEMA-DRIVEN render config on the MapLibre instance so
  // every client layer (loadMapState, MapDoctrinalPaint, the cartographic
  // chrome) can read its primitives synchronously from the map handle.
  // Backend `tool_render_map` reads each field off the active product
  // schema and forwards it as a URL primitive (basemap, allowed kinds,
  // basemap layer visibility, doctrinal layer visibility, contour
  // overlay flag, mil-unit cluster mode, label compactness). The frontend
  // treats them all as raw values --- there is no product-type switch
  // in any client code. product_type is preserved as an opaque tag on
  // the instance so multi-map records / analyst-edit can still tell
  // products apart, but client logic is driven by the primitive flags.
  const { mapRef } = useGeoAgent();
  useEffect(() => {
    const map = mapRef?.current;
    if (!map) return;
    const productType = (mapMeta?.attrs?.product_type || "").toUpperCase();
    map.__productType = productType;
    map.__renderConfig = renderConfig;
    try {
      map.triggerRepaint?.();
    } catch {
      /* ignore — map may be torn down */
    }
  }, [mapMeta, renderConfig, mapRef]);
  return null;
}

function HeadlessMapContent({
  bbox,
  mapMeta,
  renderConfig,
}: {
  bbox: number[] | null;
  mapMeta: any;
  renderConfig: RenderConfig;
}) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        overflow: "hidden",
        background: "#fff",
      }}
    >
      <GeoAgentMap bounds={bbox ?? undefined} />
      {/* Stash the schema-driven render config + product_type on the
          map instance so every client layer reads primitives, no
          product-type switches anywhere. */}
      <HeadlessRenderConfigStash mapMeta={mapMeta} renderConfig={renderConfig} />
      <MapDoctrinalPaint mapMeta={mapMeta} />
      {/* In-frame cartographic chrome (legend + north arrow + scale bar). */}
      <MapCartographicChrome mapMeta={mapMeta} />
      <HeadlessReadySignal bbox={bbox} renderConfig={renderConfig} />
    </div>
  );
}

export default function OperationsMapHeadless() {
  const [searchParams] = useSearchParams();
  const [mapMeta, setMapMeta] = useState<any>(null);

  // Parse all params once per search-string change.
  const { mapId, bbox, productTypeOverride, renderConfig } = useMemo(() => {
    // No fallback id: the only caller is render/headless.py, which
    // always forwards the required map_uuid. A missing param is a
    // caller bug — surfaced by the guard below, never masked by
    // rendering some other map.
    const id = searchParams.get("map_id") || "";
    const bboxParam = searchParams.get("bbox");
    let parsedBbox: number[] | null = null;
    if (bboxParam) {
      const parts = bboxParam.split(",").map((v) => parseFloat(v));
      if (parts.length === 4 && parts.every((v) => Number.isFinite(v))) {
        parsedBbox = parts;
      }
    }
    // Per-render product_type override (set by intel_agent.tool_render_map).
    // Lets one master map serve every doctrinal product. Kept as an
    // opaque tag for backwards compatibility / multi-map record routing;
    // ALL per-product render behavior is now driven through the
    // schema-primitive fields below, NOT through frontend switches on
    // this value.
    const productTypeOverride = (
      searchParams.get("product_type") || ""
    ).toUpperCase() || null;
    // Schema-driven render config — every per-product behavior the
    // frontend used to switch on productType lives here as a primitive,
    // populated from the active product schema (templates/products/
    // *.py map_* fields) by intel_agent.tool_render_map and forwarded
    // as a URL primitive by render/headless.py _build_url.
    const renderConfig: RenderConfig = {
      basemap: searchParams.get("basemap") || null,
      allowedKinds: parseSetParam(searchParams.get("layers")),
      basemapLayers: parseSetParam(searchParams.get("basemap_layers")),
      doctrinalLayers: parseSetParam(searchParams.get("doctrinal_layers")),
      showContours: parseBoolParam(searchParams.get("contours")),
      clusterUnits: parseBoolParam(searchParams.get("cluster_units")),
      compactAaLabels: parseBoolParam(searchParams.get("compact_aa")),
      compactLegendLabels: parseBoolParam(searchParams.get("compact_legend")),
    };
    return { mapId: id, bbox: parsedBbox, productTypeOverride, renderConfig };
  }, [searchParams]);

  // Reset the ready flag on every mount so consecutive Playwright sessions
  // sharing a process (shouldn't happen with on-demand Chromium, but safe)
  // don't see a stale `true`. Same reset on __doctrinalPainted so the
  // doctrinal-paint wait gate fires fresh on every render.
  useEffect(() => {
    (window as any).__renderReady = false;
    (window as any).__doctrinalPainted = false;
  }, []);

  // Pull full map metadata (name, attrs.product_type, attrs.classification,
  // attrs.aor) so the doctrinal marginalia can render correct title block
  // and legend strip text. Mirrors render.html's fetch at
  // `${apiBase}/maps/${mapId}`. Soft-fails: if the call returns 404 or the
  // network breaks, marginalia falls back to defaults (no banners visible
  // unless we have a product_type).
  useEffect(() => {
    if (!mapId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${GEO_AGENT_API_URL}/maps/${mapId}`);
        if (!res.ok) return;
        const json = await res.json();
        if (!cancelled) setMapMeta(json);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("headless: failed to fetch map meta", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mapId]);

  // If the URL carries ?product_type=..., it wins over whatever the map
  // record has stored in attrs.product_type. Master map serves every product;
  // the URL param tells the paint layer which doctrinal drawer set to fire.
  // Synthesize a minimal mapMeta when the /maps/ fetch hasn't resolved yet
  // so paint can start with the right product_type instead of the Threat Overlay fallback.
  const effectiveMapMeta = useMemo(() => {
    if (!productTypeOverride) return mapMeta;
    const baseMeta = mapMeta ?? {};
    const baseAttrs = (baseMeta as any).attrs ?? {};
    return {
      ...baseMeta,
      attrs: { ...baseAttrs, product_type: productTypeOverride },
    };
  }, [mapMeta, productTypeOverride]);

  // Caller bug surface: render/headless.py always forwards map_uuid, so
  // an empty mapId means a malformed render URL. Render the error text
  // and never flip __renderReady — the render fails loudly on timeout
  // with this message in the failure screenshot, instead of silently
  // exporting some other (or a phantom) map.
  if (!mapId) {
    return (
      <div style={{ padding: 24, fontFamily: "monospace" }}>
        render error: map_id missing from headless URL
      </div>
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        margin: 0,
        padding: 0,
      }}
    >
      <GeoAgentProvider apiUrl={GEO_AGENT_API_URL} mapId={mapId} headless>
        <HeadlessMapContent
          bbox={bbox}
          mapMeta={effectiveMapMeta}
          renderConfig={renderConfig}
        />
      </GeoAgentProvider>
    </div>
  );
}
