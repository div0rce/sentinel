/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the FastAPI backend so the frontend can call same-origin
// paths (`/query`, `/review`, `/dashboard/*`) without CORS gymnastics.
//
// Build chunking (issue #10): the Dashboard route is React.lazy-loaded in
// `src/App.tsx`, so its synchronous deps stay out of the initial bundle. We
// also pin the Recharts + d3 graph into a dedicated vendor chunk so visitors
// who do open the Dashboard get a long-cacheable file separate from app code.
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
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id: string): string | undefined => {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("recharts") || id.includes("/d3-") || id.includes("\\d3-")) {
            return "vendor-recharts";
          }
          if (id.includes("react-router")) return "vendor-router";
          if (id.includes("/react/") || id.includes("/react-dom/")) {
            return "vendor-react";
          }
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
