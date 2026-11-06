import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api goes to FastAPI on :8000. In production FastAPI serves frontend/dist itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
