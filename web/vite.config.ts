import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // JARVIS_API_URL lets a second dev copy talk to a server on another port.
      '/api': process.env.JARVIS_API_URL ?? 'http://127.0.0.1:8000',
    },
  },
  build: {
    chunkSizeWarningLimit: 1800,
  },
});
