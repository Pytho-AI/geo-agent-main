"use client";

import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DefaultPageLayout } from "../subframe/layouts/DefaultPageLayout";
import { useAppContext } from "../lib/contextLib";
import { clientWarn } from "../lib/clientLog";
import { logAnalystEvent } from "../lib/analystEvent";

// Import geo-agent components
import { GeoAgentProvider, useGeoAgent } from "../geo-agent/GeoAgentProvider";
import { TacticalOverlaysPanel } from "./TacticalOverlaysPanel";
import { GeoAgentMap } from "../geo-agent/components/GeoAgentMap";
// Entity graph surfaces — ORBAT rail, link view (the repurposed
// GraphViewer), catalog/registry editor. The record lives in
// graph_nodes; these panels are its authored-mode UI (design §7).
import { GraphLinkView } from "../geo-agent/components/graph/GraphLinkView";
import { CatalogEditor } from "../geo-agent/components/graph/CatalogEditor";
// The map's chat rail hosts the MAP AGENT (ChatPanel → /nl/chat →
// propose/approve geoops). Human-to-human chat is the SHELL's job —
// the edge frame renders its IRC rail (#operationalmap) alongside the
// iframe. During the IRC-ification this slot briefly held a null
// IrcChatPanel stub, which left the NL agent with no reachable surface
// at all; the agent pane owns the slot until the shell-side unified
// agent chat takes over (scratch/docs/agent/map-nl-chat-scope.md
// Step 3).
import { ChatPanel } from "../geo-agent/components/ChatPanel";
import { HistoryPanel } from "../geo-agent/components/HistoryPanel";
import { MapDoctrinalPaint } from "../geo-agent/components/MapDoctrinalPaint";
import { MapCartographicChrome } from "../geo-agent/components/MapCartographicChrome";

// Import geo-agent styles
import "../geo-agent/index.css";

// Get the geo-agent API URL from environment
// Relative path. proxy-app nginx (ui/nginx/nginx.conf) routes `/api/v1/*`
// to http://geo-agent-backend:8000 via the `^~ /api/v1/` location. Same URL
// works from the analyst's networked browser and from the headless Chromium
// running inside docker-api — both hit nginx on whatever origin served the
// SPA. The VITE env var stays as a cross-origin testing override.
// Previous fallback was `http://localhost:9845/api/v1`, which broke every
// non-dev deployment (analyst's localhost ≠ the server).
const GEO_AGENT_API_URL = import.meta.env.VITE_GEO_AGENT_API_URL || "/geo-api/v1";

/**
 * Stash product_type on the MapLibre instance so useMapInstance.loadMapState
 * can read it (it runs from the map load handler before any async fetch
 * resolves). Same pattern as OperationsMapHeadless.
 */
function ProductTypeStash({ mapMeta }: { mapMeta: any }) {
  const { mapRef } = useGeoAgent();
  useEffect(() => {
    const map = mapRef?.current;
    if (!map) return;
    const productType = (mapMeta?.attrs?.product_type || "").toUpperCase();
    map.__productType = productType;
    // Mirror OperationsMapHeadless's window.__map exposure so parity probes
    // (and the geo-agent's editor-view smoke checks) can introspect map
    // state from the same handle in both views. Harmless in production —
    // it's just a debugging hook on the MapLibre instance.
    (window as any).__map = map;
    try {
      map.triggerRepaint?.();
    } catch {
      /* ignore */
    }
  }, [mapMeta, mapRef]);
  return null;
}

/**
 * Initialize the Contours layer toggle from the map's stored render
 * spec (stashed server-side by the product-generation render,
 * GET /render/spec/{map_uuid}) so a product EDIT session starts with
 * the contour state its exported artifact carries — a product whose
 * schema declares `map_show_topographic_contours: false` opens with
 * the toggle off, one declaring true opens with it on. The analyst can
 * still flip the toggle afterward. 404 (never product-rendered, e.g. a
 * project master map) means no product presets: the toggle keeps its
 * default (ON) / persisted state. Product-agnostic — no product_type
 * switch; the stored spec IS the product's declared configuration.
 * Headless renders never touch this path (they follow the ?contours=
 * URL primitive only).
 */
function RenderSpecStash({ mapId }: { mapId?: string }) {
  const { mapLoaded, setLayerVisibility } = useGeoAgent();
  useEffect(() => {
    // Gate on mapLoaded so this lands AFTER the provider's persisted
    // layer_visibility merge — the product spec should win the initial
    // state in an edit session, with the analyst's later clicks on top.
    if (!mapId || !mapLoaded) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${GEO_AGENT_API_URL}/render/spec/${mapId}`);
        if (!res.ok) return; // 404 = no product presets — keep defaults
        const spec = await res.json();
        if (cancelled) return;
        const specContours = spec?.show_topographic_contours;
        if (typeof specContours === "boolean") {
          setLayerVisibility((prev: any) => ({ ...prev, contours: specContours }));
        }
      } catch (err) {
        clientWarn("OperationsMap.render_spec_fetch", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mapId, mapLoaded, setLayerVisibility]);
  return null;
}

/**
 * Inner map content that uses the GeoAgent context
 */
function MapContent({
  mapMeta,
  mapId,
  editSession,
  editLabel,
  doRender,
}: {
  mapMeta: any;
  mapId?: string;
  // Embedded edit session (?editEnabled=1 iframe). ALL edit chrome — the
  // banner + Done editing button — is map chrome and renders HERE; the
  // embedding parent holds none. Done posts `geoagent.editDone` up.
  editSession?: boolean;
  editLabel?: string;
  // ?render=1 — this product embeds a rendered image, so Done triggers
  // geo-agent's OWN export pipeline (POST /render replay+persist, base
  // spec = the last generation render, override = the session basemap;
  // the analyst's layer toggles are already persisted on the map record)
  // and the done hook carries the persisted image URL. Without it, Done
  // is hook-only — nothing renders for live-map-only products.
  doRender?: boolean;
}) {
  const { showHistoryPanel, baseMapStyle, userId: ctxUserId, showChatPanel } = useGeoAgent();
  const [doneState, setDoneState] = useState<"idle" | "rendering" | "error">("idle");
  // Entity-graph surfaces. ?focus=<graph_nodes uuid> deep-links the
  // link view onto an entity (UnitMetadataPanel's graph_viewer_url
  // mechanism, re-keyed from cougaar kbids to record uuids).
  const [graphSearchParams] = useSearchParams();
  const qsGraphFocus = graphSearchParams.get("focus") || "";
  const [showLinkView, setShowLinkView] = useState(!!qsGraphFocus);
  const [showCatalog, setShowCatalog] = useState(false);
  const [graphFocusId, setGraphFocusId] = useState(qsGraphFocus);
  useEffect(() => {
    // UnitMetadataPanel's "View relationships" dispatches this for
    // entity_graph-sourced units (the in-app link view replaces the
    // cougaar-era shell graph viewer for record rows).
    const open = (e: any) => {
      setGraphFocusId(e?.detail?.id || "");
      setShowLinkView(true);
    };
    window.addEventListener("geoagent:openLinkView", open);
    return () => window.removeEventListener("geoagent:openLinkView", open);
  }, []);

  // Equipment deep-link: a placard equipment row click opens the
  // catalog focused on that system's WEG sheet.
  const [catalogFocusWegId, setCatalogFocusWegId] = useState("");
  useEffect(() => {
    const open = (e: any) => {
      setCatalogFocusWegId(e?.detail?.weg_id || "");
      setShowCatalog(true);
    };
    window.addEventListener("geoagent:openCatalog", open);
    return () => window.removeEventListener("geoagent:openCatalog", open);
  }, []);

  // Analyst identity — sidebar attribution and telemetry read it off
  // the app context (standalone dev) or the ?user_id/?email iframe
  // params via the provider.
  const { user } = useAppContext() || ({} as any);
  const userEmail: string = (user?.email || user?.userId || "") as string;

  // Edit session Done: geo-agent renders ITSELF (when
  // doRender) via replay of the last generation spec + the session's
  // basemap override, persists the JPG, then posts the done hook up. The
  // parent's ONLY job is the document-side embed (download image_url,
  // swap into the DOCX/PPTX) — it never triggers a render.
  const onEmbeddedDone = async () => {
    if (doneState === "rendering") return;
    logAnalystEvent({
      event_type: "edit_session.done",
      user_id: (ctxUserId as string) || userEmail || null,
      map_id: mapId ? String(mapId) : null,
      surface: "edit_session",
      detail: { render: !!doRender, basemap: baseMapStyle },
    });
    const payload: any = { type: "geoagent.editDone", map_id: mapId, rendered: false };
    if (doRender && mapId) {
      setDoneState("rendering");
      try {
        const res = await fetch(`${GEO_AGENT_API_URL}/render`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            map_uuid: mapId,
            replay: true,
            persist: true,
            basemap: baseMapStyle,
          }),
        });
        if (!res.ok) throw new Error(`render ${res.status}`);
        payload.rendered = true;
        payload.image_url = `${GEO_AGENT_API_URL}/render/latest/${mapId}.jpg`;
      } catch (err) {
        clientWarn("OperationsMap.editDone_render", err);
        payload.error = String(err);
        setDoneState("error");
        // Still post the hook — the parent closes the overlay and surfaces
        // the error; the document keeps its previous image.
        window.parent.postMessage(payload, "*");
        return;
      }
      setDoneState("idle");
    }
    window.parent.postMessage(payload, "*");
  };

  // Outer div fills its positioned parent (set up by the page wrapper as
  // `position: relative; flex: 1 1 0%; min-height: 0`) via absolute inset-0
  // rather than `h-full`. h-full in the editor route's nested flex chain
  // intermittently resolves to 0px before MapLibre's canvas-container
  // initializes, which leaves doctrinal SVG paint with a zero-height target.
  // Absolute positioning gives MapLibre and `.map-container` (which is
  // `position: absolute; inset: 0`) a known-size positioned ancestor.
  // The map column is a flex centering container so the inner 16:9 aspect-
  // ratio wrapper can sit in the middle with letterbox space above/below
  // (or pillarbox left/right) when the available column doesn't match the
  // doctrinal 16:9 framing. The aspect-ratio target mirrors the headless
  // renderer's RenderOptions default (1920x1080 = 1.78:1) which itself
  // mirrors the DOCX landscape map area (~10 x 5.5 in) + PPTX 16:9 slide
  // embed targets defined in ATP 2-01.3. Analysts see the SAME framing the
  // exporter captures; no surprise crop at embed time.
  //
  // The inner positioned wrapper (position: relative) keeps the existing
  // canvas-h0 chain working: GeoAgentMap's `.map-container` still resolves
  // via `position: absolute; inset: 0` against this aspect-ratio box.
  return (
    // Inline styles throughout this layout: geo-agent's build has NO
    // tailwind, so utility classNames here are dead weight (the ported
    // markup relied on the shell app's CSS — the rail rendered as
    // unstyled block flow and the map canvas swallowed its clicks).
    <div
      style={{ position: "absolute", inset: 0, minHeight: 0, display: "flex" }}
    >
      <div
        style={{
          position: "relative", flex: "1 1 0%", height: "100%",
          minWidth: 0, overflow: "hidden",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        <div
          className="relative"
          style={{
            // Live operations surface fills the entire column — no 16:9
            // letterbox. The 16:9 framing applies in edit sessions, where
            // the analyst is previewing the exporter's embed target
            // (1920x1080 headless default = DOCX landscape map area /
            // PPTX 16:9 slide embed). The live map is a working surface;
            // analysts want every available pixel, not exporter framing.
            ...(editSession
              ? { aspectRatio: "16 / 9", maxWidth: "100%", maxHeight: "100%", width: "100%" }
              : { width: "100%", height: "100%" }),
          }}
        >
          {editSession && (
            <div
              data-testid="ibl-edit-map-banner"
              style={{
                // Top-CENTER — the MAP OVERLAYS sidebar owns the top-left
                // corner and the map controls own the right edge.
                position: "absolute", top: 12, left: "50%",
                transform: "translateX(-50%)", zIndex: 1000,
                background: "rgba(44,62,80,0.95)", color: "#fff",
                padding: "8px 12px", borderRadius: 4, fontSize: 13,
                display: "flex", alignItems: "center", gap: 12,
                whiteSpace: "nowrap",
              }}
            >
              <span>
                Editing map{editLabel ? <> for <b>{editLabel}</b></> : null}
              </span>
              <button
                type="button"
                onClick={onEmbeddedDone}
                disabled={doneState === "rendering"}
                style={{
                  padding: "4px 10px",
                  background: doneState === "rendering" ? "#7f8c8d" : "#27ae60",
                  color: "#fff", border: 0, borderRadius: 3,
                  cursor: doneState === "rendering" ? "wait" : "pointer",
                }}
              >
                {doneState === "rendering" ? "Rendering…" : "Done editing"}
              </button>
              {doneState === "error" && (
                <span style={{ color: "#e74c3c" }}>
                  Render failed — document keeps its previous map image.
                </span>
              )}
            </div>
          )}
          <GeoAgentMap />
          {/* Floating map-overlay selector — visibility checkboxes,
              refresh buttons for SITEMP / Threat Overlay, status pills.
              Absolute-positioned over the map's top-left corner like a
              standard cartographic control. Stays mounted in edit
              sessions — toggling what the render shows is the point of
              editing (the toggles persist onto the map record, which the
              Done-render replays). */}
          <TacticalOverlaysPanel mapMeta={mapMeta} userEmail={userEmail} />
          {/* Entity graph is launched from the map control stack
              (MapControls, square icon-btn, clear of the MGRS readout).
              It IS the ORBAT UI — the command tree is its Hierarchy
              layout mode, so there is no separate ORBAT launcher. */}
          {mapId && showLinkView && (
            <GraphLinkView mapId={mapId} userId={userEmail}
                           focusId={graphFocusId || undefined}
                           onOpenCatalog={() => setShowCatalog(true)}
                           onClose={() => setShowLinkView(false)} />
          )}
          {showCatalog && (
            <CatalogEditor mapId={mapId}
                           focusWegId={catalogFocusWegId}
                           onClose={() => { setShowCatalog(false); setCatalogFocusWegId(""); }}
                           onChanged={() => { /* panels refetch on open */ }} />
          )}
          {/* Stash product_type so useMapInstance can drive per-product
              entity dispatch (MCOO/SITEMP/Threat Overlay). */}
          <ProductTypeStash mapMeta={mapMeta} />
          {/* Initialize the Contours layer toggle from the stored render
              spec so a product edit session opens matching its export. */}
          <RenderSpecStash mapId={mapId} />
          {/* Doctrinal SVG paint — AA chevrons, NAI/OBJ/EA point shapes,
              key terrain, choke points, obstacle glyphs, FSCM / boundary /
              BP / AA / ROZ labels, phase-line labels, control-measure
              labels, urban labels, cluster frames, entity labels.
              Mounted inside MapLibre's canvas container with pointer-
              events: none — clicks pass through to the underlying source
              features so the analyst can still drag + edit. */}
          <MapDoctrinalPaint mapMeta={mapMeta} />
          {/* In-frame cartographic chrome (legend + north arrow + scale
              bar). Classification banners, title, prepared-by, AOI inset
              now live in the document layer via _render_header_block —
              no longer painted in the map. */}
          <MapCartographicChrome mapMeta={mapMeta} />
        </div>
      </div>
      {showHistoryPanel && <HistoryPanel />}
      {/* The agent pane (ChatPanel → /nl/chat → propose/approve). Its
          own header carries the title and close button; the TOGGLE
          lives in the map-controls stack (MapControls), so closed
          costs ZERO map width — no reserved gutter. Human-to-human
          chat is the SHELL's rail beside the iframe, never this slot.
          Explicit zIndex — the MapLibre canvas eclipses unstacked
          siblings and swallows their clicks (same failure the history
          panel had). */}
      {showChatPanel && (
        <div
          data-testid="map-agent-column"
          style={{
            position: "relative", zIndex: 20, flex: "0 0 360px",
            height: "100%", display: "flex", flexDirection: "column",
          }}
        >
          <ChatPanel />
        </div>
      )}
    </div>
  );
}

/**
 * Operations Map page — THE map surface for every embed mode.
 *
 * Query-string contract (consumers only assemble URLs; all map UI and
 * mode logic lives here):
 * - `map_id`       → GeoAgentProvider's `mapId` so the right overlay loads.
 * - `bbox`         → converted to center+zoom; consumed by `defaultCenter`
 *                     and `defaultZoom`. The provider's saved viewport
 *                     supersedes it when one exists.
 * - `editEnabled=1`→ edit session: edit affordances mount, and the edit
 *                     chrome (the "Editing map for …" banner + Done
 *                     editing button) renders IN-MAP. On Done we post
 *                     `geoagent.editDone` up to the embedding parent —
 *                     its only job is the document-side embed.
 * - `render=1`     → this product embeds a rendered image: Done triggers
 *                     geo-agent's OWN export render (POST /render
 *                     replay+persist) and the done hook carries
 *                     `image_url`. Without it Done is hook-only.
 * - `product_type` → banner label + per-product doctrinal gating.
 */
export default function OperationsMap() {
  const { user } = useAppContext();
  const [searchParams] = useSearchParams();
  const [mapMeta, setMapMeta] = useState<any>(null);

  const qsMapId = searchParams.get("map_id") || "";
  const qsBbox = searchParams.get("bbox") || "";
  const qsEditEnabled = searchParams.get("editEnabled") === "1";
  const qsRender = searchParams.get("render") === "1";
  const qsProductType = searchParams.get("product_type") || "";
  // Embedding shell's graph-viewer URL — the shell declares the surface
  // by passing it; absent means the shell has no graph viewer and unit
  // "View data source" deep links stay hidden.
  const qsGraphViewerUrl = searchParams.get("graph_viewer_url") || "";
  // Embedding consumers (DocEditor edit overlay, project iframes) pass
  // the analyst's identity as ?user_id= — inside the iframe there is
  // no auth context, so the param takes precedence. Feeds created_by
  // on entity/overlay writes AND user attribution on analyst_events.
  const qsUserId = searchParams.get("user_id") || "";
  const effectiveUserId =
    qsUserId || (user?.userId as string) || (user?.email as string) || "";

  // Map identity comes from the CONSUMER: maps are scoped per
  // PROJECT/EVENT (the event map's id IS the projectId — pytho-vite
  // 2a606a2 is the canonical linkage), so every embed passes ?map_id=
  // and this page never guesses. There is deliberately NO fallback of
  // any kind — not per-user (users.map_id is dead), not per-deployment
  // (VITE_DEFAULT_MAP_ID is dead), not a hardcoded constant: a guessed
  // id silently lands the analyst on the wrong map, which is worse
  // than no map. Without ?map_id= this page renders the notice below.
  // A brand-new project needs no seeding: the backend's
  // GET /maps/{id} materializes a blank map on first open.
  const mapId = qsMapId || "";

  // Persistent audit: one row per map open (and one per edit-session
  // open) — the anchor event every other action on this map follows in
  // the analyst_events timeline.
  useEffect(() => {
    logAnalystEvent({
      event_type: qsEditEnabled ? "edit_session.opened" : "map.opened",
      user_id: effectiveUserId || null,
      map_id: mapId ? String(mapId) : null,
      surface: qsEditEnabled ? "edit_session" : "map",
      detail: {
        product_type: qsProductType || null,
        bbox: qsBbox || null,
        render: qsRender,
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapId, qsEditEnabled]);

  // Fetch map metadata so MapDoctrinalPaint and MapCartographicChrome
  // can gate on product_type (MCOO / SITEMP / Threat Overlay). Mirrors
  // the same fetch in OperationsMapHeadless.
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
        clientWarn("OperationsMap.map_meta_fetch", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mapId]);

  // Parse bbox "west,south,east,north" into a centre. Width-based zoom is a
  // rough approximation — the saved viewport (when present) supersedes this
  // once the provider loads it. Falls back to the map record's stored bbox
  // (from mapMeta) when ?bbox= is missing, and only to the geo-agent provider's
  // hardcoded center (which is Taiwan) as last resort. Without this fallback
  // an "Edit map" click from a DocEditor figure whose data-bbox is empty
  // (older artifacts, pre-spatial_overlay_bbox-fix) lands in Taiwan.
  let defaultCenter: [number, number] | undefined;
  let defaultZoom: number | undefined;
  const bboxParts: number[] | null = (() => {
    if (qsBbox) {
      const p = qsBbox.split(",").map((s) => parseFloat(s.trim()));
      if (p.length === 4 && p.every((n) => Number.isFinite(n))) return p;
    }
    if (mapMeta && [mapMeta.bbox_west, mapMeta.bbox_south,
                    mapMeta.bbox_east, mapMeta.bbox_north].every(
                      (v) => typeof v === "number" && Number.isFinite(v))) {
      return [mapMeta.bbox_west, mapMeta.bbox_south,
              mapMeta.bbox_east, mapMeta.bbox_north];
    }
    return null;
  })();
  if (bboxParts) {
    const [w, s, e, n] = bboxParts;
    defaultCenter = [(w + e) / 2, (s + n) / 2];
    const span = Math.max(Math.abs(e - w), Math.abs(n - s));
    // log-style mapping from bbox span (degrees) to MapLibre zoom.
    // span ≈ 360 → z 0;  span ≈ 1 → z ~8;  span ≈ 0.01 → z ~14.
    defaultZoom = span > 0 ? Math.max(2, Math.min(16, Math.round(Math.log2(360 / span)))) : 10;
  }

  // Layout note: DefaultPageLayout's page-content slot is
  //   `flex grow shrink-0 basis-0 flex-col items-start gap-4 self-stretch
  //    overflow-y-auto bg-default-background`.
  // The map needs a sized, positioned parent so `.map-container`
  // (`position:absolute; inset:0` from geo-agent/index.css) can fill it. A
  // naive `h-full` child of the page-content slot does NOT propagate pixel
  // height reliably — the `overflow-y-auto` + `items-start` combination lets
  // descendants resolve to 0px tall before MapLibre and the doctrinal SVG
  // paint pass mount. (Symptom: `.maplibregl-canvas-container` has
  // `getBoundingClientRect().height === 0` at paint time; the doctrinal SVG
  // exists with width/height attrs but ends up with 0 children because every
  // projected glyph lands outside the zero-height viewport.) Explicit
  // pixel-based sizing via `style={{ flex: 1, minHeight: 0 }}` plus
  // `position: relative` gives `.map-container` a sized positioned ancestor
  // independent of the flex-chain quirk; the inner MapContent then resolves
  // h-full against this fixed-size wrapper. Combined with the ResizeObserver
  // in MapDoctrinalPaint (which calls `map.resize()` + repaints when the
  // container's pixel size changes), the doctrinal overlays paint reliably
  // even when the layout settles after MapLibre's first mount.
  // Opened with no map identity (direct URL, not from an event) — an
  // analyst-facing notice, never a guessed map. No system internals in
  // the copy: the analyst's remedy is opening the map from their event,
  // not learning about URL parameters.
  if (!mapId) {
    return (
      <DefaultPageLayout>
        <div
          className="w-full"
          style={{
            flex: "1 1 0%",
            minHeight: 0,
            alignSelf: "stretch",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div style={{ textAlign: "center", maxWidth: 420, padding: 24 }}>
            <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
              No event selected
            </div>
            <div style={{ fontSize: 14, opacity: 0.75, lineHeight: 1.5 }}>
              Each event has its own operations map. Open the map from an
              event workspace to see it here.
            </div>
          </div>
        </div>
      </DefaultPageLayout>
    );
  }

  return (
    <DefaultPageLayout>
      <div
        className="w-full"
        style={{
          position: "relative",
          flex: "1 1 0%",
          minHeight: 0,
          alignSelf: "stretch",
        }}
      >
        <GeoAgentProvider
          apiUrl={GEO_AGENT_API_URL}
          mapId={mapId}
          userId={effectiveUserId}
          // editEnabled flips the read-only operations-map surface into an
          // editable map (?editEnabled=1 on the embedding iframe URL).
          editEnabled={qsEditEnabled}
          shellGraphViewerUrl={qsGraphViewerUrl}
          {...(defaultCenter ? { defaultCenter } : {})}
          {...(defaultZoom !== undefined ? { defaultZoom } : {})}
        >
          <MapContent
            mapMeta={mapMeta}
            mapId={mapId}
            editSession={qsEditEnabled}
            editLabel={qsProductType || undefined}
            doRender={qsRender}
          />
        </GeoAgentProvider>
      </div>
    </DefaultPageLayout>
  );
}
