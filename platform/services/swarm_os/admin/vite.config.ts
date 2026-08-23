import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxy = {
  "/api": { target: "http://127.0.0.1:8100", changeOrigin: true },
  "/inspection": { target: "http://127.0.0.1:8100", changeOrigin: true },
  "/docs": { target: "http://127.0.0.1:8100", changeOrigin: true },
  "/status": { target: "http://127.0.0.1:8100", changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: apiProxy,
    // ngrok y otros túneles cambian de host en cada sesión
    allowedHosts: true,
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
    proxy: apiProxy,
    allowedHosts: true,
  },
});
