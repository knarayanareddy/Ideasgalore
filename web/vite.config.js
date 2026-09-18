import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Static-first: relative base so the build works on github.io/<repo>/ subpaths.
// The dev server binds 0.0.0.0 and accepts any host so the sandbox preview and
// Codespace-style proxies both work without config.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
  },
  build: { target: 'es2020', chunkSizeWarningLimit: 700 },
})
