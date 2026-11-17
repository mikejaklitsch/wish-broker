import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the Python server runs on :8000 and Vite forwards /api to it.
export default defineConfig({
  plugins: [react()],
  // Polling: file-change events don't reach WSL from Windows drives, so without it edits go unnoticed.
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' }, watch: { usePolling: true, interval: 300 } },
});
