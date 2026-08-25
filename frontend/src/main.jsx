// FIRST import: wraps requestAnimationFrame with a timer backstop before
// MapLibre captures it. Without this, hidden/backgrounded/automation tabs
// (where Chromium suspends RAF) never finish the deferred style load and
// the map stays black forever. See utils/rafBackstop.js.
import './geo-agent/utils/rafBackstop'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import './geo-agent/theme.css'
import './geo-agent/index.css'
import { initThemeSync } from './geo-agent/utils/theme'

// The shell owns the theme; embedded surfaces mirror it (both ways:
// ?theme= on load and geoagent.theme on toggle).
initThemeSync()

// ROUTE-LEVEL CODE SPLITTING. The map routes pull MapLibre, milsymbol,
// turf and the doctrinal paint layer — megabytes the REFERENCE routes
// (catalog, chat) have no use for. Eagerly importing them made the
// equipment-catalog iframe download the whole map stack before it could
// render a table, which is most of that iframe's load time. Each route
// now fetches only its own chunk.
const OperationsMapHeadless = lazy(() => import('./pages/OperationsMapHeadless'))
const OperationsMap = lazy(() => import('./pages/OperationsMap'))
const EquipmentCatalog = lazy(() => import('./pages/EquipmentCatalog'))

// Router for the geo-agent frontend. Served under /geo-app/ by the
// geo-agent container's StaticFiles mount. Every route here is meant
// to be embedded as an iframe by pytho-app (or driven directly by
// Playwright for the /headless render path).
//
// Routes:
//   /headless           — Playwright screenshot target (no chrome).
//                         Frontend surface behind /api/v1/render.
//   /operations-map     — analyst-facing map iframe. Full sidebar
//                         toggles + tactical overlays + right-click
//                         generate menu; parent frame owns the top
//                         nav + chat rail chrome.
//   /equipment-catalog  — standalone WEG catalog reference iframe
//                         (read-only; ?weg_id= deep-links a sheet).

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename="/geo-app">
      <Suspense fallback={null}>
      <Routes>
        <Route path="/headless" element={<OperationsMapHeadless />} />
        <Route path="/operations-map" element={<OperationsMap />} />
        <Route path="/equipment-catalog" element={<EquipmentCatalog />} />
        <Route path="*" element={<Navigate to="/operations-map" replace />} />
      </Routes>
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>,
)
