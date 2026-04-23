import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    // In dev, proxy API calls to the backend so we don't hit CORS.
    // The backend already enables permissive CORS, so this is just a nicety.
    proxy: {
      "/api": {
        target: "http://localhost:8765",
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
