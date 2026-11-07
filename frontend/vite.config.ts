import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api goes to FastAPI on :8000. In production FastAPI serves frontend/dist itself.
export default defineConfig({
  plugins: [react()],
  // The Pyodide worker is an ES module (it imports pyodide.mjs from the CDN).
  worker: { format: "es" },
  server: {
    port: 5173,
    proxy: { "/api": "https://data-preprocessing-gui.onrender.com" },
  },
});
