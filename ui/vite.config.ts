import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The production bundle is served by the FastAPI backend at "/" (StaticFiles, html=True).
// Relative base + HashRouter means deep links work from a static mount.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
  // Hook tests opt into jsdom; pure logic tests use Node.
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
