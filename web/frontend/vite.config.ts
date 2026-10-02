import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are written into the Python package so `redsi serve` can serve them.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../../src/redsi/server/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", ws: true },
    },
  },
});
