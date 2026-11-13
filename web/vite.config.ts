import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the page is served by Vite and every /api call is passed to the Python server on port 8000.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } } },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
});
