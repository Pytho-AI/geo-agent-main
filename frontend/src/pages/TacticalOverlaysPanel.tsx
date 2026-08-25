"use client";

/**
 * Tactical Overlays panel — the operations map's visibility control.
 *
 * Two sections, two concepts (model: geo-agent/utils/featureVisibility):
 *
 * LEGEND — census-driven type toggles over everything currently in
 * view. Entries exist ONLY for types the map actually carries (a chip
 * with nothing behind it is a lie to the analyst): unit symbols,
 * graphics by kind, factions, per-faction categories and range-fan
 * classes. Every toggle is global — hiding "Phase lines" hides every
 * phase line regardless of which pipe produced it. Provenance
 * (attrs.source = 'manual' vs pipeline tokens) never appears here.
 *
 * PRODUCT LAYERS — each row is a product claim-set (one hypothesis's
 * geometry) plus that layer's SAVED legend. Activating a row brings
 * its content into scope and restores its saved legend; legend edits
 * autosave to the ACTIVE collection ('base' when no product layer is
 * active), so every layer remembers how the analyst last viewed it.
 * Persisted per map: attrs.visibility_collections = { base: [...],
 * "SITEMP:COA-2": [...], ... } (arrays of hidden type tokens).
 *
 * Adding a new product requires ZERO code here: its content surfaces
 * through the census, its kinds appear in the legend, its collection
 * materializes on first save.
 */

import React, { useEffect, useRef, useState } from "react";
import * as SubframeCore from "@subframe/core";
import { useGeoAgent } from "../geo-agent/GeoAgentProvider";
import useProductChains from "../lib/useProductChains";
import { clientWarn } from "../lib/clientLog";
import { logAnalystEvent } from "../lib/analystEvent";
import {
  BASE_SOURCES,
  buildBearerAffiliationIndex,
  buildOverlayCensus,
  kindToken,
  typeToken,
  factionToken,
  factionDimToken,
  unitNamesToken,
  UNCATEGORIZED,
} from "../geo-agent/utils/featureVisibility";

// ── Display catalogs — labels only, never presence. Presence comes
// from the census; an unknown token still renders via prettify().
const KIND_LABELS: Record<string, string> = {
  phase_line: "Phase lines",
  engagement_area: "Engagement areas",
  avenue_of_approach: "Avenues of approach",
  axis_of_advance: "Axes of advance",
  threat_objective: "Threat objectives",
  named_area_of_interest: "NAIs",
  targeted_area_of_interest: "TAIs",
  key_terrain: "Key terrain",
  defensible_terrain: "Defensible terrain",
  obstacle_point: "Obstacles",
  boundary: "Boundaries",
  decision_point: "Decision points",
  time_phase_line: "Time phase lines",
  battle_position: "Battle positions",
  urban_area: "Urban areas",
  fortified_area: "Fortified areas",
  assembly_area: "Assembly areas",
  range_fan: "Range fans",
};
const CATEGORY_LABELS: Record<string, string> = {
  command_and_control: "C2 / Signal",
  fire_support: "Fires",
  air_defense_artillery: "Air Defense",
  maneuver: "Maneuver",
  engineer: "Engineer",
  reconnaissance_and_surveillance: "RISTA / Recon",
  cyberspace_electromagnetic_activities: "EW / Cyber",
  sustainment: "Sustainment",
  lift: "Lift",
  [UNCATEGORIZED]: "Other",
};
const SUBKIND_LABELS: Record<string, string> = {
  ada: "Air defense",
  indirect_fire: "Indirect fire / arty",
  mlrs: "MLRS",
  long_range: "Long-range / cruise",
  antitank: "Antitank / ATGM",
};
const prettify = (token: string): string => {
  const t = token.replace(/_/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};
const kindLabel = (k: string) => KIND_LABELS[k] || prettify(k);
const categoryLabel = (c: string) => CATEGORY_LABELS[c] || prettify(c);
const subkindLabel = (s: string) => SUBKIND_LABELS[s] || prettify(s);

// Stable display order for legend kind chips: catalog order first,
// unknown kinds alphabetical after.
const KIND_ORDER = Object.keys(KIND_LABELS);
const kindSort = (a: string, b: string) => {
  const ia = KIND_ORDER.indexOf(a);
  const ib = KIND_ORDER.indexOf(b);
  return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib) || a.localeCompare(b);
};

// ── Product-layer refire endpoints (fire-and-forget 202, ?by= attribution).
// The Threat COAs row fires the DAG entry point whose topological
// closure regenerates the whole threat-analysis set; per-product rows
// refire themselves and the DAG resolves consumes_artifacts deps.
const REFIRE_ENDPOINT_FOR: Record<string, string> = {
  "Threat COAs": "/api/products/threat_coas/refire_chain",
  "Threat Overlay": "/api/products/threat_model/refire_chain",
  "Event Template": "/api/products/event_template/refire_chain",
};
const CHAIN_PRODUCTS = ["Threat Overlay", "Threat COA Statement", "SITEMP", "Threat COAs"];

// Analyst-facing display names for product-layer rows; any token not
// listed shows as itself (source tokens are PRODUCT_SCHEMAS keys, i.e.
// product names).
const PRODUCT_LABELS: Record<string, string> = {
  "Threat Overlay": "Threat Template",
};
// Report-pin feeds — layer tokens, but their rows are probe-gated and
// rendered separately from the census-derived product rows.
const SIGNAL_LAYER_TOKENS = new Set(["live_klieglight", "live_osir"]);

// Fixed doctrinal COA set (IPB Step 4 enumerates 1-4 threat COAs); the
// per-COA rows render unconditionally under the parent so a mid-flight
// failed artifact can never collapse the list.
const COA_IDS = ["COA-1", "COA-2", "COA-3", "COA-4"];

// Echelon roll-up slider stops, low → high (one slider per faction).
const ROLLUP_STOPS: Array<{ value: string; label: string }> = [
  { value: "PLT", label: "PLT" },
  { value: "CO", label: "CO" },
  { value: "BN", label: "BN" },
  { value: "BDE", label: "BDE" },
  { value: "DIV", label: "DIV" },
];

// Legend default when a map has no saved base collection yet: range
// fans hidden (per-equipment fans on a corps-scale feed bury the map;
// opt-in via the Range fans chip).
const DEFAULT_HIDDEN = [kindToken("range_fan")];

interface Census {
  layers: Map<string, number>;
  kinds: Map<string, number>;
  kindsBySource: Map<string, Map<string, number>>;
  factions: Map<string, { units: number; categories: Map<string, number>; subkinds: Map<string, number> }>;
}
const EMPTY_CENSUS: Census = {
  layers: new Map(), kinds: new Map(), kindsBySource: new Map(), factions: new Map(),
};

// ── Shared row/chip styling (dark panel — geo-agent stays dark).
const chipStyle = (off: boolean): React.CSSProperties => ({
  display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer",
  padding: "2px 6px", borderRadius: 3,
  background: off ? "#16181f" : "#1f2230",
  border: `1px solid ${off ? "#2a2c38" : "#3a3a52"}`,
});
const sectionHeaderStyle: React.CSSProperties = {
  padding: "6px 12px 2px", fontSize: 10, textTransform: "uppercase",
  letterSpacing: 0.4, color: "#7a7a8c",
};
const dimHeaderStyle: React.CSSProperties = {
  fontSize: 10, textTransform: "uppercase", letterSpacing: 0.3,
  color: "#7a7a8c", margin: "6px 0 4px",
};
const chevronButtonStyle: React.CSSProperties = {
  background: "transparent", color: "#a0a0b8", border: 0, cursor: "pointer",
  padding: 0, display: "flex", alignItems: "center",
};

export function TacticalOverlaysPanel({
  mapMeta,
  userEmail,
}: {
  mapMeta: any;
  userEmail: string;
}) {
  const {
    enabledLayers, setEnabledLayers,
    hiddenTypes, setHiddenTypes,
    apiUrl, mapId, mapRefreshTrigger, userId, appConfig,
    rollupEchelonByFaction, setRollupEchelonByFaction,
  } = useGeoAgent() as any;

  // ── Census — MAP-scoped world-bbox fetch, deliberately NOT viewport-
  // scoped (paint fetches are bbox'd to the camera; gating the panel on
  // those would make entries vanish when the analyst pans away).
  const [census, setCensus] = useState<Census>(EMPTY_CENSUS);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiUrl}/map/state?map_id=${mapId}&bbox=-180,-85,180,85`);
        if (!res.ok || cancelled) return;
        const data = await res.json();
        const entities = data.entities?.features || [];
        const overlays = data.overlays?.features || [];
        const bearerIndex = buildBearerAffiliationIndex(entities);
        if (!cancelled) {
          setCensus(buildOverlayCensus([...entities, ...overlays], bearerIndex) as Census);
        }
      } catch { /* census is advisory — panel stays minimal on failure */ }
    })();
    return () => { cancelled = true; };
  }, [apiUrl, mapId, mapRefreshTrigger]);

  // ── Signal-report presence (their data lives behind a consumer
  // endpoint, not /map/state; non-200 = absent, correct for cloud).
  const [signalPresence, setSignalPresence] = useState({ klieg: false, osir: false });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/operations/recent_signal_reports?max_age_hours=24");
        if (!res.ok || cancelled) return;
        const body = await res.json();
        const reports: any[] = Array.isArray(body?.reports) ? body.reports : [];
        if (!cancelled) {
          setSignalPresence({
            klieg: reports.some((r) => r?.type === "KLIEGLIGHT"),
            osir: reports.some((r) => r?.type === "OSIR"),
          });
        }
      } catch { /* absent */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // ── Visibility collections — per-layer saved legends.
  const collectionsRef = useRef<Record<string, string[]>>({});
  const [activeCollection, setActiveCollection] = useState<string>("base");
  const seededRef = useRef(false);
  // Immediate seed so the first paint has the right defaults: no
  // product layers in scope, range fans hidden.
  useEffect(() => {
    setEnabledLayers((prev: Set<string> | null) => prev ?? new Set());
    setHiddenTypes((prev: Set<string>) =>
      prev && prev.size > 0 ? prev : new Set(DEFAULT_HIDDEN));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Saved collections arrive with the map record; apply base once.
  useEffect(() => {
    if (seededRef.current) return;
    const saved = mapMeta?.attrs?.visibility_collections;
    if (!saved || typeof saved !== "object") return;
    seededRef.current = true;
    collectionsRef.current = { ...saved };
    if (Array.isArray(saved.base)) {
      setHiddenTypes(new Set(saved.base));
    }
  }, [mapMeta, setHiddenTypes]);

  // Autosave the legend to the active collection (debounced, same
  // shape as the provider's layer-prefs save). Also the audit event —
  // legend flips are analyst actions.
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (!hiddenTypes) return;
    if (!hydratedRef.current) { hydratedRef.current = true; return; }
    collectionsRef.current = {
      ...collectionsRef.current,
      [activeCollection]: Array.from(hiddenTypes as Set<string>),
    };
    const timeout = setTimeout(async () => {
      try {
        await fetch(`${apiUrl}/maps/${mapId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attrs: { visibility_collections: collectionsRef.current } }),
        });
      } catch (err) {
        clientWarn("TacticalOverlaysPanel.save_collections", err);
      }
      logAnalystEvent({
        event_type: "map.visibility_changed",
        user_id: (userId as string) || userEmail || null,
        map_id: mapId ? String(mapId) : null,
        surface: "tactical_overlays",
        detail: {
          collection: activeCollection,
          hidden: Array.from(hiddenTypes as Set<string>),
        },
      });
    }, 500);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hiddenTypes]);

  // ── Legend toggles.
  const isHidden = (token: string) => !!hiddenTypes?.has(token);
  const toggleType = (tokens: string[]) => {
    setHiddenTypes((prev: Set<string>) => {
      const next = new Set(prev);
      const hiding = tokens.some((t) => !next.has(t));
      for (const t of tokens) {
        if (hiding) next.add(t);
        else next.delete(t);
      }
      return next;
    });
  };

  // ── Product-layer activation: scope + saved-legend restore. The
  // radioPrefix clears sibling per-COA layers (two COAs' templated
  // positions painted together read as double the enemy force).
  const layerOn = (token: string) => !!enabledLayers?.has(token);
  const setLayer = (token: string, on: boolean, radioPrefix?: string) => {
    setEnabledLayers((prev: Set<string> | null) => {
      const next = new Set(prev ?? []);
      if (radioPrefix) {
        for (const t of [...next]) if (t.startsWith(radioPrefix)) next.delete(t);
      }
      if (on) next.add(token);
      else next.delete(token);
      return next;
    });
    if (on) {
      setActiveCollection(token);
      const saved = collectionsRef.current[token];
      if (Array.isArray(saved)) setHiddenTypes(new Set(saved));
      // No saved collection yet → the layer inherits the current
      // legend; the first autosave materializes its collection.
    } else if (activeCollection === token) {
      setActiveCollection("base");
      const base = collectionsRef.current.base;
      if (Array.isArray(base)) setHiddenTypes(new Set(base));
    }
  };

  // ── Product chain state (pills + refire).
  const { chains } = useProductChains();
  const chainStateFor = (): "idle" | "generating" => {
    for (const c of chains) {
      if (!CHAIN_PRODUCTS.includes(c.product_type)) continue;
      if (c.state === "running") return "generating";
    }
    return "idle";
  };
  const stateFor = (productType: string, coaId?: string): "idle" | "generating" => {
    for (const c of chains) {
      if (c.product_type !== productType) continue;
      if (coaId) {
        const sm = (c.source_metadata as any) || {};
        const cCoa = (sm.coa_id || c.coa_id || "").toString();
        if (cCoa !== coaId) continue;
      }
      if (c.state === "running") return "generating";
    }
    return "idle";
  };
  const onRefire = (productType: string) => {
    const url = REFIRE_ENDPOINT_FOR[productType];
    if (!url) return;
    const by = userEmail || "";
    fetch(url + (by ? `?by=${encodeURIComponent(by)}` : ""), { method: "POST" }).catch(
      (err) => clientWarn("TacticalOverlaysPanel.refire_failed", err));
  };

  // ── Derived legend content.
  const graphicsKinds = [...census.kinds.keys()]
    .filter((k) => k !== "mil_unit" && k !== "range_fan")
    .sort(kindSort);
  // Kind -> {category, label} from the overlay draw catalog
  // (backend /config overlayTypes; same source the draw toolbar groups
  // by). Kinds outside the catalog fall into "Other" with a prettified
  // label so nothing on the map is ever unlisted.
  const kindCatalog: Record<string, { category?: string; label?: string }> = {};
  const overlayTypeLists = (appConfig as any)?.overlayTypes;
  for (const list of [overlayTypeLists?.line, overlayTypeLists?.point, overlayTypeLists?.polygon]) {
    for (const t of list || []) {
      if (t?.value) kindCatalog[t.value] = { category: t.category, label: t.label };
    }
  }
  const graphicsCategoryOrder: string[] = overlayTypeLists?.lineCategoryOrder || [];
  const graphicsByCategory = new Map<string, string[]>();
  for (const k of graphicsKinds) {
    const cat = kindCatalog[k]?.category || "Other";
    if (!graphicsByCategory.has(cat)) graphicsByCategory.set(cat, []);
    (graphicsByCategory.get(cat) as string[]).push(k);
  }
  const graphicsGroups = [...graphicsByCategory.keys()]
    .sort((a, b) => {
      const ia = graphicsCategoryOrder.indexOf(a);
      const ib = graphicsCategoryOrder.indexOf(b);
      const ra = ia === -1 ? (a === "Other" ? 10000 : 999) : ia;
      const rb = ib === -1 ? (b === "Other" ? 10000 : 999) : ib;
      return ra - rb || a.localeCompare(b);
    })
    .map((cat) => ({ category: cat, kinds: graphicsByCategory.get(cat) as string[] }));
  const hasUnits = (census.kinds.get("mil_unit") || 0) > 0;
  const hasFans = (census.kinds.get("range_fan") || 0) > 0;
  const derivedUnitCount =
    census.kindsBySource.get("reference_walk")?.get("mil_unit") || 0;
  const factionEntries = [...census.factions.entries()].filter(([, v]) => v.units > 0);

  // Seed the roll-up tier for every present faction to the finest stop
  // (PLT). The slider RENDERS PLT as its default, and the roll-up is a
  // clustering granularity — with no entry the transform would not run
  // at all, so aggregate parents would paint alongside their painted
  // subordinates while the slider claims finest granularity. Explicit
  // seeding keeps display and behavior identical.
  React.useEffect(() => {
    if (!factionEntries.length) return;
    setRollupEchelonByFaction((prev: Record<string, string>) => {
      const next = { ...prev };
      let changed = false;
      for (const [aff] of factionEntries) {
        if (!next[aff]) {
          next[aff] = ROLLUP_STOPS[0].value;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [factionEntries.map(([aff]) => aff).join('|')]);

  // Product-layer rows derive from the census: EVERY non-base source
  // token present on the map gets a row — a claim-set with no row is
  // unreachable content (the pre-refactor panel had exactly that bug
  // with opord and GRINTSUM). SITEMP tokens render as the per-COA
  // radio group below; compound "<src>:<coa>" tokens ride their bare
  // source's row through the filter's compound gate. Source tokens ARE
  // product names (PRODUCT_SCHEMAS keys), so they're analyst-facing as
  // labels; the display-name overrides live in PRODUCT_LABELS
  // ("Threat Template" is the doctrinal name for the Threat Overlay
  // product's graphic). Refresh buttons render only for products with
  // a refire endpoint.
  const productRows: Array<{ token: string; label: string; productType: string }> =
    [...census.layers.keys()]
      .filter(
        (t) =>
          !(BASE_SOURCES as string[]).includes(t) &&
          !t.startsWith("SITEMP") &&
          !SIGNAL_LAYER_TOKENS.has(t) &&
          !t.includes(":"))
      .sort()
      .map((token) => ({
        token,
        label: PRODUCT_LABELS[token] || token,
        productType: token,
      }));
  const hasSitemp = [...census.layers.keys()].some((k) => k === "SITEMP" || k.startsWith("SITEMP:"));

  // ── Expansion state.
  const [collapsed, setCollapsed] = useState(true);
  const [unitsOpen, setUnitsOpen] = useState(false);
  const [graphicsOpen, setGraphicsOpen] = useState(false);
  const [coasOpen, setCoasOpen] = useState(false);
  const [factionOpen, setFactionOpen] = useState<Set<string>>(new Set());

  const hasAnything =
    hasUnits || graphicsKinds.length > 0 || productRows.length > 0 ||
    hasSitemp || signalPresence.klieg || signalPresence.osir;
  if (!hasAnything) return null;

  if (collapsed) {
    return (
      <button
        data-testid="ops-map-sidebar-collapsed"
        type="button"
        onClick={() => setCollapsed(false)}
        title="Show tactical overlays"
        aria-label="Show tactical overlays"
        style={{
          position: "absolute", top: 12, left: 12, zIndex: 1100,
          width: 34, height: 34,
          background: "rgba(17,19,26,0.88)",
          backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)",
          color: "#e6e6f0", border: "1px solid rgba(58,58,82,0.6)",
          borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
          cursor: "pointer", fontSize: 16,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        <SubframeCore.Icon name="FeatherLayers" />
      </button>
    );
  }

  const rowStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 8, padding: "8px 14px",
    borderBottom: "1px solid #1d1f2a",
  };
  const pill = (state: "idle" | "generating") => (
    <span
      style={{
        background: state === "generating" ? "#1f6feb" : "#3a3a52",
        color: "#fff", fontSize: 10, textTransform: "uppercase",
        padding: "2px 6px", borderRadius: 8, letterSpacing: 0.3,
        minWidth: 56, textAlign: "center",
      }}
    >
      {state}
    </span>
  );
  const refireButton = (productType: string, label: string, state: "idle" | "generating") => (
    <button
      type="button"
      onClick={() => onRefire(productType)}
      disabled={state === "generating"}
      title={state === "generating" ? `${label} already firing` : `Refresh ${label}`}
      aria-label={`Refresh ${label}`}
      style={{
        border: "1px solid #3a3a52",
        background: state === "generating" ? "#16181f" : "#1a1a2e",
        color: state === "generating" ? "#6a6a82" : "#e6e6f0",
        borderRadius: 3, padding: "2px 8px",
        cursor: state === "generating" ? "not-allowed" : "pointer",
        fontSize: 12, opacity: state === "generating" ? 0.6 : 1,
      }}
    >
      Refresh
    </button>
  );

  return (
    <div
      data-testid="ops-map-sidebar"
      style={{
        position: "absolute", top: 12, left: 12, zIndex: 1100, width: 250,
        maxHeight: "calc(100% - 24px)",
        background: "rgba(17,19,26,0.88)",
        backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)",
        color: "#e6e6f0", border: "1px solid rgba(58,58,82,0.6)",
        borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
        display: "flex", flexDirection: "column", fontSize: 12,
        overflowY: "auto",
      }}
    >
      <div
        style={{
          padding: "8px 12px", borderBottom: "1px solid rgba(42,42,58,0.6)",
          fontWeight: 600, letterSpacing: 0.3, fontSize: 11,
          textTransform: "uppercase", color: "#a0a0b8",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}
      >
        <span>Tactical Overlays</span>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          title="Collapse"
          aria-label="Collapse tactical overlays"
          style={chevronButtonStyle}
        >
          <SubframeCore.Icon name="FeatherChevronLeft" />
        </button>
      </div>

      {/* ════ LEGEND ════ */}
      {hasUnits && (
        <>
          <div style={rowStyle}>
            <button
              type="button"
              onClick={() => setUnitsOpen((v) => !v)}
              title={unitsOpen ? "Collapse Units" : "Expand Units"}
              aria-expanded={unitsOpen}
              style={chevronButtonStyle}
            >
              <SubframeCore.Icon name={unitsOpen ? "FeatherChevronDown" : "FeatherChevronRight"} />
            </button>
            <input
              type="checkbox"
              data-testid="legend-units"
              checked={!isHidden(kindToken("mil_unit"))}
              onChange={() => toggleType([kindToken("mil_unit")])}
              aria-label="Show units"
              style={{ cursor: "pointer" }}
            />
            <span style={{ flex: 1, color: isHidden(kindToken("mil_unit")) ? "#8a8aa0" : "#e6e6f0" }}>
              Units
            </span>
          </div>
          {unitsOpen && (
            <div
              data-testid="sub-toggles-units"
              style={{
                paddingLeft: 28, paddingRight: 14, paddingBottom: 8,
                borderBottom: "1px solid #1d1f2a", fontSize: 11, color: "#a0a0b8",
              }}
            >
              {factionEntries.length > 0 && (() => {
                {/* Master over every present faction's unit_names token;
                    per-faction chips live inside each faction section. */}
                const nameTokens = factionEntries.map(([aff]) => unitNamesToken(aff));
                const anyShown = nameTokens.some((t) => !isHidden(t));
                return (
                  <label
                    data-testid="ops-map-unit-names-row"
                    style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6, cursor: "pointer" }}
                  >
                    <input
                      type="checkbox"
                      checked={anyShown}
                      onChange={() => toggleType(nameTokens)}
                      aria-label="Show unit names"
                      style={{ cursor: "pointer", margin: 0 }}
                    />
                    <span style={{ color: anyShown ? "#c0c0d0" : "#666" }}>Unit Names</span>
                  </label>
                );
              })()}
              {hasFans && (
                <label style={{ ...chipStyle(isHidden(kindToken("range_fan"))), marginTop: 6 }}>
                  <input
                    type="checkbox"
                    checked={!isHidden(kindToken("range_fan"))}
                    onChange={() => toggleType([kindToken("range_fan")])}
                    style={{ cursor: "pointer", margin: 0 }}
                  />
                  <span style={{ color: isHidden(kindToken("range_fan")) ? "#666" : "#c0c0d0" }}>
                    Range fans
                  </span>
                </label>
              )}
              {derivedUnitCount > 0 && (() => {
                {/* The reference walk's doctrine projection — base map
                    content (default ON), toggled as a TYPE so the layer
                    gate never demotes doctrine to a product overlay. */}
                const dToken = typeToken("source", "reference_walk");
                const dHidden = isHidden(dToken);
                return (
                  <label
                    data-testid="ops-map-doctrine-row"
                    style={{ ...chipStyle(dHidden), marginTop: 6 }}
                    title="Templated doctrinal subordinates projected from the reference catalog (dashed anticipated frames)"
                  >
                    <input
                      type="checkbox"
                      checked={!dHidden}
                      onChange={() => toggleType([dToken])}
                      style={{ cursor: "pointer", margin: 0 }}
                    />
                    <span style={{ color: dHidden ? "#666" : "#c0c0d0" }}>
                      Doctrinal subordinates ({derivedUnitCount})
                    </span>
                  </label>
                );
              })()}
              {factionEntries.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <div style={dimHeaderStyle}>Faction</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {factionEntries.map(([aff, bucket]) => {
                      const fToken = factionToken(aff);
                      const fHidden = isHidden(fToken);
                      const tier = rollupEchelonByFaction?.[aff] ?? ROLLUP_STOPS[0].value;
                      const tierIndex = Math.max(0, ROLLUP_STOPS.findIndex((s) => s.value === tier));
                      const open = factionOpen.has(aff);
                      const categories = [...bucket.categories.keys()].sort();
                      const subkinds = [...bucket.subkinds.keys()].sort();
                      return (
                        <React.Fragment key={aff}>
                          <div data-testid={`faction-row-${aff}`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <button
                              type="button"
                              onClick={() =>
                                setFactionOpen((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(aff)) next.delete(aff);
                                  else next.add(aff);
                                  return next;
                                })
                              }
                              title={open ? `Collapse ${aff}` : `Expand ${aff}`}
                              aria-expanded={open}
                              style={chevronButtonStyle}
                            >
                              <SubframeCore.Icon name={open ? "FeatherChevronDown" : "FeatherChevronRight"} />
                            </button>
                            <label style={{ ...chipStyle(fHidden), minWidth: 74 }}>
                              <input
                                type="checkbox"
                                checked={!fHidden}
                                onChange={() => toggleType([fToken])}
                                style={{ cursor: "pointer", margin: 0 }}
                              />
                              <span style={{ color: fHidden ? "#666" : "#c0c0d0" }}>
                                {aff === "Friend" ? "Friendly" : aff}
                              </span>
                            </label>
                            <input
                              type="range"
                              className="echelon-slider"
                              min={0}
                              max={ROLLUP_STOPS.length - 1}
                              step={1}
                              value={tierIndex}
                              title={`${aff} units below ${ROLLUP_STOPS[tierIndex].label} roll up into their parent formation`}
                              aria-label={`${aff} echelon roll-up`}
                              onChange={(e) =>
                                setRollupEchelonByFaction((prev: Record<string, string>) => ({
                                  ...prev,
                                  [aff]: ROLLUP_STOPS[Number(e.target.value)].value,
                                }))
                              }
                              style={{ flex: 1, minWidth: 0 }}
                            />
                            <span style={{ minWidth: 28, textAlign: "right", fontWeight: 700, color: "#9db2d6" }}>
                              {ROLLUP_STOPS[tierIndex].label}
                            </span>
                          </div>
                          {open && (
                            <div data-testid={`faction-${aff}-names`} style={{ paddingLeft: 18, marginTop: 4 }}>
                              <label style={chipStyle(isHidden(unitNamesToken(aff)))}>
                                <input
                                  type="checkbox"
                                  checked={!isHidden(unitNamesToken(aff))}
                                  onChange={() => toggleType([unitNamesToken(aff)])}
                                  style={{ cursor: "pointer", margin: 0 }}
                                />
                                <span style={{ color: isHidden(unitNamesToken(aff)) ? "#666" : "#c0c0d0" }}>
                                  Names
                                </span>
                              </label>
                            </div>
                          )}
                          {open && categories.length > 0 && (
                            <div data-testid={`faction-${aff}-category`} style={{ paddingLeft: 18 }}>
                              <div style={dimHeaderStyle}>Category</div>
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                {categories.map((cat) => {
                                  const token = factionDimToken(aff, "category", cat);
                                  const off = isHidden(token);
                                  return (
                                    <label key={cat} style={chipStyle(off)}>
                                      <input
                                        type="checkbox"
                                        checked={!off}
                                        onChange={() => toggleType([token])}
                                        style={{ cursor: "pointer", margin: 0 }}
                                      />
                                      <span style={{ color: off ? "#666" : "#c0c0d0" }}>{categoryLabel(cat)}</span>
                                    </label>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                          {open && subkinds.length > 0 && (
                            <div data-testid={`faction-${aff}-subkind`} style={{ paddingLeft: 18 }}>
                              <div style={dimHeaderStyle}>Range fan classes</div>
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                {subkinds.map((sub) => {
                                  const token = factionDimToken(aff, "subkind", sub);
                                  const off = isHidden(token);
                                  return (
                                    <label key={sub} style={chipStyle(off)}>
                                      <input
                                        type="checkbox"
                                        checked={!off}
                                        onChange={() => toggleType([token])}
                                        style={{ cursor: "pointer", margin: 0 }}
                                      />
                                      <span style={{ color: off ? "#666" : "#c0c0d0" }}>{subkindLabel(sub)}</span>
                                    </label>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {graphicsKinds.length > 0 && (
        <>
          <div style={rowStyle}>
            <button
              type="button"
              onClick={() => setGraphicsOpen((v) => !v)}
              title={graphicsOpen ? "Collapse Graphics" : "Expand Graphics"}
              aria-expanded={graphicsOpen}
              style={chevronButtonStyle}
            >
              <SubframeCore.Icon name={graphicsOpen ? "FeatherChevronDown" : "FeatherChevronRight"} />
            </button>
            <input
              type="checkbox"
              data-testid="legend-graphics"
              checked={graphicsKinds.some((k) => !isHidden(kindToken(k)))}
              onChange={() => toggleType(graphicsKinds.map(kindToken))}
              aria-label="Show graphics"
              style={{ cursor: "pointer" }}
            />
            <span
              style={{
                flex: 1,
                color: graphicsKinds.every((k) => isHidden(kindToken(k))) ? "#8a8aa0" : "#e6e6f0",
              }}
            >
              Graphics
            </span>
          </div>
          {graphicsOpen && (
            <div
              data-testid="sub-toggles-graphics"
              style={{
                paddingLeft: 28, paddingRight: 14, paddingBottom: 8,
                borderBottom: "1px solid #1d1f2a", fontSize: 11, color: "#a0a0b8",
              }}
            >
              {graphicsGroups.map(({ category, kinds }) => (
                <div key={category} style={{ marginTop: 6 }} data-testid={`graphics-group-${category}`}>
                  <label
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      cursor: "pointer", ...dimHeaderStyle,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={kinds.some((k) => !isHidden(kindToken(k)))}
                      onChange={() => toggleType(kinds.map(kindToken))}
                      aria-label={`Show ${category} graphics`}
                      style={{ cursor: "pointer", margin: 0 }}
                    />
                    {category}
                  </label>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {kinds.map((k) => {
                      const token = kindToken(k);
                      const off = isHidden(token);
                      return (
                        <label key={k} style={chipStyle(off)}>
                          <input
                            type="checkbox"
                            checked={!off}
                            onChange={() => toggleType([token])}
                            style={{ cursor: "pointer", margin: 0 }}
                          />
                          <span style={{ color: off ? "#666" : "#c0c0d0" }}>
                            {kindCatalog[k]?.label || kindLabel(k)}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ════ PRODUCT LAYERS ════ */}
      {(productRows.length > 0 || hasSitemp || signalPresence.klieg || signalPresence.osir) && (
        <div style={sectionHeaderStyle}>Product overlays</div>
      )}
      {signalPresence.klieg && (
        <div style={rowStyle}>
          <input
            type="checkbox"
            checked={layerOn("live_klieglight")}
            onChange={() => setLayer("live_klieglight", !layerOn("live_klieglight"))}
            aria-label="Show Live KLIEGLIGHTs"
            style={{ cursor: "pointer" }}
          />
          <span style={{ flex: 1, color: layerOn("live_klieglight") ? "#e6e6f0" : "#8a8aa0" }}>
            Live KLIEGLIGHTs
          </span>
        </div>
      )}
      {signalPresence.osir && (
        <div style={rowStyle}>
          <input
            type="checkbox"
            checked={layerOn("live_osir")}
            onChange={() => setLayer("live_osir", !layerOn("live_osir"))}
            aria-label="Show Live OSIRs"
            style={{ cursor: "pointer" }}
          />
          <span style={{ flex: 1, color: layerOn("live_osir") ? "#e6e6f0" : "#8a8aa0" }}>
            Live OSIRs
          </span>
        </div>
      )}
      {productRows.map((row) => {
        const state = stateFor(row.productType);
        return (
          <div key={row.token} style={rowStyle}>
            <input
              type="checkbox"
              checked={layerOn(row.token)}
              onChange={() => setLayer(row.token, !layerOn(row.token))}
              aria-label={`Show ${row.label}`}
              style={{ cursor: "pointer" }}
            />
            <span style={{ flex: 1, color: layerOn(row.token) ? "#e6e6f0" : "#8a8aa0" }}>
              {row.label}
            </span>
            {/* A Refresh button with no endpoint behind it is a lie to
                the analyst — render it only where a refire exists. */}
            {REFIRE_ENDPOINT_FOR[row.productType] && refireButton(row.productType, row.label, state)}
            {pill(state)}
          </div>
        );
      })}
      {hasSitemp && (
        <>
          <div style={rowStyle}>
            <button
              type="button"
              onClick={() => setCoasOpen((v) => !v)}
              title={coasOpen ? "Collapse Threat COAs" : "Expand Threat COAs"}
              aria-expanded={coasOpen}
              style={chevronButtonStyle}
            >
              <SubframeCore.Icon name={coasOpen ? "FeatherChevronDown" : "FeatherChevronRight"} />
            </button>
            <span style={{ flex: 1 }}>Threat COAs</span>
            {refireButton("Threat COAs", "Threat COAs", chainStateFor())}
            {pill(chainStateFor())}
          </div>
          {coasOpen &&
            COA_IDS.map((coaId) => {
              const token = `SITEMP:${coaId}`;
              const on = layerOn(token);
              const state = stateFor("SITEMP", coaId);
              return (
                <div key={coaId} style={{ ...rowStyle, paddingLeft: 42 }}>
                  <input
                    type="radio"
                    checked={on}
                    // Controlled radio; onClick fires on the already-
                    // selected radio too so clicking the active COA
                    // clears it — "one or none".
                    onChange={() => {}}
                    onClick={() => setLayer(token, !on, "SITEMP:")}
                    aria-label={`Show Situation Template (${coaId})`}
                    style={{ cursor: "pointer" }}
                  />
                  <span style={{ flex: 1, color: on ? "#e6e6f0" : "#8a8aa0" }}>
                    Situation Template ({coaId})
                  </span>
                  {pill(state)}
                </div>
              );
            })}
        </>
      )}
    </div>
  );
}
