// STANDALONE equipment-catalog iframe target (her ruling 2026-07-28:
// the WEG catalog is a useful reference in its own right). Served at
// /geo-app/equipment-catalog and embedded by any consumer exactly like
// /operations-map — through the consumer's existing /geo-app proxy,
// zero new wiring. Pure REFERENCE surface: no map, no project, no
// GeoAgentProvider, no range overrides (those are per-map config and
// only exist on the in-map mount); reads only.
//
// Query params:
//   weg_id — optional deep link straight to one system's sheet.
import { useMemo } from "react";
import { CatalogEditor } from "../geo-agent/components/graph/CatalogEditor";

export default function EquipmentCatalog() {
  const focusWegId = useMemo(
    () => new URLSearchParams(window.location.search).get("weg_id") || "",
    [],
  );
  return <CatalogEditor focusWegId={focusWegId} />;
}
