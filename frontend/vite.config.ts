/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the FastAPI backend so the frontend can call same-origin
// paths (`/query`, `/review`, `/dashboard/*`) without CORS gymnastics.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/query": "http://localhost:8000",
      "/extract": "http://localhost:8000",
      "/review": "http://localhost:8000",
      "/dashboard": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
