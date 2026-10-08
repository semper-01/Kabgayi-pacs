import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Development-only reverse proxy so the browser talks to Django via a
// same-origin `/api` prefix (no CORS and no direct Orthanc access).
// Production routing is handled by nginx (unchanged in Phase 7).
const devApiTarget = process.env.VITE_DEV_PROXY_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: devApiTarget,
        changeOrigin: true,
      },
    },
  },
});