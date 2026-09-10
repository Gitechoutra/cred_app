import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // Proxy /v1 to the Flask API in development so the browser sees one origin.
    // This keeps cookies and CORS out of the way locally; in production nginx
    // serves the bundle and the API is reached by its own URL.
    proxy: {
      '/v1': {
        target: 'http://localhost:5050',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:5050',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
