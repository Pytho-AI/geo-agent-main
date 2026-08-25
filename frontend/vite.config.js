import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// The geo-agent frontend is served by the geo-agent container's FastAPI
// (StaticFiles mount) OR its bundled nginx, and is embedded in pytho-app
// as an iframe. In dev, we proxy /api/v1 to the local geo-agent backend
// and /api/* (non-v1) to a pytho-app docker-api dev instance so cross-service REST
// calls (products/records, products/generate, etc.) still work when
// running the frontend standalone via `pnpm dev`.
export default defineConfig({
  base: '/geo-app/',
  server: {
    port: 5174,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:9845',
        changeOrigin: true,
        secure: false,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/ws': {
        target: 'ws://localhost:9845',
        ws: true,
        changeOrigin: true,
        secure: false,
      },
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      // Alias pytho-app's proprietary @subframe/core package to a
      // minimal local stub (just the SubframeCore.Icon symbol) so the
      // moved OperationsMap.tsx compiles inside geo-agent without
      // pulling in the full Subframe UI kit.
      '@subframe/core': path.resolve(__dirname, 'src/subframe/core.jsx'),
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1000,
  },
})
