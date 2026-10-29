import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Tailwind v4 is a Vite plugin: there is no tailwind.config.js and no PostCSS
// step. Theme tokens are declared in src/index.css with @theme.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // tsconfig paths are type-checking only; the bundler needs its own alias.
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    // Dev only. In production Flask serves dist/ itself, so the SPA and the API
    // share an origin and no proxy (or CORS) is involved.
    proxy: {
      '/api': { target: 'http://localhost:5000', changeOrigin: true },
      '/health': { target: 'http://localhost:5000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
