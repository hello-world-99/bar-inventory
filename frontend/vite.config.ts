import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: true,
    // Docker bind mounts on Windows do not deliver file events; poll instead.
    watch: { usePolling: true },
    proxy: { "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8000" },
  },
});
