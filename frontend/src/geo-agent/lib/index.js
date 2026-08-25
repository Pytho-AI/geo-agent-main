/**
 * Geo-Agent Library Entry Point
 * 
 * A React component library for geo-spatial intelligence visualization
 * with military symbology support (MIL-STD-2525D)
 * 
 * @example
 * import { GeoAgentProvider, GeoAgentMap, Sidebar } from 'geo-agent';
 * 
 * function App() {
 *   return (
 *     <GeoAgentProvider apiUrl="/api/v1" mapId="00000000-0000-0000-0000-000000000001">
 *       <Sidebar />
 *       <GeoAgentMap />
 *     </GeoAgentProvider>
 *   );
 * }
 */

// Context Provider
export { GeoAgentProvider, useGeoAgent, GeoAgentContext } from '../GeoAgentProvider'

// Main Components
export { GeoAgentMap } from '../components/GeoAgentMap'
export { Sidebar } from '../components/Sidebar'
export { MapControls } from '../components/MapControls'
export { SymbolPicker } from '../components/SymbolPicker'
export { EditPanel } from '../components/EditPanel'
export { CreatePanel } from '../components/CreatePanel'
export { OverlayToolbar } from '../components/OverlayToolbar'
export { OverlayCreatePanel, OverlayEditPanel } from '../components/OverlayPanel'
export { StatusBar } from '../components/StatusBar'
export { 
  EditModeBanner, 
  PlacementModeBanner, 
  OverlayDrawModeBanner,
  GeometryEditModeBanner,
  AllBanners 
} from '../components/Banners'

// Hooks
export { useGeoAgent as useGeoAgentContext } from '../hooks/useGeoAgent'
export { useMapInstance } from '../hooks/useMapInstance'
export { useEntities } from '../hooks/useEntities'
export { useOverlays } from '../hooks/useOverlays'

// Utilities - Symbol rendering
export { 
  createMilsymbolPreview,
  createMilSymbol,
  createTacticalGraphic,
  createUnitIcon,
  isMilSymRendererReady,
  getMilStdIconRenderer
} from '../utils/symbols'

// Utilities - SIDC generation
export {
  SIDC_AFFILIATION,
  SIDC_ECHELON,
  SIDC_STATUS,
  SIDC_UNIT_TYPE,
  generateMilUnitSidc,
  updateSidcAffiliation
} from '../utils/sidc'

// Note: Symbol search is now handled by backend API
// Use GeoAgentProvider's findBestSymbolMatch() and searchSymbols()

export { createApiClient, defaultApiClient } from '../utils/api'

export {
  MAP_STYLE,
  DEFAULT_CENTER,
  DEFAULT_ZOOM,
  DRAW_STYLES,
  AFFILIATION_COLORS,
  AFFILIATION_POPUP_COLORS
} from '../utils/mapStyles'

// Note: Overlay types are now loaded from the backend via GeoAgentProvider.appConfig
// Access via: const { appConfig } = useGeoAgent()
// appConfig.overlayTypes contains { line: [...], polygon: [...], point: [...] }
// appConfig.overlayStyles contains styling info

// Re-export styles (consumers need to import the CSS)
// Usage: import 'geo-agent/styles.css' or import from the index.css directly
