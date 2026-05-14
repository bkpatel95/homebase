import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// VITE_API_PROXY_TARGET lets docker-compose.dev.yml point the dev server at
// http://backend:8000 instead of localhost. Default keeps the local-uvicorn
// workflow (`npm run dev` after `uvicorn ... --port 8096`) working unchanged.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8096';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsInlineLimit: 0,
  },
});
