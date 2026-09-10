import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    strictPort: true,
    // Bind all interfaces rather than IPv6 localhost only. CashU is mobile-first
    // and the layout genuinely needs checking on a real handset, which means the
    // dev server has to be reachable from the phone on the same network.
    host: true,
    // Proxy /v1 to the Flask API in development so the browser sees one origin.
    // This keeps cookies and CORS out of the way locally; in production nginx
    // serves the bundle and the API is reached by its own URL.
    //
    // The target is 127.0.0.1 rather than "localhost" deliberately. On Windows,
    // Node resolves "localhost" to ::1 (IPv6) first, while Flask's dev server
    // binds 0.0.0.0 (IPv4 only) - so every proxied request fails to connect and
    // surfaces as an opaque 500. Naming the IPv4 address avoids that entirely.
    proxy: {
      '/v1': {
        target: 'http://127.0.0.1:5050',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:5050',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
