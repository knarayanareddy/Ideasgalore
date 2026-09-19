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
  // Pin the optimizer's entry points so a cold dev server resolves them in ONE epoch. Without
  // this, Vite discovers `react-dom/client` and `lucide-react` only after the first requests,
  // re-optimizes, and can keep serving a transformed `main.jsx` that points at the previous
  // epoch's copy of react-dom — two React instances in the browser, which renders a blank page
  // whose only symptom is an "Invalid hook call" in the console. The list is exactly the bare
  // specifiers under src/ (react, react-dom/client, lucide-react); nothing else may be added
  // without it being a real import, or the optimizer fails the build.
  optimizeDeps: { include: ['react', 'react-dom/client', 'lucide-react'] },
  build: { target: 'es2020', chunkSizeWarningLimit: 700 },
})
